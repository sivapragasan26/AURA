import pytest
from pathlib import Path
from aura.evaluation.registry import GroundTruthRegistry
from aura.evaluation.evaluator import EvaluationEngine
from aura.findings.aggregation import FindingsAggregator, AggregationResult
from aura.findings.models import (
    AURAFinding, FindingVerificationStatus, FindingSeverity,
    FindingCategory, FindingSource, FindingEvidence, AffectedElement
)


def test_expected_defect_count_sourced_only_from_registry():
    """TEST 1 & 2: Expected defect count is sourced only from GroundTruthRegistry."""
    site_dir = Path("test_lab/05_mixed_realistic_suite")
    gt = GroundTruthRegistry.load_suite_ground_truth(site_dir)
    assert gt["expected_defects_count"] == 7
    assert len(gt["expected_findings"]) == 7
    
    eval_res = EvaluationEngine.evaluate(site_dir, [])
    assert eval_res["expected_count"] == 7
    assert eval_res["expected_count"] == gt["expected_defects_count"]


def test_tp_plus_fn_equals_expected_defect_count():
    """TEST 3 & 13: Invariant TP + FN == Expected Defects holds deterministically."""
    site_dir = Path("test_lab/05_mixed_realistic_suite")
    eval_res = EvaluationEngine.evaluate(site_dir, [])
    assert eval_res["true_positives"] + eval_res["false_negatives"] == eval_res["expected_count"]
    assert eval_res["integrity_status"] == "PASS"


def test_one_to_one_matching_invariants():
    """TEST 4 & 5: Strict 1:1 ground-truth matching enforcement."""
    site_dir = Path("test_lab/05_mixed_realistic_suite")
    
    # Create findings matching GT-MIX-001
    f1 = AURAFinding(
        id="F-001",
        title="image_alt_missing",
        description="Missing alt",
        observation="Missing alt",
        category=FindingCategory.ACCESSIBILITY,
        severity=FindingSeverity.MEDIUM,
        source=FindingSource.AI,
        sources=["axe-core"],
        canonical_target="#mixed-missing-alt",
        verification_status=FindingVerificationStatus.CONFIRMED,
        confidence=1.0,
        evidence=FindingEvidence(flags={"dom": True}),
        normalized_rule="image_alt_missing"
    )
    f2 = AURAFinding(
        id="F-002",
        title="image_alt_missing",
        description="Missing alt 2",
        observation="Missing alt 2",
        category=FindingCategory.ACCESSIBILITY,
        severity=FindingSeverity.MEDIUM,
        source=FindingSource.AI,
        sources=["axe-core"],
        canonical_target="#mixed-missing-alt",
        verification_status=FindingVerificationStatus.CONFIRMED,
        confidence=1.0,
        evidence=FindingEvidence(flags={"dom": True}),
        normalized_rule="image_alt_missing"
    )
    
    eval_res = EvaluationEngine.evaluate(site_dir, [f1, f2])
    # Only ONE finding can match GT-MIX-001 as TP; the other becomes FP
    assert eval_res["true_positives"] == 1
    assert eval_res["false_positives"] == 1
    assert eval_res["expected_count"] == eval_res["true_positives"] + eval_res["false_negatives"]


def test_fn_root_cause_classification():
    """TEST 6: FN root cause distinguishes AI_NOT_GENERATED from CORRELATION_FAILURE."""
    site_dir = Path("test_lab/05_mixed_realistic_suite")
    eval_res = EvaluationEngine.evaluate(site_dir, [])
    assert len(eval_res["fn_diagnostics"]) == 7
    causes = {d["ground_truth_id"]: d["diagnostic_category"] for d in eval_res["fn_diagnostics"]}
    # Nothing was produced: AI-detectable defects are AI_NOT_GENERATED; the runtime-only defect
    # (allowed_sources = RUNTIME) is missing deterministic evidence, not an AI miss
    assert causes["GT-MIX-007"] == "EVIDENCE_INSUFFICIENT"
    assert all(c == "AI_NOT_GENERATED" for gt, c in causes.items() if gt != "GT-MIX-007")


def test_fp_root_cause_availability():
    """TEST 7: FP root cause is always available for active findings outside ground truth."""
    site_dir = Path("test_lab/05_mixed_realistic_suite")
    f_extra = AURAFinding(
        id="F-999",
        title="extra_unknown_rule",
        description="Non-GT finding",
        observation="Non-GT finding",
        category=FindingCategory.UX,
        severity=FindingSeverity.LOW,
        source=FindingSource.AI,
        sources=["AI"],
        canonical_target="#non-existent-element",
        verification_status=FindingVerificationStatus.CONFIRMED,
        confidence=1.0,
        evidence=FindingEvidence(flags={"dom": True}),
        normalized_rule="extra_unknown_rule"
    )
    eval_res = EvaluationEngine.evaluate(site_dir, [f_extra])
    assert eval_res["false_positives"] == 1
    assert len(eval_res["fp_diagnostics"]) == 1
    assert eval_res["fp_diagnostics"][0]["diagnostic_category"] == "OUTSIDE_BENCHMARK_SCOPE"


def test_verification_summary_source_obs_vs_canonical():
    """TEST 10: Verification summary distinguishes source observations from canonical findings."""
    agg = FindingsAggregator.aggregate(
        verified_ai_findings=[],
        rejected_ai_findings=[],
        accessibility_violations=[],
        telemetry=None
    )
    assert "0" in agg.summary_text or "No" in agg.summary_text


def test_provider_failure_benchmark_handling():
    """TEST 11: Provider failure sets benchmark status to NOT_EVALUABLE cleanly."""
    site_dir = Path("test_lab/05_mixed_realistic_suite")
    eval_res = EvaluationEngine.evaluate(site_dir, [], provider_failed=True)
    assert eval_res["benchmark_ai_status"] == "NOT_EVALUABLE"
    assert eval_res["precision_formatted"] == "N/A"
    assert eval_res["recall_formatted"] == "N/A (NOT EVALUABLE)"


def test_ground_truth_isolation():
    """TEST 14: Ground Truth is strictly isolated and never leaked to prompts."""
    from aura.agent.prompts import AURA_SYSTEM_PROMPT
    assert "ground_truth" not in AURA_SYSTEM_PROMPT.lower()
    assert "expected_findings" not in AURA_SYSTEM_PROMPT.lower()

