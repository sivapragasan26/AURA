from enum import Enum
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, ConfigDict


class FindingSource(str, Enum):
    AI = "AI"
    AXE = "axe-core"
    RUNTIME = "Runtime"
    INTERACTION = "Interaction"
    SYSTEM = "System"


class FindingCategory(str, Enum):
    UI = "UI"
    UX = "UX"
    ACCESSIBILITY = "ACCESSIBILITY"
    RESPONSIVENESS = "RESPONSIVENESS"
    NAVIGATION = "NAVIGATION"
    FORM = "FORM"
    CONTENT = "CONTENT"
    RUNTIME = "RUNTIME"
    INTERACTION = "INTERACTION"


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingVerificationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    LIKELY = "LIKELY"
    UNCERTAIN = "UNCERTAIN"
    REJECTED = "REJECTED"


class AffectedElement(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    selector: Optional[str] = None
    tag: Optional[str] = None
    text: Optional[str] = None
    target_list: List[str] = []
    bounding_box: Optional[Dict[str, float]] = None


class FindingEvidence(BaseModel):
    types: List[str] = ["VISUAL"]  # VISUAL, DOM, ACCESSIBILITY, RUNTIME, MULTI_SOURCE
    description: str = ""
    sources: List[str] = []
    flags: Dict[str, bool] = {
        "screenshot": False,
        "dom": False,
        "accessibility": False,
        "runtime": False
    }


class AIContributionType(str, Enum):
    NOVEL_AI_INSIGHT = "NOVEL_AI_INSIGHT"
    COMPLEMENTARY_INTERPRETATION = "COMPLEMENTARY_INTERPRETATION"
    DETERMINISTIC_DUPLICATE = "DETERMINISTIC_DUPLICATE"


class AURAFinding(BaseModel):
    """Unified first-class finding model across AI, AXE, RUNTIME, and SYSTEM sources."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    candidate_id: Optional[str] = None
    source: FindingSource
    sources: List[str] = Field(default_factory=list)
    category: FindingCategory
    severity: FindingSeverity
    title: str
    description: str
    observation: str
    confidence: float  # 0.0 to 1.0
    verification_status: FindingVerificationStatus
    evidence: FindingEvidence
    affected_element: Optional[AffectedElement] = None
    target_identity: Optional[Dict[str, Any]] = None
    recommendation: Optional[str] = None
    why_it_matters: Optional[str] = None
    rejection_reason: Optional[str] = None
    raw_rule: Optional[str] = None  # e.g., image-alt or uncaught-exception
    normalized_rule: Optional[str] = None
    raw_target: Optional[str] = None
    canonical_target: Optional[str] = None
    # GT-blind DOM resolution of the target: {method, match_count, elements: [{tag, id, id_chain}]}
    resolved_target: Optional[Dict[str, Any]] = None
    why_ai_needed: Optional[str] = None
    verification_score: Optional[float] = None
    ai_confidence: Optional[float] = None
    ai_contribution_type: Optional[AIContributionType] = None
    ai_contribution_score: Optional[float] = None  # 0.0 to 1.0
    evidence_ids: List[str] = Field(default_factory=list)
    candidate_ids: List[str] = Field(default_factory=list)
    benchmark_eligible: bool = True

    @property
    def evidence_flags(self) -> Dict[str, bool]:
        if self.evidence and hasattr(self.evidence, "flags"):
            return self.evidence.flags
        return {"screenshot": False, "dom": False, "accessibility": False, "runtime": False}

    @property
    def evidence_sources(self) -> List[str]:
        if self.evidence and hasattr(self.evidence, "sources"):
            return self.evidence.sources
        return []


class AggregationResult(BaseModel):
    """Container holding unified findings aggregation results."""
    model_config = ConfigDict(populate_by_name=True)

    findings: List[AURAFinding] = Field(default_factory=list)
    all_active_findings: List[AURAFinding] = Field(default_factory=list)
    rejected_findings: List[AURAFinding] = Field(default_factory=list)
    all_rejected_findings: List[AURAFinding] = Field(default_factory=list)
    severity_counts: Dict[str, int] = Field(default_factory=dict)
    verification_counts: Dict[str, int] = Field(default_factory=dict)
    source_counts: Dict[str, int] = Field(default_factory=dict)
    correlation_counts: Dict[str, int] = Field(default_factory=lambda: {
        "ai_plus_axe": 0,
        "ai_plus_runtime": 0,
        "axe_only": 0,
        "runtime_only": 0,
        "ai_only": 0
    })
    summary_text: str = ""

