import pytest
from pathlib import Path
from aura.agent.diagnostics import AIDiagnostics, AIAnalysisStatus
from aura.evaluation.evaluator import EvaluationEngine
from aura.evidence.correlator import EvidenceCorrelator
from aura.findings.models import (
    AURAFinding, FindingSource, FindingCategory, FindingSeverity,
    FindingVerificationStatus, AffectedElement, FindingEvidence
)


def test_diagnostics_reconcile_counts():
    """Verify that verified_count explicitly equals confirmed_count + likely_count."""
    diag = AIDiagnostics(
        ai_candidate_count_raw=10,
        ai_candidate_count_deduplicated=10,
        ai_candidate_count_confirmed=6,
        ai_candidate_count_likely=2,
        ai_candidate_count_uncertain=2,
        ai_candidate_count_rejected=0
    )
    diag.reconcile_counts()
    assert diag.ai_candidate_count_verified == 8  # 6 + 2, NOT 10!
    
    summary = diag.to_summary_dict()
    assert summary["Verified"] == 8
    assert summary["Confirmed"] == 6
    assert summary["Likely"] == 2
    assert summary["Uncertain"] == 2


def test_ground_truth_eligibility_policy(tmp_path):
    """Verify that EvaluationEngine evaluates ONLY eligible findings (CONFIRMED & LIKELY)."""
    site_dir = tmp_path / "test_site"
    site_dir.mkdir()
    gt_file = site_dir / "ground_truth.json"
    gt_content = """{
        "site_id": "test_site",
        "expected_findings": [
            {"id": "GT-001", "rule": "image-alt", "category": "ACCESSIBILITY", "target": "img.logo"},
            {"id": "GT-002", "rule": "color-contrast", "category": "ACCESSIBILITY", "target": "p.text"}
        ]
    }"""
    gt_file.write_text(gt_content, encoding="utf-8")

    f1_confirmed = AURAFinding(
        id="AURA-001",
        candidate_id="CAND-001",
        source=FindingSource.AI,
        category=FindingCategory.ACCESSIBILITY,
        severity=FindingSeverity.HIGH,
        title="Missing image alt text",
        description="Image missing alt attribute",
        observation="Observable missing alt attribute on image element",
        confidence=0.9,
        verification_status=FindingVerificationStatus.CONFIRMED,
        affected_element=AffectedElement(selector="img.logo"),
        raw_rule="image-alt",
        normalized_rule="image-alt",
        evidence=FindingEvidence(types=["DOM"], description="DOM inspection")
    )

    f2_uncertain = AURAFinding(
        id="AURA-002",
        candidate_id="CAND-002",
        source=FindingSource.AI,
        category=FindingCategory.ACCESSIBILITY,
        severity=FindingSeverity.MEDIUM,
        title="Low color contrast",
        description="Text contrast below threshold",
        observation="Visual observation of low contrast text",
        confidence=0.7,
        verification_status=FindingVerificationStatus.UNCERTAIN,
        affected_element=AffectedElement(selector="p.text"),
        raw_rule="color-contrast",
        normalized_rule="color-contrast",
        evidence=FindingEvidence(types=["VISUAL"], description="Visual inspection")
    )

    f3_rejected = AURAFinding(
        id="AURA-003",
        candidate_id="CAND-003",
        source=FindingSource.AI,
        category=FindingCategory.UX,
        severity=FindingSeverity.LOW,
        title="Misleading CTA",
        description="CTA button text ambiguous",
        observation="Claimed ambiguous button text",
        confidence=0.6,
        verification_status=FindingVerificationStatus.REJECTED,
        affected_element=AffectedElement(selector="button.cta"),
        raw_rule="weak_cta",
        normalized_rule="weak_cta",
        evidence=FindingEvidence(types=["VISUAL"], description="Visual inspection")
    )

    eval_res = EvaluationEngine.evaluate(site_dir, [f1_confirmed, f2_uncertain, f3_rejected])

    assert eval_res["detected_count"] == 1  # Eligible count
    assert eval_res["raw_detected_count"] == 3
    assert eval_res["true_positives"] == 1
    assert eval_res["false_positives"] == 0
    assert eval_res["false_negatives"] == 1
    assert eval_res["recall_formatted"] == "50.0%"
    assert eval_res["precision_formatted"] == "100.0%"

    trace = eval_res["traceability"]
    assert len(trace) == 4
    
    tp_item = next(t for t in trace if t["finding_id"] == "AURA-001")
    assert tp_item["benchmark_match_status"] == "TP"
    assert tp_item["ground_truth_id"] == "GT-001"

    inelig_item = next(t for t in trace if t["finding_id"] == "AURA-002")
    assert inelig_item["benchmark_match_status"] == "INELIGIBLE"
    assert inelig_item["verification_status"] == "uncertain"

    fn_item = next(t for t in trace if t["ground_truth_id"] == "GT-002")
    assert fn_item["benchmark_match_status"] == "FN"
    assert fn_item["finding_id"] == "N/A"


def test_source_unification_deduplication():
    """Verify AI and axe-core findings targeting the same semantic rule unify sources."""
    f_axe = AURAFinding(
        id="AURA-A11Y-001",
        source=FindingSource.AXE,
        sources=["axe-core"],
        category=FindingCategory.ACCESSIBILITY,
        severity=FindingSeverity.HIGH,
        title="WCAG image-alt violation",
        description="axe-core image-alt violation",
        observation="axe-core image-alt violation observed",
        confidence=1.0,
        verification_status=FindingVerificationStatus.CONFIRMED,
        affected_element=AffectedElement(selector="img.hero"),
        raw_rule="image-alt",
        normalized_rule="image-alt",
        evidence=FindingEvidence(types=["ACCESSIBILITY"], description="axe-core", sources=["axe-core"])
    )

    f_ai = AURAFinding(
        id="AURA-001",
        candidate_id="CAND-001",
        source=FindingSource.AI,
        sources=["AI"],
        category=FindingCategory.UX,
        severity=FindingSeverity.MEDIUM,
        title="Hero image missing alternative text",
        description="Hero image missing alternative text",
        observation="Hero image missing alternative text",
        confidence=0.85,
        verification_status=FindingVerificationStatus.CONFIRMED,
        affected_element=AffectedElement(selector="img.hero"),
        raw_rule="image-alt",
        normalized_rule="image-alt",
        evidence=FindingEvidence(types=["VISUAL"], description="AI visual observation", sources=["AI"])
    )

    deduped = EvidenceCorrelator.correlate_and_deduplicate([f_axe, f_ai])
    assert len(deduped) == 1
    unified = deduped[0]
    
    assert "axe-core" in unified.sources or "axe" in [s.lower() for s in unified.sources]
    assert "AI" in unified.sources or "ai" in [s.lower() for s in unified.sources]
    assert unified.verification_status == FindingVerificationStatus.CONFIRMED

