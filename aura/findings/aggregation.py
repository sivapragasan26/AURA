from typing import List, Dict, Any, Optional
from aura.findings.models import (
    AURAFinding, FindingSource, FindingSeverity, FindingVerificationStatus,
    AffectedElement, FindingEvidence, FindingCategory, AggregationResult
)
from aura.models.findings import AccessibilityViolation, RuntimeTelemetry, VerifiedFinding


class FindingsAggregator:
    """Single Source of Truth aggregating findings from AI, axe-core, and Runtime Telemetry."""

    @staticmethod
    def convert_accessibility_violations(violations: List[AccessibilityViolation]) -> List[AURAFinding]:
        """Converts raw axe-core violations into first-class CONFIRMED AURA Findings."""
        axe_findings: List[AURAFinding] = []
        for idx, viol in enumerate(violations, start=1):
            severity = FindingSeverity.MEDIUM
            imp = viol.impact.lower()
            if imp == "critical":
                severity = FindingSeverity.CRITICAL
            elif imp == "serious":
                severity = FindingSeverity.HIGH
            elif imp == "moderate":
                severity = FindingSeverity.MEDIUM
            elif imp == "minor":
                severity = FindingSeverity.LOW

            target_str = ", ".join(viol.target) if viol.target else "Document element"
            
            axe_findings.append(
                AURAFinding(
                    id=f"AURA-A11Y-00{idx}",
                    source=FindingSource.AXE,
                    category=FindingCategory.ACCESSIBILITY,
                    severity=severity,
                    title=f"WCAG [{viol.rule}]: {viol.description}",
                    description=viol.description,
                    observation=f"Deterministic axe-core scan detected '{viol.rule}' rule violation on target: {target_str}",
                    confidence=1.0,
                    verification_status=FindingVerificationStatus.CONFIRMED,
                    evidence=FindingEvidence(
                        types=["ACCESSIBILITY", "DOM"],
                        description=f"axe-core rule match: {viol.rule}",
                        sources=[f"Deterministic W3C WCAG Audit: {viol.rule}"],
                        # An axe rule is decided from the page's structure and accessibility information.
                        # The scan does capture a screenshot, but this finding does not rest on it, so it
                        # must not claim visual evidence.
                        flags={"screenshot": False, "dom": True, "accessibility": True, "runtime": False}
                    ),
                    affected_element=AffectedElement(
                        selector=viol.target[0] if viol.target else "Element",
                        target_list=viol.target
                    ),
                    recommendation=f"Resolve the '{viol.rule}' accessibility violation to comply with WCAG standards.",
                    why_it_matters=viol.why_it_matters or "Users of assistive technology (e.g. screen readers) may be unable to navigate or understand this content.",
                    raw_rule=viol.rule,
                    verification_score=1.0,
                    ai_confidence=1.0
                )
            )
        return axe_findings

    @staticmethod
    def convert_runtime_events(telemetry: Optional[RuntimeTelemetry]) -> List[AURAFinding]:
        """Converts critical classified runtime errors/failures into first-class CONFIRMED AURA Findings."""
        if not telemetry or not getattr(telemetry, "classified_events", None):
            return []

        runtime_findings: List[AURAFinding] = []
        idx = 1

        for evt in telemetry.classified_events:
            if evt.category.value in ("APPLICATION_ERROR", "API_ERROR"):
                severity = FindingSeverity.HIGH if evt.category.value == "APPLICATION_ERROR" else FindingSeverity.MEDIUM
                # Rule and target describe what was actually observed: console messages belong to the
                # page window, network failures to the request URL.
                category = FindingCategory.RUNTIME
                title = evt.title
                if evt.source == "network":
                    runtime_rule = "application_network_failure"
                    runtime_target = evt.url or "network"
                elif evt.triggered_by and evt.event_type == "exception":
                    # Deterministic evidence of an interaction failure on a specific control
                    runtime_rule = "interaction_failure"
                    runtime_target = evt.triggered_by
                    category = FindingCategory.INTERACTION
                    title = f"Uncaught exception raised by interacting with {evt.triggered_by}"
                elif evt.event_type == "exception":
                    runtime_rule = "application_runtime_exception"
                    runtime_target = "window"
                else:
                    runtime_rule = "application_console_error"
                    runtime_target = "window"
                runtime_findings.append(
                    AURAFinding(
                        id=f"AURA-RUNTIME-00{idx}",
                        source=FindingSource.RUNTIME,
                        category=category,
                        severity=severity,
                        title=title,
                        description=evt.detail,
                        observation=f"Browser telemetry recorded {evt.source} event: {evt.detail}",
                        confidence=0.95,
                        verification_status=FindingVerificationStatus.CONFIRMED,
                        evidence=FindingEvidence(
                            types=["RUNTIME"],
                            description=f"Runtime {evt.source} telemetry log",
                            sources=[f"Live Browser {evt.source} log"],
                            flags={"screenshot": False, "dom": False, "accessibility": False, "runtime": True}
                        ),
                        affected_element=AffectedElement(selector=runtime_target),
                        recommendation="Investigate stack trace or endpoint failure and resolve runtime error.",
                        why_it_matters="Runtime JavaScript and API failures can disrupt dynamic page functionality.",
                        raw_rule=runtime_rule,
                        verification_score=0.95,
                        ai_confidence=0.95
                    )
                )
                idx += 1

        return runtime_findings

    @staticmethod
    def convert_verified_ai_finding(vf: VerifiedFinding) -> AURAFinding:
        """Converts a verified AI candidate finding into a unified AURAFinding model."""
        c = vf.candidate
        v = vf.verification

        sev_map = {
            "critical": FindingSeverity.CRITICAL,
            "high": FindingSeverity.HIGH,
            "medium": FindingSeverity.MEDIUM,
            "low": FindingSeverity.LOW,
            "info": FindingSeverity.INFO
        }
        severity = sev_map.get(c.severity.lower(), FindingSeverity.MEDIUM)

        status_map = {
            "confirmed": FindingVerificationStatus.CONFIRMED,
            "likely": FindingVerificationStatus.LIKELY,
            "uncertain": FindingVerificationStatus.UNCERTAIN,
            "rejected": FindingVerificationStatus.REJECTED
        }
        verification_status = status_map.get(v.status.value.lower(), FindingVerificationStatus.UNCERTAIN)

        cat_map = {
            "UI": FindingCategory.UI,
            "UX": FindingCategory.UX,
            "ACCESSIBILITY": FindingCategory.ACCESSIBILITY,
            "RESPONSIVENESS": FindingCategory.RESPONSIVENESS,
            "NAVIGATION": FindingCategory.NAVIGATION,
            "FORM": FindingCategory.FORM,
            "CONTENT": FindingCategory.CONTENT,
            "RUNTIME": FindingCategory.RUNTIME,
            "INTERACTION": FindingCategory.INTERACTION
        }
        category = cat_map.get(str(c.category).upper(), FindingCategory.UX)

        selector_val = None
        tag_val = None
        text_val = None
        if isinstance(c.affected_element, dict):
            selector_val = c.affected_element.get("selector")
            tag_val = c.affected_element.get("tag")
            text_val = c.affected_element.get("text")
        elif hasattr(c.affected_element, "selector"):
            selector_val = getattr(c.affected_element, "selector", None)
            tag_val = getattr(c.affected_element, "tag", None)
            text_val = getattr(c.affected_element, "text", None)

        cand_id = c.candidate_id or getattr(v, "candidate_id", None) or c.id
        norm_rule = c.normalized_rule or c.rule_type or c.title
        raw_ai_rule = getattr(c, "raw_rule_type", None) or c.rule_type

        target_ident = c.target_identity or {
            "selector": selector_val,
            "tag": tag_val,
            "text": text_val,
            "target_match_method": getattr(v, "target_match_method", None)
        }

        sources_list = ["AI"]
        for s in v.evidence_sources:
            if "axe-core" in s.lower() and "axe-core" not in sources_list:
                sources_list.append("axe-core")

        why_matters = c.why_it_matters
        if not why_matters:
            if norm_rule in ("weak_primary_cta", "competing_cta"):
                why_matters = "When the primary action is not clear, visitors hesitate or miss the main task."
            elif norm_rule in ("bad_visual_hierarchy", "misleading_visual_emphasis"):
                why_matters = "Unbalanced visual emphasis can distract from the main content and make the page harder to scan."
            elif norm_rule in ("search_discoverability", "discoverability_problem"):
                why_matters = "When key features are hard to spot, people spend extra effort looking for them."
            elif (c.category or "").lower() == "accessibility":
                why_matters = "People using screen readers or keyboards need clear names and structure to navigate."
            elif (c.category or "").lower() == "responsiveness":
                why_matters = "Content that overflows or clips requires extra scrolling and looks broken on smaller screens."
            elif (c.category or "").lower() == "interaction":
                why_matters = "Controls that do not respond or give clear feedback cause uncertainty about whether an action succeeded."
            else:
                # No generic filler here. Leaving it unset lets the interpretation layer use the wording
                # for this rule; if it has none either, the finding is marked GENERIC and held back from
                # the human list rather than shown with a sentence that fits anything.
                why_matters = None

        return AURAFinding(
            id=c.id,
            candidate_id=cand_id,
            source=FindingSource.AI,
            sources=sources_list,
            category=category,
            severity=severity,
            title=c.title,
            description=c.description,
            observation=c.observation or c.description,
            confidence=c.confidence,
            verification_status=verification_status,
            evidence=FindingEvidence(
                types=[c.evidence.type.upper()],
                description=c.evidence.description,
                sources=v.evidence_sources,
                flags=v.evidence_flags
            ),
            affected_element=AffectedElement(
                selector=selector_val or "Element",
                tag=tag_val,
                text=text_val
            ),
            target_identity=target_ident,
            recommendation=c.recommendation,
            why_it_matters=why_matters,
            rejection_reason=v.rejection_reason,
            raw_rule=raw_ai_rule,
            normalized_rule=norm_rule,
            verification_score=v.confidence,
            ai_confidence=c.confidence,
            ai_contribution_type=getattr(c, "ai_contribution_type", None),
            ai_contribution_score=getattr(c, "ai_contribution_score", None),
            why_ai_needed=getattr(c, "why_ai_needed", None),
            evidence_ids=v.evidence_ids
        )

    @staticmethod
    def convert_interaction_outcomes(interaction_log: Optional[List[Dict[str, Any]]]) -> List[AURAFinding]:
        """
        A control AURA operated that produced no effect at all, reported as a finding in its own right.

        This is measured, not inferred: AURA clicked the control, recorded the page state before and
        after, and nothing changed - no DOM change, no address change, no error. Until now that evidence
        was only offered to the AI, which in practice reported visual problems instead and left measured
        interaction failures unmentioned; on the navigation benchmark suite every seeded dead control was
        missed with the diagnosis "AI produced no candidate", while the proof of each one sat unused in
        the interaction log.

        It is reported as LIKELY rather than CONFIRMED on purpose. A click can legitimately do something
        AURA cannot observe - copy to the clipboard, fire analytics, alter state off-screen - so this is
        strong evidence of a dead control, not proof of one, and it is presented to the reader as such.
        """
        findings: List[AURAFinding] = []
        for idx, entry in enumerate((interaction_log or []), start=1):
            if entry.get("status") != "executed" or entry.get("action") != "click":
                continue
            if entry.get("errors_after_action"):
                continue   # already reported as an interaction_failure by the runtime path
            if any(entry.get(k) for k in ("dom_changed", "url_changed", "visible_change")):
                continue
            selector = entry.get("element_selector") or entry.get("target") or "unknown"
            label = (entry.get("target_text") or "").strip()
            name = f"'{label}'" if label else selector
            findings.append(AURAFinding(
                id=f"AURA-INTERACT-{idx:03d}",
                source=FindingSource.RUNTIME,
                category=FindingCategory.INTERACTION,
                severity=FindingSeverity.MEDIUM,
                title=f"Clicking {name} produced no visible response",
                description=(f"AURA clicked {name} and compared the page before and after. Nothing changed: "
                             f"no content, no address change and no error."),
                observation=("Controlled interaction recorded no change to the page state after the click, "
                             "and no error was raised."),
                confidence=0.75,
                verification_status=FindingVerificationStatus.LIKELY,
                evidence=FindingEvidence(
                    types=["INTERACTION"],
                    description="Before and after page state captured around a controlled click",
                    sources=["AURA controlled interaction"],
                    flags={"screenshot": False, "dom": True, "accessibility": False, "runtime": True},
                ),
                affected_element=AffectedElement(selector=selector),
                recommendation=("Confirm the control is meant to do something here. If it is, fix the handler; "
                                "if its effect is invisible, give the user feedback that it worked."),
                why_it_matters=("A control that appears interactive but does nothing leaves the person repeating "
                                "the action and assuming the page is broken."),
                raw_rule="non_responsive_control",
                verification_score=0.75,
                ai_confidence=0.0,
            ))
        return findings

    @classmethod
    def aggregate(
        cls,
        verified_ai_findings: List[VerifiedFinding],
        rejected_ai_findings: List[VerifiedFinding],
        accessibility_violations: List[AccessibilityViolation],
        telemetry: RuntimeTelemetry,
        ai_status: Optional[str] = None,
        interaction_log: Optional[List[Dict[str, Any]]] = None
    ) -> AggregationResult:
        """
        Unified Single Source of Truth aggregation.
        Returns AggregationResult model containing active_findings, rejected_findings, and metrics.
        """
        active_findings: List[AURAFinding] = []
        rejected_findings: List[AURAFinding] = []

        # 1. Convert axe-core violations
        axe_findings = cls.convert_accessibility_violations(accessibility_violations)
        active_findings.extend(axe_findings)

        # 2. Convert runtime error events
        runtime_findings = cls.convert_runtime_events(telemetry)
        active_findings.extend(runtime_findings)

        # 2b. Controls that were operated and did nothing
        interaction_findings = cls.convert_interaction_outcomes(interaction_log)
        active_findings.extend(interaction_findings)

        # 3. Convert verified AI findings
        ai_active_cnt = 0
        for vf in verified_ai_findings:
            converted = cls.convert_verified_ai_finding(vf)
            if converted.verification_status == FindingVerificationStatus.REJECTED:
                rejected_findings.append(converted)
            else:
                active_findings.append(converted)
                ai_active_cnt += 1

        for r_vf in rejected_ai_findings:
            rejected_findings.append(cls.convert_verified_ai_finding(r_vf))

        # 4. Deduplicate overlapping active findings
        from aura.evidence.correlator import EvidenceCorrelator
        active_findings = EvidenceCorrelator.correlate_and_deduplicate(active_findings)

        # Calculate Severity Counts (Active Findings Only)
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

        for f in active_findings:
            sev_key = f.severity.value.lower()
            if sev_key in severity_counts:
                severity_counts[sev_key] += 1

        # Calculate Verification Counts
        verification_counts = {"confirmed": 0, "likely": 0, "uncertain": 0, "rejected": len(rejected_findings)}
        for f in active_findings:
            st_key = f.verification_status.value.lower()
            if st_key in verification_counts:
                verification_counts[st_key] += 1

        # Calculate Correlation Breakdown Counts
        correlation_counts = {
            "ai_plus_axe": 0,
            "ai_plus_runtime": 0,
            "axe_only": 0,
            "runtime_only": 0,
            "ai_only": 0
        }

        for f in active_findings:
            srcs = [s.lower() for s in f.sources]
            has_ai = "ai" in srcs
            has_axe = "axe-core" in srcs or "axe" in srcs
            has_rt = "runtime" in srcs

            if has_ai and has_axe:
                correlation_counts["ai_plus_axe"] += 1
            elif has_ai and has_rt:
                correlation_counts["ai_plus_runtime"] += 1
            elif has_axe and not has_ai:
                correlation_counts["axe_only"] += 1
            elif has_rt and not has_ai:
                correlation_counts["runtime_only"] += 1
            elif has_ai:
                correlation_counts["ai_only"] += 1

        # Calculate Source Counts
        source_counts = {
            "ai": ai_active_cnt,
            "axe": len(axe_findings),
            "runtime": len(runtime_findings)
        }

        # Build accurate non-contradictory summary statement
        total_active = len(active_findings)
        total_source_obs = ai_active_cnt + len(axe_findings) + len(runtime_findings)
        ai_failed = ai_status in (
            "PROVIDER_NOT_EVALUABLE", "RATE_LIMITED", "AI_SKIPPED", "NOT_RUN",
            "REQUEST_FAILED", "AI_UNAVAILABLE", "AI_RESPONSE_INVALID", "PARSE_FAILED",
            "SCHEMA_FAILED", "RESPONSE_EMPTY"
        )
        if total_active == 0:
            summary_text = "No UI/UX, accessibility, or runtime defects were detected on this page."
            if ai_failed:
                summary_text = "No accessibility or runtime defects detected. AI analysis was unavailable."
            else:
                summary_text = "No UI/UX, accessibility, or runtime defects were detected on this page."
        elif ai_active_cnt == 0:
            summary_text = f"No AI-generated UI/UX candidate findings were identified. However, {len(axe_findings)} accessibility violation(s) and {len(runtime_findings)} runtime error(s) were confirmed."
            if ai_failed:
                summary_text = f"AI analysis was unavailable. However, {len(axe_findings)} accessibility violation(s) and {len(runtime_findings)} runtime error(s) were confirmed."
            else:
                summary_text = f"AI analysis completed — no candidate findings identified. However, {len(axe_findings)} accessibility violation(s) and {len(runtime_findings)} runtime error(s) were confirmed."
        elif total_source_obs > total_active:
            summary_text = f"Identified {total_active} unique canonical finding(s) from {total_source_obs} source observations across AI ({ai_active_cnt}), axe-core ({len(axe_findings)}), and Runtime telemetry ({len(runtime_findings)}), with cross-source observations merged where applicable."
        else:
            summary_text = f"Identified {total_active} active canonical defect(s) across AI ({ai_active_cnt}), axe-core accessibility ({len(axe_findings)}), and Runtime telemetry ({len(runtime_findings)})."

        return AggregationResult(
            findings=active_findings,
            all_active_findings=active_findings,
            rejected_findings=rejected_findings,
            all_rejected_findings=rejected_findings,
            severity_counts=severity_counts,
            verification_counts=verification_counts,
            source_counts=source_counts,
            correlation_counts=correlation_counts,
            summary_text=summary_text
        )

