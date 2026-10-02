"""
Provider selection: the extension picks the provider, the key stays on the local server, and AURA never
silently falls back to Mock AI.
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


def test_api_key_is_accepted_but_never_returned_or_logged(client, caplog):
    r = client.post("/api/providers/select", headers=auth(), json={"provider": "groq", "api_key": SECRET})
    body = json.dumps(r.json())
    assert SECRET not in body
    assert SECRET not in json.dumps(client.get("/api/providers", headers=auth()).json())
    assert SECRET not in json.dumps(client.get("/api/health", headers=auth()).json())
    assert SECRET not in caplog.text
    groq = next(p for p in client.get("/api/providers", headers=auth()).json()["providers"] if p["provider"] == "groq")
    assert groq["key_configured"] is True and groq["key_source"] == "Dashboard Session"


def test_empty_key_clears_the_stored_key(client):
    client.post("/api/providers/select", headers=auth(), json={"provider": "groq", "api_key": SECRET})
    client.post("/api/providers/select", headers=auth(), json={"provider": "groq", "api_key": ""})
    groq = next(p for p in client.get("/api/providers", headers=auth()).json()["providers"] if p["provider"] == "groq")
    assert groq["key_configured"] is False


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
