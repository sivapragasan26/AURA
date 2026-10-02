"""
Provider selection: the extension picks the provider and model, the server never receives anyone's API key
(the browser calls the provider directly with it), and AURA never silently falls back to Mock AI.
"""
import json

import pytest
from starlette.testclient import TestClient

from aura.api import server as api_server
from aura.api.plain_language import plain_for
from aura.api.provider_config import ProviderConfig
from aura.api.server import create_app
from aura.api.store import AuditStore
from aura.config import settings

TOKEN = "p" * 40
BASE = "http://127.0.0.1:8765"
EXT_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
SECRET = "gsk_supersecretkey_0123456789abcdef"


def auth(extra=None):
    return {"X-AURA-Token": TOKEN, "Origin": EXT_ORIGIN, **(extra or {})}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "mock")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(api_server, "PROVIDERS", ProviderConfig())
    return TestClient(create_app(token=TOKEN, store=AuditStore()), base_url=BASE)


def test_lists_the_five_providers_with_mock_labelled_as_demo(client):
    body = client.get("/api/providers", headers=auth()).json()
    assert [p["provider"] for p in body["providers"]] == ["mock", "groq", "gemini", "openai", "anthropic"]
    mock = body["providers"][0]
    assert mock["label"] == "Mock AI · Demo" and mock["is_mock"] and not mock["requires_key"]
    assert body["selected"] == "mock"
    assert all(p["models"] for p in body["providers"])


def test_selecting_a_provider_changes_the_next_scan_only(client):
    r = client.post("/api/providers/select", headers=auth(), json={"provider": "groq", "model": "qwen/qwen3.8-27b"})
    assert r.status_code == 200 and r.json()["selected"] == "groq"
    assert api_server.configured_provider() == ("groq", "qwen/qwen3.8-27b")
    health = client.get("/api/health", headers=auth()).json()
    assert health["ai"]["provider"] == "groq" and health["ai"]["label"] == "Groq" and health["ai"]["is_mock"] is False


def test_unknown_provider_is_refused(client):
    r = client.post("/api/providers/select", headers=auth(), json={"provider": "definitely-not-a-provider"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "UNKNOWN_PROVIDER"


def test_the_server_refuses_an_api_key(client, caplog):
    """
    The server does not take anyone's API key: the browser calls the provider directly with it.

    A client that sends one is told so plainly rather than having it silently ignored, and the key must not
    appear in the answer, in any later answer, or in the log.
    """
    r = client.post("/api/providers/select", headers=auth(), json={"provider": "groq", "api_key": SECRET})
    assert r.status_code == 400 and r.json()["error"]["code"] == "KEY_NOT_ACCEPTED"
    assert "api key" in r.json()["error"]["message"].lower()
    for later in (r, client.get("/api/providers", headers=auth()), client.get("/api/health", headers=auth())):
        assert SECRET not in json.dumps(later.json())
    assert SECRET not in caplog.text
    # A refused request changes nothing, including the selection it came with.
    assert client.get("/api/providers", headers=auth()).json()["selected"] == "mock"


def test_no_user_key_can_be_held_by_the_server(client):
    """There is nowhere in the provider configuration for a user's key to live."""
    config = ProviderConfig()
    config.set("groq", "llama-x")
    held = json.dumps(vars(config), default=str)
    assert SECRET not in held
    assert not hasattr(config, "_keys") and not hasattr(config, "session_state")
    with pytest.raises(TypeError):
        config.set("groq", "llama-x", SECRET)  # the parameter does not exist any more
    # What it does still report is whether THIS SERVER has a key of its own, without revealing it.
    described = {p["provider"]: p for p in config.describe()}
    assert described["groq"]["key_configured"] in (True, False)
    assert SECRET not in json.dumps(config.describe())


def test_choosing_a_provider_needs_no_key(client):
    r = client.post("/api/providers/select", headers=auth(), json={"provider": "groq", "model": "llama-x"})
    assert r.status_code == 200 and r.json()["selected"] == "groq" and r.json()["model"] == "llama-x"


def test_test_connection_reports_states_without_an_inference(client):
    mock = client.post("/api/providers/test", headers=auth()).json()
    assert mock["status"] == "READY" and "not real model analysis" in mock["detail"]
    client.post("/api/providers/select", headers=auth(), json={"provider": "gemini"})
    unconfigured = client.post("/api/providers/test", headers=auth()).json()
    assert unconfigured["status"] == "NOT_CONFIGURED" and "No API key" in unconfigured["detail"]


def test_provider_endpoints_need_the_pairing_token(client):
    assert client.get("/api/providers").status_code == 401
    assert client.post("/api/providers/select", json={"provider": "mock"}).status_code == 401
    assert client.post("/api/providers/test").status_code == 401


def test_no_silent_mock_fallback_when_a_real_provider_has_no_key(client):
    client.post("/api/providers/select", headers=auth(), json={"provider": "groq"})
    provider = api_server.make_provider()
    assert provider.provider_key == "groq"  # never swapped for Mock behind the user's back
    health = client.get("/api/health", headers=auth()).json()["ai"]
    assert health["provider"] == "groq" and health["key_configured"] is False and health["preflight_status"] == "NOT_CONFIGURED"


# ---------------------------------------------------------------- plain language

def test_axe_rules_are_translated_without_inventing_claims():
    p = plain_for("link-name", "ACCESSIBILITY", "axe-core", "WCAG [link-name]: Ensures links have discernible text",
                  "desc", None, None)
    assert p["headline"] == "Some links don't have clear names"
    assert "Screen readers" in p["why"] and "accessible label" in p["fix"] and p["wording"] == "aura"


def test_unknown_rules_keep_the_detector_wording():
    p = plain_for("some-new-axe-rule", "ACCESSIBILITY", "axe-core", "WCAG [x]: Ensures something", "what axe said",
                  "why axe said", "fix axe said")
    assert p["headline"] == "Ensures something" and p["why"] == "why axe said" and p["wording"] == "detector"


def test_ai_rule_wording_avoids_internal_vocabulary():
    p = plain_for("bad_visual_hierarchy", "UI", "AI", "Inverted action visual hierarchy", "d", None, "Make it clearer")
    assert "hierarchy" not in p["headline"].lower() or "prominent" in p["headline"].lower()
    assert p["fix"] == "Make it clearer"
