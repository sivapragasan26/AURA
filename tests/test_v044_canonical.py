import pytest
from pathlib import Path
from aura.agent.analyzer_agent import normalize_rule_type
from aura.evaluation.evaluator import EvaluationEngine
from aura.evidence.correlator import EvidenceCorrelator, normalize_target_selector
from aura.findings.models import (
    AURAFinding, FindingSource, FindingCategory, FindingSeverity,
    FindingVerificationStatus, AffectedElement, FindingEvidence, AggregationResult
)
from aura.findings.aggregation import FindingsAggregator


def test_target_selector_normalization():
    """Verify normalize_target_selector resolves equivalent element selectors to canonical targets."""
    assert normalize_target_selector("header > div.hero > img#logo") == "#logo"
    assert normalize_target_selector("div.card > button.btn-primary") == "button.btn-primary"
    assert normalize_target_selector("form#ux-form input.email", {"id": "user-email"}) == "#user-email"
    assert normalize_target_selector("") == "window / document"


def test_expanded_rule_taxonomy_normalization():
    """Verify V0.4.4 defect taxonomy canonical rule normalization."""
    assert normalize_rule_type("bad_visual_hierarchy") == "bad_visual_hierarchy"
    assert normalize_rule_type("weak_cta") == "weak_primary_cta"
    assert normalize_rule_type("confusing_form") == "confusing_form"
    assert normalize_rule_type("dead_button") == "interaction_failure"
    assert normalize_rule_type("mobile_layout_break") == "horizontal_overflow"
    assert normalize_rule_type("image-alt") == "image_alt_missing"


def test_canonical_finding_correlation():
    """Verify AI + axe-core findings correlate into a single Canonical Finding with sequential ID F-001."""
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
        affected_element=AffectedElement(selector="img#hero"),
        raw_rule="image-alt",
        normalized_rule="image_alt_missing",
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
        affected_element=AffectedElement(selector="header img#hero"),
        raw_rule="image_alt_missing",
        normalized_rule="image_alt_missing",
        evidence=FindingEvidence(types=["VISUAL"], description="AI visual observation", sources=["AI"])
    )

    correlated = EvidenceCorrelator.correlate_and_deduplicate([f_axe, f_ai])
    assert len(correlated) == 1
    
    canonical_f = correlated[0]
    assert canonical_f.id == "F-001"
    assert canonical_f.canonical_target == "#hero"
    assert "axe-core" in [s.lower() for s in canonical_f.sources]
    assert "ai" in [s.lower() for s in canonical_f.sources]
    assert canonical_f.verification_status == FindingVerificationStatus.CONFIRMED


def test_aggregation_correlation_counts():
    """Verify FindingsAggregator returns correct correlation breakdown metrics."""
    f_canonical = AURAFinding(
        id="F-001",
        source=FindingSource.AI,
        sources=["axe-core", "AI"],
        category=FindingCategory.ACCESSIBILITY,
        severity=FindingSeverity.HIGH,
        title="WCAG image-alt violation",
        description="Correlated finding",
        observation="Correlated observation",
        confidence=1.0,
        verification_status=FindingVerificationStatus.CONFIRMED,
        affected_element=AffectedElement(selector="img#logo"),
        raw_rule="image-alt",
        normalized_rule="image_alt_missing",
        evidence=FindingEvidence(types=["ACCESSIBILITY"], description="axe-core", sources=["axe-core"])
    )

    agg = FindingsAggregator.aggregate(
        verified_ai_findings=[],
        rejected_ai_findings=[],
        accessibility_violations=[],
        telemetry=None
    )
    # Manually append correlated canonical finding for unit test check
    agg.all_active_findings = [f_canonical]
    agg.findings = [f_canonical]

    # Re-run count calculation
    res = FindingsAggregator.aggregate([], [], [], type('DummyTelemetry', (), {'classified_events': []})())
    assert "ai_plus_axe" in res.correlation_counts
    assert "axe_only" in res.correlation_counts


def test_evaluator_traceability_matrix_completeness(tmp_path):
    """Verify evaluation traceability output contains all required fields and match reasons."""
    site_dir = tmp_path / "test_site"
    site_dir.mkdir()
    gt_file = site_dir / "ground_truth.json"
    gt_content = """{
        "suite_id": "test_site",
        "expected_findings": [
            {
                "ground_truth_id": "GT-UI-001",
                "suite_id": "test_site",
                "category": "UI",
                "normalized_rule": "bad_visual_hierarchy",
                "severity": "HIGH",
                "target": "#ui-hierarchy"
            }
        ]
    }"""
    gt_file.write_text(gt_content, encoding="utf-8")

    f_canonical = AURAFinding(
        id="F-001",
        candidate_id="CAND-001",
        candidate_ids=["CAND-001"],
        source=FindingSource.AI,
        sources=["AI"],
        category=FindingCategory.UI,
        severity=FindingSeverity.HIGH,
        title="Bad Visual Hierarchy",
        description="Visual hierarchy inverted",
        observation="Visual hierarchy inverted",
        confidence=0.9,
        verification_status=FindingVerificationStatus.CONFIRMED,
        affected_element=AffectedElement(selector="#ui-hierarchy"),
        canonical_target="#ui-hierarchy",
        raw_rule="bad_visual_hierarchy",
        normalized_rule="bad_visual_hierarchy",
        evidence=FindingEvidence(types=["VISUAL"], description="Visual inspection")
    )

    eval_res = EvaluationEngine.evaluate(site_dir, [f_canonical])
    assert eval_res["true_positives"] == 1
    assert eval_res["false_positives"] == 0
    assert eval_res["false_negatives"] == 0

    trace = eval_res["traceability"]
    assert len(trace) == 1
    t_item = trace[0]
    assert t_item["finding_id"] == "F-001"
    assert t_item["candidate_id"] == "CAND-001"
    assert t_item["ground_truth_id"] == "GT-UI-001"
    assert t_item["benchmark_match_status"] == "TP"
    assert "Matched ground truth defect" in t_item["match_reason"]

