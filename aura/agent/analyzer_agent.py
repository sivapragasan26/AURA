import json
import re
from typing import Dict, Any, List, Optional
from aura.config import settings
from aura.agent.schemas import RawAICandidatePayload, AICandidateOutput
from aura.agent.evidence_packet import build_evidence_packet
from aura.agent.provider_status import ProviderStateStore
from aura.security.credentials import sanitize_provider_error
from aura.agent.diagnostics import AIDiagnostics, AIAnalysisStatus
from aura.agent.providers import get_ai_provider
from aura.agent.provider import AIProvider
from aura.config.models import MODEL_CAPABILITIES
from aura.analyzers.screenshot_analyzer import ScreenshotAnalyzer
from aura.models.findings import CandidateFinding, RuntimeTelemetry, AccessibilityViolation
from aura.utils.logger import logger


CANONICAL_RULE_MAP = {
    # UI Defects
    "bad_visual_hierarchy": "bad_visual_hierarchy",
    "visual_hierarchy": "bad_visual_hierarchy",
    "inverted_hierarchy": "bad_visual_hierarchy",
    "weak_primary_cta": "weak_primary_cta",
    "weak_cta": "weak_primary_cta",
    "insufficient_cta_prominence": "weak_primary_cta",
    "competing_cta": "competing_cta",
    "poor_spacing_consistency": "poor_spacing_consistency",
    "poor_spacing": "poor_spacing_consistency",
    "poor_alignment": "poor_alignment",
    "misaligned_elements": "poor_alignment",
    "inconsistent_component_styling": "inconsistent_component_styling",
    "inconsistent_components": "inconsistent_component_styling",
    "typography_hierarchy_issue": "typography_hierarchy_issue",
    "excessive_information_density": "excessive_information_density",
    "poor_information_density": "excessive_information_density",
    "poor_grouping": "poor_grouping",
    "misleading_visual_emphasis": "misleading_visual_emphasis",
    "unclear_interactive_affordance": "unclear_interactive_affordance",
    "poor_responsive_visual_layout": "poor_responsive_visual_layout",
    "excessive_horizontal_scanning": "excessive_horizontal_scanning",
    "visually_hidden_important_information": "visually_hidden_important_information",
    "inconsistent_state_styling": "inconsistent_state_styling",

    # UX Defects
    "confusing_form": "confusing_form",
    "unclear_form_flow": "confusing_form",
    "bad_navigation": "bad_navigation",
    "bad_nav": "bad_navigation",
    "unclear_information_architecture": "unclear_information_architecture",
    "ambiguous_label": "ambiguous_label",
    "unclear_instruction": "unclear_instruction",
    "excessive_form_complexity": "excessive_form_complexity",
    "unnecessary_user_step": "unnecessary_user_step",
    "poor_error_recovery": "poor_error_recovery",
    "insufficient_feedback": "insufficient_feedback",
    "misleading_feedback": "misleading_feedback",
    "poor_task_flow": "poor_task_flow",
    "discoverability_problem": "discoverability_problem",
    "cognitive_load_problem": "cognitive_load_problem",
    "unexpected_behavior": "unexpected_behavior",
    "dead_end_workflow": "dead_end_workflow",
    "unclear_system_status": "unclear_system_status",
    "destructive_action_without_clear_warning": "destructive_action_without_clear_warning",
    "inconsistent_workflow_behavior": "inconsistent_workflow_behavior",
    "unclear_error_message": "poor_error_recovery",

    # Interaction Defects
    "interaction_failure": "interaction_failure",
    "non_responsive_control": "non_responsive_control",
    "click_without_feedback": "click_without_feedback",
    "incorrect_state_transition": "incorrect_state_transition",
    "broken_toggle": "broken_toggle",
    "broken_menu": "broken_menu",
    "broken_modal": "broken_modal",
    "broken_form_submission": "broken_form_submission",
    "validation_feedback_failure": "validation_feedback_failure",
    "hover_affordance_mismatch": "hover_affordance_mismatch",
    "disabled_control_confusion": "disabled_control_confusion",
    "interaction_dead_end": "interaction_dead_end",
    "dead_button": "interaction_failure",
    "false_affordance": "false_affordance",
    "fake_button": "false_affordance",
    "non_actionable_control": "false_affordance",

    # Responsive Defects
    "horizontal_overflow": "horizontal_overflow",
    "horizontal_content_overflow": "horizontal_overflow",
    "clipped_content": "clipped_content",
    "overlapping_elements": "overlapping_elements",
    "offscreen_control": "offscreen_control",
    "broken_mobile_navigation": "broken_mobile_navigation",
    "unusable_mobile_form": "unusable_mobile_form",
    "excessive_horizontal_scrolling": "horizontal_overflow",
    "responsive_spacing_failure": "responsive_spacing_failure",
    "responsive_typography_failure": "responsive_typography_failure",
    "viewport_specific_visibility_failure": "viewport_specific_visibility_failure",
    "mobile_layout_break": "horizontal_overflow",

    # Accessibility & Runtime Canonical Aliases
    "image_alt": "image_alt_missing",
    "missing_alt": "image_alt_missing",
    "color_contrast": "color_contrast",
    "button_name": "unlabelled_button",
    "label": "missing_label"
}


def normalize_rule_type(rule: str) -> str:
    if not rule:
        return "ui_defect"
    clean_rule = rule.strip().lower().replace("-", "_")
    return CANONICAL_RULE_MAP.get(clean_rule, clean_rule)


DETERMINISTIC_RULE_TYPES = {
    "image_alt", "missing_alt", "image_alt_missing", "color_contrast", "heading_order",
    "landmark_one_main", "region", "unlabelled_button", "missing_label", "button_name",
    "link_name", "console_error", "uncaught_exception", "application_console_error",
    "application_runtime_exception", "api_404", "network_failure", "application_network_failure",
    "initialization_error", "http_failure", "horizontal_overflow", "horizontal_content_overflow",
    "excessive_horizontal_scrolling", "mobile_layout_break", "clipped_content", "offscreen_control"
}

COMPLEMENTARY_UX_RULES = {
    "insufficient_feedback", "poor_error_recovery", "unclear_system_status", "misleading_feedback",
    "unusable_mobile_form", "broken_mobile_navigation", "cognitive_load_problem", "discoverability_problem"
}


RUNTIME_CONSOLE_RULES = {"console_error", "uncaught_exception", "application_console_error", "application_runtime_exception", "initialization_error"}
RUNTIME_NETWORK_RULES = {"api_404", "network_failure", "application_network_failure", "http_failure"}

# Keyword in a free-text rule -> deterministic rules it would duplicate (only if actually observed)
DETERMINISTIC_KEYWORD_FAMILIES = {
    "alt": {"image_alt_missing"},
    "contrast": {"color_contrast"},
    "landmark": {"landmark_one_main", "region"},
    "console": RUNTIME_CONSOLE_RULES,
    "404": RUNTIME_NETWORK_RULES,
    "500": RUNTIME_NETWORK_RULES,
    "network": RUNTIME_NETWORK_RULES,
}


def observed_deterministic_rules(accessibility_violations: List[AccessibilityViolation], telemetry: Optional[RuntimeTelemetry]) -> set:
    """Normalized rule identifiers that deterministic tools actually reported in this audit."""
    rules = {normalize_rule_type(v.rule) for v in accessibility_violations}
    if telemetry is not None:
        if any(c.type.lower() in ("error", "exception") for c in telemetry.console_errors):
            rules |= RUNTIME_CONSOLE_RULES
        if telemetry.network_failures:
            rules |= RUNTIME_NETWORK_RULES
    return rules


def classify_ai_contribution(rule_type: str, title: str = "", description: str = "", confidence: float = 0.8,
                             deterministic_rules: Optional[set] = None) -> tuple[str, float]:
    """
    Classifies AI candidate contribution type and calculates ai_contribution_score (0.0 to 1.0).
    Types: NOVEL_AI_INSIGHT, COMPLEMENTARY_INTERPRETATION, DETERMINISTIC_DUPLICATE

    deterministic_rules: normalized rules that deterministic tools actually reported in this audit.
    When given, a candidate is only a DETERMINISTIC_DUPLICATE if it repeats one of those observations;
    a rule no deterministic tool reported (e.g. horizontal_overflow, which has no deterministic producer)
    cannot be a duplicate. When omitted, the rule-name heuristic is used.
    """
    rule_clean = (rule_type or "").strip().lower().replace("-", "_")
    norm_rule = CANONICAL_RULE_MAP.get(rule_clean, rule_clean)
    text = f"{rule_clean} {norm_rule} {title} {description}".lower()

    # Check if rule is complementary UX rule
    if norm_rule in COMPLEMENTARY_UX_RULES or any(kw in text for kw in ["recovery", "user is not informed", "feedback", "no error state", "system status", "user guidance"]):
        return "COMPLEMENTARY_INTERPRETATION", 0.80

    # Check if candidate is pure deterministic duplicate
    if deterministic_rules is not None:
        is_duplicate = norm_rule in deterministic_rules or any(
            re.search(r"(?<![a-z])" + kw + r"(?![a-z])", rule_clean) and (family & deterministic_rules)
            for kw, family in DETERMINISTIC_KEYWORD_FAMILIES.items()
        )
    else:
        is_duplicate = norm_rule in DETERMINISTIC_RULE_TYPES or any(kw in rule_clean for kw in ["alt", "contrast", "landmark", "console", "404", "500", "network"])
    if is_duplicate:
        if any(kw in text for kw in ["recovery guidance", "unclear error", "no feedback", "user unable"]):
            return "COMPLEMENTARY_INTERPRETATION", 0.70
        else:
            return "DETERMINISTIC_DUPLICATE", 0.0

    score = 1.0 if confidence >= 0.80 else 0.85
    return "NOVEL_AI_INSIGHT", score


class AnalyzerAgent:
    """Orchestrates AI analysis by formatting runtime evidence into structured LLM prompts for Candidate Findings."""

    def __init__(self, provider: Optional[AIProvider] = None):
        self.provider = provider or get_ai_provider()
        self.screenshot_analyzer = ScreenshotAnalyzer()
        self.last_packet = None

    def analyze(
        self,
        telemetry: RuntimeTelemetry,
        dom_summary: Dict[str, Any],
        accessibility_violations: List[AccessibilityViolation],
        screenshot_path: Optional[str] = None,
        interaction_log: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Runs multimodal AI analysis on the focused evidence packet; returns summary, issues and diagnostics."""
        provider_name = self.provider.__class__.__name__.replace("Provider", "")
        model_name = getattr(self.provider, "model", "default")
        provider_key = getattr(self.provider, "provider_key", "unknown")

        diagnostics = AIDiagnostics(
            provider_name=provider_name,
            model_name=model_name,
            requested_model=model_name,
            actual_model=model_name,
            ai_request_started=True
        )

        # 1. Screenshot + focused evidence packet (the only evidence the AI receives)
        screenshot_payload = {"available": False, "base64_data": None, "mime_type": "image/png"}
        if screenshot_path:
            screenshot_payload = self.screenshot_analyzer.prepare_screenshot_payload(screenshot_path)
        packet = build_evidence_packet(
            telemetry=telemetry,
            dom_summary=dom_summary,
            accessibility_violations=accessibility_violations,
            interaction_log=interaction_log,
            screenshot_base64=screenshot_payload.get("base64_data"),
            screenshot_mime=screenshot_payload.get("mime_type") or "image/png",
        )
        self.last_packet = packet
        diagnostics.max_findings_requested = packet.max_findings
        diagnostics.evidence_packet_stats = {
            "targeted_elements": len(packet.targeted_dom),
            "interactions": len(packet.interactions),
            "accessibility_summaries": len(packet.deterministic_findings.get("accessibility", [])),
            "runtime_events": len(packet.deterministic_findings.get("runtime", [])),
            "screenshot_attached": bool(packet.screenshot_base64),
            "prompt_chars": len(packet.to_prompt()),
        }

        # Phase 5: Screenshot Provenance Tracking
        caps = getattr(self.provider, "capabilities", lambda: None)() or MODEL_CAPABILITIES.get(model_name, {})
        supports_vision = bool(caps.get("image_input", False)) if isinstance(caps, dict) else False
        diagnostics.screenshot_captured = bool(screenshot_payload.get("available"))
        diagnostics.screenshot_attached_to_request = bool(packet.screenshot_base64)
        diagnostics.multimodal_request = bool(packet.screenshot_base64 and supports_vision)
        diagnostics.screenshot_evaluated_by_model = bool(packet.screenshot_base64 and supports_vision)

        # 2. Invoke AI provider
        try:
            raw_response = self.provider.analyze_packet(packet)
            diagnostics.ai_request_succeeded = True
            diagnostics.ai_raw_response_received = True
            diagnostics.ai_response_length = len(raw_response or "")
            prov_meta = getattr(self.provider, "last_execution_metadata", {}) or {}
            if prov_meta:
                diagnostics.requested_model = prov_meta.get("requested_model", model_name)
                diagnostics.actual_model = prov_meta.get("actual_model", model_name)
                diagnostics.fallback_used = prov_meta.get("fallback_used", False)
                diagnostics.attempt_count = prov_meta.get("attempt_count", 1)
                diagnostics.retry_count = prov_meta.get("retry_count", 0)
                diagnostics.http_status = prov_meta.get("http_status")
                diagnostics.provider_rate_limit = prov_meta.get("rate_limit") or {}
                ProviderStateStore.record(provider_key, model_name, prov_meta)

        except Exception as e:
            err_msg = sanitize_provider_error(str(e))
            logger.error(f"AI Provider execution failed: {err_msg}")

            prov_meta = getattr(self.provider, "last_execution_metadata", {}) or {}
            ProviderStateStore.record(provider_key, model_name, prov_meta)
            diagnostics.failure_category = prov_meta.get("failure_category", "TRANSIENT_PROVIDER_ERROR")
            diagnostics.http_status = prov_meta.get("http_status", 500)
            diagnostics.quota_scope = prov_meta.get("quota_scope")
            diagnostics.retry_after_seconds = prov_meta.get("retry_after_seconds")
            diagnostics.provider_rate_limit = prov_meta.get("rate_limit") or {}
            diagnostics.rate_limit_kind = prov_meta.get("rate_limit_kind")
            diagnostics.provider_limit_status = prov_meta.get("provider_limit_status")
            if diagnostics.failure_category == "RATE_LIMITED":
                diagnostics.status = AIAnalysisStatus.RATE_LIMITED
                if diagnostics.quota_scope == "DAILY":
                    reason = f"{provider_name} daily quota/rate limit reached (HTTP 429). Wait for the quota to reset or select another configured provider."
                else:
                    reason = f"{provider_name} rate limit reached (HTTP 429). Retry later or select another configured provider."
                diagnostics.ai_failure_reason = f"{reason} Provider message: {err_msg}"
            elif diagnostics.failure_category == "REQUEST_TOO_LARGE":
                diagnostics.status = AIAnalysisStatus.PROVIDER_NOT_EVALUABLE
                diagnostics.ai_failure_reason = (f"{provider_name} rejected the request as larger than a per-minute limit "
                                                 f"({diagnostics.provider_limit_status}); this is not quota exhaustion and "
                                                 f"the unchanged request is not retried. Provider message: {err_msg}")
            else:
                diagnostics.status = AIAnalysisStatus.PROVIDER_NOT_EVALUABLE
                diagnostics.ai_failure_reason = f"Provider request failed: {err_msg}"
            diagnostics.attempt_count = prov_meta.get("attempt_count", 1)
            diagnostics.retry_count = prov_meta.get("retry_count", 0)
            diagnostics.requested_model = prov_meta.get("requested_model", model_name)
            diagnostics.actual_model = prov_meta.get("actual_model", model_name)
            diagnostics.fallback_used = prov_meta.get("fallback_used", False)

            return {
                "overall_summary": f"AI analysis unavailable ({err_msg}). Runtime & Accessibility evidence remain verified.",
                "issues": [],
                "diagnostics": diagnostics
            }

        # 3. Parse and validate JSON response
        return self._parse_and_process_response(
            raw_response, diagnostics,
            deterministic_rules=observed_deterministic_rules(accessibility_violations, telemetry),
            resolve_ref=packet.resolve_ref,
            max_findings=packet.max_findings
        )

    def _parse_and_process_response(self, raw_text: str, diagnostics: AIDiagnostics,
                                     deterministic_rules: Optional[set] = None,
                                     resolve_ref=None, max_findings: Optional[int] = None) -> Dict[str, Any]:
        """Cleans, extracts JSON, validates schema, normalizes rule types, and deduplicates candidates."""
        cleaned_text = (raw_text or "").strip()
        if not cleaned_text:
            diagnostics.status = AIAnalysisStatus.RESPONSE_EMPTY
            diagnostics.status = AIAnalysisStatus.AI_RESPONSE_INVALID
            diagnostics.ai_failure_reason = "Received empty response text from AI provider."
            return {
                "overall_summary": "AI provider returned empty response.",
                "issues": [],
                "diagnostics": diagnostics
            }

        # JSON Extraction (Markdown code fence regex or raw string search)
        json_str = cleaned_text
        if json_str.startswith("```"):
            json_str = re.sub(r"^```(?:json)?\n?", "", json_str)
            json_str = re.sub(r"\n?```$", "", json_str).strip()
        else:
            match = re.search(r"(\{[\s\S]*\})", json_str)
            if match:
                json_str = match.group(1).strip()

        try:
            parsed_data = json.loads(json_str)
            diagnostics.ai_response_parsed = True
        except Exception as e:
            diagnostics.status = AIAnalysisStatus.PARSE_FAILED
            diagnostics.ai_parse_failure_reason = f"JSON parse error: {str(e)}"
            logger.warning(f"AI Response JSON parsing failed: {e}")
            return {
                "overall_summary": f"Failed to parse Candidate Findings JSON: {str(e)}",
                "issues": [],
                "diagnostics": diagnostics
            }

        # Extract raw candidate items from 'candidates' or 'issues' array
        raw_items = []
        if isinstance(parsed_data, dict):
            raw_items = parsed_data.get("candidates", []) or parsed_data.get("issues", [])
        elif isinstance(parsed_data, list):
            raw_items = parsed_data

        diagnostics.ai_candidate_count_raw = len(raw_items)

        # Validate Schema and Build CandidateFinding Objects
        valid_candidates: List[CandidateFinding] = []
        rejected_cnt = 0

        missing_rule_cnt = 0
        for idx, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                rejected_cnt += 1
                continue
            # rule_type is mandatory and is never inferred from the title
            if not isinstance(item.get("rule_type"), str) or not item["rule_type"].strip():
                rejected_cnt += 1
                missing_rule_cnt += 1
                continue
            cand = None
            # 1. Current contract (prompts.AURA_SYSTEM_PROMPT); 2-3. legacy shapes that still carry rule_type
            try:
                cand = AICandidateOutput(**item).to_candidate_finding(index=idx, resolve_ref=resolve_ref)
            except Exception:
                try:
                    cand = RawAICandidatePayload(**item).to_candidate_finding(index=idx)
                except Exception:
                    try:
                        cand = CandidateFinding(**{"id": f"AURA-AI-CAND-{idx:03d}", **item})
                    except Exception as e:
                        logger.debug(f"Rejected malformed AI candidate item: {e}")
            if cand is None:
                rejected_cnt += 1
                continue
            if not cand.why_ai_needed and item.get("why_ai_needed"):
                cand.why_ai_needed = str(item["why_ai_needed"])
            if not cand.why_ai_needed:
                diagnostics.missing_why_ai_needed_count += 1
            valid_candidates.append(cand)

        diagnostics.missing_rule_type_count = missing_rule_cnt

        diagnostics.schema_rejected_count = rejected_cnt
        diagnostics.ai_candidate_count_valid = len(valid_candidates)

        if rejected_cnt > 0 and len(valid_candidates) == 0:
            diagnostics.status = AIAnalysisStatus.SCHEMA_FAILED
            diagnostics.ai_schema_failure_reason = f"All {rejected_cnt} raw candidates failed schema validation."
            return {
                "overall_summary": "All AI candidate payloads failed schema validation.",
                "issues": [],
                "diagnostics": diagnostics
            }

        diagnostics.ai_schema_valid = True

        # Rule Type Normalization & ID Assignment
        normalized_candidates: List[CandidateFinding] = []
        for idx, cand in enumerate(valid_candidates, start=1):
            cand_id = f"AI-{idx:03d}"
            cand.candidate_id = cand_id
            if cand.raw_rule_type is None:
                cand.raw_rule_type = cand.rule_type
            raw_rule = cand.rule_type or cand.title
            canonical_rule = normalize_rule_type(raw_rule)
            cand.rule_type = canonical_rule
            cand.normalized_rule = canonical_rule
            cand.claim = f"Rule: {canonical_rule} | {cand.title}"
            
            target_str = "body"
            if cand.affected_element:
                if isinstance(cand.affected_element, str):
                    target_str = cand.affected_element
                elif hasattr(cand.affected_element, "selector") and cand.affected_element.selector:
                    target_str = cand.affected_element.selector
            
            cand.target_identity = {
                "selector": target_str,
                "rule": canonical_rule
            }
            normalized_candidates.append(cand)

        diagnostics.ai_candidate_count_normalized = len(normalized_candidates)

        # Deduplication: retain highest-confidence candidate per (canonical_rule, target)
        dedup_map: Dict[str, CandidateFinding] = {}
        for cand in normalized_candidates:
            target_str = cand.target_identity.get("selector", "body") if cand.target_identity else "body"
            canonical_rule = cand.normalized_rule or normalize_rule_type(cand.rule_type or cand.title)
            key = f"{canonical_rule}::{target_str}"

            if key not in dedup_map or cand.confidence > dedup_map[key].confidence:
                dedup_map[key] = cand

        deduplicated_candidates = list(dedup_map.values())
        diagnostics.ai_candidate_count_deduplicated = len(deduplicated_candidates)

        # AI Contribution Classification & Duplicate Suppression (Threshold = 0.50)
        AI_INDEPENDENT_THRESHOLD = 0.50
        final_candidates: List[CandidateFinding] = []
        suppressed_candidates: List[CandidateFinding] = []
        c_seq = 1

        for cand in deduplicated_candidates:
            contrib_type, contrib_score = classify_ai_contribution(
                rule_type=cand.normalized_rule or cand.rule_type or cand.title,
                title=cand.title,
                description=cand.description,
                confidence=cand.confidence,
                deterministic_rules=deterministic_rules
            )
            cand.ai_contribution_type = contrib_type
            cand.ai_contribution_score = contrib_score

            if contrib_type == "NOVEL_AI_INSIGHT":
                diagnostics.independent_candidate_count += 1
            elif contrib_type == "COMPLEMENTARY_INTERPRETATION":
                diagnostics.complementary_candidate_count += 1
            elif contrib_type == "DETERMINISTIC_DUPLICATE":
                diagnostics.deterministic_duplicate_count += 1

            # Only retain candidates meeting or exceeding independent threshold as active AI findings
            if contrib_score >= AI_INDEPENDENT_THRESHOLD:
                c_id = f"AI-{c_seq:03d}"
                cand.id = c_id
                cand.candidate_id = c_id
                final_candidates.append(cand)
                c_seq += 1
            else:
                suppressed_candidates.append(cand)

        # Reconcile research metrics
        diagnostics.reconcile_counts()

        # Final Status determination
        if len(final_candidates) > 0 or diagnostics.ai_candidate_count_deduplicated > 0:
            diagnostics.status = AIAnalysisStatus.SUCCESS_WITH_CANDIDATES
        else:
            diagnostics.status = AIAnalysisStatus.SUCCESS_ZERO_CANDIDATES

        overall_summary = parsed_data.get("overall_summary", "AI candidate finding generation complete.") if isinstance(parsed_data, dict) else "AI candidates generated."

        # Enforce the requested candidate budget on active candidates (keep the most confident)
        if max_findings is not None and len(final_candidates) > max_findings:
            diagnostics.ai_candidates_over_limit = len(final_candidates) - max_findings
            ranked = sorted(final_candidates, key=lambda c: -c.confidence)
            for dropped in ranked[max_findings:]:
                dropped.status = "dropped_over_limit"  # kept for traceability, never verified or scored
                suppressed_candidates.append(dropped)
            final_candidates = ranked[:max_findings]
            for c_idx, cand in enumerate(final_candidates, start=1):
                cand.id = cand.candidate_id = f"AI-{c_idx:03d}"

        # Suppressed candidates get their own ID space so they never collide with active AI-xxx IDs
        for s_idx, cand in enumerate(suppressed_candidates, start=1):
            cand.id = cand.candidate_id = f"AI-SUP-{s_idx:03d}"

        return {
            "overall_summary": overall_summary,
            "issues": [cand.model_dump() for cand in final_candidates],
            "suppressed_issues": [cand.model_dump() for cand in suppressed_candidates],
            "diagnostics": diagnostics
        }
