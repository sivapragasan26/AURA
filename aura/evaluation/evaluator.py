import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from urllib.parse import urlparse
from aura.findings.models import AURAFinding, FindingSource
from aura.evaluation.registry import GroundTruthRegistry
from aura.utils.logger import logger


# Machine-readable root causes (see EvaluationEngine._classify_fn / _classify_fp)
FN_ROOT_CAUSES = (
    "AI_NOT_GENERATED", "AI_GENERATED_NOT_MATCHED", "CORRELATION_FAILURE", "NORMALIZATION_FAILURE",
    "EVIDENCE_INSUFFICIENT", "TARGET_MISMATCH", "CATEGORY_MISMATCH", "RULE_MISMATCH", "OTHER"
)
FP_ROOT_CAUSES = (
    "OUTSIDE_BENCHMARK_SCOPE", "CORRELATION_FAILURE", "TARGET_MISMATCH", "CATEGORY_MISMATCH",
    "RULE_MISMATCH", "DUPLICATE", "INSUFFICIENT_EVIDENCE", "LEGITIMATE_NON_GT_FINDING", "OTHER"
)


class EvaluationEngine:
    """
    Evaluates detected final canonical findings against the suite's ground truth.

    Ground truth is strictly isolated: it is only read here, downstream of analysis and verification,
    and is never exposed to AI prompts or the verifier.

    Guarantees:
    1. Single authoritative ground truth source (GroundTruthRegistry).
    2. Only CONFIRMED and LIKELY canonical findings are benchmark eligible.
    3. Deterministic, explainable matching. A match needs category compatibility, a rule match and a
       target match; each match records which tier satisfied the rule and the target.
    4. Strict one-to-one matching (maximum cardinality): a GT defect matches at most one canonical
       finding and a canonical finding matches at most one GT defect.
    5. Every FN and FP gets a root cause derived from the actual findings/candidates of the run.
    6. Integrity invariants (Expected == TP + FN, one-to-one, ...) are checked; any failure => FAIL.
    7. Provider failure => NOT_EVALUABLE: TP/FP/FN/P/R/F1 are not computed. A separately labelled
       deterministic-only evaluation is reported instead.
    """

    # Controlled vocabulary per GT rule. Identifier-style aliases (no spaces) are rule identifiers
    # ("rule_alias" tier); phrases are searched as whole words in the finding text ("keyword_evidence"
    # tier, only accepted together with a specific target match). Entries must describe defect types,
    # never the content of a particular test page.
    DEFECT_TYPE_ALIASES = {
        "image-alt": ["image-alt", "missing_alt", "alt_text", "image_alt", "image_alt_missing", "missing alt", "alt text"],
        "button-name": ["button-name", "bad_button_name", "unlabelled_button", "button_name", "button label", "unlabeled button"],
        "color-contrast": ["color-contrast", "bad_contrast", "contrast", "color_contrast", "color contrast"],
        "bad_links": ["bad_links", "broken_links", "javascript:void", "empty_href", "nonfunctional_navigation", "bad navigation", "broken link"],
        "landmark-one-main": ["landmark-one-main", "bad_landmarks", "missing_landmark", "missing_main_landmark", "main landmark"],
        "label": ["label", "bad_form_labels", "missing_label", "form_labels", "form label"],
        "navigation_layout": ["navigation_layout", "bad_navigation", "overlapping navigation", "navigation_link", "navigation", "bad_nav", "navigation items", "overlap"],
        "visual_hierarchy": ["visual_hierarchy", "bad_visual_hierarchy", "cta prominence", "visual prominence", "action hierarchy", "inverted_hierarchy", "visual hierarchy", "inverted visual hierarchy"],
        "bad_navigation": ["bad_navigation", "bad_nav", "navigation_layout", "overlapping navigation", "navigation_link", "nonfunctional_navigation", "broken_navigation_destination", "navigation items", "navigation", "overlap", "visually overlap"],
        "bad_visual_hierarchy": ["bad_visual_hierarchy", "visual_hierarchy", "cta prominence", "visual prominence", "action hierarchy", "inverted_hierarchy", "misleading_visual_emphasis", "visual hierarchy", "inverted visual hierarchy", "primary action"],
        "poor_information_density": ["poor_information_density", "information density", "clutter", "whitespace", "excessive_information_density"],
        "weak_cta": ["weak_cta", "weak_primary_cta", "cta prominence", "button prominence", "cta", "competing_cta"],
        "inconsistent_components": ["inconsistent_components", "visual consistency", "button style", "inconsistent", "inconsistent_component_styling"],
        "unclear_error_message": ["unclear_error_message", "error message", "unclear error", "error banner", "poor_error_recovery"],
        "weak_primary_cta": ["weak_primary_cta", "weak_cta", "insufficient_cta_prominence", "button prominence", "competing_cta"],
        "inconsistent_component_styling": ["inconsistent_component_styling", "inconsistent_components", "visual consistency", "button style"],
        "poor_error_recovery": ["poor_error_recovery", "unclear_error_message", "error message", "unclear error", "error banner"],
        "broken_menu": ["broken_menu", "dropdown menu", "menu"],
        "dead_button": ["dead_button", "unresponsive button", "dead action", "non_responsive_control"],
        "misleading_cta": ["misleading_cta", "misleading link", "destination"],
        "failed_form_interaction": ["failed_form_interaction", "form submit", "form feedback", "broken_form_submission"],
        "mobile_layout_break": ["mobile_layout_break", "layout break", "table overflow", "horizontal_overflow", "overflow"],
        "non_responsive_control": ["non_responsive_control", "dead_button", "unresponsive button", "dead action"],
        "confusing_form": ["confusing_form", "form_usability", "reset button", "submit form reset", "form reset", "ambiguous_label", "excessive_form_complexity", "unclear_instruction", "form input", "button types"],
        "interaction_failure": ["interaction_failure", "click_failure", "unhandled js exception", "button exception", "click_without_feedback", "incorrect_state_transition", "broken_toggle", "uncaught typeerror"],
        "false_affordance": ["false_affordance", "fake_button", "non_actionable_control", "unclear_interactive_affordance"],
        "horizontal_overflow": ["horizontal_overflow", "mobile_layout", "mobile overflow", "horizontal scroll", "clipped layout", "excessive_horizontal_scrolling", "mobile_layout_break", "overflow", "overflows", "viewport boundary"],
        "clipped_content": ["clipped_content", "clipped", "overflow hidden"],
        "offscreen_control": ["offscreen_control", "offscreen", "outside viewport"],
        "overlapping_elements": ["overlapping_elements", "overlapping", "element overlap"],
        "application_console_error": ["application_console_error", "application_error", "console error", "initialization error", "console_error"],
        "application_runtime_exception": ["application_runtime_exception", "uncaught_exception", "runtime error", "exception", "runtime_exception", "uncaught typeerror"],
        "application_network_failure": ["application_network_failure", "network_failure", "http_failure", "500", "fetch failure", "api_failure"],
        "form_usability": ["form_usability", "confusing_form", "reset button", "submit form reset", "form reset", "ambiguous_label", "excessive_form_complexity", "form input"]
    }

    # GT category -> finding categories that may represent the same defect
    CATEGORY_COMPATIBILITY = {
        "ACCESSIBILITY": {"ACCESSIBILITY"},
        "UI": {"UI", "UX", "RESPONSIVENESS", "NAVIGATION", "FORM"},
        "UX": {"UX", "UI", "NAVIGATION", "FORM", "INTERACTION"},
        "NAVIGATION": {"NAVIGATION", "UX", "UI"},
        "FORM": {"FORM", "UX", "UI"},
        "INTERACTION": {"INTERACTION", "UX", "UI", "RUNTIME"},
        "RESPONSIVENESS": {"RESPONSIVENESS", "RESPONSIVE", "UI", "UX"},
        "RESPONSIVE": {"RESPONSIVENESS", "RESPONSIVE", "UI", "UX"},
        "RUNTIME": {"RUNTIME"},
    }

    DOCUMENT_LEVEL_TARGETS = {"window", "document", "body", "html", "window / document", "window / network"}

    # Higher rank = stronger evidence of identity
    RULE_TIER_RANK = {"exact_rule": 4, "normalized_rule": 3, "rule_alias": 2, "keyword_evidence": 1}
    TARGET_TIER_RANK = {
        "exact_target": 4, "selector_ancestor": 3, "dom_resolved": 3, "document_level": 3, "network_url": 3,
        "gt_target_unspecified": 1, "finding_target_unspecified": 1
    }
    STRONG_RULE_TIERS = {"exact_rule", "normalized_rule", "rule_alias"}
    STRONG_TARGET_TIERS = {"exact_target", "selector_ancestor", "dom_resolved", "document_level", "network_url"}

    ELIGIBLE_STATUSES = ("confirmed", "likely")
    DETERMINISTIC_SOURCES = {"axe-core", "axe", "runtime", "interaction"}
    DETERMINISTIC_GT_SOURCES = {"AXE_CORE", "RUNTIME"}

    @classmethod
    def load_ground_truth(cls, site_dir: Path) -> Dict[str, Any]:
        """Loads authoritative ground truth specification using GroundTruthRegistry."""
        return GroundTruthRegistry.load_suite_ground_truth(site_dir)

    # ------------------------------------------------------------------
    # Finding views: AURAFinding (canonical) and CandidateFinding (raw AI) share one comparable shape
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_rule(rule: Any) -> str:
        return str(rule or "").strip().lower().replace("-", "_")

    @staticmethod
    def _enum_val(v: Any) -> str:
        return str(v.value if hasattr(v, "value") else (v or ""))

    @classmethod
    def _view(cls, obj: Any) -> Dict[str, Any]:
        """Normalizes an AURAFinding or CandidateFinding into the fields the matcher compares."""
        ae = getattr(obj, "affected_element", None)
        if isinstance(ae, dict):
            selector, text = ae.get("selector") or "", ae.get("text") or ""
        elif isinstance(ae, str):
            selector, text = ae, ""
        elif ae is not None:
            selector, text = getattr(ae, "selector", "") or "", getattr(ae, "text", "") or ""
        else:
            selector, text = "", ""

        is_canonical = isinstance(obj, AURAFinding)
        if is_canonical:
            raw_rule = obj.raw_rule
            raw_target = obj.raw_target or selector
            canonical_target = obj.canonical_target or ""
            resolved = obj.resolved_target
            sources = [str(s) for s in (obj.sources or [])] or [cls._enum_val(obj.source)]
            status = cls._enum_val(obj.verification_status).lower()
            cand_ids = list(obj.candidate_ids or ([obj.candidate_id] if obj.candidate_id else []))
            fid = obj.id
        else:
            from aura.evidence.correlator import normalize_target_selector
            raw_rule = getattr(obj, "raw_rule_type", None) or getattr(obj, "rule_type", None)
            raw_target = selector
            canonical_target = normalize_target_selector(selector) if selector else ""
            resolved = None
            sources = ["AI"]
            status = getattr(obj, "status", None) or "candidate"
            cand_ids = [getattr(obj, "candidate_id", None) or getattr(obj, "id", "")]
            fid = cand_ids[0]

        return {
            "id": fid,
            "candidate_ids": [c for c in cand_ids if c],
            "category": cls._enum_val(getattr(obj, "category", "")).upper(),
            "normalized_rule": getattr(obj, "normalized_rule", None) or "",
            "raw_rule": raw_rule or "",
            "title": getattr(obj, "title", "") or "",
            "text": " ".join(str(getattr(obj, k, "") or "") for k in ("title", "description", "observation")).lower(),
            "raw_target": (raw_target or "").strip().lower(),
            "canonical_target": (canonical_target or "").strip().lower(),
            "element_text": text,
            "resolved": resolved,
            "sources": sources,
            "status": status,
            "is_canonical": is_canonical,
        }

    # ------------------------------------------------------------------
    # Match components
    # ------------------------------------------------------------------

    @classmethod
    def _gt_rules(cls, exp: Dict[str, Any]) -> List[str]:
        rules = [exp.get("normalized_rule"), exp.get("rule"), exp.get("rule_type"), exp.get("type")]
        return [str(r).strip().lower() for r in rules if r]

    @classmethod
    def _category_ok(cls, exp: Dict[str, Any], v: Dict[str, Any]) -> bool:
        exp_cat = str(exp.get("category") or "").upper().strip()
        if not exp_cat:
            return True
        return v["category"] in cls.CATEGORY_COMPATIBILITY.get(exp_cat, {exp_cat})

    @classmethod
    def _rule_tier(cls, exp: Dict[str, Any], v: Dict[str, Any]) -> Optional[str]:
        from aura.agent.analyzer_agent import normalize_rule_type

        gt_raw = cls._gt_rules(exp)
        if not gt_raw:
            return "exact_rule"
        gt_rules = {cls._norm_rule(r) for r in gt_raw}
        f_rules = {cls._norm_rule(r) for r in (v["normalized_rule"], v["raw_rule"]) if r}

        if gt_rules & f_rules:
            return "exact_rule"
        if {normalize_rule_type(r) for r in gt_rules} & {normalize_rule_type(r) for r in f_rules}:
            return "normalized_rule"

        aliases: List[str] = []
        for r in gt_raw:
            aliases.extend(cls.DEFECT_TYPE_ALIASES.get(r, []))
            aliases.extend(cls.DEFECT_TYPE_ALIASES.get(r.replace("_", "-"), []))
            aliases.extend(cls.DEFECT_TYPE_ALIASES.get(r.replace("-", "_"), []))

        alias_ids = {cls._norm_rule(a) for a in aliases if " " not in a}
        if f_rules & (alias_ids | {normalize_rule_type(a) for a in alias_ids}):
            return "rule_alias"

        text = f"{v['text']} {' '.join(r.replace('_', ' ') for r in f_rules)}"
        phrases = {a.lower().replace("_", " ") for a in aliases} | {r.replace("_", " ").replace("-", " ") for r in gt_raw}
        for phrase in sorted(phrases):
            if len(phrase) >= 3 and re.search(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", text):
                return "keyword_evidence"
        return None

    @classmethod
    def _target_tier(cls, exp: Dict[str, Any], v: Dict[str, Any]) -> Optional[str]:
        gt_t = str(exp.get("target") or exp.get("selector") or "").strip().lower()
        f_targets = {t for t in (v["raw_target"], v["canonical_target"]) if t and t != "element"}

        if not gt_t:
            return "gt_target_unspecified"
        if gt_t in f_targets:
            return "exact_target"
        if gt_t in cls.DOCUMENT_LEVEL_TARGETS and f_targets & cls.DOCUMENT_LEVEL_TARGETS:
            return "document_level"

        if gt_t.startswith("#"):
            gid = gt_t[1:]
            # The finding's own selector places it inside the GT element (e.g. '#gt-id > h3')
            id_token = re.compile(r"#" + re.escape(gid) + r"(?![\w-])")
            if any(id_token.search(t) for t in f_targets):
                return "selector_ancestor"
            # GT-blind DOM resolution: every element the finding target resolved to is the GT element
            # or one of its descendants
            res = v.get("resolved") or {}
            elements = res.get("elements") or []
            if elements and res.get("match_count") == len(elements) and all(
                gid in [str(i).lower() for i in (e.get("id_chain") or [])] for e in elements
            ):
                return "dom_resolved"

        if gt_t.startswith("/") or "://" in gt_t:
            gt_path = urlparse(gt_t).path or gt_t
            for t in f_targets:
                if "://" in t or t.startswith("/"):
                    f_path = urlparse(t).path or t
                    if f_path == gt_path or f_path.endswith(gt_path):
                        return "network_url"

        if not f_targets:
            return "finding_target_unspecified"
        return None

    @classmethod
    def _components(cls, exp: Dict[str, Any], v: Dict[str, Any]) -> Dict[str, Any]:
        cat_ok = cls._category_ok(exp, v)
        rule_tier = cls._rule_tier(exp, v)
        target_tier = cls._target_tier(exp, v)
        full = bool(
            cat_ok and rule_tier and target_tier
            # weak evidence on one axis must be backed by strong evidence on the other
            and (rule_tier in cls.STRONG_RULE_TIERS or target_tier in cls.STRONG_TARGET_TIERS)
        )
        score = (cls.RULE_TIER_RANK.get(rule_tier, 0) + cls.TARGET_TIER_RANK.get(target_tier, 0)) if full else 0
        return {"category_ok": cat_ok, "rule_tier": rule_tier, "target_tier": target_tier, "full": full, "score": score}

    @staticmethod
    def _missing_axis(comp: Dict[str, Any]) -> Optional[str]:
        """For a near-miss (exactly one failing axis) returns the root cause naming that axis."""
        cat_ok = comp["category_ok"]
        rule_ok = comp["rule_tier"] is not None
        target_ok = comp["target_tier"] is not None
        if comp["full"]:
            return None
        if cat_ok and rule_ok and target_ok:
            # both axes only weakly supported (keyword rule + unspecified target)
            return "TARGET_MISMATCH"
        if sum([cat_ok, rule_ok, target_ok]) != 2:
            return None
        if not target_ok:
            return "TARGET_MISMATCH"
        if not rule_ok:
            return "RULE_MISMATCH"
        return "CATEGORY_MISMATCH"

    @classmethod
    def _is_defect_match(cls, exp: Dict[str, Any], finding: Any) -> Tuple[bool, float, str]:
        """Returns (is_match, match_score, reason) for one GT defect and one finding."""
        comp = cls._components(exp, cls._view(finding))
        if comp["full"]:
            return True, float(comp["score"]), (
                f"Matched rule '{cls._gt_rules(exp)[0] if cls._gt_rules(exp) else 'any'}' "
                f"[rule: {comp['rule_tier']}, target: {comp['target_tier']}]"
            )
        axis = cls._missing_axis(comp) or "NO_RELATION"
        return False, 0.0, f"{axis} (category_ok={comp['category_ok']}, rule={comp['rule_tier']}, target={comp['target_tier']})"

    # ------------------------------------------------------------------
    # One-to-one assignment
    # ------------------------------------------------------------------

    @staticmethod
    def _max_one_to_one(n_gt: int, edges: Dict[int, List[Tuple[int, int]]]) -> Dict[int, int]:
        """
        One-to-one assignment of GT defects to findings. edges[gt] = [(score, f_idx), ...].
        Objective (lexicographic): 1) maximum number of matched GT defects, 2) maximum total match
        strength, so an exact rule+target match is never given up for a weaker keyword match.
        Solved exactly with the Hungarian algorithm; deterministic for identical inputs.
        """
        cols = sorted({f for es in edges.values() for _, f in es})
        if n_gt == 0 or not cols:
            return {}
        n, m = n_gt, max(len(cols), n_gt)  # pad columns so rows <= columns
        col_pos = {f: j for j, f in enumerate(cols)}
        big = 1 + sum(max((s for s, _ in es), default=0) for es in edges.values())
        weight = [[0] * m for _ in range(n)]
        for g, es in edges.items():
            for s, f in es:
                weight[g][col_pos[f]] = max(weight[g][col_pos[f]], big + s)

        # Hungarian algorithm (minimizing cost = -weight), 1-indexed potentials formulation
        INF = float("inf")
        u, v = [0.0] * (n + 1), [0.0] * (m + 1)
        p, way = [0] * (m + 1), [0] * (m + 1)
        for i in range(1, n + 1):
            p[0], j0 = i, 0
            minv, used = [INF] * (m + 1), [False] * (m + 1)
            while True:
                used[j0] = True
                i0, delta, j1 = p[j0], INF, 0
                for j in range(1, m + 1):
                    if not used[j]:
                        cur = -weight[i0 - 1][j - 1] - u[i0] - v[j]
                        if cur < minv[j]:
                            minv[j], way[j] = cur, j0
                        if minv[j] < delta:
                            delta, j1 = minv[j], j
                for j in range(m + 1):
                    if used[j]:
                        u[p[j]] += delta
                        v[j] -= delta
                    else:
                        minv[j] -= delta
                j0 = j1
                if p[j0] == 0:
                    break
            while j0:
                j1 = way[j0]
                p[j0] = p[j1]
                j0 = j1

        assignment = {}
        for j in range(1, m + 1):
            g = p[j] - 1
            if g >= 0 and j - 1 < len(cols) and weight[g][j - 1] > 0:  # drop padding / non-edges
                assignment[g] = cols[j - 1]
        return assignment

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    @staticmethod
    def _metrics(tp: int, fp: int, fn: int) -> Dict[str, Any]:
        if (tp + fp) == 0:
            precision, precision_fmt = None, "N/A"
            precision_note = "Precision is undefined because AURA produced no positive predictions."
        else:
            precision = round(tp / (tp + fp), 4)
            precision_fmt, precision_note = f"{precision * 100:.1f}%", None
        recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 1.0
        if precision is None or (precision + recall) == 0:
            f1 = 0.0
        else:
            f1 = round(2 * precision * recall / (precision + recall), 4)
        return {
            "precision": precision, "precision_formatted": precision_fmt, "precision_note": precision_note,
            "recall": recall, "recall_formatted": f"{recall * 100:.1f}%",
            "f1_score": f1, "f1_formatted": f"{f1 * 100:.1f}%",
        }

    @classmethod
    def evaluate(
        cls,
        site_dir: Path,
        detected_findings: List[AURAFinding],
        provider_failed: bool = False,
        raw_ai_candidates: Optional[List[Any]] = None,
        suppressed_ai_candidates: Optional[List[Any]] = None,
        rejected_findings: Optional[List[AURAFinding]] = None,
        interaction_log: Optional[List[Dict[str, Any]]] = None,
        ai_status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates detected canonical findings against suite ground truth: TP/FP/FN, Precision, Recall, F1,
        integrity invariants, per-item root causes and GT-to-finding traceability.
        """
        site_dir = Path(site_dir)
        ground_truth = cls.load_ground_truth(site_dir)
        expected_list = ground_truth.get("expected_findings", [])
        base = {
            "site_id": ground_truth.get("suite_id", site_dir.name),
            "site_name": ground_truth.get("name", site_dir.name),
            "ground_truth_available": True,
            "expected_count": len(expected_list),
            "raw_detected_count": len(detected_findings),
        }

        if provider_failed:
            return {**base, **cls._not_evaluable(ground_truth, expected_list, detected_findings, rejected_findings,
                                                  interaction_log, ai_status)}

        core = cls._evaluate_core(
            expected_list, detected_findings,
            raw_ai_candidates=raw_ai_candidates, suppressed_ai_candidates=suppressed_ai_candidates,
            rejected_findings=rejected_findings, interaction_log=interaction_log, ai_available=True,
            unique_gt_ids=ground_truth.get("unique_ground_truth_ids", [])
        )
        return {**base, "benchmark_ai_status": "EVALUATED", **core}

    @classmethod
    def _not_evaluable(cls, ground_truth, expected_list, detected_findings, rejected_findings, interaction_log, ai_status):
        """AI provider failed: the AI-inclusive benchmark cannot be computed. Report deterministic-only separately."""
        det_scope = [e for e in expected_list
                     if set(e.get("allowed_sources") or []) & cls.DETERMINISTIC_GT_SOURCES]
        det_findings = [f for f in detected_findings
                        if {s.lower() for s in (f.sources or [cls._enum_val(f.source)])} & cls.DETERMINISTIC_SOURCES]
        det_core = cls._evaluate_core(det_scope, det_findings, rejected_findings=rejected_findings,
                                      interaction_log=interaction_log, ai_available=False,
                                      unique_gt_ids=[e["ground_truth_id"] for e in det_scope if e.get("ground_truth_id")])
        eligible = [f for f in detected_findings if cls._enum_val(f.verification_status).lower() in cls.ELIGIBLE_STATUSES]
        status = ai_status or "PROVIDER_NOT_EVALUABLE"
        return {
            "benchmark_ai_status": "NOT_EVALUABLE",
            "ai_status": status,
            "detected_count": len(eligible),
            "true_positives": None,
            "false_positives": None,
            "false_negatives": None,
            "precision": None,
            "precision_formatted": "N/A",
            "precision_note": None,
            "recall": None,
            "recall_formatted": "N/A (NOT EVALUABLE)",
            "f1_score": None,
            "f1_formatted": "N/A (NOT EVALUABLE)",
            "integrity_status": "NOT_EVALUABLE",
            "integrity_notes": (
                f"AI provider unavailable ({status}); TP/FP/FN/Precision/Recall/F1 were not computed. "
                f"Expected defects ({len(expected_list)}) come from the ground-truth registry."
            ),
            "missed_defects": [],
            "traceability": [],
            "fn_diagnostics": [],
            "fp_diagnostics": [],
            "deterministic_only": {
                "label": "DETERMINISTIC-ONLY (AI unavailable) - scope: GT defects detectable by axe-core/runtime; not comparable with the full benchmark",
                "scope_ground_truth_ids": [e.get("ground_truth_id") for e in det_scope],
                "expected_count": len(det_scope),
                **det_core
            }
        }

    @classmethod
    def _evaluate_core(
        cls,
        expected_list: List[Dict[str, Any]],
        detected_findings: List[AURAFinding],
        raw_ai_candidates: Optional[List[Any]] = None,
        suppressed_ai_candidates: Optional[List[Any]] = None,
        rejected_findings: Optional[List[AURAFinding]] = None,
        interaction_log: Optional[List[Dict[str, Any]]] = None,
        ai_available: bool = True,
        unique_gt_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        expected_count = len(expected_list)
        gt_ids = [exp.get("ground_truth_id") or f"GT-{i + 1:03d}" for i, exp in enumerate(expected_list)]

        eligible: List[AURAFinding] = []
        ineligible: List[AURAFinding] = []
        for f in detected_findings:
            (eligible if cls._enum_val(f.verification_status).lower() in cls.ELIGIBLE_STATUSES else ineligible).append(f)

        elig_views = [cls._view(f) for f in eligible]
        inelig_views = [cls._view(f) for f in ineligible]
        rejected_views = [cls._view(f) for f in (rejected_findings or [])]
        raw_views = [cls._view(c) for c in (raw_ai_candidates or [])]
        supp_views = [cls._view(c) for c in (suppressed_ai_candidates or [])]
        raw_by_id = {v["id"]: v for v in raw_views}

        # 1. Match matrix over eligible findings
        comps: Dict[Tuple[int, int], Dict[str, Any]] = {}
        edges: Dict[int, List[Tuple[int, int]]] = {}
        for g, exp in enumerate(expected_list):
            for fi, v in enumerate(elig_views):
                c = cls._components(exp, v)
                comps[(g, fi)] = c
                if c["full"]:
                    edges.setdefault(g, []).append((c["score"], fi))

        # 2. One-to-one maximum matching
        assignment = cls._max_one_to_one(expected_count, edges)   # gt -> finding
        f_to_gt = {fi: g for g, fi in assignment.items()}

        tp = len(assignment)
        fp = len(eligible) - tp
        fn = expected_count - tp

        traceability: List[Dict[str, Any]] = []
        fn_diagnostics: List[Dict[str, Any]] = []
        fp_diagnostics: List[Dict[str, Any]] = []

        # 3. TP / FP rows
        for fi, (f, v) in enumerate(zip(eligible, elig_views)):
            row = cls._finding_row(f, v)
            if fi in f_to_gt:
                g = f_to_gt[fi]
                c = comps[(g, fi)]
                row.update({
                    "benchmark_status": "TP", "benchmark_match_status": "TP",
                    "ground_truth_id": gt_ids[g],
                    "gt_category": str(expected_list[g].get("category", "")).upper(),
                    "rule_match_tier": c["rule_tier"], "target_match_tier": c["target_tier"],
                    "root_cause": None,
                    "match_reason": (f"Matched ground truth defect [{gt_ids[g]}]: rule '{cls._gt_rules(expected_list[g])[0] if cls._gt_rules(expected_list[g]) else 'any'}' "
                                     f"via {c['rule_tier']}, target '{expected_list[g].get('target') or 'any'}' via {c['target_tier']}"),
                    "chain": cls._chain(gt_ids[g], v, raw_by_id, f"matched [rule: {c['rule_tier']}, target: {c['target_tier']}]", "TP"),
                })
            else:
                cause, related_gt, detail = cls._classify_fp(fi, v, expected_list, gt_ids, comps, assignment)
                row.update({
                    "benchmark_status": "FP", "benchmark_match_status": "FP",
                    "ground_truth_id": None, "related_ground_truth_id": related_gt,
                    "root_cause": cause, "match_reason": detail,
                    "chain": cls._chain(related_gt or "(no GT)", v, raw_by_id, detail, f"FP [{cause}]"),
                })
                fp_diagnostics.append({
                    "finding_id": f.id, "candidate_id": row["candidate_id"], "source": row["source"],
                    "sources": row["sources"], "category": row["category"], "normalized_rule": row["normalized_rule"],
                    "target": row["target"], "verification_status": row["verification_status"],
                    "related_ground_truth_id": related_gt,
                    "diagnostic_category": cause, "root_cause": cause, "reason": detail,
                })
            traceability.append(row)

        # 4. Ineligible rows (UNCERTAIN / REJECTED canonical findings)
        for f, v in zip(ineligible, inelig_views):
            row = cls._finding_row(f, v)
            row.update({
                "benchmark_status": "INELIGIBLE", "benchmark_match_status": "INELIGIBLE",
                "ground_truth_id": None, "root_cause": None,
                "match_reason": f"Candidate status '{v['status']}' is ineligible for benchmark ground truth evaluation",
            })
            traceability.append(row)

        # 5. FN rows with root causes
        missed_defects = []
        for g, exp in enumerate(expected_list):
            if g in assignment:
                continue
            missed_defects.append(exp)
            cause, detail, related = cls._classify_fn(
                g, exp, elig_views, inelig_views, rejected_views, raw_views, supp_views,
                comps, assignment, gt_ids, interaction_log, ai_available
            )
            exp_rule = cls._gt_rules(exp)[0] if cls._gt_rules(exp) else "defect"
            traceability.append({
                "benchmark_status": "FN", "benchmark_match_status": "FN",
                "ground_truth_id": gt_ids[g], "finding_id": "N/A", "candidate_id": "N/A",
                "normalized_rule": exp_rule, "category": exp.get("category", "UX"),
                "gt_category": str(exp.get("category", "")).upper(),
                "target": exp.get("target") or "N/A", "verification_status": "N/A",
                "related_finding_id": related, "root_cause": cause, "match_reason": detail,
                "chain": f"{gt_ids[g]} → {detail} → FN [{cause}]",
            })
            fn_diagnostics.append({
                "ground_truth_id": gt_ids[g], "category": exp.get("category", "UX"),
                "normalized_rule": exp_rule, "target": exp.get("target") or "N/A",
                "related_finding_id": related,
                "diagnostic_category": cause, "root_cause": cause, "reason": detail,
                "match_reason": f"Expected ground truth defect [{gt_ids[g]}] ({exp_rule}) has no matching canonical finding",
            })

        # 6. Integrity invariants
        integrity_notes = cls._check_integrity(expected_count, tp, fp, fn, len(eligible), traceability, unique_gt_ids)
        integrity_status = "FAIL" if integrity_notes else "PASS"

        ai_tp = sum(1 for fi in f_to_gt if "ai" in [s.lower() for s in elig_views[fi]["sources"]])
        ai_recall = round(ai_tp / expected_count, 4) if expected_count > 0 else 1.0
        metrics = cls._metrics(tp, fp, fn)

        return {
            "detected_count": len(eligible),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            **metrics,
            "ai_candidate_recall": ai_recall,
            "ai_verified_recall": ai_recall,
            "final_finding_recall": metrics["recall"],
            "integrity_status": integrity_status,
            "integrity_notes": "; ".join(integrity_notes) if integrity_notes else "All benchmark invariants passed",
            "missed_defects": missed_defects,
            "traceability": traceability,
            "fn_diagnostics": fn_diagnostics,
            "fp_diagnostics": fp_diagnostics,
            "fn_root_cause_counts": cls._count(fn_diagnostics),
            "fp_root_cause_counts": cls._count(fp_diagnostics),
        }

    @staticmethod
    def _count(diags: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for d in diags:
            counts[d["root_cause"]] = counts.get(d["root_cause"], 0) + 1
        return counts

    @classmethod
    def _finding_row(cls, f: AURAFinding, v: Dict[str, Any]) -> Dict[str, Any]:
        c_type = getattr(f, "ai_contribution_type", None)
        return {
            "finding_id": f.id,
            "candidate_id": (v["candidate_ids"][0] if v["candidate_ids"] else f.id),
            "candidate_ids": v["candidate_ids"],
            "source": cls._enum_val(f.source),
            "sources": v["sources"],
            "normalized_rule": v["normalized_rule"] or v["raw_rule"] or f.title,
            "raw_rule": v["raw_rule"] or None,
            "category": v["category"],
            "target": f.canonical_target or f.raw_target or "Element",
            "raw_target": f.raw_target,
            "target_resolution": (f.resolved_target or {}).get("method"),
            "verification_status": v["status"],
            "verification_confidence": f.verification_score if f.verification_score is not None else f.confidence,
            "ai_confidence": f.ai_confidence if f.ai_confidence is not None else f.confidence,
            "ai_contribution_type": cls._enum_val(c_type) if c_type else None,
            "ai_contribution_score": getattr(f, "ai_contribution_score", None),
            "evidence_ids": f.evidence_ids,
        }

    @classmethod
    def _chain(cls, head: str, v: Dict[str, Any], raw_by_id: Dict[str, Dict[str, Any]], match: str, tail: str) -> str:
        """GT → candidate(s) → normalization → verification → canonical finding → match → outcome."""
        parts = [head]
        cands = [c for c in v["candidate_ids"] if c in raw_by_id]
        for cid in cands:
            rv = raw_by_id[cid]
            parts.append(f"{cid} (AI rule: {rv['raw_rule'] or 'none'} → normalized: {rv['normalized_rule'] or 'none'})")
        if not cands:
            parts.append(f"{'+'.join(v['sources'])} observation")
        parts.append(f"verified {v['status'].upper()}")
        parts.append(v["id"])
        parts.append(match)
        parts.append(tail)
        return " → ".join(parts)

    @classmethod
    def _classify_fp(cls, fi, v, expected_list, gt_ids, comps, assignment) -> Tuple[str, Optional[str], str]:
        # a. Fully matches a GT defect that another finding already represents -> duplicate
        for g in range(len(expected_list)):
            c = comps[(g, fi)]
            if c["full"] and g in assignment:
                return ("DUPLICATE", gt_ids[g],
                        f"Also matches [{gt_ids[g]}], which is already matched one-to-one by another canonical finding; "
                        f"the correlator did not merge them")
        # b. Near-miss against a GT defect (prefer defects still unmatched)
        near = []
        for g in range(len(expected_list)):
            axis = cls._missing_axis(comps[(g, fi)])
            if axis:
                near.append((g in assignment, g, axis))
        if near:
            _, g, axis = sorted(near)[0]
            c = comps[(g, fi)]
            return (axis, gt_ids[g],
                    f"Near-miss to [{gt_ids[g]}]: category_ok={c['category_ok']}, rule={c['rule_tier']}, "
                    f"target={c['target_tier']} (GT target '{expected_list[g].get('target') or 'any'}', "
                    f"finding target '{v['raw_target'] or v['canonical_target'] or 'none'}')")
        # c. Tool-confirmed defect that the ground truth does not enumerate
        srcs = {s.lower() for s in v["sources"]}
        if srcs & cls.DETERMINISTIC_SOURCES:
            return ("LEGITIMATE_NON_GT_FINDING", None,
                    f"Deterministically observed by {'+'.join(v['sources'])}; not enumerated in this suite's ground truth")
        # d/e. AI-only finding with no relation to any GT defect
        if v["status"] == "likely":
            return ("INSUFFICIENT_EVIDENCE", None,
                    "AI-only finding verified only as LIKELY and unrelated to any ground-truth defect")
        return ("OUTSIDE_BENCHMARK_SCOPE", None,
                "AI-only finding unrelated to any ground-truth defect; the benchmark cannot judge it (needs human review)")

    @classmethod
    def _classify_fn(cls, g, exp, elig_views, inelig_views, rejected_views, raw_views, supp_views,
                     comps, assignment, gt_ids, interaction_log, ai_available) -> Tuple[str, str, Optional[str]]:
        f_to_gt = {fi: gg for gg, fi in assignment.items()}

        # a. A full match exists but is consumed by another GT under one-to-one matching. It is only a
        #    correlation failure if this defect's match is at least as strong as the one that won;
        #    a weaker (e.g. keyword-only) association is just noted.
        weak_notes = []
        for fi, v in enumerate(elig_views):
            if comps[(g, fi)]["full"] and fi in f_to_gt:
                other = f_to_gt[fi]
                if comps[(g, fi)]["score"] >= comps[(other, fi)]["score"]:
                    return ("CORRELATION_FAILURE",
                            f"{v['id']} matches this defect but is already matched one-to-one to [{gt_ids[other]}]",
                            v["id"])
                weak_notes.append(f"{v['id']} relates only weakly [rule: {comps[(g, fi)]['rule_tier']}] and is the stronger match for [{gt_ids[other]}]")
        weak_note = f"; {'; '.join(weak_notes)}" if weak_notes else ""
        # a2. A relevant AI candidate was merged into a canonical finding that represents another GT defect
        raw_by_id = {rv["id"]: rv for rv in raw_views}
        for fi, v in enumerate(elig_views):
            if fi in f_to_gt:
                for cid in v["candidate_ids"]:
                    rv = raw_by_id.get(cid)
                    if rv and cls._components(exp, rv)["full"]:
                        return ("CORRELATION_FAILURE",
                                f"AI candidate {cid} describes this defect but was merged into {v['id']}, which matched [{gt_ids[f_to_gt[fi]]}]",
                                v["id"])

        # b. Matching canonical finding / AI claim exists but verification did not make it eligible
        for v in inelig_views + rejected_views:
            if cls._components(exp, v)["full"]:
                return ("EVIDENCE_INSUFFICIENT",
                        f"{v['id']} describes this defect but verification status is {v['status'].upper()} (benchmark-ineligible)",
                        v["id"])

        # c. Near-miss among eligible canonical findings: name the failing axis
        near = []
        for fi, v in enumerate(elig_views):
            axis = cls._missing_axis(comps[(g, fi)])
            if axis:
                c = comps[(g, fi)]
                near.append((-(cls.RULE_TIER_RANK.get(c["rule_tier"], 0) + cls.TARGET_TIER_RANK.get(c["target_tier"], 0)), fi, axis))
        if near:
            _, fi, axis = sorted(near)[0]
            v, c = elig_views[fi], comps[(g, fi)]
            if axis == "CATEGORY_MISMATCH":
                # category changed between the AI candidate and the canonical finding
                for cid in v["candidate_ids"]:
                    rv = raw_by_id.get(cid)
                    if rv and cls._category_ok(exp, rv):
                        return ("NORMALIZATION_FAILURE",
                                f"AI candidate {cid} category '{rv['category']}' fits, but canonical {v['id']} became '{v['category']}'",
                                v["id"])
            return (axis,
                    f"Verified {v['id']} is related but not matched: category_ok={c['category_ok']}, rule={c['rule_tier']}, "
                    f"target={c['target_tier']} (GT target '{exp.get('target') or 'any'}', "
                    f"finding target '{v['raw_target'] or v['canonical_target'] or 'none'}', "
                    f"finding rule '{v['normalized_rule'] or v['raw_rule'] or 'none'}')",
                    v["id"])

        # d. AI proposed something related that never became a canonical finding (e.g. suppressed as duplicate)
        represented = {cid for v in elig_views + inelig_views + rejected_views for cid in v["candidate_ids"]}
        for rv in supp_views + raw_views:
            if rv["id"] in represented:
                continue
            c = cls._components(exp, rv)
            if c["full"] or cls._missing_axis(c):
                why = {"dropped_over_limit": "it was dropped because the AI returned more candidates than the requested budget"}.get(
                    rv["status"], "it produced no matching canonical finding")
                return ("AI_GENERATED_NOT_MATCHED",
                        f"AI candidate {rv['id']} ('{rv['title'][:60]}') is related, but {why}",
                        rv["id"])

        # e. Nothing related was produced
        allowed = set(exp.get("allowed_sources") or [])
        evidence_note = cls._interaction_note(exp, interaction_log)
        if "AI" in allowed and ai_available:
            det = allowed & cls.DETERMINISTIC_GT_SOURCES
            extra = f"; no {'/'.join(sorted(det))} observation either" if det else ""
            return ("AI_NOT_GENERATED", f"AI produced no candidate for this defect{extra}{evidence_note}{weak_note}", None)
        return ("EVIDENCE_INSUFFICIENT",
                f"No deterministic ({'/'.join(sorted(allowed & cls.DETERMINISTIC_GT_SOURCES)) or 'evidence'}) observation of this defect was recorded{evidence_note}{weak_note}",
                None)

    @staticmethod
    def _interaction_note(exp: Dict[str, Any], interaction_log: Optional[List[Dict[str, Any]]]) -> str:
        if "interaction" not in (exp.get("expected_evidence") or []) or interaction_log is None:
            return ""
        target = str(exp.get("target") or "").strip()
        tid = target[1:].lower() if target.startswith("#") else None
        exercised = [e for e in interaction_log if e.get("status") == "executed" and (
            e.get("target") == target or (tid and tid in [str(i).lower() for i in (e.get("element_id_chain") or [])]))]
        if exercised:
            return f"; target {target} was exercised by controlled interaction"
        executed = sum(1 for e in interaction_log if e.get("status") == "executed")
        return f"; target {target} was never exercised by controlled interactions ({executed} executed on other elements)"

    @classmethod
    def _check_integrity(cls, expected, tp, fp, fn, eligible_cnt, traceability, unique_gt_ids) -> List[str]:
        notes = []
        if unique_gt_ids and len(unique_gt_ids) != expected:
            notes.append(f"Ground truth ID count ({len(unique_gt_ids)}) != expected record count ({expected})")
        if tp + fn != expected:
            notes.append(f"Invariant violation: TP ({tp}) + FN ({fn}) != Expected ({expected})")
        if min(tp, fp, fn) < 0 or tp > expected or fn > expected:
            notes.append(f"Count bounds violated (TP={tp}, FP={fp}, FN={fn}, Expected={expected})")
        if tp + fp != eligible_cnt:
            notes.append(f"TP ({tp}) + FP ({fp}) != eligible canonical findings ({eligible_cnt})")
        tp_rows = [r for r in traceability if r["benchmark_status"] == "TP"]
        fn_rows = [r for r in traceability if r["benchmark_status"] == "FN"]
        if any(not r.get("ground_truth_id") for r in tp_rows + fn_rows):
            notes.append("A TP or FN row has no ground truth ID")
        tp_gt = [r["ground_truth_id"] for r in tp_rows]
        fn_gt = [r["ground_truth_id"] for r in fn_rows]
        if len(set(tp_gt)) != len(tp_gt):
            notes.append("A ground truth ID is matched by more than one canonical finding")
        if set(tp_gt) & set(fn_gt):
            notes.append(f"Ground truth IDs both TP and FN: {sorted(set(tp_gt) & set(fn_gt))}")
        tp_f = [r["finding_id"] for r in tp_rows]
        if len(set(tp_f)) != len(tp_f):
            notes.append("A canonical finding is matched to more than one ground truth ID")
        return notes

    @classmethod
    def not_run(cls, site_dir: Path, reason: str) -> Dict[str, Any]:
        """A suite that was never audited (e.g. provider became unavailable mid Run All): no metrics at all."""
        gt = cls.load_ground_truth(Path(site_dir))
        return {
            "site_id": gt.get("suite_id", Path(site_dir).name),
            "site_name": gt.get("name", Path(site_dir).name),
            "ground_truth_available": True,
            "expected_count": len(gt.get("expected_findings", [])),
            "detected_count": None,
            "benchmark_ai_status": "NOT_EVALUABLE",
            "ai_status": "NOT_RUN",
            "true_positives": None, "false_positives": None, "false_negatives": None,
            "precision": None, "recall": None, "f1_score": None,
            "precision_formatted": "N/A", "recall_formatted": "N/A (NOT RUN)", "f1_formatted": "N/A (NOT RUN)",
            "integrity_status": "NOT_EVALUABLE",
            "integrity_notes": f"Suite not run: {reason}",
            "missed_defects": [], "traceability": [], "fn_diagnostics": [], "fp_diagnostics": [],
        }

    @classmethod
    def evaluate_suite(
        cls,
        test_lab_dir: Path,
        scenario_results: Dict[str, List[AURAFinding]],
        precomputed: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Evaluates the full 5-suite Test Lab benchmark (category-level, micro and macro metrics).
        precomputed: per-suite results from the audit runs (preferred: they carry AI candidate and
        provider context). NOT_EVALUABLE suites are excluded from the aggregate metrics and counted.
        """
        CONSOLIDATED_SUITES = [
            "01_accessibility_suite",
            "02_ui_ux_suite",
            "03_navigation_interaction_suite",
            "04_responsive_runtime_suite",
            "05_mixed_realistic_suite"
        ]
        categories = ["ACCESSIBILITY", "UI", "UX", "FORM", "NAVIGATION", "INTERACTION", "RESPONSIVENESS", "RUNTIME"]
        category_metrics: Dict[str, Dict[str, int]] = {c: {"expected": 0, "tp": 0, "fp": 0, "fn": 0} for c in categories}

        scenario_evaluations = []
        not_evaluable = []
        strong_count = partial_count = missed_count = 0
        total_expected = total_detected = micro_tp = micro_fp = micro_fn = 0

        for suite_name in CONSOLIDATED_SUITES:
            site_dir = Path(test_lab_dir) / suite_name
            if not site_dir.exists():
                continue
            if precomputed and suite_name in precomputed:
                eval_res = dict(precomputed[suite_name])
            else:
                eval_res = cls.evaluate(site_dir, scenario_results.get(suite_name, []))

            if eval_res.get("benchmark_ai_status") == "NOT_EVALUABLE":
                eval_res["status_icon"] = "⚪ Not evaluable"
                not_evaluable.append(suite_name)
                scenario_evaluations.append(eval_res)
                continue

            total_expected += eval_res["expected_count"]
            total_detected += eval_res["detected_count"]
            micro_tp += eval_res["true_positives"]
            micro_fp += eval_res["false_positives"]
            micro_fn += eval_res["false_negatives"]

            f1 = eval_res.get("f1_score") or 0.0
            if f1 >= 0.80:
                eval_res["status_icon"] = "🟢 Strong"
                strong_count += 1
            elif f1 > 0.0:
                eval_res["status_icon"] = "🟡 Partial"
                partial_count += 1
            else:
                eval_res["status_icon"] = "🔴 Missed"
                missed_count += 1
            scenario_evaluations.append(eval_res)

            for exp in cls.load_ground_truth(site_dir).get("expected_findings", []):
                cat = str(exp.get("category", "UX")).upper().strip()
                category_metrics[cat if cat in category_metrics else "UX"]["expected"] += 1

            for row in eval_res.get("traceability", []):
                st = row.get("benchmark_status")
                # TP/FN are counted under the GT defect's category; FP under the finding's category
                cat = str(row.get("gt_category") or row.get("category", "UX")).upper().strip()
                cat = cat if cat in category_metrics else "UX"
                if st == "TP":
                    category_metrics[cat]["tp"] += 1
                elif st == "FP":
                    category_metrics[cat]["fp"] += 1
                elif st == "FN":
                    category_metrics[cat]["fn"] += 1

        micro = cls._metrics(micro_tp, micro_fp, micro_fn)

        category_results = {}
        category_f1s = {}
        macro_p, macro_r, macro_f = [], [], []
        for cat, c in category_metrics.items():
            if c["expected"] == 0 and (c["tp"] + c["fp"]) == 0:
                p_fmt = r_fmt = f_fmt = "N/A"
            else:
                m = cls._metrics(c["tp"], c["fp"], c["fn"])
                p = m["precision"] or 0.0
                p_fmt, r_fmt, f_fmt = m["precision_formatted"], m["recall_formatted"], m["f1_formatted"]
                macro_p.append(p)
                macro_r.append(m["recall"])
                macro_f.append(m["f1_score"])
            category_f1s[cat] = f_fmt
            category_results[cat] = {**c, "precision_formatted": p_fmt, "recall_formatted": r_fmt, "f1_formatted": f_fmt}

        macro_prec = round(sum(macro_p) / len(macro_p), 4) if macro_p else 0.0
        macro_rec = round(sum(macro_r) / len(macro_r), 4) if macro_r else 0.0
        macro_f1 = round(sum(macro_f) / len(macro_f), 4) if macro_f else 0.0

        return {
            "total_scenarios": len(scenario_evaluations),
            "executed_scenarios": len(scenario_evaluations),
            "total_suites": len(scenario_evaluations),
            "not_evaluable_suites": not_evaluable,
            "total_expected": total_expected,
            "total_expected_defects": total_expected,
            "total_detected": total_detected,
            "total_detected_eligible": total_detected,
            "total_tp": micro_tp,
            "total_fp": micro_fp,
            "total_fn": micro_fn,
            "total_true_positives": micro_tp,
            "total_false_positives": micro_fp,
            "total_false_negatives": micro_fn,
            "micro_precision": micro["precision"],
            "micro_recall": micro["recall"],
            "micro_f1": micro["f1_score"],
            "overall_precision_formatted": micro["precision_formatted"],
            "overall_recall_formatted": micro["recall_formatted"],
            "overall_f1_formatted": micro["f1_formatted"],
            "micro_precision_formatted": micro["precision_formatted"],
            "micro_recall_formatted": micro["recall_formatted"],
            "micro_f1_formatted": micro["f1_formatted"],
            "macro_precision": macro_prec,
            "macro_recall": macro_rec,
            "macro_f1": macro_f1,
            "macro_precision_formatted": f"{macro_prec * 100:.1f}%",
            "macro_recall_formatted": f"{macro_rec * 100:.1f}%",
            "macro_f1_formatted": f"{macro_f1 * 100:.1f}%",
            "category_f1s": category_f1s,
            "category_metrics": category_results,
            "strong_count": strong_count,
            "partial_count": partial_count,
            "missed_count": missed_count,
            "scenario_evaluations": scenario_evaluations,
            "suite_evaluations": scenario_evaluations
        }
