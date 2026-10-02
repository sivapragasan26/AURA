from enum import Enum
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, ConfigDict


class EvidenceType(str, Enum):
    VISUAL = "visual"
    DOM = "dom"
    ACCESSIBILITY = "accessibility"
    RUNTIME = "runtime"
    MULTI_SOURCE = "multi_source"


class RuntimeCategory(str, Enum):
    APPLICATION_ERROR = "APPLICATION_ERROR"
    API_ERROR = "API_ERROR"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    THIRD_PARTY_FAILURE = "THIRD_PARTY_FAILURE"
    TELEMETRY_FAILURE = "TELEMETRY_FAILURE"
    WARNING = "WARNING"
    INFORMATION = "INFORMATION"


class VerificationStatus(str, Enum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"


class ElementMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tag: str
    role: Optional[str] = None
    accessible_name: Optional[str] = None
    text: str = ""
    aria_label: Optional[str] = None
    id: Optional[str] = None
    class_name: Optional[str] = Field(default=None, alias="class")
    visible: bool = True
    enabled: bool = True
    bounding_box: Optional[Dict[str, float]] = None  # {x, y, width, height}
    href: Optional[str] = None
    src: Optional[str] = None
    alt: Optional[str] = None
    type: Optional[str] = None
    placeholder: Optional[str] = None
    selector: Optional[str] = None  # unique selector re-resolvable in the page
    id_chain: List[str] = Field(default_factory=list)  # own id + ancestor ids
    overflows_viewport: bool = False  # right edge beyond the viewport
    contains_overflow: bool = False  # content wider than the element's box (not clipped)
    clipped: bool = False  # overflow hidden/clip with content cut off


class AccessibilityViolation(BaseModel):
    rule: str
    impact: str  # critical, serious, moderate, minor
    description: str
    target: List[str] = []
    help_url: Optional[str] = None
    why_it_matters: Optional[str] = None


class ConsoleError(BaseModel):
    type: str  # error, warning, exception
    text: str
    location: Optional[str] = None
    category: RuntimeCategory = RuntimeCategory.APPLICATION_ERROR
    triggered_by: Optional[str] = None  # selector of the control whose interaction raised this error


class NetworkFailure(BaseModel):
    url: str
    status: int
    status_text: str = ""
    method: str = "GET"
    category: RuntimeCategory = RuntimeCategory.NETWORK_FAILURE


class ClassifiedRuntimeEvent(BaseModel):
    category: RuntimeCategory
    source: str  # console or network
    title: str
    detail: str
    deduction: int = 0
    ownership: str = "TARGET_APPLICATION"  # TARGET_APPLICATION, AURA_INFRASTRUCTURE, TEST_LAB_INFRASTRUCTURE, THIRD_PARTY, BROWSER
    event_type: Optional[str] = None  # console: error | warning | exception; network: http status
    url: Optional[str] = None  # request URL for network events
    triggered_by: Optional[str] = None  # control whose interaction raised the event



class RuntimeTelemetry(BaseModel):
    url: str
    title: str = ""
    viewport: Dict[str, int] = {"width": 1440, "height": 900}
    page_load_time_ms: float = 0.0
    console_errors: List[ConsoleError] = []
    network_failures: List[NetworkFailure] = []
    classified_events: List[ClassifiedRuntimeEvent] = []
    dom_summary: Dict[str, Any] = {}
    accessibility_summary: Dict[str, Any] = {}
    screenshot_path: Optional[str] = None


class AffectedElementDetail(BaseModel):
    selector: Optional[str] = None
    tag: Optional[str] = None
    text: Optional[str] = None


class FindingEvidenceDetail(BaseModel):
    type: str  # visual, dom, accessibility, runtime, multi_source
    description: str


class CandidateFinding(BaseModel):
    id: str
    candidate_id: Optional[str] = None
    category: str  # UI, UX, ACCESSIBILITY, RESPONSIVENESS, RUNTIME, CONTENT, NAVIGATION, FORM, INTERACTION
    title: str
    description: str
    observation: str
    severity: str  # critical, high, medium, low, info
    confidence: float  # 0.0 to 1.0
    affected_element: Optional[Union[AffectedElementDetail, str, Dict[str, Any]]] = None
    target_identity: Optional[Dict[str, Any]] = None
    evidence: FindingEvidenceDetail
    recommendation: Optional[str] = None
    why_it_matters: Optional[str] = None
    claim: Optional[str] = None
    viewport: Optional[str] = None
    evidence_required: List[str] = Field(default_factory=list)
    rule_type: Optional[str] = None
    raw_rule_type: Optional[str] = None  # rule_type exactly as the AI emitted it, before normalization
    why_ai_needed: Optional[str] = None  # the model's explanation of why this is not deterministic
    normalized_rule: Optional[str] = None
    status: str = "candidate"
    ai_contribution_type: Optional[str] = None
    ai_contribution_score: Optional[float] = None


class VerificationResult(BaseModel):
    issue_id: str
    candidate_id: Optional[str] = None
    status: VerificationStatus
    confidence: float
    evidence_ids: List[str] = []
    evidence_sources: List[str] = []
    rejection_reason: Optional[str] = None
    target_match_method: Optional[str] = None
    evidence_flags: Dict[str, bool] = {
        "screenshot": False,
        "dom": False,
        "accessibility": False,
        "runtime": False
    }


class VerifiedFinding(BaseModel):
    candidate: CandidateFinding
    verification: VerificationResult


class AURAScore(BaseModel):
    overall: int
    ui: int
    ux: int
    accessibility: int
    runtime: int
    ui: Union[int, str] = 100
    ux: Union[int, str] = 100
    accessibility: Union[int, str] = 100
    runtime: Union[int, str] = 100



class AURAReport(BaseModel):
    url: str
    viewport: Dict[str, int]
    timestamp: str
    scores: AURAScore
    findings: List[VerifiedFinding]
    rejected_findings: List[VerifiedFinding] = []
    accessibility_violations: List[AccessibilityViolation]
    runtime_telemetry: RuntimeTelemetry
    execution_steps: List[Dict[str, Any]] = []
    provider_name: str = "Mock"
    is_mock_mode: bool = True
