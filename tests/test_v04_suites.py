import pytest
from pathlib import Path
from test_lab.launcher import TestLabLauncher
from aura.evaluation.evaluator import EvaluationEngine
from aura.analyzers.runtime_analyzer import RuntimeAnalyzer
from aura.models.findings import RuntimeTelemetry, ConsoleError, NetworkFailure, RuntimeCategory
from aura.scoring.runtime_scorer import RuntimeScorer


def test_five_consolidated_suites_discovery():
    """Verify that TestLabLauncher discovers exactly 5 consolidated suites."""
    sites = TestLabLauncher.list_sites()
    assert len(sites) == 5, f"Expected 5 consolidated suites, found {len(sites)}"
    
    suite_ids = [s["id"] for s in sites]
    expected_ids = [
        "01_accessibility_suite",
        "02_ui_ux_suite",
        "03_navigation_interaction_suite",
        "04_responsive_runtime_suite",
        "05_mixed_realistic_suite"
    ]
    for exp_id in expected_ids:
        assert exp_id in suite_ids, f"Expected suite {exp_id} not found in discovered sites"


def test_embedded_ground_truth_parsing():
    """Verify ground truth is loaded correctly from embedded HTML script tag."""
    test_lab_dir = Path("test_lab") / "01_accessibility_suite"
    gt = EvaluationEngine.load_ground_truth(test_lab_dir)
    
    assert gt.get("suite_id") == "01_accessibility_suite"
    expected = gt.get("expected_findings", [])
    assert len(expected) == 6, f"Expected 6 ground truth defects in 01_accessibility_suite, got {len(expected)}"


def test_runtime_event_classification():
    """Verify runtime event classification separates application errors from third party errors."""
    analyzer = RuntimeAnalyzer()
    scorer = RuntimeScorer()
    
    telemetry = RuntimeTelemetry(
        url="http://127.0.0.1:8999",
        console_errors=[
            ConsoleError(type="exception", text="Uncaught ReferenceError: x is not defined"),
            ConsoleError(type="error", text="Failed to load resource from google-analytics.com")
        ],
        network_failures=[
            NetworkFailure(url="http://127.0.0.1:8999/api/v1/status-500", status=500, status_text="Internal Server Error"),
            NetworkFailure(url="https://analytics.facebook.net/pixel", status=404, status_text="Not Found")
        ]
    )
    
    events = analyzer.classify_telemetry(telemetry)
    summary = scorer.summarize_runtime_events(events)
    
    assert summary["application_errors"] == 2, f"Expected 2 application errors, got {summary['application_errors']}"
    assert summary["third_party_failures"] == 2, f"Expected 2 third-party failures, got {summary['third_party_failures']}"
    
    # Runtime score should penalize ONLY application errors (25 for exception + 20 for 500 API error = 45 deduction)
    score = scorer.compute_runtime_score(events)
    assert score == 55, f"Expected runtime score 55 (100 - 45 deduction), got {score}"


def test_zero_denominator_precision_handling():
    """Verify precision is returned as None (N/A) when TP=0 and FP=0."""
    test_lab_dir = Path("test_lab") / "01_accessibility_suite"
    # No findings detected
    res = EvaluationEngine.evaluate(test_lab_dir, [])
    
    assert res["precision"] is None
    assert res["precision_formatted"] == "N/A"
    assert "Precision is undefined" in res["precision_note"]
    assert res["recall"] == 0.0
    assert res["f1_score"] == 0.0
    assert res["false_negatives"] == 6

