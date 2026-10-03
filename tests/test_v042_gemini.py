import pytest
from aura.agent.gemini_provider import GeminiProvider
from aura.config.models import PROVIDER_MODELS, DEFAULT_MODELS
from aura.config import settings


def test_gemini_model_registry_defaults():
    assert DEFAULT_MODELS["gemini"] == "gemini-3.6-flash"
    assert "gemini-3.6-flash" in PROVIDER_MODELS["gemini"]
    assert "gemini-3.8-flash" in PROVIDER_MODELS["gemini"]
    # The 2.5 generation is closed to accounts that never used it, so AURA no longer offers it.
    assert "gemini-2.5-flash" not in PROVIDER_MODELS["gemini"]
    assert "gemini-3.5-flash-lite" in PROVIDER_MODELS["gemini"]
    assert "gemini-3.1-flash-lite" in PROVIDER_MODELS["gemini"]
    # The 1.5 and 2.5 generations are gone from what AURA offers; a new key cannot use them.
    assert not [m for m in PROVIDER_MODELS["gemini"] if m.startswith(("gemini-1.5", "gemini-2.5"))]


def test_gemini_provider_init():
    provider = GeminiProvider(api_key="test_key", model="gemini-3.6-flash")
    assert provider.api_key == "test_key"
    assert provider.model == "gemini-3.6-flash"


def test_gemini_provider_test_connection_missing_key():
    provider = GeminiProvider(api_key="", model="gemini-3.6-flash")
    success, msg = provider.test_connection()
    assert success is False
    assert "missing" in msg.lower()


def test_gemini_provider_test_connection_invalid_key():
    provider = GeminiProvider(api_key="invalid_fake_key_12345", model="gemini-3.6-flash")
    success, msg = provider.test_connection()
    assert success is False
    assert "Failed" in msg or "Authentication" in msg or "unsupported" in msg

