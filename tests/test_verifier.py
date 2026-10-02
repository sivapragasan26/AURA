import pytest
from aura.verification.verifier import FindingVerifier
from aura.models.findings import (
    CandidateFinding, FindingEvidenceDetail, AffectedElementDetail, VerificationStatus,
    AccessibilityViolation, RuntimeTelemetry
)


def test_verifier_confirmed_and_rejected():
    verifier = FindingVerifier()

    dom_summary = {
        "all_elements": [
            {
                "tag": "button",
                "id": "submit-btn",
                "text": "Submit Form",
                "visible": True,
                "bounding_box": {"x": 10, "y": 10, "width": 80, "height": 30}
            }
        ]
    }

    # Candidate 1: Button exists and is visible -> CONFIRMED
    c1 = CandidateFinding(
        id="AURA-001",
        category="UX",
        title="Primary button contrast",
        description="CTA button visual hierarchy issue",
        observation="Primary button lacks contrast",
        severity="medium",
        confidence=0.85,
        affected_element=AffectedElementDetail(selector="button#submit-btn", tag="button", text="Submit Form"),
        evidence=FindingEvidenceDetail(type="visual", description="Low contrast visual observation")
    )

    # Candidate 2: Claims button is missing/hidden, but DOM & screenshot confirm visible -> REJECTED
    c2 = CandidateFinding(
        id="AURA-002",
        category="UI",
        title="Submit button missing from page",
        description="Submit button claimed absent",
        observation="Submit button is not visible on page",
        severity="high",
        confidence=0.70,
        affected_element=AffectedElementDetail(selector="button#submit-btn", tag="button", text="Submit Form"),
        evidence=FindingEvidenceDetail(type="visual", description="Visual claim of hidden button")
    )

    telemetry = RuntimeTelemetry(url="http://localhost:8000", title="Test", viewport={"width": 1440, "height": 900})

    active_findings, rejected_findings = verifier.verify_findings(
        candidate_findings=[c1, c2],
        dom_summary=dom_summary,
        accessibility_violations=[],
        telemetry=telemetry
    )

    assert len(active_findings) == 1
    # Since the materiality gate: a visual-only contrast claim with no measured ratio and no axe
    # color-contrast violation is a judgement call, not a confirmed defect (CONFIRMED needs measurement).
    assert active_findings[0].verification.status == VerificationStatus.LIKELY
    assert active_findings[0].verification.confidence <= 0.80
    assert "no measurement supports or contradicts the claim" in (active_findings[0].verification.rejection_reason or "")

    assert len(rejected_findings) == 1
    assert rejected_findings[0].verification.status == VerificationStatus.REJECTED
    # The universal screenshot-contradiction rule has one wording (rectification section 5).
    assert rejected_findings[0].verification.rejection_reason == "Visual evidence contradicts the AI observation."
