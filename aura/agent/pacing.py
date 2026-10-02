"""
Pacing between sequential AI requests (Test Lab "Run All", one request at a time).

Uses only what the provider itself reported on its previous response (never invented quota values):
  - an active short-term cooldown (provider Retry-After, stored by ProviderStateStore);
  - the provider-reported remaining tokens per minute and their reset time (Groq x-ratelimit-*-tokens),
    compared with the token usage the provider reported for the previous request.
Daily quotas are not waited out: preflight blocks those and the run reports the remaining suites as not run.
"""
import time
from datetime import timedelta
from typing import Any, Callable, Optional, Tuple

from aura.agent.provider_status import ProviderStateStore, _now, _parse_ts

TPM_SAFETY_MARGIN = 1.1  # the next request is assumed ~10% larger than the last one


def capacity_wait_seconds(provider_key: str, model: str, now=None) -> Tuple[float, Optional[str]]:
    """Seconds to wait before the next request is expected to fit the provider's reported limits."""
    now = now or _now()
    state = ProviderStateStore.get(provider_key, model) or {}
    waits = []
    tracked = state.get("aura_tracked") or {}
    until = _parse_ts(tracked.get("cooldown_until"))
    if until and state.get("quota_scope") != "DAILY" and until > now:
        waits.append(((until - now).total_seconds(), f"provider cooldown ({tracked.get('basis')})"))

    reported = state.get("provider_reported") or {}
    remaining = reported.get("remaining_tokens_per_minute")
    reset_s = reported.get("reset_tokens_seconds")
    observed = _parse_ts(reported.get("observed_at"))
    used = (state.get("last_usage") or {}).get("total_tokens")
    if isinstance(remaining, int) and isinstance(used, int) and reset_s is not None and observed:
        if remaining < used * TPM_SAFETY_MARGIN:
            ready_at = observed + timedelta(seconds=float(reset_s))
            if ready_at > now:
                waits.append(((ready_at - now).total_seconds(),
                              f"provider-reported remaining tokens/min {remaining} < last request {used}"))
    if not waits:
        return 0.0, None
    return max(waits, key=lambda w: w[0])


def wait_for_provider_capacity(provider: Any, max_wait_s: float = 90.0,
                               on_wait: Optional[Callable[[float, str], None]] = None,
                               sleep: Callable[[float], None] = time.sleep) -> float:
    """Waits (bounded) until the provider's reported limits allow the next request. Returns seconds waited."""
    key = getattr(provider, "provider_key", "unknown")
    if key in ("mock", "unknown"):
        return 0.0
    wait, reason = capacity_wait_seconds(key, getattr(provider, "model", "default") or "default")
    if wait <= 0 or wait > max_wait_s:
        return 0.0  # nothing to wait for, or too long: preflight decides (it never runs an inference)
    wait = round(wait + 1.0, 1)
    if on_wait:
        on_wait(wait, reason or "")
    sleep(wait)
    return wait
