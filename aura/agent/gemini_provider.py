"""
AURA Gemini AI Provider implementation (V0.4.4.4).
Migrated to Gemini Interactions API (client.interactions.create) with gemini-3.6-flash as default model.
Harden Gemini AI Provider against transient API failures and enforce strict benchmark semantics.
Uses official google-genai SDK (genai.Client).
"""

import os
import time
import random
import base64
import logging
import re
from typing import Dict, Any, Optional, Tuple, List

from aura.agent.provider import AIProvider
from aura.config import settings
from aura.security.credentials import sanitize_provider_error

logger = logging.getLogger("aura.agent.gemini_provider")


_DAILY_QUOTA_PATTERNS = ("per day", "perday", "requests per day", "daily limit", "daily quota")


def is_daily_quota_exhausted(error: Exception) -> bool:
    """True when a 429 reports an exhausted per-day quota (e.g. '20 requests per day on Free Tier').
    Retrying such an error cannot succeed until the quota resets."""
    err_str = str(error).lower().replace("_", " ")
    details = getattr(error, "details", None)
    if details:
        err_str += " " + str(details).lower().replace("_", " ")
    return any(p in err_str for p in _DAILY_QUOTA_PATTERNS)


def extract_retry_delay_seconds(error: Exception) -> Optional[float]:
    """Parses the server-suggested retry delay ('retryDelay': '40s' or 'retry in 40.5s'), if any."""
    text = f"{error} {getattr(error, 'details', '')}"
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", text) or \
            re.search(r"retry in (\d+(?:\.\d+)?)\s*s", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def classify_gemini_error(error: Exception) -> Tuple[str, Optional[int], bool]:
    """
    Classifies a Gemini API exception into structured error metadata.
    Returns: (failure_category, http_status_code, is_retryable)
    """
    err_str = str(error).lower()
    err_type = type(error).__name__.lower()

    # SDK / Local request construction / Pydantic unmarshaller validation errors
    if ("pydantic" in err_type or "validationerror" in err_type or
        "createagentinteraction" in err_str or "field required" in err_str or
        "expected object with" in err_str or "unmarshaller" in err_str or
        "sdk_request_construction_error" in err_str):
        return "SDK_REQUEST_CONSTRUCTION_ERROR", None, False

    # Prefer the structured HTTP code carried by google.genai.errors.APIError over string heuristics
    code = getattr(error, "code", None)
    if isinstance(code, int):
        if code == 429:
            return "RATE_LIMITED", 429, not is_daily_quota_exhausted(error)
        if code == 401:
            return "AUTHENTICATION_ERROR", 401, False
        if code == 403:
            return "PERMISSION_ERROR", 403, False
        if code == 404:
            return "MODEL_NOT_FOUND", 404, False
        if 400 <= code < 500:
            return "BAD_REQUEST", code, False
        if code >= 500:
            return "TRANSIENT_PROVIDER_ERROR", code, True

    # Rate limiting is checked before auth heuristics: quota messages can mention the consumer API key
    if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str or "rate limit" in err_str:
        return "RATE_LIMITED", 429, not is_daily_quota_exhausted(error)

    # Non-retryable status codes / authentication errors
    if "401" in err_str or "unauthorized" in err_str or "invalid api key" in err_str or "api_key" in err_str:
        return "AUTHENTICATION_ERROR", 401, False
    if "403" in err_str or "permission_denied" in err_str or "forbidden" in err_str:
        return "PERMISSION_ERROR", 403, False
    if "404" in err_str or "not_found" in err_str or "model not found" in err_str or "no longer available" in err_str:
        return "MODEL_NOT_FOUND", 404, False
    if "400" in err_str or "invalid_argument" in err_str or "bad_request" in err_str:
        return "BAD_REQUEST", 400, False

    # Retryable status codes / transient errors
    if "503" in err_str or "unavailable" in err_str or "service unavailable" in err_str:
        return "TRANSIENT_PROVIDER_ERROR", 503, True
    if "500" in err_str or "internal" in err_str:
        return "TRANSIENT_PROVIDER_ERROR", 500, True
    if "502" in err_str or "bad gateway" in err_str:
        return "TRANSIENT_PROVIDER_ERROR", 502, True
    if "504" in err_str or "gateway timeout" in err_str or "timeout" in err_str:
        return "TRANSIENT_PROVIDER_ERROR", 504, True

    # Default to transient retryable error for unknown network/connection issues
    return "TRANSIENT_PROVIDER_ERROR", 503, True


def normalize_mime_type(mime_type: Optional[str]) -> str:
    """
    Normalizes MIME string to strict valid image MIME representation.
    Enforces 'image/png' or 'image/jpeg' and prevents None, empty, or invalid strings.
    """
    if not mime_type:
        return "image/png"
    mime = str(mime_type).strip().lower()
    if mime in ("png", "image/png"):
        return "image/png"
    if mime in ("jpg", "jpeg", "image/jpg", "image/jpeg"):
        return "image/jpeg"
    if mime.startswith("image/"):
        return mime
    return "image/png"


def build_gemini_multimodal_input(
    prompt: str,
    screenshot_base64: Optional[str] = None,
    mime_type: str = "image/png"
) -> Any:
    """
    Central Gemini Multimodal Input Adapter for client.interactions.create().
    
    For text-only prompts, returns a plain string.
    For multimodal prompts with base64 screenshots, returns a list of dictionary content blocks:
    [
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "mime_type": valid_mime,
            "data": screenshot_base64,
            "image": {
                "bytes": screenshot_base64,
                "data": screenshot_base64,
                "mime_type": valid_mime
            },
            "image_url": {
                "url": f"data:{valid_mime};base64,{screenshot_base64}"
            }
        }
    ]
    """
    if not screenshot_base64:
        return prompt

    valid_mime = normalize_mime_type(mime_type)
    data_url = f"data:{valid_mime};base64,{screenshot_base64}"

    return [
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "mime_type": valid_mime,
            "data": screenshot_base64,
            "image": {
                "bytes": screenshot_base64,
                "data": screenshot_base64,
                "mime_type": valid_mime
            },
            "image_url": {
                "url": data_url
            }
        }
    ]


# Backwards compatibility alias
build_gemini_interaction_input = build_gemini_multimodal_input


class GeminiProvider(AIProvider):
    """
    Official Google Gemini API provider supporting gemini-3.6-flash via Gemini Interactions API:
    - Exponential backoff retries + jitter for transient errors (503, 429, 500)
    - Non-retryable immediate model error on 404 MODEL_NOT_FOUND
    - Non-retryable immediate SDK construction error on validation error
    - Strict distinction between transient provider failure and AI evaluation failure
    - Real structured connection health checks with latency measurement
    - Optional fallback model support (disabled during strict benchmark mode)
    - Zero API key leaks in logs, stack traces, or metadata
    """
    provider_key = "gemini"

    FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    PRIMARY_MODEL = "gemini-3.6-flash"
    FALLBACK_MODEL = "gemini-3.6-flash-lite"
    MAX_RETRIES = 2  # Total maximum attempts = 3 (Initial + 2 retries)
    # Short-term (per-minute) 429s get at most one retry, and only if the server-suggested wait is short.
    # Daily quota exhaustion is never retried: it cannot succeed before the quota resets.
    MAX_RATE_LIMIT_RETRIES = 1
    RATE_LIMIT_MAX_WAIT_S = 20.0

    def __init__(self, api_key: Optional[str] = None, model: str = "", strict_benchmark_mode: bool = False,
                 allow_model_fallback: bool = False):
        self.api_key = settings.GEMINI_API_KEY if api_key is None else api_key
        self.model = model or settings.GEMINI_MODEL or self.PRIMARY_MODEL
        self.strict_benchmark_mode = strict_benchmark_mode
        # Fallback silently changes the model under evaluation, so it is opt-in.
        self.allow_model_fallback = allow_model_fallback
        self.last_execution_metadata: Dict[str, Any] = {}

    def analyze(self, prompt: str, screenshot_base64: Optional[str] = None, mime_type: str = "image/png") -> str:
        if not self.api_key:
            err_msg = "Gemini API Key is missing. Please configure key in dashboard sidebar or environment."
            self.last_execution_metadata = {
                "provider": "Gemini",
                "api": "Interactions API",
                "requested_model": self.model,
                "actual_model": self.model,
                "fallback_used": False,
                "status": "PROVIDER_NOT_EVALUABLE",
                "failure_category": "CONFIGURATION_ERROR",
                "http_status": 401,
                "retryable": False,
                "attempt_count": 0,
                "retry_count": 0,
                "final_error": err_msg
            }
            raise ValueError(err_msg)

        from google import genai

        client = genai.Client(api_key=self.api_key)
        input_payload = build_gemini_multimodal_input(prompt, screenshot_base64, mime_type)

        # STEP 1: Safe runtime diagnostics before calling interactions.create
        sdk_ver = getattr(genai, "__version__", "unknown")
        logger.info(f"[Gemini DEBUG] SDK version: {sdk_ver}")
        logger.info(f"[Gemini DEBUG] Input type: {type(input_payload).__name__}")
        if isinstance(input_payload, list):
            for idx, elem in enumerate(input_payload):
                elem_type = type(elem).__name__
                if isinstance(elem, dict):
                    b_type = elem.get("type", "unknown")
                    b_mime = elem.get("mime_type") or (elem.get("image", {}).get("mime_type") if isinstance(elem.get("image"), dict) else None)
                    b_len = len(elem.get("image", {}).get("bytes", "")) if isinstance(elem.get("image"), dict) else (len(elem.get("text", "")) if "text" in elem else 0)
                    logger.info(f"[Gemini DEBUG] Element {idx} type: {elem_type} (type={b_type}, mime={b_mime}, len={b_len})")
                else:
                    logger.info(f"[Gemini DEBUG] Element {idx} type: {elem_type}")
        else:
            logger.info(f"[Gemini DEBUG] Input payload: text-only (len={len(input_payload)})")

        requested_model = self.model
        current_model = requested_model
        fallback_used = False
        
        attempt_count = 0
        retry_count = 0
        original_error_str = None
        last_error_obj = None

        candidate_models = [requested_model]
        if self.allow_model_fallback and not self.strict_benchmark_mode and self.FALLBACK_MODEL != requested_model:
            candidate_models.append(self.FALLBACK_MODEL)

        for attempt_model in candidate_models:
            if attempt_model != requested_model:
                fallback_used = True
                logger.warning(f"[Gemini] Primary model '{requested_model}' exhausted retries. Invoking fallback model '{attempt_model}'...")

            current_model = attempt_model
            rate_limit_retries = 0
            next_delay: Optional[float] = None

            for attempt in range(1, self.MAX_RETRIES + 2):  # Attempts 1, 2, 3
                attempt_count += 1
                if attempt > 1:
                    retry_count += 1
                    backoff_delay = next_delay if next_delay is not None else (2.0 ** (attempt - 2)) + random.uniform(0.1, 0.5)
                    logger.info(f"[Gemini Retry] Attempt {attempt}/{self.MAX_RETRIES + 1} for model '{current_model}' after {backoff_delay:.2f}s backoff...")
                    time.sleep(backoff_delay)
                else:
                    logger.info(f"[Gemini Request] Attempting interaction with model '{current_model}' via Interactions API...")

                try:
                    interaction = client.interactions.create(
                        model=current_model,
                        input=input_payload
                    )
                    res_text = getattr(interaction, "output_text", None) or getattr(interaction, "text", None) or "{}"
                    interaction_id = getattr(interaction, "id", None)

                    self.model = current_model
                    self.last_execution_metadata = {
                        "provider": "Gemini",
                        "api": "Interactions API",
                        "requested_model": requested_model,
                        "actual_model": current_model,
                        "fallback_used": fallback_used,
                        "status": "SUCCESS",
                        "failure_category": None,
                        "http_status": 200,
                        "retryable": False,
                        "attempt_count": attempt_count,
                        "retry_count": retry_count,
                        "original_error": original_error_str,
                        "final_error": None,
                        "interaction_id": interaction_id
                    }
                    return res_text or "{}"
                except Exception as e:
                    last_error_obj = e
                    sanitized_err = sanitize_provider_error(e)
                    if not original_error_str:
                        original_error_str = sanitized_err

                    category, http_code, is_retryable = classify_gemini_error(e)
                    logger.warning(f"[Gemini Attempt Failed] Attempt {attempt} failed ({category}, HTTP {http_code}): {sanitized_err}")

                    quota_scope = None
                    server_delay = None
                    next_delay = None
                    if category == "RATE_LIMITED":
                        quota_scope = "DAILY" if is_daily_quota_exhausted(e) else "SHORT_TERM"
                        server_delay = extract_retry_delay_seconds(e)
                        if (quota_scope == "DAILY"
                                or rate_limit_retries >= self.MAX_RATE_LIMIT_RETRIES
                                or (server_delay is not None and server_delay > self.RATE_LIMIT_MAX_WAIT_S)):
                            is_retryable = False
                        else:
                            rate_limit_retries += 1
                            next_delay = server_delay

                    # Non-retryable errors stop immediate model attempt
                    if not is_retryable:
                        if category == "SDK_REQUEST_CONSTRUCTION_ERROR":
                            status = "SDK_REQUEST_CONSTRUCTION_ERROR"
                        elif category == "MODEL_NOT_FOUND":
                            status = "MODEL_ERROR"
                        elif category == "RATE_LIMITED":
                            status = "RATE_LIMITED"
                        else:
                            status = "PROVIDER_NOT_EVALUABLE"

                        self.last_execution_metadata = {
                            "provider": "Gemini",
                            "api": "Interactions API",
                            "requested_model": requested_model,
                            "actual_model": current_model,
                            "fallback_used": fallback_used,
                            "status": status,
                            "failure_category": category,
                            "http_status": http_code,
                            "retryable": False,
                            "quota_scope": quota_scope,
                            "retry_after_seconds": server_delay,
                            "attempt_count": attempt_count,
                            "retry_count": retry_count,
                            "original_error": original_error_str,
                            "final_error": sanitized_err
                        }
                        raise RuntimeError(f"Gemini Request Failed ({category}): {sanitized_err}")

        # All retries and models exhausted
        category, http_code, is_retryable = classify_gemini_error(last_error_obj) if last_error_obj else ("TRANSIENT_PROVIDER_ERROR", 503, True)
        sanitized_final = sanitize_provider_error(last_error_obj) if last_error_obj else "All retries exhausted"
        if category == "SDK_REQUEST_CONSTRUCTION_ERROR":
            status = "SDK_REQUEST_CONSTRUCTION_ERROR"
        elif category == "MODEL_NOT_FOUND":
            status = "MODEL_ERROR"
        elif category == "RATE_LIMITED":
            status = "RATE_LIMITED"
        else:
            status = "PROVIDER_NOT_EVALUABLE"

        self.last_execution_metadata = {
            "provider": "Gemini",
            "api": "Interactions API",
            "requested_model": requested_model,
            "actual_model": current_model,
            "fallback_used": fallback_used,
            "status": status,
            "failure_category": category,
            "http_status": http_code,
            "retryable": is_retryable,
            "attempt_count": attempt_count,
            "retry_count": retry_count,
            "original_error": original_error_str,
            "final_error": sanitized_final
        }

        raise RuntimeError(f"Gemini Request Failed after {attempt_count} attempts ({category}): {sanitized_final}")

    def check_availability(self) -> Dict[str, Any]:
        """models.get: validates key and model metadata. This is not a generate_content inference call."""
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "http_status": None, "detail": "Gemini API key missing", "provider_reported": {}}
        try:
            from google import genai
            genai.Client(api_key=self.api_key).models.get(model=self.model)
            return {"status": "READY", "http_status": 200, "detail": f"API key valid; model '{self.model}' available", "provider_reported": {}}
        except Exception as e:
            category, http_code, _ = classify_gemini_error(e)
            status = {"AUTHENTICATION_ERROR": "AUTH_INVALID", "PERMISSION_ERROR": "AUTH_INVALID",
                      "MODEL_NOT_FOUND": "MODEL_UNAVAILABLE", "RATE_LIMITED": "RATE_LIMITED"}.get(category)
            if status is None:
                status = "NETWORK_UNAVAILABLE" if http_code is None or "connect" in str(e).lower() else "UNKNOWN"
            return {"status": status, "http_status": http_code, "detail": sanitize_provider_error(e), "provider_reported": {}}

    def test_connection_details(self) -> Dict[str, Any]:
        """
        Executes a real tiny Gemini test interaction request ("Reply with exactly: AURA_GEMINI_OK")
        and measures latency, returning structured health metadata.
        """
        if not self.api_key:
            return {
                "success": False,
                "status": "CONFIGURATION_ERROR",
                "provider": "Gemini",
                "api": "Interactions API",
                "requested_model": self.model,
                "actual_model": self.model,
                "latency_ms": 0,
                "message": "Gemini API Key missing. Please configure key in dashboard sidebar or environment.",
                "http_status": 401,
                "error_details": "API Key not configured."
            }

        from google import genai

        start_time = time.time()
        try:
            client = genai.Client(api_key=self.api_key)
            test_prompt = "Reply with exactly: AURA_GEMINI_OK"
            input_payload = build_gemini_interaction_input(test_prompt)
            
            interaction = client.interactions.create(
                model=self.model,
                input=input_payload
            )
            latency_ms = round((time.time() - start_time) * 1000)
            res_text = (getattr(interaction, "output_text", None) or getattr(interaction, "text", None) or "").strip()
            interaction_id = getattr(interaction, "id", None)
            
            return {
                "success": True,
                "status": "CONNECTED",
                "provider": "Gemini",
                "api": "Interactions API",
                "requested_model": self.model,
                "actual_model": self.model,
                "latency_ms": latency_ms,
                "message": f"CONNECTED | API: Interactions API | Model: {self.model} | Latency: {latency_ms} ms",
                "http_status": 200,
                "raw_response": res_text,
                "interaction_id": interaction_id
            }
        except Exception as e:
            latency_ms = round((time.time() - start_time) * 1000)
            sanitized_err = sanitize_provider_error(e)
            category, http_code, is_retryable = classify_gemini_error(e)
            
            status = "REQUEST_FAILED"
            if category == "RATE_LIMITED" and not is_retryable:
                status = "RATE_LIMITED"
            elif category in ("RATE_LIMITED", "TRANSIENT_PROVIDER_ERROR"):
                status = "TEMPORARILY_UNAVAILABLE"
            elif category == "MODEL_NOT_FOUND":
                status = "MODEL_ERROR"
            elif category in ("AUTHENTICATION_ERROR", "PERMISSION_ERROR"):
                status = "CONFIGURATION_ERROR"
            elif category == "SDK_REQUEST_CONSTRUCTION_ERROR":
                status = "SDK_REQUEST_CONSTRUCTION_ERROR"

            return {
                "success": False,
                "status": status,
                "provider": "Gemini",
                "api": "Interactions API",
                "requested_model": self.model,
                "actual_model": self.model,
                "latency_ms": latency_ms,
                "message": f"Gemini Connection Failed ({category}): {sanitized_err}",
                "http_status": http_code,
                "error_category": category,
                "error_details": sanitized_err
            }

    def test_connection(self) -> Tuple[bool, str]:
        """Implements AIProvider test_connection returning (success: bool, formatted_message: str)."""
        details = self.test_connection_details()
        if details["success"]:
            return True, details["message"]
        return False, details["message"]
