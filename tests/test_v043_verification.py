import pytest
from aura.models.findings import (
    CandidateFinding, FindingEvidenceDetail, AccessibilityViolation,
    RuntimeTelemetry, ConsoleError, NetworkFailure
)
from aura.verification.verifier import FindingVerifier
from aura.verification.evidence import EvidenceMatcher
from aura.verification.rules import VerificationRulesEngine
from aura.findings.aggregation import FindingsAggregator
from aura.agent.diagnostics import AIDiagnostics


def test_ai_candidate_verification_correlation():
    verifier = FindingVerifier()
    
    candidate = CandidateFinding(
        id="AI-001",
        candidate_id="AI-001",
        category="ACCESSIBILITY",
        title="Image element is missing alternative text",
        description="The primary image does not specify an alt attribute.",
        observation="Missing alt attribute",
        severity="high",
        confidence=0.90,
        affected_element={"selector": "#hero-img", "tag": "img"},
        evidence=FindingEvidenceDetail(type="accessibility", description="axe scan"),
        rule_type="image_alt",
        normalized_rule="image_alt"
    )

    dom_summary = {
        "all_elements": [
            {"tag": "img", "id": "hero-img", "alt": None, "visible": True, "bounding_box": {"x": 10, "y": 10, "width": 100, "height": 100}}
        ]
    }

    a11y_violations = [
        AccessibilityViolation(
            rule="image-alt",
            impact="critical",
            description="Images must have alternate text",
            target=["#hero-img"]
        )
    ]

    telemetry = RuntimeTelemetry(url="http://127.0.0.1:8999")

    active_findings, rejected_findings = verifier.verify_findings(
        candidate_findings=[candidate],
        dom_summary=dom_summary,
        accessibility_violations=a11y_violations,
        telemetry=telemetry
    )

    assert len(active_findings) == 1
    assert len(rejected_findings) == 0

    vf = active_findings[0]
    assert vf.verification.status.value.lower() == "confirmed"
    assert "AXE-001" in vf.verification.evidence_ids
    assert any(e in vf.verification.evidence_ids for e in ["EV-AXE-001", "AXE-001"])


def test_overflow_candidate_verification():
    verifier = FindingVerifier()

    candidate = CandidateFinding(
        id="AI-002",
        candidate_id="AI-002",
        category="RESPONSIVENESS",
        title="Page exhibits horizontal layout overflow",
        description="The content width exceeds the screen viewport width.",
        observation="Horizontal overflow",
        severity="medium",
        confidence=0.85,
        affected_element="body",
        evidence=FindingEvidenceDetail(type="dom", description="DOM measurement"),
        rule_type="horizontal_overflow",
        normalized_rule="horizontal_overflow"
    )

    dom_summary = {
        "has_horizontal_overflow": True,
        "doc_scroll_width": 1600,
        "doc_viewport_width": 1440
    }

    telemetry = RuntimeTelemetry(url="http://127.0.0.1:8999", dom_summary=dom_summary)

    active_findings, rejected_findings = verifier.verify_findings(
        candidate_findings=[candidate],
        dom_summary=dom_summary,
        accessibility_violations=[],
        telemetry=telemetry
    )

    assert len(active_findings) == 1
    assert active_findings[0].verification.status.value.lower() == "confirmed"
    assert "DOM-OVERFLOW" in active_findings[0].verification.evidence_ids
    assert any(e in active_findings[0].verification.evidence_ids for e in ["EV-RESPONSIVE-001", "DOM-OVERFLOW"])


def test_broken_navigation_verification():
    verifier = FindingVerifier()

    candidate = CandidateFinding(
        id="AI-003",
        candidate_id="AI-003",
        category="NAVIGATION",
        title="Top navigation links are non-functional placeholders",
        description="Clicking navigation link does not trigger destination page.",
        observation="Placeholder link",
        severity="high",
        confidence=0.85,
        affected_element={"selector": "#nav-link", "tag": "a"},
        evidence=FindingEvidenceDetail(type="dom", description="Interaction log"),
        rule_type="broken_navigation",
        normalized_rule="broken_navigation"
    )

    dom_summary = {
        "all_elements": [
            {"tag": "a", "id": "nav-link", "href": "#", "text": "Products", "visible": True}
        ]
    }

    telemetry = RuntimeTelemetry(url="http://127.0.0.1:8999")
    interaction_log = [{"action": "click", "target": "#nav-link", "status": "executed"}]

    active_findings, rejected_findings = verifier.verify_findings(
        candidate_findings=[candidate],
        dom_summary=dom_summary,
        accessibility_violations=[],
        telemetry=telemetry,
        interaction_log=interaction_log
    )

    assert len(active_findings) == 1
    assert active_findings[0].verification.status.value.lower() == "confirmed"


def test_valid_claim_rejected():
    verifier = FindingVerifier()

    candidate = CandidateFinding(
        id="AI-004",
        candidate_id="AI-004",
        category="ACCESSIBILITY",
        title="Image element is missing alternative text",
        description="Image lacks alt text",
        observation="Missing alt",
        severity="medium",
        confidence=0.80,
        affected_element={"selector": "#valid-img", "tag": "img"},
        evidence=FindingEvidenceDetail(type="dom", description="DOM check"),
        rule_type="image_alt",
        normalized_rule="image_alt"
    )

    # DOM actually HAS valid non-empty alt text!
    dom_summary = {
        "all_elements": [
            {"tag": "img", "id": "valid-img", "alt": "User Profile Photo", "visible": True}
        ]
    }

    telemetry = RuntimeTelemetry(url="http://127.0.0.1:8999")

    active_findings, rejected_findings = verifier.verify_findings(
        candidate_findings=[candidate],
        dom_summary=dom_summary,
        accessibility_violations=[],
        telemetry=telemetry
    )

    assert len(active_findings) == 0
    assert len(rejected_findings) == 1
    assert rejected_findings[0].verification.status.value.lower() == "rejected"
    assert "valid non-empty alt attribute" in (rejected_findings[0].verification.rejection_reason or "")


def test_insufficient_evidence_uncertain():
    verifier = FindingVerifier()

    candidate = CandidateFinding(
        id="AI-005",
        candidate_id="AI-005",
        category="UI",
        title="Unclear obscure layout alignment in subpanel",
        description="Subpanel layout feels awkward",
        observation="Visual layout issue",
        severity="low",
        confidence=0.50,
        affected_element={"selector": "#non-existent-subpanel", "tag": "div"},
        evidence=FindingEvidenceDetail(type="visual", description="Visual observation"),
        rule_type="bad_visual_hierarchy",
        normalized_rule="bad_visual_hierarchy"
    )

    dom_summary = {"all_elements": []}
    telemetry = RuntimeTelemetry(url="http://127.0.0.1:8999")

    active_findings, rejected_findings = verifier.verify_findings(
        candidate_findings=[candidate],
        dom_summary=dom_summary,
        accessibility_violations=[],
        telemetry=telemetry
    )

    assert len(active_findings) == 1
    assert active_findings[0].verification.status.value.lower() == "uncertain"


def test_pipeline_count_reconciliation():
    diag = AIDiagnostics(
        provider_name="Gemini",
        model_name="gemini-2.5-flash",
        ai_candidate_count_raw=10,
        ai_candidate_count_valid=10,
        ai_candidate_count_normalized=10,
        ai_candidate_count_deduplicated=10,
        ai_candidate_count_confirmed=6,
        ai_candidate_count_likely=2,
        ai_candidate_count_uncertain=1,
        ai_candidate_count_rejected=1
    )

    diag.reconcile_counts()

    assert diag.ai_candidate_count_verified == 8  # 6 confirmed + 2 likely
    assert diag.ai_candidate_count_deduplicated == (
        diag.ai_candidate_count_confirmed +
        diag.ai_candidate_count_likely +
        diag.ai_candidate_count_uncertain +
        diag.ai_candidate_count_rejected
    )

