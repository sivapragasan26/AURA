"""
AURA Groq AI Provider.

Groq's OpenAI-compatible Chat Completions API (https://api.groq.com/openai/v1), called with `requests` so
the rate-limit response headers can be captured as provider-reported quota information.

- Multimodal: the screenshot is sent as an image_url content part (data URL), never as text.
- Structured output: JSON mode (response_format={"type": "json_object"}); reasoning models run with
  reasoning_format="hidden" (Groq requires parsed/hidden with JSON mode) so the content is only JSON.
- No silent model fallback: the configured model is the only model used.
- Retry policy mirrors the Gemini provider: a daily request quota (x-ratelimit-remaining-requests == 0)
  is never retried; a short-term 429 is retried at most once when retry-after is short; 5xx/network
  errors are retried with backoff; 4xx configuration errors are not retried.
"""
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests

from aura.agent.provider import AIProvider
from aura.config import settings
from aura.config.models import MODEL_CAPABILITIES
from aura.security.credentials import sanitize_provider_error
from aura.utils.logger import logger

GROQ_API_BASE = "https://api.groq.com/openai/v1"

# Groq documents: *-requests headers always refer to requests per DAY, *-tokens headers to tokens per MINUTE
RATE_LIMIT_HEADERS = {
    "x-ratelimit-limit-requests": "limit_requests_per_day",
    "x-ratelimit-remaining-requests": "remaining_requests_per_day",
    "x-ratelimit-reset-requests": "reset_requests",
    "x-ratelimit-limit-tokens": "limit_tokens_per_minute",
    "x-ratelimit-remaining-tokens": "remaining_tokens_per_minute",
    "x-ratelimit-reset-tokens": "reset_tokens",
    "retry-after": "retry_after",
}


def parse_groq_duration(value: Optional[str]) -> Optional[float]:
    """'2m59.56s' -> 179.56, '7.66s' -> 7.66, '1h2m' -> 3720, '250ms' -> 0.25, '2' -> 2.0."""
    if value is None:
        return None
    value = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    total, matched = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", value):
        matched = True
        total += float(num) * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[unit]
    return round(total, 3) if matched else None


# Below this an answer cannot carry even one complete finding, so a retry would be pointless.
MIN_OUTPUT_BUDGET = 512


def parse_rate_limit_headers(headers: Any) -> Dict[str, Any]:
    """Provider-reported rate-limit values; only headers actually present are returned."""
    if not headers:
        return {}
    lower = {str(k).lower(): v for k, v in dict(headers).items()}
    out: Dict[str, Any] = {}
    for header, name in RATE_LIMIT_HEADERS.items():
        if header not in lower:
            continue
        raw = lower[header]
        if name.startswith(("limit_", "remaining_")):
            try:
                out[name] = int(float(raw))
            except (TypeError, ValueError):
                out[name] = raw
        else:
            out[name] = raw
            seconds = parse_groq_duration(raw)
            if seconds is not None:
                out[f"{name}_seconds"] = seconds
    if out:
        out["source"] = "provider-reported"
        out["observed_at"] = datetime.now(timezone.utc).isoformat()
    return out


def classify_groq_response(status_code: int, body: Any, rate_limit: Dict[str, Any]) -> Tuple[str, bool, Optional[str]]:
    """Returns (failure_category, retryable, quota_scope) for a non-2xx Groq response."""
    err = body.get("error", {}) if isinstance(body, dict) else {}
    code = str(err.get("code") or "").lower()
    message = str(err.get("message") or body or "").lower()

    if status_code == 429:
        daily = rate_limit.get("remaining_requests_per_day") == 0 or "per day" in message or "rpd" in message
        return "RATE_LIMITED", not daily, ("DAILY" if daily else "SHORT_TERM")
    if status_code == 401:
        return "AUTHENTICATION_ERROR", False, None
    if status_code == 403:
        return "PERMISSION_ERROR", False, None
    if status_code == 404 or code in ("model_not_found", "model_decommissioned"):
        return "MODEL_NOT_FOUND", False, None
    if status_code == 413:
        return "REQUEST_TOO_LARGE", False, None
    if status_code == 400:
        if code == "json_validate_failed":
            return "AI_RESPONSE_INVALID", False, None
        if any(k in message for k in ("image", "vision", "multimodal", "does not support", "not supported")):
            return "CAPABILITY_UNSUPPORTED", False, None
        return "BAD_REQUEST", False, None
    if status_code >= 500 or status_code == 498:
        return "TRANSIENT_PROVIDER_ERROR", True, None
    return "BAD_REQUEST", False, None


def optimize_image_for_groq(screenshot_base64: Optional[str], max_dim: int = 512, quality: int = 60) -> Tuple[Optional[str], str]:
    """
    Resizes and compresses base64 screenshot to fit comfortably within Groq's 7,000 ITPM input limit.
    A full 1440x900 PNG can consume 4,000-5,000 vision tokens.
    Resizing to max_dim 512 with JPEG quality 60 consumes ~800-1,100 vision tokens.
    """
    if not screenshot_base64:
        return None, "image/png"
    try:
        import base64
        import io
        from PIL import Image

        raw_bytes = base64.b64decode(screenshot_base64)
        img = Image.open(io.BytesIO(raw_bytes))
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
    except Exception as e:
        logger.warning(f"[GroqProvider] Image optimization skipped: {e}")
        return screenshot_base64, "image/png"


def compact_prompt_for_groq(prompt: str, max_dom_elements: int = 20, max_chars: int = 9000) -> str:
    """
    Compacts AURA prompt for Groq to stay safely under its 7,000 ITPM limit.
    Preserves instructions, schema, metadata, and the top N interactive DOM elements.
    """
    if not prompt:
        return prompt
    m = re.search(r"```json\s*(.*?)\s*```", prompt, re.DOTALL)
    if not m:
        if len(prompt) > max_chars:
            return prompt[:max_chars] + "\n\nRespond with valid JSON."
        return prompt
    try:
        data = json.loads(m.group(1))
        if isinstance(data, dict):
            dom = data.get("targeted_dom", [])
            if len(dom) > max_dom_elements:
                data["targeted_dom"] = dom[:max_dom_elements]
            compact_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            new_prompt = prompt[:m.start()] + "```json\n" + compact_json + "\n```" + prompt[m.end():]
            if len(new_prompt) > max_chars:
                data["targeted_dom"] = dom[:15]
                compact_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                new_prompt = prompt[:m.start()] + "```json\n" + compact_json + "\n```" + prompt[m.end():]
            return new_prompt
    except Exception as e:
        logger.debug(f"[GroqProvider] Prompt JSON compaction skipped: {e}")
    if len(prompt) > max_chars:
        return prompt[:max_chars] + "\n\nRespond with valid JSON."
    return prompt



def classify_rate_limit_kind(message: Any, rate_limit: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    """
    Which provider limit a 429/413 refers to, from the provider's own message/headers (never guessed from the
    status code alone): RPM, TPM, ITPM (input tokens per minute), OTPM (output tokens per minute), RPD, TPD, or None when not stated.
    oversized=True means the REQUEST ITSELF exceeds the limit ("Request too large", "exceed enforced limit"):
    waiting cannot make the unchanged request succeed, so it must not be retried as-is.
    """
    m = str(message or "").lower()
    oversized = any(k in m for k in ("request too large", "exceed enforced limit", "exceeds the limit", "reduce your message size"))
    if "input tokens per minute" in m or "(itpm)" in m:
        kind = "ITPM"
    elif "output tokens per minute" in m or "(otpm)" in m:
        kind = "OTPM"
    elif "tokens per day" in m or "(tpd)" in m:
        kind = "TPD"
    elif "requests per day" in m or "(rpd)" in m:
        kind = "RPD"
    elif "tokens per minute" in m or "(tpm)" in m:
        kind = "TPM"
    elif "requests per minute" in m or "(rpm)" in m:
        kind = "RPM"
    elif rate_limit.get("remaining_requests_per_day") == 0:
        kind = "RPD"
    elif rate_limit.get("remaining_tokens_per_minute") == 0:
        kind = "TPM"
    else:
        kind = None
    return kind, oversized


def provider_limit_status(category: Optional[str], kind: Optional[str], oversized: bool) -> Optional[str]:
    """User-facing provider status: RATE_LIMITED_RPM/TPM/OTPM, QUOTA_EXHAUSTED_RPD/TPD, REQUEST_TOO_LARGE_*,
    TEMPORARY_PROVIDER_ERROR."""
    if oversized:
        return f"REQUEST_TOO_LARGE_{kind}" if kind else "REQUEST_TOO_LARGE"
    if category == "RATE_LIMITED":
        if kind in ("RPD", "TPD"):
            return f"QUOTA_EXHAUSTED_{kind}"
        return f"RATE_LIMITED_{kind}" if kind else "RATE_LIMITED"
    if category in ("TRANSIENT_PROVIDER_ERROR", "NETWORK_UNAVAILABLE"):
        return "TEMPORARY_PROVIDER_ERROR"
    return None


def parse_limit_value(message: Any) -> Optional[int]:
    """'... (OTPM): Limit 2000, Requested 4096 ...' -> 2000 (the provider-stated limit), else None."""
    m = re.search(r"limit[:\s]+(\d+)", str(message or ""), re.IGNORECASE)
    return int(m.group(1)) if m else None


STATUS_FOR_CATEGORY = {
    "RATE_LIMITED": "RATE_LIMITED",
    "MODEL_NOT_FOUND": "MODEL_ERROR",
    "CAPABILITY_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
}


class GroqProvider(AIProvider):
    provider_key = "groq"
    PRIMARY_MODEL = "qwen/qwen3.8-27b"
    MAX_RETRIES = 2
    MAX_RATE_LIMIT_RETRIES = 1
    RATE_LIMIT_MAX_WAIT_S = 20.0

    def __init__(self, api_key: Optional[str] = None, model: str = "", max_output_tokens: Optional[int] = None,
                 timeout_s: Optional[int] = None, api_base: str = GROQ_API_BASE):
        self.api_key = settings.GROQ_API_KEY if api_key is None else api_key
        self.model = model or settings.GROQ_MODEL or self.PRIMARY_MODEL
        self.max_output_tokens = max_output_tokens or settings.AI_MAX_OUTPUT_TOKENS
        self.timeout_s = timeout_s or settings.AI_TIMEOUT_SECONDS
        self.api_base = api_base.rstrip("/")
        self.last_execution_metadata: Dict[str, Any] = {}

    # -- helpers -------------------------------------------------------------

    def capabilities(self) -> Optional[Dict[str, Any]]:
        return MODEL_CAPABILITIES.get(self.model)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def build_payload(self, prompt: str, screenshot_base64: Optional[str] = None, mime_type: str = "image/png",
                      max_tokens: Optional[int] = None, json_mode: bool = True) -> Dict[str, Any]:
        """Converts AURA's (text, screenshot) into a Groq chat completion request body."""
        prompt_text = prompt
        if screenshot_base64:
            content: Any = [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type or 'image/png'};base64,{screenshot_base64}"}},
            ]
        else:
            content = prompt_text
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_completion_tokens": max_tokens or self.max_output_tokens,
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        caps = self.capabilities() or {}
        if caps.get("reasoning"):
            payload["reasoning_format"] = "hidden"
        return payload

    def _metadata(self, **kw) -> Dict[str, Any]:
        base = {
            "provider": "Groq", "api": "Chat Completions (OpenAI-compatible)",
            "requested_model": self.model, "actual_model": self.model, "fallback_used": False,
            "status": "PROVIDER_NOT_EVALUABLE", "failure_category": None, "http_status": None,
            "retryable": False, "quota_scope": None, "retry_after_seconds": None,
            "attempt_count": 0, "retry_count": 0, "rate_limit": {}, "final_error": None,
        }
        base.update(kw)
        return base

    # -- inference -----------------------------------------------------------

    def analyze(self, prompt: str, screenshot_base64: Optional[str] = None, mime_type: str = "image/png") -> str:
        if not self.api_key:
            self.last_execution_metadata = self._metadata(failure_category="CONFIGURATION_ERROR", http_status=401,
                                                          final_error="Groq API key is not configured.")
            raise ValueError("Groq API key is not configured. Enter an API key in the dashboard sidebar or .env.")

        caps = self.capabilities()
        if screenshot_base64 and caps is not None and not caps.get("image_input"):
            msg = f"Model '{self.model}' does not support image input required for visual analysis."
            self.last_execution_metadata = self._metadata(status="CAPABILITY_UNSUPPORTED", failure_category="CAPABILITY_UNSUPPORTED",
                                                          final_error=msg)
            raise RuntimeError(f"Groq Request Failed (CAPABILITY_UNSUPPORTED): {msg}")

        # Optimize image and prompt for Groq to stay safely under 7,000 ITPM on Attempt 1
        curr_b64, curr_mime = optimize_image_for_groq(screenshot_base64, max_dim=480, quality=55) if screenshot_base64 else (None, mime_type)
        curr_prompt = compact_prompt_for_groq(prompt, max_dom_elements=18, max_chars=8000)
        payload = self.build_payload(curr_prompt, curr_b64, curr_mime)
        url = f"{self.api_base}/chat/completions"
        attempt_count = retry_count = rate_limit_retries = 0
        budget_reduced_to: Optional[int] = None
        has_retried_input_reduction = False
        next_delay: Optional[float] = None
        rate_limit: Dict[str, Any] = {}
        last = {"category": "TRANSIENT_PROVIDER_ERROR", "http": None, "error": "No attempt made", "scope": None, "retry_after": None}

        for attempt in range(1, self.MAX_RETRIES + 2):
            attempt_count += 1
            if attempt > 1:
                retry_count += 1
                delay = next_delay if next_delay is not None else (2.0 ** (attempt - 2)) + random.uniform(0.1, 0.5)
                logger.info(f"[Groq Retry] Attempt {attempt} for model '{self.model}' after {delay:.2f}s")
                time.sleep(delay)
            next_delay = None

            try:
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout_s)
            except requests.RequestException as e:
                last = {"category": "NETWORK_UNAVAILABLE", "http": None, "error": sanitize_provider_error(e), "scope": None, "retry_after": None}
                logger.warning(f"[Groq Attempt Failed] Attempt {attempt}: network error: {last['error']}")
                continue

            responded_at = datetime.now(timezone.utc).isoformat()
            rate_limit = parse_rate_limit_headers(resp.headers) or rate_limit
            try:
                body = resp.json()
            except ValueError:
                body = {"error": {"message": resp.text[:300]}}

            if 200 <= resp.status_code < 300:
                try:
                    choice = body["choices"][0]
                    text = choice["message"].get("content") or ""
                except (KeyError, IndexError, TypeError):
                    text = ""
                    choice = {}
                self.last_execution_metadata = self._metadata(
                    status="SUCCESS", http_status=resp.status_code, actual_model=body.get("model") or self.model,
                    attempt_count=attempt_count, retry_count=retry_count, rate_limit=rate_limit,
                    finish_reason=choice.get("finish_reason"), usage=body.get("usage") or {}, responded_at=responded_at,
                    output_budget_reduced_to=budget_reduced_to,
                )
                return text or "{}"

            category, retryable, scope = classify_groq_response(resp.status_code, body, rate_limit)
            error_msg = sanitize_provider_error((body.get("error") or {}).get("message") if isinstance(body, dict) else body) or f"HTTP {resp.status_code}"
            retry_after = rate_limit.get("retry_after_seconds")
            kind, oversized = (classify_rate_limit_kind(error_msg, rate_limit) if resp.status_code in (413, 429)
                               else (None, False))
            if oversized:
                # The request itself exceeds a per-minute limit: not a quota problem, no cooldown, and never
                # retried unchanged. An output budget above the provider-stated OTPM limit is retried ONCE with
                # max_completion_tokens lowered below that limit (a changed request).
                category, retryable, scope = "REQUEST_TOO_LARGE", False, None
                limit = parse_limit_value(error_msg)
                current = payload.get("max_completion_tokens") or 0
                # The floor is what a model can still answer usefully within, not a round number. Groq's
                # free tier states an OTPM limit of 1000, so the old floor of 1024 made this retry
                # unreachable for exactly the accounts that hit the limit: the request was refused
                # outright and the scan lost its AI analysis. A reduced budget may truncate a long
                # answer, which the parser reports honestly; refusing to try guarantees nothing at all.
                if kind == "OTPM" and budget_reduced_to is None and limit and MIN_OUTPUT_BUDGET <= int(limit * 0.9) < current:
                    budget_reduced_to = int(limit * 0.9)
                    payload["max_completion_tokens"] = budget_reduced_to
                    retryable, next_delay = True, 0.5
            last = {"category": category, "http": resp.status_code, "error": error_msg, "scope": scope, "retry_after": retry_after,
                    "responded_at": responded_at, "kind": kind, "oversized": oversized}
            logger.warning(f"[Groq Attempt Failed] Attempt {attempt} failed ({category}, HTTP {resp.status_code}): {error_msg}")

            if category == "RATE_LIMITED" and retryable:
                if rate_limit_retries >= self.MAX_RATE_LIMIT_RETRIES or retry_after is None or retry_after > self.RATE_LIMIT_MAX_WAIT_S:
                    retryable = False
                else:
                    rate_limit_retries += 1
                    next_delay = retry_after
            if not retryable:
                break

        status = STATUS_FOR_CATEGORY.get(last["category"], "PROVIDER_NOT_EVALUABLE")
        self.last_execution_metadata = self._metadata(
            status=status, failure_category=last["category"], http_status=last["http"], quota_scope=last["scope"],
            retry_after_seconds=last["retry_after"], attempt_count=attempt_count, retry_count=retry_count,
            rate_limit=rate_limit, final_error=last["error"], responded_at=last.get("responded_at"),
            rate_limit_kind=last.get("kind"),
            provider_limit_status=provider_limit_status(last["category"], last.get("kind"), bool(last.get("oversized"))),
            output_budget_reduced_to=budget_reduced_to,
        )
        raise RuntimeError(f"Groq Request Failed after {attempt_count} attempt(s) ({last['category']}): {last['error']}")

    # -- non-inference availability -----------------------------------------

    def check_availability(self) -> Dict[str, Any]:
        """GET /models: validates key and model without running an inference."""
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "http_status": None, "detail": "Groq API key missing", "provider_reported": {}}
        try:
            resp = requests.get(f"{self.api_base}/models", headers=self._headers(), timeout=15)
        except requests.RequestException as e:
            return {"status": "NETWORK_UNAVAILABLE", "http_status": None, "detail": sanitize_provider_error(e), "provider_reported": {}}
        reported = parse_rate_limit_headers(resp.headers)
        if resp.status_code == 200:
            try:
                body = resp.json()
                if "data" in body:
                    data = body.get("data", [])
                    model_map = {m.get("id"): m for m in data if isinstance(m, dict)}
                    if model_map and self.model not in model_map:
                        available = list(model_map.keys())[:10]
                        return {"status": "MODEL_UNAVAILABLE", "http_status": 200, "detail": f"Model '{self.model}' not found in Groq models list (available: {available})", "provider_reported": reported}
                    if self.model in model_map:
                        active = model_map[self.model].get("active", True)
                        if active is False:
                            return {"status": "MODEL_UNAVAILABLE", "http_status": 200, "detail": f"Model '{self.model}' is not active on Groq", "provider_reported": reported}
                else:
                    if body.get("active") is False:
                        return {"status": "MODEL_UNAVAILABLE", "http_status": 200, "detail": f"Model '{self.model}' is not active on Groq", "provider_reported": reported}
            except Exception:
                pass
            return {"status": "READY", "http_status": 200, "detail": f"API key valid; model '{self.model}' available", "provider_reported": reported}
        mapping = {401: "AUTH_INVALID", 403: "AUTH_INVALID", 404: "MODEL_UNAVAILABLE", 429: "RATE_LIMITED"}
        status = mapping.get(resp.status_code, "UNKNOWN")
        return {"status": status, "http_status": resp.status_code, "detail": f"Groq models endpoint returned HTTP {resp.status_code}",
                "provider_reported": reported}

    # -- explicit connection test (uses one small inference request) --------

    def test_connection_details(self) -> Dict[str, Any]:
        start = time.time()
        base = {"provider": "Groq", "api": "Chat Completions (OpenAI-compatible)", "requested_model": self.model, "actual_model": self.model}
        if not self.api_key:
            return {**base, "success": False, "status": "CONFIGURATION_ERROR", "latency_ms": 0,
                    "error_category": "CONFIGURATION_ERROR", "error_details": "API key not configured.",
                    "message": "Groq API key missing."}
        payload = self.build_payload("Reply with exactly: AURA_GROQ_OK", max_tokens=64, json_mode=False)
        if (self.capabilities() or {}).get("reasoning"):
            payload["reasoning_effort"] = "none"
        try:
            resp = requests.post(f"{self.api_base}/chat/completions", headers=self._headers(), json=payload, timeout=30)
        except requests.RequestException as e:
            return {**base, "success": False, "status": "NETWORK_UNAVAILABLE", "latency_ms": round((time.time() - start) * 1000),
                    "error_category": "NETWORK_UNAVAILABLE", "error_details": sanitize_provider_error(e),
                    "message": "Groq connection failed (network)."}
        latency_ms = round((time.time() - start) * 1000)
        rate_limit = parse_rate_limit_headers(resp.headers)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 200:
            actual = body.get("model") or self.model
            self.last_execution_metadata = self._metadata(status="SUCCESS", http_status=200, actual_model=actual,
                                                          attempt_count=1, rate_limit=rate_limit)
            return {**base, "success": True, "status": "CONNECTED", "actual_model": actual, "latency_ms": latency_ms,
                    "http_status": 200, "rate_limit": rate_limit,
                    "message": f"CONNECTED | Model: {actual} | Latency: {latency_ms} ms"}
        category, _, scope = classify_groq_response(resp.status_code, body, rate_limit)
        detail = sanitize_provider_error((body.get("error") or {}).get("message") if isinstance(body, dict) else "") or f"HTTP {resp.status_code}"
        self.last_execution_metadata = self._metadata(status=STATUS_FOR_CATEGORY.get(category, "PROVIDER_NOT_EVALUABLE"),
                                                      failure_category=category, http_status=resp.status_code,
                                                      quota_scope=scope, attempt_count=1, rate_limit=rate_limit,
                                                      retry_after_seconds=rate_limit.get("retry_after_seconds"),
                                                      final_error=detail)
        return {**base, "success": False, "status": category, "latency_ms": latency_ms, "http_status": resp.status_code,
                "error_category": category, "error_details": detail, "rate_limit": rate_limit,
                "message": f"Groq connection failed ({category})"}

    def test_connection(self) -> Tuple[bool, str]:
        details = self.test_connection_details()
        return details["success"], details["message"]
