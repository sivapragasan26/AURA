import pytest
from aura.scoring.scorer import AURAScorer
from aura.analyzers.runtime_analyzer import RuntimeAnalyzer
from aura.models.findings import (
    CandidateFinding, FindingEvidenceDetail, VerificationResult, VerifiedFinding, VerificationStatus,
    AccessibilityViolation, RuntimeTelemetry, ConsoleError, RuntimeCategory
)


def test_aura_scorer_with_candidate_findings():
    scorer = AURAScorer()
    runtime_analyzer = RuntimeAnalyzer()

    c1 = CandidateFinding(
        id="AURA-001",
        category="UX",
        title="Button contrast low",
        description="Low visual hierarchy",
        observation="CTA button background shares card color",
        severity="high",
        confidence=0.9,
        evidence=FindingEvidenceDetail(type="visual", description="Test evidence")
    )
    vr1 = VerificationResult(issue_id="AURA-001", status=VerificationStatus.CONFIRMED, confidence=0.9, evidence_sources=["Verified in DOM"])
    vf1 = VerifiedFinding(candidate=c1, verification=vr1)

    telemetry = RuntimeTelemetry(
        url="http://localhost:8000",
        title="Test",
        viewport={"width": 1440, "height": 900},
        console_errors=[ConsoleError(type="exception", text="Uncaught Error", category=RuntimeCategory.APPLICATION_ERROR)]
    )
    runtime_analyzer.classify_telemetry(telemetry)

    a11y_violations = [
        AccessibilityViolation(rule="image-alt", impact="critical", description="Missing alt text", target=["img"])
    ]

    scores = scorer.compute_score(
        verified_findings=[vf1],
        accessibility_violations=a11y_violations,
        telemetry=telemetry
    )

    assert scores.overall < 100
    assert scores.ux < 100
    assert scores.accessibility <= 90
    assert scores.runtime <= 95
