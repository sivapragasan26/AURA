import time
from typing import Any, Dict, Optional, Tuple
from aura.agent.provider import AIProvider
from aura.config import settings
from aura.security.credentials import sanitize_provider_error
from aura.utils.logger import logger


class OpenAIProvider(AIProvider):
    """AI Provider for OpenAI GPT-4o / GPT-4o-mini."""
    provider_key = "openai"

    def check_availability(self):
        """models.retrieve: key + model metadata, no inference."""
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "http_status": None, "detail": "OpenAI API key missing", "provider_reported": {}}
        try:
            import openai
            openai.OpenAI(api_key=self.api_key).models.retrieve(self.model)
            return {"status": "READY", "http_status": 200, "detail": f"Model '{self.model}' available", "provider_reported": {}}
        except Exception as e:
            code = getattr(e, "status_code", None)
            status = {401: "AUTH_INVALID", 403: "AUTH_INVALID", 404: "MODEL_UNAVAILABLE", 429: "RATE_LIMITED"}.get(code, "UNKNOWN")
            return {"status": status, "http_status": code, "detail": sanitize_provider_error(e), "provider_reported": {}}

    def __init__(self, api_key: Optional[str] = None, model: str = ""):
        self.api_key = settings.OPENAI_API_KEY if api_key is None else api_key
        self.model = model or settings.OPENAI_MODEL
        self.last_execution_metadata: Dict[str, Any] = {}

    def analyze(self, prompt: str, screenshot_base64: Optional[str] = None, mime_type: str = "image/png") -> str:
        if not self.api_key:
            err_msg = "OpenAI API Key is not configured. Enter an API key in the dashboard sidebar or .env."
            self.last_execution_metadata = {
                "provider": "OpenAI",
                "api": "Chat Completions",
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

        import openai
        client = openai.OpenAI(api_key=self.api_key)

        user_content = []
        if screenshot_base64:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{screenshot_base64}"}
            })
        user_content.append({"type": "text", "text": prompt})

        logger.info(f"Sending multimodal request to OpenAI model '{self.model}'...")
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": user_content}],
                response_format={"type": "json_object"},
                temperature=0.2
            )
            text = response.choices[0].message.content or "{}"
            usage_dict = {}
            if getattr(response, "usage", None):
                usage_dict = getattr(response.usage, "model_dump", lambda: {})() if hasattr(response.usage, "model_dump") else dict(response.usage)
            self.last_execution_metadata = {
                "provider": "OpenAI",
                "api": "Chat Completions",
                "requested_model": self.model,
                "actual_model": getattr(response, "model", self.model),
                "fallback_used": False,
                "status": "SUCCESS",
                "http_status": 200,
                "attempt_count": 1,
                "usage": usage_dict,
            }
            return text
        except Exception as e:
            code = getattr(e, "status_code", None)
            sanitized = sanitize_provider_error(e)
            category = "AUTHENTICATION_ERROR" if code in (401, 403) else ("MODEL_NOT_FOUND" if code == 404 else ("RATE_LIMITED" if code == 429 else "TRANSIENT_PROVIDER_ERROR"))
            self.last_execution_metadata = {
                "provider": "OpenAI",
                "api": "Chat Completions",
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
        base = {"provider": "OpenAI", "api": "Chat Completions", "requested_model": self.model, "actual_model": self.model}
        if not self.api_key:
            return {**base, "success": False, "status": "CONFIGURATION_ERROR", "latency_ms": 0,
                    "error_category": "CONFIGURATION_ERROR", "error_details": "OpenAI API Key is missing.",
                    "message": "OpenAI API Key missing."}
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            client.models.retrieve(self.model)
            latency_ms = round((time.time() - start) * 1000)
            self.last_execution_metadata = {
                "provider": "OpenAI", "api": "Chat Completions", "requested_model": self.model,
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
                "provider": "OpenAI", "api": "Chat Completions", "requested_model": self.model,
                "actual_model": self.model, "status": category, "http_status": code, "failure_category": category,
                "attempt_count": 1, "final_error": sanitized
            }
            return {**base, "success": False, "status": category, "latency_ms": latency_ms, "http_status": code,
                    "error_category": category, "error_details": sanitized, "message": f"OpenAI Connection Failed: {sanitized}"}

    def test_connection(self) -> Tuple[bool, str]:
        details = self.test_connection_details()
        return details["success"], details["message"]
