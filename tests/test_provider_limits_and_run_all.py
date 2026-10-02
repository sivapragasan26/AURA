"""
Provider limit classification (Groq), oversized-request handling, pacing between sequential suites, and the
sequential Test Lab "Run All" runner. All provider responses are mocked: no live AI request is made.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from aura.agent.groq_provider import (
    GroqProvider, classify_rate_limit_kind, parse_limit_value, provider_limit_status,
)
from aura.agent.pacing import capacity_wait_seconds, wait_for_provider_capacity
from aura.agent.provider_status import PreflightResult, ProviderPreflightBlocked, ProviderStateStore, run_preflight
from aura.config import settings
from aura.evaluation.evaluator import EvaluationEngine
from aura.evaluation.test_lab_runner import run_all_suites

MODEL = "qwen/qwen3.8-27b"
KEY = "gsk_LimitsTestFakeKey0000000000"


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, str(body)

    def json(self):
        return self._body


def err(msg, code="rate_limit_exceeded"):
    return {"error": {"message": msg, "type": "tokens", "code": code}}


TPM_429 = ("Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_x` service tier `on_demand` on tokens per "
           "minute (TPM): Limit 8000, Used 6186, Requested 2554. Please try again in 6.55s.")
OTPM_TOO_LARGE = ("Request too large for model `qwen/qwen3.8-27b` on output tokens per minute (OTPM): Limit 2000, "
                  "Requested 4096. Requested output tokens exceed enforced limit.")
TPM_TOO_LARGE = ("Request too large for model `qwen/qwen3.8-27b` on tokens per minute (TPM): Limit 6000, Requested 9100, "
                 "please reduce your message size and try again.")
RPD_429 = "Rate limit reached for model `qwen/qwen3.8-27b` on requests per day (RPD): Limit 1000, Used 1000, Requested 1."


@pytest.mark.parametrize("msg,kind,oversized,status", [
    (TPM_429, "TPM", False, "RATE_LIMITED_TPM"),
    (OTPM_TOO_LARGE, "OTPM", True, "REQUEST_TOO_LARGE_OTPM"),
    (TPM_TOO_LARGE, "TPM", True, "REQUEST_TOO_LARGE_TPM"),
    (RPD_429, "RPD", False, "QUOTA_EXHAUSTED_RPD"),
    ("Rate limit reached ... on tokens per day (TPD): Limit 500000", "TPD", False, "QUOTA_EXHAUSTED_TPD"),
    ("Rate limit reached ... on requests per minute (RPM): Limit 30", "RPM", False, "RATE_LIMITED_RPM"),
])
def test_limit_kind_comes_from_the_provider_message(msg, kind, oversized, status):
    k, o = classify_rate_limit_kind(msg, {})
    assert (k, o) == (kind, oversized)
    assert provider_limit_status("RATE_LIMITED", k, o) == status


def test_limit_value_parsing():
    assert parse_limit_value(TPM_429) == 8000
    assert parse_limit_value(OTPM_TOO_LARGE) == 2000
    assert parse_limit_value("no numbers here") is None


def test_tpm_429_is_short_term_not_daily_quota():
    p = GroqProvider(api_key=KEY, model=MODEL)
    hdr = {"retry-after": "7", "x-ratelimit-remaining-requests": "990"}
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(429, err(TPM_429), hdr)), patch("time.sleep"):
        with pytest.raises(RuntimeError):
            p.analyze("prompt")
    meta = p.last_execution_metadata
    assert meta["quota_scope"] == "SHORT_TERM" and meta["provider_limit_status"] == "RATE_LIMITED_TPM"
    assert meta["attempt_count"] == 2  # one retry after the provider's short Retry-After


def test_oversized_tpm_request_is_not_retried_and_sets_no_cooldown():
    p = GroqProvider(api_key=KEY, model=MODEL)
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(413, err(TPM_TOO_LARGE, "request_too_large"))) as post, \
            patch("time.sleep"):
        with pytest.raises(RuntimeError):
            p.analyze("prompt")
    assert post.call_count == 1  # unchanged oversized request: never retried
    meta = p.last_execution_metadata
    assert meta["failure_category"] == "REQUEST_TOO_LARGE" and meta["provider_limit_status"] == "REQUEST_TOO_LARGE_TPM"
    entry = ProviderStateStore.record("groq", MODEL, meta)
    assert entry["aura_tracked"]["cooldown_until"] is None  # not a quota/cooldown condition
    assert run_preflight(p, check_remote=False).blocked is False


def test_oversized_output_budget_is_retried_once_with_a_smaller_budget():
    p = GroqProvider(api_key=KEY, model=MODEL, max_output_tokens=4096)
    ok = {"choices": [{"message": {"content": "{\"candidates\": []}"}, "finish_reason": "stop"}], "model": MODEL,
          "usage": {"total_tokens": 3000}}
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json["max_completion_tokens"])
        return FakeResp(429, err(OTPM_TOO_LARGE)) if len(sent) == 1 else FakeResp(200, ok)

    with patch("aura.agent.groq_provider.requests.post", side_effect=fake_post), patch("time.sleep"):
        assert p.analyze("prompt") == "{\"candidates\": []}"
    assert sent == [4096, 1800]  # the changed request stays below the provider-stated OTPM limit (2000)
    assert p.last_execution_metadata["output_budget_reduced_to"] == 1800


def test_oversized_output_budget_is_not_retried_twice():
    p = GroqProvider(api_key=KEY, model=MODEL, max_output_tokens=4096)
    with patch("aura.agent.groq_provider.requests.post", return_value=FakeResp(429, err(OTPM_TOO_LARGE))) as post, \
            patch("time.sleep"):
        with pytest.raises(RuntimeError):
            p.analyze("prompt")
    assert post.call_count == 2


# ---------------------------------------------------------------- pacing

NOW = datetime(2026, 9, 19, 10, 0, 0, tzinfo=timezone.utc)


def _success(observed, remaining, reset_s, used):
    return {"status": "SUCCESS", "http_status": 200, "responded_at": observed.isoformat(), "usage": {"total_tokens": used},
            "rate_limit": {"remaining_tokens_per_minute": remaining, "reset_tokens": f"{reset_s}s",
                           "reset_tokens_seconds": reset_s, "source": "provider-reported", "observed_at": observed.isoformat()}}


def test_pacing_waits_for_reported_token_reset_when_next_request_would_not_fit():
    ProviderStateStore.record("groq", MODEL, _success(NOW, remaining=1800, reset_s=40.0, used=6200))
    wait, why = capacity_wait_seconds("groq", MODEL, now=NOW + timedelta(seconds=5))
    assert 34.9 <= wait <= 35.1 and "remaining tokens/min" in why


def test_pacing_does_not_wait_when_capacity_is_reported():
    ProviderStateStore.record("groq", MODEL, _success(NOW, remaining=7000, reset_s=40.0, used=3000))
    assert capacity_wait_seconds("groq", MODEL, now=NOW + timedelta(seconds=5)) == (0.0, None)


def test_pacing_respects_retry_after_cooldown_and_bounds_the_wait():
    meta = {"status": "RATE_LIMITED", "failure_category": "RATE_LIMITED", "quota_scope": "SHORT_TERM", "http_status": 429,
            "retry_after_seconds": 30.0, "responded_at": datetime.now(timezone.utc).isoformat()}
    ProviderStateStore.record("groq", MODEL, meta)
    slept = []
    waited = wait_for_provider_capacity(GroqProvider(api_key=KEY, model=MODEL), max_wait_s=90, sleep=slept.append)
    assert slept and 29 <= waited <= 32
    slept.clear()
    assert wait_for_provider_capacity(GroqProvider(api_key=KEY, model=MODEL), max_wait_s=10, sleep=slept.append) == 0.0
    assert not slept  # longer than the bound: not waited; preflight decides


def test_pacing_never_waits_out_a_daily_quota():
    meta = {"status": "RATE_LIMITED", "failure_category": "RATE_LIMITED", "quota_scope": "DAILY", "http_status": 429,
            "responded_at": NOW.isoformat(), "rate_limit": {"reset_requests_seconds": 3600.0}}
    ProviderStateStore.record("groq", MODEL, meta)
    assert capacity_wait_seconds("groq", MODEL, now=NOW + timedelta(seconds=1)) == (0.0, None)


# ---------------------------------------------------------------- sequential Run All

LAB = settings.TEST_LAB_DIR
SITES = [{"id": n, "name": n, "url": f"http://127.0.0.1:8999/{n}/", "dir": LAB / n} for n in (
    "01_accessibility_suite", "02_ui_ux_suite", "03_navigation_interaction_suite",
    "04_responsive_runtime_suite", "05_mixed_realistic_suite")]


class _Agg:
    all_active_findings = []


class FakeEngine:
    """Records call order and concurrency; can block the provider before a given suite."""

    def __init__(self, block_before=None):
        self.calls, self.active, self.max_active, self.block_before = [], 0, 0, block_before

        class P:
            provider_key, model = "mock", "mock"
        self.orchestrator = type("O", (), {"provider": P()})()

    def run_analysis(self, url, **kw):
        name = url.rstrip("/").split("/")[-1]
        if name == self.block_before:
            raise ProviderPreflightBlocked(PreflightResult(provider="groq", model=MODEL, status="QUOTA_EXHAUSTED",
                                                           blocked=True, reason="daily quota", action="stop"))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append(name)
        self.active -= 1
        return {"aggregation": _Agg(), "evaluation": {"site_id": name, "benchmark_ai_status": "EVALUATED"}}


def test_run_all_is_sequential_in_suite_order():
    eng = FakeEngine()
    out = run_all_suites(eng, SITES, viewport_preset="Desktop (1440x900)", headless=True, enable_interactions=True, skip_ai=False)
    assert eng.calls == [s["id"] for s in SITES] and eng.max_active == 1
    assert out["stopped"] is None and len(out["suite_evals"]) == 5


def test_run_all_keeps_completed_suites_and_marks_the_rest_not_run():
    eng = FakeEngine(block_before="04_responsive_runtime_suite")
    out = run_all_suites(eng, SITES, viewport_preset="Desktop (1440x900)", headless=True, enable_interactions=True, skip_ai=False)
    assert eng.calls == ["01_accessibility_suite", "02_ui_ux_suite", "03_navigation_interaction_suite"]
    assert out["stopped"]["status"] == "QUOTA_EXHAUSTED"
    for n in ("04_responsive_runtime_suite", "05_mixed_realistic_suite"):
        ev = out["suite_evals"][n]
        assert ev["benchmark_ai_status"] == "NOT_EVALUABLE"
        assert ev["true_positives"] is None and ev["false_negatives"] is None  # no invented numbers
        assert ev["expected_count"] > 0  # expected defects still come from ground truth


def test_run_all_first_suite_blocked_raises_for_explicit_user_choice():
    with pytest.raises(ProviderPreflightBlocked):
        run_all_suites(FakeEngine(block_before="01_accessibility_suite"), SITES, viewport_preset="x", headless=True,
                       enable_interactions=True, skip_ai=False)


def test_not_run_suites_are_excluded_from_aggregate_metrics():
    ev = EvaluationEngine.not_run(LAB / "05_mixed_realistic_suite", "provider unavailable")
    sm = EvaluationEngine.evaluate_suite(LAB, {}, precomputed={s["id"]: ev if s["id"].startswith("05") else
                                                               EvaluationEngine.evaluate(s["dir"], []) for s in SITES})
    assert "05_mixed_realistic_suite" in sm["not_evaluable_suites"]
