import time
from typing import Any, Dict, Optional, Tuple
from aura.agent.provider import AIProvider
from aura.config import settings
from aura.security.credentials import sanitize_provider_error
from aura.utils.logger import logger


class AnthropicProvider(AIProvider):
    """AI Provider for Anthropic Claude 3.5 / 3.7 Sonnet."""
    provider_key = "anthropic"

    def check_availability(self):
        """models.retrieve: key + model metadata, no inference (UNKNOWN if the SDK lacks the endpoint)."""
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "http_status": None, "detail": "Anthropic API key missing", "provider_reported": {}}
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            if not hasattr(client, "models"):
                return {"status": "UNKNOWN", "http_status": None, "detail": "SDK has no models endpoint", "provider_reported": {}}
            client.models.retrieve(self.model)
            return {"status": "READY", "http_status": 200, "detail": f"Model '{self.model}' available", "provider_reported": {}}
        except Exception as e:
            code = getattr(e, "status_code", None)
            status = {401: "AUTH_INVALID", 403: "AUTH_INVALID", 404: "MODEL_UNAVAILABLE", 429: "RATE_LIMITED"}.get(code, "UNKNOWN")
            return {"status": status, "http_status": code, "detail": sanitize_provider_error(e), "provider_reported": {}}

    def __init__(self, api_key: Optional[str] = None, model: str = ""):
        self.api_key = settings.ANTHROPIC_API_KEY if api_key is None else api_key
        self.model = model or settings.ANTHROPIC_MODEL
        self.last_execution_metadata: Dict[str, Any] = {}

    def analyze(self, prompt: str, screenshot_base64: Optional[str] = None, mime_type: str = "image/png") -> str:
        if not self.api_key:
            err_msg = "Anthropic API Key is not configured. Enter an API key in the dashboard sidebar or .env."
            self.last_execution_metadata = {
                "provider": "Anthropic",
                "api": "Messages API",
                "requested_model": self.model,
                "actual_model": self.model,
                "fallback_used": False,
                "status": "PROVIDER_NOT_EVALUABLE",
                "failure_category": "CONFIGURATION_ERROR",
                "http_status": 401,
                "retryable": False,
                "attempt_count": 0,
                "final_error": err_msg,
            }
            raise ValueError(err_msg)

        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)

        content = []
        if screenshot_base64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": screenshot_base64
                }
            })
        content.append({"type": "text", "text": prompt})

        logger.info(f"Sending multimodal request to Anthropic model '{self.model}'...")
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=4000,
                temperature=0.2,
                messages=[{"role": "user", "content": content}]
            )
            response_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    response_text += block.text
            usage_dict = {}
            if getattr(response, "usage", None):
                usage_dict = getattr(response.usage, "model_dump", lambda: {})() if hasattr(response.usage, "model_dump") else dict(response.usage)
            self.last_execution_metadata = {
                "provider": "Anthropic",
                "api": "Messages API",
                "requested_model": self.model,
                "actual_model": getattr(response, "model", self.model),
                "fallback_used": False,
                "status": "SUCCESS",
                "http_status": 200,
                "attempt_count": 1,
                "usage": usage_dict,
            }
            return response_text or "{}"
        except Exception as e:
            code = getattr(e, "status_code", None)
            sanitized = sanitize_provider_error(e)
            category = "AUTHENTICATION_ERROR" if code in (401, 403) else ("MODEL_NOT_FOUND" if code == 404 else ("RATE_LIMITED" if code == 429 else "TRANSIENT_PROVIDER_ERROR"))
            self.last_execution_metadata = {
                "provider": "Anthropic",
                "api": "Messages API",
                "requested_model": self.model,
                "actual_model": self.model,
                "fallback_used": False,
                "status": "RATE_LIMITED" if category == "RATE_LIMITED" else "PROVIDER_NOT_EVALUABLE",
                "failure_category": category,
                "http_status": code,
                "attempt_count": 1,
                "final_error": sanitized,
            }
            raise RuntimeError(sanitized)

    def test_connection_details(self) -> Dict[str, Any]:
        start = time.time()
        base = {"provider": "Anthropic", "api": "Messages API", "requested_model": self.model, "actual_model": self.model}
        if not self.api_key:
            return {**base, "success": False, "status": "CONFIGURATION_ERROR", "latency_ms": 0,
                    "error_category": "CONFIGURATION_ERROR", "error_details": "Anthropic API Key is missing.",
                    "message": "Anthropic API Key missing."}
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            if hasattr(client, "models"):
                client.models.retrieve(self.model)
            else:
                client.messages.create(
                    model=self.model,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "ping"}]
                )
            latency_ms = round((time.time() - start) * 1000)
            self.last_execution_metadata = {
                "provider": "Anthropic", "api": "Messages API", "requested_model": self.model,
                "actual_model": self.model, "status": "SUCCESS", "http_status": 200, "attempt_count": 1
            }
            return {**base, "success": True, "status": "CONNECTED", "latency_ms": latency_ms,
                    "http_status": 200, "message": f"CONNECTED | Model: {self.model} | Latency: {latency_ms} ms"}
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000)
            code = getattr(e, "status_code", None)
            sanitized = sanitize_provider_error(e)
            category = "AUTHENTICATION_ERROR" if code in (401, 403) else ("MODEL_NOT_FOUND" if code == 404 else ("RATE_LIMITED" if code == 429 else "REQUEST_FAILED"))
            self.last_execution_metadata = {
                "provider": "Anthropic", "api": "Messages API", "requested_model": self.model,
                "actual_model": self.model, "status": category, "http_status": code, "failure_category": category,
                "attempt_count": 1, "final_error": sanitized
            }
            return {**base, "success": False, "status": category, "latency_ms": latency_ms, "http_status": code,
                    "error_category": category, "error_details": sanitized, "message": f"Anthropic Connection Failed: {sanitized}"}

    def test_connection(self) -> Tuple[bool, str]:
        details = self.test_connection_details()
        return details["success"], details["message"]
