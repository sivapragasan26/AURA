"""
Provider availability: tracked provider state and the pre-audit preflight gate.

The preflight never runs a model inference. It combines:
  1. local configuration (key present, documented model capabilities),
  2. AURA-tracked state from previous real responses (last HTTP status, quota scope, cooldowns),
  3. provider-reported rate-limit values from previous response headers (Groq x-ratelimit-*),
  4. an optional non-inference remote check (model metadata endpoint: validates key + model).

Values are always labelled: "provider-reported" (from provider responses/headers) versus
"AURA estimate" (computed locally, e.g. Gemini's daily reset at midnight Pacific time).
Nothing here stores or logs credentials.
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from aura.config import settings
from aura.utils.logger import logger


class PreflightStatus(str, Enum):
    READY = "READY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AUTH_INVALID = "AUTH_INVALID"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    # A previously recorded block has ended (e.g. cooldown expired) but availability was not re-checked.
    # Not blocking, and NOT a claim that the provider is ready.
    PREFLIGHT_REQUIRED = "PREFLIGHT_REQUIRED"
    UNKNOWN = "UNKNOWN"


# UNKNOWN / PREFLIGHT_REQUIRED do not block: AURA has no current evidence either way
BLOCKING_STATUSES = {s for s in PreflightStatus} - {PreflightStatus.READY, PreflightStatus.UNKNOWN, PreflightStatus.PREFLIGHT_REQUIRED}

# A recent successful request counts as READY evidence for this long
RECENT_SUCCESS_WINDOW = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """ISO timestamp -> timezone-aware UTC datetime. Naive values are treated as UTC (never local time)."""
    try:
        ts = datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None
    if ts is None:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def next_pacific_midnight(now: datetime) -> datetime:
    """Gemini API daily quotas reset at midnight Pacific time (per Google's rate-limit docs)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except Exception:
        tz = timezone(timedelta(hours=-8))
    local = now.astimezone(tz)
    return (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


class ProviderStateStore:
    """Persisted per provider+model state derived from real provider responses (no credentials)."""

    path: Path = settings.RUNS_DIR / "provider_state.json"

    @classmethod
    def _load(cls) -> Dict[str, Any]:
        try:
            return json.loads(cls.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @classmethod
    def _save(cls, data: Dict[str, Any]) -> None:
        try:
            cls.path.parent.mkdir(parents=True, exist_ok=True)
            cls.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning(f"Could not persist provider state: {e}")

    @staticmethod
    def key(provider: str, model: str) -> str:
        return f"{provider}:{model}"

    @classmethod
    def get(cls, provider: str, model: str) -> Optional[Dict[str, Any]]:
        return cls._load().get(cls.key(provider, model))

    @classmethod
    def clear(cls, provider: str, model: str) -> None:
        data = cls._load()
        data.pop(cls.key(provider, model), None)
        cls._save(data)

    @classmethod
    def record(cls, provider: str, model: str, meta: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Records the outcome of a real provider request (success or failure).

        Cooldowns are anchored to when the provider RESPONDED (meta["responded_at"], else the rate-limit
        header observation time), never to the time this method runs: re-recording the same old response
        cannot move its cooldown forward. A response that is not newer than the stored one is ignored, so
        only a NEW provider response can establish a new cooldown.
        """
        if not meta or provider in ("mock", "unknown"):
            return {}
        rate = dict(meta.get("rate_limit") or {})
        responded_at = _parse_ts(meta.get("responded_at")) or _parse_ts(rate.get("observed_at")) or now or _now()
        data = cls._load()
        previous = data.get(cls.key(provider, model))
        prev_at = _parse_ts((previous or {}).get("observed_at"))
        if prev_at and responded_at <= prev_at:
            return previous  # same or older response: it cannot replace or extend the stored state
        entry: Dict[str, Any] = {
            "observed_at": responded_at.isoformat(),
            "last_status": meta.get("status"),
            "last_http_status": meta.get("http_status"),
            "failure_category": meta.get("failure_category"),
            "quota_scope": meta.get("quota_scope"),
            "provider_reported": rate,  # only values present in provider responses
            "last_usage": meta.get("usage") or None,  # provider-reported token usage of that request
            "provider_limit_status": meta.get("provider_limit_status"),
            "aura_tracked": {"cooldown_until": None, "basis": None},
        }
        tracked = entry["aura_tracked"]
        if meta.get("failure_category") == "RATE_LIMITED":
            if meta.get("quota_scope") == "DAILY":
                reset_s = rate.get("reset_requests_seconds")
                if reset_s is not None:
                    tracked["cooldown_until"] = (responded_at + timedelta(seconds=reset_s)).isoformat()
                    tracked["basis"] = "provider-reported x-ratelimit-reset-requests"
                elif provider == "gemini":
                    tracked["cooldown_until"] = next_pacific_midnight(responded_at).isoformat()
                    tracked["basis"] = "AURA estimate: Gemini daily quotas reset at midnight Pacific time"
                else:
                    tracked["basis"] = "daily quota exhausted; provider supplied no reset time"
            else:
                wait = meta.get("retry_after_seconds") or rate.get("retry_after_seconds")
                if wait is not None:
                    tracked["cooldown_until"] = (responded_at + timedelta(seconds=float(wait))).isoformat()
                    tracked["basis"] = "provider-reported retry-after"
        data[cls.key(provider, model)] = entry
        cls._save(data)
        return entry

    @classmethod
    def expire_cooldown(cls, provider: str, model: str, now: Optional[datetime] = None) -> None:
        """Clears an expired short-term cooldown (kept as history). Does not claim the provider is available."""
        data = cls._load()
        entry = data.get(cls.key(provider, model))
        if not entry:
            return
        tracked = entry.get("aura_tracked") or {}
        if tracked.get("cooldown_until"):
            entry["aura_tracked"] = {"cooldown_until": None, "basis": None,
                                     "expired_cooldown_until": tracked["cooldown_until"],
                                     "expired_basis": tracked.get("basis"),
                                     "expiry_noted_at": (now or _now()).isoformat()}
            data[cls.key(provider, model)] = entry
            cls._save(data)


@dataclass
class PreflightResult:
    provider: str
    model: str
    status: str
    blocked: bool
    reason: str
    action: str
    checked_remotely: bool = False
    consumed_inference: bool = False  # always False: preflight never runs a model inference
    last_http_status: Optional[int] = None
    provider_reported: Dict[str, Any] = field(default_factory=dict)
    aura_tracked: Dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: _now().isoformat())
    blocked_until: Optional[str] = None      # absolute UTC end of a time-bound block (cooldown / quota reset)
    cooldown_expired_at: Optional[str] = None  # a previous cooldown that has expired (not proof of availability)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def seconds_remaining(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds until a time-bound block ends, computed at call time (never a stored countdown)."""
        until = _parse_ts(self.blocked_until)
        if until is None:
            return None
        return max(0.0, (until - (now or _now())).total_seconds())

    def is_stale(self, now: Optional[datetime] = None, max_age_s: float = 60.0) -> bool:
        """
        A snapshot must not be displayed or acted on once its block has ended, or once it is older than
        max_age_s (it reflects provider state at checked_at only).
        """
        now = now or _now()
        until = _parse_ts(self.blocked_until)
        if until is not None and now >= until:
            return True
        checked = _parse_ts(self.checked_at)
        return checked is None or (now - checked).total_seconds() > max_age_s


class ProviderPreflightBlocked(RuntimeError):
    """Raised before any browser work when the provider is known to be unusable."""

    def __init__(self, result: PreflightResult):
        self.result = result
        super().__init__(f"AI provider preflight BLOCKED ({result.status}): {result.reason}")


def _result(provider, model, status: PreflightStatus, reason: str, now: Optional[datetime] = None, **kw) -> PreflightResult:
    blocked = status in BLOCKING_STATUSES
    action = "Do not start AI-dependent audit" if blocked else "Proceed"
    return PreflightResult(provider=provider, model=model, status=status.value, blocked=blocked,
                           reason=reason, action=action, checked_at=(now or _now()).isoformat(), **kw)


def run_preflight(ai_provider: Any, check_remote: Optional[bool] = None, needs_image: bool = True,
                  now: Optional[datetime] = None) -> PreflightResult:
    """
    Decides whether an AI-dependent audit should start. Never performs a model inference.

    Cooldown lifecycle: a short-term 429 with Retry-After N stores cooldown_until = response time + N (UTC).
    While now < cooldown_until the result is COOLDOWN_ACTIVE (blocked). Once now >= cooldown_until the
    cooldown is cleared and preflight continues; without a fresh check the result is PREFLIGHT_REQUIRED
    (not blocked, and explicitly NOT a claim that the provider is available).
    """
    now = (now or _now()).astimezone(timezone.utc)
    provider = getattr(ai_provider, "provider_key", "unknown")
    model = getattr(ai_provider, "model", "default") or "default"
    check_remote = settings.PREFLIGHT_REMOTE_CHECK if check_remote is None else check_remote

    if provider == "mock":
        return _result(provider, "mock", PreflightStatus.READY, "Mock provider (scripted, no remote service)", now=now)

    if not getattr(ai_provider, "api_key", None):
        return _result(provider, model, PreflightStatus.NOT_CONFIGURED, "No API key configured for this provider", now=now)

    caps = ai_provider.capabilities() if hasattr(ai_provider, "capabilities") else None
    if needs_image and caps is not None and not caps.get("image_input"):
        return _result(provider, model, PreflightStatus.CAPABILITY_UNSUPPORTED,
                       f"Model '{model}' does not support image input required for visual analysis", now=now)

    state = ProviderStateStore.get(provider, model) or {}
    reported = state.get("provider_reported") or {}
    tracked = state.get("aura_tracked") or {}
    last_http = state.get("last_http_status")
    cooldown_until = _parse_ts(tracked.get("cooldown_until"))
    observed_at = _parse_ts(state.get("observed_at"))
    expired_at: Optional[str] = tracked.get("expired_cooldown_until")
    common = {"last_http_status": last_http, "provider_reported": reported, "aura_tracked": tracked}

    # Known exhaustion / cooldown from real previous responses
    if state.get("failure_category") == "RATE_LIMITED":
        if state.get("quota_scope") == "DAILY":
            if cooldown_until is None and observed_at and now - observed_at < timedelta(hours=24):
                return _result(provider, model, PreflightStatus.QUOTA_EXHAUSTED,
                               "Daily quota exhausted (last provider response HTTP 429); provider-reported reset: unavailable",
                               now=now, blocked_until=(observed_at + timedelta(hours=24)).isoformat(), **common)
            if cooldown_until and now < cooldown_until:
                return _result(provider, model, PreflightStatus.QUOTA_EXHAUSTED,
                               f"Daily quota exhausted (last provider response HTTP 429); reset ({tracked.get('basis')}): {cooldown_until.isoformat()}",
                               now=now, blocked_until=cooldown_until.isoformat(), **common)
        elif cooldown_until:
            if now < cooldown_until:
                return _result(provider, model, PreflightStatus.COOLDOWN_ACTIVE,
                               f"Rate limited; cooldown until {cooldown_until.isoformat()} ({tracked.get('basis')})",
                               now=now, blocked_until=cooldown_until.isoformat(), **common)
            # expired: clear it (kept as history) and continue preflight
            ProviderStateStore.expire_cooldown(provider, model, now=now)
            expired_at = cooldown_until.isoformat()
            tracked = (ProviderStateStore.get(provider, model) or {}).get("aura_tracked") or {}
            common["aura_tracked"] = tracked

    if reported.get("remaining_requests_per_day") == 0 and observed_at:
        reset_s = reported.get("reset_requests_seconds")
        reset_at = observed_at + timedelta(seconds=reset_s) if reset_s is not None else None
        if reset_at is None or now < reset_at:
            return _result(provider, model, PreflightStatus.QUOTA_EXHAUSTED,
                           f"Provider-reported remaining requests (per day): 0; provider-reported reset: {reported.get('reset_requests', 'unavailable')}",
                           now=now, blocked_until=reset_at.isoformat() if reset_at else None, **common)

    # Optional non-inference remote check (auth + model metadata)
    if check_remote and hasattr(ai_provider, "check_availability"):
        remote = ai_provider.check_availability() or {}
        merged_reported = {**reported, **(remote.get("provider_reported") or {})}
        status = PreflightStatus(remote.get("status", "UNKNOWN"))
        retry_after = (remote.get("provider_reported") or {}).get("retry_after_seconds")
        blocked_until = (now + timedelta(seconds=float(retry_after))).isoformat() if status == PreflightStatus.RATE_LIMITED and retry_after else None
        return _result(provider, model, status, remote.get("detail") or status.value, now=now, checked_remotely=True,
                       last_http_status=remote.get("http_status", last_http), provider_reported=merged_reported,
                       aura_tracked=tracked, blocked_until=blocked_until, cooldown_expired_at=expired_at)

    if expired_at:
        return _result(provider, model, PreflightStatus.PREFLIGHT_REQUIRED,
                       f"Cooldown expired (previous cooldown ended {expired_at}). This only means the old cooldown is over; "
                       "provider availability has not been re-checked", now=now, cooldown_expired_at=expired_at, **common)
    if state.get("last_status") == "SUCCESS" and observed_at and now - observed_at < RECENT_SUCCESS_WINDOW:
        return _result(provider, model, PreflightStatus.READY,
                       f"Last request succeeded at {observed_at.isoformat()} (AURA tracked)", now=now, **common)
    if state.get("failure_category"):
        return _result(provider, model, PreflightStatus.PREFLIGHT_REQUIRED,
                       f"Last recorded provider response: {state.get('last_status')} (HTTP {last_http}); availability not re-checked",
                       now=now, **common)
    return _result(provider, model, PreflightStatus.UNKNOWN,
                   "No provider response recorded yet; availability not checked remotely", now=now, **common)
