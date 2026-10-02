"""
Quality gate over the recorded real-world validation run.

tests/real_world_validation.py drives the real extension over live sites and writes what the side panel
actually showed to runs/real_world/summary.json. This module reads that recording back and holds it to the
standard the rectification asks for, so the real-world pass is checked rather than merely performed:

  - every finding shown to a person describes a specific problem, in plain language;
  - the status badge and the conclusion never contradict each other;
  - the evidence checklist is finding-level, not everything the scan collected;
  - what / why / fix are three different sentences;
  - Highlight either works, or explains itself honestly;
  - Ask AURA answers the finding that was open, and two findings never get the same answer;
  - different pages get different audit ids.

The tests skip when no recording exists, so the suite still runs on a machine with no network or no
provider key.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "runs" / "real_world" / "summary.json"

# Terms a normal user should never have to read in the default view.
JARGON = ["axe-core", "wcag", "aria-", "dom path", "css selector", "materiality", "cognitive load",
          "affordance", "assistive technology", "landmark", "tabindex", "innerhtml", "queryselector"]

GENERIC = ["this condition may make it more difficult for some people to view or use the page",
           "impacts overall visual hierarchy and user interaction flow",
           "users may have difficulty", "people may struggle"]

CONCLUSIONS = ("Confirmed problem", "Potential problem", "Needs review", "Advisory")


def _load():
    if not SUMMARY.exists():
        pytest.skip("no real-world recording: run `python tests/real_world_validation.py` first")
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    sites = {k: v for k, v in data.items() if not k.startswith("_")}
    scanned = {k: v for k, v in sites.items() if v.get("findings") is not None}
    if not scanned:
        pytest.skip("the real-world recording contains no successful scan")
    return data, scanned


def _findings(scanned):
    for site, record in scanned.items():
        for f in record["findings"]:
            yield site, f


def test_every_finding_has_a_specific_human_description():
    _, scanned = _load()
    for site, f in _findings(scanned):
        for field in ("title", "what", "why"):
            value = (f.get(field) or "").strip()
            assert value, f"{site}/{f['id']}: empty {field}"
            assert len(value) > 12, f"{site}/{f['id']}: {field} is not a real sentence: {value!r}"


def test_no_generic_explanation_reaches_a_real_finding():
    _, scanned = _load()
    for site, f in _findings(scanned):
        blob = " ".join(str(f.get(k) or "") for k in ("title", "what", "why", "fix", "meaning")).lower()
        for phrase in GENERIC:
            assert phrase not in blob, f"{site}/{f['id']} still shows the generic phrase '{phrase}'"


def test_human_view_stays_free_of_jargon():
    _, scanned = _load()
    offenders = []
    for site, f in _findings(scanned):
        blob = " ".join(str(f.get(k) or "") for k in ("title", "what", "why", "fix", "where", "meaning")).lower()
        for term in JARGON:
            if term in blob:
                offenders.append(f"{site}/{f['id']}: '{term}' in the default view")
    assert not offenders, offenders


def test_what_why_and_fix_are_three_different_sentences():
    _, scanned = _load()
    for site, f in _findings(scanned):
        norm = lambda t: re.sub(r"\s+", " ", (t or "").strip().lower()).rstrip(".")
        what, why, fix = norm(f.get("what")), norm(f.get("why")), norm(f.get("fix"))
        assert what != why, f"{site}/{f['id']}: 'What is wrong' repeats 'Why it matters'"
        if fix:
            assert fix != why, f"{site}/{f['id']}: 'What to do' repeats 'Why it matters'"
            assert fix != what, f"{site}/{f['id']}: 'What to do' repeats 'What is wrong'"


def test_status_and_conclusion_never_contradict():
    _, scanned = _load()
    for site, f in _findings(scanned):
        conclusion = f.get("conclusion") or ""
        shown = [c for c in CONCLUSIONS if c in conclusion]
        assert shown, f"{site}/{f['id']}: no recognised conclusion in {conclusion!r}"
        strength = shown[0]
        badges = " ".join(f.get("badges") or [])
        status = f.get("status") or ""
        assert strength in badges or strength in status, (
            f"{site}/{f['id']}: conclusion says '{strength}' but the badge says '{badges}' / '{status}'")
        # Only one of the four may appear, or the card is saying two things at once.
        assert len(shown) == 1, f"{site}/{f['id']}: conclusion names several strengths: {shown}"


def test_evidence_checklist_is_finding_level():
    _, scanned = _load()
    for site, f in _findings(scanned):
        checklist = f.get("evidence_checklist") or []
        assert len(checklist) <= 4, (
            f"{site}/{f['id']}: the checklist claims {len(checklist)} evidence kinds, which looks like the "
            f"audit's collection rather than this finding's own evidence: {checklist}")
        if f.get("rule") and "axe" in str(f.get("technical", {}).get("Detector", "")).lower():
            assert "Visual screenshot" not in checklist, (
                f"{site}/{f['id']}: a deterministic accessibility finding must not claim screenshot evidence")


def test_highlight_either_works_or_explains_itself():
    _, scanned = _load()
    honest = ("scan this page again", "no longer on the page", "several elements match",
              "cannot be looked up", "area of the page", "could not match this suggestion",
              "different page", "page as a whole", "covers several elements",
              "about a request the page made")
    for site, record in scanned.items():
        for h in record.get("highlight") or []:
            if not h.get("offered"):
                note = (h.get("note") or "").lower()
                assert any(k in note for k in honest), f"{site}/{h['finding']}: silent missing Highlight ({note!r})"
                continue
            result = (h.get("result") or "").lower()
            if "highlighted on the page" in result:
                continue
            assert any(k in result for k in honest), (
                f"{site}/{h['finding']}: Highlight failed without an honest reason: {result!r}")
            assert "not in content" not in result


def test_ask_aura_answers_the_finding_that_was_open():
    _, scanned = _load()
    for site, record in scanned.items():
        asks = [a for a in (record.get("ask") or []) if a.get("question") == "how to solve"]
        if len(asks) < 2:
            continue
        ids = [a["finding_id"] for a in asks]
        # Compare the answer body only: the citation chip and the cost note are appended to every answer,
        # so comparing the raw textContent would hide two findings that answer identically.
        bodies = [a["answer"].split("Answered directly from")[0].split("AI-generated answer")[0].strip()
                  for a in asks]
        answers = [a["answer"] for a in asks]
        assert len(set(ids)) == len(ids), f"{site}: the same finding was asked twice"
        assert len(set(bodies)) == len(bodies), (
            f"{site}: two different findings gave the same answer -> {ids}: {bodies[0][:160]!r}")
        for a in asks:
            assert a["answer"].strip(), f"{site}/{a['finding_id']}: empty answer"
            assert "Thinking" not in a["answer"], f"{site}/{a['finding_id']}: the answer never arrived"


def test_the_bookmyshow_regression_does_not_come_back():
    """A question on the region finding must answer about page sections, never about zoom or headings."""
    _, scanned = _load()
    probed = False
    for site, record in scanned.items():
        for a in record.get("ask") or []:
            probe = a.get("probe")
            if not probe:
                continue
            answer = a["answer"].lower()
            assert answer.strip(), f"{site}/{probe}: empty answer"
            # An unavailable provider is a legitimate outcome: AURA says so rather than answering from
            # some other finding. What matters is that it never substitutes one.
            if "provider unavailable" in answer or "provider request failed" in answer:
                assert "zoom" not in answer
                continue
            probed = True
            if probe == "region":
                assert "zoom" not in answer, f"{site}: the region question was answered about zoom: {answer[:200]!r}"
                assert any(k in answer for k in ("section", "region", "landmark", "not enough evidence")), (
                    f"{site}: the region question was not answered about sections: {answer[:200]!r}")
            if probe.startswith("heading"):
                assert "zoom" not in answer, f"{site}: the heading question was answered about zoom: {answer[:200]!r}"
                assert any(k in answer for k in ("heading", "outline", "not enough evidence")), (
                    f"{site}: the heading question was not answered about headings: {answer[:200]!r}")
    if not probed:
        pytest.skip("no region/heading finding was probed in this recording")


def test_screenshot_provenance_is_answered_truthfully():
    _, scanned = _load()
    for site, record in scanned.items():
        for a in record.get("ask") or []:
            if a.get("question") != "did you see this in the screenshot?":
                continue
            answer = a["answer"].lower()
            assert answer.startswith("yes") or answer.startswith("no") or "screenshot" in answer, (
                f"{site}: the screenshot question was not answered from provenance: {a['answer'][:120]!r}")


def test_each_page_gets_its_own_audit():
    data, scanned = _load()
    audits = {site: rec.get("audit_id") for site, rec in scanned.items()}
    ids = [a for a in audits.values() if a]
    assert len(set(ids)) == len(ids), f"two pages share an audit id: {audits}"
    for site, rec in scanned.items():
        assert rec.get("banner"), f"{site}: the panel showed no result banner"


def test_no_preview_ui_appeared_on_any_real_page():
    _, scanned = _load()
    for site, record in scanned.items():
        blob = json.dumps(record).lower()
        assert "preview fix" not in blob, f"{site}: Preview UI is still reachable"
        assert "revert preview" not in blob, f"{site}: Revert preview is still reachable"
