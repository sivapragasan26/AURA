from typing import List
from aura.models.findings import ClassifiedRuntimeEvent, RuntimeCategory


class RuntimeScorer:
    """Computes transparent Runtime Sub-score based on classified telemetry events."""

    DEDUCTION_MAP = {
        RuntimeCategory.APPLICATION_ERROR: 25,
        RuntimeCategory.API_ERROR: 20,
        RuntimeCategory.NETWORK_FAILURE: 10,
        RuntimeCategory.THIRD_PARTY_FAILURE: 0,
        RuntimeCategory.TELEMETRY_FAILURE: 0,
        RuntimeCategory.WARNING: 0,
        RuntimeCategory.INFORMATION: 0,
    }

    def compute_runtime_score(self, classified_events: List[ClassifiedRuntimeEvent]) -> int:
        """Calculates Runtime Score starting from 100 penalizing only application-owned defects."""
        total_deduction = sum(
            self.DEDUCTION_MAP.get(evt.category, 0) for evt in classified_events
        )
        score = max(0, 100 - total_deduction)
        return score

    def summarize_runtime_events(self, classified_events: List[ClassifiedRuntimeEvent]) -> dict:
        """Categorizes telemetry events into application, third-party, environment, and browser counts."""
        app_errs = sum(1 for e in classified_events if e.category in (RuntimeCategory.APPLICATION_ERROR, RuntimeCategory.API_ERROR, RuntimeCategory.NETWORK_FAILURE))
        third_party = sum(1 for e in classified_events if e.category in (RuntimeCategory.THIRD_PARTY_FAILURE, RuntimeCategory.TELEMETRY_FAILURE))
        warnings = sum(1 for e in classified_events if e.category == RuntimeCategory.WARNING)
        
        return {
            "application_errors": app_errs,
            "third_party_failures": third_party,
            "environment_warnings": warnings,
            "total_events": len(classified_events)
        }

