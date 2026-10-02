from typing import List, Dict, Any, Tuple, Optional
from aura.models.findings import (
    CandidateFinding, VerificationResult, VerifiedFinding, VerificationStatus,
    AccessibilityViolation, RuntimeTelemetry
)
from aura.verification.evidence import EvidenceMatcher
from aura.verification.rules import VerificationRulesEngine
from aura.utils.logger import logger


class FindingVerifier:
    """Independent Evidence-Based Verification Engine testing Candidate Findings against physical browser evidence."""

    def __init__(self):
        self.evidence_matcher = EvidenceMatcher()
        self.rules_engine = VerificationRulesEngine()

    def verify_findings(
        self,
        candidate_findings: List[CandidateFinding],
        dom_summary: Dict[str, Any],
        accessibility_violations: List[AccessibilityViolation],
        telemetry: RuntimeTelemetry,
        interaction_log: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[List[VerifiedFinding], List[VerifiedFinding]]:
        """
        Runs evidence verification on candidate findings.
        Returns:
          - active_findings: List[VerifiedFinding] (CONFIRMED, LIKELY, UNCERTAIN)
          - rejected_findings: List[VerifiedFinding] (REJECTED)
        """
        active_findings: List[VerifiedFinding] = []
        rejected_findings: List[VerifiedFinding] = []

        all_dom_elements = dom_summary.get("all_elements") or dom_summary.get("interactive_elements") or []

        for candidate in candidate_findings:
            flags, sources, evidence_ids, matching_elements, contradiction_reason, target_match_method = self.evidence_matcher.evaluate_evidence(
                candidate=candidate,
                all_dom_elements=all_dom_elements,
                accessibility_violations=accessibility_violations,
                telemetry=telemetry,
                interaction_log=interaction_log
            )

            status, confidence, rejection_reason = self.rules_engine.evaluate_status_and_confidence(
                candidate=candidate,
                flags=flags,
                matching_elements=matching_elements,
                contradiction_reason=contradiction_reason,
                dom_summary=dom_summary,
                accessibility_violations=accessibility_violations
            )

            v_result = VerificationResult(
                issue_id=candidate.id,
                candidate_id=candidate.candidate_id or candidate.id,
                status=status,
                confidence=round(confidence, 2),
                evidence_ids=evidence_ids,
                evidence_sources=sources,
                rejection_reason=rejection_reason,
                target_match_method=target_match_method,
                evidence_flags=flags
            )

            item = VerifiedFinding(candidate=candidate, verification=v_result)

            if status == VerificationStatus.REJECTED:
                rejected_findings.append(item)
                logger.info(f"Finding [{candidate.id}] REJECTED: {rejection_reason}")
            else:
                active_findings.append(item)
                logger.info(f"Finding [{candidate.id}] VERIFIED ({status.value.upper()} | score: {confidence:.2f})")

        return active_findings, rejected_findings
