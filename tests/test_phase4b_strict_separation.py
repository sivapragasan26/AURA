"""
Phase 4B verification suite: Strict Human View / Technical View Separation
and True Screenshot Evidence Provenance.
"""
import pytest
from aura.interpretation.interpreter import (
    interpret_finding,
    AXE_INTERPRETATIONS,
    AI_INTERPRETATIONS,
    RUNTIME_INTERPRETATIONS,
    CANONICAL_ALIASES,
    describe_location,
    map_human_status,
    map_confidence_label,
)
from aura.api.views import finding_view
from aura.agent.prompts import AURA_SYSTEM_PROMPT
from aura.config.models import MODEL_CAPABILITIES, supports_vision


# Technical jargon tokens that must NOT appear in the user-facing human view
FORBIDDEN_HUMAN_TOKENS = [
    "wcag",
    "axe-core",
    "<main>",
    "<h1>",
    "<h2>",
    "<nav>",
    "<header>",
    "<footer>",
    "aria-",
    "aria ",
    "aria-label",
    "aria-labelledby",
    "css selector",
    "css path",
    "dom node",
    "dom path",
    "dom tree",
    "materiality score",
    "deterministic detector",
]


def test_no_jargon_in_axe_interpretations():
    """Verify all 30+ axe interpretation dictionaries contain zero technical jargon."""
    for rule, data in AXE_INTERPRETATIONS.items():
        title, summary, why, fix = data

        # Title and summary must never be identical
        assert title != summary, f"Rule '{rule}' has identical title and summary: '{title}'"
        assert len(title) > 0, f"Rule '{rule}' has empty title"
        assert len(summary) > 0, f"Rule '{rule}' has empty summary"
        assert len(why) > 0, f"Rule '{rule}' has empty why"
        assert len(fix) > 0, f"Rule '{rule}' has empty fix"

        for field_name, field_val in [("title", title), ("summary", summary), ("why", why), ("fix", fix)]:
            val_lower = field_val.lower()
            for token in FORBIDDEN_HUMAN_TOKENS:
                assert token not in val_lower, (
                    f"Forbidden jargon '{token}' found in AXE_INTERPRETATIONS['{rule}']['{field_name}']: {field_val}"
                )


def test_no_jargon_in_ai_interpretations():
    """Verify all AI interpretation templates contain zero technical jargon."""
    for rule, data in AI_INTERPRETATIONS.items():
        title, summary, why, fix = data

        assert title != summary, f"AI Rule '{rule}' has identical title and summary: '{title}'"
        for field_name, field_val in [("title", title), ("summary", summary), ("why", why), ("fix", fix)]:
            val_lower = field_val.lower()
            for token in FORBIDDEN_HUMAN_TOKENS:
                assert token not in val_lower, (
                    f"Forbidden jargon '{token}' found in AI_INTERPRETATIONS['{rule}']['{field_name}']: {field_val}"
                )


def test_no_jargon_in_runtime_interpretations():
    """Verify runtime interpretations contain zero technical jargon."""
    for rule, data in RUNTIME_INTERPRETATIONS.items():
        title, summary, why, fix = data
        assert title != summary, f"Runtime Rule '{rule}' has identical title and summary"
        for field_name, field_val in [("title", title), ("summary", summary), ("why", why), ("fix", fix)]:
            val_lower = field_val.lower()
            for token in FORBIDDEN_HUMAN_TOKENS:
                assert token not in val_lower, (
                    f"Forbidden jargon '{token}' found in RUNTIME_INTERPRETATIONS['{rule}']['{field_name}']: {field_val}"
                )


def test_specific_flagged_rules_have_human_explanations():
    """Check specifically the rules highlighted by users in Play Store / YouTube scans."""
    rules_to_check = [
        "page-has-heading-one",
        "landmark-one-main",
        "region",
        "link-name",
        "discoverability_problem",
        "search_discoverability",
        "secondary_looks_primary",
        "viewport_horizontal_scroll",
    ]
    for r in rules_to_check:
        raw_f = {
            "id": f"test-{r}",
            "rule": r,
            "category": "accessibility" if "landmark" in r or "heading" in r or "region" in r or "link" in r else "visual_hierarchy",
            "severity": "medium",
            "target": {"kind": "element", "selector": "#main-content", "tag": "div", "aria_label": ""},
            "evidence": {"sources": ["DOM", "Screenshot"]},
            "verification_status": "CONFIRMED",
            "verification_score": 0.95,
            "confidence": 0.90,
        }
        out = interpret_finding(raw_f)
        h = out["human"]
        t = out["technical"]

        # Human checks
        assert h["title"] != h["summary"], f"Title and summary are duplicate for {r}"
        for token in FORBIDDEN_HUMAN_TOKENS:
            assert token not in h["title"].lower(), f"Token {token} in title for {r}"
            assert token not in h["summary"].lower(), f"Token {token} in summary for {r}"
            assert token not in h["why_it_matters"].lower(), f"Token {token} in why for {r}"
            assert token not in h["what_to_do"].lower(), f"Token {token} in fix for {r}"

        # Technical checks: preserved perfectly
        assert t["rule_id"] == r
        assert t["verification_status"] == "CONFIRMED"
        assert t["verification_score"] == 0.95
        assert t["confidence"] == 0.90
        assert t["selector"] == "#main-content"


def test_evidence_provenance_tracking():
    """Verify evidence provenance tags (VISUAL, STRUCTURAL, ACCESSIBILITY, RUNTIME)."""
    # 1. Visual AI finding with screenshot
    visual_f = {
        "id": "v-1",
        "rule": "visual_hierarchy_weak",
        "category": "visual_hierarchy",
        "origin": "AI_GENERATED",
        "evidence": {"sources": ["screenshot_png_base64", "computed_styles"], "has_visual_evidence": True},
        "target": {"kind": "element", "selector": ".hero-btn", "role": "button"},
    }
    out_v = interpret_finding(visual_f)
    assert "VISUAL" in out_v["technical"]["evidence_provenance"]
    assert "STRUCTURAL" in out_v["technical"]["evidence_provenance"]

    # 2. Axe accessibility finding
    axe_f = {
        "id": "a-1",
        "rule": "color-contrast",
        "category": "accessibility",
        "origin": "DETERMINISTIC",
        "detector": "axe-core",
        "evidence": {"sources": ["axe-core", "color-check"]},
        "target": {"kind": "element", "selector": "p.text", "tag": "p"},
    }
    out_a = interpret_finding(axe_f)
    assert "ACCESSIBILITY" in out_a["technical"]["evidence_provenance"]

    # 3. Runtime console error finding
    rt_f = {
        "id": "r-1",
        "rule": "js_uncaught_exception",
        "category": "runtime_performance",
        "origin": "DETERMINISTIC",
        "detector": "console_telemetry",
        "evidence": {"sources": ["console.error"]},
        "target": {"kind": "element", "selector": "window"},
    }
    out_rt = interpret_finding(rt_f)
    assert "RUNTIME" in out_rt["technical"]["evidence_provenance"]


def test_finding_view_contract():
    """Ensure finding_view emits both human and technical schemas without dropping fields."""
    raw_finding = {
        "id": "F-042",
        "rule": "button-name",
        "category": "accessibility",
        "severity": "high",
        "origin": "DETERMINISTIC",
        "detector": "axe-core",
        "verification_status": "CONFIRMED",
        "verification_score": 1.0,
        "confidence": 0.95,
        "materiality_score": 0.85,
        "evidence": {"sources": ["axe-core-v4", "dom_snapshot"]},
        "target": {"kind": "element", "selector": "button.icon-only", "tag": "button"},
    }
    view = finding_view(raw_finding)

    assert "human" in view
    assert "technical" in view

    # Human view assertions
    h = view["human"]
    assert h["title"] == "Some buttons don't have clear names"
    assert "screen reader" in h["why_it_matters"].lower()
    assert "axe-core" not in h["title"].lower()
    assert "button.icon-only" not in h["location"]
    assert h["status_label"] == "Confirmed problem"
    assert h["confidence_label"] == "High"

    # Technical view assertions
    t = view["technical"]
    assert t["rule_id"] == "button-name"
    assert t["detector"] == "axe-core"
    assert t["selector"] == "button.icon-only"
    assert t["verification_status"] == "CONFIRMED"
    assert t["verification_score"] == 1.0
    assert t["confidence"] == 0.95
    assert t["materiality_score"] == 0.85
    assert "ACCESSIBILITY" in t["evidence_provenance"]


def test_model_capabilities_and_system_prompt_grounding():
    """Verify model capabilities table and prompt visual grounding instructions."""
    # Groq vision models
    assert supports_vision("groq", "qwen/qwen3.8-27b") is True
    assert supports_vision("groq", "llama-3.3-70b-versatile") is False
    assert supports_vision("gemini", "gemini-2.5-flash") is True
    assert supports_vision("openai", "gpt-4o") is True

    # System prompt visual grounding
    assert "CRITICAL VISUAL GROUNDING RULES" in AURA_SYSTEM_PROMPT
    assert "visually rendered in the screenshot" in AURA_SYSTEM_PROMPT
    assert "inspect the screenshot" in AURA_SYSTEM_PROMPT

