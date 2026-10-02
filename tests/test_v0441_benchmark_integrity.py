import pytest
from pathlib import Path
from aura.evaluation.registry import GroundTruthRegistry
from aura.evaluation.evaluator import EvaluationEngine
from aura.findings.models import (
    AURAFinding, FindingSource, FindingCategory, FindingSeverity, FindingVerificationStatus, FindingEvidence, AffectedElement
)
from aura.verification.rules import VerificationRulesEngine, VerificationStatus


def test_ground_truth_registry_loading_and_uniqueness(tmp_path):
    """Verify GroundTruthRegistry loads, validates, and rejects duplicate ground_truth_id records."""
    gt_file = tmp_path / "ground_truth.json"
    gt_json = """{
        "suite_id": "test_suite",
        "name": "Test Suite",
        "expected_findings": [
            {"ground_truth_id": "GT-TEST-001", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"},
            {"ground_truth_id": "GT-TEST-001", "category": "UX", "normalized_rule": "confusing_form", "target": "#form"},
            {"ground_truth_id": "GT-TEST-002", "category": "INTERACTION", "normalized_rule": "interaction_failure", "target": "#btn"}
        ]
    }"""
    gt_file.write_text(gt_json, encoding="utf-8")

    res = GroundTruthRegistry.load_suite_ground_truth(tmp_path)
    assert res["suite_id"] == "test_suite"
    assert res["expected_defects_count"] == 2  # Duplicate GT-TEST-001 rejected
    assert len(res["unique_ground_truth_ids"]) == 2
    assert "GT-TEST-001" in res["unique_ground_truth_ids"]
    assert "GT-TEST-002" in res["unique_ground_truth_ids"]


def test_expected_defects_equals_tp_plus_fn_invariant(tmp_path):
    """Verify that expected_defects == true_positives + false_negatives invariant holds under all evaluations."""
    gt_file = tmp_path / "ground_truth.json"
    gt_json = """{
        "suite_id": "invariant_suite",
        "expected_findings": [
            {"ground_truth_id": "GT-INV-001", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"},
            {"ground_truth_id": "GT-INV-002", "category": "UX", "normalized_rule": "confusing_form", "target": "#form"},
            {"ground_truth_id": "GT-INV-003", "category": "INTERACTION", "normalized_rule": "interaction_failure", "target": "#btn"}
        ]
    }"""
    gt_file.write_text(gt_json, encoding="utf-8")

    f1_tp = AURAFinding(
        id="F-001",
        candidate_id="AI-001",
        source=FindingSource.AI,
        category=FindingCategory.UI,
        severity=FindingSeverity.HIGH,
        title="Bad visual hierarchy",
        description="Visual hierarchy issue",
        observation="Hero heading visual issue",
        confidence=0.9,
        verification_status=FindingVerificationStatus.CONFIRMED,
        affected_element=AffectedElement(selector="#hero"),
        raw_rule="bad_visual_hierarchy",
        normalized_rule="bad_visual_hierarchy",
        evidence=FindingEvidence(types=["VISUAL"], description="Test evidence"),
    )

    eval_res = EvaluationEngine.evaluate(tmp_path, [f1_tp])
    assert eval_res["expected_count"] == 3
    assert eval_res["true_positives"] == 1
    assert eval_res["false_negatives"] == 2
    assert eval_res["false_positives"] == 0
    assert eval_res["expected_count"] == eval_res["true_positives"] + eval_res["false_negatives"]
    assert eval_res["integrity_status"] == "PASS"


def test_strict_one_to_one_ground_truth_matching(tmp_path):
    """Verify multiple canonical findings for the same ground truth defect match AT MOST ONE TP, making rest FP."""
    gt_file = tmp_path / "ground_truth.json"
    gt_json = """{
        "suite_id": "one_to_one_suite",
        "expected_findings": [
            {"ground_truth_id": "GT-ONE-001", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"}
        ]
    }"""
    gt_file.write_text(gt_json, encoding="utf-8")

    f1 = AURAFinding(
        id="F-001",
        candidate_id="AI-001",
        source=FindingSource.AI,
        category=FindingCategory.UI,
        severity=FindingSeverity.HIGH,
        title="Bad visual hierarchy 1",
        description="Issue 1",
        observation="Observation 1",
        confidence=0.9,
        verification_status=FindingVerificationStatus.CONFIRMED,
        affected_element=AffectedElement(selector="#hero"),
        raw_rule="bad_visual_hierarchy",
        normalized_rule="bad_visual_hierarchy",
        evidence=FindingEvidence(types=["VISUAL"], description="Test evidence"),
    )

    f2_dup = AURAFinding(
        id="F-002",
        candidate_id="AI-002",
        source=FindingSource.AI,
        category=FindingCategory.UI,
        severity=FindingSeverity.HIGH,
        title="Bad visual hierarchy 2",
        description="Issue 2",
        observation="Observation 2",
        confidence=0.88,
        verification_status=FindingVerificationStatus.CONFIRMED,
        affected_element=AffectedElement(selector="#hero"),
        raw_rule="bad_visual_hierarchy",
        normalized_rule="bad_visual_hierarchy",
        evidence=FindingEvidence(types=["VISUAL"], description="Test evidence"),
    )

    eval_res = EvaluationEngine.evaluate(tmp_path, [f1, f2_dup])
    assert eval_res["expected_count"] == 1
    assert eval_res["true_positives"] == 1
    assert eval_res["false_positives"] == 1
    assert eval_res["false_negatives"] == 0
    assert eval_res["expected_count"] == eval_res["true_positives"] + eval_res["false_negatives"]


def test_fn_diagnostic_root_cause_classification(tmp_path):
    """Verify missed defects (FN) receive explicit diagnostic root cause classifications."""
    gt_file = tmp_path / "ground_truth.json"
    gt_json = """{
        "suite_id": "diag_suite",
        "expected_findings": [
            {"ground_truth_id": "GT-DIAG-001", "category": "UX", "normalized_rule": "confusing_form", "target": "#form"},
            {"ground_truth_id": "GT-DIAG-002", "category": "INTERACTION", "normalized_rule": "interaction_failure", "target": "#btn"}
        ]
    }"""
    gt_file.write_text(gt_json, encoding="utf-8")

    f_uncertain = AURAFinding(
        id="F-001",
        candidate_id="AI-001",
        source=FindingSource.AI,
        category=FindingCategory.UX,
        severity=FindingSeverity.HIGH,
        title="Confusing form",
        description="Form issue",
        observation="Form observation",
        confidence=0.5,
        verification_status=FindingVerificationStatus.UNCERTAIN,
        affected_element=AffectedElement(selector="#form"),
        raw_rule="confusing_form",
        normalized_rule="confusing_form",
        evidence=FindingEvidence(types=["VISUAL"], description="Test evidence"),
        canonical_target="#form"
    )

    eval_res = EvaluationEngine.evaluate(tmp_path, [f_uncertain])
    fn_diags = eval_res["fn_diagnostics"]
    assert len(fn_diags) == 2

    diag1 = next(d for d in fn_diags if d["ground_truth_id"] == "GT-DIAG-001")
    # A matching finding exists but verification left it UNCERTAIN (benchmark-ineligible)
    assert diag1["diagnostic_category"] == "EVIDENCE_INSUFFICIENT"

    diag2 = next(d for d in fn_diags if d["ground_truth_id"] == "GT-DIAG-002")
    assert diag2["diagnostic_category"] == "AI_NOT_GENERATED"


def test_provider_failure_returns_not_evaluable(tmp_path):
    """Verify provider failure returns benchmark_ai_status = NOT_EVALUABLE with N/A metrics."""
    gt_file = tmp_path / "ground_truth.json"
    gt_json = """{
        "suite_id": "fail_suite",
        "expected_findings": [
            {"ground_truth_id": "GT-FAIL-001", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"}
        ]
    }"""
    gt_file.write_text(gt_json, encoding="utf-8")

    eval_res = EvaluationEngine.evaluate(tmp_path, [], provider_failed=True)
    assert eval_res["benchmark_ai_status"] == "NOT_EVALUABLE"
    assert eval_res["precision_formatted"] == "N/A"
    assert "N/A" in eval_res["recall_formatted"]
    assert "N/A" in eval_res["f1_formatted"]


def test_false_affordance_rule_verification():
    """Verify VerificationRulesEngine confirms false_affordance candidate findings when DOM/interaction flags exist."""
    rules_engine = VerificationRulesEngine()
    
    cand = AURAFinding(
        id="F-001",
        source=FindingSource.AI,
        category=FindingCategory.INTERACTION,
        severity=FindingSeverity.HIGH,
        title="Fake button control",
        description="Non actionable element visually rendered as button",
        observation="Observation of fake button",
        confidence=0.85,
        verification_status=FindingVerificationStatus.UNCERTAIN,
        affected_element=AffectedElement(selector="div.fake-button"),
        raw_rule="false_affordance",
        normalized_rule="false_affordance",
        evidence=FindingEvidence(types=["INTERACTION"], description="Test interaction evidence")
    )

    # Confirmed only by a target-specific interaction that produced no effect (the control is not actionable)
    flags = {"screenshot": True, "dom": True, "accessibility": False, "runtime": False, "interaction": True,
             "interaction_no_effect": True}
    status, conf, reason = rules_engine.evaluate_status_and_confidence(cand, flags, [{"visible": True}], None)
    assert status == VerificationStatus.CONFIRMED
    assert conf >= 0.85

    # The element existing (dom) is not enough
    flags_exists_only = {"screenshot": True, "dom": True, "interaction": False}
    status, _, reason = rules_engine.evaluate_status_and_confidence(cand, flags_exists_only, [{"visible": True}], None)
    assert status == VerificationStatus.UNCERTAIN

    # An interaction that visibly worked contradicts "not actionable"
    flags_worked = {"screenshot": True, "dom": True, "interaction": True, "interaction_visible_effect": True}
    status, _, _ = rules_engine.evaluate_status_and_confidence(cand, flags_worked, [{"visible": True}], None)
    assert status != VerificationStatus.CONFIRMED

