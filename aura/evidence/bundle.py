"""
EvidenceBundle: browser evidence collected OUTSIDE the engine (the AURA Chrome extension, in the user's own tab).

It carries the same raw evidence the Playwright collector produces (raw DOM extraction from the shared
aura/analyzers/js/dom_extraction.js, raw axe-core violations, runtime telemetry, controlled-interaction log and
one viewport screenshot), so AURAOrchestrator.analyze_evidence() can run the SAME analysis pipeline on it.

Privacy is enforced twice: the extension strips it at collection time and this model sanitizes again
(query strings/fragments removed from URLs, obvious secrets redacted from text, sizes bounded). Ground truth is
never part of a bundle: the engine only reads it from disk in Test Lab evaluation.
"""
import re
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_ELEMENTS = 3000
MAX_AXE_VIOLATIONS = 200
MAX_AXE_NODES = 50
MAX_CONSOLE = 100
MAX_NETWORK = 200
MAX_INTERACTIONS = 30
MAX_TEXT = 300
# ~10 MB of base64 PNG: a 1920x1080 viewport screenshot is typically well below 3 MB
MAX_SCREENSHOT_B64 = 10_000_000
# A second, full-page capture used only for the panel's per-finding screenshots. It is never sent to an
# AI provider, so it does not affect the size of a provider request.
MAX_FULLPAGE_B64 = 7_000_000

_SECRET_PATTERNS = [
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"), "[REDACTED_JWT]"),
    (re.compile(r"\b(?:sk|pk|rk|gsk|ghp|gho|xox[abp])[-_][A-Za-z0-9_\-]{12,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.=]{10,}", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_NUMBER]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
]


def redact_text(value: Any, limit: int = MAX_TEXT) -> Any:
    """Redacts obvious secrets/personal identifiers from free text and bounds its length."""
    if not isinstance(value, str):
        return value
    for pattern, repl in _SECRET_PATTERNS:
        value = pattern.sub(repl, value)
    return value[:limit]


def strip_url(url: Any) -> Any:
    """Removes query string and fragment (they can carry tokens or personal data). Placeholder hrefs are kept."""
    if not isinstance(url, str):
        return url
    u = url.strip()
    low = u.lower()
    if u in ("", "#") or low.startswith("javascript:"):
        return "javascript:" if low.startswith("javascript:") else u
    if u.startswith("#"):
        return "#"
    try:
        parts = urlsplit(u)
    except ValueError:
        return u.split("?", 1)[0].split("#", 1)[0]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class RawDomExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    doc_scroll_width: int = 0
    doc_client_width: int = 0
    has_horizontal_overflow: bool = False
    elements: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("elements")
    @classmethod
    def _sanitize_elements(cls, elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for e in elements[:MAX_ELEMENTS]:
            if not isinstance(e, dict):
                continue
            e = dict(e)
            for k in ("text", "accessible_name", "aria_label", "placeholder", "alt"):
                if k in e:
                    e[k] = redact_text(e[k], 100 if k in ("text", "accessible_name") else 200)
            for k in ("href", "src"):
                if k in e:
                    e[k] = strip_url(e[k])
            out.append(e)
        return out


class AxeNode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    target: List[str] = Field(default_factory=list)

    @field_validator("target", mode="before")
    @classmethod
    def _flatten(cls, value: Any) -> List[str]:
        # axe uses nested arrays for iframe / shadow-DOM targets; keep only plain document selectors
        return [t for t in (value or []) if isinstance(t, str)][:5]


class AxeViolation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    impact: Optional[str] = "moderate"
    description: str = ""
    helpUrl: Optional[str] = None
    nodes: List[AxeNode] = Field(default_factory=list)

    @field_validator("nodes")
    @classmethod
    def _bound(cls, nodes: List[AxeNode]) -> List[AxeNode]:
        return nodes[:MAX_AXE_NODES]


class AxeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    available: bool = False  # False: axe-core could not run in the page; accessibility is NOT evaluated
    version: Optional[str] = None
    error: Optional[str] = None
    violations: List[AxeViolation] = Field(default_factory=list)

    @field_validator("violations")
    @classmethod
    def _bound(cls, v: List[AxeViolation]) -> List[AxeViolation]:
        return v[:MAX_AXE_VIOLATIONS]


class ConsoleEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["error", "warning", "exception"]
    text: str
    location: Optional[str] = None
    triggered_by: Optional[str] = None

    @field_validator("text")
    @classmethod
    def _redact(cls, v: str) -> str:
        return redact_text(v)

    @field_validator("location")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        m = re.match(r"^(.*?)(:\d+)?$", v)
        return f"{strip_url(m.group(1))}{m.group(2) or ''}" if m else strip_url(v)


class NetworkEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    status: int
    status_text: str = ""
    method: str = "GET"

    @field_validator("url")
    @classmethod
    def _strip(cls, v: str) -> str:
        return strip_url(v)


class Telemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # "post_load": the extension attached after the page loaded, so console errors/exceptions raised during
    # page load are NOT in this bundle (failed resource loads are, via the Resource Timing API).
    capture_scope: Literal["post_load", "full_load"] = "post_load"
    page_load_time_ms: float = 0.0
    console: List[ConsoleEvent] = Field(default_factory=list)
    network: List[NetworkEvent] = Field(default_factory=list)

    @field_validator("console")
    @classmethod
    def _bound_console(cls, v):
        return v[:MAX_CONSOLE]

    @field_validator("network")
    @classmethod
    def _bound_network(cls, v):
        return v[:MAX_NETWORK]


class InteractionRecord(BaseModel):
    """Same fields as BrowserAgent._perform() log entries, so the verifier treats both paths identically."""
    model_config = ConfigDict(extra="ignore")
    hypothesis: str = ""
    action: Literal["click", "hover", "scroll"]
    target: str
    element_selector: str
    element_id_chain: List[str] = Field(default_factory=list)
    target_text: str = ""
    trigger: str = "planned"
    status: Literal["executed", "blocked", "failed", "skipped"]
    reason: str = ""
    dom_changed: Optional[bool] = None
    url_changed: Optional[bool] = None
    errors_after_action: List[str] = Field(default_factory=list)
    timestamp: Optional[str] = None

    @field_validator("target_text", "reason", "hypothesis")
    @classmethod
    def _redact(cls, v: str) -> str:
        return redact_text(v)

    @field_validator("errors_after_action")
    @classmethod
    def _redact_list(cls, v: List[str]) -> List[str]:
        return [redact_text(t) for t in v[:3]]


class Viewport(BaseModel):
    width: int = Field(ge=200, le=10000)
    height: int = Field(ge=200, le=10000)


class EvidenceBundle(BaseModel):
    # Unknown fields are ignored, not refused. The extension and the server are upgraded independently —
    # the extension by reloading it, the server by restarting a long-running process — so a newer
    # extension routinely talks to an older server. Refusing an unrecognised field made that skew fail the
    # whole scan ("Evidence bundle failed validation") instead of costing only the extra evidence.
    # Everything else still applies: the pairing token, the loopback and origin checks, the body size
    # limit, every max_length below, and the URL and redaction validators.
    # tests/test_extension_api.py diffs the keys the extension sends against the fields declared here, so
    # a field that goes missing or gets misspelled is caught by the suite rather than silently dropped.
    model_config = ConfigDict(extra="ignore")

    source: Literal["extension"] = "extension"
    collector_version: str = Field(max_length=40)
    url: str = Field(max_length=2048)
    title: str = Field(default="", max_length=500)
    viewport: Viewport
    dom: RawDomExtraction
    axe: AxeResult
    telemetry: Telemetry = Field(default_factory=Telemetry)
    interactions: List[InteractionRecord] = Field(default_factory=list)
    screenshot_png_base64: Optional[str] = Field(default=None, max_length=MAX_SCREENSHOT_B64)
    screenshot_fullpage_png_base64: Optional[str] = Field(default=None, max_length=MAX_FULLPAGE_B64)
    # Where the reported elements sat on the page when the capture was taken, keyed by the selector the
    # finding will carry. Geometry only; used to crop the capture to a finding.
    target_boxes: Dict[str, Dict[str, float]] = Field(default_factory=dict, max_length=600)
    captured_at: Optional[str] = Field(default=None, max_length=64)

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        parts = urlsplit(v.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("Only http(s) pages can be audited")
        return strip_url(v)

    @field_validator("title")
    @classmethod
    def _redact_title(cls, v: str) -> str:
        return redact_text(v, 200)

    @field_validator("interactions")
    @classmethod
    def _bound_interactions(cls, v):
        return v[:MAX_INTERACTIONS]
