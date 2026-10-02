from pathlib import Path
import pytest

from aura.models.findings import CandidateFinding, FindingEvidenceDetail
from aura.findings.models import AURAFinding, FindingCategory, FindingSeverity, FindingVerificationStatus, FindingSource, FindingEvidence
from aura.agent.analyzer_agent import classify_ai_contribution, AnalyzerAgent
from aura.agent.diagnostics import AIDiagnostics
from aura.agent.prompts import AURA_SYSTEM_PROMPT
from aura.evaluation.evaluator import EvaluationEngine
from aura.verification.evidence import EvidenceMatcher
from aura.findings.aggregation import FindingsAggregator


def test_ai_contribution_classification_novel_insight():
    """Verify novel UI/UX insights receive NOVEL_AI_INSIGHT contribution type and score >= 0.85."""
    contrib_type, score = classify_ai_contribution(
        rule_type="bad_visual_hierarchy",
        title="Heading visual hierarchy inverted",
        description="Visual hierarchy prioritizes secondary cards over main heading",
        confidence=0.9
    )
    assert contrib_type == "NOVEL_AI_INSIGHT"
    assert score >= 0.85


def test_ai_contribution_classification_complementary_interpretation():
    """Verify AI adding UX error recovery interpretation to runtime/network events receives COMPLEMENTARY_INTERPRETATION."""
    contrib_type, score = classify_ai_contribution(
        rule_type="insufficient_feedback",
        title="API 404 failure provides no user error state",
        description="The failed request leaves the user with no visible error state or recovery guidance",
        confidence=0.85
    )
    assert contrib_type == "COMPLEMENTARY_INTERPRETATION"
    assert score >= 0.70


def test_ai_contribution_classification_deterministic_duplicate():
    """Verify pure deterministic duplicates receive DETERMINISTIC_DUPLICATE and score 0.0."""
    contrib_type, score = classify_ai_contribution(
        rule_type="image_alt",
        title="Image missing alt attribute",
        description="Image tag is missing alt text",
        confidence=0.9
    )
    assert contrib_type == "DETERMINISTIC_DUPLICATE"
    assert score == 0.0


def test_ai_duplicate_suppression_threshold():
    """Verify candidates below AI_INDEPENDENT_THRESHOLD (0.50) are suppressed from active AI candidates."""
    diag = AIDiagnostics(provider_name="Mock", model_name="test")
    agent = AnalyzerAgent()
    
    raw_response = """{
      "overall_summary": "Test duplicate suppression",
      "issues": [
        {
          "id": "AURA-001",
          "category": "ACCESSIBILITY",
          "title": "Image missing alt text",
          "description": "Image missing alt text",
          "observation": "Missing alt attribute",
          "severity": "medium",
          "confidence": 0.9,
          "affected_element": "img#hero",
          "evidence": {"type": "accessibility", "description": "axe match"},
          "rule_type": "image_alt"
        },
        {
          "id": "AURA-002",
          "category": "UI",
          "title": "Bad visual hierarchy in hero banner",
          "description": "Primary action button shares same styling as neutral container",
          "observation": "Visual contrast is poor",
          "severity": "high",
          "confidence": 0.88,
          "affected_element": "button#cta",
          "evidence": {"type": "visual", "description": "visual inspection"},
          "rule_type": "bad_visual_hierarchy"
        }
      ]
    }"""
    
    res = agent._parse_and_process_response(raw_response, diag)
    issues = res["issues"]
    
    # image_alt should be suppressed (score 0.0 < 0.50), bad_visual_hierarchy retained
    assert len(issues) == 1
    assert issues[0]["rule_type"] == "bad_visual_hierarchy"
    assert diag.deterministic_duplicate_count == 1
    assert diag.independent_candidate_count == 1
    assert diag.ai_duplicate_suppression_rate > 0.0


def test_system_prompt_contains_reflection_questions_and_priority():
    """Verify AURA_SYSTEM_PROMPT includes self-reflection questions and target priority list."""
    prompt = AURA_SYSTEM_PROMPT
    assert "Before reporting a candidate, ask yourself:" in prompt
    assert "1. Is this already deterministically established?" in prompt
    assert "bad_visual_hierarchy" in prompt
    assert "weak_primary_cta" in prompt
    assert "false_affordance" in prompt


def test_standardized_evidence_ids_format():
    """Verify evidence matcher generates standardized EV-xxx evidence IDs."""
    matcher = EvidenceMatcher()
    cand = CandidateFinding(
        id="AI-001",
        category="UI",
        title="Test Title",
        description="Test Desc",
        observation="Test Obs",
        severity="medium",
        confidence=0.9,
        affected_element="div#test",
        evidence=FindingEvidenceDetail(type="visual", description="Test evidence"),
        rule_type="bad_visual_hierarchy"
    )
    
    flags, sources, evidence_ids, _, _, _ = matcher.evaluate_evidence(
        candidate=cand,
        all_dom_elements=[{"tag": "div", "id": "test", "text": "sample text"}],
        accessibility_violations=[],
        telemetry=None
    )
    
    assert any(e.startswith("EV-") for e in evidence_ids)
    assert "EV-SCREEN-001" in evidence_ids


def test_aura_finding_model_includes_contribution_type_and_score():
    """Verify AURAFinding model supports ai_contribution_type and ai_contribution_score."""
    finding = AURAFinding(
        id="AURA-UI-001",
        source=FindingSource.AI,
        category=FindingCategory.UI,
        severity=FindingSeverity.HIGH,
        title="Bad Visual Hierarchy",
        description="Test description",
        observation="Test observation",
        confidence=0.9,
        verification_status=FindingVerificationStatus.CONFIRMED,
        evidence=FindingEvidence(types=["VISUAL"]),
        ai_contribution_type="NOVEL_AI_INSIGHT",
        ai_contribution_score=1.0
    )
    
    assert finding.ai_contribution_type == "NOVEL_AI_INSIGHT"
    assert finding.ai_contribution_score == 1.0
