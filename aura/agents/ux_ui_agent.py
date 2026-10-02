from typing import Dict, Any, List, Optional
from aura.agent.analyzer_agent import AnalyzerAgent
from aura.agent.provider import AIProvider
from aura.agent.diagnostics import AIDiagnostics
from aura.models.findings import CandidateFinding, RuntimeTelemetry, AccessibilityViolation
from aura.utils.logger import logger


class UXUIAgent:
    """
    Dedicated UX/UI Analysis Agent utilizing multimodal AI reasoning to propose
    candidate findings based on visual evidence, DOM structure, and interaction flows.
    """

    def __init__(self, provider: Optional[AIProvider] = None):
        self.agent = AnalyzerAgent(provider=provider)
        self.last_diagnostics: Optional[AIDiagnostics] = None
        # Candidates dropped as DETERMINISTIC_DUPLICATE; kept only for benchmark traceability
        self.last_suppressed: List[CandidateFinding] = []

    def analyze(
        self,
        telemetry: RuntimeTelemetry,
        dom_summary: Dict[str, Any],
        accessibility_violations: List[AccessibilityViolation],
        screenshot_path: Optional[str] = None,
        interaction_log: Optional[List[Dict[str, Any]]] = None
    ) -> List[CandidateFinding]:
        """
        Executes multimodal AI analysis and returns structured CandidateFinding objects.
        Instructed explicitly: 'You are an analysis agent, not the final authority.'
        Stores pipeline diagnostics on self.last_diagnostics.
        """
        raw_result = self.agent.analyze(
            telemetry=telemetry,
            dom_summary=dom_summary,
            accessibility_violations=accessibility_violations,
            screenshot_path=screenshot_path,
            interaction_log=interaction_log
        )

        self.last_diagnostics = raw_result.get("diagnostics")
        self.last_suppressed = []
        for issue_dict in raw_result.get("suppressed_issues", []):
            try:
                self.last_suppressed.append(CandidateFinding(**issue_dict))
            except Exception as e:
                logger.warning(f"UXUIAgent skipped invalid suppressed candidate payload: {e}")

        candidates: List[CandidateFinding] = []
        for issue_dict in raw_result.get("issues", []):
            try:
                candidates.append(CandidateFinding(**issue_dict))
            except Exception as e:
                logger.warning(f"UXUIAgent skipped invalid candidate payload: {e}")

        return candidates

