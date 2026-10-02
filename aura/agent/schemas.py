from typing import List
from pydantic import BaseModel
from aura.models.findings import CandidateFinding
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator
from aura.models.findings import CandidateFinding, AffectedElementDetail, FindingEvidenceDetail


class RawAICandidatePayload(BaseModel):
    category: str  # UI, UX, ACCESSIBILITY, RESPONSIVENESS, RUNTIME, INTERACTION
    rule_type: str
    title: str
    description: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    confidence: float
    target: Union[str, Dict[str, Any], AffectedElementDetail]
    reasoning_summary: Optional[str] = None
    observation: Optional[str] = None
    recommendation: Optional[str] = None
    why_it_matters: Optional[str] = None
    claim: Optional[str] = None

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v):
        try:
            val = float(v)
            if 0.0 <= val <= 1.0:
                return val
            if 1.0 < val <= 100.0:
                return val / 100.0
            return 0.8
        except Exception:
            return 0.8

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, v):
        if not v:
            return "UI"
        val = str(v).upper()
        if val in ["UI", "UX", "ACCESSIBILITY", "RESPONSIVENESS", "RUNTIME", "INTERACTION", "FORM", "NAVIGATION"]:
            return val
        return "UI"

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v):
        if not v:
            return "medium"
        val = str(v).lower()
        if val in ["critical", "high", "medium", "low", "info"]:
            return val
        return "medium"

    def to_candidate_finding(self, index: int = 1) -> CandidateFinding:
        target_str = self.target if isinstance(self.target, str) else (
            self.target.get("selector", "body") if isinstance(self.target, dict) else str(self.target)
        )
        affected = AffectedElementDetail(selector=target_str, tag="element", text=self.title)
        
        return CandidateFinding(
            id=f"AURA-AI-CAND-{index:03d}",
            category=self.category,
            title=self.title,
            description=self.description,
            observation=self.observation or self.reasoning_summary or self.description,
            severity=self.severity.lower(),
            confidence=self.confidence,
            affected_element=affected,
            evidence=FindingEvidenceDetail(
                type="visual" if self.category in ["UI", "RESPONSIVENESS"] else "dom",
                description=f"AI Candidate Reasoning: {self.reasoning_summary or self.title}"
            ),
            recommendation=self.recommendation or f"Address identified {self.rule_type} issue on {target_str}.",
            why_it_matters=self.why_it_matters or "UI/UX defects degrade user conversion and product trust.",
            claim=self.claim or self.title,
            evidence_required=["visual", "dom"],
            rule_type=self.rule_type,
            status="candidate"
        )


class AICandidateOutput(BaseModel):
    """
    The candidate contract requested from every provider (see prompts.AURA_SYSTEM_PROMPT).
    rule_type is mandatory and is never inferred from the title.
    """
    title: str
    category: str
    rule_type: str
    description: str
    target: Union[str, Dict[str, Any]]
    confidence: float
    evidence: Union[str, Dict[str, Any], None] = ""
    why_ai_needed: Optional[str] = None
    severity: str = "medium"
    recommendation: Optional[str] = None
    observation: Optional[str] = None

    _conf = field_validator("confidence", mode="before")(RawAICandidatePayload.validate_confidence.__func__)
    _cat = field_validator("category", mode="before")(RawAICandidatePayload.validate_category.__func__)
    _sev = field_validator("severity", mode="before")(RawAICandidatePayload.validate_severity.__func__)

    @field_validator("rule_type", mode="before")
    @classmethod
    def require_rule_type(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("rule_type is required")
        return v.strip()

    def to_candidate_finding(self, index: int, resolve_ref=None) -> CandidateFinding:
        """resolve_ref maps an evidence-packet ref (E12) to {selector, tag, text}; None for other targets."""
        target_ref = None
        if isinstance(self.target, dict):
            selector, tag, text = self.target.get("selector") or "body", self.target.get("tag"), self.target.get("text")
        else:
            resolved = resolve_ref(self.target) if resolve_ref else None
            if resolved:
                target_ref = self.target.strip().upper()
                selector, tag, text = resolved.get("selector"), resolved.get("tag"), resolved.get("text")
            elif self.target.strip().lower() in ("page", "document", "body", "window", ""):
                selector, tag, text = "body", "body", None
            else:
                selector, tag, text = self.target, None, None

        evidence_text = self.evidence if isinstance(self.evidence, str) else (
            (self.evidence or {}).get("description") if isinstance(self.evidence, dict) else "")
        category = self.category
        cand = CandidateFinding(
            id=f"AURA-AI-CAND-{index:03d}",
            category=category,
            title=self.title,
            description=self.description,
            observation=self.observation or evidence_text or self.description,
            severity=self.severity,
            confidence=self.confidence,
            affected_element=AffectedElementDetail(selector=selector, tag=tag, text=text),
            evidence=FindingEvidenceDetail(
                type="visual" if category in ("UI", "RESPONSIVENESS") else "dom",
                description=evidence_text or f"AI candidate reasoning: {self.title}"
            ),
            recommendation=self.recommendation,
            claim=self.title,
            evidence_required=["visual", "dom"],
            rule_type=self.rule_type,
            raw_rule_type=self.rule_type,
            why_ai_needed=self.why_ai_needed,
            status="candidate"
        )
        if target_ref:
            cand.target_identity = {"ref": target_ref, "selector": selector}
        return cand


class AIAnalysisResponseSchema(BaseModel):
    overall_summary: str
    issues: List[CandidateFinding] = []
    overall_summary: str = "AI Multimodal candidate findings generated."
    issues: List[CandidateFinding] = Field(default_factory=list)
    candidates: List[RawAICandidatePayload] = Field(default_factory=list)
