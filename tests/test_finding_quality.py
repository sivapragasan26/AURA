"""
Finding quality: an AI candidate becomes a CONFIRMED finding only when measurements support it.

Before this phase any UI/UX candidate whose target element merely existed and was visible was CONFIRMED
(aura/verification/rules.py checked `flags["screenshot"]`, which is always true). These tests pin the new
behaviour of aura/verification/materiality.py and the rules that use it.
"""
import pytest

from aura.models.findings import (
    AccessibilityViolation, CandidateFinding, FindingEvidenceDetail, VerificationStatus,
)
from aura.verification.materiality import assess
from aura.verification.rules import VerificationRulesEngine

RULES = VerificationRulesEngine()
DOM_FLAGS = {"screenshot": True, "dom": True}


def candidate(rule, title, description="", category="UI", confidence=0.95, selector="#target"):
    return CandidateFinding(
        id="AI-001", candidate_id="AI-001", category=category, title=title, description=description,
        observation=description, severity="high", confidence=confidence,
        affected_element={"selector": selector, "tag": "div", "text": ""},
        evidence=FindingEvidenceDetail(type="visual", description="screenshot"),
        rule_type=rule, normalized_rule=rule)


def element(selector="#target", tag="button", text="Go", x=0, y=0, w=100, hgt=40, visible=True, ids=None):
    return {"selector": selector, "tag": tag, "text": text, "visible": visible,
            "bounding_box": {"x": x, "y": y, "width": w, "height": hgt}, "id": selector.lstrip("#"),
            "id_chain": ids if ids is not None else [selector.lstrip("#")]}


def dom(elements, styles=None):
    styles = styles or {}
    return {"all_elements": elements,
            "raw_elements_with_styles": [{"selector": e["selector"], "computed_style": styles.get(e["selector"], {})} for e in elements]}


def verify(cand, target, dom_summary, flags=None, violations=None):
    return RULES.evaluate_status_and_confidence(cand, {**DOM_FLAGS, **(flags or {})}, [target] if target else [],
                                                None, dom_summary=dom_summary, accessibility_violations=violations or [])


# ---------------------------------------------------------------- rejected: not defects by themselves

def test_blank_space_alone_is_rejected():
    t = element("#hero", "div", "")
    status, _, reason = verify(candidate("poor_grouping", "Large blank area on the right", "A big empty space sits next to the hero"),
                               t, dom([t]))
    assert status == VerificationStatus.REJECTED and "Blank or empty space alone is not a defect" in reason


def test_blank_space_with_measured_obstruction_is_not_rejected():
    t = element("#hero", "div", "")
    status, _, _ = verify(candidate("overlapping_elements", "Empty overlay covers the buttons", "The blank overlay hides the controls"),
                          t, dom([t]), flags={"layout_overlap": True})
    assert status != VerificationStatus.REJECTED


def test_merely_unusual_appearance_is_rejected():
    t = element("#promo", "div", "Deal of the day")
    status, _, reason = verify(candidate("inconsistent_component_styling", "Unusual layout style",
                                         "The section looks unconventional compared with the rest of the page"), t, dom([t]))
    assert status == VerificationStatus.REJECTED and "not a defect" in reason


def test_claim_that_repeats_an_axe_finding_is_not_a_separate_finding():
    t = element("#buy", "button", "Buy now")
    viol = AccessibilityViolation(rule="color-contrast", impact="serious", description="contrast", target=["#buy"])
    status, _, reason = verify(candidate("misleading_visual_emphasis", "Button text has low contrast",
                                         "The label is hard to read against the background"), t, dom([t]), violations=[viol])
    assert status == VerificationStatus.REJECTED and "axe-core" in reason


def test_hidden_element_with_a_visible_twin_is_responsive_markup_not_a_defect():
    hidden = element("#nav-mobile", "a", "Account", visible=False)
    twin = element("#nav-desktop", "a", "Account")
    status, _, reason = verify(candidate("visually_hidden_important_information", "Account link is hidden"), hidden,
                               dom([hidden, twin]))
    assert status == VerificationStatus.REJECTED and "responsive or duplicated markup" in reason


# ---------------------------------------------------------------- confirmed only with measurements

def test_weak_primary_cta_confirmed_when_a_peer_is_measurably_stronger():
    cta = element("#cta", "a", "Continue", w=80, hgt=20, ids=["cta", "panel"])
    rival = element("#danger", "button", "Delete everything", w=320, hgt=60, ids=["danger", "panel"])
    styles = {"#cta": {"font_size": "11px", "font_weight": "400", "background_color": "rgba(0, 0, 0, 0)"},
              "#danger": {"font_size": "20px", "font_weight": "700", "background_color": "rgb(200, 30, 30)"}}
    status, score, reason = verify(candidate("weak_primary_cta", "Primary action is easy to miss"), cta,
                                   dom([cta, rival], styles))
    assert status == VerificationStatus.CONFIRMED and score >= 0.85 and "measured" in reason


def test_weak_primary_cta_rejected_when_the_target_is_already_dominant():
    cta = element("#cta", "button", "Continue", w=320, hgt=60, ids=["cta", "panel"])
    small = element("#help", "a", "Help", w=40, hgt=14, ids=["help", "panel"])
    styles = {"#cta": {"font_size": "22px", "font_weight": "700", "background_color": "rgb(20, 90, 200)"},
              "#help": {"font_size": "11px", "font_weight": "400", "background_color": "rgba(0, 0, 0, 0)"}}
    status, _, reason = verify(candidate("weak_primary_cta", "Primary action does not stand out"), cta,
                               dom([cta, small], styles))
    assert status == VerificationStatus.REJECTED and "already clearly the most prominent" in reason


def test_inverted_hierarchy_in_a_section_is_measured_from_the_controls_inside_it():
    section = element("#actions", "div", "", w=600, hgt=200, ids=["actions"])
    destructive = element("#del", "button", "Delete workspace", w=320, hgt=60, ids=["del", "actions"])
    primary = element("#save", "button", "Save changes", w=90, hgt=24, ids=["save", "actions"])
    styles = {"#del": {"font_size": "20px", "font_weight": "700", "background_color": "rgb(200, 40, 40)"},
              "#save": {"font_size": "12px", "font_weight": "400", "background_color": "rgba(0, 0, 0, 0)"}}
    status, _, reason = verify(candidate("bad_visual_hierarchy", "Destructive action dominates"), section,
                               dom([section, destructive, primary], styles))
    assert status == VerificationStatus.CONFIRMED and "destructive action is visually stronger" in reason


def test_ai_confidence_alone_never_confirms():
    t = element("#box", "div", "Some section", ids=["box"])
    cand = candidate("poor_task_flow", "This flow is confusing", confidence=0.99, category="UX")
    status, _, _ = verify(cand, t, dom([t]))
    assert status == VerificationStatus.LIKELY  # judgement: verified target, unmeasurable opinion


def test_design_judgement_is_likely_not_confirmed():
    form = element("#signup", "form", "", ids=["signup"])
    status, _, reason = verify(candidate("confusing_form", "The signup form is confusing", category="UX"), form, dom([form]))
    assert status == VerificationStatus.LIKELY and "design judgement" in reason


def test_claim_without_a_matched_element_is_uncertain_not_likely():
    status, score, reason = verify(candidate("poor_alignment", "Things look misaligned somewhere"), None, dom([]),
                                   flags={"dom": False})
    assert status == VerificationStatus.UNCERTAIN and score <= 0.5 and "nothing could be measured" in reason


def test_navigation_claim_needs_more_than_an_existing_element():
    link = element("#nav", "a", "Shop")
    cand = candidate("bad_navigation", "Navigation is broken", category="NAVIGATION")
    status, _, reason = verify(cand, link, dom([link]))
    assert status == VerificationStatus.UNCERTAIN and "no obstruction, dead link, failed interaction" in reason


def test_navigation_claim_confirmed_with_a_placeholder_link():
    link = element("#nav", "a", "Shop")
    cand = candidate("bad_navigation", "Navigation link goes nowhere", category="NAVIGATION")
    status, _, _ = verify(cand, link, dom([link]), flags={"placeholder_href": True})
    assert status == VerificationStatus.CONFIRMED


# ---------------------------------------------------------------- the gate itself

@pytest.mark.parametrize("rule,verdict", [
    ("excessive_information_density", "JUDGEMENT"),  # element counts alone cannot settle density
    ("poor_spacing_consistency", "JUDGEMENT"),       # too few neighbours to measure
])
def test_unmeasurable_claims_stay_judgements_rather_than_refusals(rule, verdict):
    t = element("#sec", "div", "", ids=["sec"])
    assert assess(candidate(rule, "…"), t, dom([t]), [], {}).verdict == verdict


def test_measurements_are_reported_with_the_decision():
    cta = element("#cta", "a", "Go", w=60, hgt=18, ids=["cta", "row"])
    rival = element("#big", "button", "Delete", w=300, hgt=60, ids=["big", "row"])
    m = assess(candidate("weak_primary_cta", "…"), cta, dom([cta, rival]), [], {})
    assert m.verdict == "SUPPORTED" and "ratio" in m.measurements and "measured:" in m.note
