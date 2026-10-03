"""
One install's scan is not another install's to read.

The hosted service answers every AURA install, and a valid token only says a request came from one of
them. Audit ids are a running number, so an audit must belong to the install that made it: a view carries
the page's address, its title, text from it and everything AURA concluded about it.

These tests act as two separate installs against one server, which is exactly the hosted situation.
"""
import json

import pytest
from starlette.testclient import TestClient

from aura.api import security
from aura.api.server import create_app
from aura.api.store import AuditStore
from aura.config import settings

SERVER_TOKEN = "server-token-" + "z" * 30

BUNDLE = {
    "collector_version": "aura-extension/0.5.0",
    "url": "https://private.example.test/invoice/8891",
    "title": "Invoice 8891",
    "viewport": {"width": 1280, "height": 800},
    "capture_size": {"width": 1280, "height": 1600},
    "dom": {"elements": [
        {"tag": "button", "text": "Pay now", "selector": "#pay", "visible": True,
         "bounding_box": {"x": 10, "y": 20, "width": 120, "height": 40}},
        {"tag": "a", "text": "", "selector": "a.icon", "visible": True,
         "bounding_box": {"x": 300, "y": 20, "width": 24, "height": 24}},
    ]},
    # One real accessibility violation, so the scan has a finding to explain, ask about and crop.
    "axe": {"available": True, "version": "4.8.2", "violations": [
        {"id": "link-name", "impact": "serious", "description": "Links must have discernible text",
         "helpUrl": "https://dequeuniversity.com/rules/axe/4.8/link-name",
         "nodes": [{"target": ["a.icon"]}]},
    ]},
    "target_boxes": {"a.icon": {"x": 300, "y": 20, "width": 24, "height": 24}},
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    # As deployed: nothing is written down, so nothing can be read back off a disk either.
    monkeypatch.setattr(settings, "PERSIST", False)
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path / "runs")
    return TestClient(create_app(token=SERVER_TOKEN, store=AuditStore()))


def install(client):
    """A fresh install, with its own token, as the extension gets on first use."""
    r = client.post("/api/register", json={}, headers={"Host": "127.0.0.1:8765"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    return {"X-AURA-Token": token, "Host": "127.0.0.1:8765"}


def scan(client, headers):
    """A deterministic scan, which needs no AI provider, and its stored audit id."""
    r = client.post("/api/audits", json={"bundle": BUNDLE, "options": {"ai": False}}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["audit_id"], r.json()


def test_two_installs_get_different_identities():
    a, b = security.issue_install_token(SERVER_TOKEN), security.issue_install_token(SERVER_TOKEN)
    assert security.install_id(SERVER_TOKEN, a) != security.install_id(SERVER_TOKEN, b)
    assert security.install_id(SERVER_TOKEN, a) == security.install_id(SERVER_TOKEN, a)
    # The identity must not be the token, nor let anyone work back to it.
    ident = security.install_id(SERVER_TOKEN, a)
    assert a not in ident and ident not in a and len(ident) == 24


def test_another_install_cannot_read_a_stored_audit(client):
    mine, theirs = install(client), install(client)
    audit_id, view = scan(client, mine)

    assert client.get(f"/api/audits/{audit_id}", headers=mine).status_code == 200
    r = client.get(f"/api/audits/{audit_id}", headers=theirs)
    assert r.status_code == 404, f"another install read the audit: {r.text[:300]}"
    assert "private.example.test" not in r.text and "Invoice 8891" not in r.text


def test_another_install_cannot_explain_ask_or_screenshot_someone_elses_finding(client):
    mine, theirs = install(client), install(client)
    audit_id, view = scan(client, mine)
    finding = (view.get("findings") or [None])[0]
    assert finding, "the fixture page must produce at least one deterministic finding"
    fid = finding["id"]

    assert client.post(f"/api/audits/{audit_id}/findings/{fid}/explain", json={}, headers=mine).status_code == 200
    for path, method, body in (
        (f"/api/audits/{audit_id}/findings/{fid}/explain", "post", {}),
        (f"/api/audits/{audit_id}/ask", "post", {"question": "what is wrong?", "finding_id": fid}),
        (f"/api/audits/{audit_id}/findings/{fid}/screenshot", "get", None),
    ):
        r = client.post(path, json=body, headers=theirs) if method == "post" else client.get(path, headers=theirs)
        assert r.status_code == 404, f"{path} answered another install with {r.status_code}: {r.text[:200]}"
        assert "private.example.test" not in r.text and "Invoice 8891" not in r.text


def test_another_install_cannot_complete_a_prepared_scan(client):
    mine, theirs = install(client), install(client)
    r = client.post("/api/audits/prepare", json={"bundle": BUNDLE, "screenshot_attached": False}, headers=mine)
    assert r.status_code == 200, r.text
    audit_id = r.json()["audit_id"]

    stolen = client.post(f"/api/audits/{audit_id}/complete",
                         json={"response": "{}", "provider": "groq", "model": "m"}, headers=theirs)
    assert stolen.status_code == 404 and stolen.json()["error"]["code"] == "SCAN_NOT_PENDING", stolen.text
    # And the real owner can still complete it: refusing the stranger must not consume the scan.
    ours = client.post(f"/api/audits/{audit_id}/complete",
                       json={"response": "{}", "provider": "groq", "model": "m"}, headers=mine)
    assert ours.status_code == 200, ours.text
    assert ours.json()["audit_id"] == audit_id


def test_an_audit_id_cannot_be_found_by_counting(client):
    """The ids are sequential; what stops enumeration is ownership, so that is what is checked."""
    mine, theirs = install(client), install(client)
    audit_id, _ = scan(client, mine)
    year, number = audit_id.split("-")[1], int(audit_id.split("-")[2])
    neighbours = [f"AURA-{year}-{n:06d}" for n in range(max(1, number - 3), number + 4)]
    assert audit_id in neighbours
    for candidate in neighbours:
        r = client.get(f"/api/audits/{candidate}", headers=theirs)
        assert r.status_code == 404, f"{candidate} was readable by another install"


def test_the_server_token_still_reads_its_own_audits(client):
    """A self-hoster uses the server's own token for everything; that must keep working."""
    own = {"X-AURA-Token": SERVER_TOKEN, "Host": "127.0.0.1:8765"}
    audit_id, _ = scan(client, own)
    assert client.get(f"/api/audits/{audit_id}", headers=own).status_code == 200


def test_a_persisted_audit_is_readable_on_the_machine_that_wrote_it(monkeypatch, tmp_path):
    """
    Persistence means a personal machine, where the audit on disk belongs to the person at it.

    The hosted service never reaches this path: it writes nothing down.
    """
    monkeypatch.setattr(settings, "PERSIST", True)
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path / "runs")
    store = AuditStore()
    store.put({"audit_id": "AURA-2026-123456", "page_url": "https://local.example.test/"}, owner="whoever")
    fresh = AuditStore()  # a restart: memory is gone, the file is not
    assert fresh.get("AURA-2026-123456", owner="someone-else") is not None

    monkeypatch.setattr(settings, "PERSIST", False)
    assert AuditStore().get("AURA-2026-123456", owner="someone-else") is None
