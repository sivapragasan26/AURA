import re
import os
from typing import Tuple, Optional, Union
from aura.config import settings


class SessionCredentialsManager:
    """Manages session-based API credentials with priority resolution and sanitization."""

    @staticmethod
    def get_credential_for_provider(provider: str, session_state: Optional[dict] = None) -> Tuple[str, str]:
        """
        Resolves API key and credential source for specified provider.
        Priority:
          1. Dashboard Session Credential
          2. Environment Variable (.env or OS)
          3. Mock / Missing
        Returns: (api_key, credential_source)
        """
        provider = (provider or "mock").lower()
        if provider == "mock":
            return "", "Mock Mode"

        session = session_state if session_state is not None else {}
        session_key = session.get(f"{provider}_api_key", "").strip()

        if session_key:
            return session_key, "Dashboard Session"

        # Fallback to Environment
        env_key = ""
        if provider == "openai":
            env_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        elif provider == "gemini":
            env_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        elif provider == "anthropic":
            env_key = settings.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        elif provider == "groq":
            env_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")

        if env_key and env_key.strip():
            return env_key.strip(), "Environment Variable"

        return "", "Missing"

    @staticmethod
    def clear_session_credential(provider: str, session_state: dict):
        """Removes API credential for provider from session state without modifying disk files."""
        provider = (provider or "mock").lower()
        key_name = f"{provider}_api_key"
        if key_name in session_state:
            session_state[key_name] = ""


def sanitize_provider_error(error: Union[Exception, str]) -> str:
    """Strips API keys, bearer tokens, and sensitive credentials from error messages."""
    error_str = str(error)
    if not error_str:
        return "An unknown error occurred."

    # Pattern for API keys (e.g. sk-..., AIza..., etc.)
    sanitized = re.sub(r"(sk-[a-zA-Z0-9_\-]{10,})", "[REDACTED_API_KEY]", error_str)
    sanitized = re.sub(r"(AIza[a-zA-Z0-9_\-]{10,})", "[REDACTED_API_KEY]", sanitized)
    sanitized = re.sub(r"(gsk_[a-zA-Z0-9_\-]{10,})", "[REDACTED_API_KEY]", sanitized)
    sanitized = re.sub(r"(Bearer\s+[a-zA-Z0-9_\-\.]{10,})", "Bearer [REDACTED_TOKEN]", sanitized)
    sanitized = re.sub(r"(key=)[a-zA-Z0-9_\-]{10,}", r"\1[REDACTED_KEY]", sanitized)

    return sanitized
