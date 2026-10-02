"""
Real-world finding-quality check on a live site (default: flipkart.com).

    python tests/flipkart_quality_compare.py [--url URL] [--provider gemini|groq|mock] [--fresh]

It collects ONE evidence bundle and makes at most ONE AI request: the provider's raw response is cached in
runs/quality/<host>.json, so the comparison can be repeated for free. The same AI candidates are then verified
twice -- with the verification rules as they were BEFORE this phase (the legacy shim below, a copy of the old
branch) and with the current rules -- so the only variable is the verification logic.

Reported per side: candidates, confirmed / likely / uncertain, rejected, and how many of the rejected ones are
the "silly" kinds (blank space, cosmetic-only, duplicates of deterministic findings).
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from aura.agents.orchestrator import AURAOrchestrator  # noqa: E402
from aura.analyzers.accessibility_analyzer import AXE_LOCAL_PATH  # noqa: E402
from aura.analyzers.dom_analyzer import DOMAnalyzer  # noqa: E402
from aura.agent.providers import get_ai_provider  # noqa: E402
from aura.evidence.bundle import EvidenceBundle  # noqa: E402
from aura.models.findings import VerificationStatus  # noqa: E402
from aura.verification.rules import VerificationRulesEngine  # noqa: E402
from aura.agent.analyzer_agent import normalize_rule_type  # noqa: E402
from aura.verification.evidence import INTERACTION_RULES  # noqa: E402

CACHE_DIR = ROOT / "runs" / "quality"
BLANKISH = re.compile(r"\b(blank|empty|whitespace|white space|unused space|large gap|dead space)\b", re.I)
COSMETIC = re.compile(r"\b(unusual|unconventional|odd|strange|aesthetic|not modern|outdated)\b", re.I)


def legacy_status(self, candidate, flags, matching_elements, contradiction_reason, dom_summary=None,
                  accessibility_violations=None):
    """The pre-Phase-3 rule: UI/UX/navigation claims passed on element existence plus AI confidence."""
    if contradiction_reason:
        return VerificationStatus.REJECTED, 0.10, contradiction_reason
    cand_rule = getattr(candidate, "normalized_rule", None) or normalize_rule_type(candidate.rule_type or candidate.title)
    cat = candidate.category.upper()
    score = candidate.confidence + 0.10 * sum(bool(flags.get(k)) for k in ("dom", "accessibility", "runtime", "interaction"))
    clamped = round(max(0.0, min(1.0, score)), 2)
    if cat == "ACCESSIBILITY" or cand_rule in ("image_alt", "image_alt_missing", "color_contrast", "unlabelled_button", "missing_label"):
        return (VerificationStatus.CONFIRMED, max(0.95, clamped), None) if (flags.get("accessibility") or flags.get("dom")) \
            else (VerificationStatus.UNCERTAIN, 0.45, "No axe-core WCAG violation or DOM accessibility defect observed")
    if cat == "RUNTIME" or cand_rule in ("console_error", "application_error", "network_failure"):
        return (VerificationStatus.CONFIRMED, max(0.95, clamped), None) if flags.get("runtime") \
            else (VerificationStatus.UNCERTAIN, 0.35, "No matching application console error or network 4xx/5xx recorded")
    if cat == "RESPONSIVENESS" or cand_rule in ("horizontal_overflow", "clipped_content", "overlapping_elements", "offscreen_control"):
        if flags.get("target_overflow") or flags.get("target_clipped") or flags.get("layout_overlap"):
            return VerificationStatus.CONFIRMED, max(0.95, clamped), None
        if flags.get("document_overflow") and cand_rule not in ("clipped_content", "overlapping_elements"):
            return VerificationStatus.LIKELY, 0.70, "Document overflows the viewport, but not measured on the claimed target"
        return VerificationStatus.UNCERTAIN, 0.45, "Responsive geometry problem not measured on the claimed target"
    if cat == "INTERACTION" or cand_rule in INTERACTION_RULES:
        if not flags.get("interaction"):
            return VerificationStatus.UNCERTAIN, 0.45, "Claimed control was not exercised by a target-specific interaction"
        if flags.get("interaction_error") or flags.get("interaction_no_effect"):
            return VerificationStatus.CONFIRMED, max(0.90, clamped), None
        return VerificationStatus.UNCERTAIN, 0.50, "Target was exercised and behaved normally"
    if cat == "NAVIGATION" or cand_rule in ("bad_navigation", "unclear_information_architecture"):
        if flags.get("placeholder_href") or flags.get("layout_overlap") or flags.get("interaction_no_effect") or flags.get("interaction_error"):
            return VerificationStatus.CONFIRMED, max(0.90, clamped), None
        if flags.get("dom"):
            return VerificationStatus.LIKELY, min(0.85, max(0.70, clamped)), "Target exists, but no specific navigation defect was measured"
        return VerificationStatus.UNCERTAIN, 0.50, "Target navigation link or route not confirmed"
    if flags.get("dom") and matching_elements:
        if matching_elements[0].get("visible", True):
            if candidate.confidence >= 0.70 or flags.get("accessibility") or flags.get("screenshot"):
                return VerificationStatus.CONFIRMED, min(1.0, max(0.85, clamped)), None
            return VerificationStatus.LIKELY, min(0.85, max(0.70, clamped)), None
        return VerificationStatus.LIKELY, 0.65, "Element present in DOM but currently invisible"
    target = str(candidate.affected_element or "").lower()
    if target in ("", "window", "body", "page", "none", "document"):
        return VerificationStatus.LIKELY, 0.75, None
    return VerificationStatus.UNCERTAIN, 0.45, "Affected element could not be verified in extracted DOM"


class RecordingProvider:
    """Wraps a provider and caches its raw response, so the comparison costs at most one AI request."""

    def __init__(self, inner, cache: Path, fresh: bool):
        self.inner, self.cache, self.fresh = inner, cache, fresh
        self.provider_key, self.model = inner.provider_key, getattr(inner, "model", "default")
        self.api_key = getattr(inner, "api_key", "")
        self.last_execution_metadata = {}
        self.used_cache = False

    def capabilities(self):
        return self.inner.capabilities() if hasattr(self.inner, "capabilities") else None

    def check_availability(self):
        return self.inner.check_availability()

    def test_connection(self):
        return self.inner.test_connection()

    def analyze_packet(self, packet):
        return self.analyze(packet.to_prompt(), packet.screenshot_base64, packet.screenshot_mime)

    def analyze(self, prompt, screenshot_base64=None, mime_type="image/png"):
        if self.cache.exists() and not self.fresh:
            self.used_cache = True
            return json.loads(self.cache.read_text(encoding="utf-8"))["raw"]
        raw = self.inner.analyze(prompt, screenshot_base64, mime_type)
        self.last_execution_metadata = getattr(self.inner, "last_execution_metadata", {})
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text(json.dumps({"provider": self.provider_key, "model": self.model, "raw": raw}), encoding="utf-8")
        return raw


def collect_bundle(url: str) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        dom = page.evaluate(f"({DOMAnalyzer.DOM_EXTRACTION_SCRIPT})({{collectFieldValues: false}})")
        page.evaluate(AXE_LOCAL_PATH.read_text(encoding="utf-8"))
        axe = page.evaluate("""async () => { const r = await axe.run(document, {resultTypes: ['violations']});
            return {available: true, version: axe.version, violations: r.violations.map(v => ({id: v.id, impact: v.impact,
            description: v.description, helpUrl: v.helpUrl, nodes: v.nodes.slice(0, 30).map(n => ({target: n.target}))}))}; }""")
        failures = page.evaluate("""() => performance.getEntriesByType('resource').filter(e => e.responseStatus >= 400)
            .map(e => ({url: e.name, status: e.responseStatus, method: 'GET'}))""")
        import base64
        shot = base64.b64encode(page.screenshot()).decode()
        title = page.title()
        browser.close()
    return {"source": "extension", "collector_version": "quality-compare/1", "url": url, "title": title,
            "viewport": {"width": 1440, "height": 900}, "dom": dom, "axe": axe,
            "telemetry": {"capture_scope": "post_load", "page_load_time_ms": 0, "console": [], "network": failures},
            "interactions": [], "screenshot_png_base64": shot, "captured_at": "now"}


def summarise(report, label):
    agg = report["aggregation"]
    ai = [f for f in agg.all_active_findings if getattr(f.source, "value", f.source) == "AI"]
    rejected = [f for f in agg.rejected_findings if getattr(f.source, "value", f.source) == "AI"]
    by = lambda st: sum(1 for f in ai if f.verification_status.value == st)
    silly = [f for f in rejected if BLANKISH.search(f"{f.title} {f.description}") or COSMETIC.search(f"{f.title} {f.description}")]
    dupes = [f for f in rejected if "axe-core" in (f.rejection_reason or "")]
    return {"label": label, "ai_candidates": len(ai) + len(rejected), "confirmed": by("CONFIRMED"), "likely": by("LIKELY"),
            "uncertain": by("UNCERTAIN"), "rejected": len(rejected), "rejected_blank_or_cosmetic": len(silly),
            "rejected_as_duplicate": len(dupes),
            "reasons": [f"{f.title[:60]} -> {(f.rejection_reason or '')[:90]}" for f in rejected]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://www.flipkart.com/")
    ap.add_argument("--provider", default="gemini")
    ap.add_argument("--fresh", action="store_true", help="make a new AI request instead of using the cached response")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    host = re.sub(r"\W+", "_", args.url)
    cache = CACHE_DIR / f"{host}_{args.provider}.json"
    bundle_cache = CACHE_DIR / f"{host}_bundle.json"
    if bundle_cache.exists() and not args.fresh:
        bundle_data = json.loads(bundle_cache.read_text(encoding="utf-8"))
        print(f"evidence: cached ({bundle_cache.name})")
    else:
        bundle_data = collect_bundle(args.url)
        bundle_cache.parent.mkdir(parents=True, exist_ok=True)
        bundle_cache.write_text(json.dumps(bundle_data), encoding="utf-8")
        print(f"evidence: collected from {args.url}")

    results = []
    for label, patched in (("BEFORE (pre-Phase-3 rules)", True), ("AFTER (materiality gate)", False)):
        provider = RecordingProvider(get_ai_provider(provider_type=args.provider), cache, args.fresh and not results)
        original = VerificationRulesEngine.evaluate_status_and_confidence
        if patched:
            VerificationRulesEngine.evaluate_status_and_confidence = legacy_status
        try:
            report = AURAOrchestrator(provider=provider).analyze_evidence(EvidenceBundle(**bundle_data))
        finally:
            VerificationRulesEngine.evaluate_status_and_confidence = original
        results.append(summarise(report, label))
        print(f"{label}: AI response {'from cache' if provider.used_cache else 'from a live request'}")

    print(f"\n{args.url}  provider={args.provider}")
    print(f"{'':32} {'candidates':>10} {'confirmed':>10} {'likely':>7} {'uncertain':>10} {'rejected':>9} {'blank/cosmetic':>15} {'duplicate':>10}")
    for r in results:
        print(f"{r['label']:32} {r['ai_candidates']:>10} {r['confirmed']:>10} {r['likely']:>7} {r['uncertain']:>10} "
              f"{r['rejected']:>9} {r['rejected_blank_or_cosmetic']:>15} {r['rejected_as_duplicate']:>10}")
    print("\nRejected after the change:")
    for line in results[-1]["reasons"]:
        print("  -", line)


if __name__ == "__main__":
    main()
