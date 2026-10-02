"""
Tests for AURA Final Finding Quality Gate.

Validates the final quality fixes:
1. Empty-space false positive rejections (whitespace alone is not a defect)
2. Target inaccuracies / The Spotify #main guard:
   - Page-level containers are not treated as button clusters
   - Skip links are excluded from peer controls
   - Differing control sizes inside containers is recognized as expected visual hierarchy
   - Navigation claims targeting #main are flagged as target mismatches
3. Harmonized verification status & conclusion strength (no fake 'Confirmed problem')
4. Complete eradication of forbidden jargon in Human view:
   - landmark, affordance, hierarchy, semantic, assistive technology, cognitive load, prominence, materiality, wcag, axe-core
5. Complete elimination of repetitive generic sentences
6. Preview is completely removed
7. Finding-specific evidence checklist
"""
import pytest
from typing import Dict, Any, List

from aura.models.findings import (
    CandidateFinding, FindingEvidenceDetail, VerificationStatus, AccessibilityViolation
)
from aura.verification.materiality import assess, _is_page_level_container, _is_valid_peer_control
from aura.verification.rules import VerificationRulesEngine
from aura.interpretation.interpreter import (
    interpret_finding,
    generate_evidence_summary,
    determine_reproduction_and_trust,
    AXE_INTERPRETATIONS,
    AI_INTERPRETATIONS,
    RUNTIME_INTERPRETATIONS,
)
from aura.findings.aggregation import FindingsAggregator

RULES = VerificationRulesEngine()
DOM_FLAGS = {"screenshot": True, "dom": True}

FORBIDDEN_JARGON = [
    "landmark",
    "affordance",
    "hierarchy",
    "semantic",
    "assistive technology",
    "cognitive load",
    "prominence",
    "materiality",
    "wcag",
    "axe-core",
    "css selector",
    "dom path",
]


def make_candidate(rule: str, title: str, description: str = "", category: str = "UI", confidence: float = 0.90, selector: str = "#target"):
    return CandidateFinding(
        id="AI-TST",
        candidate_id="AI-TST",
        category=category,
        title=title,
        description=description,
        observation=description,
        severity="medium",
        confidence=confidence,
        affected_element={"selector": selector, "tag": "div", "text": ""},
        evidence=FindingEvidenceDetail(type="visual", description="screenshot analysis"),
        rule_type=rule,
        normalized_rule=rule,
    )


def make_element(selector="#target", tag="button", text="Click", x=0, y=0, w=100, hgt=40, visible=True, ids=None):
    clean_id = selector.lstrip("#").split(".")[0]
    return {
        "selector": selector,
        "tag": tag,
        "text": text,
        "visible": visible,
        "bounding_box": {"x": x, "y": y, "width": w, "height": hgt},
        "id": clean_id,
        "id_chain": ids if ids is not None else [clean_id],
    }


def make_dom(elements, styles=None):
    styles = styles or {}
    return {
        "all_elements": elements,
        "raw_elements_with_styles": [
            {"selector": e["selector"], "computed_style": styles.get(e["selector"], {})}
            for e in elements
        ],
    }


def verify_candidate(cand, target, dom_summary, flags=None, violations=None):
    return RULES.evaluate_status_and_confidence(
        cand,
        {**DOM_FLAGS, **(flags or {})},
        [target] if target else [],
        None,
        dom_summary=dom_summary,
        accessibility_violations=violations or [],
    )


# =============================================================================
# 1. Empty-Space False Positive Rejections
# =============================================================================

@pytest.mark.parametrize("claim_text", [
    "There is a large empty area on the right",
    "There is unused space in the hero section",
    "The layout contains blank space",
    "This area does not contain content",
    "The page has excessive whitespace",
    "Large blank gap between content cards",
    "Unfilled space in container",
    "Dead space observed in the main layout",
])
def test_whitespace_claims_alone_are_rejected(claim_text):
    t = make_element("#container", "div", "")
    cand = make_candidate("poor_spacing_consistency", claim_text, claim_text)
    status, score, reason = verify_candidate(cand, t, make_dom([t]))
    assert status == VerificationStatus.REJECTED
    assert "Blank or empty space alone is not a defect" in reason


def test_whitespace_with_measured_harm_is_not_rejected():
    t = make_element("#overlay", "div", "")
    cand = make_candidate("overlapping_elements", "Empty space overlay obstructs buttons", "Blank overlay covers actions")
    status, _, _ = verify_candidate(cand, t, make_dom([t]), flags={"layout_overlap": True})
    assert status != VerificationStatus.REJECTED


# =============================================================================
# 2. Target Inaccuracies & The Spotify #main Guard
# =============================================================================

def test_page_level_container_detection():
    assert _is_page_level_container({"selector": "#main", "tag": "main", "id": "main"}) is True
    assert _is_page_level_container({"selector": "main", "tag": "main", "id": ""}) is True
    assert _is_page_level_container({"selector": "body", "tag": "body", "id": ""}) is True
    assert _is_page_level_container({"selector": "#root", "tag": "div", "id": "root"}) is True
    assert _is_page_level_container({"selector": "#__next", "tag": "div", "id": "__next"}) is True
    assert _is_page_level_container({"selector": ".btn-primary", "tag": "button", "id": "btn"}) is False


def test_skip_link_filtered_from_peer_controls():
    skip = make_element("#skip", "a", "Skip to main content", w=100, hgt=20)
    normal = make_element("#play", "button", "Play", w=80, hgt=40)
    zero_dim = make_element("#ghost", "button", "Invisible", w=0, hgt=0)
    hidden = make_element("#hidden", "button", "Hidden", visible=False)

    assert _is_valid_peer_control(skip) is False
    assert _is_valid_peer_control(zero_dim) is False
    assert _is_valid_peer_control(hidden) is False
    assert _is_valid_peer_control(normal) is True


def test_spotify_main_container_not_evaluated_as_button_group():
    """#main container holding a tiny skip link and big buttons must NOT return a confirmed hierarchy bug."""
    main_el = make_element("#main", "main", "", w=1200, hgt=900, ids=["main"])
    skip = make_element("#skip", "a", "Skip to main content", w=1, hgt=1, ids=["skip", "main"])
    hero_btn = make_element("#hero-play", "button", "Play Album", w=140, hgt=48, ids=["hero-play", "main"])
    styles = {
        "#hero-play": {"font_size": "16px", "font_weight": "700", "background_color": "#1db954"},
        "#skip": {"font_size": "12px", "font_weight": "400", "background_color": "transparent"},
    }
    cand = make_candidate("bad_visual_hierarchy", "Inverted hierarchy in main", selector="#main")
    m = assess(cand, main_el, make_dom([main_el, skip, hero_btn], styles), [], {})
    assert m.verdict == "JUDGEMENT"
    assert "page-level container" in m.reason.lower()


def test_navigation_claim_targeting_page_container_is_downgraded():
    """If the claim discusses top navigation/search but matches #main, it must be flagged as a target mismatch."""
    main_el = make_element("#main", "main", "", ids=["main"])
    cand = make_candidate("search_discoverability", "Search bar is difficult to find", "Search control in top navigation is hidden", selector="#main")
    m = assess(cand, main_el, make_dom([main_el]), [], {})
    assert m.verdict == "WEAK"
    assert "page-level container" in m.reason.lower()


def test_controls_with_different_sizes_in_section_is_expected_hierarchy():
    """In a normal card, having a large primary button and a smaller secondary link is normal design, NOT a defect."""
    card = make_element("#card", "div", "", ids=["card"])
    primary = make_element("#buy", "button", "Buy Now", w=200, hgt=50, ids=["buy", "card"])
    secondary = make_element("#terms", "a", "Terms", w=50, hgt=16, ids=["terms", "card"])
    styles = {
        "#buy": {"font_size": "18px", "font_weight": "700", "background_color": "#2563eb"},
        "#terms": {"font_size": "12px", "font_weight": "400", "background_color": "transparent"},
    }
    cand = make_candidate("bad_visual_hierarchy", "Controls differ in weight", selector="#card")
    m = assess(cand, card, make_dom([card, primary, secondary], styles), [], {})
    assert m.verdict == "NOT_A_DEFECT"
    assert "expected visual hierarchy" in m.reason.lower()


# =============================================================================
# 3. Harmonized Verification Status & Conclusion Strength
# =============================================================================

def test_heuristic_visual_measurement_becomes_likely_not_confirmed():
    """A heuristic visual finding without objective browser blockage must be LIKELY (Potential problem), NOT CONFIRMED."""
    cand = make_candidate("competing_cta", "Two buttons compete equally", selector="#actions")
    actions = make_element("#actions", "div", "", ids=["actions"])
    b1 = make_element("#b1", "button", "Option A", w=120, hgt=40, ids=["b1", "actions"])
    b2 = make_element("#b2", "button", "Option B", w=120, hgt=40, ids=["b2", "actions"])
    styles = {
        "#b1": {"font_size": "14px", "font_weight": "600", "background_color": "#2563eb"},
        "#b2": {"font_size": "14px", "font_weight": "600", "background_color": "#2563eb"},
    }
    status, score, reason = verify_candidate(cand, actions, make_dom([actions, b1, b2], styles))
    assert status == VerificationStatus.LIKELY
    assert score <= 0.80


def test_destructive_dominating_primary_remains_confirmed():
    """A destructive action that is measurably larger than the primary action is an objective defect."""
    sec = make_element("#row", "div", "", ids=["row"])
    del_btn = make_element("#delete", "button", "Delete Account", w=300, hgt=60, ids=["delete", "row"])
    save_btn = make_element("#save", "button", "Save Profile", w=80, hgt=24, ids=["save", "row"])
    styles = {
        "#delete": {"font_size": "20px", "font_weight": "700", "background_color": "#dc2626"},
        "#save": {"font_size": "12px", "font_weight": "400", "background_color": "transparent"},
    }
    cand = make_candidate("bad_visual_hierarchy", "Delete dominates Save", selector="#row")
    status, score, reason = verify_candidate(cand, sec, make_dom([sec, del_btn, save_btn], styles))
    assert status == VerificationStatus.CONFIRMED
    assert "destructive action is visually stronger" in reason


# =============================================================================
# 4. Zero Technical Jargon in Human View
# =============================================================================

def test_zero_jargon_across_all_human_dictionaries():
    """Verify that AXE, AI, and RUNTIME human interpretation tables have zero forbidden jargon."""
    for rule, (title, summary, why, fix) in AXE_INTERPRETATIONS.items():
        all_text = f"{title} {summary} {why} {fix}".lower()
        for word in FORBIDDEN_JARGON:
            assert word not in all_text, f"Forbidden jargon '{word}' in AXE rule '{rule}': {all_text}"

    for rule, (title, summary, why, fix) in AI_INTERPRETATIONS.items():
        all_text = f"{title} {summary} {why} {fix}".lower()
        for word in FORBIDDEN_JARGON:
            assert word not in all_text, f"Forbidden jargon '{word}' in AI rule '{rule}': {all_text}"

    for rule, (title, summary, why, fix) in RUNTIME_INTERPRETATIONS.items():
        all_text = f"{title} {summary} {why} {fix}".lower()
        for word in FORBIDDEN_JARGON:
            assert word not in all_text, f"Forbidden jargon '{word}' in RUNTIME rule '{rule}': {all_text}"


def test_zero_jargon_in_interpreted_output():
    """Verify interpreted finding dictionary contains zero forbidden words in human view."""
    sample_finding = {
        "id": "F-QUAL",
        "title": "WCAG [landmark-one-main]: Page missing main landmark",
        "description": "The page structure has no semantic main landmark container for assistive technology.",
        "category": "ACCESSIBILITY",
        "source": "axe-core",
        "rule": "landmark-one-main",
        "verification_status": "CONFIRMED",
        "affected_element": {"selector": "#content-wrap"},
        "evidence": {"sources": ["axe-core", "dom"], "flags": {"dom": True, "accessibility": True}}
    }
    out = interpret_finding(sample_finding)
    h = out["human"]
    why_aura = h["why_aura_reported_this"]
    human_text = " ".join([
        h.get("title", ""),
        h.get("summary", ""),
        h.get("why_it_matters", ""),
        h.get("what_to_do", ""),
        h.get("location", ""),
        why_aura.get("observation", ""),
        why_aura.get("conclusion", {}).get("known_fact", ""),
        why_aura.get("conclusion", {}).get("inferred_judgement", ""),
    ]).lower()

    for word in FORBIDDEN_JARGON:
        assert word not in human_text, f"Forbidden word '{word}' found in human view: {human_text}"


# =============================================================================
# 5. No Repetitive Generic Template Phrases
# =============================================================================

def test_repetitive_sentences_eradicated():
    """Ensure forbidden repetitive stock phrases never appear in aggregation or interpretations."""
    forbidden_phrases = [
        "impacts overall visual hierarchy and user interaction flow",
        "visual weight signals importance",
        "features people cannot find might as well not exist",
    ]
    # Check aggregation result
    c = make_candidate("weak_primary_cta", "Primary button blends in", "")
    from aura.models.findings import VerifiedFinding, VerificationResult
    ver = VerificationResult(issue_id="AI-001", status=VerificationStatus.LIKELY, confidence=0.75, evidence_sources=["dom", "screenshot"])
    v = VerifiedFinding(candidate=c, verification=ver)
    res = FindingsAggregator.aggregate(verified_ai_findings=[v], rejected_ai_findings=[], accessibility_violations=[], telemetry=None)
    for f in res.findings:
        text = f"{f.why_it_matters} {f.description}".lower()
        for phrase in forbidden_phrases:
            assert phrase not in text, f"Found forbidden phrase '{phrase}' in finding: {text}"


# =============================================================================
# 6. Honest Preview Capabilities
# =============================================================================

def test_preview_is_removed_from_the_engine():
    """Preview Fix is permanently removed: no module may still expose it."""
    import aura.interpretation.interpreter as interp_mod
    import aura.api.views as views_mod

    assert not hasattr(interp_mod, "evaluate_preview_capability")
    assert "preview" not in interp_mod.__dict__
    sample = {
        "id": "F-PRV", "title": "Elements must have sufficient color contrast",
        "description": "Contrast is too low.", "category": "ACCESSIBILITY", "source": "axe-core",
        "rule": "color-contrast", "verification_status": "CONFIRMED",
        "affected_element": {"selector": ".btn"},
        "evidence": {"sources": ["axe-core"], "flags": {"dom": True, "accessibility": True}},
    }
    out = interp_mod.interpret_finding(sample)
    assert "preview_capability" not in out
    view = views_mod.finding_view(sample)
    assert not any("preview" in k.lower() for k in view.keys())


# =============================================================================
# 7. Finding-Specific Evidence Checklist
# =============================================================================

def test_evidence_summary_checklist_and_sources():
    rep = {"state": "OBSERVED", "action_attempted": "Checked computed styles", "details": "Observed in DOM"}
    conc = {"strength": "Confirmed problem", "known_fact": "Contrast is low", "inferred_judgement": "Hard to read"}
    summary = generate_evidence_summary(
        observation="Text contrast is too low to read comfortably.",
        evidence_types=["STRUCTURAL", "ACCESSIBILITY"],
        evidence_sources=["axe-core"],
        reproduction=rep,
        conclusion=conc,
        verification_status="CONFIRMED",
        verification_score=0.95
    )
    assert "evaluated_sources" in summary
    assert "Page structure" in summary["evaluated_sources"]
    assert "Accessibility information" in summary["evaluated_sources"]
    assert "Visual screenshot" not in summary["evaluated_sources"]
    assert "Runtime telemetry" not in summary["evaluated_sources"]
