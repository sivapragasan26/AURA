"""
Ask AURA on a server that holds no provider key, and the wording a finding is explained with.

Four defects, all found by reading one real finding the panel produced for an overlapping-links problem
on a live page:

1. Ask AURA called the *server's* provider. The hosted deployment runs with AI_PROVIDER=mock on purpose
   - that is the whole point of the browser making the model call - so Ask AURA refused for every user,
   whatever they had selected in the panel, and told them to select a provider they had already
   selected. It is now split like a scan: the service builds the prompt, the browser calls the model.
2. extra_context() searched the rule, title and summary together and took the first match. The title
   "Overlapping navigation links create an unusable cluster" contains "link", so a finding about
   stacked elements was explained with advice about link text and screen readers.
3. determine_reproduction_and_trust() routed on category alone, so anything filed RESPONSIVENESS was
   described as content extending past the viewport - including an overlap, which has nothing to do
   with the viewport.
4. The confidence shown to the reader was the model's own self-report. A claim the model rated 0.95
   that the evidence could only support at 0.45 was displayed as "High confidence" next to a verdict of
   "Advisory".
"""
import json

import pytest
from starlette.testclient import TestClient

from aura.assistant.chat import cache_clear, interpret_ask, prepare_ask
from aura.assistant.explain import extra_context
from aura.interpretation.interpreter import interpret_finding
from aura.api.server import create_app
from aura.api.store import AuditStore
from aura.config import settings

SERVER_TOKEN = "s" * 40
HOST = "127.0.0.1:8765"

VIEW = {
    "audit_id": "AURA-2026-287133",
    "page_url": "https://example.test/catalogue",
    "page_title": "Catalogue",
    "findings": [
        {"id": "F-001", "title": "Overlapping navigation links create an unusable cluster",
         "category": "RESPONSIVENESS", "severity": "critical", "status": "Advisory",
         "summary": "Several navigation links are drawn on top of each other.",
         "verification_status": "UNCERTAIN", "confidence": 0.45,
         "location": "the navigation links", "location_description": "the navigation links",
         "recommendation": "Give each item room of its own.",
         "target": {"kind": "element", "label": "nav a"},
         "evidence": {"types": ["VISUAL", "STRUCTURAL"], "sources": ["dom_elements"], "flags": {}},
         "technical": {}, "human": {}},
    ],
}


@pytest.fixture(autouse=True)
def clean_cache():
    cache_clear()
    yield
    cache_clear()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # As deployed: no provider key of its own, and nothing written to disk.
    monkeypatch.setattr(settings, "PERSIST", False)
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(settings, "AI_PROVIDER", "mock", raising=False)
    store = AuditStore()
    app = create_app(token=SERVER_TOKEN, store=store)
    return TestClient(app), store


def install(c):
    r = c.post("/api/register", json={}, headers={"Host": HOST})
    assert r.status_code == 200, r.text
    return {"X-AURA-Token": r.json()["token"], "Host": HOST}


# ----------------------------------------------------------- 1. Ask AURA without a server-side key

def test_a_question_needing_the_model_comes_back_as_a_prompt_for_the_browser():
    prepared = prepare_ask(VIEW, "would this also confuse someone using a screen magnifier?", "F-001")
    assert prepared["state"] == "NEEDS_MODEL"
    assert prepared["scoped_finding_id"] == "F-001"
    assert "F-001" in prepared["prompt"], "the prompt must be scoped to the finding that was asked about"
    assert "Overlapping navigation links" in prepared["prompt"]


def test_a_standard_question_still_costs_no_ai_request():
    prepared = prepare_ask(VIEW, "how do i fix this?", "F-001")
    assert prepared["state"] == "OK", "a question the record answers must not reach a model"
    assert prepared["cited_finding_ids"] == ["F-001"]


def test_the_browsers_answer_is_accepted_and_grounded():
    raw = json.dumps({"answer": "The links sit on top of each other, so taps land on the wrong one.",
                      "cited_finding_ids": ["F-001"], "evidence_gaps": []})
    result = interpret_ask(VIEW, "would a magnifier user notice?", "F-001", raw, "groq", "qwen/qwen3.8-27b")
    assert result["state"] == "OK"
    assert result["cited_finding_ids"] == ["F-001"]
    assert result["provider"] == "groq"


def test_an_answer_citing_a_finding_this_audit_does_not_have_is_refused():
    raw = json.dumps({"answer": "See the other problem.", "cited_finding_ids": ["F-999"],
                      "evidence_gaps": []})
    result = interpret_ask(VIEW, "would a magnifier user notice?", "F-001", raw, "groq", "m")
    assert "F-999" not in result.get("cited_finding_ids", []), (
        "a citation of a finding this audit does not contain must be dropped, never passed through to "
        "a panel that would then try to open it")


def test_a_provider_failure_is_reported_as_a_failure_not_an_empty_answer():
    result = interpret_ask(VIEW, "would a magnifier user notice?", "F-001", None, "groq", "m",
                           failure={"message": "Groq rate limit reached."})
    assert result["state"] == "AI_UNAVAILABLE"
    assert "Groq rate limit reached." in result["message"]
    assert result["answer"] is None


def test_ask_works_on_a_service_with_no_provider_key_of_its_own(client):
    """
    The regression. The hosted service runs the mock provider by design, and Ask AURA used to refuse on
    that basis alone - so it was unusable in production no matter what the user selected.
    """
    c, store = client
    headers = install(c)
    store.put(VIEW, owner=__import__("aura.api.security", fromlist=["install_id"]).install_id(
        SERVER_TOKEN, headers["X-AURA-Token"]))

    r = c.post(f"/api/audits/{VIEW['audit_id']}/ask/prepare",
               json={"question": "would this confuse someone using a screen magnifier?", "finding_id": "F-001"},
               headers=headers)
    assert r.status_code == 200, r.text
    prepared = r.json()
    assert prepared["state"] == "NEEDS_MODEL", (
        "a service with no key must hand the prompt to the browser rather than refuse the question")

    raw = json.dumps({"answer": "Taps land on whichever link is in front.",
                      "cited_finding_ids": ["F-001"], "evidence_gaps": []})
    r = c.post(f"/api/audits/{VIEW['audit_id']}/ask/complete",
               json={"question": "would this confuse someone using a screen magnifier?", "finding_id": "F-001",
                     "provider": "groq", "model": "qwen/qwen3.8-27b", "response": raw},
               headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "OK"


def test_asking_about_a_finding_from_another_audit_is_refused(client):
    c, store = client
    headers = install(c)
    from aura.api.security import install_id
    store.put(VIEW, owner=install_id(SERVER_TOKEN, headers["X-AURA-Token"]))
    r = c.post(f"/api/audits/{VIEW['audit_id']}/ask/prepare",
               json={"question": "why?", "finding_id": "F-404"}, headers=headers)
    assert r.status_code == 404


# ----------------------------------------------------------- 2. the right explanation for the rule

def test_an_overlap_is_not_explained_as_a_link_problem():
    got = extra_context("overlapping_elements",
                        "Overlapping navigation links create an unusable cluster",
                        "Several navigation links are drawn on top of each other.")
    assert got is not None, "an overlap has something worth explaining"
    experience, good = got
    assert "click here" not in experience, (
        "the title contains the word 'link', which used to select advice about link text for screen "
        "readers - nothing to do with elements drawn on top of each other")
    assert "same place" in experience or "on top of" in experience


def test_the_rule_decides_before_the_wording_does():
    """A rule that matches a family wins, even when the title mentions another one."""
    experience, _ = extra_context("color-contrast", "Low contrast on the image caption link", "")
    assert "smudge" in experience, "contrast is the rule; 'image' and 'link' in the title must not win"


def test_the_wording_is_still_used_when_the_rule_says_nothing():
    got = extra_context("custom_unknown_rule", "Button has no accessible name", "")
    assert got is not None and "button" in got[0].lower()


# ----------------------------------------------------------- 3. the right conclusion for the rule

def test_an_overlap_is_not_described_as_running_off_the_screen():
    interp = interpret_finding({
        "id": "F-001", "title": "Overlapping navigation links create an unusable cluster",
        "description": "Several navigation links are drawn on top of each other.",
        "category": "RESPONSIVENESS", "source": "AI", "rule": "overlapping_elements",
        "verification_status": "UNCERTAIN", "confidence": 0.45, "ai_confidence": 0.95,
        "affected_element": {"selector": "nav a"},
        "evidence": {"types": ["VISUAL"], "sources": ["dom_elements"], "flags": {"layout_overlap": True}},
    })
    conclusion = interp["conclusion"]
    text = f"{conclusion['known_fact']} {conclusion['inferred_judgement']}".lower()
    assert "viewport" not in text and "sideways" not in text, (
        "an overlap was being reported as content extending past the edge of the screen, which is a "
        f"different problem the finding never claimed: {text}")
    assert "covers" in text or "shares space" in text


def test_an_actual_overflow_still_says_what_it_used_to():
    interp = interpret_finding({
        "id": "F-002", "title": "Table is wider than the screen", "description": "The table overflows.",
        "category": "RESPONSIVENESS", "source": "AI", "rule": "horizontal_overflow",
        "verification_status": "CONFIRMED", "confidence": 0.9,
        "affected_element": {"selector": "table"},
        "evidence": {"types": ["STRUCTURAL"], "sources": ["dom_elements"], "flags": {"document_overflow": True}},
    })
    text = f"{interp['conclusion']['known_fact']} {interp['conclusion']['inferred_judgement']}".lower()
    assert "viewport" in text or "sideways" in text


# ----------------------------------------------------------- 4. whose confidence is on display

def test_the_confidence_shown_is_auras_not_the_models():
    interp = interpret_finding({
        "id": "F-001", "title": "Overlapping navigation links create an unusable cluster",
        "description": "Several navigation links are drawn on top of each other.",
        "category": "RESPONSIVENESS", "source": "AI", "rule": "overlapping_elements",
        "verification_status": "UNCERTAIN",
        "confidence": 0.45,        # what the evidence supports
        "ai_confidence": 0.95,     # what the model said about its own claim
        "affected_element": {"selector": "nav a"},
        "evidence": {"types": ["VISUAL"], "sources": ["dom_elements"], "flags": {}},
    })
    assert interp["confidence_label"] == "Low", (
        "0.45 from verification is Low; showing the model's own 0.95 as 'High confidence' beside an "
        "Advisory verdict told the reader the opposite of what AURA had established")
    assert interp["status"] == "Advisory"


def test_the_models_own_number_is_still_recorded():
    """It is not hidden - it is just not presented as AURA's confidence."""
    interp = interpret_finding({
        "id": "F-001", "title": "Overlapping links", "description": "Drawn on top of each other.",
        "category": "RESPONSIVENESS", "source": "AI", "rule": "overlapping_elements",
        "verification_status": "UNCERTAIN", "confidence": 0.45, "ai_confidence": 0.95,
        "affected_element": {"selector": "nav a"},
        "evidence": {"types": ["VISUAL"], "sources": ["dom_elements"], "flags": {}},
    })
    assert "0.95" in json.dumps(interp["technical"]), "the model's self-report belongs in the technical block"
