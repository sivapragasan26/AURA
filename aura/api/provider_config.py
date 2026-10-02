"""
Provider selection for the local AURA server.

The extension chooses WHICH provider and model to use. It does NOT send its API key: the browser calls the
provider directly with the user's key, so this process never holds, stores, logs or returns a credential
belonging to a user (see aura/api/relay.py). A self-hosted server may still have a key of its own in its
environment (.env), which SessionCredentialsManager resolves and which only /api/audits uses.

Changing the provider affects the NEXT scan only: audits already stored keep the provider they ran with.
There is no silent fallback to the Mock provider: an unusable provider is reported as unavailable.
"""
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from aura.config import settings
from aura.config.models import DEFAULT_MODELS, MODEL_CAPABILITIES, PROVIDER_MODELS
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
    """Thread-safe provider selection. Holds no API key, by construction."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        provider = (settings.AI_PROVIDER or "mock").lower()
        if provider not in SUPPORTED:
            provider = "mock"
        self._selection = Selection(provider, self._default_model(provider))

    @staticmethod
    def _default_model(provider: str) -> Optional[str]:
        return ENV_MODEL.get(provider, lambda: None)() or DEFAULT_MODELS.get(provider)

    def selection(self) -> Selection:
        with self._lock:
            return Selection(self._selection.provider, self._selection.model)

    def set(self, provider: str, model: Optional[str] = None) -> Selection:
        provider = (provider or "").lower()
        if provider not in SUPPORTED:
            raise ValueError(f"Unknown provider '{provider}'")
        with self._lock:
            self._selection = Selection(provider, (model or "").strip() or self._default_model(provider))
            return Selection(self._selection.provider, self._selection.model)

    def key_source(self, provider: str) -> str:
        """Where this SERVER's own key for the provider comes from, if it has one. Never the key itself."""
        _, source = SessionCredentialsManager.get_credential_for_provider(provider, None)
        return source

    def has_key(self, provider: str) -> bool:
        """Whether this server has its own key for the provider. The user's key is in their browser."""
        key, _ = SessionCredentialsManager.get_credential_for_provider(provider, None)
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
                # What each model can do, so the browser - which makes the AI call itself - knows whether
                # to attach the screenshot and whether to ask for JSON. One table, in Python, under test.
                "model_capabilities": {m: dict(MODEL_CAPABILITIES.get(m, {}))
                                       for m in PROVIDER_MODELS.get(key, [])},
                "default_model": self._default_model(key),
                "key_configured": key == "mock" or self.has_key(key),
                "key_source": "built in" if key == "mock" else self.key_source(key),
                "selected": key == current.provider,
            })
        return out
