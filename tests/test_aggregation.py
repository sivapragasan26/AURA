import pytest
from aura.findings.aggregation import FindingsAggregator
from aura.findings.models import AURAFinding, FindingSource, FindingSeverity, FindingVerificationStatus
from aura.analyzers.runtime_analyzer import RuntimeAnalyzer
from aura.models.findings import (
    AccessibilityViolation, RuntimeTelemetry, ConsoleError, NetworkFailure,
    RuntimeCategory, VerifiedFinding, CandidateFinding, FindingEvidenceDetail, VerificationResult, VerificationStatus
)


def test_aggregation_converts_axe_violations_into_confirmed_findings():
    a11y_violations = [
        AccessibilityViolation(rule="color-contrast", impact="critical", description="Low contrast element", target=["div#nav"]),
        AccessibilityViolation(rule="image-alt", impact="serious", description="Image missing alt text", target=["img#logo"]),
        AccessibilityViolation(rule="button-name", impact="moderate", description="Button missing label", target=["button#menu"]),
        AccessibilityViolation(rule="label", impact="minor", description="Form label missing", target=["input#email"]),
        AccessibilityViolation(rule="landmark-one-main", impact="moderate", description="No main landmark", target=["html"]),
    ]

    result = FindingsAggregator.aggregate(
        verified_ai_findings=[],
        rejected_ai_findings=[],
        accessibility_violations=a11y_violations,
        telemetry=RuntimeTelemetry(url="http://example.com", title="Test", viewport={"width": 1440, "height": 900})
    )

    # 1. Total findings must be 5
    assert len(result.findings) == 5

    # 2. Every finding must have source=AXE and status=CONFIRMED
    for f in result.findings:
        assert f.source == FindingSource.AXE
        assert f.verification_status == FindingVerificationStatus.CONFIRMED

    # 3. Severity counts must NOT be all 0
    assert result.severity_counts["critical"] == 1
    assert result.severity_counts["high"] == 1
    assert result.severity_counts["medium"] == 2
    assert result.severity_counts["low"] == 1

    # 4. Summary text must NOT declare "No defects identified"
    assert "No defects identified" not in result.summary_text
    assert "5" in result.summary_text


def test_aggregation_captures_runtime_telemetry_errors():
    telemetry = RuntimeTelemetry(
        url="http://example.com",
        title="Test",
        viewport={"width": 1440, "height": 900},
        console_errors=[
            ConsoleError(type="error", text="Uncaught TypeError: Cannot read property 'map' of undefined", category=RuntimeCategory.APPLICATION_ERROR)
        ],
        network_failures=[
            NetworkFailure(url="http://example.com/api/v1/user", status=500, status_text="Internal Server Error", method="GET", category=RuntimeCategory.API_ERROR)
        ]
    )
    RuntimeAnalyzer().classify_telemetry(telemetry)

    result = FindingsAggregator.aggregate(
        verified_ai_findings=[],
        rejected_ai_findings=[],
        accessibility_violations=[],
        telemetry=telemetry
    )

    assert len(result.findings) == 2
    for f in result.findings:
        assert f.source == FindingSource.RUNTIME
        assert f.verification_status == FindingVerificationStatus.CONFIRMED

    assert result.severity_counts["high"] >= 1
    assert "2" in result.summary_text


def test_aggregation_combines_ai_axe_and_runtime_findings():
    c1 = CandidateFinding(
        id="AI-001",
        category="UX",
        title="Confusing navigation structure",
        description="Navigation hierarchy is unclear",
        observation="Nav items overlap on narrow screens",
        severity="medium",
        confidence=0.85,
        evidence=FindingEvidenceDetail(type="visual", description="Visual overlap")
    )
    vr1 = VerificationResult(issue_id="AI-001", status=VerificationStatus.CONFIRMED, confidence=0.85)
    ai_finding = VerifiedFinding(candidate=c1, verification=vr1)

    a11y = [AccessibilityViolation(rule="color-contrast", impact="critical", description="Low contrast", target=["div"])]

    telemetry = RuntimeTelemetry(
        url="http://example.com",
        title="Test",
        viewport={"width": 1440, "height": 900},
        console_errors=[ConsoleError(type="error", text="Fatal crash", category=RuntimeCategory.APPLICATION_ERROR)]
    )
    RuntimeAnalyzer().classify_telemetry(telemetry)

    result = FindingsAggregator.aggregate(
        verified_ai_findings=[ai_finding],
        rejected_ai_findings=[],
        accessibility_violations=a11y,
        telemetry=telemetry
    )

    assert len(result.findings) == 3
    sources = {f.source for f in result.findings}
    assert sources == {FindingSource.AI, FindingSource.AXE, FindingSource.RUNTIME}

