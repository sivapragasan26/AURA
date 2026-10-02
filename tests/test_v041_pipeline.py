import pytest
from pathlib import Path
from aura.agent.diagnostics import AIDiagnostics, AIAnalysisStatus
from aura.agent.analyzer_agent import AnalyzerAgent, normalize_rule_type
from aura.agent.schemas import RawAICandidatePayload, AIAnalysisResponseSchema
from aura.agent.mock_provider import MockAIProvider
from aura.models.findings import (
    RuntimeTelemetry, ConsoleError, NetworkFailure, RuntimeCategory, ClassifiedRuntimeEvent
)
from aura.findings.models import (
    AURAFinding, FindingSource, FindingCategory, FindingSeverity, FindingVerificationStatus, FindingEvidence
)

from aura.analyzers.runtime_analyzer import RuntimeAnalyzer
from aura.scoring.scorer import AURAScorer
from aura.evaluation.evaluator import EvaluationEngine
from app import format_affected_element


def test_ai_diagnostics_initialization():
    diag = AIDiagnostics(provider_name="Gemini", model_name="gemini-2.5-flash")
    assert diag.status == AIAnalysisStatus.NOT_RUN
    assert diag.ai_request_started is False
    assert diag.ai_candidate_count_raw == 0


def test_rule_type_normalization():
    assert normalize_rule_type("weak_primary_cta") == "weak_primary_cta"
    assert normalize_rule_type("insufficient_cta_prominence") == "weak_primary_cta"
    assert normalize_rule_type("horizontal_content_overflow") == "horizontal_overflow"
    assert normalize_rule_type("unclear_form_flow") == "confusing_form"
    assert normalize_rule_type("inverted_hierarchy") == "bad_visual_hierarchy"


def test_json_parsing_robustness():
    agent = AnalyzerAgent(provider=MockAIProvider())
    diag = AIDiagnostics()
    
    # 1. Fenced JSON
    fenced_text = "```json\n{\"overall_summary\": \"OK\", \"candidates\": [{\"category\": \"UI\", \"rule_type\": \"weak_cta\", \"title\": \"Test\", \"description\": \"Desc\", \"severity\": \"MEDIUM\", \"confidence\": 0.9, \"target\": \"#btn\"}]}\n```"
    res1 = agent._parse_and_process_response(fenced_text, diag)
    assert diag.ai_response_parsed is True
    assert diag.status == AIAnalysisStatus.SUCCESS_WITH_CANDIDATES
    assert len(res1["issues"]) == 1

    # 2. Embedded prose JSON
    prose_text = "Here is the analysis result:\n{\"overall_summary\": \"OK\", \"candidates\": [{\"category\": \"UX\", \"rule_type\": \"confusing_form\", \"title\": \"Form Test\", \"description\": \"Desc\", \"severity\": \"HIGH\", \"confidence\": 0.85, \"target\": \"#form\"}]}\nHope this helps!"
    diag2 = AIDiagnostics()
    res2 = agent._parse_and_process_response(prose_text, diag2)
    assert diag2.ai_response_parsed is True
    assert diag2.status == AIAnalysisStatus.SUCCESS_WITH_CANDIDATES
    assert len(res2["issues"]) == 1

    # 3. Malformed JSON parse failure
    bad_text = "Not JSON at all"
    diag3 = AIDiagnostics()
    res3 = agent._parse_and_process_response(bad_text, diag3)
    assert diag3.ai_response_parsed is False
    assert diag3.status == AIAnalysisStatus.PARSE_FAILED


def test_candidate_deduplication():
    agent = AnalyzerAgent(provider=MockAIProvider())
    diag = AIDiagnostics()
    
    raw_payload = """{
      "overall_summary": "Test",
      "candidates": [
        {"category": "UI", "rule_type": "weak_primary_cta", "title": "Weak CTA 1", "description": "Desc 1", "severity": "MEDIUM", "confidence": 0.7, "target": "#primary-btn"},
        {"category": "UI", "rule_type": "weak_cta", "title": "Weak CTA 2", "description": "Desc 2", "severity": "HIGH", "confidence": 0.95, "target": "#primary-btn"}
      ]
    }"""
    res = agent._parse_and_process_response(raw_payload, diag)
    assert diag.ai_candidate_count_raw == 2
    assert diag.ai_candidate_count_deduplicated == 1
    assert len(res["issues"]) == 1
    assert res["issues"][0]["confidence"] == 0.95


def test_runtime_ownership_classification():
    telemetry = RuntimeTelemetry(
        url="http://127.0.0.1:8999",
        console_errors=[
            ConsoleError(type="error", text="Uncaught Error in main script", category=RuntimeCategory.APPLICATION_ERROR),
            ConsoleError(type="warning", text="Font load warning", category=RuntimeCategory.WARNING),
            ConsoleError(type="error", text="Google analytics failed", category=RuntimeCategory.TELEMETRY_FAILURE)
        ],
        network_failures=[
            NetworkFailure(url="http://127.0.0.1:8999/api/v1/data", status=500, category=RuntimeCategory.API_ERROR),
            NetworkFailure(url="https://cdn.example.com/asset.js", status=404, category=RuntimeCategory.THIRD_PARTY_FAILURE)
        ]
    )
    
    analyzer = RuntimeAnalyzer()
    events = analyzer.classify_telemetry(telemetry)
    
    owners = [e.ownership for e in events]
    assert "TARGET_APPLICATION" in owners
    assert "THIRD_PARTY" in owners
    assert "BROWSER" in owners


def test_score_na_when_ai_fails():
    scorer = AURAScorer()
    telemetry = RuntimeTelemetry(url="http://example.com")
    
    score, deductions = scorer.compute_score_with_deductions(
        verified_findings=[],
        accessibility_violations=[],
        telemetry=telemetry
    )
    assert score.overall >= 0


def test_format_affected_element_no_object():
    assert format_affected_element(None) == "N/A"
    assert format_affected_element("#btn") == "#btn"
    assert format_affected_element({"selector": "#btn", "tag": "button"}) == "#btn (button)"
    assert "[object Object]" not in format_affected_element({"selector": "#btn", "tag": "button"})


def test_one_to_one_ground_truth_matching():
    test_lab_dir = Path(__file__).resolve().parent.parent / "test_lab" / "01_accessibility_suite"
    
    # 2 identical predictions for same defect
    findings = [
        AURAFinding(
            id="AURA-1", source=FindingSource.AI, category=FindingCategory.ACCESSIBILITY, severity=FindingSeverity.HIGH,
            title="Image missing alt", description="Desc", observation="Missing alt", confidence=0.9,
            verification_status=FindingVerificationStatus.CONFIRMED, evidence=FindingEvidence(types=["ACCESSIBILITY"]),
            raw_rule="image-alt", affected_element={"selector": "#a11y-missing-alt", "tag": "img"}
        ),
        AURAFinding(
            id="AURA-2", source=FindingSource.AI, category=FindingCategory.ACCESSIBILITY, severity=FindingSeverity.HIGH,
            title="Image missing alt duplicate", description="Desc", observation="Missing alt", confidence=0.8,
            verification_status=FindingVerificationStatus.CONFIRMED, evidence=FindingEvidence(types=["ACCESSIBILITY"]),
            raw_rule="image-alt", affected_element={"selector": "#a11y-missing-alt", "tag": "img"}
        )
    ]
    
    res = EvaluationEngine.evaluate(test_lab_dir, findings)
    assert res["true_positives"] == 1
    assert res["false_positives"] == 1
