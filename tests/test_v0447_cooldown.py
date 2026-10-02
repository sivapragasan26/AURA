"""
V0.4.4.7 regression tests: provider cooldown / preflight state lifecycle.
All provider responses are mocked; no live Groq or Gemini request is made.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from aura.agent.gemini_provider import GeminiProvider
from aura.agent.groq_provider import GroqProvider
from aura.agent.provider_status import (
    PreflightResult, PreflightStatus, ProviderStateStore, run_preflight, _parse_ts,
)

MODEL = "qwen/qwen3.8-27b"
KEY = "gsk_CooldownTestFakeKey000000000"
T0 = datetime(2026, 9, 18, 16, 50, 11, tzinfo=timezone.utc)


def groq():
    return GroqProvider(api_key=KEY, model=MODEL)


def short_429(responded_at: datetime, retry_after: float = 120.0):
    return {"status": "RATE_LIMITED", "failure_category": "RATE_LIMITED", "quota_scope": "SHORT_TERM", "http_status": 429,
            "retry_after_seconds": retry_after, "responded_at": responded_at.isoformat(),
            "rate_limit": {"retry_after": str(int(retry_after)), "retry_after_seconds": retry_after,
                           "remaining_requests_per_day": 999, "source": "provider-reported",
                           "observed_at": responded_at.isoformat()}}


def pf(now):
    return run_preflight(groq(), check_remote=False, now=now)


# A / B / C
def test_retry_after_120_active_then_expires():
    ProviderStateStore.record("groq", MODEL, short_429(T0, 120))
    first = pf(T0 + timedelta(seconds=1))
    assert first.status == "COOLDOWN_ACTIVE" and first.blocked
    assert first.blocked_until == (T0 + timedelta(seconds=120)).isoformat()   # response time + Retry-After

    later = pf(T0 + timedelta(seconds=60))
    assert later.status == "COOLDOWN_ACTIVE" and later.blocked
    assert later.seconds_remaining(T0 + timedelta(seconds=60)) == 60.0

    expired = pf(T0 + timedelta(seconds=121))
    assert expired.status != "COOLDOWN_ACTIVE" and not expired.blocked
    assert expired.status == "PREFLIGHT_REQUIRED"                              # not READY: no fresh evidence
    assert expired.cooldown_expired_at == (T0 + timedelta(seconds=120)).isoformat()
    assert "availability has not been re-checked" in expired.reason


# D
def test_expired_cooldown_does_not_extend_itself():
    old = short_429(T0, 120)
    ProviderStateStore.record("groq", MODEL, old)
    assert not pf(T0 + timedelta(seconds=200)).blocked
    # the SAME old response recorded again later (e.g. stale metadata on a reused provider object)
    ProviderStateStore.record("groq", MODEL, old, now=T0 + timedelta(seconds=300))
    again = pf(T0 + timedelta(seconds=301))
    assert again.status != "COOLDOWN_ACTIVE" and not again.blocked
    # repeated preflights never re-create it either
    for s in (400, 500, 600):
        assert not pf(T0 + timedelta(seconds=s)).blocked
    # metadata without a response timestamp is anchored to the original response header time, not "now"
    no_ts = {k: v for k, v in old.items() if k != "responded_at"}
    ProviderStateStore.record("groq", MODEL, no_ts, now=T0 + timedelta(seconds=700))
    assert not pf(T0 + timedelta(seconds=701)).blocked


# E
def test_new_429_creates_new_cooldown():
    ProviderStateStore.record("groq", MODEL, short_429(T0, 120))
    assert not pf(T0 + timedelta(seconds=130)).blocked
    t1 = T0 + timedelta(seconds=140)
    ProviderStateStore.record("groq", MODEL, short_429(t1, 30))
    fresh = pf(t1 + timedelta(seconds=5))
    assert fresh.status == "COOLDOWN_ACTIVE" and fresh.blocked_until == (t1 + timedelta(seconds=30)).isoformat()
    assert not pf(t1 + timedelta(seconds=31)).blocked


def test_groq_429_response_is_timestamped_and_recorded_from_response_time():
    class R:
        status_code = 429
        headers = {"retry-after": "32", "x-ratelimit-remaining-requests": "999"}
        text = "{}"
        def json(self):
            return {"error": {"message": "Rate limit reached for tokens per minute"}}
    provider = groq()
    with patch("aura.agent.groq_provider.requests.post", return_value=R()), patch("time.sleep"):
        with pytest.raises(RuntimeError):
            provider.analyze("p")
    meta = provider.last_execution_metadata
    responded = _parse_ts(meta["responded_at"])
    assert responded.tzinfo is not None
    entry = ProviderStateStore.record("groq", MODEL, meta)
    assert _parse_ts(entry["aura_tracked"]["cooldown_until"]) == responded + timedelta(seconds=32)


# F
def test_timezone_aware_utc_comparison():
    ProviderStateStore.record("groq", MODEL, short_429(T0, 120))
    # same instant expressed in IST (+05:30): still active, compared as instants not strings
    ist = timezone(timedelta(hours=5, minutes=30))
    assert pf((T0 + timedelta(seconds=60)).astimezone(ist)).status == "COOLDOWN_ACTIVE"
    assert not pf((T0 + timedelta(seconds=121)).astimezone(ist)).blocked
    # naive timestamps are read as UTC, never local time, and never compared naive vs aware
    assert _parse_ts("2026-09-18T16:50:55") == datetime(2026, 9, 18, 16, 50, 55, tzinfo=timezone.utc)
    assert _parse_ts("2026-09-18T22:20:55+05:30") == datetime(2026, 9, 18, 16, 50, 55, tzinfo=timezone.utc)


# G + acceptance: the exact stale timestamp from the reported incident
def test_reported_stale_cooldown_no_longer_blocks():
    stuck_until = "2026-09-18T16:50:55.047489+00:00"
    responded = _parse_ts(stuck_until) - timedelta(seconds=44)
    ProviderStateStore.record("groq", MODEL, short_429(responded, 44))
    assert ProviderStateStore.get("groq", MODEL)["aura_tracked"]["cooldown_until"] == stuck_until
    after = _parse_ts(stuck_until) + timedelta(minutes=2)
    result = pf(after)
    assert result.status == "PREFLIGHT_REQUIRED" and not result.blocked
    # and it stays unblocked indefinitely afterwards
    for hours in (1, 24, 24 * 30):
        assert not pf(after + timedelta(hours=hours)).blocked
    # the stored cooldown is cleared and kept only as history
    tracked = ProviderStateStore.get("groq", MODEL)["aura_tracked"]
    assert tracked["cooldown_until"] is None and tracked["expired_cooldown_until"] == stuck_until


def test_cached_snapshot_goes_stale_when_block_ends():
    ProviderStateStore.record("groq", MODEL, short_429(T0, 44))
    snap = pf(T0 + timedelta(seconds=1))
    assert not snap.is_stale(T0 + timedelta(seconds=30))
    assert snap.is_stale(T0 + timedelta(seconds=45))                      # block ended
    ready = PreflightResult(provider="groq", model=MODEL, status="READY", blocked=False, reason="", action="Proceed",
                            checked_at=T0.isoformat())
    assert ready.is_stale(T0 + timedelta(seconds=61))                        # any snapshot ages out


# J
def test_daily_quota_exhaustion_stays_distinct_from_cooldown():
    daily = {"status": "RATE_LIMITED", "failure_category": "RATE_LIMITED", "quota_scope": "DAILY", "http_status": 429,
             "responded_at": T0.isoformat()}
    ProviderStateStore.record("gemini", "gemini-3.6-flash", daily)
    gem = run_preflight(GeminiProvider(api_key="AIzaSyCooldownFakeKey0000000", model="gemini-3.6-flash"),
                        check_remote=False, now=T0 + timedelta(minutes=5))
    assert gem.status == "QUOTA_EXHAUSTED" and gem.blocked                   # not COOLDOWN_ACTIVE
    assert "AURA estimate" in gem.reason
    # a short cooldown on Groq is independent of the Gemini daily state
    ProviderStateStore.record("groq", MODEL, short_429(T0, 30))
    assert pf(T0 + timedelta(minutes=5)).status == "PREFLIGHT_REQUIRED"
    assert run_preflight(GeminiProvider(api_key="AIzaSyCooldownFakeKey0000000", model="gemini-3.6-flash"),
                         check_remote=False, now=T0 + timedelta(minutes=5)).status == "QUOTA_EXHAUSTED"


# H / I: dashboard
def _dashboard(preflight_blocked=None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("C:/Users/somanathan/Desktop/Final_year/app.py", default_timeout=120)
    at.session_state["groq_api_key"] = KEY
    at.session_state["provider_select"] = "groq"
    if preflight_blocked:
        at.session_state["preflight_blocked"] = preflight_blocked
    return at


def _texts(at):
    out = []
    for kind in ("caption", "error", "info", "warning", "markdown"):
        out += [str(e.value) for e in getattr(at, kind)]
    return out


def test_dashboard_shows_remaining_cooldown_seconds():
    now = datetime.now(timezone.utc)
    until = now - timedelta(seconds=10) + timedelta(seconds=120)
    ProviderStateStore.record("groq", MODEL, short_429(now - timedelta(seconds=10), 120))
    with patch("aura.agent.groq_provider.requests.post") as post, patch("aura.agent.groq_provider.requests.get") as get:
        at = _dashboard()
        before = datetime.now(timezone.utc)
        at.run()
        after = datetime.now(timezone.utc)
    assert not at.exception, at.exception
    texts = _texts(at)
    assert any("COOLDOWN_ACTIVE" in t and "BLOCKED" in t for t in texts)
    shown = [t for t in texts if t.startswith("Retry available in:")]
    # remaining time is computed at render time from the absolute UTC end, so it lies between these bounds
    lo, hi = int((until - after).total_seconds()), int((until - before).total_seconds()) + 1
    assert shown and lo <= int(shown[0].split(":")[1].split()[0]) <= hi
    post.assert_not_called()
    get.assert_not_called()                                                  # render uses local state only


def test_dashboard_after_expiry_no_longer_shows_old_block():
    stuck_until = "2026-09-18T16:50:55.047489+00:00"
    responded = _parse_ts(stuck_until) - timedelta(seconds=44)
    ProviderStateStore.record("groq", "qwen/qwen3.6-27b", short_429(responded, 44))
    # the snapshot a blocked audit left in session state (the stale display from the incident)
    old_block = run_preflight(groq_36(), check_remote=False, now=responded + timedelta(seconds=10))
    assert old_block.status == "COOLDOWN_ACTIVE"
    with patch("aura.agent.groq_provider.requests.post") as post, patch("aura.agent.groq_provider.requests.get"):
        at = _dashboard(preflight_blocked={"result": old_block, "mode": "all"})
        at.run()
    assert not at.exception, at.exception
    texts = _texts(at)
    assert not any("COOLDOWN_ACTIVE" in t and "BLOCKED" in t for t in texts)
    assert not any("preflight BLOCKED" in t for t in texts)
    assert any("cooldown expired" in t.lower() and "preflight required" in t.lower() for t in texts)
    assert "preflight_blocked" not in at.session_state
    post.assert_not_called()


def groq_36():
    return GroqProvider(api_key=KEY, model="qwen/qwen3.6-27b")
