"""
Fitting a scan into what the chosen provider will actually accept, and the origin rule that decides
which installs may ask.

Bug (fixed): Groq's free tier meters input at 7,000 tokens per minute. The engine's own Groq client has
shaped its requests to fit that for a long time, but when the model call moved into the browser the
browser began sending the prompt and the full-page capture unshaped. A scan of an ordinary page was
measured at 7,016 tokens against that 7,000 limit; Groq refused the whole request and the extension
reported "AI analysis unavailable" on every real page while the benchmark, which uses the Python path,
kept passing.

Bug (fixed, configuration): AURA_ALLOWED_ORIGINS replaces the default rather than adding to it, so
setting it to the published extension's id refused every other install - including a copy loaded from
disk - with ORIGIN_NOT_ALLOWED.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from aura.agent.request_shaping import compact_packet_prompt, shaped_prompt
from aura.api import security
from aura.api.server import create_app
from aura.api.store import AuditStore
from aura.config import models, settings

SERVER_TOKEN = "s" * 40
HOST = "127.0.0.1:8765"
SHAPED_MODEL = "qwen/qwen3.8-27b"          # Groq free tier: 7,000 input tokens per minute
UNSHAPED_MODEL = "gemini-3.6-flash"        # a far larger input allowance; nothing to shape

BUNDLE = {
    "collector_version": "aura-extension/0.5.0",
    "url": "https://example.test/catalogue",
    "title": "Catalogue",
    "viewport": {"width": 1280, "height": 800},
    "capture_size": {"width": 1280, "height": 9600},
    # A page with far more elements than a tight input budget can carry.
    "dom": {"elements": [
        {"tag": "button", "text": f"Action {i}", "selector": f"#b{i}", "visible": True,
         "bounding_box": {"x": 10, "y": 20 + i * 30, "width": 160, "height": 40}}
        for i in range(90)
    ]},
    "axe": {"available": True, "version": "4.8.2", "violations": []},
    "telemetry": {"capture_scope": "post_load", "page_load_time_ms": 100, "console": [], "network": []},
    "interactions": [],
    "captured_at": "2026-10-06T00:00:00Z",
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PERSIST", False)
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path / "runs")
    return TestClient(create_app(token=SERVER_TOKEN, store=AuditStore()))


def install(client):
    r = client.post("/api/register", json={}, headers={"Host": HOST})
    assert r.status_code == 200, r.text
    return {"X-AURA-Token": r.json()["token"], "Host": HOST}


def prepare(client, headers, model=None):
    body = {"bundle": BUNDLE, "screenshot_attached": True}
    if model is not None:
        body["model"] = model
    r = client.post("/api/audits/prepare", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------- shaping the prompt

def test_a_metered_model_gets_a_prompt_inside_its_budget(client):
    prepared = prepare(client, install(client), SHAPED_MODEL)
    budget = models.shaping_for(SHAPED_MODEL)["max_prompt_chars"]
    assert len(prepared["prompt"]) <= budget, (
        f"the prompt is {len(prepared['prompt'])} characters against a {budget} budget; Groq refuses "
        f"the whole request when the input exceeds its per-minute allowance")


def test_a_model_with_room_is_sent_the_evidence_whole(client):
    headers = install(client)
    shaped = prepare(client, headers, SHAPED_MODEL)
    whole = prepare(client, headers, UNSHAPED_MODEL)
    assert len(whole["prompt"]) > len(shaped["prompt"]), (
        "shaping a provider that does not need it would throw away evidence for nothing")
    assert "image" not in whole


def test_an_extension_that_cannot_name_its_model_is_served_as_before(client):
    """The published build does not send `model` yet; it must keep working while the update is in review."""
    headers = install(client)
    silent = prepare(client, headers)
    whole = prepare(client, headers, UNSHAPED_MODEL)
    assert len(silent["prompt"]) == len(whole["prompt"])
    assert "image" not in silent


def test_the_browser_is_told_how_far_to_shrink_its_capture(client):
    """The screenshot never reaches the service, so only the browser can resize it."""
    directive = prepare(client, install(client), SHAPED_MODEL)["image"]
    assert directive["max_dim"] == 480 and directive["format"] == "image/jpeg"
    assert 1 <= directive["quality"] <= 100
    assert "7,000 input tokens" in directive["reason"], "the panel shows this, so it has to read as English"


def test_a_shaped_scan_completes(client):
    """
    The shaped prompt is the one the browser is given, so it must also be the one kept: an answer is
    interpreted against the stored prompt, and keeping the unshaped version would judge the model on
    evidence it was never shown. A scan that completes proves the two halves still agree.
    """
    headers = install(client)
    prepared = prepare(client, headers, SHAPED_MODEL)
    r = client.post(f"/api/audits/{prepared['audit_id']}/complete",
                    json={"provider": "groq", "model": SHAPED_MODEL, "vision": True,
                          "response": json.dumps({"findings": []}), "meta": {}},
                    headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ai"]["state"] in ("AI_OK", "AI_RESPONSE_INVALID")


def test_an_answer_given_without_the_picture_is_not_recorded_as_having_seen_one(client):
    """
    When the provider refuses for size, the browser retries without the screenshot. The record has to
    say the model answered blind, or a visual claim would be credited to a picture it never received.
    """
    headers = install(client)
    prepared = prepare(client, headers, SHAPED_MODEL)
    r = client.post(f"/api/audits/{prepared['audit_id']}/complete",
                    json={"provider": "groq", "model": SHAPED_MODEL, "vision": True,
                          "response": json.dumps({"findings": []}),
                          "meta": {"image_dropped": True}},
                    headers=headers)
    assert r.status_code == 200, r.text


# --------------------------------------------------------------- the compaction itself

def _prompt_with(n_elements):
    packet = {"page": {"url": "https://example.test/"},
              "targeted_dom": [{"ref": f"E{i}", "selector": f"#b{i}", "text": f"Action {i}"} for i in range(n_elements)]}
    return ("Follow these instructions.\n\n```json\n" + json.dumps(packet)
            + "\n```\n\nReturn JSON matching the schema above.")


def test_compaction_trims_the_elements_and_keeps_everything_else():
    out = compact_packet_prompt(_prompt_with(90), max_dom_elements=18, max_chars=100_000)
    assert out.startswith("Follow these instructions.")
    assert out.rstrip().endswith("Return JSON matching the schema above.")
    kept = json.loads(out.split("```json")[1].split("```")[0])
    assert len(kept["targeted_dom"]) == 18
    assert kept["targeted_dom"][0]["ref"] == "E0", "the elements kept are the ones ranked most likely to matter"
    assert kept["page"]["url"] == "https://example.test/"


def test_compaction_cuts_again_when_the_first_pass_is_still_too_long():
    out = compact_packet_prompt(_prompt_with(90), max_dom_elements=18, max_chars=900)
    kept = json.loads(out.split("```json")[1].split("```")[0])
    assert len(kept["targeted_dom"]) == 15


def test_a_prompt_already_inside_the_budget_loses_no_evidence():
    """Whitespace is still squeezed out of the packet - that is free - but no element is dropped."""
    small = _prompt_with(4)
    out = compact_packet_prompt(small, max_dom_elements=18, max_chars=100_000)
    assert json.loads(out.split("```json")[1].split("```")[0]) == \
           json.loads(small.split("```json")[1].split("```")[0])
    assert len(out) <= len(small)


def test_no_shaping_means_no_change():
    assert shaped_prompt("anything at all", None) == "anything at all"


# --------------------------------------------------------------- which installs may ask

def test_by_default_every_extension_install_is_accepted_and_no_web_page_is(client):
    """
    Two different extension ids - a store install and a copy loaded from disk - must both work. This is
    the default, and it is what AURA_ALLOWED_ORIGINS is usually reached for by mistake.
    """
    store = "chrome-extension://" + "a" * 32
    unpacked = "chrome-extension://" + "b" * 32
    for origin in (store, unpacked):
        r = client.post("/api/register", json={}, headers={"Host": HOST, "Origin": origin})
        assert r.status_code == 200, f"{origin} was refused: {r.text}"
    r = client.post("/api/register", json={}, headers={"Host": HOST, "Origin": "https://example.com"})
    assert r.status_code == 403


def test_the_browser_side_retry_rules_hold():
    """
    The half of this fix that lives in the extension. Without this the JavaScript tests exist but the
    suite never runs them, which is the same as not having them.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    suite = Path(__file__).resolve().parent / "extension_js" / "oversize.test.mjs"
    r = subprocess.run([node, "--test", str(suite)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


def test_naming_one_install_locks_out_every_other_one(monkeypatch, client):
    """The regression: setting this to the published id refused the Chrome copy with ORIGIN_NOT_ALLOWED."""
    store = "chrome-extension://" + "a" * 32
    unpacked = "chrome-extension://" + "b" * 32
    monkeypatch.setenv("AURA_ALLOWED_ORIGINS", store)
    assert security.origin_allowed(store, security.allowed_origins()) is True
    assert security.origin_allowed(unpacked, security.allowed_origins()) is False, (
        "AURA_ALLOWED_ORIGINS replaces the default rather than adding to it; this is the behaviour that "
        "took the Chrome install offline when the Edge id was set on the deployed service")
