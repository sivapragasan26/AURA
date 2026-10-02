from typing import List, Dict, Any, Tuple
from aura.config import settings
from aura.models.findings import VerifiedFinding, AURAScore, AccessibilityViolation, RuntimeTelemetry, VerificationStatus
from aura.scoring.accessibility_scorer import AccessibilityScorer
from aura.scoring.runtime_scorer import RuntimeScorer


class AURAScorer:
    """
    Computes transparent AURA Prototype Scores with itemized deduction breakdowns:
    - UI Score: 25%
    - UX Score: 30%
    - Accessibility Score: 25%
    - Runtime Score: 20%
    """

    STATUS_MULTIPLIERS = {
        VerificationStatus.CONFIRMED: 1.0,
        VerificationStatus.LIKELY: 0.8,
        VerificationStatus.UNCERTAIN: 0.3,
        VerificationStatus.REJECTED: 0.0,
    }

    def __init__(self):
        self.a11y_scorer = AccessibilityScorer()
        self.runtime_scorer = RuntimeScorer()

    def compute_score_with_deductions(
        self,
        verified_findings: List[VerifiedFinding],
        accessibility_violations: List[AccessibilityViolation],
        telemetry: RuntimeTelemetry,
        has_responsive_eval: bool = True,
        has_interaction_eval: bool = True,
        ai_evaluated: bool = True
    ) -> Tuple[AURAScore, Dict[str, List[Dict[str, Any]]]]:
        """
        Calculates Overall, UI, UX, Accessibility, Runtime, Responsive, and Interaction scores with itemized deductions.
        ai_evaluated=False: AI analysis did not succeed, so the AI-derived dimensions (UI, UX, responsive,
        interaction) were not evaluated. The overall score is then the weighted mean of the deterministic
        dimensions (accessibility, runtime) only, instead of counting the unevaluated ones as 100.
        """

        ui_deductions = 0.0
        ux_deductions = 0.0
        responsive_deductions = 0.0
        interaction_deductions = 0.0

        ui_deduction_items: List[Dict[str, Any]] = []
        ux_deduction_items: List[Dict[str, Any]] = []
        a11y_deduction_items: List[Dict[str, Any]] = []
        runtime_deduction_items: List[Dict[str, Any]] = []
        responsive_deduction_items: List[Dict[str, Any]] = []
        interaction_deduction_items: List[Dict[str, Any]] = []

        for item in verified_findings:
            c = item.candidate
            status = item.verification.status
            mult = self.STATUS_MULTIPLIERS.get(status, 0.5)

            if mult == 0.0:
                continue

            severity = c.severity.lower()
            base_deduction = settings.SEVERITY_DEDUCTIONS.get(severity, 5)
            effective_deduction = round(base_deduction * mult, 1)

            cat = c.category.upper()
            item_detail = {
                "title": c.title,
                "severity": c.severity,
                "status": status.value if hasattr(status, 'value') else str(status),
                "deduction": effective_deduction
            }

            if cat == "UI":
                ui_deductions += effective_deduction
                ui_deduction_items.append(item_detail)
            elif cat == "UX":
                ux_deductions += effective_deduction
                ux_deduction_items.append(item_detail)
            elif cat in ("RESPONSIVENESS", "RESPONSIVE"):
                responsive_deductions += effective_deduction
                responsive_deduction_items.append(item_detail)
            elif cat == "INTERACTION":
                interaction_deductions += effective_deduction
                interaction_deduction_items.append(item_detail)
            else:
                ux_deductions += effective_deduction
                ux_deduction_items.append(item_detail)

        # Accessibility deductions from axe-core
        for v in accessibility_violations:
            imp = v.impact.lower()
            ded = 15 if imp == "critical" else (10 if imp == "serious" else (5 if imp == "moderate" else 2))
            a11y_deduction_items.append({
                "title": f"WCAG [{v.rule}]: {v.description}",
                "severity": v.impact,
                "deduction": ded
            })

        # Runtime deductions (application errors only)
        for evt in telemetry.classified_events:
            if evt.deduction > 0:
                runtime_deduction_items.append({
                    "title": f"{evt.source.upper()}: {evt.title}",
                    "severity": evt.category.value if hasattr(evt.category, 'value') else str(evt.category),
                    "deduction": evt.deduction
                })

        ui_score = max(0, int(settings.SCORE_BASE - ui_deductions))
        ux_score = max(0, int(settings.SCORE_BASE - ux_deductions))
        a11y_score = self.a11y_scorer.compute_accessibility_score(accessibility_violations)
        runtime_score = self.runtime_scorer.compute_runtime_score(telemetry.classified_events)
        responsive_score = max(0, int(settings.SCORE_BASE - responsive_deductions)) if has_responsive_eval else "NOT EVALUATED"
        interaction_score = max(0, int(settings.SCORE_BASE - interaction_deductions)) if has_interaction_eval else "NOT EVALUATED"

        # Configurable weights: UI 20%, UX 20%, A11y 20%, Runtime 15%, Responsive 15%, Interaction 10%
        resp_val = responsive_score if isinstance(responsive_score, int) else 100
        int_val = interaction_score if isinstance(interaction_score, int) else 100

        if ai_evaluated:
            overall_raw = (0.20 * ui_score) + (0.20 * ux_score) + (0.20 * a11y_score) + (0.15 * runtime_score) + (0.15 * resp_val) + (0.10 * int_val)
        else:
            overall_raw = ((0.20 * a11y_score) + (0.15 * runtime_score)) / 0.35
        overall_score = max(0, min(100, int(overall_raw)))

        score_model = AURAScore(
            overall=overall_score,
            ui=ui_score,
            ux=ux_score,
            accessibility=a11y_score,
            runtime=runtime_score
        )

        deductions_map = {
            "ui": ui_deduction_items,
            "ux": ux_deduction_items,
            "accessibility": a11y_deduction_items,
            "runtime": runtime_deduction_items
        }

        return score_model, deductions_map

    def compute_score(
        self,
        verified_findings: List[VerifiedFinding],
        accessibility_violations: List[AccessibilityViolation],
        telemetry: RuntimeTelemetry
    ) -> AURAScore:
        """Backward-compatible score computation returning AURAScore model."""
        score, _ = self.compute_score_with_deductions(verified_findings, accessibility_violations, telemetry)
        return score
