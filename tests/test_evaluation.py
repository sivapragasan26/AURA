import pytest
from pathlib import Path
from aura.evaluation.evaluator import EvaluationEngine
from aura.findings.models import AURAFinding, FindingSource, FindingCategory, FindingSeverity, FindingVerificationStatus, FindingEvidence


def test_evaluation_engine_metrics_positive():
    site_dir = Path(__file__).resolve().parent.parent / "test_lab" / "01_missing_alt"

    detected_findings = [
        AURAFinding(
            id="AURA-A11Y-001",
            source=FindingSource.AXE,
            category=FindingCategory.ACCESSIBILITY,
            severity=FindingSeverity.CRITICAL,
            title="WCAG [image-alt]: Image missing alt text",
            description="Image missing alt text",
            observation="Missing alt attribute",
            confidence=1.0,
            verification_status=FindingVerificationStatus.CONFIRMED,
            evidence=FindingEvidence(types=["ACCESSIBILITY"]),
            raw_rule="image-alt"
        )
    ]

    metrics = EvaluationEngine.evaluate(site_dir, detected_findings)

    assert metrics["expected_count"] == 1
    assert metrics["detected_count"] == 1
    assert metrics["true_positives"] == 1
    assert metrics["false_positives"] == 0
    assert metrics["false_negatives"] == 0
    assert metrics["precision"] == 1.0
    assert metrics["precision_formatted"] == "100.0%"
    assert metrics["recall"] == 1.0
    assert metrics["f1_score"] == 1.0


def test_evaluation_engine_zero_denominator_precision_na():
    site_dir = Path(__file__).resolve().parent.parent / "test_lab" / "08_bad_visual_hierarchy"

    # No positive predictions made by AURA -> TP=0, FP=0, FN=1
    detected_findings = []

    metrics = EvaluationEngine.evaluate(site_dir, detected_findings)

    assert metrics["expected_count"] == 1
    assert metrics["detected_count"] == 0
    assert metrics["true_positives"] == 0
    assert metrics["false_positives"] == 0
    assert metrics["false_negatives"] == 1
    assert metrics["precision"] is None
    assert metrics["precision_formatted"] == "N/A"
    assert "undefined" in metrics["precision_note"].lower()
    assert metrics["recall"] == 0.0
    assert metrics["f1_score"] == 0.0
    assert len(metrics["missed_defects"]) == 1


def test_evaluation_engine_suite_metrics():
    test_lab_dir = Path(__file__).resolve().parent.parent / "test_lab"
    scenario_results = {
        "01_accessibility_suite": [
            AURAFinding(
                id="AURA-A11Y-001",
                source=FindingSource.AXE,
                category=FindingCategory.ACCESSIBILITY,
                severity=FindingSeverity.CRITICAL,
                title="WCAG [image-alt]: Image missing alt text",
                description="Image missing alt text",
                observation="Missing alt attribute",
                confidence=1.0,
                verification_status=FindingVerificationStatus.CONFIRMED,
                evidence=FindingEvidence(types=["ACCESSIBILITY"]),
                raw_rule="image-alt"
            )
        ]
    }

    suite_res = EvaluationEngine.evaluate_suite(test_lab_dir, scenario_results)

    assert suite_res["total_scenarios"] >= 5
    assert "category_f1s" in suite_res
    assert suite_res["total_tp"] >= 1

