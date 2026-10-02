import re
from typing import List, Tuple
from urllib.parse import urlparse
from aura.models.findings import (
    ConsoleError, NetworkFailure, ClassifiedRuntimeEvent, RuntimeCategory, RuntimeTelemetry
)

TELEMETRY_KEYWORDS = [
    "analytics", "telemetry", "tracking", "tracker", "segment.io", "mixpanel",
    "sentry", "hotjar", "datadog", "facebook.net", "google-analytics", "doubleclick",
    "clarity.ms", "posthog", "logrocket", "bugsnag", "ping"
]

THIRD_PARTY_KEYWORDS = [
    "cdn", "font", "gstatic", "cloudflare", "fontawesome", "typekit"
]


class RuntimeAnalyzer:
    """Classifies browser console errors and network response failures into structured categories."""

    def classify_telemetry(self, telemetry: RuntimeTelemetry) -> List[ClassifiedRuntimeEvent]:
        """Analyzes raw console errors and network failures, returning classified runtime events."""
        events: List[ClassifiedRuntimeEvent] = []

        # 1. Process Console Errors
        for c_err in telemetry.console_errors:
            cat, deduction = self._classify_console_error(c_err, telemetry.url)
            c_err.category = cat
            ownership = "THIRD_PARTY" if cat in (RuntimeCategory.THIRD_PARTY_FAILURE, RuntimeCategory.TELEMETRY_FAILURE) else ("BROWSER" if cat == RuntimeCategory.WARNING else ("AURA_INFRASTRUCTURE" if "aura" in c_err.text.lower() else "TARGET_APPLICATION"))
            events.append(
                ClassifiedRuntimeEvent(
                    category=cat,
                    source="console",
                    title=f"Console {c_err.type.upper()}: {cat.value}",
                    detail=c_err.text[:200],
                    deduction=deduction,
                    ownership=ownership,
                    event_type=c_err.type,
                    triggered_by=c_err.triggered_by
                )
            )

        # 2. Process Network Failures
        for n_fail in telemetry.network_failures:
            cat, deduction = self._classify_network_failure(n_fail, telemetry.url)
            n_fail.category = cat
            ownership = "THIRD_PARTY" if cat in (RuntimeCategory.THIRD_PARTY_FAILURE, RuntimeCategory.TELEMETRY_FAILURE) else ("AURA_INFRASTRUCTURE" if "aura" in n_fail.url.lower() else "TARGET_APPLICATION")
            events.append(
                ClassifiedRuntimeEvent(
                    category=cat,
                    source="network",
                    title=f"HTTP {n_fail.status} Failure: {cat.value}",
                    detail=f"{n_fail.method} {n_fail.url}",
                    deduction=deduction,
                    ownership=ownership,
                    event_type=str(n_fail.status),
                    url=n_fail.url
                )
            )

        telemetry.classified_events = events
        return events

    def _classify_console_error(self, c_err: ConsoleError, page_url: str = "") -> Tuple[RuntimeCategory, int]:
        txt_lower = c_err.text.lower()
        
        if c_err.type == "warning":
            return RuntimeCategory.WARNING, 1

        # Ownership is decided by where the message came from, not by words inside it: an application
        # error whose text happens to say "Telemetry" is still an application error. Resource-load
        # failures are the exception, since their text names the failing (possibly third-party) resource.
        loc_url = re.sub(r":\d*$", "", (c_err.location or "").strip()).lower()
        ownership_evidence = loc_url
        if txt_lower.startswith("failed to load resource"):
            ownership_evidence = f"{loc_url} {txt_lower}"

        if any(kw in ownership_evidence for kw in TELEMETRY_KEYWORDS):
            return RuntimeCategory.TELEMETRY_FAILURE, 1

        loc_domain = urlparse(loc_url).netloc
        page_domain = urlparse(page_url).netloc.lower()
        if any(kw in ownership_evidence for kw in THIRD_PARTY_KEYWORDS) or (loc_domain and page_domain and loc_domain != page_domain):
            return RuntimeCategory.THIRD_PARTY_FAILURE, 2

        if c_err.type == "exception" or "uncaught" in txt_lower or "referenceerror" in txt_lower or "typeerror" in txt_lower:
            return RuntimeCategory.APPLICATION_ERROR, 25

        return RuntimeCategory.APPLICATION_ERROR, 10

    def _classify_network_failure(self, n_fail: NetworkFailure, page_url: str) -> Tuple[RuntimeCategory, int]:
        url_lower = n_fail.url.lower()

        # Check telemetry / analytics
        if any(kw in url_lower for kw in TELEMETRY_KEYWORDS):
            return RuntimeCategory.TELEMETRY_FAILURE, 1

        # Check third party CDN / asset host
        page_domain = urlparse(page_url).netloc.lower()
        req_domain = urlparse(n_fail.url).netloc.lower()

        if req_domain and page_domain and page_domain not in req_domain and req_domain not in page_domain:
            if any(kw in url_lower for kw in THIRD_PARTY_KEYWORDS):
                return RuntimeCategory.THIRD_PARTY_FAILURE, 2
            return RuntimeCategory.THIRD_PARTY_FAILURE, 4

        # Core app API endpoint or 5xx server error
        if n_fail.status >= 500 or "/api/" in url_lower or "graphql" in url_lower:
            return RuntimeCategory.API_ERROR, 20

        if n_fail.status == 0 or "failed" in n_fail.status_text.lower():
            return RuntimeCategory.NETWORK_FAILURE, 8

        return RuntimeCategory.API_ERROR, 10
