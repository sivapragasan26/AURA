import pytest
from aura.analyzers.runtime_analyzer import RuntimeAnalyzer
from aura.scoring.runtime_scorer import RuntimeScorer
from aura.models.findings import RuntimeTelemetry, ConsoleError, NetworkFailure, RuntimeCategory


def test_runtime_classification():
    analyzer = RuntimeAnalyzer()
    scorer = RuntimeScorer()

    telemetry = RuntimeTelemetry(
        url="http://localhost:8000/app",
        title="Test App",
        viewport={"width": 1440, "height": 900},
        console_errors=[
            ConsoleError(type="exception", text="Uncaught TypeError: Cannot read property of null"),
            ConsoleError(type="error", text="Failed to load resource google-analytics.com/collect")
        ],
        network_failures=[
            NetworkFailure(url="http://localhost:8000/api/users", status=500, status_text="Internal Server Error", method="GET"),
            NetworkFailure(url="https://google-analytics.com/g/collect", status=404, status_text="Not Found", method="POST")
        ]
    )

    events = analyzer.classify_telemetry(telemetry)
    assert len(events) == 4

    categories = [e.category for e in events]
    assert RuntimeCategory.APPLICATION_ERROR in categories
    assert RuntimeCategory.TELEMETRY_FAILURE in categories
    assert RuntimeCategory.API_ERROR in categories

    # Verify transparent runtime score deduction
    score = scorer.compute_runtime_score(events)
    # 100 - (25 app exception + 1 telemetry + 20 api error + 1 telemetry failure) = 53
    assert score < 100
    assert score > 0

