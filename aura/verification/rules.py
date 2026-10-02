from typing import Dict, List, Tuple, Optional, Any
from aura.models.findings import CandidateFinding, VerificationStatus
from aura.agent.analyzer_agent import normalize_rule_type
from aura.verification.evidence import INTERACTION_RULES
from aura.verification.materiality import assess, BLANK_CLAIM, WHITESPACE_ONLY_REASON

# Claims of "the control does nothing / gives no feedback"
NO_EFFECT_RULES = INTERACTION_RULES - {"interaction_failure"}


class VerificationRulesEngine:
    """Calculates Verification Status and Verification Score using explicit evidence-driven rules."""

    def evaluate_status_and_confidence(
        self,
        candidate: CandidateFinding,
        flags: Dict[str, bool],
        matching_elements: List[Dict[str, Any]],
        contradiction_reason: Optional[str],
        dom_summary: Optional[Dict[str, Any]] = None,
        accessibility_violations: Optional[List[Any]] = None
    ) -> Tuple[VerificationStatus, float, Optional[str]]:
        # If physical evidence directly contradicts AI candidate finding -> REJECTED
        if contradiction_reason:
            return VerificationStatus.REJECTED, 0.10, contradiction_reason

        # Global empty-space rejection: whitespace alone is not a defect without measured harm
        claim_full = f"{candidate.title} {candidate.description or ''} {candidate.observation or ''}"
        has_measured_harm = bool(
            flags.get("layout_overlap") or flags.get("target_overflow") or
            flags.get("target_clipped") or flags.get("document_overflow") or
            flags.get("interaction_error") or flags.get("runtime")
        )
        if BLANK_CLAIM.search(claim_full) and not has_measured_harm:
            return VerificationStatus.REJECTED, 0.10, WHITESPACE_ONLY_REASON

        cand_rule = (getattr(candidate, "normalized_rule", None) or 
                     normalize_rule_type(candidate.rule_type or candidate.title))
        cat = candidate.category.upper()
        base_confidence = candidate.confidence
        score = base_confidence

        if flags.get("dom"):
            score += 0.10
        if flags.get("accessibility"):
            score += 0.10
        if flags.get("runtime"):
            score += 0.10
        if flags.get("interaction"):
            score += 0.10

        clamped_score = round(max(0.0, min(1.0, score)), 2)

        # 1. ACCESSIBILITY Rules
        if cat == "ACCESSIBILITY" or cand_rule in ("image_alt", "image_alt_missing", "color_contrast", "unlabelled_button", "missing_label", "missing_main_landmark"):
            if flags.get("accessibility") or flags.get("dom"):
                return VerificationStatus.CONFIRMED, min(1.0, max(0.95, clamped_score)), None
            else:
                return VerificationStatus.UNCERTAIN, 0.45, "No axe-core WCAG violation or DOM accessibility defect observed"

        # 2. RUNTIME Rules
        elif cat == "RUNTIME" or cand_rule in ("runtime_api_failure", "console_error", "application_error", "runtime_exception", "api_failure", "network_failure"):
            if flags.get("runtime"):
                return VerificationStatus.CONFIRMED, min(1.0, max(0.95, clamped_score)), None
            else:
                return VerificationStatus.UNCERTAIN, 0.35, "No matching application console error or network 4xx/5xx recorded"

        # 3. RESPONSIVENESS Rules
        elif cat == "RESPONSIVENESS" or cand_rule in ("horizontal_overflow", "clipped_content", "overlapping_elements", "offscreen_control", "broken_mobile_navigation", "unusable_mobile_form", "mobile_layout_break"):
            if flags.get("target_overflow") or flags.get("target_clipped") or flags.get("layout_overlap"):
                return VerificationStatus.CONFIRMED, min(1.0, max(0.95, clamped_score)), None
            if flags.get("document_overflow") and cand_rule not in ("clipped_content", "overlapping_elements"):
                return VerificationStatus.LIKELY, 0.70, "Document overflows the viewport, but the overflow was not measured on the claimed target"
            return VerificationStatus.UNCERTAIN, 0.45, "Responsive geometry problem not measured on the claimed target"

        # 4. INTERACTION Rules
        elif cat == "INTERACTION" or cand_rule in ("interaction_failure", "non_responsive_control", "click_without_feedback", "incorrect_state_transition", "broken_toggle", "broken_menu", "broken_modal", "broken_form_submission", "validation_feedback_failure", "hover_affordance_mismatch", "dead_button", "false_affordance", "fake_button", "non_actionable_control"):
            if not flags.get("interaction"):
                return VerificationStatus.UNCERTAIN, 0.45, "Claimed control was not exercised by a target-specific interaction; existence alone does not verify behavior"
            if flags.get("interaction_error"):
                return VerificationStatus.CONFIRMED, min(1.0, max(0.90, clamped_score)), None
            if flags.get("interaction_no_effect"):
                if cand_rule in NO_EFFECT_RULES or cand_rule == "interaction_failure":
                    return VerificationStatus.CONFIRMED, min(1.0, max(0.90, clamped_score)), None
            return VerificationStatus.UNCERTAIN, 0.50, "Target was exercised: it produced a visible change and no error, which does not support the claimed failure"

        # 5. NAVIGATION Rules
        elif cat == "NAVIGATION" or cand_rule in ("bad_navigation", "unclear_information_architecture", "nonfunctional_navigation", "broken_links"):
            if flags.get("placeholder_href") or flags.get("layout_overlap") or flags.get("interaction_no_effect") or flags.get("interaction_error"):
                return VerificationStatus.CONFIRMED, min(1.0, max(0.90, clamped_score)), None
            if flags.get("dom"):
                return (VerificationStatus.UNCERTAIN, 0.45,
                        "The navigation element exists, but no obstruction, dead link, failed interaction or wrong "
                        "destination was measured")
            return VerificationStatus.UNCERTAIN, 0.50, "Target navigation link or route not confirmed"

        # 6. UI & UX & FORM & CONTENT Rules
        # AI confidence is never evidence here. The claim is checked against measurements of the page
        # (aura/verification/materiality.py): only a measured condition is CONFIRMED, a verified target with an
        # unmeasurable design judgement is LIKELY, an unsupported claim is UNCERTAIN, and evidence that the
        # condition is harmless (or already reported deterministically) REJECTS it.
        else:
            target = matching_elements[0] if (flags.get("dom") and matching_elements) else None
            material = assess(candidate, target, dom_summary or {}, accessibility_violations, flags)
            if material.verdict == "NOT_A_DEFECT":
                return VerificationStatus.REJECTED, 0.10, material.note
            if material.verdict == "SUPPORTED":
                is_objective_defect = (
                    bool(flags.get("layout_overlap") or flags.get("target_overflow") or flags.get("target_clipped")
                         or flags.get("interaction_error") or flags.get("interaction_no_effect")
                         or flags.get("placeholder_href") or flags.get("runtime"))
                    or "destructive action is visually stronger" in material.reason
                    or "competing control is visually stronger" in material.reason
                )
                if is_objective_defect:
                    return VerificationStatus.CONFIRMED, min(1.0, max(0.85, clamped_score)), material.note
                return VerificationStatus.LIKELY, min(0.80, max(0.65, clamped_score)), material.note
            if material.verdict == "JUDGEMENT":
                return VerificationStatus.LIKELY, min(0.80, max(0.65, base_confidence)), material.note
            return VerificationStatus.UNCERTAIN, 0.45, material.note


