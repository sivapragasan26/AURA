import pytest
from aura.agent.gemini_provider import GeminiProvider
from aura.config.models import PROVIDER_MODELS, DEFAULT_MODELS
from aura.config import settings


def test_gemini_model_registry_defaults():
    assert DEFAULT_MODELS["gemini"] == "gemini-3.6-flash"
    assert "gemini-3.6-flash" in PROVIDER_MODELS["gemini"]
    assert "gemini-2.5-flash" in PROVIDER_MODELS["gemini"]
    assert "gemini-2.5-pro" in PROVIDER_MODELS["gemini"]
    assert "gemini-1.5-flash" in PROVIDER_MODELS["gemini"]
    assert "gemini-1.5-pro" in PROVIDER_MODELS["gemini"]


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

