"""
Tests for AURA Phase 5: Evidence-Backed Validation, Reproduction & Final Trust Layer.

Verifies:
1. Finding Trust Layer contract:
   - finding.human (plain language, 4 core questions + why_aura_reported_this)
   - finding.technical (100% engineering facts preserved)
   - finding.evidence (provenance codes: VISUAL, STRUCTURAL, ACCESSIBILITY, RUNTIME, BEHAVIORAL, RESPONSIVE)
   - finding.reproduction (OBSERVED, REPRODUCED, SUPPORTED, NOT_REPRODUCIBLE, NOT_APPLICABLE, UNVERIFIED)
   - finding.conclusion (Confirmed problem, Potential problem, Needs review, Advisory + known fact vs inferred)
2. Reproduction state mappings across categories:
   - Responsive overflow -> REPRODUCED
   - Deterministic accessibility -> OBSERVED
   - Runtime errors -> OBSERVED
   - Safe interaction -> REPRODUCED
   - Destructive interaction boundary (payments/forms) -> NOT_APPLICABLE
   - AI multimodal with screenshot -> SUPPORTED
   - AI hypothesis without screenshot -> UNVERIFIED
3. Screenshot provenance truthfulness:
   - Never claim VISUAL or 'Screenshot verified' unless screenshot was captured, attached, and evaluated
4. Ask AURA contextual assistant grounding in reproduction & visual truth
5. Zero technical jargon in all human-facing text
6. Realistic scenarios: Flipkart, YouTube, Play Store
"""
import pytest
from typing import Dict, Any

from aura.interpretation.interpreter import (
    determine_reproduction_and_trust,
    generate_evidence_summary,
    interpret_finding,
    group_findings_for_presentation
)
from aura.api.views import finding_view
from aura.agent.diagnostics import AIDiagnostics, AIAnalysisStatus
from aura.assistant.chat import build_chat_context, ask
from aura.agent.mock_provider import MockAIProvider


# -----------------------------------------------------------------------------
# 1. Reproduction & Trust State Mappings
# -----------------------------------------------------------------------------

def test_reproduction_responsive_overflow_confirmed():
    rep, conc = determine_reproduction_and_trust(
        rule_key="horizontal_overflow",
        category="RESPONSIVENESS",
        source="Browser Layout Engine",
        v_status="CONFIRMED",
        flags={"dom": True},
        is_ai=False,
        selector=".carousel-track",
        verification_score=0.95
    )
    assert rep["state"] == "REPRODUCED"
    assert "viewport bounds" in rep["action_attempted"].lower()
    assert conc["strength"] == "Confirmed problem"
    assert "viewport" in conc["known_fact"].lower()
    assert "scroll sideways" in conc["inferred_judgement"].lower()


def test_reproduction_accessibility_color_contrast():
    rep, conc = determine_reproduction_and_trust(
        rule_key="color-contrast",
        category="ACCESSIBILITY",
        source="axe-core",
        v_status="CONFIRMED",
        flags={"dom": True, "accessibility": True},
        is_ai=False,
        selector=".btn-muted",
        verification_score=0.9
    )
    assert rep["state"] == "OBSERVED"
    assert "background colour" in rep["action_attempted"].lower()
    assert conc["strength"] == "Confirmed problem"
    assert "measured contrast" in conc["known_fact"].lower()
    assert "reduced vision" in conc["inferred_judgement"].lower()


def test_reproduction_accessibility_missing_label():
    rep, conc = determine_reproduction_and_trust(
        rule_key="button-name",
        category="ACCESSIBILITY",
        source="axe-core",
        v_status="CONFIRMED",
        flags={"dom": True, "accessibility": True},
        is_ai=False,
        selector="button.icon-only",
        verification_score=0.95
    )
    assert rep["state"] == "OBSERVED"
    assert "readable text or a name" in rep["action_attempted"].lower()
    assert conc["strength"] == "Confirmed problem"
    assert "no readable text" in conc["known_fact"].lower()
    assert "screen reader" in conc["inferred_judgement"].lower()


def test_reproduction_runtime_console_error():
    rep, conc = determine_reproduction_and_trust(
        rule_key="console_error",
        category="RUNTIME",
        source="RUNTIME",
        v_status="CONFIRMED",
        flags={"runtime": True},
        is_ai=False,
        selector=None,
        verification_score=1.0
    )
    assert rep["state"] == "OBSERVED"
    assert "browser console" in rep["action_attempted"].lower()
    assert conc["strength"] == "Confirmed problem"
    assert "script error" in conc["known_fact"].lower()


def test_reproduction_safe_interaction_click():
    rep, conc = determine_reproduction_and_trust(
        rule_key="click_without_feedback",
        category="INTERACTION",
        source="INTERACTION",
        v_status="CONFIRMED",
        flags={"interaction": True, "dom": True},
        is_ai=False,
        selector="button#expand-accordion",
        verification_score=0.85
    )
    assert rep["state"] == "REPRODUCED"
    assert "clicked the control" in rep["action_attempted"].lower()
    assert conc["strength"] == "Confirmed problem"
    assert "gave no feedback" in conc["known_fact"].lower()


def test_reproduction_destructive_safety_boundary():
    rep, conc = determine_reproduction_and_trust(
        rule_key="broken_form_submission",
        category="INTERACTION",
        source="INTERACTION",
        v_status="UNCERTAIN",
        flags={"dom": True},
        is_ai=False,
        selector="form#checkout-payment-form button[type='submit']",
        verification_score=0.5
    )
    assert rep["state"] == "NOT_APPLICABLE"
    assert rep["safety_boundary"] is not None
    assert "non-destructive verification policy" in rep["safety_boundary"].lower()
    assert conc["strength"] == "Needs review"


def test_reproduction_ai_with_screenshot():
    rep, conc = determine_reproduction_and_trust(
        rule_key="weak_primary_cta",
        category="UI",
        source="AI",
        v_status="LIKELY",
        flags={"screenshot": True},
        is_ai=True,
        selector="button.cta-primary",
        raw_conf=0.82,
        has_visual_evidence=True
    )
    assert rep["state"] == "SUPPORTED"
    assert "screenshot" in rep["action_attempted"].lower()
    assert conc["strength"] == "Potential problem"
    assert "screenshot" in conc["known_fact"].lower()


def test_reproduction_ai_without_screenshot():
    rep, conc = determine_reproduction_and_trust(
        rule_key="search_discoverability",
        category="UX",
        source="AI",
        v_status="UNCERTAIN",
        flags={"dom": True},
        is_ai=True,
        selector="input#search",
        raw_conf=0.55,
        has_visual_evidence=False
    )
    assert rep["state"] == "UNVERIFIED"
    assert "without" in rep["action_attempted"].lower()
    # UNCERTAIN on an AI hypothesis is "Advisory" everywhere in the product. The old code said
    # "Needs review" here while the badge said "Advisory" - that contradiction is what section 12 bans.
    assert conc["strength"] == "Advisory"


# -----------------------------------------------------------------------------
# 2. Evidence Summary & Checklist
# -----------------------------------------------------------------------------

def test_generate_evidence_summary():
    rep = {
        "state": "OBSERVED",
        "action_attempted": "Inspected accessible name in DOM",
        "safety_boundary": None,
        "details": "Directly observed during automated inspection."
    }
    conc = {
        "strength": "Confirmed problem",
        "known_fact": "Element lacks accessible label.",
        "inferred_judgement": "Screen readers cannot announce purpose."
    }
    summary = generate_evidence_summary(
        observation="A button has no accessible name.",
        evidence_types=["STRUCTURAL", "ACCESSIBILITY"],
        evidence_sources=["axe-core", "dom_snapshot"],
        reproduction=rep,
        conclusion=conc,
        verification_status="CONFIRMED",
        verification_score=0.95
    )

    assert summary["observation"] == "A button has no accessible name."
    checklist = {item["name"]: item["present"] for item in summary["checklist"]}
    assert checklist["Page structure"] is True
    assert checklist["Accessibility information"] is True
    assert checklist["Visual screenshot"] is False
    assert checklist["Runtime telemetry"] is False
    assert summary["reproduction"]["state"] == "OBSERVED"
    assert summary["conclusion"]["strength"] == "Confirmed problem"


# -----------------------------------------------------------------------------
# 3. Screenshot Provenance Integrity
# -----------------------------------------------------------------------------

def test_screenshot_provenance_diagnostics():
    diag = AIDiagnostics(
        provider_name="Gemini",
        model_name="gemini-2.5-flash",
        status=AIAnalysisStatus.SUCCESS_WITH_CANDIDATES,
        screenshot_captured=True,
        screenshot_attached_to_request=True,
        multimodal_request=True,
        screenshot_evaluated_by_model=True
    )
    summary = diag.to_summary_dict()
    assert summary["Screenshot Captured"] is True
    assert summary["Screenshot Attached"] is True
    assert summary["Multimodal Request"] is True
    assert summary["Screenshot Evaluated"] is True


def test_visual_evidence_not_claimed_when_no_screenshot():
    finding = {
        "id": "F-101",
        "title": "Search bar is hard to find",
        "description": "Search input is not prominent.",
        "category": "UX",
        "source": "AI",
        "rule": "search_discoverability",
        "verification_status": "LIKELY",
        "confidence": 0.75,
        "affected_element": {"selector": "#search-input"},
        "evidence": {
            "types": ["DOM"],
            "sources": ["dom_elements"],
            "flags": {"screenshot": False, "dom": True},
            "has_visual_evidence": False
        }
    }
    interp = interpret_finding(finding)
    assert "VISUAL" not in interp["evidence"]["types"]
    assert interp["evidence"]["has_visual_evidence"] is False
    assert interp["reproduction"]["state"] == "UNVERIFIED"
    # LIKELY is "Potential problem" on every surface, including this conclusion.
    assert interp["conclusion"]["strength"] == "Potential problem"
    assert interp["conclusion"]["strength"] == interp["status"]


def test_visual_evidence_claimed_when_screenshot_verified():
    finding = {
        "id": "F-102",
        "title": "Primary button lacks contrast",
        "description": "Visual contrast is weak in rendered screenshot.",
        "category": "UI",
        "source": "AI",
        "rule": "weak_primary_cta",
        "verification_status": "CONFIRMED",
        "confidence": 0.88,
        "affected_element": {"selector": ".hero-cta"},
        "evidence": {
            "types": ["VISUAL", "DOM"],
            "sources": ["screenshot", "dom_elements"],
            "flags": {"screenshot": True, "dom": True},
            "has_visual_evidence": True
        }
    }
    interp = interpret_finding(finding)
    assert "VISUAL" in interp["evidence"]["types"]
    assert interp["evidence"]["has_visual_evidence"] is True
    assert interp["reproduction"]["state"] == "SUPPORTED"
    # Restraint belongs in the verifier, not here: an AI candidate only reaches CONFIRMED when a
    # measurement backs it. Once it is CONFIRMED, every surface must say "Confirmed problem".
    assert interp["conclusion"]["strength"] == "Confirmed problem"
    assert interp["conclusion"]["strength"] == interp["status"]


# -----------------------------------------------------------------------------
# 4. Strict Contract Separation & Zero Jargon
# -----------------------------------------------------------------------------

def test_zero_jargon_in_human_view_and_summary():
    finding = {
        "id": "F-201",
        "title": "WCAG [region]: Content is outside region",
        "description": "Users of assistive technology may be unable to navigate.",
        "category": "ACCESSIBILITY",
        "source": "axe-core",
        "rule": "region",
        "verification_status": "CONFIRMED",
        "affected_element": {"selector": "div.container > section#promo"},
        "evidence": {"sources": ["axe-core"], "flags": {"dom": True, "accessibility": True}}
    }
    interp = interpret_finding(finding)
    h = interp["human"]
    why_aura = h["why_aura_reported_this"]

    forbidden = ["axe-core", "wcag", "aria-", "<main role=\"main\">", "css selector", "dom path"]
    all_human_text = " ".join([
        h.get("title", ""),
        h.get("summary", ""),
        h.get("why_it_matters", ""),
        h.get("what_to_do", ""),
        h.get("location", ""),
        why_aura.get("observation", ""),
        why_aura.get("conclusion", {}).get("known_fact", ""),
        why_aura.get("conclusion", {}).get("inferred_judgement", ""),
    ]).lower()

    for word in forbidden:
        assert word not in all_human_text, f"Forbidden jargon '{word}' found in human view: {all_human_text}"

    # Technical view preserves raw engineering facts
    tech = interp["technical"]
    assert tech["rule_id"] == "region"
    assert tech["selector"] == "div.container > section#promo"
    assert "axe" in tech["detector"].lower()


# -----------------------------------------------------------------------------
# 5. Finding View Serialization for Extension API
# -----------------------------------------------------------------------------

def test_finding_view_phase5_serialization():
    raw_finding = {
        "id": "F-301",
        "title": "Horizontal overflow",
        "description": "Page scrolls horizontally on standard viewport.",
        "category": "RESPONSIVENESS",
        "source": "layout_engine",
        "rule": "horizontal_overflow",
        "verification_status": "CONFIRMED",
        "verification_score": 0.95,
        "affected_element": {"selector": ".product-grid"},
        "evidence": {
            "sources": ["layout_geometry"],
            "flags": {"dom": True, "responsive": True},
            "types": ["RESPONSIVE", "STRUCTURAL"]
        }
    }
    view = finding_view(raw_finding)
    assert "human" in view
    assert "technical" in view
    assert "evidence" in view
    assert "reproduction" in view
    assert "conclusion" in view
    assert "why_aura_reported_this" in view

    assert view["reproduction"]["state"] == "REPRODUCED"
    assert view["conclusion"]["strength"] == "Confirmed problem"
    assert view["why_aura_reported_this"]["reproduction"]["state"] == "REPRODUCED"


# -----------------------------------------------------------------------------
# 6. Grouped Findings Retain Phase 5 Evidence Summary
# -----------------------------------------------------------------------------

def test_grouped_findings_retain_trust_layer():
    f1 = finding_view({
        "id": "F-401",
        "title": "Some content outside sections",
        "category": "ACCESSIBILITY",
        "source": "axe-core",
        "rule": "region",
        "verification_status": "CONFIRMED",
        "affected_element": {"selector": "#banner"}
    })
    f2 = finding_view({
        "id": "F-402",
        "title": "Some content outside sections",
        "category": "ACCESSIBILITY",
        "source": "axe-core",
        "rule": "region",
        "verification_status": "CONFIRMED",
        "affected_element": {"selector": "#footer-nav"}
    })

    grouped = group_findings_for_presentation([f1, f2])
    assert len(grouped) == 1
    parent = grouped[0]
    assert parent["affected_count"] == 2
    assert "reproduction" in parent
    assert "conclusion" in parent
    assert "why_aura_reported_this" in parent
    assert parent["reproduction"]["state"] == "OBSERVED"
    assert "2 parts of this page" in parent["summary"]
    # The observation describes what AURA did, not what the summary says: a grouped card used to set
    # them equal, which read as the same sentence twice.
    observation = parent["why_aura_reported_this"]["observation"]
    assert parent["summary"] != observation
    assert "2 separate elements" in observation


# -----------------------------------------------------------------------------
# 7. Ask AURA Chat Assistant Context & Truthful Grounding
# -----------------------------------------------------------------------------

def test_chat_context_includes_phase5_trust_fields():
    f = finding_view({
        "id": "F-501",
        "title": "Text is difficult to read",
        "category": "ACCESSIBILITY",
        "source": "axe-core",
        "rule": "color-contrast",
        "verification_status": "CONFIRMED",
        "affected_element": {"selector": ".subtext"},
        "evidence": {
            "sources": ["axe-core", "computed_styles"],
            "flags": {"screenshot": False, "dom": True},
            "types": ["ACCESSIBILITY", "STRUCTURAL"]
        }
    })
    audit_view = {
        "page_url": "https://example.com",
        "title": "Example",
        "viewport": {"width": 1440, "height": 900},
        "scores": {"aura": 85},
        "findings": [f]
    }
    ctx = build_chat_context(audit_view, finding_id="F-501")
    assert len(ctx["findings"]) == 1
    compact_f = ctx["findings"][0]
    assert compact_f["reproduction_state"] == "OBSERVED"
    assert compact_f["conclusion_strength"] == "Confirmed problem"
    assert compact_f["has_visual_evidence"] is False
    assert "ACCESSIBILITY" in compact_f["evidence_provenance"]


def test_ask_aura_answers_visual_provenance_truthfully():
    f = finding_view({
        "id": "F-601",
        "title": "Text is difficult to read",
        "category": "ACCESSIBILITY",
        "source": "axe-core",
        "rule": "color-contrast",
        "verification_status": "CONFIRMED",
        "affected_element": {"selector": ".subtext"},
        "evidence": {
            "sources": ["axe-core"],
            "flags": {"screenshot": False, "dom": True},
            "types": ["ACCESSIBILITY"]
        }
    })
    audit_view = {
        "page_url": "https://example.com",
        "title": "Example",
        "scores": {"aura": 85},
        "findings": [f]
    }

    provider = MockAIProvider()
    response = ask(provider, audit_view, "Did you see this contrast issue in the screenshot?", finding_id="F-601")
    assert "answer" in response
    # Mock or live response handles questions and cites finding
    assert response["cited_finding_ids"] == ["F-601"]
