from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AIAnalysisStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    AI_SKIPPED = "AI_SKIPPED"  # not called: provider preflight blocked, user chose deterministic-only
    EVALUATED = "EVALUATED"
    PROVIDER_NOT_EVALUABLE = "PROVIDER_NOT_EVALUABLE"
    RATE_LIMITED = "RATE_LIMITED"  # Provider refused the request (HTTP 429); AI reasoning unavailable
    REQUEST_FAILED = "REQUEST_FAILED"
    AI_RESPONSE_INVALID = "AI_RESPONSE_INVALID"
    RESPONSE_EMPTY = "RESPONSE_EMPTY"
    PARSE_FAILED = "PARSE_FAILED"
    SCHEMA_FAILED = "SCHEMA_FAILED"
    SUCCESS_ZERO_CANDIDATES = "SUCCESS_ZERO_CANDIDATES"
    SUCCESS_WITH_CANDIDATES = "SUCCESS_WITH_CANDIDATES"


class AIDiagnostics(BaseModel):
    """Pipeline diagnostics tracking every stage of AI candidate processing."""
    provider_name: str = "Mock"
    model_name: str = "default"
    requested_model: str = "default"
    actual_model: str = "default"
    fallback_used: bool = False
    status: AIAnalysisStatus = AIAnalysisStatus.NOT_RUN
    
    # Stage tracking flags
    ai_request_started: bool = False
    ai_request_succeeded: bool = False
    ai_raw_response_received: bool = False
    ai_response_length: int = 0
    ai_response_parsed: bool = False
    ai_schema_valid: bool = False

    # Screenshot provenance flags (Phase 5)
    screenshot_captured: bool = False
    screenshot_attached_to_request: bool = False
    multimodal_request: bool = False
    screenshot_evaluated_by_model: bool = False
    
    # Retry and Failure Classification Metadata
    failure_category: Optional[str] = None
    http_status: Optional[int] = None
    attempt_count: int = 0
    retry_count: int = 0
    retryable: bool = False
    quota_scope: Optional[str] = None  # DAILY | SHORT_TERM (RATE_LIMITED only)
    retry_after_seconds: Optional[float] = None
    rate_limit_kind: Optional[str] = None  # RPM | TPM | OTPM | RPD | TPD (as stated by the provider)
    provider_limit_status: Optional[str] = None  # e.g. RATE_LIMITED_TPM, QUOTA_EXHAUSTED_RPD, REQUEST_TOO_LARGE_OTPM
    
    # Preflight / provider-reported quota (only values actually present in provider responses)
    preflight_status: Optional[str] = None
    provider_rate_limit: Dict[str, Any] = Field(default_factory=dict)

    # Evidence packet / output contract
    max_findings_requested: Optional[int] = None
    evidence_packet_stats: Dict[str, Any] = Field(default_factory=dict)
    missing_rule_type_count: int = 0
    missing_why_ai_needed_count: int = 0
    ai_candidates_over_limit: int = 0

    # Candidate metrics
    ai_candidate_count_raw: int = 0
    ai_candidate_count_valid: int = 0
    ai_candidate_count_normalized: int = 0
    ai_candidate_count_deduplicated: int = 0
    independent_candidate_count: int = 0
    complementary_candidate_count: int = 0
    deterministic_duplicate_count: int = 0
    ai_duplicate_suppression_rate: float = 0.0
    ai_complementary_finding_rate: float = 0.0
    ai_deterministic_duplicate_rate: float = 0.0
    ai_candidate_count_confirmed: int = 0
    ai_candidate_count_likely: int = 0
    ai_candidate_count_uncertain: int = 0
    ai_candidate_count_verified: int = 0
    ai_candidate_count_rejected: int = 0
    schema_rejected_count: int = 0
    
    # Sanitized failure reasons (NO secret leaks)
    ai_failure_reason: Optional[str] = None
    ai_parse_failure_reason: Optional[str] = None
    ai_schema_failure_reason: Optional[str] = None
    ai_normalization_failure_reason: Optional[str] = None

    def reconcile_counts(self):
        """Enforces verified_count = confirmed_count + likely_count."""
        self.ai_candidate_count_verified = (
            self.ai_candidate_count_confirmed +
            self.ai_candidate_count_likely
        )
        if self.ai_candidate_count_raw > 0:
            self.ai_duplicate_suppression_rate = round(self.deterministic_duplicate_count / self.ai_candidate_count_raw, 4)
            self.ai_complementary_finding_rate = round(self.complementary_candidate_count / self.ai_candidate_count_raw, 4)
            self.ai_deterministic_duplicate_rate = round(self.deterministic_duplicate_count / self.ai_candidate_count_raw, 4)

    def to_summary_dict(self) -> Dict[str, Any]:
        self.reconcile_counts()
        return {
            "Provider": self.provider_name,
            "Model": self.model_name,
            "Requested Model": self.requested_model or self.model_name,
            "Actual Model": self.actual_model or self.model_name,
            "Fallback Used": self.fallback_used,
            "Preflight Status": self.preflight_status or "N/A",
            "Status": self.status.value,
            "Failure Category": self.failure_category or "None",
            "HTTP Status": self.http_status or "N/A",
            "Quota Scope": self.quota_scope or "N/A",
            "Provider Limit Status": self.provider_limit_status or "N/A",
            "Attempts": self.attempt_count,
            "Retries": self.retry_count,
            "Request Succeeded": self.ai_request_succeeded,
            "Response Parsed": self.ai_response_parsed,
            "Schema Valid": self.ai_schema_valid,
            "Screenshot Captured": self.screenshot_captured,
            "Screenshot Attached": self.screenshot_attached_to_request,
            "Multimodal Request": self.multimodal_request,
            "Screenshot Evaluated": self.screenshot_evaluated_by_model,
            "Max Candidates Requested": self.max_findings_requested if self.max_findings_requested is not None else "N/A",
            "Missing rule_type (rejected)": self.missing_rule_type_count,
            "Missing why_ai_needed": self.missing_why_ai_needed_count,
            "Over Candidate Limit (dropped)": self.ai_candidates_over_limit,
            "Raw Candidates": self.ai_candidate_count_raw,
            "Valid Candidates": self.ai_candidate_count_valid,
            "Normalized": self.ai_candidate_count_normalized,
            "Deduplicated": self.ai_candidate_count_deduplicated,
            "Independent": self.independent_candidate_count,
            "Complementary": self.complementary_candidate_count,
            "Deterministic Duplicates": self.deterministic_duplicate_count,
            "Suppression Rate": f"{self.ai_duplicate_suppression_rate * 100:.1f}%",
            "Complementary Rate": f"{self.ai_complementary_finding_rate * 100:.1f}%",
            "Confirmed": self.ai_candidate_count_confirmed,
            "Likely": self.ai_candidate_count_likely,
            "Uncertain": self.ai_candidate_count_uncertain,
            "Verified": self.ai_candidate_count_verified,
            "Rejected": self.ai_candidate_count_rejected,
            "Failure Reason": self.ai_failure_reason or self.ai_parse_failure_reason or self.ai_schema_failure_reason or "None",
            **self.provider_quota_summary()
        }

    def provider_quota_summary(self) -> Dict[str, Any]:
        """Provider-reported quota values, only when the provider actually supplied them."""
        rl = self.provider_rate_limit or {}
        out = {}
        if "limit_requests_per_day" in rl:
            out["Provider-reported limit (requests/day)"] = rl["limit_requests_per_day"]
        if "remaining_requests_per_day" in rl:
            out["Provider-reported remaining (requests/day)"] = rl["remaining_requests_per_day"]
        if "reset_requests" in rl:
            out["Provider-reported reset (requests)"] = rl["reset_requests"]
        if "remaining_tokens_per_minute" in rl:
            out["Provider-reported remaining (tokens/min)"] = rl["remaining_tokens_per_minute"]
        return out

