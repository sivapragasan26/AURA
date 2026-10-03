"""
The model call made in the browser, carried through AURA's own pipeline.

The hosted AURA service holds no provider API key. The extension calls the user's chosen provider itself
and brings the raw response back, so a scan is two short requests:

    POST /api/audits/prepare                evidence (no screenshot) -> {audit_id, prompt}
    ... the browser calls the provider with that prompt, its own screenshot and the user's key ...
    POST /api/audits/{audit_id}/complete    the raw model response -> parsed, verified, scored audit view

Nothing about the analysis changes. The prompt, the response schema, the independent verification, the
materiality gate, the correlation and the scoring are the same Python code as the local build and keep the
same tests. BrowserRelayProvider stands in for an AI provider so the pipeline runs unaltered: instead of
making an HTTP request it hands back the text the browser already collected. Being a provider that cannot
reach a network is the point - the server has no key to reach one with.

The prepared evidence waits in PendingScans between the two requests: in memory only, bounded in count and
in age, never written to disk. One scan must therefore reach one instance twice, which is why the hosted
deployment runs a single instance (see render.yaml).
"""
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from aura.agent.provider import AIProvider

# A prepared scan is only useful until the browser comes back with the model's answer. These bound what one
# process holds while waiting: a prepared bundle is roughly 1 MB of DOM and accessibility data.
PENDING_TTL_SECONDS = 600
MAX_PENDING = 12


class RelayProviderError(RuntimeError):
    """The browser's call to the provider failed. Carries the provider's own report, not a guess."""


def category_for(http_status: Optional[int], message: str = "") -> str:
    """
    How a provider's HTTP status becomes an AURA failure category.

    The same mapping the Python providers do, kept here so the policy stays in Python and under test rather
    than in the extension.
    """
    text = (message or "").lower()
    if http_status in (401, 403):
        return "AUTHENTICATION_ERROR"
    if http_status == 404:
        return "MODEL_NOT_FOUND"
    if http_status == 429:
        return "RATE_LIMITED"
    if http_status == 413 or "too large" in text or "request_too_large" in text:
        return "REQUEST_TOO_LARGE"
    return "TRANSIENT_PROVIDER_ERROR"


def quota_scope_for(category: str, message: str = "") -> Optional[str]:
    """DAILY only when the provider itself said so, never assumed from a bare 429."""
    if category != "RATE_LIMITED":
        return None
    text = (message or "").lower()
    if "per day" in text or "requests per day" in text or "daily" in text:
        return "DAILY"
    if "per minute" in text or "per_minute" in text:
        return "MINUTE"
    return None


class BrowserRelayProvider(AIProvider):
    """
    An AI provider that makes no request: the browser already made it.

    analyze() returns the raw response the extension reported, or raises RelayProviderError carrying the
    provider's own failure report. Everything the pipeline reads from a provider - provider_key, model,
    capabilities, last_execution_metadata - is the real provider's, so the audit records which model
    actually answered and the existing rate-limit bookkeeping keeps working.
    """

    # Marks this provider to the pipeline: there is nothing to preflight, because the call already happened.
    is_browser_relay = True

    def __init__(self, provider_key: str, model: str, *, raw_response: Optional[str] = None,
                 failure: Optional[Dict[str, Any]] = None, vision: bool = False,
                 screenshot_captured: bool = False, screenshot_attached: bool = False,
                 reported: Optional[Dict[str, Any]] = None) -> None:
        self.provider_key = provider_key or "unknown"
        self.model = model or "unknown"
        self.display_name = {"groq": "Groq", "openai": "OpenAI", "gemini": "Gemini",
                             "anthropic": "Anthropic", "mock": "Mock"}.get(self.provider_key, self.provider_key)
        self._raw = raw_response
        self._failure = failure
        self._vision = bool(vision)
        # Only the browser knows what it attached to the request it made, so it reports that and the
        # diagnostics use it rather than inferring from a screenshot the server never received.
        self.browser_screenshot = {"captured": bool(screenshot_captured), "attached": bool(screenshot_attached)}
        reported = reported or {}
        meta: Dict[str, Any] = {
            "provider": self.display_name,
            "api": "browser relay",
            "requested_model": self.model,
            "actual_model": reported.get("actual_model") or self.model,
            "fallback_used": False,
            "attempt_count": int(reported.get("attempt_count") or 1),
            "retry_count": int(reported.get("retry_count") or 0),
            "rate_limit": reported.get("rate_limit") or {},
        }
        if failure:
            message = str(failure.get("message") or "")
            category = failure.get("category") or category_for(failure.get("http_status"), message)
            meta.update({
                "status": "PROVIDER_NOT_EVALUABLE",
                "failure_category": category,
                "http_status": failure.get("http_status"),
                "quota_scope": failure.get("quota_scope") or quota_scope_for(category, message),
                "retry_after_seconds": failure.get("retry_after_seconds"),
                "rate_limit_kind": failure.get("rate_limit_kind"),
                "provider_limit_status": failure.get("provider_limit_status"),
                "retryable": category in ("RATE_LIMITED", "TRANSIENT_PROVIDER_ERROR"),
                "final_error": message,
            })
        else:
            meta.update({"status": "SUCCESS", "failure_category": None,
                         "http_status": reported.get("http_status") or 200, "retryable": False})
        self.last_execution_metadata = meta

    def analyze(self, prompt: str, screenshot_base64: Optional[str] = None, mime_type: str = "image/png") -> str:
        if self._failure:
            raise RelayProviderError(str(self._failure.get("message") or "The provider request failed."))
        return self._raw or "{}"

    def test_connection(self) -> Tuple[bool, str]:
        return False, "AURA holds no key for this provider: the browser calls it directly."

    def check_availability(self) -> Dict[str, Any]:
        return {"status": "READY", "http_status": None,
                "detail": "The browser calls this provider directly; AURA holds no key for it.",
                "provider_reported": {}}

    def capabilities(self) -> Optional[Dict[str, Any]]:
        return {"image_input": self._vision, "json_mode": True}


@dataclass
class PendingScan:
    bundle: Any
    prompt: str
    max_findings: int
    # What the browser said it would attach. That is what the prompt was built with, so it is also what the
    # pipeline is told later: the recorded prompt then matches the one the model actually received.
    screenshot_attached: bool
    screenshot_captured: bool
    # The install that prepared this scan. Only it can complete it: an audit id is a running number, and
    # finishing someone else's scan would hand over their page's evidence.
    owner: str = ""
    created_at: float = field(default_factory=time.time)


class PendingScans:
    """Prepared scans waiting for the browser's model response. In memory, bounded, nothing on disk."""

    def __init__(self, ttl: int = PENDING_TTL_SECONDS, limit: int = MAX_PENDING) -> None:
        self._ttl = ttl
        self._limit = limit
        self._lock = threading.Lock()
        self._items: "OrderedDict[str, PendingScan]" = OrderedDict()

    def _evict(self, now: float) -> None:
        for key in [k for k, v in self._items.items() if now - v.created_at > self._ttl]:
            self._items.pop(key, None)
        while len(self._items) > self._limit:
            self._items.popitem(last=False)

    def put(self, audit_id: str, scan: PendingScan) -> None:
        with self._lock:
            self._items[audit_id] = scan
            self._items.move_to_end(audit_id)
            self._evict(time.time())

    def take(self, audit_id: str, owner: str = "") -> Optional[PendingScan]:
        """
        Removes and returns the scan, for the install that prepared it.

        A prepared scan can be completed once, and only by its owner; anyone else is told there is no
        such scan waiting, which is what they would see for an id that never existed.
        """
        with self._lock:
            self._evict(time.time())
            held = self._items.get(audit_id)
            if held is None or held.owner != owner:
                return None
            return self._items.pop(audit_id)

    def __len__(self) -> int:
        with self._lock:
            self._evict(time.time())
            return len(self._items)
