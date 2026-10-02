"""
Final engineering rectification: trust, finding quality, Ask AURA, highlight, human language,
deterministic curation and Preview removal.

The lettered sections match the required test cases:

  A. Side panel startup (no duplicate declarations, no duplicate element ids)
  B. Screenshot contradiction rejection
  C. Whitespace-only rejection
  D. Visual-difference-only rejection
  E. Target mismatch rejection
  F. Grouped target resolution
  G. Stale target detection
  H. Exact selector highlight
  I. Fallback text/role highlight
  J. Ambiguous highlight rejection
  K. Page changed highlight rejection
  L. Context-specific highlight errors
  M. Rule-specific human explanation
  N. Generic fallback rejection
  O. No duplicated human fields
  P. Finding-specific evidence checklist
  Q. Conclusion consistency
  R. Ask AURA finding isolation
  S. Ask AURA question isolation
  T. Ask AURA cache isolation
  U. Audit id / page identity
  V. Preview completely removed

H-L are behavioural checks of the in-page resolver. The structure and the honest, distinct failure
messages are asserted here; the resolver is exercised against a real DOM in a real Chrome by
tests/extension_highlight_e2e.py.
"""
import json
import re
from pathlib import Path

import pytest

from aura.api import views
from aura.api.store import AuditStore
from aura.api.views import build_audit_view, finding_view
from aura.assistant import chat
from aura.assistant.chat import (
    ask, build_chat_context, build_finding_context, cache_clear, cache_key, classify_question,
    NOT_IN_THIS_FINDING,
)
from aura.findings.aggregation import FindingsAggregator
from aura.interpretation import interpret_finding, group_findings_for_presentation
from aura.interpretation.interpreter import (
    BANNED_GENERIC_PHRASES, DETERMINISTIC_RULE_POLICY, canonical_conclusion, contains_banned_generic,
    finding_evidence_checklist, rule_policy,
)
from aura.models.findings import (
    AccessibilityViolation, CandidateFinding, FindingEvidenceDetail, RuntimeTelemetry, VerificationStatus,
)
from aura.verification.materiality import assess
from aura.verification.rules import VerificationRulesEngine
from aura.verification.verifier import FindingVerifier

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"
PANEL_JS = (EXT / "sidepanel" / "panel.js").read_text(encoding="utf-8")
PAGE_AGENT_JS = (EXT / "content" / "page_agent.js").read_text(encoding="utf-8")
PANEL_HTML = (EXT / "sidepanel" / "index.html").read_text(encoding="utf-8")

RULES = VerificationRulesEngine()


# ---------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------
def make_candidate(rule, title, description="", category="UI", confidence=0.9, selector="#target", text=""):
    return CandidateFinding(
        id="AI-001", candidate_id="AI-001", category=category, title=title, description=description,
        observation=description, severity="medium", confidence=confidence,
        affected_element={"selector": selector, "tag": "button", "text": text},
        evidence=FindingEvidenceDetail(type="visual", description="screenshot analysis"),
        rule_type=rule, normalized_rule=rule,
    )


def element(selector="#target", tag="button", text="Click", x=0, y=0, w=120, h=40, visible=True, ids=None, **extra):
    clean = selector.lstrip("#").split(".")[0]
    el = {"selector": selector, "tag": tag, "text": text, "visible": visible,
          "bounding_box": {"x": x, "y": y, "width": w, "height": h},
          "id": clean, "id_chain": ids if ids is not None else [clean]}
    el.update(extra)
    return el


def dom(elements, styles=None):
    styles = styles or {}
    return {"all_elements": elements,
            "raw_elements_with_styles": [{"selector": e["selector"], "computed_style": styles.get(e["selector"], {})}
                                         for e in elements]}


def verify(candidate, dom_summary, violations=None, telemetry=None):
    verifier = FindingVerifier()
    return verifier.verify_findings(
        candidate_findings=[candidate], dom_summary=dom_summary,
        accessibility_violations=violations or [],
        telemetry=telemetry or RuntimeTelemetry(url="https://example.com"))


def axe_finding(rule, description, targets, severity="serious"):
    return AccessibilityViolation(rule=rule, impact=severity, description=description, target=targets)


# ===================================================================================================
# A. Side panel startup
# ===================================================================================================
def test_A_panel_has_no_duplicate_top_level_declarations():
    """A duplicate const at module scope stops the whole side panel from starting."""
    names = re.findall(r"^(?:const|let)\s+([A-Za-z_$][\w$]*)", PANEL_JS, re.M)
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"duplicate top-level declarations in panel.js: {duplicates}"


def test_A_panel_html_ids_are_unique_and_every_referenced_id_exists():
    ids = re.findall(r'\bid="([^"]+)"', PANEL_HTML)
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate element ids in index.html: {duplicates}"

    referenced = set(re.findall(r'\$\("([a-z0-9\-]+)"\)', PANEL_JS))
    missing = referenced - set(ids)
    assert not missing, f"panel.js reads ids that index.html does not define: {missing}"


# ===================================================================================================
# B. Screenshot contradiction rejection
# ===================================================================================================
CONTRADICTION_REASON = "Visual evidence contradicts the AI observation."


def test_B_amazon_add_to_cart_claim_is_rejected_when_the_screenshot_shows_it():
    """The Amazon regression: 'purchase actions are not visible' with Add to Cart rendered on screen."""
    cart = element("#add-to-cart-button", "input", "Add to Cart", y=600, w=220, h=44)
    buy = element("#buy-now-button", "input", "Buy Now", y=660, w=220, h=44)
    cand = make_candidate("discoverability_problem",
                          "Primary purchase actions (add to cart) are not visible",
                          "The add to cart and buy now actions cannot be seen on the page.",
                          category="UX", selector="#centerCol")
    active, rejected = verify(cand, dom([cart, buy]))
    assert not active and len(rejected) == 1
    assert rejected[0].verification.rejection_reason == CONTRADICTION_REASON


@pytest.mark.parametrize("title,description", [
    ("Submit button is not visible", "The submit button cannot be seen in the rendered page."),
    ("The main navigation is missing", "Navigation is absent from the page."),
    ("Search is not present on this page", "No search control is rendered."),
])
def test_B_visual_state_claims_are_rejected_when_the_element_is_rendered(title, description):
    el = element("#submit", "button", "Submit", y=200)
    nav = element("#nav", "nav", "navigation Home Products search", y=0, w=900, h=60)
    cand = make_candidate("discoverability_problem", title, description, category="UX", selector="#submit")
    active, rejected = verify(cand, dom([el, nav]))
    assert not active, f"{title} should have been rejected"
    assert rejected[0].verification.rejection_reason == CONTRADICTION_REASON


def test_B_clipping_claim_is_rejected_when_geometry_shows_the_element_whole():
    el = element("#panel", "div", "Full content", w=400, h=300,
                 clipped=False, overflows_viewport=False, contains_overflow=False)
    cand = make_candidate("clipped_content", "Content is clipped by its container",
                          "The panel content is cut off.", category="RESPONSIVENESS", selector="#panel")
    active, rejected = verify(cand, dom([el]))
    assert not active
    assert rejected[0].verification.rejection_reason == CONTRADICTION_REASON


def test_B_attribute_claims_are_not_mistaken_for_visual_absence():
    """'missing alternative text' is about a property, not about the element being absent."""
    img = element("#hero-img", "img", "", w=400, h=300, alt=None)
    cand = make_candidate("image_alt", "Image element is missing alternative text",
                          "The primary image does not specify an alt attribute.",
                          category="ACCESSIBILITY", selector="#hero-img")
    active, rejected = verify(cand, dom([img]),
                              violations=[axe_finding("image-alt", "Images must have alternate text", ["#hero-img"])])
    assert len(active) == 1 and not rejected
    assert active[0].verification.status == VerificationStatus.CONFIRMED


def test_B_visual_qualifier_is_not_treated_as_an_absence_claim():
    """'visually hidden behind' is an overlap/emphasis claim; a screenshot cannot refute it on its own."""
    save = element("#save", "button", "Save", y=300)
    delete = element("#delete", "button", "Delete", y=300, x=200)
    cand = make_candidate("bad_visual_hierarchy", "Primary save action is visually hidden behind the delete button",
                          category="UI", selector="#save")
    active, rejected = verify(cand, dom([save, delete]))
    assert not rejected, "an emphasis claim must not be rejected as a screenshot contradiction"


# ===================================================================================================
# C. Whitespace-only rejection
# ===================================================================================================
@pytest.mark.parametrize("claim", [
    "There is a large blank hero area at the top",
    "The sidebar is empty",
    "Large gap between the content sections",
    "The layout has excessive whitespace",
    "This is intentional breathing room that wastes space",
    "The hero contains no content",
    "Unused pixels across the right column",
])
def test_C_whitespace_only_claims_are_rejected(claim):
    target = element("#hero", "div", "")
    cand = make_candidate("poor_spacing_consistency", claim, claim, selector="#hero")
    status, _, reason = RULES.evaluate_status_and_confidence(
        cand, {"screenshot": True, "dom": True}, [target], None, dom_summary=dom([target]))
    assert status == VerificationStatus.REJECTED
    assert "WHITESPACE_ONLY" in reason


@pytest.mark.parametrize("flag", ["layout_overlap", "target_overflow", "target_clipped", "interaction_error"])
def test_C_whitespace_claim_with_measured_harm_survives(flag):
    target = element("#hero", "div", "")
    cand = make_candidate("overlapping_elements", "Empty overlay area covers the buttons",
                          "A blank overlay sits on top of the actions", selector="#hero")
    status, _, _ = RULES.evaluate_status_and_confidence(
        cand, {"screenshot": True, "dom": True, flag: True}, [target], None, dom_summary=dom([target]))
    assert status != VerificationStatus.REJECTED


@pytest.mark.parametrize("claim", [
    # A placeholder destination is a broken link, not whitespace. Matching the bare word "void" inside
    # "javascript:void(0)" used to reject these real defects as empty space.
    "Anchor link points to javascript:void(0). Anchor elements have empty href destinations.",
    "Link element uses a placeholder href value without an active destination route.",
    "Misleading navigation link: 'Download Full Invoice PDF' uses javascript:void(0) and downloads nothing.",
    "Header navigation links overlap with negative margins.",
])
def test_C_the_whitespace_rule_does_not_swallow_real_defects(claim):
    from aura.verification.materiality import BLANK_CLAIM
    match = BLANK_CLAIM.search(claim)
    assert match is None, f"whitespace rule wrongly matched {match.group(0)!r} in: {claim}"


def test_C_content_outside_the_viewport_is_still_reported():
    """The counter-example: real layout breaks must not be swept up by the whitespace rule."""
    wide = element("#table", "div", "Report", w=2400, h=400, overflows_viewport=True)
    cand = make_candidate("horizontal_overflow", "The table extends past the right edge of the screen",
                          category="RESPONSIVENESS", selector="#table")
    active, rejected = verify(cand, dom([wide]))
    assert len(active) == 1 and not rejected
    assert active[0].verification.status == VerificationStatus.CONFIRMED


# ===================================================================================================
# D. Visual-difference-only rejection
# ===================================================================================================
@pytest.mark.parametrize("claim", [
    "Header navigation items have inconsistent visual treatment",
    "The cards show variation in style across the row",
    "There is a discrepancy in size between the buttons",
    "The layout looks unusual compared with similar sites",
])
def test_D_visual_difference_alone_is_not_a_defect(claim):
    target = element("#nav-list", "ul", "")
    cand = make_candidate("inconsistent_component_styling", claim, claim, selector="#nav-list")
    m = assess(cand, target, dom([target]), [], {})
    assert m.verdict == "NOT_A_DEFECT"
    assert "not a defect" in m.reason.lower()


def test_D_visual_difference_with_measured_harm_is_kept():
    target = element("#nav-list", "ul", "")
    cand = make_candidate("inconsistent_component_styling",
                          "Inconsistent styling causes the labels to overlap each other",
                          "The differing sizes make the links overlap", selector="#nav-list")
    m = assess(cand, target, dom([target]), [], {"layout_overlap": True})
    assert m.verdict != "NOT_A_DEFECT"


# ===================================================================================================
# E. Target mismatch rejection
# ===================================================================================================
def test_E_control_claim_matched_to_a_page_container_is_not_confirmed():
    """The Spotify regression: a navigation claim must not confirm against #main."""
    main = element("#main", "main", "", w=1200, h=900, ids=["main"])
    cand = make_candidate("search_discoverability", "Search is hard to find in the header navigation",
                          "The search control in the top navigation is not obvious", category="UX", selector="#main")
    m = assess(cand, main, dom([main]), [], {})
    assert m.verdict == "WEAK"
    assert "page-level container" in m.reason.lower()


def test_E_area_target_is_reported_as_an_area_and_is_not_highlightable():
    view = finding_view({
        "id": "F-AREA", "title": "Header navigation items look inconsistent",
        "description": "The header items differ in treatment.", "category": "UI", "source": "AI",
        "rule": "inconsistent_component_styling", "verification_status": "UNCERTAIN",
        "affected_element": {"selector": "header", "tag": "header"},
        "target_identity": {"target_match_method": "area_level"},
        "evidence": {"sources": ["screenshot"], "flags": {"screenshot": True}},
    })
    assert view["target"]["kind"] == "area"
    assert view["target"]["highlightable"] is False
    assert view["target"]["area_label"] == "Header area"
    assert "could not isolate one specific element" in view["target"]["description"]


def test_E_a_real_element_target_stays_highlightable():
    view = finding_view({
        "id": "F-EL", "title": "Some buttons don't have clear names", "description": "No readable name.",
        "category": "ACCESSIBILITY", "source": "axe-core", "rule": "button-name",
        "verification_status": "CONFIRMED",
        "affected_element": {"selector": "#checkout-btn", "tag": "button", "text": "Checkout"},
        "evidence": {"sources": ["axe-core"], "flags": {"dom": True, "accessibility": True}},
    })
    assert view["target"]["kind"] == "element"
    assert view["target"]["highlightable"] is True
    assert view["target"]["selectors"] == ["#checkout-btn"]


# ===================================================================================================
# F. Grouped target resolution
# ===================================================================================================
def _axe_view(rule, description, selector, fid):
    return finding_view({
        "id": fid, "title": f"WCAG [{rule}]: {description}", "description": description,
        "category": "ACCESSIBILITY", "source": "axe-core", "rule": rule, "verification_status": "CONFIRMED",
        "affected_element": {"selector": selector, "tag": "div"},
        "evidence": {"sources": ["axe-core"], "types": ["ACCESSIBILITY", "DOM"],
                     "flags": {"dom": True, "accessibility": True}},
    })


def test_F_related_aria_rules_are_grouped_by_user_meaning():
    items = [
        _axe_view("aria-required-children", "Ensures elements with an aria role that require child roles contain them", "#tabs", "F-1"),
        _axe_view("aria-allowed-attr", "Ensures an element's role supports its ARIA attributes", "#tab-1", "F-2"),
        _axe_view("aria-valid-attr-value", "Ensures all ARIA attributes have valid values", "#tab-2", "F-3"),
    ]
    grouped = group_findings_for_presentation(items)
    assert len(grouped) == 1
    card = grouped[0]
    assert card["title"] == "Some controls provide incorrect accessibility information"
    assert card["affected_count"] == 3
    assert "Screen readers may misunderstand these controls." == card["why_it_matters"]
    # Raw evidence survives underneath.
    assert sorted(card["technical"]["grouped_rules"]) == ["aria-allowed-attr", "aria-required-children", "aria-valid-attr-value"]
    assert card["technical"]["all_finding_ids"] == ["F-1", "F-2", "F-3"]
    assert card["technical"]["all_selectors"] == ["#tabs", "#tab-1", "#tab-2"]
    details = card["technical"]["grouped_details"]
    assert len(details) == 3
    assert {d["rule"] for d in details} == {"aria-required-children", "aria-allowed-attr", "aria-valid-attr-value"}
    assert all(d["raw_message"] for d in details), "the raw axe message of every merged violation is kept"
    # Every affected element stays individually addressable for per-element highlighting.
    assert [e["selector"] for e in card["affected_elements"]] == ["#tabs", "#tab-1", "#tab-2"]


def test_F_unrelated_accessibility_rules_are_not_grouped_together():
    items = [
        _axe_view("color-contrast", "Elements must have sufficient color contrast", "#p1", "F-1"),
        _axe_view("aria-allowed-attr", "Ensures an element's role supports its ARIA attributes", "#tab-1", "F-2"),
        _axe_view("heading-order", "Heading levels should only increase by one", "#h3", "F-3"),
    ]
    grouped = group_findings_for_presentation(items)
    assert len(grouped) == 3, "unrelated rules must stay separate findings"


def test_F_every_deterministic_rule_is_classified():
    for rule, policy in DETERMINISTIC_RULE_POLICY.items():
        assert policy == "KEEP" or policy.startswith("GROUP:") or policy == "TECHNICAL_ONLY", (rule, policy)
    assert rule_policy("region") == "GROUP:page-section-issues"
    assert rule_policy("color-contrast") == "KEEP"
    assert rule_policy("a-rule-aura-has-never-seen") == "KEEP"


# ===================================================================================================
# G. Stale target detection  /  U. audit id and page identity
# ===================================================================================================
def test_G_panel_checks_document_identity_before_highlighting():
    """The panel compares the tab's current document with the audited one before it highlights."""
    assert "async function doHighlight" in PANEL_JS
    highlight_fn = PANEL_JS[PANEL_JS.index("async function doHighlight"):PANEL_JS.index("async function clearPageMarks")]
    assert "pageIdentity(state.tabId)" in highlight_fn
    assert "now.pageKey !== rec.pageKey" in highlight_fn
    assert "now.documentId !== rec.documentId" in highlight_fn
    assert "Scan this page again before highlighting this finding." in highlight_fn
    assert "earlier version of this page" in highlight_fn


def test_U_audit_identity_is_keyed_on_tab_document_and_page():
    assert "const AUDITS_KEY" in PANEL_JS
    assert "documentId: rec.documentId" in PANEL_JS and "pageKey: rec.pageKey" in PANEL_JS
    # A navigation drops the audit; a reload keeps it but marks it stale.
    assert 'check = "navigated"' in PANEL_JS and 'check = "reloaded"' in PANEL_JS
    assert "forgetAudit(tab.id)" in PANEL_JS


def test_U_each_audit_keeps_its_own_findings_and_page_url():
    repo_id, issues_id = "AURA-2026-900001", "AURA-2026-900002"
    store = AuditStore()
    store.put({"audit_id": repo_id, "page_url": "https://github.com/acme/repo", "findings": [{"id": "F-1"}]})
    store.put({"audit_id": issues_id, "page_url": "https://github.com/acme/repo/issues", "findings": [{"id": "F-9"}]})
    assert store.get(repo_id)["page_url"] == "https://github.com/acme/repo"
    assert store.get(issues_id)["page_url"] == "https://github.com/acme/repo/issues"
    assert store.get(repo_id)["findings"][0]["id"] == "F-1"
    assert store.get(issues_id)["findings"][0]["id"] == "F-9"
    assert store.get("AURA-2026-999999") is None


# ===================================================================================================
# H-L. Highlight resolution and honest failure messages
# ===================================================================================================
def test_H_exact_selector_is_the_first_strategy():
    assert "EXACT_SELECTOR" in PAGE_AGENT_JS
    order = [PAGE_AGENT_JS.index(s) for s in
             ("EXACT_SELECTOR", "SELECTOR_PLUS_TEXT", "VISIBLE_TEXT_AND_ROLE", "ACCESSIBLE_NAME_AND_ROLE",
              "STABLE_ATTRIBUTE", "SEMANTIC_TAG_AND_TEXT")]
    assert order == sorted(order), "resolution strategies must be tried most-confident first"


def test_I_fallback_strategies_exist_for_text_role_and_stable_attributes():
    for strategy in ("VISIBLE_TEXT_AND_ROLE", "ACCESSIBLE_NAME_AND_ROLE", "STABLE_ATTRIBUTE", "SEMANTIC_TAG_AND_TEXT"):
        assert f'strategy: "{strategy}"' in PAGE_AGENT_JS or f'"{strategy}"' in PAGE_AGENT_JS
    assert "accessibleNameOf" in PAGE_AGENT_JS and "roleOf" in PAGE_AGENT_JS


def test_J_ambiguous_matches_are_never_highlighted():
    assert "function uniqueBy" in PAGE_AGENT_JS
    assert "if (hits.length === 1) return hits[0]" in PAGE_AGENT_JS or "hits.length === 1" in PAGE_AGENT_JS
    assert "Several elements match this finding, so AURA did not highlight one automatically." in PAGE_AGENT_JS


def test_K_page_change_is_detected_before_anything_is_highlighted():
    assert "status: \"page_changed\"" in PAGE_AGENT_JS
    assert "Scan this page again before highlighting" in PAGE_AGENT_JS


def test_L_every_highlight_failure_has_its_own_message():
    messages = {
        "page_changed": "This finding belongs to a different page than the one open here.",
        "element_gone": "The element AURA identified is no longer on the page.",
        "ambiguous": "Several elements match this finding, so AURA did not highlight one automatically.",
        "invalid_selector": "The target AURA recorded cannot be looked up in this page any more.",
    }
    for status, message in messages.items():
        assert f'status: "{status}"' in PAGE_AGENT_JS, status
        assert message in PAGE_AGENT_JS, status
    assert len(set(messages.values())) == len(messages), "failure messages must differ from each other"
    # The old catch-all is gone.
    assert "not in content" not in PAGE_AGENT_JS.lower()
    assert "The target element is not on the page any more" not in PAGE_AGENT_JS


def test_L_panel_titles_each_highlight_failure_differently():
    titles = re.search(r"const HIGHLIGHT_FAILURE_TITLE = \{(.*?)\};", PANEL_JS, re.S)
    assert titles, "panel must map each highlight failure to its own title"
    values = re.findall(r'"([^"]+)"', titles.group(1))
    assert len(values) == len(set(values)), f"highlight failure titles repeat: {values}"
    assert len(values) >= 5


def test_L_area_findings_explain_instead_of_highlighting():
    assert "This finding applies to an area of the page rather than one specific element." in PANEL_JS


# ===================================================================================================
# M. Rule-specific human explanation
# ===================================================================================================
def _interpret(rule, title, description="", category="ACCESSIBILITY", source="axe-core", status="CONFIRMED"):
    flags = ({"dom": True, "screenshot": True} if source == "AI" else {"dom": True, "accessibility": True})
    return interpret_finding({
        "id": "F-M", "title": title, "description": description, "category": category, "source": source,
        "rule": rule, "verification_status": status, "affected_element": {"selector": "#el", "tag": "div"},
        "observation": description or title,
        "evidence": {"sources": [source], "flags": flags},
    })


def test_M_region_explanation_acknowledges_a_visually_divided_page():
    """The BookMyShow regression: never claim the page is not divided into sections."""
    out = _interpret("region", "Ensures all page content is contained by landmarks")
    text = f"{out['title']} {out['summary']}".lower()
    assert "not divided into sections" not in text
    assert "may look divided into sections" in out["summary"]
    assert "page section" in out["summary"]
    assert "jumping straight to that content" in out["why_it_matters"]


def test_M_heading_order_explanation_is_about_headings_only():
    out = _interpret("heading-order", "Heading levels should only increase by one")
    assert out["title"] == "Some headings jump over levels"
    assert "heading" in out["summary"].lower()
    for unrelated in ("aria", "zoom", "control", "landmark", "contrast"):
        assert unrelated not in f"{out['title']} {out['summary']} {out['why_it_matters']}".lower()


@pytest.mark.parametrize("rule,expected", [
    ("link-name", "link"),
    ("color-contrast", "read"),
    ("button-name", "button"),
    ("meta-viewport", "zoom"),
])
def test_M_each_rule_gets_its_own_wording(rule, expected):
    out = _interpret(rule, f"raw title for {rule}")
    assert expected in f"{out['title']} {out['summary']}".lower()


def test_M_different_rules_never_share_the_same_explanation():
    seen = {}
    for rule in ("region", "heading-order", "link-name", "button-name", "color-contrast", "image-alt",
                 "label", "meta-viewport", "html-has-lang", "document-title"):
        out = _interpret(rule, f"raw {rule}")
        signature = (out["title"], out["why_it_matters"])
        assert signature not in seen.values(), f"{rule} reuses the wording of {[k for k, v in seen.items() if v == signature]}"
        seen[rule] = signature


# ===================================================================================================
# N. Generic fallback rejection
# ===================================================================================================
def test_N_banned_generic_phrases_appear_in_no_interpretation():
    from aura.interpretation.interpreter import AI_INTERPRETATIONS, AXE_INTERPRETATIONS, RUNTIME_INTERPRETATIONS
    for table in (AXE_INTERPRETATIONS, AI_INTERPRETATIONS, RUNTIME_INTERPRETATIONS):
        for rule, entry in table.items():
            joined = " ".join(entry).lower()
            for phrase in BANNED_GENERIC_PHRASES:
                assert phrase not in joined, f"{rule} still uses the generic phrase '{phrase}'"


def test_N_unexplainable_finding_is_marked_generic_and_held_back():
    out = interpret_finding({
        "id": "F-N", "title": "Ensures the widget conforms", "description": "Ensures the widget conforms",
        "category": "ACCESSIBILITY", "source": "axe-core", "rule": "some-unknown-widget-rule",
        "verification_status": "CONFIRMED", "affected_element": {"selector": "#w"},
        "evidence": {"sources": ["axe-core"], "flags": {"dom": True, "accessibility": True}},
    })
    assert out["explanation_specificity"] == "GENERIC"
    for phrase in BANNED_GENERIC_PHRASES:
        assert phrase not in f"{out['summary']} {out['why_it_matters']}".lower()


def test_N_contains_banned_generic_detects_the_old_wording():
    assert contains_banned_generic("This condition may make it more difficult for some people to view or use the page.")
    assert contains_banned_generic("Impacts overall visual hierarchy and user interaction flow")
    assert not contains_banned_generic("The page prevents or limits zooming.")


def test_N_generic_findings_are_not_in_the_findings_list_but_keep_their_evidence(monkeypatch):
    findings = [
        _axe_view("color-contrast", "Elements must have sufficient color contrast", "#p1", "F-1"),
        {**_axe_view("some-unknown-widget-rule", "Ensures the widget conforms", "#w", "F-2"),
         "explanation_specificity": "GENERIC"},
    ]

    class Agg:
        all_active_findings = []
        rejected_findings = []
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        summary_text = ""

    monkeypatch.setattr(views, "finding_view", lambda f: f)
    report = _fake_report(findings)
    view = build_audit_view(report)
    assert [f["id"] for f in view["findings"]] == ["F-1"]
    assert [f["id"] for f in view["technical_only_findings"]] == ["F-2"]
    assert view["technical_only_findings"][0]["technical"]["selector"] == "#w"


def _fake_report(finding_views):
    class Scores:
        def model_dump(self):
            return {"overall": 80, "ui": 80, "ux": 80, "accessibility": 80, "runtime": 100}

    class Telemetry:
        title = "Example"

    class Report:
        url = "https://example.com"
        timestamp = "2026-09-30T00:00:00"
        viewport = {"width": 1440, "height": 900}
        scores = Scores()
        runtime_telemetry = Telemetry()
        execution_steps = []

    class Agg:
        all_active_findings = list(finding_views)
        rejected_findings = []
        severity_counts = {"critical": 0, "high": 0, "medium": 1, "low": 0, "info": 0}
        summary_text = "summary"

    return {"report_model": Report(), "aggregation": Agg(), "ai_diagnostics": None, "preflight": None,
            "collection": {"title": "Example", "axe_available": True}, "audit_id": "A-1",
            "duration_seconds": 1.0, "evidence_coverage": {}, "provider_selection": {}}


# ===================================================================================================
# O. No duplicated human fields
# ===================================================================================================
DISTINCT_FIELDS = ("title", "summary", "why_it_matters", "what_to_do", "what_does_this_mean")


@pytest.mark.parametrize("rule", ["region", "heading-order", "link-name", "color-contrast", "image-alt",
                                  "button-name", "label", "meta-viewport", "weak_primary_cta",
                                  "bad_visual_hierarchy", "application_console_error", "ambiguous_label"])
@pytest.mark.parametrize("source", ["axe-core", "AI"])
def test_O_no_two_sentences_on_a_card_are_identical(rule, source):
    """
    Everything a person reads on one finding card, compared against everything else on that card.

    This is the "same wording repeated" complaint: What is wrong, Why it matters, What to do, What does
    this mean, What AURA observed, Known fact and Inferred impact were landing on the same sentence.
    """
    out = _interpret(rule, f"raw title for {rule}", description=f"raw description for {rule}", source=source)
    human = out["human"]
    conclusion = out["conclusion"]
    on_screen = {
        "title": human["title"],
        "what_is_wrong": human["summary"],
        "why_it_matters": human["why_it_matters"],
        "what_to_do": human["what_to_do"],
        "what_does_this_mean": human["what_does_this_mean"],
        "what_aura_observed": human["why_aura_reported_this"]["observation"],
        "known_fact": conclusion["known_fact"],
        "inferred_impact": conclusion["inferred_judgement"],
    }
    seen = {}
    for field, value in on_screen.items():
        text = (value or "").strip().lower().rstrip(".")
        if not text:
            continue  # a field AURA deliberately leaves out rather than fill with a repeat
        assert text not in seen, f"{rule}/{source}: '{field}' repeats '{seen[text]}' word for word: {value!r}"
        seen[text] = field


def test_O_why_aura_reported_is_not_a_copy_of_why_it_matters():
    out = _interpret("color-contrast", "Elements must have sufficient color contrast")
    why_reported = out["human"]["why_aura_reported_this"]
    assert why_reported["observation"] != out["human"]["why_it_matters"]
    assert why_reported["conclusion"]["known_fact"] != why_reported["conclusion"]["inferred_judgement"]


# ===================================================================================================
# P. Finding-specific evidence checklist
# ===================================================================================================
def test_P_checklist_lists_only_the_evidence_this_finding_rests_on():
    checklist = finding_evidence_checklist(["VISUAL", "STRUCTURAL"])
    present = {c["name"] for c in checklist if c["present"]}
    assert present == {"Visual screenshot", "Page structure"}
    assert {c["name"] for c in checklist} >= {"Runtime telemetry", "Interactive behaviour", "Layout geometry"}


def test_P_an_axe_finding_does_not_claim_visual_evidence():
    out = _interpret("color-contrast", "Elements must have sufficient color contrast")
    assert "VISUAL" not in out["evidence"]["types"]
    assert out["evidence"]["has_visual_evidence"] is False
    present = [c["name"] for c in out["human"]["why_aura_reported_this"]["checklist"] if c["present"]]
    assert "Visual screenshot" not in present
    assert "Page structure" in present and "Accessibility information" in present


def test_P_axe_findings_are_built_without_a_screenshot_flag():
    findings = FindingsAggregator.convert_accessibility_violations(
        [axe_finding("color-contrast", "Elements must have sufficient color contrast", ["#p"])])
    assert findings[0].evidence.flags["screenshot"] is False


def test_P_the_view_exposes_exactly_one_evidence_object():
    source = (ROOT / "aura" / "api" / "views.py").read_text(encoding="utf-8")
    body = source[source.index("def finding_view("):source.index("def build_audit_view(")]
    assert body.count('"evidence":') == 1, "finding_view must not define the evidence key twice"

    view = finding_view({
        "id": "F-P", "title": "Elements must have sufficient color contrast", "description": "low contrast",
        "category": "ACCESSIBILITY", "source": "axe-core", "rule": "color-contrast",
        "verification_status": "CONFIRMED", "affected_element": {"selector": "#p", "tag": "p"},
        "evidence": {"sources": ["axe-core"], "types": ["ACCESSIBILITY", "DOM"],
                     "flags": {"dom": True, "accessibility": True, "screenshot": False}},
    })
    assert view["evidence"]["has_visual_evidence"] is False
    assert "RUNTIME" not in view["evidence"]["types"]


# ===================================================================================================
# Q. Conclusion consistency
# ===================================================================================================
@pytest.mark.parametrize("status,source,expected", [
    ("CONFIRMED", "axe-core", "Confirmed problem"),
    ("LIKELY", "axe-core", "Potential problem"),
    ("UNCERTAIN", "axe-core", "Needs review"),
    ("CONFIRMED", "AI", "Confirmed problem"),
    ("LIKELY", "AI", "Potential problem"),
    ("UNCERTAIN", "AI", "Advisory"),
])
def test_Q_every_surface_shows_the_same_conclusion(status, source, expected):
    out = interpret_finding({
        "id": "F-Q", "title": "Elements must have sufficient color contrast", "description": "low contrast",
        "category": "ACCESSIBILITY" if source == "axe-core" else "UI", "source": source,
        "rule": "color-contrast" if source == "axe-core" else "weak_primary_cta",
        "verification_status": status, "confidence": 0.8,
        "affected_element": {"selector": "#p", "tag": "p"},
        "evidence": {"sources": [source], "flags": {"dom": True}},
    })
    assert out["status"] == expected
    assert out["human"]["status_label"] == expected
    assert out["human"]["conclusion_strength"] == expected
    assert out["conclusion"]["strength"] == expected
    assert out["human"]["why_aura_reported_this"]["conclusion"]["strength"] == expected
    assert out["technical"]["conclusion_strength"] == expected
    assert canonical_conclusion(status, is_ai_hypothesis=(source == "AI")) == expected


def test_Q_conclusion_is_one_of_the_four_allowed_values():
    for status in ("CONFIRMED", "LIKELY", "UNCERTAIN"):
        for is_ai in (True, False):
            assert canonical_conclusion(status, is_ai) in (
                "Confirmed problem", "Potential problem", "Needs review", "Advisory")


# ===================================================================================================
# R / S / T. Ask AURA
# ===================================================================================================
class RecordingProvider:
    """A provider that records the prompt it was given and returns a fixed answer."""
    provider_key = "groq"
    model = "test-model"
    last_execution_metadata = {}

    def __init__(self):
        self.prompts = []

    def analyze(self, prompt: str):
        self.prompts.append(prompt)
        return json.dumps({"answer": "Here is the answer.", "cited_finding_ids": ["F-008", "F-002"],
                           "evidence_gaps": []})


@pytest.fixture(autouse=True)
def _clear_ask_cache():
    cache_clear()
    yield
    cache_clear()


@pytest.fixture
def ready_preflight(monkeypatch):
    class PF:
        blocked = False
        status = "READY"
    monkeypatch.setattr(chat, "run_preflight", lambda *a, **k: PF())


def _ask_view():
    def f(fid, rule, title, summary, why, fix, status="CONFIRMED"):
        return {
            "id": fid, "rule": rule, "title": title, "category": "ACCESSIBILITY", "severity": "medium",
            "verification_status": status, "verification_note": None, "origin": "DETERMINISTIC",
            "summary": summary, "why_it_matters": why, "recommendation": fix,
            "human": {"title": title, "summary": summary, "why_it_matters": why, "what_to_do": fix,
                      "location": f"the {rule} element", "status_label": "Confirmed problem",
                      "confidence_label": "High", "conclusion_strength": "Confirmed problem",
                      "why_aura_reported_this": {"observation": summary, "evaluated_sources": ["Page structure"]}},
            "evidence": {"types": ["STRUCTURAL", "ACCESSIBILITY"], "sources": ["axe-core"],
                         "has_visual_evidence": False, "flags": {"dom": True}},
            "reproduction": {"state": "OBSERVED", "action_attempted": "Checked the page structure."},
            "conclusion": {"strength": "Confirmed problem", "known_fact": f"Fact about {rule}.",
                           "inferred_judgement": f"Impact of {rule}."},
            "target": {"kind": "element", "description": f"the {rule} element", "text": rule},
        }

    return {
        "audit_id": "A-BMS",
        "page_url": "https://in.bookmyshow.com/explore/movies-pondicherry",
        "title": "Movies",
        "viewport": {"width": 1440, "height": 900},
        "findings": [
            f("F-002", "region", "Some content isn't assigned to a page section",
              "This page may look divided into sections on screen, but some content is not assigned to a page section.",
              "People who move through a page section by section cannot jump straight to that content.",
              "Assign the content to a clear page section."),
            f("F-005", "heading-order", "Some headings jump over levels",
              "The page moves between heading levels without following a consistent order.",
              "People who navigate by headings may find the page structure harder to follow.",
              "Arrange the headings so their levels follow the structure of the content."),
            f("F-008", "meta-viewport", "The page prevents zooming",
              "The page is set up to block or limit zooming.",
              "People who need larger text cannot enlarge the page to read it.",
              "Let people zoom the page as far as they need to."),
        ],
    }


def test_R_context_for_a_selected_finding_contains_only_that_finding():
    view = _ask_view()
    ctx = build_finding_context(view, view["findings"][0])
    serialized = json.dumps(ctx).lower()
    assert ctx["finding"]["id"] == "F-002"
    assert "f-005" not in serialized and "f-008" not in serialized
    assert "zoom" not in serialized, "the zoom finding must not be visible while answering about region"


def test_R_build_chat_context_narrows_to_the_selected_finding():
    view = _ask_view()
    ctx = build_chat_context(view, finding_id="F-005")
    assert ctx["scope"] == "SINGLE_FINDING"
    assert len(ctx["findings"]) == 1 and ctx["findings"][0]["id"] == "F-005"
    assert "rejected_ai_candidates" not in ctx


def test_R_the_bookmyshow_regression_never_answers_with_the_zoom_finding(ready_preflight):
    """Selected: region. Question: 'but its already divided into sections'. Answer must be about region."""
    view = _ask_view()
    provider = RecordingProvider()
    result = ask(provider, view, "but its already divided into sections", finding_id="F-002")
    assert result["state"] == "OK"
    assert result["scoped_finding_id"] == "F-002"
    # The model could not have mentioned zoom: it never saw that finding.
    prompt = provider.prompts[0].lower()
    assert "zoom" not in prompt
    assert "f-008" not in prompt and "f-005" not in prompt
    # The model offered F-008 and F-002; only the finding under discussion survives the filter.
    assert result["cited_finding_ids"] == ["F-002"]


def test_R_switching_findings_switches_the_context(ready_preflight):
    view = _ask_view()
    provider = RecordingProvider()
    ask(provider, view, "explain the reasoning behind this in detail please", finding_id="F-002")
    ask(provider, view, "explain the reasoning behind this in detail please", finding_id="F-005")
    # Inspect the finding payload only. The prompt's own instructions mention words like "heading",
    # so searching the whole prompt would test the wording of the instructions, not the isolation.
    def payload(prompt):
        return prompt.split("the only issue you may talk about:", 1)[1].split("USER QUESTION", 1)[0]
    first, second = (payload(x) for x in provider.prompts)
    assert "F-002" in first and "region" in first.lower()
    assert "heading" not in first.lower() and "zoom" not in first.lower()
    assert "F-005" in second and "heading" in second.lower()
    assert "F-002" not in second and "zoom" not in second.lower()


def test_R_a_finding_from_another_audit_is_not_used():
    view = _ask_view()
    provider = RecordingProvider()
    result = ask(provider, view, "how do i fix this", finding_id="F-999-from-another-audit")
    # Unknown finding: the question falls back to the audit scope and never borrows another finding.
    assert result["state"] in ("AI_UNAVAILABLE", "OK")
    assert result.get("scoped_finding_id") in (None, "")


@pytest.mark.parametrize("question,intent", [
    ("what is wrong here?", "WHAT_IS_WRONG"),
    ("why does this matter?", "WHY_MATTERS"),
    ("how to solve", "HOW_FIX"),
    ("how do i fix this", "HOW_FIX"),
    ("why did aura report this", "WHY_REPORTED"),
    ("is this confirmed?", "IS_CONFIRMED"),
    ("did you see this in the screenshot?", "SCREENSHOT"),
])
def test_S_each_standard_question_is_recognised(question, intent):
    assert classify_question(question) == intent


def test_S_different_questions_get_different_grounded_answers():
    view = _ask_view()
    provider = RecordingProvider()
    answers = {}
    for question in ("what is wrong?", "why does this matter?", "how to solve",
                     "why did aura report this", "is this confirmed?", "did you see this in the screenshot?"):
        result = ask(provider, view, question, finding_id="F-005")
        assert result["state"] == "OK", question
        assert result["answered_from"] == "RECORDED_EVIDENCE", question
        answers[question] = result["answer"]
    assert len(set(answers.values())) == len(answers), f"answers repeat: {answers}"
    assert not provider.prompts, "standard questions must cost no AI request"


def test_S_answers_come_from_the_selected_finding_not_a_neighbour():
    view = _ask_view()
    provider = RecordingProvider()
    region = ask(provider, view, "how to solve", finding_id="F-002")["answer"]
    heading = ask(provider, view, "how to solve", finding_id="F-005")["answer"]
    zoom = ask(provider, view, "how to solve", finding_id="F-008")["answer"]
    assert "page section" in region and "heading" not in region.lower()
    assert "headings" in heading and "zoom" not in heading.lower()
    assert "zoom" in zoom
    assert len({region, heading, zoom}) == 3


def test_S_a_question_the_finding_cannot_answer_says_so(ready_preflight):
    view = _ask_view()

    class Refusing(RecordingProvider):
        def analyze(self, prompt):
            self.prompts.append(prompt)
            return json.dumps({"answer": NOT_IN_THIS_FINDING, "cited_finding_ids": [], "evidence_gaps": ["load time"]})

    result = ask(Refusing(), view, "how fast does this page load on 3g", finding_id="F-002")
    assert result["answer"] == NOT_IN_THIS_FINDING
    assert result["evidence_gaps"] == ["load time"]


def test_T_cache_is_keyed_on_audit_finding_and_question():
    a = cache_key("A-1", "F-1", "How to solve?")
    b = cache_key("A-1", "F-2", "How to solve?")
    c = cache_key("A-2", "F-1", "How to solve?")
    d = cache_key("A-1", "F-1", "how to solve")
    assert len({a, b, c}) == 3, "the same question on another finding or audit must not share a cache entry"
    assert a == d, "the question is normalized"


def test_T_cached_answers_never_cross_findings():
    view = _ask_view()
    provider = RecordingProvider()
    first = ask(provider, view, "What is wrong?", finding_id="F-002")
    again = ask(provider, view, "what is wrong?", finding_id="F-002")
    other = ask(provider, view, "What is wrong?", finding_id="F-008")
    assert again.get("cached") is True and again["answer"] == first["answer"]
    assert other["answer"] != first["answer"]
    assert other.get("cached") is not True


def test_T_cache_is_isolated_across_audits():
    view_a = _ask_view()
    view_b = {**_ask_view(), "audit_id": "A-OTHER"}
    view_b["findings"] = [{**view_b["findings"][0],
                           "human": {**view_b["findings"][0]["human"],
                                     "summary": "A completely different observation on another page."}}]
    provider = RecordingProvider()
    a = ask(provider, view_a, "What is wrong?", finding_id="F-002")
    b = ask(provider, view_b, "What is wrong?", finding_id="F-002")
    assert a["answer"] != b["answer"]


# ===================================================================================================
# V. Preview completely removed
# ===================================================================================================
PREVIEW_TOKENS = ["doPreview", "doRevert", "agentPreview", "agentRevertPreview", "act-preview",
                  "previewed", "not_visual", "Revert preview", "Preview Fix", "preview_capability",
                  "evaluate_preview_capability"]


@pytest.mark.parametrize("token", PREVIEW_TOKENS)
def test_V_no_preview_token_survives_in_the_product(token):
    """The product itself carries no Preview code. (Tests may still name the tokens to prove they are gone.)"""
    hits = []
    for root in (ROOT / "aura", ROOT / "extension"):
        for path in root.rglob("*"):
            if path.suffix not in (".py", ".js", ".html", ".css") or "__pycache__" in path.parts:
                continue
            if token in path.read_text(encoding="utf-8", errors="ignore"):
                hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"'{token}' still present in: {hits}"


def test_V_no_test_still_calls_the_removed_preview_api():
    """No test may import or call the deleted preview API — only assert that it is gone."""
    offenders = []
    for path in (ROOT / "tests").glob("*.py"):
        if path.name == Path(__file__).name:
            continue  # this file names the removed API in order to check for it
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "not hasattr" in stripped or "assert" in stripped:
                continue
            if "evaluate_preview_capability(" in stripped or "import evaluate_preview_capability" in stripped:
                offenders.append(f"{path.name}: {stripped}")
    assert not offenders, offenders


def test_V_the_panel_offers_no_preview_action():
    actions = PANEL_HTML[PANEL_HTML.index('<div class="actions">'):PANEL_HTML.index("</div>", PANEL_HTML.index('<div class="actions">'))]
    buttons = re.findall(r'id="(act-[a-z]+)"', actions)
    assert buttons == ["act-highlight", "act-shot", "act-explain"]
    assert not any("preview" in b for b in buttons)


def test_V_no_preview_wiring_remains_in_the_panel():
    assert "preview" not in PANEL_JS.lower()
    assert "preview" not in PAGE_AGENT_JS.lower()
    assert "preview" not in PANEL_HTML.lower()
    css = (EXT / "sidepanel" / "panel.css").read_text(encoding="utf-8")
    assert "preview" not in css.lower()


# ===================================================================================================
# Explain depth, the screenshot control and the dismissable action panel
# ===================================================================================================
EXPLAIN_RULES = ["color-contrast", "heading-order", "page-has-heading-one", "region", "landmark-one-main",
                 "link-name", "button-name", "label", "image-alt", "aria-allowed-attr", "list",
                 "meta-viewport", "horizontal_overflow", "clipped_content", "html-has-lang",
                 "document-title", "scrollable-region-focusable"]


@pytest.mark.parametrize("rule", EXPLAIN_RULES)
def test_explain_gives_real_context_without_technical_wording(rule):
    """Explain carries the whole problem for a non-technical reader: what it is like, and what good looks like."""
    from aura.assistant.explain import explain_finding

    view = finding_view({
        "id": "F-EX", "title": f"WCAG [{rule}]: raw detector title", "description": f"raw description for {rule}",
        "observation": f"Deterministic axe-core scan detected '{rule}'", "category": "ACCESSIBILITY",
        "source": "axe-core", "rule": rule, "normalized_rule": rule.replace("-", "_"),
        "verification_status": "CONFIRMED", "affected_element": {"selector": "#el", "tag": "div"},
        "evidence": {"sources": ["axe-core"], "types": ["ACCESSIBILITY", "DOM"],
                     "flags": {"dom": True, "accessibility": True}},
    })
    out = explain_finding(view)
    headings = [s["heading"] for s in out["sections"]]
    assert headings[0] == "What is happening"
    assert "How sure AURA is" in headings
    assert {"What it is like to run into this", "What it looks like when it is right"} <= set(headings), (
        f"{rule} has no added context in Explain: {headings}")

    body = " ".join(str(s.get("body") or "") for s in out["sections"]) + out["title"]
    low = body.lower()
    for technical in ("wcag", "axe-core", "aria-", "aria ", "selector", "landmark", "semantic", "dom",
                      "css", "viewport", "tabindex", "assistive technolog"):
        assert technical not in low, f"{rule}: Explain leaked the technical term '{technical}'"
    # It must say materially more than the card's one sentence.
    assert len(body) > len(view["human"]["short_summary"]) * 3


def test_explain_is_longer_than_the_card_but_the_card_stays_short():
    from aura.assistant.explain import explain_finding
    view = finding_view({
        "id": "F-EX2", "title": "WCAG [color-contrast]: low contrast", "description": "contrast is low",
        "category": "ACCESSIBILITY", "source": "axe-core", "rule": "color-contrast",
        "verification_status": "CONFIRMED",
        "affected_element": {"selector": "#p", "tag": "span", "text": "Inclusive of all taxes"},
        "evidence": {"sources": ["axe-core"], "flags": {"dom": True, "accessibility": True}},
    })
    assert len(view["human"]["short_summary"]) <= 150
    assert view["human"]["short_summary"].count(".") <= 1
    full = " ".join(str(s.get("body") or "") for s in explain_finding(view)["sections"])
    assert len(full) > 300


def test_the_action_panel_can_be_dismissed_and_the_screenshot_can_be_zoomed():
    # A panel that cannot be closed covers the finding it belongs to.
    assert "function closeActOut" in PANEL_JS
    assert 'class: "act-close"' in PANEL_JS
    assert "out.classList.add(\"hidden\")" in PANEL_JS
    # Zoom: the crop is shown fit-to-width and clicking shows it at full size in a scrollable frame.
    assert 'img.classList.toggle("zoomed")' in PANEL_JS
    assert "Click to zoom" in PANEL_JS and "Click to fit" in PANEL_JS
    css = (EXT / "sidepanel" / "panel.css").read_text(encoding="utf-8")
    assert ".shot-frame.zoomed" in css and ".act-out .shot.zoomed" in css
    assert ".act-out .act-close" in css


def test_the_full_page_capture_is_only_for_the_panel():
    """The AI keeps receiving the single viewport capture, so provider request sizes do not change."""
    from aura.evidence.bundle import EvidenceBundle
    assert "screenshot_fullpage_png_base64" in EvidenceBundle.model_fields
    scanner = (EXT / "sidepanel" / "scanner.js").read_text(encoding="utf-8")
    assert "captureFullPage" in scanner and "pageHoldSticky" in scanner
    # Sticky bars are hidden for the lower slices and restored afterwards.
    assert "pageHoldSticky, args: [true]" in scanner and "pageHoldSticky, args: [false]" in scanner
    # The original scroll position is put back.
    assert "pageScrollTo, args: [metrics.scrollY]" in scanner
    orchestrator = (ROOT / "aura" / "agents" / "orchestrator.py").read_text(encoding="utf-8")
    assert "screenshot_fullpage_png_base64" in orchestrator
    # Only the viewport capture reaches the analysis pipeline.
    assert "screenshot_path=screenshot_path" in orchestrator
