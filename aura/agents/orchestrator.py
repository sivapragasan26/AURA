import base64
import time
import json
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
from aura.config import settings
from aura.agents.browser_agent import BrowserAgent
from aura.analyzers.dom_analyzer import DOMAnalyzer
from aura.analyzers.accessibility_analyzer import AccessibilityAnalyzer
from aura.models.findings import ConsoleError, NetworkFailure, RuntimeTelemetry
from aura.agents.ux_ui_agent import UXUIAgent
from aura.agents.accessibility_agent import AccessibilityAgent
from aura.agents.runtime_agent import RuntimeAgent
from aura.agents.verification_agent import VerificationAgent
from aura.agent.provider import AIProvider
from aura.agent.providers import get_ai_provider
from aura.security.credentials import SessionCredentialsManager
from aura.scoring.scorer import AURAScorer
from aura.report.report_generator import ReportGenerator
from aura.evaluation.evaluator import EvaluationEngine
from aura.utils.logger import logger, ExecutionStepTracker
from aura.utils.helpers import validate_url
from aura.agent.diagnostics import AIDiagnostics, AIAnalysisStatus
from aura.agent.evidence_packet import build_evidence_packet
from aura.agent.provider_status import run_preflight, ProviderPreflightBlocked

PNG_SIGNATURE = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def _png_size(path):
    """The pixel size of a PNG on disk, or None when it is missing or unreadable."""
    if not path:
        return None
    try:
        from PIL import Image
        with Image.open(path) as img:
            return {"width": img.width, "height": img.height}
    except Exception:
        return None


def bundle_inputs(bundle: Any) -> Tuple[Dict[str, Any], List[Any], List[Dict[str, Any]]]:
    """The DOM summary, accessibility violations and interaction records an evidence bundle carries."""
    dom_summary = DOMAnalyzer().summarize(bundle.dom.model_dump())
    a11y_violations = AccessibilityAnalyzer.convert_raw_violations(
        [v.model_dump() for v in bundle.axe.violations]) if bundle.axe.available else []
    interaction_log = [i.model_dump() for i in bundle.interactions]
    return dom_summary, a11y_violations, interaction_log


def bundle_telemetry(bundle: Any, screenshot_path: Optional[str] = None) -> RuntimeTelemetry:
    """The runtime telemetry an evidence bundle carries."""
    return RuntimeTelemetry(
        url=bundle.url, title=bundle.title,
        viewport={"width": bundle.viewport.width, "height": bundle.viewport.height},
        page_load_time_ms=bundle.telemetry.page_load_time_ms,
        console_errors=[ConsoleError(type=c.type, text=c.text, location=c.location, triggered_by=c.triggered_by)
                        for c in bundle.telemetry.console],
        network_failures=[NetworkFailure(url=n.url, status=n.status, status_text=n.status_text, method=n.method)
                          for n in bundle.telemetry.network],
        screenshot_path=screenshot_path,
    )


def build_ai_prompt(bundle: Any, screenshot_attached: bool = False) -> Any:
    """
    The evidence packet - and so the exact prompt - for one bundle, without running the analysis.

    This is the first half of a scan whose model call happens in the browser (aura/api/relay.py): the
    browser is handed this prompt, calls the provider itself, and returns the response for the second half.
    It builds on the same bundle_inputs() the one-shot path uses, so the two cannot drift apart.
    """
    if not validate_url(bundle.url):
        raise ValueError("Invalid or unsafe URL in evidence bundle.")
    dom_summary, a11y_violations, interaction_log = bundle_inputs(bundle)
    return build_evidence_packet(
        telemetry=bundle_telemetry(bundle),
        dom_summary=dom_summary,
        accessibility_violations=a11y_violations,
        interaction_log=interaction_log,
        screenshot_in_browser=bool(screenshot_attached),
    )


class AURAOrchestrator:
    """
    Central Orchestrator managing the V0.4 agentic audit lifecycle:
    Two-mode execution (Test Lab Mode vs External Website Mode), evidence collection,
    hypothesis-driven interactions, multimodal AI candidates, verification, transparent scoring,
    and ground truth benchmark evaluation.
    """

    def __init__(
        self,
        provider: Optional[AIProvider] = None,
        session_state: Optional[Dict[str, Any]] = None,
        step_callback: Optional[Callable[[str, str], None]] = None,
        provider_type: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.step_tracker = ExecutionStepTracker(callback=step_callback)
        selected_provider_type = provider_type or settings.AI_PROVIDER
        
        if provider is None:
            self.provider = get_ai_provider(
                provider_type=selected_provider_type,
                model_name=model_name,
                session_state=session_state
            )
            _, self.credential_source = SessionCredentialsManager.get_credential_for_provider(
                selected_provider_type,
                session_state
            )
        else:
            self.provider = provider
            self.credential_source = getattr(provider, "credential_source", "Explicit Provider")

        self.browser_agent = BrowserAgent()
        self.ux_ui_agent = UXUIAgent(provider=self.provider)
        self.a11y_agent = AccessibilityAgent()
        self.runtime_agent = RuntimeAgent()
        self.verification_agent = VerificationAgent()
        self.scorer = AURAScorer()
        self.report_generator = ReportGenerator()

    _issued_ids: set = set()

    @classmethod
    def generate_audit_id(cls) -> str:
        """
        Generates unique audit session identifier (e.g., AURA-2026-000001). Two audits started in the same
        second (e.g. two browser-tab scans) must never share an id, a run directory or a stored result.
        """
        year = time.strftime("%Y")
        timestamp_seq = int(time.time()) % 1000000
        audit_id = f"AURA-{year}-{timestamp_seq:06d}"
        while audit_id in cls._issued_ids or (settings.RUNS_DIR / audit_id).exists():
            timestamp_seq = (timestamp_seq + 1) % 1000000
            audit_id = f"AURA-{year}-{timestamp_seq:06d}"
        cls._issued_ids.add(audit_id)
        return audit_id

    def compute_evidence_coverage(
        self,
        viewport_ss: Optional[str],
        dom_summary: Dict[str, Any],
        telemetry: Any,
        interaction_log: List[Dict[str, Any]],
        collection: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculates evidence coverage percentage and itemized checklist.
        collection: metadata of an external collector (extension); it states whether axe-core ran and whether
        runtime telemetry covers page load, so coverage is never claimed for evidence that was not collected.
        """
        collection = collection or {}
        checklist = {
            "Screenshot Visual": viewport_ss is not None,
            "Structured DOM": dom_summary.get("total_elements", 0) > 0,
            "axe-core Accessibility": bool(collection.get("axe_available", True)),
            "Runtime Telemetry": True,
            "Controlled Interaction": len(interaction_log) > 0,
            "Responsive Overflow Check": "has_horizontal_overflow" in dom_summary
        }
        passed = sum(1 for v in checklist.values() if v)
        total = len(checklist)
        pct = int(round((passed / total) * 100))
        coverage = {
            "percentage": pct,
            "checklist": checklist
        }
        notes = []
        if collection.get("telemetry_scope") == "post_load":
            notes.append("Runtime telemetry started after the page had loaded: console errors and exceptions raised during "
                         "page load are not included (failed resource loads are, via the Resource Timing API).")
        if collection and not collection.get("axe_available", True):
            notes.append(f"axe-core could not run in the page ({collection.get('axe_error') or 'unknown reason'}); "
                         "accessibility was not evaluated.")
        if notes:
            coverage["notes"] = notes
        return coverage

    def run_audit(
        self,
        url: str,
        viewport_preset: str = "Desktop (1440x900)",
        headless: bool = settings.BROWSER_HEADLESS,
        enable_interactions: bool = True,
        mode: str = "external",
        site_dir: Optional[Path] = None,
        skip_ai: bool = False,
        preflight: bool = True,
        fallback_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executes full V0.4 audit workflow for given URL: Playwright evidence collection, then the shared
        analysis pipeline (_analyze_collected) that the extension path (analyze_evidence) also uses.
        skip_ai: run deterministic evidence only (AI benchmark becomes NOT_EVALUABLE).
        preflight: check the AI provider BEFORE any browser work; a blocked provider raises
            ProviderPreflightBlocked (no browser/AI work is wasted). Never runs an inference.
        fallback_context: set when the user switched provider after the primary was unavailable;
            recorded verbatim in the report so the run is never attributed to the wrong provider.
        """
        if not validate_url(url):
            raise ValueError(f"Invalid or unsafe URL: '{url}'. Please specify a valid http:// or https:// URL.")

        audit_id = self.generate_audit_id()
        viewport = settings.VIEWPORT_PRESETS.get(viewport_preset, {"width": 1440, "height": 900})
        start_time = time.time()

        # 0. Provider preflight (before any expensive browser work)
        preflight_result = None
        if not skip_ai and preflight:
            self.step_tracker.add_step(f"AI provider preflight ({getattr(self.provider, 'provider_key', 'unknown')})", "running")
            preflight_result = run_preflight(self.provider)
            if preflight_result.blocked:
                self.step_tracker.update_last_step("failed", f"{preflight_result.status}: {preflight_result.reason}")
                raise ProviderPreflightBlocked(preflight_result)
            self.step_tracker.update_last_step("completed", f"{preflight_result.status}")

        try:
            # 1. Browser Launch & Navigation
            self.step_tracker.add_step(f"[{audit_id}] Launching Playwright Chromium Browser ({viewport_preset})", "running")
            self.browser_agent.start(viewport=viewport)
            self.step_tracker.update_last_step("completed", "Browser initialized")

            self.step_tracker.add_step(f"Navigating to {url}", "running")
            success, message, load_time_ms = self.browser_agent.navigate(url)
            if not success:
                self.step_tracker.update_last_step("failed", message)
                raise RuntimeError(message)
            self.step_tracker.update_last_step("completed", f"Page loaded in {load_time_ms:.0f}ms")

            # 2. DOM & Screenshot Evidence Collection
            self.step_tracker.add_step("Extracting DOM structure, layout geometry & capturing screenshots", "running")
            dom_summary = self.browser_agent.extract_structured_dom_summary()
            viewport_ss, fullpage_ss = self.browser_agent.capture_screenshots(settings.TEMP_DIR)
            overflow_flag = " (Horizontal Overflow Detected)" if dom_summary.get("has_horizontal_overflow") else ""
            self.step_tracker.update_last_step("completed", f"DOM captured ({dom_summary.get('total_elements', 0)} elements){overflow_flag}")

            # 3. Controlled Autonomous Interaction (Level-B)
            interaction_log = []
            if enable_interactions:
                self.step_tracker.add_step("Executing hypothesis-driven interactions under Level-B Safety Policy", "running")
                interaction_log = self.browser_agent.execute_controlled_interactions()
                executed_cnt = sum(1 for item in interaction_log if item.get("status") == "executed")
                blocked_cnt = sum(1 for item in interaction_log if item.get("status") == "blocked")
                self.step_tracker.update_last_step("completed", f"Interactions: {executed_cnt} executed | {blocked_cnt} blocked")

            # 4. Accessibility Scan (axe-core)
            self.step_tracker.add_step("Running axe-core WCAG accessibility scan", "running")
            a11y_violations = self.a11y_agent.run_scan(self.browser_agent.browser_manager.page)
            self.step_tracker.update_last_step("completed", f"{len(a11y_violations)} WCAG violations found")

            # 5. Runtime Telemetry Collection
            self.step_tracker.add_step("Collecting live runtime telemetry & console logs", "running")
            page_title = self.browser_agent.browser_manager.page.title() if self.browser_agent.browser_manager.page else ""
            telemetry = self.browser_agent.collector.get_telemetry(
                url=url,
                title=page_title,
                viewport=viewport,
                screenshot_path=viewport_ss
            )

            return self._analyze_collected(
                audit_id=audit_id, url=url, viewport=viewport, start_time=start_time,
                dom_summary=dom_summary, a11y_violations=a11y_violations, telemetry=telemetry,
                screenshot_path=viewport_ss, interaction_log=interaction_log,
                mode=mode, site_dir=site_dir, skip_ai=skip_ai, preflight_result=preflight_result,
                fallback_context=fallback_context,
                live_agent=self.browser_agent, enable_targeted_interactions=enable_interactions,
            )

        finally:
            self.browser_agent.stop()

    def analyze_evidence(self, bundle: Any, skip_ai: bool = False, audit_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Runs the AURA analysis pipeline on evidence collected in the user's own browser tab by the extension
        (aura.evidence.bundle.EvidenceBundle). Same pipeline as run_audit, minus the steps that need a page
        the engine controls (targeted re-interaction and target resolution; the extension resolves targets
        in the page when it highlights them).

        A blocked provider preflight does not abort the scan: deterministic evidence is still analysed and the
        AI state is reported as unavailable (never as "AI found 0 problems").
        """
        url = bundle.url
        if not validate_url(url):
            raise ValueError("Invalid or unsafe URL in evidence bundle.")
        # The id may be given: a two-phase scan hands it to the browser before the model answers, so the
        # audit that comes back carries the same id the browser was told to complete.
        audit_id = audit_id or self.generate_audit_id()
        viewport = {"width": bundle.viewport.width, "height": bundle.viewport.height}
        start_time = time.time()

        preflight_result = None
        ai_skip_reason = "AI analysis was not run (deterministic-only scan requested)." if skip_ai else None
        # A relayed call has already been made, in the browser, with the user's own key: there is nothing
        # left to preflight and this process holds no credential to preflight with.
        if not skip_ai and not getattr(self.provider, "is_browser_relay", False):
            self.step_tracker.add_step(f"AI provider preflight ({getattr(self.provider, 'provider_key', 'unknown')})", "running")
            preflight_result = run_preflight(self.provider)
            if preflight_result.blocked:
                self.step_tracker.update_last_step("failed", f"{preflight_result.status}: {preflight_result.reason}")
                skip_ai = True
                ai_skip_reason = f"AI provider unavailable ({preflight_result.status}): {preflight_result.reason}"
            else:
                self.step_tracker.update_last_step("completed", f"{preflight_result.status}")

        self.step_tracker.add_step(f"[{audit_id}] Processing evidence collected by the AURA extension", "running")
        dom_summary, a11y_violations, interaction_log = bundle_inputs(bundle)

        def _write_png(b64: Optional[str], suffix: str) -> Optional[str]:
            if not b64:
                return None
            try:
                raw = base64.b64decode(b64, validate=True)
            except (ValueError, TypeError):
                return None
            if not raw.startswith(PNG_SIGNATURE):
                return None
            # The analysis needs the bytes on disk for the provider call. When persistence is off that
            # goes to the system temp dir, which exists even where the app directory is read-only, and is
            # removed again in the finally block below.
            directory = settings.TEMP_DIR if settings.PERSIST else Path(tempfile.gettempdir())
            path = str(directory / f"extension_{audit_id}{suffix}.png")
            with open(path, "wb") as fh:
                fh.write(raw)
            return path

        # The viewport capture is what the AI analyses. The full-page capture, when the page was taller
        # than one screen, is what the panel shows per finding, so findings below the fold have an image.
        screenshot_path = _write_png(bundle.screenshot_png_base64, "")
        keep_path = _write_png(bundle.screenshot_fullpage_png_base64, "_fullpage") or screenshot_path

        telemetry = bundle_telemetry(bundle, screenshot_path)
        self.step_tracker.update_last_step(
            "completed", f"DOM {dom_summary.get('total_elements', 0)} elements | axe {'ran' if bundle.axe.available else 'unavailable'} | "
                         f"{len(interaction_log)} interaction records | screenshot {'yes' if screenshot_path else 'no'}")
        self.step_tracker.add_step("Classifying runtime telemetry", "running")

        try:
            return self._analyze_collected(
                audit_id=audit_id, url=url, viewport=viewport, start_time=start_time,
                dom_summary=dom_summary, a11y_violations=a11y_violations, telemetry=telemetry,
                screenshot_path=screenshot_path, interaction_log=interaction_log,
                mode="extension", site_dir=None, skip_ai=skip_ai, preflight_result=preflight_result,
                fallback_context=None, live_agent=None, enable_targeted_interactions=False,
                ai_skip_reason=ai_skip_reason,
                collection={
                    # The pixel size of the capture, so a finding outside it is not offered a screenshot.
                    # When the capture stayed in the browser it reports the size instead.
                    "capture_size": _png_size(keep_path) or (bundle.capture_size.model_dump() if bundle.capture_size else None),
                    "target_boxes": dict(bundle.target_boxes or {}),
                    "source": bundle.source, "collector_version": bundle.collector_version,
                    "captured_at": bundle.captured_at, "title": bundle.title,
                    "axe_available": bundle.axe.available, "axe_version": bundle.axe.version, "axe_error": bundle.axe.error,
                    "telemetry_scope": bundle.telemetry.capture_scope,
                },
            )
        finally:
            # The capture is kept with its audit so the panel can show a person WHERE a finding is, cropped
            # to the element in question. It stays on this machine: the local server serves it to the local
            # extension and nothing uploads it. It is removed from the temp area either way.
            if keep_path and settings.PERSIST:
                try:
                    kept = settings.RUNS_DIR / audit_id
                    kept.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(keep_path, kept / "screenshot.png")
                except OSError as e:
                    logger.warning(f"Could not keep the capture for {audit_id}: {e}")
            for temp in {screenshot_path, keep_path}:
                if temp:
                    try:
                        Path(temp).unlink()
                    except OSError:
                        pass

    def _analyze_collected(
        self,
        audit_id: str,
        url: str,
        viewport: Dict[str, int],
        start_time: float,
        dom_summary: Dict[str, Any],
        a11y_violations: List[Any],
        telemetry: Any,
        screenshot_path: Optional[str],
        interaction_log: List[Dict[str, Any]],
        mode: str,
        site_dir: Optional[Path],
        skip_ai: bool,
        preflight_result: Any,
        fallback_context: Optional[Dict[str, Any]],
        live_agent: Optional[BrowserAgent],
        enable_targeted_interactions: bool,
        ai_skip_reason: Optional[str] = None,
        collection: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        The single AURA analysis pipeline shared by every collector: runtime classification, AI candidates,
        (live-page) targeted interactions, independent verification, correlation, scoring, report, evaluation.
        live_agent: the Playwright BrowserAgent whose page is still open, or None for extension evidence.
        """
        telemetry.dom_summary = dom_summary
        classified_events = self.runtime_agent.classify(telemetry)
        self.step_tracker.update_last_step("completed", f"Telemetry analyzed ({len(classified_events)} events)")

        # 6. UX/UI Agent Candidate Findings (focused evidence packet)
        _ai_provider = self.ux_ui_agent.agent.provider
        provider_name = getattr(_ai_provider, "display_name", None) or _ai_provider.__class__.__name__.replace("Provider", "")
        is_mock_mode = ("mock" in provider_name.lower())

        if skip_ai:
            self.step_tracker.add_step("AI analysis skipped (deterministic-only audit)", "completed")
            raw_candidates = []
            self.ux_ui_agent.last_suppressed = []
            model_name = getattr(self.provider, "model", "default")
            diagnostics = AIDiagnostics(provider_name=provider_name, model_name=model_name, requested_model=model_name,
                                        actual_model=model_name, status=AIAnalysisStatus.AI_SKIPPED,
                                        ai_failure_reason=ai_skip_reason or "AI analysis was not run (deterministic-only audit requested).")
        else:
            self.step_tracker.add_step(f"AI Multimodal UX/UI Analysis ({provider_name})", "running")
            raw_candidates = self.ux_ui_agent.analyze(
                telemetry=telemetry,
                dom_summary=dom_summary,
                accessibility_violations=a11y_violations,
                screenshot_path=screenshot_path,
                interaction_log=interaction_log
            )
            diagnostics = self.ux_ui_agent.last_diagnostics
            self.step_tracker.update_last_step("completed", f"Generated {len(raw_candidates)} candidate findings")
        if diagnostics is not None and preflight_result is not None:
            diagnostics.preflight_status = preflight_result.status

        # 6b. Targeted interactions for controls referenced by candidates but not yet exercised (live page only)
        if live_agent is not None and enable_targeted_interactions and raw_candidates:
            targets = []
            for cand in raw_candidates:
                ae = cand.affected_element
                sel = ae.get("selector") if isinstance(ae, dict) else getattr(ae, "selector", None)
                if sel and sel not in ("body", "window", "document"):
                    targets.append(sel)
            errors_before = len(live_agent.collector.console_errors)
            added = live_agent.execute_targeted_interactions(targets, interaction_log)
            if added:
                self.step_tracker.add_step(f"Targeted interactions for AI-referenced controls: {sum(1 for a in added if a['status'] == 'executed')} executed", "completed")
                new_errors = live_agent.collector.console_errors[errors_before:]
                if new_errors:
                    telemetry.console_errors.extend(new_errors)
                    classified_events = self.runtime_agent.classify(telemetry)

        # 7. Independent Verification Engine
        self.step_tracker.add_step("Running Independent Evidence Verification Engine", "running")
        active_findings, rejected_findings = self.verification_agent.verify(
            candidate_findings=raw_candidates,
            dom_summary=dom_summary,
            accessibility_violations=a11y_violations,
            telemetry=telemetry,
            interaction_log=interaction_log
        )
        self.step_tracker.update_last_step("completed", f"Verified: {len(active_findings)} Active | {len(rejected_findings)} Rejected")

        if diagnostics:
            diagnostics.ai_candidate_count_confirmed = len([f for f in active_findings if getattr(f, "verification", None) and f.verification.status.value.lower() == "confirmed"])
            diagnostics.ai_candidate_count_likely = len([f for f in active_findings if getattr(f, "verification", None) and f.verification.status.value.lower() == "likely"])
            diagnostics.ai_candidate_count_uncertain = len([f for f in active_findings if getattr(f, "verification", None) and f.verification.status.value.lower() == "uncertain"])
            diagnostics.ai_candidate_count_rejected = len(rejected_findings)
            diagnostics.reconcile_counts()

        # 8. Transparent Scoring & Report Generation
        self.step_tracker.add_step("Computing transparent AURA scores & assembling audit report", "running")
        # Without a successful AI analysis the AI-derived dimensions (UI, UX, responsive, interaction) are not
        # evaluated: they are shown as N/A and excluded from the overall score instead of counting as 100.
        provider_failed = False
        ai_evaluated = True
        if diagnostics and (diagnostics.status.value in ("PROVIDER_NOT_EVALUABLE", "RATE_LIMITED", "REQUEST_FAILED", "AI_SKIPPED", "RESPONSE_EMPTY", "PARSE_FAILED", "SCHEMA_FAILED", "AI_RESPONSE_INVALID", "NOT_RUN") or not diagnostics.ai_request_succeeded):
            ai_evaluated = False
            if diagnostics and diagnostics.status.value in ("PROVIDER_NOT_EVALUABLE", "RATE_LIMITED", "REQUEST_FAILED", "AI_SKIPPED"):
                provider_failed = True

        scores, deductions_map = self.scorer.compute_score_with_deductions(
            verified_findings=active_findings,
            accessibility_violations=a11y_violations,
            telemetry=telemetry,
            ai_evaluated=ai_evaluated,
        )
        if not ai_evaluated:
            scores.ui = "N/A"
            scores.ux = "N/A"

        report_data = self.report_generator.generate_report(
            url=url,
            viewport=viewport,
            scores=scores,
            findings=active_findings,
            rejected_findings=rejected_findings,
            accessibility_violations=a11y_violations,
            telemetry=telemetry,
            execution_steps=self.step_tracker.get_steps(),
            provider_name=provider_name,
            is_mock_mode=is_mock_mode,
            credential_source=self.credential_source,
            ai_status=diagnostics.status.value if diagnostics else None
        )

        duration_s = round(time.time() - start_time, 2)
        report_data["audit_id"] = audit_id
        report_data["mode"] = mode
        report_data["interaction_log"] = interaction_log
        report_data["duration_seconds"] = duration_s
        report_data["deductions"] = deductions_map
        # Where each element sat when the capture was taken. The panel uses this to crop the screenshot
        # to the element a finding is about; it is geometry only, never page content.
        report_data["element_boxes"] = {
            str(el.get("selector")): el["bounding_box"]
            for el in (dom_summary.get("all_elements") or [])
            if el.get("selector") and isinstance(el.get("bounding_box"), dict)
        }
        # Boxes the collector resolved for the selectors the detectors actually report (axe uses its own
        # CSS paths, which never match the extractor's). These take precedence: they are keyed by the
        # exact selector the finding will carry.
        report_data["element_boxes"].update((collection or {}).get("target_boxes") or {})
        # The size of the image the panel will crop. A full-page capture covers the whole page, so every
        # finding has a region; a viewport-only capture covers what was on screen, and findings below the
        # fold are correctly offered no screenshot.
        report_data["capture_size"] = (collection or {}).get("capture_size") or _png_size(screenshot_path)
        report_data["evidence_coverage"] = self.compute_evidence_coverage(screenshot_path, dom_summary, telemetry, interaction_log,
                                                                          collection=collection)
        report_data["ai_diagnostics"] = diagnostics
        report_data["raw_ai_candidates"] = raw_candidates
        report_data["suppressed_ai_candidates"] = self.ux_ui_agent.last_suppressed
        report_data["preflight"] = preflight_result.to_dict() if preflight_result else None
        report_data["provider_selection"] = self._provider_selection(diagnostics, fallback_context)
        report_data["score_basis"] = ("all dimensions" if ai_evaluated
                                      else "deterministic dimensions only (accessibility, runtime); AI-derived dimensions not evaluated")
        report_data["collection"] = collection or {"source": "playwright"}

        # Resolve every finding's target to concrete DOM elements while the page is still open
        # (GT-blind target identity evidence, used for traceability and benchmark matching)
        aggregation = report_data["aggregation"]
        if live_agent is not None:
            live_agent.resolve_finding_targets(aggregation.all_active_findings + aggregation.rejected_findings)

        # 9. Mode-Based Ground Truth Evaluation (Test Lab vs External URL)
        if mode == "test_lab" and site_dir:
            eval_res = EvaluationEngine.evaluate(
                site_dir=site_dir,
                detected_findings=aggregation.all_active_findings,
                provider_failed=provider_failed,
                raw_ai_candidates=raw_candidates,
                suppressed_ai_candidates=self.ux_ui_agent.last_suppressed,
                rejected_findings=aggregation.rejected_findings,
                interaction_log=interaction_log,
                ai_status=diagnostics.status.value if diagnostics else None
            )
            # The benchmark names the provider/model that actually produced the AI findings
            eval_res["ai_provider"] = report_data["provider_selection"]["provider"]
            eval_res["ai_model"] = report_data["provider_selection"]["actual_model"]
            report_data["evaluation"] = eval_res
        else:
            report_data["evaluation"] = {
                "site_id": "external",
                "ground_truth_available": False,
                "expected_count": "N/A",
                "detected_count": len(report_data["aggregation"].all_active_findings),
                "true_positives": "N/A",
                "false_positives": "N/A",
                "false_negatives": "N/A",
                "precision": None,
                "precision_formatted": "N/A",
                "precision_note": "Ground truth is not available for external websites.",
                "recall_formatted": "N/A",
                "f1_formatted": "N/A",
                "missed_defects": []
            }

        # 10. Persist Audit Run
        self.save_audit_run(audit_id, report_data)

        self.step_tracker.update_last_step("completed", f"Audit {audit_id} complete! Score: {scores.overall}/100")
        return report_data

    def _provider_selection(self, diagnostics: Any, fallback_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Which provider actually produced this run's AI findings, and any user-chosen fallback."""
        provider = getattr(self.provider, "provider_key", "unknown")
        requested = getattr(self.provider, "model", "default")
        selection = {
            "provider": provider,
            "requested_model": getattr(diagnostics, "requested_model", None) or requested,
            "actual_model": getattr(diagnostics, "actual_model", None) or requested,
            "request_status": diagnostics.status.value if diagnostics else "NOT_RUN",
            "fallback": None,
        }
        if fallback_context:
            selection["fallback"] = {
                "primary_provider": fallback_context.get("primary_provider"),
                "primary_model": fallback_context.get("primary_model"),
                "primary_status": fallback_context.get("primary_status"),
                "primary_reason": fallback_context.get("primary_reason"),
                "fallback_provider": provider,
                "fallback_model": selection["actual_model"],
                "fallback_status": selection["request_status"],
                "selected_by": fallback_context.get("selected_by", "user"),
            }
        return selection

    @staticmethod
    def _candidate_record(c: Any) -> Dict[str, Any]:
        ae = c.affected_element
        selector = ae.get("selector") if isinstance(ae, dict) else (getattr(ae, "selector", None) if ae else None)
        return {
            "candidate_id": c.candidate_id or c.id, "category": c.category, "title": c.title,
            "raw_rule_type": c.raw_rule_type, "normalized_rule": c.normalized_rule, "target": selector,
            "confidence": c.confidence, "ai_contribution_type": c.ai_contribution_type,
            "why_ai_needed": c.why_ai_needed, "target_ref": (c.target_identity or {}).get("ref"),
        }

    @staticmethod
    def _finding_record(f: Any) -> Dict[str, Any]:
        return {
            "id": f.id, "candidate_ids": f.candidate_ids, "sources": f.sources, "category": f.category.value,
            "severity": f.severity.value, "title": f.title, "verification_status": f.verification_status.value,
            "raw_rule": f.raw_rule, "normalized_rule": f.normalized_rule, "raw_target": f.raw_target,
            "canonical_target": f.canonical_target, "resolved_target": f.resolved_target,
            "rejection_reason": f.rejection_reason,
        }

    def save_audit_run(self, audit_id: str, report_data: Dict[str, Any]):
        """Persists audit run data locally to runs/<audit_id>/audit.json."""
        if not settings.PERSIST:
            return  # hosted: nothing about someone else's page is written down
        try:
            run_dir = settings.RUNS_DIR / audit_id
            run_dir.mkdir(parents=True, exist_ok=True)
            audit_file = run_dir / "audit.json"
            diag = report_data.get("ai_diagnostics")

            serializable_data = {
                "audit_id": audit_id,
                "mode": report_data.get("mode", "external"),
                "url": report_data["report_model"].url,
                "timestamp": report_data["report_model"].timestamp,
                "scores": report_data["report_model"].scores.model_dump(),
                "summary": report_data["aggregation"].summary_text,
                "severity_counts": report_data["aggregation"].severity_counts,
                "duration_seconds": report_data.get("duration_seconds", 0.0),
                "interaction_log": report_data.get("interaction_log", []),
                "evaluation": report_data.get("evaluation", {}),
                "evidence_coverage": report_data.get("evidence_coverage", {}),
                # Pipeline data needed to re-diagnose a benchmark result offline
                "ai_diagnostics": diag.to_summary_dict() if diag else None,
                "preflight": report_data.get("preflight"),
                "provider_selection": report_data.get("provider_selection"),
                "raw_ai_candidates": [self._candidate_record(c) for c in report_data.get("raw_ai_candidates", [])],
                "suppressed_ai_candidates": [self._candidate_record(c) for c in report_data.get("suppressed_ai_candidates", [])],
                "canonical_findings": [self._finding_record(f) for f in report_data["aggregation"].all_active_findings],
                "rejected_findings": [self._finding_record(f) for f in report_data["aggregation"].rejected_findings],
                "runtime_events": [
                    {"category": e.category.value, "source": e.source, "event_type": e.event_type,
                     "ownership": e.ownership, "detail": e.detail}
                    for e in report_data["report_model"].runtime_telemetry.classified_events
                ]
            }
            with open(audit_file, "w", encoding="utf-8") as f:
                json.dump(serializable_data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Could not persist audit run {audit_id}: {e}")
