"""
Verification of Phase 4B on real-world sites (Flipkart, Play Store, YouTube scenarios).
Validates strict separation of human-facing presentation from technical details,
evidence provenance tracking, zero jargon leakage, and no duplicate headlines.
"""
import json
from pathlib import Path
import pytest

from aura.agents.orchestrator import AURAOrchestrator
from aura.agent.providers import get_ai_provider
from aura.evidence.bundle import EvidenceBundle
from aura.api.views import finding_view
from aura.interpretation.interpreter import interpret_finding


FORBIDDEN_JARGON = [
    "wcag",
    "axe-core",
    "<main>",
    "<h1>",
    "<h2>",
    "<nav>",
    "aria-",
    "aria ",
    "dom node",
    "dom path",
    "css selector",
    "materiality score",
]


def test_flipkart_bundle_audit_human_view_cleanliness():
    """Load real Flipkart evidence bundle and verify finding views have zero technical jargon."""
    bundle_path = Path("runs/quality/https_www_flipkart_com__bundle.json")
    if not bundle_path.exists():
        pytest.skip("Flipkart bundle not found")

    bundle_data = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle = EvidenceBundle(**bundle_data)

    provider = get_ai_provider(provider_type="mock")
    orchestrator = AURAOrchestrator(provider=provider)
    report = orchestrator.analyze_evidence(bundle)

    agg = report.get("aggregation")
    findings = agg.all_active_findings if agg else []
    assert len(findings) > 0, "Expected findings from Flipkart scan"

    for f in findings:
        fv = finding_view(f)

        assert "human" in fv, "Finding view missing human dict"
        assert "technical" in fv, "Finding view missing technical dict"

        h = fv["human"]
        t = fv["technical"]

        # Human fields must NOT have technical jargon
        for field in ("title", "summary", "why_it_matters", "what_to_do", "location"):
            val = str(h.get(field) or "").lower()
            for token in FORBIDDEN_JARGON:
                assert token not in val, f"Forbidden token '{token}' in human.{field}: {h.get(field)}"

        # Title and summary must never be identical
        assert h["title"] != h["summary"], f"Duplicate title/summary in finding {f.id}: {h['title']}"

        # Technical fields must preserve raw facts
        assert t["rule_id"], f"Missing rule_id in technical for {f.id}"
        assert t["verification_status"], f"Missing verification_status in technical for {f.id}"
        assert isinstance(t["evidence_provenance"], list)
        assert len(t["evidence_provenance"]) > 0


def test_play_store_and_youtube_flagged_scenarios():
    """
    Test the exact findings reported from live Play Store and YouTube scans:
    - Search functionality discoverability
    - Heading one structure
    - Landmark one main
    - Viewport horizontal scroll
    - Secondary looks primary
    """
    test_cases = [
        {
            "id": "play-search",
            "rule": "search_discoverability",
            "category": "UX",
            "severity": "medium",
            "source": "AI",
            "verification_status": "LIKELY",
            "confidence": 0.75,
            "target": {"kind": "element", "selector": "button.search-btn", "text": "Search"},
            "evidence": {"sources": ["screenshot_png_base64", "dom_snapshot"], "has_visual_evidence": True},
        },
        {
            "id": "play-heading",
            "rule": "page-has-heading-one",
            "category": "accessibility",
            "severity": "medium",
            "source": "axe-core",
            "verification_status": "CONFIRMED",
            "confidence": 1.0,
            "target": {"kind": "page", "selector": "body"},
            "evidence": {"sources": ["axe-core"]},
        },
        {
            "id": "play-main",
            "rule": "landmark-one-main",
            "category": "accessibility",
            "severity": "medium",
            "source": "axe-core",
            "verification_status": "CONFIRMED",
            "confidence": 1.0,
            "target": {"kind": "page", "selector": "body"},
            "evidence": {"sources": ["axe-core"]},
        },
        {
            "id": "play-secondary",
            "rule": "secondary_looks_primary",
            "category": "UI",
            "severity": "medium",
            "source": "AI",
            "verification_status": "LIKELY",
            "confidence": 0.80,
            "target": {"kind": "element", "selector": "button.cancel-btn", "text": "Cancel"},
            "evidence": {"sources": ["screenshot_png_base64"], "has_visual_evidence": True},
        },
        {
            "id": "play-overflow",
            "rule": "viewport_horizontal_scroll",
            "category": "responsiveness",
            "severity": "high",
            "source": "runtime",
            "verification_status": "CONFIRMED",
            "confidence": 0.95,
            "target": {"kind": "page", "selector": "html"},
            "evidence": {"sources": ["viewport_telemetry"]},
        },
    ]

    for tc in test_cases:
        fv = finding_view(tc)
        h = fv["human"]
        t = fv["technical"]

        # Human checks
        assert h["title"] != h["summary"], f"Duplicate title/summary for {tc['rule']}"
        for token in FORBIDDEN_JARGON:
            assert token not in h["title"].lower(), f"Jargon {token} in title for {tc['rule']}"
            assert token not in h["summary"].lower(), f"Jargon {token} in summary for {tc['rule']}"
            assert token not in h["why_it_matters"].lower(), f"Jargon {token} in why for {tc['rule']}"
            assert token not in h["what_to_do"].lower(), f"Jargon {token} in fix for {tc['rule']}"

        # Technical checks
        assert t["rule_id"] == tc["rule"]
        assert t["verification_status"] == tc["verification_status"]
        assert t["confidence"] == tc["confidence"]

        # Provenance check: visual findings have VISUAL tag
        if tc["evidence"].get("has_visual_evidence"):
            assert "VISUAL" in t["evidence_provenance"], f"Missing VISUAL tag for {tc['rule']}"
