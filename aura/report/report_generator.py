import json
from datetime import datetime
from typing import List, Dict, Any
from typing import List, Dict, Any, Optional
from aura.models.findings import AURAReport, AURAScore, VerifiedFinding, AccessibilityViolation, RuntimeTelemetry
from aura.findings.models import AURAFinding
from aura.findings.aggregation import FindingsAggregator


class ReportGenerator:
    """Generates structured AURA V0.3 audit reports."""

    def generate_report(
        self,
        url: str,
        viewport: Dict[str, int],
        scores: AURAScore,
        findings: List[VerifiedFinding],
        rejected_findings: List[VerifiedFinding],
        accessibility_violations: List[AccessibilityViolation],
        telemetry: RuntimeTelemetry,
        execution_steps: List[Dict[str, Any]] = [],
        provider_name: str = "Mock",
        is_mock_mode: bool = True,
        credential_source: str = "Mock Mode",
        ai_status: Optional[str] = None,
        interaction_log: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Assembles full V0.3 audit report data model and unified findings aggregation."""

        aggregation_result = FindingsAggregator.aggregate(
            verified_ai_findings=findings,
            rejected_ai_findings=rejected_findings,
            accessibility_violations=accessibility_violations,
            telemetry=telemetry,
            ai_status=ai_status,
            interaction_log=interaction_log
        )

        base_report = AURAReport(
            url=url,
            viewport=viewport,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            scores=scores,
            findings=findings,
            rejected_findings=rejected_findings,
            accessibility_violations=accessibility_violations,
            runtime_telemetry=telemetry,
            execution_steps=execution_steps,
            provider_name=provider_name,
            is_mock_mode=is_mock_mode
        )

        return {
            "report_model": base_report,
            "aggregation": aggregation_result,
            "credential_source": credential_source
        }
