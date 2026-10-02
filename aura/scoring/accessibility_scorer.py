from typing import List
from aura.models.findings import AccessibilityViolation


class AccessibilityScorer:
    """Computes transparent Accessibility Sub-score based on axe-core WCAG violation impact."""

    IMPACT_DEDUCTIONS = {
        "critical": 15,
        "serious": 10,
        "moderate": 5,
        "minor": 2,
    }

    def compute_accessibility_score(self, violations: List[AccessibilityViolation]) -> int:
        """Calculates Accessibility Score starting from 100 with impact deductions."""
        total_deduction = sum(
            self.IMPACT_DEDUCTIONS.get(v.impact.lower(), 5) for v in violations
        )
        score = max(0, 100 - total_deduction)
        return score

