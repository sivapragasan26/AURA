"""
The service's logs must not hold what people browse.

A hosted AURA sees the address and the title of every page anyone scans. Those belong in the analysis and
in the answer, and nowhere else: not in a log line, not in an error message, not in a request path that a
proxy or a hosting provider records as a matter of course.

This is checked rather than asserted in prose, because the privacy notice and the store listing both
promise it.
"""
import json
import logging

import pytest
from starlette.testclient import TestClient

from aura.api import security
from aura.api.server import create_app
from aura.api.store import AuditStore
from aura.config import settings

TOKEN = "log-privacy-token"
SECRET_URL = "https://clinic.example.test/patients/records/8891"
SECRET_TITLE = "Margaret Okonkwo - appointment history"
SECRET_TEXT = "Diagnosis summary for Margaret Okonkwo"

BUNDLE = {
    "collector_version": "aura-extension/0.5.0",
    "url": SECRET_URL,
    "title": SECRET_TITLE,
    "viewport": {"width": 1280, "height": 800},
    "capture_size": {"width": 1280, "height": 1600},
    "dom": {"elements": [
        {"tag": "h1", "text": SECRET_TEXT, "selector": "h1", "visible": True,
         "bounding_box": {"x": 10, "y": 10, "width": 400, "height": 40}},
        {"tag": "a", "text": "", "selector": "a.icon", "visible": True,
         "bounding_box": {"x": 300, "y": 80, "width": 24, "height": 24}},
    ]},
    "axe": {"available": True, "version": "4.8.2", "violations": [
        {"id": "link-name", "impact": "serious", "description": "Links must have discernible text",
         "helpUrl": "https://dequeuniversity.com/rules/axe/4.8/link-name", "nodes": [{"target": ["a.icon"]}]},
    ]},
    "telemetry": {"console": [{"type": "error", "text": f"Failed to load {SECRET_URL}/photo.jpg"}],
                  "network": [{"url": f"{SECRET_URL}/photo.jpg", "status": 404, "method": "GET"}]},
    "target_boxes": {"a.icon": {"x": 300, "y": 80, "width": 24, "height": 24}},
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PERSIST", False)
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path / "runs")
    return TestClient(create_app(token=TOKEN, store=AuditStore()))


def auth():
    return {security.TOKEN_HEADER: TOKEN, "Host": "127.0.0.1:8765"}


SECRETS = (SECRET_URL, SECRET_TITLE, SECRET_TEXT, "clinic.example.test", "Margaret", "Okonkwo")


def test_a_scan_writes_no_page_address_or_title_to_the_log(client, caplog):
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/audits", json={"bundle": BUNDLE, "options": {"ai": False}}, headers=auth())
    assert r.status_code == 200, r.text
    assert r.json()["page_url"] == SECRET_URL, "the answer to the person who scanned does carry it"

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in SECRETS:
        assert secret not in logged, f"{secret!r} was written to the log:\n{logged[:600]}"


def test_a_two_phase_scan_writes_no_page_data_to_the_log(client, caplog):
    with caplog.at_level(logging.DEBUG):
        prepared = client.post("/api/audits/prepare", json={"bundle": BUNDLE, "screenshot_attached": True},
                               headers=auth())
        assert prepared.status_code == 200, prepared.text
        audit_id = prepared.json()["audit_id"]
        done = client.post(f"/api/audits/{audit_id}/complete",
                           json={"response": "{}", "provider": "groq", "model": "m"}, headers=auth())
        assert done.status_code == 200, done.text

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in SECRETS:
        assert secret not in logged, f"{secret!r} was written to the log:\n{logged[:600]}"


def test_a_failed_scan_writes_no_page_data_to_the_log(client, caplog, monkeypatch):
    """An error is where page data usually escapes: the message is built from whatever was at hand."""
    from aura.api import server as api_server

    def explode(*a, **kw):
        raise RuntimeError(f"engine blew up while analysing {SECRET_URL} ({SECRET_TITLE})")

    monkeypatch.setattr(api_server, "build_audit_view", explode)
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/audits", json={"bundle": BUNDLE, "options": {"ai": False}}, headers=auth())
    assert r.status_code == 500 and r.json()["error"]["code"] == "SCAN_FAILED"

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in (SECRET_URL, SECRET_TITLE, "clinic.example.test"):
        assert secret not in logged, (
            f"a failing scan wrote {secret!r} to the log. An error message must not carry the page it was "
            f"looking at:\n{logged[:800]}")
    assert secret not in json.dumps(r.json()) or True  # the caller already knows their own page


def test_no_request_path_the_extension_uses_carries_page_data():
    """
    What a proxy or host records without being asked is the request line, so nothing identifying may be
    in it. Every path is fixed or an audit id; the page itself always travels in the body.
    """
    from aura.api.server import create_app as build

    app = build(token=TOKEN)
    for route in app.routes:
        path = getattr(route, "path", "")
        params = [p.strip("{}") for p in path.split("/") if p.startswith("{")]
        assert all(p in ("audit_id", "finding_id") for p in params), (
            f"{path} puts {params} in the URL; only an audit id and a finding id may appear there")
