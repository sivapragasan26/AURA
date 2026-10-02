"""
Chrome-extension path: EvidenceBundle -> AURA API -> shared analysis pipeline.

Evidence bundles are collected from Test Lab pages with Playwright using the SAME shared scripts the extension
injects (aura/analyzers/js/dom_extraction.js with collectFieldValues=false, vendored axe-core), so these tests
exercise the real bundle shape. Mock provider only: no live AI requests.
"""
import base64
import json
import re
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from aura.agents.orchestrator import AURAOrchestrator
from aura.analyzers.accessibility_analyzer import AXE_LOCAL_PATH
from aura.analyzers.dom_analyzer import DOMAnalyzer
from aura.api import security
from aura.api import server as api_server
from aura.api.provider_config import ProviderConfig
from aura.api.server import create_app
from aura.api.store import AuditStore
from aura.assistant.chat import ask, build_chat_context
from aura.assistant.explain import explain_finding
from aura.browser.interaction_policy import InteractionPolicy
from aura.config import settings
from aura.evidence.bundle import EvidenceBundle, redact_text, strip_url
from test_lab.launcher import TestLabLauncher

TOKEN = "t" * 40
BASE = "http://127.0.0.1:8765"
LAB = f"http://127.0.0.1:{settings.TEST_LAB_PORT}"
EXT_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture(scope="module")
def lab():
    TestLabLauncher.start_server()
    time.sleep(0.3)
    yield
    TestLabLauncher.stop_server()


def collect_bundle(url: str) -> dict:
    """Extension-equivalent collection (shared DOM script, vendored axe, post-load runtime probe)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        dom = page.evaluate(f"({DOMAnalyzer.DOM_EXTRACTION_SCRIPT})({{collectFieldValues: false}})")
        page.evaluate(AXE_LOCAL_PATH.read_text(encoding="utf-8"))
        axe = page.evaluate("""async () => { const r = await axe.run(document, {resultTypes: ['violations']});
            return {available: true, version: axe.version, violations: r.violations.map(v => ({id: v.id, impact: v.impact,
            description: v.description, helpUrl: v.helpUrl, nodes: v.nodes.map(n => ({target: n.target}))}))}; }""")
        failures = page.evaluate("""() => performance.getEntriesByType('resource').filter(e => e.responseStatus >= 400)
            .map(e => ({url: e.name, status: e.responseStatus, method: 'GET'}))""")
        shot = base64.b64encode(page.screenshot()).decode()
        title = page.title()
        browser.close()
    return {
        "source": "extension", "collector_version": "test/1", "url": url, "title": title,
        "viewport": {"width": 1440, "height": 900}, "dom": dom, "axe": axe,
        "telemetry": {"capture_scope": "post_load", "page_load_time_ms": 100, "console": [], "network": failures},
        "interactions": [], "screenshot_png_base64": shot, "captured_at": "2026-09-19T00:00:00Z",
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "mock")
    app = create_app(token=TOKEN, store=AuditStore())
    return TestClient(app, base_url=BASE)


def auth(extra=None):
    return {"X-AURA-Token": TOKEN, "Origin": EXT_ORIGIN, **(extra or {})}


# ---------------------------------------------------------------- security

def test_health_needs_no_token_but_reports_pairing(client, monkeypatch):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["paired"] is False
    assert client.get("/api/health", headers=auth()).json()["paired"] is True
    # Health may report WHETHER a key is configured, but never any key material.
    body = json.dumps(r.json()).lower()
    for metadata_field in ("provider_key", "key_configured", "key_source"):
        body = body.replace(metadata_field, "")
    assert "key" not in body
    # A self-hosted server may have its own key in its environment. Health may say a key is configured;
    # it must never show the key. (A user's key is never here at all: the browser calls the provider.)
    secret = "gsk_liveprovidersecret_0123456789"
    monkeypatch.setattr(settings, "GROQ_API_KEY", secret)
    providers = ProviderConfig()
    providers.set("groq")
    monkeypatch.setattr(api_server, "PROVIDERS", providers)
    with_key = json.dumps(client.get("/api/health").json())
    assert providers.has_key("groq") is True
    assert secret not in with_key and with_key.count("key_configured") == 1


def test_endpoints_require_token_and_reject_web_origins_and_foreign_hosts(client):
    assert client.post("/api/audits", json={}).status_code == 401
    assert client.post("/api/audits", json={}, headers={"X-AURA-Token": "wrong"}).status_code == 401
    assert client.post("/api/audits", json={}, headers=auth({"Origin": "https://evil.example"})).status_code == 403
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403


def test_oversized_body_is_rejected(client):
    r = client.post("/api/audits", headers=auth({"Content-Length": str(security.MAX_BODY_BYTES + 1)}), content=b"{}")
    assert r.status_code == 413


def test_invalid_bundle_is_rejected_with_field_problems(client):
    r = client.post("/api/audits", headers=auth(), json={"bundle": {"url": "file:///etc/passwd"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_EVIDENCE"


def test_token_file_is_created_once(tmp_path, monkeypatch):
    monkeypatch.delenv("AURA_API_TOKEN", raising=False)
    path = tmp_path / "tok"
    first = security.load_or_create_token(path)
    assert len(first) >= 32 and security.load_or_create_token(path) == first


# ---------------------------------------------------------------- bundle privacy

def test_bundle_strips_urls_and_redacts_secrets():
    assert strip_url("https://app.example/a/b?session=abc#x") == "https://app.example/a/b"
    assert strip_url("#") == "#" and strip_url("javascript:void(0)") == "javascript:"
    red = redact_text("mail bob@example.com token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop card 4111 1111 1111 1111")
    assert "bob@example.com" not in red and "eyJ" not in red and "4111" not in red
    b = EvidenceBundle(source="extension", collector_version="x", url="https://app.example/p?token=1",
                       viewport={"width": 1000, "height": 800},
                       dom={"elements": [{"tag": "a", "href": "/next?id=5", "text": "Contact alice@corp.com"}]},
                       axe={"available": True, "violations": [{"id": "image-alt", "nodes": [{"target": [["iframe", "img"], "#ok"]}]}]},
                       telemetry={"network": [{"url": "https://api.example/x?key=secret", "status": 500}]})
    assert b.url == "https://app.example/p"
    assert b.dom.elements[0]["href"] == "/next" and "alice@corp.com" not in b.dom.elements[0]["text"]
    assert b.axe.violations[0].nodes[0].target == ["#ok"]  # nested iframe target dropped
    assert b.telemetry.network[0].url == "https://api.example/x"


def test_bundle_never_keeps_an_unknown_field():
    """
    A field the server does not declare must never become evidence. It is now dropped rather than
    refused, so that a newer extension still gets a scan from an older server, but the value itself must
    not survive anywhere in the parsed bundle.
    """
    bundle = EvidenceBundle(source="extension", collector_version="x", url="https://a.example",
                            viewport={"width": 800, "height": 600}, dom={}, axe={}, cookies="session=1")
    assert not hasattr(bundle, "cookies")
    assert "cookies" not in bundle.model_dump()
    assert "session=1" not in json.dumps(bundle.model_dump(), default=str)


# ---------------------------------------------------------------- live-session policy

@pytest.mark.parametrize("element,ok", [
    ({"tag": "button", "type": "button", "text": "Open menu", "selector": "#m"}, True),
    ({"tag": "a", "href": "#", "text": "Features", "selector": "#f"}, True),
    ({"tag": "a", "href": "/pricing", "text": "Pricing", "selector": "#p"}, False),  # navigation
    ({"tag": "button", "text": "Next", "selector": "#n", "in_form": True, "effective_type": "submit"}, False),
    ({"tag": "input", "type": "submit", "text": "Go", "selector": "#s"}, False),
    ({"tag": "input", "type": "text", "selector": "#q"}, False),
    ({"tag": "button", "type": "button", "text": "Delete project", "selector": "#d"}, False),
    ({"tag": "button", "type": "button", "text": "Save changes", "selector": "#sv"}, False),
    ({"tag": "button", "type": "button", "text": "Send invite", "selector": "#i"}, False),
    ({"tag": "button", "type": "button", "text": "Log out", "selector": "#o"}, False),
])
def test_live_session_policy(element, ok):
    assert InteractionPolicy.is_action_safe_live_session("click", element, "https://app.example/")[0] is ok


def test_live_session_policy_never_types():
    assert InteractionPolicy.is_action_safe_live_session("input", {"tag": "input", "type": "text", "selector": "#q"})[0] is False


def test_interaction_plan_endpoint_applies_policy_and_budget(client):
    els = [{"tag": "button", "type": "button", "text": f"Tab {i}", "selector": f"#t{i}", "visible": True} for i in range(8)]
    els += [{"tag": "button", "type": "button", "text": "Delete account", "selector": "#del", "visible": True},
            {"tag": "a", "href": "/away", "text": "Away", "selector": "#away", "visible": True}]
    r = client.post("/api/interaction-plan", headers=auth(), json={"page_url": "https://app.example/", "elements": els})
    body = r.json()
    planned = {p["selector"] for p in body["plan"]}
    assert len(planned) == InteractionPolicy.LIVE_SESSION_BUDGET
    assert "#del" not in planned and "#away" not in planned
    assert {b["selector"] for b in body["blocked"]} >= {"#del", "#away"}


# ---------------------------------------------------------------- scoring / ids

def test_overall_excludes_unevaluated_ai_dimensions():
    from aura.models.findings import AccessibilityViolation, RuntimeTelemetry
    from aura.scoring.scorer import AURAScorer
    v = [AccessibilityViolation(rule="image-alt", impact="critical", description="d", target=["img"])]
    t = RuntimeTelemetry(url="https://a.example")
    with_ai, _ = AURAScorer().compute_score_with_deductions([], v, t)
    without, _ = AURAScorer().compute_score_with_deductions([], v, t, ai_evaluated=False)
    # Without AI, UI/UX/responsive/interaction must not count as a perfect 100
    assert without.overall < with_ai.overall
    assert without.overall == int((0.20 * without.accessibility + 0.15 * without.runtime) / 0.35)


def test_audit_ids_are_unique_within_one_second():
    ids = {AURAOrchestrator.generate_audit_id() for _ in range(5)}
    assert len(ids) == 5


# ---------------------------------------------------------------- end to end (mock provider)

def _all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def test_extension_scan_end_to_end_is_gt_free_and_labelled(lab, client):
    bundle = collect_bundle(f"{LAB}/05_mixed_realistic_suite/")
    r = client.post("/api/audits", headers=auth(), json={"bundle": bundle, "options": {"ai": True}})
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["source"] == "extension" and view["ai"]["state"] == "AI_OK" and view["result_state"] == "COMPLETE"
    assert view["findings"], "expected findings on the mixed suite"
    for f in view["findings"]:
        assert f["severity"] in ("critical", "high", "medium", "low", "info")
        assert f["verification_status"] in ("CONFIRMED", "LIKELY", "UNCERTAIN")
        assert f["origin"] in ("DETERMINISTIC", "VERIFIED_AI_CANDIDATE")
        if f["ai_contribution_score"] is not None:
            assert 0.0 <= f["ai_contribution_score"] <= 1.0
        if f["target"]["kind"] == "element":
            assert f["target"]["selector"]
    assert any(f["origin"] == "DETERMINISTIC" for f in view["findings"])
    assert any(f["origin"] == "VERIFIED_AI_CANDIDATE" for f in view["findings"])
    # Ground truth and benchmark data never reach the extension
    dumped = json.dumps(view)
    assert "GT-" not in dumped and "ground_truth" not in dumped.lower()
    assert not {"evaluation", "true_positives", "false_negatives", "precision", "recall"} & set(_all_keys(view))
    assert "telemetry_scope" not in dumped or view["evidence_coverage"]["notes"]
    # load-time console errors were not captured by a post-load collector: the coverage says so
    assert any("after the page had loaded" in n for n in view["evidence_coverage"]["notes"])

    # Stored and retrievable; isolated by audit id
    got = client.get(f"/api/audits/{view['audit_id']}", headers=auth()).json()
    assert got["audit_id"] == view["audit_id"]
    assert client.get("/api/audits/../../etc", headers=auth()).status_code == 404

    # Explain: grounded, no AI request
    f0 = view["findings"][0]
    ex = client.post(f"/api/audits/{view['audit_id']}/findings/{f0['id']}/explain", headers=auth()).json()
    headings = [s["heading"] for s in ex["sections"]]
    # Explain carries the whole problem in plain language; the card has only a short sentence and every
    # technical fact lives in Technical details.
    assert headings[0] == "What is happening"
    assert "How sure AURA is" in headings
    body = json.dumps(ex).lower()
    for technical in ("wcag", "axe-core", "aria-", "selector", "landmark", "verification status"):
        assert technical not in body, f"Explain leaked the technical term '{technical}'"
    assert "No new AI request" in ex["grounding"]

    # Ask AURA with the Mock provider: explicitly unavailable, never a fabricated answer
    a = client.post(f"/api/audits/{view['audit_id']}/ask", headers=auth(), json={"question": "Why is this a problem?"}).json()
    assert a["state"] == "AI_UNAVAILABLE" and a["answer"] is None


def test_deterministic_only_scan_marks_ai_dimensions_not_evaluated(lab, client):
    bundle = collect_bundle(f"{LAB}/01_accessibility_suite/")
    view = client.post("/api/audits", headers=auth(), json={"bundle": bundle, "options": {"ai": False}}).json()
    assert view["ai"]["state"] == "AI_OFF" and view["result_state"] == "DETERMINISTIC_ONLY"
    assert view["scores"]["ui"] == "N/A" and view["scores"]["ux"] == "N/A"
    assert all(f["origin"] == "DETERMINISTIC" for f in view["findings"])
    assert view["findings"], "axe-core findings expected on the accessibility suite"


def test_blocked_provider_degrades_to_deterministic_not_zero_ai_findings(lab, client, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Provider selection lives in ProviderConfig (built from settings at server start), not read per request.
    monkeypatch.setattr(api_server, "PROVIDERS", ProviderConfig())
    bundle = collect_bundle(f"{LAB}/02_ui_ux_suite/")
    view = client.post("/api/audits", headers=auth(), json={"bundle": bundle}).json()
    assert view["ai"]["state"] == "AI_UNAVAILABLE"
    assert "Deterministic evidence is available" in view["ai"]["message"]
    assert view["scores"]["ui"] == "N/A"


def test_extension_and_playwright_paths_agree_on_deterministic_evidence(lab):
    """Parity: same page, same shared DOM script and axe version -> same DOM elements and axe rules."""
    url = f"{LAB}/04_responsive_runtime_suite/"
    pw = AURAOrchestrator(provider_type="mock").run_audit(url=url, enable_interactions=False, skip_ai=True)
    ext = AURAOrchestrator(provider_type="mock").analyze_evidence(EvidenceBundle(**collect_bundle(url)), skip_ai=True)
    rules = lambda rep: sorted(v.rule for v in rep["report_model"].accessibility_violations)
    assert rules(pw) == rules(ext)
    pw_dom = pw["report_model"].runtime_telemetry.dom_summary
    ext_dom = ext["report_model"].runtime_telemetry.dom_summary
    assert pw_dom["total_elements"] == ext_dom["total_elements"]
    assert pw_dom["has_horizontal_overflow"] == ext_dom["has_horizontal_overflow"]
    # Known, documented difference: the extension cannot see console errors raised before it attached
    assert ext["collection"]["telemetry_scope"] == "post_load"


# ---------------------------------------------------------------- assistant

def _view_with_findings():
    return {"audit_id": "AURA-2026-000001", "page_url": "https://a.example/", "findings": [
        {"id": "F-001", "title": "Low contrast", "category": "ACCESSIBILITY", "severity": "high", "verification_status": "CONFIRMED",
         "origin": "DETERMINISTIC", "evidence": {"sources": ["axe"]}, "target": {"label": "#x"}}]}


def test_chat_context_excludes_benchmark_data():
    view = _view_with_findings()
    view["evaluation"] = {"true_positives": 3}  # must never be copied into the context
    ctx = build_chat_context(view)
    assert "evaluation" not in json.dumps(ctx) and "true_positives" not in json.dumps(ctx)


class _FakeProvider:
    provider_key = "groq"
    model = "fake-model"
    api_key = "k"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.last_execution_metadata = reply, error, {}
        self.prompts = []

    def capabilities(self):
        return {"image_input": True}

    def analyze(self, prompt, screenshot_base64=None, mime_type="image/png"):
        self.prompts.append(prompt)
        if self.error:
            raise RuntimeError(self.error)
        return self.reply


def test_ask_drops_unknown_citations_and_never_fabricates_on_failure():
    good = _FakeProvider(reply=json.dumps({"answer": "Contrast is 2.1:1.", "cited_finding_ids": ["F-001", "F-999"], "evidence_gaps": []}))
    r = ask(good, _view_with_findings(), "why?", "F-001")
    assert r["state"] == "OK" and r["cited_finding_ids"] == ["F-001"]
    assert "GT-" not in good.prompts[0] and "ground_truth" not in good.prompts[0]
    bad = _FakeProvider(error="HTTP 500")
    r = ask(bad, _view_with_findings(), "why?")
    assert r["state"] == "AI_UNAVAILABLE" and r["answer"] is None
    junk = _FakeProvider(reply="not json")
    assert ask(junk, _view_with_findings(), "why?")["state"] == "AI_RESPONSE_INVALID"


def test_explain_uncertain_ai_finding_is_labelled_as_hypothesis():
    f = {"id": "F-002", "title": "Weak CTA", "origin": "VERIFIED_AI_CANDIDATE", "verification_status": "UNCERTAIN",
         "verification_note": "Claimed control was not exercised", "severity": "medium", "category": "UI",
         "ai_contribution_type": "NOVEL_AI_INSIGHT", "evidence": {"sources": [], "flags": {"dom": True}},
         "target": {"kind": "element", "selector": "#cta", "text": "Buy"}}
    # An unverified AI suggestion must say, in plain words, that it is not a measured fact.
    out = explain_finding(f)
    sure = next(s for s in out["sections"] if s["heading"] == "How sure AURA is")
    assert "could not confirm" in sure["body"]
    assert "look at" in sure["body"]
    text = json.dumps(out).lower()
    for technical in ("wcag", "axe-core", "selector", "uncertain"):
        assert technical not in text, f"Explain leaked '{technical}'"


def test_test_lab_server_never_serves_ground_truth(lab):
    import urllib.error
    import urllib.request
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"{LAB}/01_accessibility_suite/ground_truth.json", timeout=5)
    assert e.value.code == 404
    assert urllib.request.urlopen(f"{LAB}/01_accessibility_suite/", timeout=5).status == 200


# ---------------------------------------------------------------------------------------------------
# Extension / server schema drift
#
# The extension and the server are upgraded independently, so the bundle the collector sends and the
# model the server declares must be kept in step by something other than a failed scan. The bundle now
# ignores unknown fields, which makes a newer extension survive an older server; this is what stops that
# tolerance from hiding a genuine mismatch.
# ---------------------------------------------------------------------------------------------------
def _bundle_keys_sent_by_the_extension() -> set:
    """Top-level keys of the `const bundle = { … }` literal in the collector."""
    scanner = (Path(__file__).resolve().parents[1] / "extension" / "sidepanel" / "scanner.js").read_text(encoding="utf-8")
    start = scanner.index("const bundle = {")
    depth, end = 0, None
    for i, ch in enumerate(scanner[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    assert end, "could not find the end of the bundle literal in scanner.js"
    body = scanner[start:end]
    # Keys at nesting depth 1 only: `telemetry: { … }` is one key, not four.
    keys, depth = set(), 1   # already inside `const bundle = {`
    for line in body.splitlines()[1:]:
        stripped = line.strip()
        if depth == 1:
            # `name: value` and the shorthand `name,` both declare a key.
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:,]", stripped)
            if m:
                keys.add(m.group(1))
        depth += line.count("{") - line.count("}")
    return keys


# The captures are deliberately NOT sent by the extension: they stay in the browser, which attaches one to
# its own request to the AI provider and crops the other itself (extension/sidepanel/shot.js). The fields
# remain accepted for a server that is given a capture another way - the Playwright collector and the
# dashboard both do - which is what aura/api/shots.py still serves.
HELD_IN_THE_BROWSER = {"screenshot_png_base64", "screenshot_fullpage_png_base64"}


def test_the_extension_sends_exactly_the_fields_the_server_declares():
    from aura.evidence.bundle import EvidenceBundle

    sent = _bundle_keys_sent_by_the_extension()
    declared = set(EvidenceBundle.model_fields)
    assert sent, "no bundle keys were parsed out of scanner.js"
    unknown = sorted(sent - declared)
    unused = sorted(declared - sent - HELD_IN_THE_BROWSER)
    assert not unknown, (f"scanner.js sends {unknown}, which EvidenceBundle does not declare. The server "
                         f"would silently drop that evidence.")
    assert not unused, (f"EvidenceBundle declares {unused}, which scanner.js never sends.")
    assert not (sent & HELD_IN_THE_BROWSER), (
        f"scanner.js sends {sorted(sent & HELD_IN_THE_BROWSER)}. The screenshots must stay in the browser: "
        f"the panel's privacy notice says so, and the service holds nothing on disk.")


def test_an_unknown_field_costs_the_evidence_not_the_scan():
    """A newer extension against an older server must still get a scan, minus the field it could not use."""
    from aura.evidence.bundle import EvidenceBundle

    base = dict(collector_version="1", url="https://example.com/", title="t",
                viewport={"width": 1280, "height": 800},
                dom={"elements": [], "total_elements": 0}, axe={"available": True, "violations": []})
    bundle = EvidenceBundle(**base, some_field_a_future_collector_adds={"anything": 1})
    assert bundle.url == "https://example.com/"
    assert not hasattr(bundle, "some_field_a_future_collector_adds")
    assert "some_field_a_future_collector_adds" not in bundle.model_dump()


def test_tolerating_unknown_fields_does_not_excuse_malformed_values():
    """Ignoring an unknown key must not loosen any check on the keys that are declared."""
    from pydantic import ValidationError
    from aura.evidence.bundle import EvidenceBundle

    base = dict(collector_version="1", title="t", viewport={"width": 1280, "height": 800},
                dom={"elements": [], "total_elements": 0}, axe={"available": True, "violations": []})
    with pytest.raises(ValidationError):
        EvidenceBundle(**base, url="file:///etc/passwd")          # http(s) only
    with pytest.raises(ValidationError):
        EvidenceBundle(**base, url="https://example.com/",
                       screenshot_png_base64="x" * 10_000_001)    # size cap still enforced
    with pytest.raises(ValidationError):
        EvidenceBundle(**base, url="https://example.com/",
                       target_boxes={f"#s{i}": {"x": 1, "y": 1, "width": 1, "height": 1}
                                     for i in range(700)})        # item cap still enforced
