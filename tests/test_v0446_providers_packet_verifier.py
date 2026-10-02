"""
V0.4.4.6 regression tests: Groq provider, provider preflight / tracked quota state, focused AI evidence
packet, mandatory rule_type, verifier corrections, GT-MIX-007 fixture, Mock suite integrity and
traceable provider fallback.

No test makes a live Gemini or Groq request: SDK clients / HTTP calls are mocked.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from aura.agent.analyzer_agent import AnalyzerAgent
from aura.agent.diagnostics import AIDiagnostics, AIAnalysisStatus
from aura.agent.evidence_packet import build_evidence_packet
from aura.agent.gemini_provider import GeminiProvider
from aura.agent.groq_provider import GroqProvider, parse_rate_limit_headers, parse_groq_duration
from aura.agent.provider import AIProvider
from aura.agent.provider_status import ProviderStateStore, ProviderPreflightBlocked, run_preflight
from aura.analyzers.runtime_analyzer import RuntimeAnalyzer
from aura.models.findings import (
    AffectedElementDetail, CandidateFinding, ConsoleError, FindingEvidenceDetail, NetworkFailure, RuntimeTelemetry,
    VerificationStatus,
)
from aura.verification.verifier import FindingVerifier

GROQ_KEY = "gsk_TestFakeKeyDoNotLeak0123456789"
GEMINI_KEY = "AIzaSyTestFakeKeyDoNotLeak00000"
GROQ_MODEL = "qwen/qwen3.6-27b"
DAILY_429 = ("429 RESOURCE_EXHAUSTED. Rate limit exceeded for model gemini-3.6-flash "
             "(limit: 20 requests per day on Free Tier)")
GROQ_HEADERS = {
    "x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": "14370",
    "x-ratelimit-reset-requests": "2m59.56s", "x-ratelimit-limit-tokens": "18000",
    "x-ratelimit-remaining-tokens": "17997", "x-ratelimit-reset-tokens": "7.66s",
}


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def ok_body(content='{"candidates": []}', model=GROQ_MODEL):
    return {"model": model, "choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {"total_tokens": 10}}


def groq():
    return GroqProvider(api_key=GROQ_KEY, model=GROQ_MODEL)


# ---------------------------------------------------------------- B/C/D: Groq requests

def test_groq_text_request_payload_and_metadata():
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(200, ok_body(), GROQ_HEADERS)) as post:
        text = groq().analyze("Analyze this page")
    assert text == '{"candidates": []}'
    kwargs = post.call_args.kwargs
    body = kwargs["json"]
    assert post.call_args.args[0].endswith("/openai/v1/chat/completions")
    assert kwargs["headers"]["Authorization"] == f"Bearer {GROQ_KEY}"
    assert body["model"] == GROQ_MODEL
    assert body["messages"][0]["content"] == "Analyze this page"          # text-only: plain string
    assert body["response_format"] == {"type": "json_object"}               # structured JSON
    assert body["reasoning_format"] == "hidden"                             # required with JSON mode
    assert isinstance(body["max_completion_tokens"], int) and body["max_completion_tokens"] > 0


def test_groq_multimodal_request_sends_image_part_not_text_dump():
    provider = groq()
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(200, ok_body(), GROQ_HEADERS)) as post:
        provider.analyze("Look at the screenshot", screenshot_base64="iVBORw0KGgoFAKE", mime_type="image/png")
    content = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Look at the screenshot"}
    assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoFAKE"}}
    assert "iVBORw0KGgoFAKE" not in content[0]["text"]
    meta = provider.last_execution_metadata
    assert meta["status"] == "SUCCESS" and meta["requested_model"] == GROQ_MODEL and meta["actual_model"] == GROQ_MODEL
    assert meta["attempt_count"] == 1 and meta["retry_count"] == 0 and meta["fallback_used"] is False


def test_groq_structured_candidates_parsed_through_analyzer_with_refs():
    """End to end: packet -> Groq (mocked HTTP) -> candidate contract -> ref mapped to real selector."""
    dom = {"all_elements": [
        {"tag": "button", "selector": "#hero > button", "id": None, "id_chain": ["hero"], "text": "Delete everything", "visible": True},
        {"tag": "a", "selector": "#hero > a", "id": None, "id_chain": ["hero"], "text": "Save", "href": "#", "visible": True},
    ]}
    telemetry = RuntimeTelemetry(url="http://127.0.0.1:8999/x/", title="t")
    response = json.dumps({"overall_summary": "x", "candidates": [{
        "title": "Delete dominates save", "category": "UI", "rule_type": "bad_visual_hierarchy",
        "description": "d", "target": "E1", "evidence": "E1 is large and red", "confidence": 0.9,
        "why_ai_needed": "Visual hierarchy requires screenshot interpretation."}]})
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(200, ok_body(response), GROQ_HEADERS)):
        res = AnalyzerAgent(provider=groq()).analyze(telemetry=telemetry, dom_summary=dom, accessibility_violations=[])
    diag = res["diagnostics"]
    assert diag.status == AIAnalysisStatus.SUCCESS_WITH_CANDIDATES
    assert diag.ai_response_parsed and diag.ai_schema_valid
    cand = res["issues"][0]
    assert cand["rule_type"] == "bad_visual_hierarchy"
    assert cand["affected_element"]["selector"] == "#hero > button"   # E1 mapped back to the real element
    assert cand["why_ai_needed"].startswith("Visual hierarchy")
    assert diag.provider_rate_limit["remaining_requests_per_day"] == 14370


# ---------------------------------------------------------------- E/F/G: Groq failures

def test_groq_invalid_key_not_retried_and_never_leaked(caplog):
    provider = groq()
    body = {"error": {"message": f"Invalid API Key {GROQ_KEY}", "code": "invalid_api_key"}}
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(401, body)) as post, patch("time.sleep"):
        with pytest.raises(RuntimeError) as exc:
            provider.analyze("p")
    assert post.call_count == 1
    meta = provider.last_execution_metadata
    assert meta["failure_category"] == "AUTHENTICATION_ERROR" and meta["http_status"] == 401
    assert GROQ_KEY not in str(exc.value)
    assert GROQ_KEY not in json.dumps(meta)
    assert GROQ_KEY not in caplog.text


def test_groq_model_unavailable():
    provider = groq()
    body = {"error": {"message": "The model does not exist", "code": "model_not_found"}}
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(404, body)) as post:
        with pytest.raises(RuntimeError):
            provider.analyze("p")
    assert post.call_count == 1
    assert provider.last_execution_metadata["status"] == "MODEL_ERROR"
    with patch("aura.agent.groq_provider.requests.get", return_value=FakeResp(404, body)):
        assert provider.check_availability()["status"] == "MODEL_UNAVAILABLE"


def test_groq_model_without_image_support_is_classified_not_downgraded():
    provider = GroqProvider(api_key=GROQ_KEY, model="some/text-only-model")
    with patch.dict("aura.agent.groq_provider.MODEL_CAPABILITIES", {"some/text-only-model": {"image_input": False}}), \
         patch("aura.agent.groq_provider.requests.post") as post:
        with pytest.raises(RuntimeError):
            provider.analyze("p", screenshot_base64="abc")
        assert run_preflight(provider, check_remote=False).status == "CAPABILITY_UNSUPPORTED"
    post.assert_not_called()
    assert provider.last_execution_metadata["failure_category"] == "CAPABILITY_UNSUPPORTED"
    assert provider.model == "some/text-only-model"  # no silent model switch


def test_groq_daily_429_single_attempt():
    provider = groq()
    headers = {**GROQ_HEADERS, "x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "7h12m", "retry-after": "2"}
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(429, {"error": {"message": "rate limit"}}, headers)) as post, \
         patch("time.sleep") as sleep:
        with pytest.raises(RuntimeError):
            provider.analyze("p")
    assert post.call_count == 1
    sleep.assert_not_called()
    meta = provider.last_execution_metadata
    assert meta["status"] == "RATE_LIMITED" and meta["quota_scope"] == "DAILY"


def test_groq_short_term_429_retries_once_with_retry_after():
    provider = groq()
    headers = {**GROQ_HEADERS, "retry-after": "2"}
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(429, {"error": {"message": "tokens per minute"}}, headers)) as post, \
         patch("time.sleep") as sleep:
        with pytest.raises(RuntimeError):
            provider.analyze("p")
    assert post.call_count == 2
    sleep.assert_called_once_with(2.0)
    meta = provider.last_execution_metadata
    assert meta["quota_scope"] == "SHORT_TERM" and meta["attempt_count"] == 2 and meta["retry_count"] == 1


# ---------------------------------------------------------------- H/K: rate-limit headers, labelling

def test_groq_rate_limit_headers_parsed():
    rl = parse_rate_limit_headers({**GROQ_HEADERS, "retry-after": "2", "content-type": "application/json"})
    assert rl["limit_requests_per_day"] == 14400 and rl["remaining_requests_per_day"] == 14370
    assert rl["limit_tokens_per_minute"] == 18000 and rl["remaining_tokens_per_minute"] == 17997
    assert rl["reset_requests"] == "2m59.56s" and rl["reset_requests_seconds"] == 179.56
    assert rl["reset_tokens_seconds"] == 7.66 and rl["retry_after_seconds"] == 2.0
    assert rl["source"] == "provider-reported"
    assert parse_rate_limit_headers({"content-type": "json"}) == {}          # nothing invented
    assert parse_groq_duration("1h2m") == 3720 and parse_groq_duration("250ms") == 0.25


def test_provider_reported_values_distinguished_from_aura_estimates():
    now = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    ProviderStateStore.record("gemini", "gemini-3.6-flash", {"status": "RATE_LIMITED", "failure_category": "RATE_LIMITED",
                                                             "quota_scope": "DAILY", "http_status": 429}, now=now)
    gemini_state = ProviderStateStore.get("gemini", "gemini-3.6-flash")
    assert gemini_state["provider_reported"] == {}                               # Gemini supplied no quota values
    assert gemini_state["aura_tracked"]["basis"].startswith("AURA estimate")
    ProviderStateStore.record("groq", GROQ_MODEL, {"status": "SUCCESS", "http_status": 200,
                                                   "rate_limit": parse_rate_limit_headers(GROQ_HEADERS)}, now=now)
    assert ProviderStateStore.get("groq", GROQ_MODEL)["provider_reported"]["source"] == "provider-reported"

    diag = AIDiagnostics(provider_rate_limit=parse_rate_limit_headers(GROQ_HEADERS))
    assert diag.provider_quota_summary()["Provider-reported remaining (requests/day)"] == 14370
    assert AIDiagnostics().provider_quota_summary() == {}                         # no fabricated "x / 20 remaining"


# ---------------------------------------------------------------- I/J: preflight

def test_preflight_blocks_known_gemini_daily_exhaustion_until_estimated_reset():
    provider = GeminiProvider(api_key=GEMINI_KEY, model="gemini-3.6-flash")
    t0 = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)  # 11:00 Pacific
    ProviderStateStore.record("gemini", "gemini-3.6-flash", {"status": "RATE_LIMITED", "failure_category": "RATE_LIMITED",
                                                             "quota_scope": "DAILY", "http_status": 429}, now=t0)
    blocked = run_preflight(provider, check_remote=False, now=t0 + timedelta(hours=1))
    assert blocked.status == "QUOTA_EXHAUSTED" and blocked.blocked
    assert blocked.action == "Do not start AI-dependent audit"
    assert blocked.last_http_status == 429
    after_reset = run_preflight(provider, check_remote=False, now=t0 + timedelta(hours=14))
    assert not after_reset.blocked


def test_preflight_short_term_cooldown():
    provider = groq()
    t0 = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    ProviderStateStore.record("groq", GROQ_MODEL, {"status": "RATE_LIMITED", "failure_category": "RATE_LIMITED",
                                                   "quota_scope": "SHORT_TERM", "http_status": 429, "retry_after_seconds": 30}, now=t0)
    assert run_preflight(provider, check_remote=False, now=t0 + timedelta(seconds=10)).status == "COOLDOWN_ACTIVE"
    assert not run_preflight(provider, check_remote=False, now=t0 + timedelta(seconds=40)).blocked


def test_preflight_never_runs_an_inference():
    provider = groq()
    with patch("aura.agent.groq_provider.requests.post") as post, \
         patch("aura.agent.groq_provider.requests.get", return_value=FakeResp(200, {"id": GROQ_MODEL, "active": True}, GROQ_HEADERS)) as get:
        result = run_preflight(provider, check_remote=True)
    post.assert_not_called()                                   # chat/completions never called
    assert get.call_args.args[0].endswith("/models") or get.call_args.args[0].endswith(f"/models/{GROQ_MODEL}")
    assert result.status == "READY" and result.consumed_inference is False
    assert result.provider_reported["remaining_requests_per_day"] == 14370

    gem = GeminiProvider(api_key=GEMINI_KEY, model="gemini-3.6-flash")
    client = MagicMock()
    with patch("google.genai.Client", return_value=client):
        assert run_preflight(gem, check_remote=True).status == "READY"
    client.interactions.create.assert_not_called()
    client.models.get.assert_called_once_with(model="gemini-3.6-flash")


def test_preflight_auth_invalid_and_not_configured():
    with patch("aura.agent.groq_provider.requests.get", return_value=FakeResp(401, {"error": {"message": "invalid"}})):
        assert run_preflight(groq(), check_remote=True).status == "AUTH_INVALID"
    assert run_preflight(GroqProvider(api_key="", model=GROQ_MODEL), check_remote=False).status == "NOT_CONFIGURED"


class _NeverCalledProvider(AIProvider):
    provider_key = "groq"
    model = GROQ_MODEL
    api_key = GROQ_KEY

    def analyze(self, prompt, screenshot_base64=None, mime_type="image/png"):
        raise AssertionError("inference must not run")

    def test_connection(self):
        return False, "n/a"


def test_blocked_preflight_stops_before_any_browser_work():
    from aura.agents.orchestrator import AURAOrchestrator
    ProviderStateStore.record("groq", GROQ_MODEL, {
        "status": "RATE_LIMITED", "failure_category": "RATE_LIMITED", "quota_scope": "DAILY", "http_status": 429,
        "rate_limit": {"remaining_requests_per_day": 0, "reset_requests": "2h", "reset_requests_seconds": 7200,
                       "source": "provider-reported"}})
    orch = AURAOrchestrator(provider=_NeverCalledProvider())
    with patch.object(orch.browser_agent, "start") as start:
        with pytest.raises(ProviderPreflightBlocked) as exc:
            orch.run_audit(url="http://127.0.0.1:8999/05_mixed_realistic_suite/", mode="external")
    start.assert_not_called()
    assert exc.value.result.status == "QUOTA_EXHAUSTED"


# ---------------------------------------------------------------- L/M/N/O/T: evidence packet

def _packet_from_page():
    from playwright.sync_api import sync_playwright
    from aura.analyzers.dom_analyzer import DOMAnalyzer
    links = "".join(f'<a href="/p{i}">Link {i}</a>' for i in range(120))
    html = f"""<html><head><title>Shop</title></head><body>
      <script type="application/json" id="aura-ground-truth">{{"expected_findings": [{{"ground_truth_id": "GT-SECRET-001"}}]}}</script>
      <nav id="nav-broken-menu-secret">{links}</nav>
      <div id="ui-visual-hierarchy-secret" class="btn-giant-red-secret card">
        <button id="interaction-dead-btn-secret" class="btn-dead-secret">Generate report</button>
      </div></body></html>"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        dom = DOMAnalyzer().analyze(page)
        browser.close()
    url = "http://127.0.0.1:8999/shop/"
    telemetry = RuntimeTelemetry(url=url, title="Shop", viewport={"width": 1440, "height": 900}, console_errors=[
        ConsoleError(type="exception", text="TypeError: cart is undefined", location=f"{url}:10"),
        ConsoleError(type="error", text="tracker blocked", location="https://cdn.thirdparty-analytics.io/t.js:1"),
        ConsoleError(type="warning", text="deprecated API"),
    ], network_failures=[NetworkFailure(url="https://ads.example.net/pixel", status=404)])
    RuntimeAnalyzer().classify_telemetry(telemetry)
    button_sel = next(e["selector"] for e in dom["all_elements"] if e["tag"] == "button")
    log = [{"status": "executed", "action": "click", "target": button_sel, "element_selector": button_sel,
            "element_id_chain": ["interaction-dead-btn-secret"], "dom_changed": False, "url_changed": False,
            "errors_after_action": [], "hypothesis": "internal hypothesis text"}]
    packet = build_evidence_packet(telemetry, dom, [], interaction_log=log, screenshot_base64="iVBORw0KGgoFAKE")
    return packet, dom, button_sel


@pytest.fixture(scope="module")
def page_packet():
    return _packet_from_page()


def test_packet_excludes_ground_truth(page_packet):
    packet, _, _ = page_packet
    text = packet.to_prompt()
    for leaked in ("aura-ground-truth", "expected_findings", "GT-SECRET-001", "ground_truth", "true_positive", "benchmark"):
        assert leaked.lower() not in text.lower()


def test_packet_excludes_raw_dom_ids_classes_and_is_bounded(page_packet):
    packet, dom, _ = page_packet
    text = packet.to_prompt()
    assert len(dom["all_elements"]) > 120
    assert len(packet.targeted_dom) <= 60
    assert "raw_elements_with_styles" not in text and "all_elements" not in text and "<html" not in text
    for secret in ("nav-broken-menu-secret", "ui-visual-hierarchy-secret", "interaction-dead-btn-secret",
                   "btn-giant-red-secret", "btn-dead-secret"):
        assert secret not in text                      # ids/classes can name the defect: never sent
    assert "at most 8" in text and "{max_findings}" not in text


def test_packet_excludes_unrelated_runtime_and_network_noise(page_packet):
    packet, _, _ = page_packet
    runtime = packet.deterministic_findings["runtime"]
    text = json.dumps(packet.to_ai_payload())
    assert [r["message"] for r in runtime] == ["TypeError: cart is undefined"]
    assert "tracker blocked" not in text and "ads.example.net" not in text and "deprecated API" not in text


def test_packet_has_screenshot_targeted_dom_and_interaction_evidence(page_packet):
    packet, _, button_sel = page_packet
    payload = packet.to_ai_payload()
    assert packet.screenshot_base64 == "iVBORw0KGgoFAKE" and payload["screenshot_attached"] is True
    assert "iVBORw0KGgoFAKE" not in packet.to_prompt()                      # image travels separately
    button = next(e for e in packet.targeted_dom if e["tag"] == "button")
    assert button["text"] == "Generate report" and button["ref"].startswith("E")
    assert packet.ref_map[button["ref"]]["selector"] == button_sel
    inter = payload["interactions"][0]
    assert inter["target"] == button["ref"] and inter["dom_changed"] is False
    assert "hypothesis" not in inter                                         # no internal AURA state


# ---------------------------------------------------------------- P: rule_type mandatory

def test_rule_type_is_mandatory_and_never_inferred_from_title():
    diag = AIDiagnostics()
    raw = json.dumps({"candidates": [
        {"title": "Bad visual hierarchy in hero", "category": "UI", "description": "d", "target": "#hero", "confidence": 0.9},
        {"title": "Confusing form", "category": "UX", "rule_type": "confusing_form", "description": "d", "target": "#form", "confidence": 0.9},
    ]})
    res = AnalyzerAgent(provider=MagicMock())._parse_and_process_response(raw, diag)
    assert diag.missing_rule_type_count == 1 and diag.schema_rejected_count == 1
    assert [i["rule_type"] for i in res["issues"]] == ["confusing_form"]


def test_candidate_budget_enforced_after_duplicate_suppression():
    diag = AIDiagnostics()
    items = [{"title": f"Issue {i}", "category": "UI", "rule_type": "bad_visual_hierarchy", "description": "d",
              "target": f"#t{i}", "confidence": 0.5 + i / 100} for i in range(10)]
    res = AnalyzerAgent(provider=MagicMock())._parse_and_process_response(json.dumps({"candidates": items}), diag, max_findings=5)
    assert len(res["issues"]) == 5 and diag.ai_candidates_over_limit == 5
    assert min(i["confidence"] for i in res["issues"]) >= 0.55
    # dropped candidates stay traceable (benchmark labels them AI_GENERATED_NOT_MATCHED, not AI_NOT_GENERATED)
    dropped = [c for c in res["suppressed_issues"] if c["status"] == "dropped_over_limit"]
    assert len(dropped) == 5


def test_budget_dropped_candidate_is_not_reported_as_ai_not_generated(tmp_path):
    from aura.evaluation.evaluator import EvaluationEngine
    (tmp_path / "ground_truth.json").write_text(json.dumps({"suite_id": "t", "expected_findings": [
        {"ground_truth_id": "GT-A", "category": "UI", "normalized_rule": "inconsistent_component_styling",
         "target": "#components", "allowed_sources": ["AI"]}]}), encoding="utf-8")
    dropped = CandidateFinding(id="AI-SUP-001", candidate_id="AI-SUP-001", category="UI", title="Inconsistent buttons",
                               description="d", observation="o", severity="medium", confidence=0.6,
                               affected_element=AffectedElementDetail(selector="#components"),
                               evidence=FindingEvidenceDetail(type="visual", description="x"),
                               rule_type="inconsistent_component_styling", normalized_rule="inconsistent_component_styling",
                               status="dropped_over_limit")
    res = EvaluationEngine.evaluate(tmp_path, [], suppressed_ai_candidates=[dropped])
    d = res["fn_diagnostics"][0]
    assert d["root_cause"] == "AI_GENERATED_NOT_MATCHED" and "budget" in d["reason"]


# ---------------------------------------------------------------- Q/R: verifier

def _cand(rule, selector, title, category="INTERACTION"):
    return CandidateFinding(id="AI-001", candidate_id="AI-001", category=category, title=title, description=title,
                            observation=title, severity="high", confidence=0.9,
                            affected_element=AffectedElementDetail(selector=selector),
                            evidence=FindingEvidenceDetail(type="dom", description="x"),
                            rule_type=rule, normalized_rule=rule)


DOM = {"all_elements": [
    {"tag": "button", "selector": "#dead-btn", "id": "dead-btn", "id_chain": ["dead-btn"], "text": "Go", "visible": True,
     "bounding_box": {"x": 10, "y": 10, "width": 80, "height": 30}},
    {"tag": "button", "selector": "#other", "id": "other", "id_chain": ["other"], "text": "Other", "visible": True,
     "bounding_box": {"x": 200, "y": 10, "width": 80, "height": 30}},
    {"tag": "div", "selector": "#hero", "id": "hero", "id_chain": ["hero"], "text": "Delete Save", "visible": True,
     "bounding_box": {"x": 0, "y": 100, "width": 800, "height": 60}},
]}
TEL = RuntimeTelemetry(url="http://x.test/", dom_summary={"has_horizontal_overflow": False})


def _verify(cand, log):
    active, rejected = FindingVerifier().verify_findings([cand], DOM, [], TEL, interaction_log=log)
    return (active or rejected)[0].verification


def test_interaction_failure_requires_target_specific_interaction():
    cand = _cand("interaction_failure", "#dead-btn", "Button throws an error when clicked")
    # element exists, but only another control was exercised -> not confirmed
    other = [{"status": "executed", "element_selector": "#other", "element_id_chain": ["other"], "errors_after_action": ["boom"]}]
    assert _verify(cand, other).status == VerificationStatus.UNCERTAIN
    assert _verify(cand, []).status == VerificationStatus.UNCERTAIN
    # target exercised and an exception followed -> confirmed
    hit = [{"status": "executed", "element_selector": "#dead-btn", "element_id_chain": ["dead-btn"],
            "errors_after_action": ["Uncaught Error: boom"], "dom_changed": False}]
    assert _verify(cand, hit).status == VerificationStatus.CONFIRMED
    # target exercised, visible change and no error -> claim not supported
    worked = [{"status": "executed", "element_selector": "#dead-btn", "element_id_chain": ["dead-btn"],
               "errors_after_action": [], "dom_changed": True}]
    assert _verify(cand, worked).status == VerificationStatus.UNCERTAIN


def test_non_responsive_control_confirmed_by_no_effect():
    cand = _cand("non_responsive_control", "#dead-btn", "Button gives no feedback", category="UX")
    log = [{"status": "executed", "element_selector": "#dead-btn", "element_id_chain": ["dead-btn"],
            "errors_after_action": [], "dom_changed": False, "url_changed": False}]
    assert _verify(cand, log).status == VerificationStatus.CONFIRMED


def test_hidden_obscured_wording_is_not_rejected_lexically():
    for title in ("Primary save action is visually hidden behind the delete button",
                  "Save link is obscured and barely noticeable",
                  "Save action is not discoverable",
                  "Save link is covered by the delete button"):
        v = _verify(_cand("bad_visual_hierarchy", "#hero", title, category="UI"), [])
        assert v.status != VerificationStatus.REJECTED, title


def test_measured_contradictions_still_reject():
    absent = _cand("discoverability_problem", "#hero", "Hero section is missing from the page", category="UX")
    assert _verify(absent, []).status == VerificationStatus.REJECTED
    css_hidden = _cand("discoverability_problem", "#hero", "Hero section is hidden", category="UX")
    v = _verify(css_hidden, [])
    # Section 5 of the rectification fixes one wording for every screenshot contradiction.
    assert v.status == VerificationStatus.REJECTED
    assert v.rejection_reason == "Visual evidence contradicts the AI observation."


# ---------------------------------------------------------------- S: GT-MIX-007 fixture

def test_gt_mix_007_page_raises_uncaught_exception_on_load():
    from aura.browser.browser_manager import BrowserManager
    from test_lab.launcher import TestLabLauncher
    TestLabLauncher.start_server()
    manager = BrowserManager(headless=True)
    manager.start(viewport={"width": 1440, "height": 900})
    try:
        ok, msg, _ = manager.navigate("http://127.0.0.1:8999/05_mixed_realistic_suite/")
        assert ok, msg
        manager.page.wait_for_timeout(800)
        exceptions = [c for c in manager.collector.console_errors if c.type == "exception"]
    finally:
        manager.stop()
    assert any("initialization failed" in c.text.lower() for c in exceptions)
    from aura.config import settings
    html = (settings.TEST_LAB_DIR / "05_mixed_realistic_suite" / "index.html").read_text(encoding="utf-8")
    assert "aura-ground-truth" not in html


# ---------------------------------------------------------------- A/V: Gemini 429 run, traceable provider

def test_gemini_daily_429_run_is_not_evaluable_attributed_and_then_preflight_blocked():
    from aura.engine import AURAEngine
    from test_lab.launcher import TestLabLauncher
    TestLabLauncher.start_server()
    site = next(s for s in TestLabLauncher.list_sites() if s["id"] == "05_mixed_realistic_suite")
    provider = GeminiProvider(api_key=GEMINI_KEY, model="gemini-3.6-flash")
    client = MagicMock()
    client.interactions.create.side_effect = Exception(DAILY_429)
    with patch("google.genai.Client", return_value=client), patch("time.sleep"), \
         patch("aura.agent.groq_provider.requests.post") as groq_post:
        report = AURAEngine(provider=provider).run_analysis(url=site["url"], mode="test_lab", site_dir=site["dir"], headless=True)
        assert client.interactions.create.call_count == 1                    # one request, no retries
        diag = report["ai_diagnostics"]
        assert diag.status == AIAnalysisStatus.RATE_LIMITED and diag.retry_count == 0
        ev = report["evaluation"]
        assert ev["benchmark_ai_status"] == "NOT_EVALUABLE" and ev["true_positives"] is None
        sel = report["provider_selection"]
        assert sel["provider"] == "gemini" and sel["fallback"] is None and ev["ai_provider"] == "gemini"
        groq_post.assert_not_called()                                         # never silently switched to Groq

        # The recorded daily exhaustion now blocks the next run before any browser work
        with pytest.raises(ProviderPreflightBlocked) as exc:
            AURAEngine(provider=provider).run_analysis(url=site["url"], mode="test_lab", site_dir=site["dir"], headless=True)
    assert exc.value.result.status == "QUOTA_EXHAUSTED"
    assert client.interactions.create.call_count == 1


def test_user_selected_fallback_is_recorded():
    from aura.agents.orchestrator import AURAOrchestrator
    orch = AURAOrchestrator(provider=groq())
    diag = AIDiagnostics(requested_model=GROQ_MODEL, actual_model=GROQ_MODEL, status=AIAnalysisStatus.SUCCESS_WITH_CANDIDATES)
    sel = orch._provider_selection(diag, {"primary_provider": "gemini", "primary_model": "gemini-3.6-flash",
                                          "primary_status": "QUOTA_EXHAUSTED", "primary_reason": "Daily quota exhausted",
                                          "fallback_provider": "groq", "selected_by": "user"})
    assert sel["provider"] == "groq"
    assert sel["fallback"] == {
        "primary_provider": "gemini", "primary_model": "gemini-3.6-flash", "primary_status": "QUOTA_EXHAUSTED",
        "primary_reason": "Daily quota exhausted", "fallback_provider": "groq", "fallback_model": GROQ_MODEL,
        "fallback_status": "SUCCESS_WITH_CANDIDATES", "selected_by": "user"}


# ---------------------------------------------------------------- U: Mock suites keep integrity

def test_all_five_mock_suites_keep_benchmark_integrity():
    from aura.engine import AURAEngine
    from aura.evaluation.registry import GroundTruthRegistry
    from test_lab.launcher import TestLabLauncher
    TestLabLauncher.start_server()
    engine = AURAEngine(provider_type="mock")
    for site in TestLabLauncher.list_sites():
        ev = engine.run_analysis(url=site["url"], mode="test_lab", site_dir=site["dir"], headless=True)["evaluation"]
        expected = len(GroundTruthRegistry.load_suite_ground_truth(site["dir"])["expected_findings"])
        assert ev["integrity_status"] == "PASS", (site["id"], ev["integrity_notes"])
        assert ev["expected_count"] == expected == ev["true_positives"] + ev["false_negatives"]
