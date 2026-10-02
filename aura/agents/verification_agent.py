from typing import List, Dict, Any, Tuple, Optional
from aura.verification.verifier import FindingVerifier
from aura.models.findings import (
    CandidateFinding, VerifiedFinding, AccessibilityViolation, RuntimeTelemetry
)


class VerificationAgent:
    """
    Verification Agent running independent deterministic verification on Candidate Findings
    against physical browser evidence (DOM, bounding boxes, axe-core WCAG, runtime logs).
    """

    def __init__(self):
        self.verifier = FindingVerifier()

    def verify(
        self,
        candidate_findings: List[CandidateFinding],
        dom_summary: Dict[str, Any],
        accessibility_violations: List[AccessibilityViolation],
        telemetry: RuntimeTelemetry,
        interaction_log: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[List[VerifiedFinding], List[VerifiedFinding]]:
        """
        Executes evidence verification rules and returns (active_findings, rejected_findings).
        """
        return self.verifier.verify_findings(
            candidate_findings=candidate_findings,
            dom_summary=dom_summary,
            accessibility_violations=accessibility_violations,
            telemetry=telemetry,
            interaction_log=interaction_log
        )

