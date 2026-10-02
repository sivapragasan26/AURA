"""
V0.4.4.5 regression tests: provider rate-limit handling, ground-truth single source, deterministic
one-to-one benchmark matching, FN/FP root causes, traceability, duplicate suppression, runtime
evidence semantics and dashboard consistency.

No test calls a real AI provider; Gemini is exercised through a mocked client.
"""
import re
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from aura.agent.gemini_provider import GeminiProvider, classify_gemini_error, extract_retry_delay_seconds
from aura.agent.diagnostics import AIAnalysisStatus
from aura.agent.analyzer_agent import AnalyzerAgent, classify_ai_contribution
from aura.agent.prompts import AURA_SYSTEM_PROMPT
from aura.analyzers.runtime_analyzer import RuntimeAnalyzer
from aura.evaluation.evaluator import EvaluationEngine, FN_ROOT_CAUSES, FP_ROOT_CAUSES
from aura.evaluation.registry import GroundTruthRegistry
from aura.evidence.correlator import EvidenceCorrelator
from aura.findings.aggregation import FindingsAggregator
from aura.findings.models import (
    AURAFinding, AffectedElement, FindingCategory, FindingEvidence, FindingSeverity, FindingSource,
    FindingVerificationStatus
)
from aura.models.findings import (
    AffectedElementDetail, CandidateFinding, ConsoleError, FindingEvidenceDetail, NetworkFailure, RuntimeTelemetry
)

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "test_lab"
SUITES = ["01_accessibility_suite", "02_ui_ux_suite", "03_navigation_interaction_suite",
          "04_responsive_runtime_suite", "05_mixed_realistic_suite"]

DAILY_429 = ("429 RESOURCE_EXHAUSTED. Rate limit exceeded for model gemini-3.6-flash "
             "(limit: 20 requests per day on Free Tier). consumer: api_key:REDACTED")


# ---------------------------------------------------------------- helpers

def finding(fid, category, rule, target=None, source=FindingSource.AI, status=FindingVerificationStatus.CONFIRMED,
            title=None, sources=None, candidate_ids=None, resolved=None, text=None):
    f = AURAFinding(
        id=fid, source=source, sources=sources if sources is not None else [source.value],
        category=category, severity=FindingSeverity.HIGH, title=title or rule,
        description=title or rule, observation=title or rule, confidence=0.9, verification_status=status,
        evidence=FindingEvidence(types=["DOM"]),
        affected_element=AffectedElement(selector=target, text=text) if target else None,
        raw_rule=rule, normalized_rule=rule, raw_target=target, canonical_target=target,
        candidate_ids=candidate_ids or [], candidate_id=(candidate_ids or [None])[0],
    )
    f.resolved_target = resolved
    return f


def candidate(cid, category, rule, target, title="AI candidate"):
    return CandidateFinding(
        id=cid, candidate_id=cid, category=category, title=title, description=title, observation=title,
        severity="high", confidence=0.9, affected_element=AffectedElementDetail(selector=target),
        evidence=FindingEvidenceDetail(type="visual", description="x"),
        rule_type=rule, raw_rule_type=rule, normalized_rule=rule,
    )


def write_gt(tmp_path, items):
    import json
    (tmp_path / "ground_truth.json").write_text(json.dumps({"suite_id": "t", "expected_findings": items}), encoding="utf-8")
    return tmp_path


def fn_cause(res, gt_id):
    return next(d["root_cause"] for d in res["fn_diagnostics"] if d["ground_truth_id"] == gt_id)


# ---------------------------------------------------------------- ground truth single source

@pytest.mark.parametrize("suite", SUITES)
def test_expected_defect_count_single_source(suite):
    """Launcher header, registry and evaluator all report the same count for each suite."""
    from test_lab.launcher import TestLabLauncher
    registry_cnt = len(GroundTruthRegistry.load_suite_ground_truth(LAB / suite)["expected_findings"])
    launcher_cnt = next(s["expected_count"] for s in TestLabLauncher.list_sites() if s["id"] == suite)
    eval_cnt = EvaluationEngine.evaluate(LAB / suite, [])["expected_count"]
    assert registry_cnt == launcher_cnt == eval_cnt


def test_mixed_suite_has_seven_expected_defects():
    assert GroundTruthRegistry.load_suite_ground_truth(LAB / "05_mixed_realistic_suite")["expected_defects_count"] == 7


def test_dashboard_has_no_hardcoded_expected_counts_or_duplicate_ai_status():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert not re.search(r"Expected Defects[^\n]*\b[67]\b\s*[\"']", src)
    assert src.count("AI interaction reasoning:") == 1
    assert "| Interaction reasoning:" not in src
    assert "AI Candidate: NOT GENERATED | Deterministic Evidence: AVAILABLE" not in src


# ---------------------------------------------------------------- metrics & integrity

def test_metric_formulas_are_computed():
    m = EvaluationEngine._metrics(tp=4, fp=7, fn=3)
    assert m["precision_formatted"] == "36.4%"
    assert m["recall_formatted"] == "57.1%"
    assert m["f1_formatted"] == "44.4%"
    assert m["precision"] == round(4 / 11, 4)


def test_integrity_pass_and_invariant():
    res = EvaluationEngine.evaluate(LAB / "05_mixed_realistic_suite", [
        finding("F-1", FindingCategory.ACCESSIBILITY, "image_alt_missing", "#mixed-missing-alt", source=FindingSource.AXE),
    ])
    assert res["integrity_status"] == "PASS"
    assert res["expected_count"] == res["true_positives"] + res["false_negatives"] == 7
    assert res["true_positives"] == 1 and res["false_negatives"] == 6


def test_integrity_detects_violations():
    rows = [
        {"benchmark_status": "TP", "ground_truth_id": "GT-1", "finding_id": "F-1"},
        {"benchmark_status": "TP", "ground_truth_id": "GT-1", "finding_id": "F-2"},
        {"benchmark_status": "FN", "ground_truth_id": "GT-1", "finding_id": "N/A"},
    ]
    notes = EvaluationEngine._check_integrity(expected=2, tp=2, fp=0, fn=1, eligible_cnt=2, traceability=rows, unique_gt_ids=["GT-1", "GT-2"])
    joined = " ".join(notes)
    assert "TP (2) + FN (1) != Expected (2)" in joined
    assert "more than one canonical finding" in joined
    assert "both TP and FN" in joined


# ---------------------------------------------------------------- one-to-one matching

def test_one_to_one_maximum_matching_does_not_starve(tmp_path):
    """GT-A can match F-1 or F-2; GT-B only F-1. Greedy could give F-1 to GT-A; maximum matching matches both."""
    site = write_gt(tmp_path, [
        {"ground_truth_id": "GT-A", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": ""},
        {"ground_truth_id": "GT-B", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"},
    ])
    res = EvaluationEngine.evaluate(site, [
        finding("F-1", FindingCategory.UI, "bad_visual_hierarchy", "#hero"),
        finding("F-2", FindingCategory.UI, "bad_visual_hierarchy", "#other"),
    ])
    assert res["true_positives"] == 2 and res["false_positives"] == 0
    tp = {r["ground_truth_id"]: r["finding_id"] for r in res["traceability"] if r["benchmark_status"] == "TP"}
    assert tp == {"GT-B": "F-1", "GT-A": "F-2"}


def test_assignment_prefers_exact_match_over_keyword_match(tmp_path):
    """F-1 is an exact rule+target match for GT-CTA and only a keyword/descendant match for GT-HIER."""
    site = write_gt(tmp_path, [
        {"ground_truth_id": "GT-HIER", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#section"},
        {"ground_truth_id": "GT-CTA", "category": "UI", "normalized_rule": "weak_primary_cta", "rule": "weak_cta", "target": "#cta"},
    ])
    resolved = {"method": "selector_unique", "match_count": 1, "elements": [{"tag": "button", "id": "cta", "id_chain": ["cta", "section"]}]}
    f1 = finding("F-1", FindingCategory.UI, "weak_cta", "#cta", title="weak cta breaks the visual hierarchy", resolved=resolved)
    res = EvaluationEngine.evaluate(site, [f1])
    tp = next(r for r in res["traceability"] if r["benchmark_status"] == "TP")
    assert tp["ground_truth_id"] == "GT-CTA" and tp["rule_match_tier"] == "exact_rule"


def test_weak_association_is_not_called_correlation_failure(tmp_path):
    """GT-HIER's only relation is F-1's weaker keyword match; F-1 is GT-CTA's exact match. No AI candidate
    addressed the hierarchy defect, so it is AI_NOT_GENERATED (with the weak relation noted)."""
    site = write_gt(tmp_path, [
        {"ground_truth_id": "GT-HIER", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#section", "allowed_sources": ["AI"]},
        {"ground_truth_id": "GT-CTA", "category": "UI", "normalized_rule": "weak_primary_cta", "target": "#cta", "allowed_sources": ["AI"]},
    ])
    resolved = {"method": "selector_unique", "match_count": 1, "elements": [{"tag": "button", "id": "cta", "id_chain": ["cta", "section"]}]}
    f1 = finding("F-1", FindingCategory.UI, "weak_primary_cta", "#cta", title="weak cta breaks the visual hierarchy",
                 resolved=resolved, candidate_ids=["AI-001"])
    raw = candidate("AI-001", "UI", "weak_primary_cta", "#cta", title="weak cta breaks the visual hierarchy")
    res = EvaluationEngine.evaluate(site, [f1], raw_ai_candidates=[raw])
    d = next(x for x in res["fn_diagnostics"] if x["ground_truth_id"] == "GT-HIER")
    assert d["root_cause"] == "AI_NOT_GENERATED"
    assert "F-1 relates only weakly" in d["reason"]


def test_hungarian_assignment_matches_exhaustive_optimum():
    import itertools, random
    rng = random.Random(7)
    for _ in range(200):
        n_gt, n_f = rng.randint(1, 5), rng.randint(1, 6)
        edges = {}
        for g in range(n_gt):
            for f in range(n_f):
                if rng.random() < 0.45:
                    edges.setdefault(g, []).append((rng.randint(2, 8), f))
        got = EvaluationEngine._max_one_to_one(n_gt, edges)
        w = {(g, f): s for g, es in edges.items() for s, f in es}
        assert len(set(got.values())) == len(got) and all((g, f) in w for g, f in got.items())
        best = (0, 0)
        for perm in itertools.permutations(list(range(n_f)) + [None] * n_gt, n_gt):
            pairs = [(g, f) for g, f in enumerate(perm) if f is not None and (g, f) in w]
            if len({f for _, f in pairs}) == len(pairs):
                best = max(best, (len(pairs), sum(w[p] for p in pairs)))
        assert (len(got), sum(w[(g, f)] for g, f in got.items())) == best


def test_registry_keeps_gt_rule_label_as_equivalent_identity(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "INTERACTION", "normalized_rule": "broken_form_submission",
                                "rule": "failed_form_interaction", "target": "#form"}])
    gt = GroundTruthRegistry.load_suite_ground_truth(site)["expected_findings"][0]
    assert gt["normalized_rule"] == "broken_form_submission" and gt["rule"] == "failed_form_interaction"
    res = EvaluationEngine.evaluate(site, [finding("F-1", FindingCategory.INTERACTION, "failed_form_interaction", "#form")])
    assert res["true_positives"] == 1


def test_one_finding_cannot_satisfy_two_gt_defects(tmp_path):
    site = write_gt(tmp_path, [
        {"ground_truth_id": "GT-A", "category": "UX", "normalized_rule": "confusing_form", "target": "#form"},
        {"ground_truth_id": "GT-B", "category": "UX", "normalized_rule": "confusing_form", "target": "#form"},
    ])
    res = EvaluationEngine.evaluate(site, [finding("F-1", FindingCategory.UX, "confusing_form", "#form")])
    assert res["true_positives"] == 1 and res["false_negatives"] == 1
    missed = next(d for d in res["fn_diagnostics"])
    assert missed["root_cause"] == "CORRELATION_FAILURE"


def test_duplicate_findings_second_is_fp_duplicate(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"}])
    res = EvaluationEngine.evaluate(site, [
        finding("F-1", FindingCategory.UI, "bad_visual_hierarchy", "#hero"),
        finding("F-2", FindingCategory.UI, "bad_visual_hierarchy", "#hero"),
    ])
    assert res["true_positives"] == 1 and res["false_positives"] == 1
    assert res["fp_diagnostics"][0]["root_cause"] == "DUPLICATE"


# ---------------------------------------------------------------- matching tiers

def test_dom_resolved_target_matches_descendant(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"}])
    resolved = {"method": "selector_unique", "match_count": 1, "elements": [{"tag": "button", "id": None, "id_chain": ["hero"]}]}
    res = EvaluationEngine.evaluate(site, [finding("F-1", FindingCategory.UI, "bad_visual_hierarchy", "button.big", resolved=resolved)])
    tp = next(r for r in res["traceability"] if r["benchmark_status"] == "TP")
    assert tp["target_match_tier"] == "dom_resolved"


def test_ambiguous_resolution_is_not_a_target_match(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "RESPONSIVENESS", "normalized_rule": "horizontal_overflow", "target": "#strip"}])
    # 'div' matched 25 elements but only 10 were returned: identity cannot be established
    resolved = {"method": "selector_ambiguous", "match_count": 25, "elements": [{"tag": "div", "id": None, "id_chain": ["strip"]}] * 10}
    res = EvaluationEngine.evaluate(site, [finding("F-1", FindingCategory.RESPONSIVENESS, "horizontal_overflow", "div", resolved=resolved)])
    assert res["true_positives"] == 0
    assert fn_cause(res, "GT-A") == "TARGET_MISMATCH"
    assert res["fp_diagnostics"][0]["root_cause"] == "TARGET_MISMATCH"


def test_keyword_rule_evidence_requires_specific_target(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"}])
    kw_title = "delete action gets primary visual prominence over save"
    with_target = EvaluationEngine.evaluate(site, [finding("F-1", FindingCategory.UI, kw_title, "#hero")])
    assert with_target["true_positives"] == 1
    tp = next(r for r in with_target["traceability"] if r["benchmark_status"] == "TP")
    assert tp["rule_match_tier"] == "keyword_evidence"
    without_target = EvaluationEngine.evaluate(site, [finding("F-1", FindingCategory.UI, kw_title, None)])
    assert without_target["true_positives"] == 0


def test_fixture_specific_words_are_not_rule_evidence(tmp_path):
    """'backup' names a test-page button, not a defect type; it must not satisfy interaction_failure."""
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "INTERACTION", "normalized_rule": "interaction_failure", "target": "#btn"}])
    res = EvaluationEngine.evaluate(site, [finding("F-1", FindingCategory.INTERACTION, "backup button looks disabled", "#btn")])
    assert res["true_positives"] == 0


def test_runtime_document_level_and_network_targets(tmp_path):
    site = write_gt(tmp_path, [
        {"ground_truth_id": "GT-R1", "category": "RUNTIME", "normalized_rule": "application_runtime_exception", "target": "window"},
        {"ground_truth_id": "GT-R2", "category": "RUNTIME", "normalized_rule": "application_network_failure", "target": "/api/v1/status"},
    ])
    res = EvaluationEngine.evaluate(site, [
        finding("F-1", FindingCategory.RUNTIME, "application_runtime_exception", "window", source=FindingSource.RUNTIME),
        finding("F-2", FindingCategory.RUNTIME, "application_network_failure", "http://127.0.0.1:8999/api/v1/status", source=FindingSource.RUNTIME),
    ])
    assert res["true_positives"] == 2 and res["false_negatives"] == 0


# ---------------------------------------------------------------- FN root causes

def test_fn_root_causes_from_run_data(tmp_path):
    site = write_gt(tmp_path, [
        {"ground_truth_id": "GT-TGT", "category": "RESPONSIVENESS", "normalized_rule": "horizontal_overflow", "target": "#strip", "allowed_sources": ["AI"]},
        {"ground_truth_id": "GT-RULE", "category": "RUNTIME", "normalized_rule": "application_runtime_exception", "target": "window", "allowed_sources": ["RUNTIME"]},
        {"ground_truth_id": "GT-UNC", "category": "UX", "normalized_rule": "confusing_form", "target": "#form", "allowed_sources": ["AI"]},
        {"ground_truth_id": "GT-SUP", "category": "UI", "normalized_rule": "weak_primary_cta", "target": "#cta", "allowed_sources": ["AI"]},
        {"ground_truth_id": "GT-NONE", "category": "UX", "normalized_rule": "broken_menu", "target": "#menu", "allowed_sources": ["AI"]},
        {"ground_truth_id": "GT-DET", "category": "RUNTIME", "normalized_rule": "application_network_failure", "target": "/api/x", "allowed_sources": ["RUNTIME"]},
    ])
    detected = [
        finding("F-1", FindingCategory.RESPONSIVENESS, "horizontal_overflow", "div.wrapper"),
        finding("F-2", FindingCategory.RUNTIME, "application_console_error", "window", source=FindingSource.RUNTIME),
        finding("F-3", FindingCategory.UX, "confusing_form", "#form", status=FindingVerificationStatus.UNCERTAIN),
    ]
    suppressed = [candidate("AI-SUP-001", "UI", "weak_primary_cta", "#cta")]
    res = EvaluationEngine.evaluate(site, detected, suppressed_ai_candidates=suppressed)

    assert fn_cause(res, "GT-TGT") == "TARGET_MISMATCH"
    assert fn_cause(res, "GT-RULE") == "RULE_MISMATCH"
    assert fn_cause(res, "GT-UNC") == "EVIDENCE_INSUFFICIENT"
    assert fn_cause(res, "GT-SUP") == "AI_GENERATED_NOT_MATCHED"
    assert fn_cause(res, "GT-NONE") == "AI_NOT_GENERATED"
    assert fn_cause(res, "GT-DET") == "EVIDENCE_INSUFFICIENT"
    assert all(d["root_cause"] in FN_ROOT_CAUSES for d in res["fn_diagnostics"])
    assert res["integrity_status"] == "PASS"


def test_fn_normalization_failure_when_category_changed(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "ACCESSIBILITY", "normalized_rule": "image-alt", "target": "#logo"}])
    raw = candidate("AI-001", "ACCESSIBILITY", "image-alt", "#logo")
    canon = finding("F-1", FindingCategory.UX, "image-alt", "#logo", candidate_ids=["AI-001"])
    res = EvaluationEngine.evaluate(site, [canon], raw_ai_candidates=[raw])
    assert fn_cause(res, "GT-A") == "NORMALIZATION_FAILURE"


def test_fn_interaction_note_reports_unexercised_target(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "INTERACTION", "normalized_rule": "interaction_failure",
                                "target": "#btn", "expected_evidence": ["interaction"], "allowed_sources": ["AI", "RUNTIME"]}])
    log = [{"target": "header", "status": "executed"}, {"target": "a", "status": "executed"}]
    res = EvaluationEngine.evaluate(site, [], interaction_log=log)
    d = res["fn_diagnostics"][0]
    assert d["root_cause"] == "AI_NOT_GENERATED"
    assert "never exercised" in d["reason"]


# ---------------------------------------------------------------- FP root causes

def test_fp_root_causes(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"}])
    res = EvaluationEngine.evaluate(site, [
        finding("F-AXE", FindingCategory.ACCESSIBILITY, "heading_order", "h3", source=FindingSource.AXE),
        finding("F-AI", FindingCategory.UX, "unexpected_behavior", "#elsewhere"),
        finding("F-LIK", FindingCategory.UX, "unexpected_behavior", "#elsewhere2", status=FindingVerificationStatus.LIKELY),
        finding("F-TGT", FindingCategory.UI, "bad_visual_hierarchy", "#wrong"),
    ])
    causes = {d["finding_id"]: d["root_cause"] for d in res["fp_diagnostics"]}
    assert causes == {
        "F-AXE": "LEGITIMATE_NON_GT_FINDING",
        "F-AI": "OUTSIDE_BENCHMARK_SCOPE",
        "F-LIK": "INSUFFICIENT_EVIDENCE",
        "F-TGT": "TARGET_MISMATCH",
    }
    assert all(c in FP_ROOT_CAUSES for c in causes.values())


# ---------------------------------------------------------------- traceability

def test_traceability_chain_from_actual_data(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"}])
    raw = candidate("AI-003", "UI", "visual_hierarchy", "#hero")
    canon = finding("F-008", FindingCategory.UI, "bad_visual_hierarchy", "#hero", candidate_ids=["AI-003"])
    res = EvaluationEngine.evaluate(site, [canon], raw_ai_candidates=[raw])
    row = next(r for r in res["traceability"] if r["benchmark_status"] == "TP")
    assert row["chain"].startswith("GT-A → AI-003 (AI rule: visual_hierarchy")
    assert "→ F-008 →" in row["chain"] and row["chain"].endswith("→ TP")


# ---------------------------------------------------------------- provider failure / 429

def test_daily_quota_429_is_not_retryable_even_if_message_mentions_api_key():
    cat, code, retryable = classify_gemini_error(Exception(DAILY_429))
    assert (cat, code, retryable) == ("RATE_LIMITED", 429, False)


def test_structured_error_code_is_preferred():
    err = Exception("something went wrong")
    err.code = 429
    err.details = {"error": {"details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}
    assert classify_gemini_error(err) == ("RATE_LIMITED", 429, False)
    err.code = 400
    assert classify_gemini_error(err) == ("BAD_REQUEST", 400, False)


def test_retry_delay_parsing():
    assert extract_retry_delay_seconds(Exception("... 'retryDelay': '40s' ...")) == 40.0
    assert extract_retry_delay_seconds(Exception("Please retry in 12.5s.")) == 12.5
    assert extract_retry_delay_seconds(Exception("no hint")) is None


def test_daily_quota_makes_one_request_and_no_model_fallback():
    provider = GeminiProvider(api_key="AIzaSyTestFakeKey12345", model="gemini-3.6-flash")
    client = MagicMock()
    client.interactions.create.side_effect = Exception(DAILY_429)
    with patch("google.genai.Client", return_value=client), patch("time.sleep") as sleep:
        with pytest.raises(RuntimeError):
            provider.analyze("prompt")
    assert client.interactions.create.call_count == 1
    sleep.assert_not_called()
    meta = provider.last_execution_metadata
    assert meta["status"] == "RATE_LIMITED" and meta["quota_scope"] == "DAILY"
    assert meta["fallback_used"] is False and meta["actual_model"] == "gemini-3.6-flash"


def test_short_term_429_retries_once_then_stops():
    provider = GeminiProvider(api_key="AIzaSyTestFakeKey12345", model="gemini-3.6-flash")
    client = MagicMock()
    client.interactions.create.side_effect = Exception("429 RESOURCE_EXHAUSTED: per-minute limit. Please retry in 2s.")
    with patch("google.genai.Client", return_value=client), patch("time.sleep") as sleep:
        with pytest.raises(RuntimeError):
            provider.analyze("prompt")
    assert client.interactions.create.call_count == 2
    sleep.assert_called_once_with(2.0)
    meta = provider.last_execution_metadata
    assert meta["status"] == "RATE_LIMITED" and meta["quota_scope"] == "SHORT_TERM"
    assert meta["attempt_count"] == 2 and meta["retry_count"] == 1 and meta["fallback_used"] is False


def test_400_is_not_retried():
    provider = GeminiProvider(api_key="AIzaSyTestFakeKey12345", model="gemini-3.6-flash")
    client = MagicMock()
    client.interactions.create.side_effect = Exception("400 INVALID_ARGUMENT: bad image")
    with patch("google.genai.Client", return_value=client), patch("time.sleep"):
        with pytest.raises(RuntimeError):
            provider.analyze("prompt")
    assert client.interactions.create.call_count == 1


def test_analyzer_reports_rate_limited_without_fake_candidates():
    provider = GeminiProvider(api_key="AIzaSyTestFakeKey12345", model="gemini-3.6-flash")
    client = MagicMock()
    client.interactions.create.side_effect = Exception(DAILY_429)
    telemetry = RuntimeTelemetry(url="http://127.0.0.1:8999/x/", title="t")
    with patch("google.genai.Client", return_value=client), patch("time.sleep"):
        res = AnalyzerAgent(provider=provider).analyze(telemetry=telemetry, dom_summary={}, accessibility_violations=[])
    diag = res["diagnostics"]
    assert res["issues"] == []
    assert diag.status == AIAnalysisStatus.RATE_LIMITED
    assert diag.failure_category == "RATE_LIMITED" and diag.http_status == 429
    assert diag.ai_request_succeeded is False
    assert "daily quota" in diag.ai_failure_reason
    assert "AIzaSyTestFakeKey12345" not in diag.ai_failure_reason


def test_provider_failure_benchmark_is_not_evaluable_with_separate_deterministic_result():
    detected = [finding("F-1", FindingCategory.ACCESSIBILITY, "image_alt_missing", "#mixed-missing-alt",
                        source=FindingSource.AXE, sources=["axe-core"])]
    res = EvaluationEngine.evaluate(LAB / "05_mixed_realistic_suite", detected, provider_failed=True, ai_status="RATE_LIMITED")
    assert res["benchmark_ai_status"] == "NOT_EVALUABLE"
    assert res["ai_status"] == "RATE_LIMITED"
    assert res["expected_count"] == 7
    assert res["true_positives"] is None and res["false_positives"] is None and res["false_negatives"] is None
    assert res["integrity_status"] == "NOT_EVALUABLE"
    assert res["fn_diagnostics"] == []
    det = res["deterministic_only"]
    # scope: GT defects whose allowed sources include AXE_CORE or RUNTIME (MIX-001, MIX-006, MIX-007)
    assert det["scope_ground_truth_ids"] == ["GT-MIX-001", "GT-MIX-006", "GT-MIX-007"]
    assert det["true_positives"] == 1 and det["false_negatives"] == 2
    assert det["integrity_status"] == "PASS"
    assert all(d["root_cause"] != "AI_NOT_GENERATED" for d in det["fn_diagnostics"])


def test_suite_aggregation_excludes_not_evaluable_suites():
    pre = {s: EvaluationEngine.evaluate(LAB / s, [], provider_failed=True) for s in SUITES}
    sm = EvaluationEngine.evaluate_suite(LAB, {}, precomputed=pre)
    assert sm["not_evaluable_suites"] == SUITES
    assert sm["total_tp"] == 0 and sm["total_expected"] == 0


# ---------------------------------------------------------------- AI contribution / duplicate suppression

def test_duplicate_requires_an_actual_deterministic_observation():
    # horizontal_overflow has no deterministic producer in this pipeline -> never a duplicate
    assert classify_ai_contribution("horizontal_overflow", deterministic_rules=set())[0] == "NOVEL_AI_INSIGHT"
    # image-alt IS a duplicate when axe-core reported it, and not when it did not
    assert classify_ai_contribution("image-alt", deterministic_rules={"image_alt_missing"})[0] == "DETERMINISTIC_DUPLICATE"
    assert classify_ai_contribution("image-alt", deterministic_rules=set())[0] == "NOVEL_AI_INSIGHT"
    # free-text rule: keyword family must also have been observed
    assert classify_ai_contribution("low text contrast ratio", deterministic_rules={"color_contrast"})[0] == "DETERMINISTIC_DUPLICATE"
    assert classify_ai_contribution("low text contrast ratio", deterministic_rules={"image_alt_missing"})[0] == "NOVEL_AI_INSIGHT"


def test_contribution_type_is_carried_into_traceability(tmp_path):
    site = write_gt(tmp_path, [{"ground_truth_id": "GT-A", "category": "UI", "normalized_rule": "bad_visual_hierarchy", "target": "#hero"}])
    f = finding("F-1", FindingCategory.UI, "bad_visual_hierarchy", "#hero")
    f.ai_contribution_type = "NOVEL_AI_INSIGHT"
    row = EvaluationEngine.evaluate(site, [f])["traceability"][0]
    assert row["ai_contribution_type"] == "NOVEL_AI_INSIGHT"


def test_prompt_requests_rule_type_and_substitutes_limit():
    prompt = AURA_SYSTEM_PROMPT.format(max_findings=7)
    assert "at most 7" in prompt and "{max_findings}" not in prompt
    assert '"rule_type"' in prompt


# ---------------------------------------------------------------- runtime evidence & verification summary

def test_console_ownership_uses_location_not_message_words():
    analyzer = RuntimeAnalyzer()
    t = RuntimeTelemetry(url="http://127.0.0.1:8999/app/", console_errors=[
        ConsoleError(type="error", text="Runtime Telemetry Error: sync agent lost heartbeat", location="http://127.0.0.1:8999/app/:52"),
        ConsoleError(type="error", text="Something failed", location="https://cdn.thirdparty.io/lib.js:1"),
    ])
    events = analyzer.classify_telemetry(t)
    assert events[0].category.value == "APPLICATION_ERROR" and events[0].ownership == "TARGET_APPLICATION"
    assert events[1].category.value == "THIRD_PARTY_FAILURE"


def test_runtime_findings_rule_and_target_per_event_type():
    t = RuntimeTelemetry(url="http://127.0.0.1:8999/app/", console_errors=[
        ConsoleError(type="exception", text="Uncaught Error: boom"),
        ConsoleError(type="error", text="console failure A"),
        ConsoleError(type="error", text="console failure B"),
    ], network_failures=[NetworkFailure(url="http://127.0.0.1:8999/api/v1/x", status=500)])
    RuntimeAnalyzer().classify_telemetry(t)
    agg = FindingsAggregator.aggregate([], [], [], t)
    got = sorted((f.normalized_rule, f.canonical_target) for f in agg.findings)
    assert got == [
        ("application_console_error", "window"),
        ("application_console_error", "window"),  # two distinct errors stay two canonical findings
        ("application_network_failure", "http://127.0.0.1:8999/api/v1/x"),
        ("application_runtime_exception", "window"),
    ]


def test_verification_summary_counts_observations_vs_canonical():
    """Identical runtime observations merge into one canonical finding; the summary reports both counts."""
    t = RuntimeTelemetry(url="http://127.0.0.1:8999/app/", console_errors=[
        ConsoleError(type="error", text="same failure"), ConsoleError(type="error", text="same failure"),
    ])
    RuntimeAnalyzer().classify_telemetry(t)
    agg = FindingsAggregator.aggregate([], [], [], t)
    assert len(agg.findings) == 1
    assert agg.source_counts["runtime"] == 2


def test_runtime_telemetry_does_not_leak_between_audits():
    """A reused engine/browser manager must start each audit with empty runtime telemetry."""
    from aura.browser.browser_manager import BrowserManager
    manager = BrowserManager(headless=True)
    manager.start(viewport={"width": 800, "height": 600})
    manager.page.evaluate("console.error('error from the first audited page')")
    manager.page.wait_for_timeout(100)
    assert len(manager.collector.console_errors) == 1
    manager.stop()

    manager.start(viewport={"width": 800, "height": 600})
    assert manager.collector.console_errors == []
    manager.stop()


# ---------------------------------------------------------------- GT isolation in DOM evidence

def test_dom_evidence_excludes_embedded_ground_truth_script():
    from playwright.sync_api import sync_playwright
    from aura.analyzers.dom_analyzer import DOMAnalyzer
    html = ('<html><body><script type="application/json" id="aura-ground-truth">{"expected_findings": []}</script>'
            '<button id="go">Go</button></body></html>')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        summary = DOMAnalyzer().analyze(page)
        browser.close()
    ids = [e.get("id") for e in summary["all_elements"]]
    assert "go" in ids and "aura-ground-truth" not in ids
