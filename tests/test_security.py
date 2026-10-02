import os
import pytest
from aura.security.credentials import SessionCredentialsManager, sanitize_provider_error


def test_session_credentials_priority(monkeypatch):
    # Set env var fallback
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key-999")

    # 1. When session state has a key, session key must take priority
    session_state = {"openai_api_key": "session-openai-key-111"}
    key, source = SessionCredentialsManager.get_credential_for_provider("openai", session_state)
    assert key == "session-openai-key-111"
    assert "Session" in source

    # 2. When session state key is empty, env var key must be used
    session_state_empty = {"openai_api_key": ""}
    key_env, source_env = SessionCredentialsManager.get_credential_for_provider("openai", session_state_empty)
    assert key_env == "env-openai-key-999"
    assert "Environment Variable" in source_env

    # 3. When mock mode selected, returns mock mode credential
    key_mock, source_mock = SessionCredentialsManager.get_credential_for_provider("mock", session_state)
    assert key_mock == ""
    assert "Mock Mode" in source_mock



def test_sanitize_provider_error():
    # OpenAI key pattern
    raw_error_openai = "Error: Invalid API key provided: sk-proj-1234567890abcdef1234567890abcdef. Please check your account."
    sanitized_openai = sanitize_provider_error(raw_error_openai)
    assert "sk-proj-1234567890abcdef1234567890abcdef" not in sanitized_openai
    assert "[REDACTED_API_KEY]" in sanitized_openai

    # Gemini key pattern
    raw_error_gemini = "API key AIzaSy1234567890abcdef1234567890abcdef is expired."
    sanitized_gemini = sanitize_provider_error(raw_error_gemini)
    assert "AIzaSy1234567890" not in sanitized_gemini
    assert "[REDACTED_API_KEY]" in sanitized_gemini

    # Bearer token pattern
    raw_error_bearer = "Unauthorized access with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    sanitized_bearer = sanitize_provider_error(raw_error_bearer)
    assert "eyJhbGciOiJIUzI1" not in sanitized_bearer
    assert "[REDACTED_TOKEN]" in sanitized_bearer

