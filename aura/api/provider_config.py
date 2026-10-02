"""
Provider selection for the local AURA server.

The extension chooses WHICH provider and model to use and may supply an API key once; the key is held here,
in the server process only (never written to disk, never logged, never returned to the extension, never part
of an audit). Key resolution itself stays with SessionCredentialsManager: a key set here behaves exactly like
the dashboard's session credential, with the environment (.env) as the fallback.

Changing the provider affects the NEXT scan only: audits already stored keep the provider they ran with.
There is no silent fallback to the Mock provider: an unusable provider is reported as unavailable.
"""
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from aura.config import settings
from aura.config.models import DEFAULT_MODELS, PROVIDER_MODELS
from aura.security.credentials import SessionCredentialsManager

PROVIDER_LABELS = {
    "mock": "Mock AI · Demo",
    "groq": "Groq",
    "gemini": "Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
}
SUPPORTED = tuple(PROVIDER_LABELS)
ENV_MODEL = {
    "gemini": lambda: settings.GEMINI_MODEL,
    "openai": lambda: settings.OPENAI_MODEL,
    "anthropic": lambda: settings.ANTHROPIC_MODEL,
    "groq": lambda: settings.GROQ_MODEL,
}


@dataclass
class Selection:
    provider: str
    model: Optional[str]


class ProviderConfig:
    """Thread-safe provider selection plus in-memory API keys."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        provider = (settings.AI_PROVIDER or "mock").lower()
        if provider not in SUPPORTED:
            provider = "mock"
        self._selection = Selection(provider, self._default_model(provider))
        self._keys: Dict[str, str] = {}

    @staticmethod
    def _default_model(provider: str) -> Optional[str]:
        return ENV_MODEL.get(provider, lambda: None)() or DEFAULT_MODELS.get(provider)

    def selection(self) -> Selection:
        with self._lock:
            return Selection(self._selection.provider, self._selection.model)

    def set(self, provider: str, model: Optional[str] = None, api_key: Optional[str] = None) -> Selection:
        provider = (provider or "").lower()
        if provider not in SUPPORTED:
            raise ValueError(f"Unknown provider '{provider}'")
        with self._lock:
            self._selection = Selection(provider, (model or "").strip() or self._default_model(provider))
            if api_key is not None:
                key = api_key.strip()
                if key:
                    self._keys[provider] = key
                else:
                    self._keys.pop(provider, None)  # empty value clears the stored key
            return Selection(self._selection.provider, self._selection.model)

    def session_state(self) -> Dict[str, str]:
        """Shape SessionCredentialsManager expects; used only inside this process."""
        with self._lock:
            return {f"{provider}_api_key": key for provider, key in self._keys.items()}

    def key_source(self, provider: str) -> str:
        """Where this provider's key comes from, without revealing it."""
        _, source = SessionCredentialsManager.get_credential_for_provider(provider, self.session_state())
        return source

    def has_key(self, provider: str) -> bool:
        key, _ = SessionCredentialsManager.get_credential_for_provider(provider, self.session_state())
        return bool(key)

    def describe(self) -> List[Dict[str, Any]]:
        """Provider list for the UI. Never contains an API key."""
        current = self.selection()
        out = []
        for key in SUPPORTED:
            out.append({
                "provider": key,
                "label": PROVIDER_LABELS[key],
                "is_mock": key == "mock",
                "requires_key": key != "mock",
                "models": list(PROVIDER_MODELS.get(key, [])),
                "default_model": self._default_model(key),
                "key_configured": key == "mock" or self.has_key(key),
                "key_source": "built in" if key == "mock" else self.key_source(key),
                "selected": key == current.provider,
            })
        return out
