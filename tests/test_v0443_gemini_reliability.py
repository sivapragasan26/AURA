import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from aura.agent.gemini_provider import GeminiProvider, classify_gemini_error
from aura.agent.diagnostics import AIDiagnostics, AIAnalysisStatus
from aura.agent.analyzer_agent import AnalyzerAgent
from aura.evaluation.evaluator import EvaluationEngine
from aura.security.credentials import sanitize_provider_error


def test_classify_gemini_error():
    """Verify error categorization and retryable flags for Gemini HTTP statuses."""
    cat, code, retryable = classify_gemini_error(Exception("503 Service Unavailable"))
    assert cat == "TRANSIENT_PROVIDER_ERROR"
    assert code == 503
    assert retryable is True

    cat, code, retryable = classify_gemini_error(Exception("429 Resource Exhausted: quota exceeded"))
    assert cat == "RATE_LIMITED"
    assert code == 429
    assert retryable is True

    cat, code, retryable = classify_gemini_error(Exception("401 Unauthorized API key"))
    assert cat == "AUTHENTICATION_ERROR"
    assert code == 401
    assert retryable is False

    cat, code, retryable = classify_gemini_error(Exception("404 Model gemini-2.0-flash not found"))
    assert cat == "MODEL_NOT_FOUND"
    assert code == 404
    assert retryable is False


def test_gemini_provider_retry_success():
    """Verify GeminiProvider retries 503 transient error twice and succeeds on attempt 3."""
    provider = GeminiProvider(api_key="AIzaSyTestFakeKey12345", model="gemini-3.6-flash")

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.output_text = '{"candidates": [{"title": "Weak CTA", "category": "UI", "severity": "high"}]}'
    mock_resp.text = '{"candidates": [{"title": "Weak CTA", "category": "UI", "severity": "high"}]}'

    # Attempt 1 & 2 fail with 503, attempt 3 succeeds
    mock_client.interactions.create.side_effect = [
        Exception("503 Service Unavailable"),
        Exception("503 Service Unavailable"),
        mock_resp
    ]

    with patch("google.genai.Client", return_value=mock_client), \
         patch("time.sleep", return_value=None):
        res_text = provider.analyze("Test Prompt")
        assert "Weak CTA" in res_text

    meta = provider.last_execution_metadata
    assert meta["status"] == "SUCCESS"
    assert meta["attempt_count"] == 3
    assert meta["retry_count"] == 2
    assert meta["fallback_used"] is False
    assert meta["requested_model"] == "gemini-3.6-flash"


def test_gemini_provider_non_retryable_failure():
    """Verify non-retryable 401/404 errors fail immediately without retries."""
    provider = GeminiProvider(api_key="AIzaSyInvalidKey", model="gemini-3.6-flash")

    mock_client = MagicMock()
    mock_client.interactions.create.side_effect = Exception("401 Invalid API Key")

    with patch("google.genai.Client", return_value=mock_client):
        with pytest.raises(RuntimeError) as exc_info:
            provider.analyze("Test Prompt")

    assert "AUTHENTICATION_ERROR" in str(exc_info.value)
    meta = provider.last_execution_metadata
    assert meta["status"] == "PROVIDER_NOT_EVALUABLE"
    assert meta["failure_category"] == "AUTHENTICATION_ERROR"
    assert meta["attempt_count"] == 1
    assert meta["retry_count"] == 0


def test_gemini_connection_details_success():
    """Verify test_connection_details issues real small request and measures latency."""
    provider = GeminiProvider(api_key="AIzaSyTestFakeKey12345", model="gemini-3.6-flash")

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.output_text = "AURA_GEMINI_OK"
    mock_resp.text = "AURA_GEMINI_OK"
    mock_resp.id = "int-12345"
    mock_client.interactions.create.return_value = mock_resp

    with patch("google.genai.Client", return_value=mock_client):
        details = provider.test_connection_details()
        assert details["success"] is True
        assert details["status"] == "CONNECTED"
        assert details["actual_model"] == "gemini-3.6-flash"
        assert "CONNECTED" in details["message"]
        assert details["latency_ms"] >= 0


def test_provider_failure_benchmark_not_evaluable(tmp_path):
    """Verify provider failure produces PROVIDER_NOT_EVALUABLE status without creating AI False Negatives."""
    gt_file = tmp_path / "ground_truth.json"
    gt_json = """{
        "suite_id": "failure_test_suite",
        "expected_findings": [
            {"ground_truth_id": "GT-001", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"},
            {"ground_truth_id": "GT-002", "category": "UX", "normalized_rule": "confusing_form", "target": "#form"}
        ]
    }"""
    gt_file.write_text(gt_json, encoding="utf-8")

    eval_res = EvaluationEngine.evaluate(
        site_dir=tmp_path,
        detected_findings=[],
        provider_failed=True
    )

    assert eval_res["benchmark_ai_status"] == "NOT_EVALUABLE"
    assert eval_res["precision_formatted"] == "N/A"
    assert "N/A" in eval_res["recall_formatted"]
    assert "N/A" in eval_res["f1_formatted"]
    # Nothing is fabricated: counts are not computed, and the invariant is not claimed to pass
    assert eval_res["expected_count"] == 2
    assert eval_res["true_positives"] is None
    assert eval_res["false_positives"] is None
    assert eval_res["false_negatives"] is None
    assert eval_res["integrity_status"] == "NOT_EVALUABLE"


def test_api_key_security_sanitization():
    """Verify sensitive Gemini/OpenAI API keys are stripped from error output."""
    raw_error = "API request failed with key=AIzaSyA1B2C3D4E5F6G7H8I9J0 and Bearer sk-proj-1234567890abcdef"
    sanitized = sanitize_provider_error(raw_error)
    assert "AIzaSyA1B2C3D4E5F6G7H8I9J0" not in sanitized
    assert "sk-proj-1234567890abcdef" not in sanitized
    assert "[REDACTED_KEY]" in sanitized or "[REDACTED_API_KEY]" in sanitized


def test_build_gemini_multimodal_input_png_jpeg():
    """Verify build_gemini_multimodal_input preserves bytes and formats valid MIME types."""
    from aura.agent.gemini_provider import build_gemini_multimodal_input, normalize_mime_type

    assert normalize_mime_type("png") == "image/png"
    assert normalize_mime_type("jpeg") == "image/jpeg"
    assert normalize_mime_type(None) == "image/png"

    # Text-only
    res_text = build_gemini_multimodal_input("Prompt only")
    assert res_text == "Prompt only"

    # Multimodal PNG
    res_mm = build_gemini_multimodal_input("Prompt with PNG", "b64data==", "image/png")
    assert isinstance(res_mm, list)
    assert len(res_mm) == 2
    assert res_mm[0]["type"] == "text"
    assert res_mm[1]["type"] == "image"
    assert res_mm[1]["mime_type"] == "image/png"
    assert res_mm[1]["data"] == "b64data=="
    assert res_mm[1]["image"]["bytes"] == "b64data=="
    assert "data:image/png;base64,b64data==" in res_mm[1]["image_url"]["url"]


