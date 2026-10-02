import os
import json
import streamlit as st
from pathlib import Path
from PIL import Image

# Page setup
st.set_page_config(
    page_title="AURA — Autonomous UI/UX Runtime Assurance",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

from aura.config import settings
from aura.config.models import AVAILABLE_MODELS, DEFAULT_MODELS
from aura.security.credentials import SessionCredentialsManager, sanitize_provider_error
from aura.engine import AURAEngine
from aura.evaluation.test_lab_runner import run_all_suites
from aura.agent.providers import get_ai_provider
from aura.findings.models import AURAFinding, FindingVerificationStatus
from aura.findings.aggregation import AggregationResult
from aura.evaluation.evaluator import EvaluationEngine
from aura.agent.provider_status import run_preflight, ProviderPreflightBlocked, ProviderStateStore
from test_lab.launcher import TestLabLauncher

PROVIDERS = ["mock", "gemini", "groq", "openai", "anthropic"]


def render_preflight_panel(result, container) -> None:
    """Compact AI provider preflight panel. Shows provider-reported quota values only when supplied."""
    container.markdown("**AI PROVIDER PREFLIGHT**")
    line = f"Provider: `{result.provider}` | Model: `{result.model}` | Status: **{'BLOCKED - ' if result.blocked else ''}{result.status}**"
    (container.error if result.blocked else container.caption)(line)
    remaining = result.seconds_remaining()  # computed now, from the absolute UTC end time
    if result.status == "COOLDOWN_ACTIVE" and remaining is not None:
        container.caption(f"Retry available in: {int(remaining + 0.999)} seconds")
    if result.cooldown_expired_at:
        container.caption("Cooldown expired · Preflight required (the old cooldown is over; availability is not guaranteed)")
    if result.status not in ("READY",) or result.blocked:
        container.caption(f"Reason: {result.reason}" + (f" | Action: {result.action}" if result.blocked else ""))
    rep = result.provider_reported or {}
    rep_parts = []
    if "remaining_requests_per_day" in rep:
        rep_parts.append(f"remaining requests/day {rep['remaining_requests_per_day']}")
    if "reset_requests" in rep:
        rep_parts.append(f"reset {rep['reset_requests']}")
    if "remaining_tokens_per_minute" in rep:
        rep_parts.append(f"remaining tokens/min {rep['remaining_tokens_per_minute']}")
    if rep_parts:
        container.caption("Provider-reported: " + " | ".join(rep_parts) + f" (observed {rep.get('observed_at', '?')[:19]})")
    tracked = result.aura_tracked or {}
    if tracked.get("cooldown_until") and result.blocked:
        container.caption(f"AURA tracked: blocked until {tracked['cooldown_until'][:19]} UTC ({tracked.get('basis')})")
    if result.last_http_status:
        container.caption(f"Last provider response: HTTP {result.last_http_status}" + ("" if result.checked_remotely else " (AURA tracked)"))


# Custom CSS styling for V0.4 Dashboard
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #0F172A;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #475569;
        margin-bottom: 1.5rem;
    }
    .security-banner {
        background-color: #FEF3C7;
        border-left: 4px solid #D97706;
        color: #92400E;
        padding: 0.75rem 1rem;
        border-radius: 6px;
        font-size: 0.9rem;
        margin-bottom: 1.5rem;
    }
    .testlab-banner {
        background-color: #F0FDF4;
        border-left: 4px solid #16A34A;
        color: #166534;
        padding: 0.75rem 1rem;
        border-radius: 6px;
        font-size: 0.9rem;
        margin-bottom: 1.5rem;
    }
    .mock-banner {
        background-color: #EFF6FF;
        border-left: 4px solid #3B82F6;
        color: #1E40AF;
        padding: 0.75rem 1rem;
        border-radius: 6px;
        font-size: 0.9rem;
        margin-bottom: 1.5rem;
    }
    .summary-banner {
        background-color: #F8FAFC;
        border-left: 4px solid #0EA5E9;
        color: #0369A1;
        padding: 0.85rem 1.1rem;
        border-radius: 6px;
        font-size: 0.95rem;
        font-weight: 600;
        margin-bottom: 1.5rem;
    }
    .score-card {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 1.2rem;
        text-align: center;
    }
    .score-value {
        font-size: 2.2rem;
        font-weight: 800;
        color: #0F172A;
    }
    .score-label {
        font-size: 0.85rem;
        font-weight: 600;
        color: #475569;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Source Badges */
    .badge-source-ai {
        background-color: #8B5CF6;
        color: white;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .badge-source-axe {
        background-color: #D97706;
        color: white;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .badge-source-runtime {
        background-color: #DC2626;
        color: white;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .badge-source-interaction {
        background-color: #059669;
        color: white;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .badge-source-system {
        background-color: #4B5563;
        color: white;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 700;
    }

    /* Verification Status Badges */
    .badge-confirmed {
        background-color: #DC2626;
        color: white;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    .badge-likely {
        background-color: #EA580C;
        color: white;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    .badge-uncertain {
        background-color: #D97706;
        color: white;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    .badge-rejected {
        background-color: #4B5563;
        color: white;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: bold;
    }

    /* Evidence Chips */
    .evidence-chip-on {
        background-color: #DCFCE7;
        color: #166534;
        border: 1px solid #86EFAC;
        padding: 3px 9px;
        border-radius: 6px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-right: 6px;
        display: inline-block;
    }
    .evidence-chip-off {
        background-color: #F1F5F9;
        color: #94A3B8;
        border: 1px solid #E2E8F0;
        padding: 3px 9px;
        border-radius: 6px;
        font-size: 0.78rem;
        font-weight: 500;
        margin-right: 6px;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)


def main():
    st.markdown('<div class="main-header">🛡️ AURA</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Autonomous UI/UX Runtime Assurance — V0.4 Evidence-Based Runtime UI/UX Assurance & Benchmark Platform</div>', unsafe_allow_html=True)

    # Sidebar setup
    st.sidebar.header("🎯 Mode Selection")
    mode_selection = st.sidebar.radio(
        "AURA Audit Mode",
        options=["🧪 LOCAL TEST LAB", "🌐 EXTERNAL WEBSITE"],
        index=0,
        help="Test Lab Mode: Evaluate against known ground-truth defects.\nExternal Website Mode: Audit real websites with same-origin safety restrictions."
    )

    audit_mode = "test_lab" if "TEST LAB" in mode_selection else "external"

    st.sidebar.markdown("---")
    st.sidebar.header("🤖 AI Provider Configuration")
    
    if "provider_select_pending" in st.session_state:
        st.session_state["provider_select"] = st.session_state.pop("provider_select_pending")
    if "provider_select" not in st.session_state:
        st.session_state["provider_select"] = settings.AI_PROVIDER if settings.AI_PROVIDER in PROVIDERS else "mock"
    provider_choice = st.sidebar.selectbox(
        "AI Provider",
        options=PROVIDERS,
        key="provider_select",
        help="Select AI model provider for multimodal candidate finding analysis."
    )

    available_models = AVAILABLE_MODELS.get(provider_choice, [])
    default_model = DEFAULT_MODELS.get(provider_choice, "")
    
    selected_model = st.sidebar.selectbox(
        "Model Selection",
        options=available_models,
        index=available_models.index(default_model) if default_model in available_models else 0,
        help="Select model variant for analysis."
    ) if provider_choice != "mock" else "Mock V0.4 Engine"

    # Remember the active provider so every audit path (incl. the suite benchmark tab) uses the same one
    st.session_state["active_provider"] = {"provider_type": provider_choice, "model_name": selected_model}

    # Handle Password Masked API Key Input per provider stored in st.session_state
    session_key_name = f"{provider_choice}_api_key"
    if session_key_name not in st.session_state:
        st.session_state[session_key_name] = ""

    if provider_choice != "mock":
        entered_key = st.sidebar.text_input(
            f"{provider_choice.capitalize()} API Key",
            value=st.session_state.get(session_key_name, ""),
            type="password",
            help="Session key stored in memory only. Never written to disk or logs."
        )
        st.session_state[session_key_name] = entered_key.strip()

        # Display Credential Source Status Badge
        key_val, source_desc = SessionCredentialsManager.get_credential_for_provider(provider_choice, st.session_state)
        if key_val:
            if "Session" in source_desc:
                st.sidebar.success(f"🟢 {source_desc}")
            else:
                st.sidebar.info(f"🔵 {source_desc}")
        else:
            st.sidebar.warning("⚠️ Key Missing")

        # Clear Key Button
        if st.sidebar.button("🗑️ Clear Session API Key", use_container_width=True):
            st.session_state[session_key_name] = ""
            st.rerun()

    else:
        st.sidebar.info("🟢 Provider: Mock AI (Simulated)")

    # AI provider preflight: local tracked state only on every render (no network, no inference)
    preflight_provider = get_ai_provider(provider_type=provider_choice, model_name=selected_model, session_state=st.session_state)
    pf_key = f"preflight::{provider_choice}::{selected_model}"
    cached_preflight = st.session_state.get(pf_key)
    if cached_preflight is not None and cached_preflight.is_stale():
        # a remote-check snapshot must not outlive its block or be shown as current state forever
        st.session_state.pop(pf_key, None)
        cached_preflight = None
    preflight_result = cached_preflight or run_preflight(preflight_provider, check_remote=False)
    render_preflight_panel(preflight_result, st.sidebar)
    if provider_choice != "mock":
        pc1, pc2 = st.sidebar.columns(2)
        if pc1.button("🩺 Check provider", use_container_width=True,
                      help="Validates key and model via the provider's model-metadata endpoint. Does not run an AI inference."):
            st.session_state[pf_key] = run_preflight(preflight_provider, check_remote=True)
            st.rerun()
        if pc2.button("♻️ Clear tracked state", use_container_width=True,
                      help="Forget AURA's recorded rate-limit/quota state for this provider and model (e.g. after a quota reset or a new key)."):
            ProviderStateStore.clear(provider_choice, selected_model)
            st.session_state.pop(pf_key, None)
            st.rerun()

    # Test Connection Button (runs one small inference: counts toward the provider's quota)
    if st.sidebar.button("🔌 Test AI Connection", use_container_width=True,
                         help="Sends one small AI request. This counts toward the provider's request quota."):
        with st.sidebar:
            with st.spinner("Testing API connection..."):
                active_provider = get_ai_provider(
                    provider_type=provider_choice,
                    model_name=selected_model,
                    session_state=st.session_state
                )
                if hasattr(active_provider, "test_connection_details"):
                    details = active_provider.test_connection_details()
                    ProviderStateStore.record(provider_choice, selected_model, getattr(active_provider, "last_execution_metadata", {}) or {})
                    st.session_state.pop(pf_key, None)
                    if details["success"]:
                        api_str = f"\nAPI: {details['api']}" if details.get("api") else ""
                        st.success(f"✓ {details['status']}\nProvider: {details.get('provider', provider_choice.title())}{api_str}\nModel: {details['actual_model']}\nLatency: {details['latency_ms']} ms")
                    else:
                        st.error(f"✗ {details['status']} ({details.get('error_category', 'ERROR')}):\n{details['error_details']}")
                else:
                    success, raw_msg = active_provider.test_connection()
                    sanitized_msg = sanitize_provider_error(raw_msg)
                    if success:
                        st.success(f"✓ {sanitized_msg}")
                    else:
                        st.error(f"✗ {sanitized_msg}")

    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Browser & Safety Settings")
    headless_toggle = st.sidebar.checkbox("Headless Browser Mode", value=True)
    enable_interactions_toggle = st.sidebar.checkbox("Enable Level-B Interactions", value=True)

    viewport_option = st.sidebar.selectbox(
        "Viewport Preset:",
        options=list(settings.VIEWPORT_PRESETS.keys()),
        index=0,
        help="Select Desktop (1440x900), Tablet (1024x768), or Mobile (390x844) viewport."
    )

    if audit_mode == "test_lab":
        st.markdown("""
        <div class="testlab-banner">
            🧪 <strong>Test Lab Mode Active:</strong> Evaluate AURA against known intentional defect scenarios with ground-truth evaluation metrics (TP, FP, FN, Precision, Recall, F1). Ground truth is isolated from analysis.
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="security-banner">
            🌐 <strong>External Website Mode Active:</strong> Audit real websites using evidence-driven autonomous analysis. Level-B Safety Policy & same-origin navigation restrictions are strictly enforced. Ground truth metrics display N/A.
        </div>
        """, unsafe_allow_html=True)

    # -----------------------------------------------------------------------------
    # Main Mode Execution Input Form
    # -----------------------------------------------------------------------------
    target_url = ""
    selected_lab_site = None
    analyze_btn = False

    if audit_mode == "test_lab":
        TestLabLauncher.start_server()
        lab_sites = TestLabLauncher.list_sites()

        if not lab_sites:
            st.error("No Test Lab sites found in test_lab/ directory.")
            return

        col1, col2, col3, col4 = st.columns([3, 2, 1.2, 1.8])

        with col1:
            site_options = [s["name"] for s in lab_sites]
            selected_site_name = st.selectbox(
                "Select Test Lab Benchmark Suite:",
                options=site_options,
                index=0
            )
            selected_lab_site = next((s for s in lab_sites if s["name"] == selected_site_name), lab_sites[0])
            target_url = selected_lab_site["url"]

        with col2:
            # Count comes from GroundTruthRegistry for the suite currently selected here
            st.write(f"**Expected Defects ({selected_lab_site['id']}):** {selected_lab_site['expected_count']}")
            st.caption(f"**Description:** {selected_lab_site['description']}")

        with col3:
            st.write("")
            analyze_btn = st.button("🚀 Audit Single Suite", type="primary", use_container_width=True)

        with col4:
            st.write("")
            run_all_suites_btn = st.button("🚀 Run Full Test Lab (All 5)", type="secondary", use_container_width=True)

        # A blocked preflight can be followed by an explicit "deterministic-only" choice
        det_only_request = st.session_state.pop("run_deterministic_only", None)
        if det_only_request == "all":
            run_all_suites_btn = True
        elif det_only_request == "single":
            analyze_btn = True
        skip_ai = det_only_request is not None

        if run_all_suites_btn:
            key_val, _ = SessionCredentialsManager.get_credential_for_provider(provider_choice, st.session_state)
            if provider_choice != "mock" and not key_val and not skip_ai:
                st.error(f"⚠️ Provider '{provider_choice.upper()}' requires an API key. Please enter a key in the sidebar or switch to Mock mode.")
                return
            status_container = st.status(f"Running AURA Audit across all {len(lab_sites)} Consolidated Test Lab Suites (sequential, one AI request at a time)...", expanded=True)
            engine = AURAEngine(session_state=st.session_state, provider_type=provider_choice, model_name=selected_model)
            try:
                run = run_all_suites(
                    engine, lab_sites, viewport_preset=viewport_option, headless=headless_toggle,
                    enable_interactions=enable_interactions_toggle, skip_ai=skip_ai,
                    fallback_context=active_fallback_context(provider_choice), on_progress=status_container.write,
                )
            except ProviderPreflightBlocked as blocked:
                status_container.update(label=f"⛔ Not started: AI provider preflight {blocked.result.status}", state="error", expanded=False)
                st.session_state["preflight_blocked"] = {"result": blocked.result, "mode": "all"}
            else:
                stopped = run["stopped"]
                if stopped:
                    status_container.update(label=f"⚠️ Stopped before {stopped['suite']}: AI provider {stopped['status']} (remaining suites NOT EVALUABLE)",
                                            state="error", expanded=True)
                else:
                    status_container.update(label=f"✅ All {len(lab_sites)} Consolidated Test Lab Suites Audited", state="complete", expanded=False)
                suite_metrics = EvaluationEngine.evaluate_suite(settings.TEST_LAB_DIR, run["suite_results"], precomputed=run["suite_evals"])
                suite_metrics["provider"] = "AI skipped (deterministic-only)" if skip_ai else f"{provider_choice} ({selected_model})"
                st.session_state["suite_metrics"] = suite_metrics
                # The detailed report below shows the last suite audited (labelled with its suite id)
                st.session_state["latest_report"] = run["last_report"]
                st.session_state.pop("preflight_blocked", None)

    else:
        skip_ai = st.session_state.pop("run_deterministic_only", None) is not None
        col1, col2 = st.columns([3, 1])

        with col1:
            target_url = st.text_input(
                "Enter Website URL to Audit:",
                value="http://localhost:8000",
                placeholder="https://example.com"
            )

        with col2:
            st.write("")
            st.write("")
            analyze_btn = st.button("🚀 Analyze External Website", type="primary", use_container_width=True) or skip_ai

    # -----------------------------------------------------------------------------
    # Execution Flow for Single Page Analysis
    # -----------------------------------------------------------------------------
    if analyze_btn:
        if audit_mode == "external" and not (target_url.startswith("http://") or target_url.startswith("https://")):
            st.error("⚠️ Invalid URL. Please specify a valid http:// or https:// URL.")
            return

        key_val, _ = SessionCredentialsManager.get_credential_for_provider(provider_choice, st.session_state)
        if provider_choice != "mock" and not key_val and not skip_ai:
            st.error(f"⚠️ Provider '{provider_choice.upper()}' requires an API key. Please enter a key in the sidebar or switch to Mock mode.")
            return

        status_container = st.status(f"AURA Runtime Audit [{audit_mode.upper()} MODE] in progress...", expanded=True)

        def step_callback(title: str, status: str):
            if status == "running":
                status_container.write(f"⏳ **{title}...**")
            elif status == "completed":
                status_container.write(f"✓ **{title}**")
            elif status == "failed":
                status_container.write(f"❌ **{title}**")

        engine = AURAEngine(
            session_state=st.session_state,
            step_callback=step_callback,
            provider_type=provider_choice,
            model_name=selected_model
        )

        try:
            site_dir = selected_lab_site["dir"] if audit_mode == "test_lab" and selected_lab_site else None
            report_data = engine.run_analysis(
                url=target_url,
                viewport_preset=viewport_option,
                headless=headless_toggle,
                enable_interactions=enable_interactions_toggle,
                mode=audit_mode,
                site_dir=site_dir,
                skip_ai=skip_ai,
                fallback_context=active_fallback_context(provider_choice)
            )

            status_container.update(label="✅ Audit & Evidence Verification Complete!", state="complete", expanded=False)
            st.session_state["latest_report"] = report_data
            st.session_state.pop("preflight_blocked", None)
        except ProviderPreflightBlocked as blocked:
            status_container.update(label=f"⛔ Not started: AI provider preflight {blocked.result.status}", state="error", expanded=False)
            st.session_state["preflight_blocked"] = {"result": blocked.result, "mode": "single"}
        except Exception as e:
            sanitized_err = sanitize_provider_error(str(e))
            status_container.update(label=f"❌ Audit Failed: {sanitized_err}", state="error", expanded=True)
            st.error(f"Error executing AURA engine: {sanitized_err}")

    blocked_state = st.session_state.get("preflight_blocked")
    if blocked_state and blocked_state["result"].provider == provider_choice:
        render_blocked_preflight(blocked_state, provider_choice, selected_model)

    # -----------------------------------------------------------------------------
    # Display Dashboard Report
    # -----------------------------------------------------------------------------
    if "latest_report" in st.session_state:
        report_data = st.session_state["latest_report"]
        reported_suite = report_data.get("evaluation", {}).get("site_id")
        if audit_mode == "test_lab" and selected_lab_site and reported_suite and reported_suite != selected_lab_site["id"]:
            st.info(f"ℹ️ The report below is for suite **{reported_suite}**; the selector above shows **{selected_lab_site['id']}**. "
                    f"Expected-defect counts refer to each suite's own ground truth.")
        render_dashboard_report(report_data)


def active_fallback_context(provider_choice: str):
    """The user-chosen fallback applies only while the fallback provider is the one selected."""
    ctx = st.session_state.get("fallback_context")
    return ctx if ctx and ctx.get("fallback_provider") == provider_choice else None


def render_blocked_preflight(blocked_state: dict, provider_choice: str, selected_model: str) -> None:
    """Explicit, traceable choices after a blocked preflight: never switch providers silently."""
    result = blocked_state["result"]
    if result.is_stale(max_age_s=float("inf")):
        # The block recorded earlier has ended: never keep presenting it as an active block
        st.session_state.pop("preflight_blocked", None)
        st.info(f"ℹ️ **{result.provider}**: cooldown expired · preflight required. The earlier {result.status} block ended at "
                f"{(result.blocked_until or '')[:19]} UTC. Start the audit again; a fresh preflight runs first.")
        return
    remaining = result.seconds_remaining()
    if result.status == "COOLDOWN_ACTIVE" and remaining is not None:
        st.caption(f"Retry available in: {int(remaining + 0.999)} seconds")
    st.error(f"⛔ **AI provider preflight BLOCKED** — Provider: **{result.provider}** | Model: **{result.model}** | "
             f"Status: **{result.status}**\n\nReason: {result.reason}\n\nAction: {result.action}. No browser or AI work was started.")
    others = [p for p in PROVIDERS if p not in ("mock", provider_choice)
              and SessionCredentialsManager.get_credential_for_provider(p, st.session_state)[0]]
    cols = st.columns(len(others) + 1)
    for col, other in zip(cols, others):
        if col.button(f"Use another configured provider: {other}", key=f"fallback_{other}"):
            st.session_state["fallback_context"] = {
                "primary_provider": result.provider, "primary_model": result.model,
                "primary_status": result.status, "primary_reason": result.reason,
                "fallback_provider": other, "selected_by": "user",
            }
            st.session_state["provider_select_pending"] = other
            st.session_state.pop("preflight_blocked", None)
            st.rerun()
    if cols[-1].button("Run deterministic-only audit (no AI)", key="det_only"):
        st.session_state["run_deterministic_only"] = blocked_state["mode"]
        st.session_state.pop("preflight_blocked", None)
        st.rerun()
    if not others:
        st.caption("No other provider has an API key configured in this session.")


def format_affected_element(elem) -> str:
    if not elem:
        return "N/A"
    if isinstance(elem, str):
        return elem
    if hasattr(elem, "selector") and elem.selector:
        tag = getattr(elem, "tag", "element")
        return f"{elem.selector} ({tag})" if tag else elem.selector
    if isinstance(elem, dict):
        sel = elem.get("selector") or elem.get("target") or elem.get("id")
        tag = elem.get("tag", "element")
        text = elem.get("text", "")
        if sel:
            return f"{sel} ({tag})" + (f" - '{text}'" if text else "")
        return str(elem)
    return str(elem)


def render_dashboard_report(report_data: dict):
    st.markdown("---")

    report = report_data["report_model"]
    aggregation: AggregationResult = report_data["aggregation"]
    credential_source: str = report_data.get("credential_source", "Unknown")
    audit_id: str = report_data.get("audit_id", "AURA-V0.4.1-AUDIT")
    mode: str = report_data.get("mode", "external")
    evaluation: dict = report_data.get("evaluation", {})
    interaction_log: list = report_data.get("interaction_log", [])
    deductions: dict = report_data.get("deductions", {})
    evidence_coverage: dict = report_data.get("evidence_coverage", {})
    ai_diag = report_data.get("ai_diagnostics")
    raw_ai_candidates = report_data.get("raw_ai_candidates", [])

    if report.is_mock_mode:
        st.markdown("""
        <div class="mock-banner">
            ℹ️ <strong>Mock Mode Active:</strong> "AI" candidates are scripted per Test Lab suite. They exercise the pipeline (verification, correlation, benchmark) but do not measure AI capability. Switch AI Provider in the sidebar to run a live model.
        </div>
        """, unsafe_allow_html=True)

    st.subheader(f"📊 Audit Results [{audit_id}] for {report.url}")
    st.caption(f"Mode: **{mode.upper()}** | Tested at {report.timestamp} | Viewport: {report.viewport['width']}x{report.viewport['height']} | Provider: {report.provider_name} | Credential Source: {credential_source}")

    # 1. Ground Truth Evaluation Scorecard (Test Lab vs External URL)
    st.markdown("### 🧪 Ground Truth Benchmark Evaluation")
    if evaluation.get("ground_truth_available"):
        ai_eval_status = evaluation.get("benchmark_ai_status", "EVALUATED")
        integ_status = evaluation.get("integrity_status", "PASS")
        expected_cnt = evaluation.get("expected_count", 0)

        # Expected count comes from the ground-truth registry for the suite this report evaluated
        st.caption(f"Suite: **{evaluation.get('site_id', 'N/A')}** | Expected Defects (ground-truth registry): **{expected_cnt}**")

        if ai_eval_status == "NOT_EVALUABLE":
            st.error(f"⚠️ **BENCHMARK: NOT EVALUABLE** — AI analysis unavailable ({evaluation.get('ai_status', 'PROVIDER_NOT_EVALUABLE')}). "
                     "TP / FP / FN / Precision / Recall / F1 are not computed, so no AI false negatives are fabricated.")
        elif integ_status in ("FAIL", "INCONSISTENT"):
            st.error(f"🔴 **BENCHMARK INTEGRITY: FAIL** — {evaluation.get('integrity_notes', 'Invariant violation observed.')}")
        else:
            st.success(f"🟢 **BENCHMARK INTEGRITY: PASS** — Expected Defects ({expected_cnt}) == TP ({evaluation.get('true_positives')}) + FN ({evaluation.get('false_negatives')}); one-to-one matching verified")

        def _count_disp(val):
            return "N/A" if val is None else val

        ec1, ec2, ec3, ec4, ec5, ec6 = st.columns(6)
        ec1.metric("Precision", evaluation.get("precision_formatted", "N/A"), help=evaluation.get("precision_note"))
        ec2.metric("Recall", evaluation.get("recall_formatted", "N/A"))
        ec3.metric("F1 Score", evaluation.get("f1_formatted", "N/A"))
        ec4.metric("True Positives (TP)", _count_disp(evaluation.get("true_positives")))
        ec5.metric("False Positives (FP)", _count_disp(evaluation.get("false_positives")))
        ec6.metric("False Negatives (FN)", _count_disp(evaluation.get("false_negatives")))

        if evaluation.get("precision_note"):
            st.info(f"ℹ️ {evaluation['precision_note']}")

        # Deterministic-only evaluation, reported separately when the AI provider was unavailable
        det_only = evaluation.get("deterministic_only")
        if det_only:
            with st.expander("🧮 Deterministic-Only Evaluation (separate from the AI benchmark)", expanded=False):
                st.caption(det_only.get("label", ""))
                st.write(f"Scope: {det_only.get('expected_count')} GT defect(s) {det_only.get('scope_ground_truth_ids')} | "
                         f"TP {det_only.get('true_positives')} | FP {det_only.get('false_positives')} | FN {det_only.get('false_negatives')} | "
                         f"Precision {det_only.get('precision_formatted')} | Recall {det_only.get('recall_formatted')} | "
                         f"Integrity {det_only.get('integrity_status')}")
                if det_only.get("traceability"):
                    st.dataframe(det_only["traceability"], use_container_width=True)

        # Root-cause summary: every FN and FP carries a machine-readable root cause
        if evaluation.get("fn_root_cause_counts") or evaluation.get("fp_root_cause_counts"):
            rc1, rc2 = st.columns(2)
            with rc1:
                st.caption("**FN root causes:** " + (", ".join(f"{k} × {v}" for k, v in evaluation.get("fn_root_cause_counts", {}).items()) or "none"))
            with rc2:
                st.caption("**FP root causes:** " + (", ".join(f"{k} × {v}" for k, v in evaluation.get("fp_root_cause_counts", {}).items()) or "none"))

        # FN Diagnostic Root Cause Breakdown Expander
        if evaluation.get("fn_diagnostics"):
            with st.expander("🔍 View Missed Defect (FN) Root Causes", expanded=False):
                st.caption("Each ground-truth defect without a matching canonical finding, with the root cause derived from this run's candidates and findings.")
                for fn_d in evaluation["fn_diagnostics"]:
                    st.markdown(f"**{fn_d['ground_truth_id']}** | Category: `{fn_d.get('category')}` | Rule: `{fn_d.get('normalized_rule')}` | "
                                f"Target: `{fn_d.get('target')}` | Root cause: **{fn_d.get('root_cause')}**")
                    st.caption(fn_d.get("reason", ""))

        # FP Diagnostic Root Cause Breakdown Expander
        if evaluation.get("fp_diagnostics"):
            with st.expander("🔍 View False Positive (FP) Root Causes", expanded=False):
                st.caption("Eligible canonical findings not matched to a ground-truth defect. An FP is not necessarily wrong: LEGITIMATE_NON_GT_FINDING marks tool-confirmed defects the ground truth does not enumerate.")
                st.dataframe(evaluation["fp_diagnostics"], use_container_width=True)

        # AI coverage: distinguish "AI unavailable" from "AI ran and proposed nothing"
        ai_candidate_cnt = aggregation.source_counts.get("ai", 0)
        if ai_eval_status == "NOT_EVALUABLE":
            st.warning("⚠️ **AI Coverage: NOT EVALUABLE** — no AI candidates exist because the provider request did not succeed.")
        elif expected_cnt > 0 and ai_candidate_cnt == 0:
            st.warning("⚠️ **AI Coverage Warning:** The AI request succeeded but produced no active candidate findings for this suite.")

        # Rejected AI candidates are verification outcomes, not benchmark false positives
        if aggregation.rejected_findings:
            with st.expander(f"🚫 View Rejected AI Candidates ({len(aggregation.rejected_findings)}) — not counted as benchmark FPs", expanded=False):
                for r_f in aggregation.rejected_findings:
                    st.markdown(f"**Candidate:** `{r_f.title}` | Category: `{r_f.category.value}` | Status: **REJECTED**")
                    st.caption(f"Rejection Reason: {r_f.rejection_reason or 'No reproducible browser evidence observed.'}")
                    st.markdown("---")

        # Benchmark Finding Traceability Matrix Expander
        if evaluation.get("traceability"):
            with st.expander("📋 View Benchmark Finding Traceability Audit Trail", expanded=False):
                st.caption("Ground Truth → AI candidate (raw → normalized rule) → verification → canonical finding → match tiers → TP / FP / FN, built from this run's data.")
                for row in evaluation["traceability"]:
                    if row.get("chain"):
                        st.caption(f"`{row['benchmark_status']}` {row['chain']}")
                st.dataframe(evaluation["traceability"], use_container_width=True)

    else:
        st.info("ℹ️ **Ground Truth: Not Available** — Benchmark metrics (Precision, Recall, F1, TP, FP, FN) are strictly reserved for Test Lab Mode scenarios with machine-readable ground truth specifications.")
        ec1, ec2, ec3, ec4 = st.columns(4)
        ec1.metric("Precision", "N/A")
        ec2.metric("Recall", "N/A")
        ec3.metric("F1 Score", "N/A")
        ec4.metric("Ground Truth", "Not Available")

    st.markdown("---")

    # 2. Top Dashboard Score Cards
    ui_disp = f"{report.scores.ui}/100" if isinstance(report.scores.ui, (int, float)) else "N/A (AI Unavailable)"
    ux_disp = f"{report.scores.ux}/100" if isinstance(report.scores.ux, (int, float)) else "N/A (AI Unavailable)"
    a11y_disp = f"{report.scores.accessibility}/100" if isinstance(report.scores.accessibility, (int, float)) else str(report.scores.accessibility)
    rt_disp = f"{report.scores.runtime}/100" if isinstance(report.scores.runtime, (int, float)) else str(report.scores.runtime)

    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    with sc1:
        st.markdown(f'<div class="score-card"><div class="score-value" style="color:#2563EB;">{report.scores.overall}/100</div><div class="score-label">AURA Score</div></div>', unsafe_allow_html=True)
    with sc2:
        st.markdown(f'<div class="score-card"><div class="score-value">{ui_disp}</div><div class="score-label">UI Score</div></div>', unsafe_allow_html=True)
    with sc3:
        st.markdown(f'<div class="score-card"><div class="score-value">{ux_disp}</div><div class="score-label">UX Score</div></div>', unsafe_allow_html=True)
    with sc4:
        st.markdown(f'<div class="score-card"><div class="score-value">{a11y_disp}</div><div class="score-label">Accessibility</div></div>', unsafe_allow_html=True)
    with sc5:
        st.markdown(f'<div class="score-card"><div class="score-value">{rt_disp}</div><div class="score-label">Runtime Score</div></div>', unsafe_allow_html=True)

    # Itemized Score Deductions Collapsible
    if deductions:
        with st.expander("🔍 View Itemized Score Deductions"):
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                st.write("**UI & Responsiveness Deductions:**")
                if deductions.get("ui"):
                    for d_item in deductions["ui"]:
                        st.caption(f"• [{d_item['severity'].upper()}] {d_item['title']}: -{d_item['deduction']} pts ({d_item['status']})")
                else:
                    st.caption("No UI deductions.")

                st.write("**UX & Navigation Deductions:**")
                if deductions.get("ux"):
                    for d_item in deductions["ux"]:
                        st.caption(f"• [{d_item['severity'].upper()}] {d_item['title']}: -{d_item['deduction']} pts ({d_item['status']})")
                else:
                    st.caption("No UX deductions.")

            with d_col2:
                st.write("**Accessibility Deductions:**")
                if deductions.get("accessibility"):
                    for d_item in deductions["accessibility"]:
                        st.caption(f"• [{d_item['severity'].upper()}] {d_item['title']}: -{d_item['deduction']} pts")
                else:
                    st.caption("No Accessibility deductions.")

                st.write("**Runtime Deductions:**")
                if deductions.get("runtime"):
                    for d_item in deductions["runtime"]:
                        st.caption(f"• [{d_item['severity'].upper()}] {d_item['title']}: -{d_item['deduction']} pts")
                else:
                    st.caption("No Runtime deductions.")

    st.markdown("---")

    # Evidence Collection vs AI Analysis Status
    col_ev, col_ai = st.columns(2)
    with col_ev:
        if evidence_coverage:
            cov_pct = evidence_coverage.get("percentage", 100)
            st.write(f"##### 🛡️ Evidence Collection: **{cov_pct}%**")
            chk_items = [f"{'✓' if v else '○'} {k}" for k, v in evidence_coverage.get("checklist", {}).items()]
            st.caption(" | ".join(chk_items))

    with col_ai:
        st.write("##### 🤖 AI Analysis Status")
        # Deterministic interaction evidence comes from the browser, independent of the AI provider
        executed_interactions = sum(1 for i in interaction_log if i.get("status") == "executed")
        evidence_ind = "✓" if executed_interactions > 0 else "—"
        if ai_diag:
            status_val = ai_diag.status.value if hasattr(ai_diag.status, "value") else str(ai_diag.status)
            ai_ok = getattr(ai_diag, "ai_request_succeeded", False) and status_val in ("SUCCESS_WITH_CANDIDATES", "SUCCESS_ZERO_CANDIDATES")
            ai_ind = "✓" if ai_ok else "—"

            st.caption(f"Visual reasoning: {ai_ind} | UX reasoning: {ai_ind} | AI interaction reasoning: {ai_ind} | Interaction evidence: {evidence_ind}")
            st.caption(f"Provider: **{ai_diag.provider_name}** | Requested model: **{ai_diag.requested_model}** | "
                       f"Actual model: **{ai_diag.actual_model}** | Preflight: **{ai_diag.preflight_status or 'N/A'}** | Status: **{status_val}**")
            quota = ai_diag.provider_quota_summary()
            if quota:
                st.caption("Provider-reported quota: " + " | ".join(f"{k.replace('Provider-reported ', '')}: {v}" for k, v in quota.items()))
            fallback = (report_data.get("provider_selection") or {}).get("fallback")
            if fallback:
                st.warning(f"Provider fallback (user-selected): Primary **{fallback['primary_provider']}** ({fallback['primary_model']}) "
                           f"was **{fallback['primary_status']}** → AI findings in this report come from **{fallback['fallback_provider']}** "
                           f"({fallback['fallback_model']}), status **{fallback['fallback_status']}**.")
            if ai_ok:
                st.caption(f"Request: HTTP {ai_diag.http_status or 'N/A'} | Attempts: {ai_diag.attempt_count} | Retries: {ai_diag.retry_count} | "
                           f"Response parsed: {'✓' if ai_diag.ai_response_parsed else '✗'} | Schema valid: {'✓' if ai_diag.ai_schema_valid else '✗'} | "
                           f"Max candidates requested: {ai_diag.max_findings_requested or 'N/A'}")
                st.caption(f"Candidates: **{ai_diag.ai_candidate_count_raw}** raw | {ai_diag.ai_candidate_count_valid} valid | "
                           f"{ai_diag.ai_candidate_count_normalized} normalized | {ai_diag.ai_candidate_count_deduplicated} deduplicated | "
                           f"{ai_diag.independent_candidate_count} independent | {ai_diag.complementary_candidate_count} complementary | "
                           f"{ai_diag.deterministic_duplicate_count} deterministic duplicates | **{ai_diag.ai_candidate_count_confirmed}** confirmed | "
                           f"**{ai_diag.ai_candidate_count_likely}** likely | **{ai_diag.ai_candidate_count_uncertain}** uncertain | "
                           f"**{ai_diag.ai_candidate_count_rejected}** rejected"
                           + (f" | {ai_diag.missing_rule_type_count} rejected for missing rule_type" if ai_diag.missing_rule_type_count else ""))
            else:
                http_part = f" | HTTP {ai_diag.http_status}" if ai_diag.http_status else ""
                st.caption(f"AI reasoning: **Unavailable** | Failure category: **{ai_diag.failure_category or status_val}**{http_part} | "
                           f"Attempts: {ai_diag.attempt_count} | Retries: {ai_diag.retry_count} | AI candidates: 0")
            failure_reason = ai_diag.ai_failure_reason or ai_diag.ai_parse_failure_reason or ai_diag.ai_schema_failure_reason
            if failure_reason:
                st.error(f"⚠️ Reason: {failure_reason}")
        else:
            st.caption(f"AI reasoning: **Not run** | Interaction evidence: {evidence_ind}")

    st.markdown("---")

    # 3. Aggregated Findings & Canonical Correlation Summary
    m_col1, m_col2 = st.columns(2)

    with m_col1:
        st.write("##### 📌 Canonical Findings by Severity (All Sources)")
        counts = aggregation.severity_counts
        ic1, ic2, ic3, ic4 = st.columns(4)
        ic1.metric("🔴 Critical", counts.get("critical", 0))
        ic2.metric("🟠 High", counts.get("high", 0))
        ic3.metric("🟡 Medium", counts.get("medium", 0))
        ic4.metric("🔵 Low", counts.get("low", 0))

    with m_col2:
        st.write("##### 🔍 Verification Status Breakdown")
        status_counts = aggregation.verification_counts
        vc1, vc2, vc3, vc4 = st.columns(4)
        vc1.metric("Confirmed", status_counts.get("confirmed", 0))
        vc2.metric("Likely", status_counts.get("likely", 0))
        vc3.metric("Uncertain", status_counts.get("uncertain", 0))
        vc4.metric("Rejected", status_counts.get("rejected", 0))

    # Canonical Correlation Breakdown Block
    if aggregation.correlation_counts:
        st.write("##### 🔗 Canonical Finding Correlation Breakdown")
        cc = aggregation.correlation_counts
        cc1, cc2, cc3, cc4, cc5 = st.columns(5)
        cc1.metric("AI + AXE", cc.get("ai_plus_axe", 0))
        cc2.metric("AI + Runtime", cc.get("ai_plus_runtime", 0))
        cc3.metric("AXE Only", cc.get("axe_only", 0))
        cc4.metric("Runtime Only", cc.get("runtime_only", 0))
        cc5.metric("AI Only", cc.get("ai_only", 0))

    # Single Aggregated Summary Text Banner
    st.markdown(f"""
    <div class="summary-banner">
        📋 <strong>Verification Summary:</strong> {aggregation.summary_text}
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # 4. Unified Active Findings List
    st.subheader("💡 Verified Runtime & AI Findings")
    st.caption("AURA aggregates accessibility (axe-core), runtime telemetry, and AI candidate findings into a single unified audit feed verified by deterministic browser evidence.")

    if not aggregation.findings:
        st.success("🎉 No active UI/UX, accessibility, or runtime defects identified!")
    else:
        for idx, finding in enumerate(aggregation.findings, start=1):
            finding: AURAFinding = finding
            v_status = finding.verification_status.value.upper()
            badge_style = "badge-confirmed" if v_status == "CONFIRMED" else ("badge-likely" if v_status == "LIKELY" else "badge-uncertain")

            # Source badge CSS class
            src_val = finding.source.value.lower()
            src_css = f"badge-source-{src_val}"

            with st.expander(f"Finding #{idx}: {finding.title} ({finding.severity.value.upper()} | {finding.category.value})", expanded=(idx == 1)):
                hc1, hc2 = st.columns([3, 1])
                with hc1:
                    st.markdown(f"### [{finding.source.value.upper()}] {finding.title}")
                    st.caption(f"ID: `{finding.id}` | Category: **{finding.category.value}** | Severity: **{finding.severity.value.upper()}**")
                with hc2:
                    st.markdown(f"**Source:** <span class='{src_css}'>{finding.source.value.upper()}</span>", unsafe_allow_html=True)
                    st.markdown(f"**Verification:** <span class='{badge_style}'>{v_status}</span>", unsafe_allow_html=True)
                    score_display = (finding.verification_score if finding.verification_score is not None else finding.confidence) * 100
                    st.write(f"**Verified Score:** {score_display:.0f}%")

                st.markdown("---")

                # Observation
                st.markdown("#### 👁️ OBSERVATION")
                st.write(finding.observation or finding.description)

                # Evidence Chips
                st.markdown("#### 📄 EVIDENCE")
                flags = getattr(finding, "evidence_flags", getattr(finding.evidence, "flags", {}))
                chip_html = ""
                chip_html += "<span class='evidence-chip-on'>✓ Screenshot</span>" if flags.get("screenshot") else "<span class='evidence-chip-off'>○ Screenshot</span>"
                chip_html += "<span class='evidence-chip-on'>✓ DOM</span>" if flags.get("dom") else "<span class='evidence-chip-off'>○ DOM</span>"
                chip_html += "<span class='evidence-chip-on'>✓ Accessibility</span>" if flags.get("accessibility") else "<span class='evidence-chip-off'>○ Accessibility</span>"
                chip_html += "<span class='evidence-chip-on'>✓ Runtime</span>" if flags.get("runtime") else "<span class='evidence-chip-off'>○ Runtime</span>"
                st.markdown(chip_html, unsafe_allow_html=True)

                sources = getattr(finding, "evidence_sources", getattr(finding.evidence, "sources", []))
                if sources:
                    st.write("")
                    for ev_src in sources:
                        st.caption(f"• {ev_src}")

                # Why it matters
                if finding.why_it_matters:
                    st.markdown("#### ❓ WHY THIS MATTERS")
                    st.write(finding.why_it_matters)

                # Recommendation
                if finding.recommendation:
                    st.markdown("#### 💡 RECOMMENDATION")
                    st.info(finding.recommendation)

                # Technical Details Collapsible
                with st.expander("🛠️ Technical Details & Selectors"):
                    st.write(f"**Affected Element / Target:** `{format_affected_element(finding.affected_element)}`")
                    st.write(f"**Full Description:** {finding.description}")
                    st.json(finding.model_dump())

    # 5. Dedicated Rejected AI Findings Section
    if aggregation.rejected_findings:
        st.markdown("---")
        st.subheader("🚫 Rejected AI Findings")
        st.caption("These AI observations were tested by the AURA Verification Engine and REJECTED because they were contradicted or unsupported by browser evidence.")

        for r_finding in aggregation.rejected_findings:
            r_finding: AURAFinding = r_finding
            with st.expander(f"Rejected: {r_finding.title} (AI Claim)", expanded=False):
                st.markdown(f"**AI Observation:** {r_finding.observation}")
                st.markdown(f"**Rejection Reason:** <span class='badge-rejected'>{r_finding.rejection_reason or 'Contradicted by physical browser evidence'}</span>", unsafe_allow_html=True)
                st.caption(f"AI Confidence was {(r_finding.ai_confidence or 0.8)*100:.0f}%, but physical browser evidence contradicted the observation.")

    # 6. Organized Evidence Panel Tabs
    st.markdown("---")
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📸 Page Screenshot", "♿ Accessibility (axe-core)", "⚡ Runtime Telemetry",
        "🌐 DOM Evidence", "🖱️ Interaction Log", "🤖 AI Candidate Reasoning", "📊 Suite Benchmark"
    ])

    with tab1:
        if report.runtime_telemetry.screenshot_path and Path(report.runtime_telemetry.screenshot_path).exists():
            image = Image.open(report.runtime_telemetry.screenshot_path)
            st.image(image, caption=f"Viewport Screenshot ({report.viewport['width']}x{report.viewport['height']}) Captured by Playwright", use_container_width=True)
        else:
            st.info("No screenshot file available.")

    with tab2:
        st.write(f"Total WCAG violations detected by axe-core: **{len(report.accessibility_violations)}**")
        if report.accessibility_violations:
            for viol in report.accessibility_violations:
                st.markdown(f"""
                <div style="background:#FFF5F5; border-left:4px solid #E53E3E; padding:12px; margin-bottom:10px; border-radius:4px;">
                    <strong style="color:#C53030;">[{viol.impact.upper()}] {viol.rule}</strong>: {viol.description}<br/>
                    <small><strong>Why it matters:</strong> {viol.why_it_matters or 'Users of assistive technology may be unable to interact with this element.'}</small><br/>
                    <span class="badge-confirmed">STATUS: CONFIRMED</span>
                </div>
                """, unsafe_allow_html=True)
                with st.expander(f"🛠️ Show technical details for [{viol.rule}] ({len(viol.target)} node target{'s' if len(viol.target) != 1 else ''})"):
                    st.write(f"**Total Affected Nodes:** {len(viol.target)}")
                    for t_idx, tgt in enumerate(viol.target, start=1):
                        st.caption(f"  Node #{t_idx}: `{tgt}`")
                    if viol.help_url:
                        st.write(f"**Documentation:** [{viol.help_url}]({viol.help_url})")
        else:
            st.success("No WCAG accessibility violations detected by axe-core.")

    with tab3:
        st.write(f"**Page Load Timing:** {report.runtime_telemetry.page_load_time_ms:.1f} ms")
        col_c, col_n = st.columns(2)

        with col_c:
            st.write(f"**Console Events ({len(report.runtime_telemetry.console_errors)}):**")
            if report.runtime_telemetry.console_errors:
                for err in report.runtime_telemetry.console_errors:
                    st.code(f"[{err.category.value}] {err.type.upper()}: {err.text}\nLocation: {err.location or 'N/A'}")
            else:
                st.write("No console errors recorded.")

        with col_n:
            st.write(f"**Network Events ({len(report.runtime_telemetry.network_failures)}):**")
            if report.runtime_telemetry.network_failures:
                for net in report.runtime_telemetry.network_failures:
                    st.code(f"[{net.category.value}] {net.method} {net.url} -> {net.status} {net.status_text}")
            else:
                st.write("No 4xx/5xx network failures recorded.")

    with tab4:
        st.write("##### 🌐 DOM Structure & Metadata Summary")
        st.caption("Extracted interactive element hierarchy and layout geometry.")
        dom_sum = report.runtime_telemetry.dom_summary
        st.write(f"**Total Elements:** {dom_sum.get('total_elements', 0)} | **Document Scroll Width:** {dom_sum.get('doc_scroll_width', 0)}px | **Horizontal Overflow:** {'⚠️ YES' if dom_sum.get('has_horizontal_overflow') else 'NO'}")
        
        interactive_count = sum(1 for f in aggregation.findings if getattr(f, 'evidence_flags', {}).get("dom"))
        st.write(f"**Interactive Elements Correlated with Evidence:** {interactive_count}")

    with tab5:
        st.write("##### 🖱️ Hypothesis-Driven Level-B Controlled Interaction Log")
        st.caption("All executed and blocked autonomous browser interactions logged under AURA Safety Policy enforcement.")
        if interaction_log:
            st.dataframe(interaction_log, use_container_width=True)
        else:
            st.info("No controlled interactions executed during this audit run.")

    with tab6:
        st.write("##### 🤖 Candidate AI Reasoning & Prompt Context")
        st.caption("AI candidate findings generated prior to independent evidence verification (status: candidate).")
        st.write(f"**AI Provider:** {report.provider_name}")
        
        if ai_diag:
            st.write("##### 📊 AI Analysis Breakdown:")
            st.json(ai_diag.to_summary_dict())
        else:
            st.write(f"**Active AI Candidates:** {aggregation.source_counts.get('ai', 0)}")
            st.write(f"**Rejected AI Candidates:** {len(aggregation.rejected_findings)}")

        st.markdown("#### 💡 Generated AI Candidates (Pre-Verification)")
        if raw_ai_candidates:
            for idx, cand in enumerate(raw_ai_candidates, start=1):
                c_id = getattr(cand, "candidate_id", None) or getattr(cand, "id", f"AI-{idx:03d}")
                cat_val = getattr(cand, "category", "UI")
                title_val = getattr(cand, "title", "AI Candidate")
                rule_val = getattr(cand, "normalized_rule", getattr(cand, "rule_type", "defect"))
                sev_val = getattr(cand, "severity", "medium")
                conf_val = getattr(cand, "confidence", 0.8)
                t_type = getattr(cand, "ai_contribution_type", "NOVEL_AI_INSIGHT")
                t_score = getattr(cand, "ai_contribution_score", 1.0)
                targ_val = format_affected_element(getattr(cand, "affected_element", getattr(cand, "target", "body")))

                with st.expander(f"Candidate [{c_id}]: [{cat_val}] {title_val} ({sev_val.upper()} | Rule: {rule_val} | Conf: {conf_val*100:.0f}%)", expanded=(idx == 1)):
                    st.write(f"**Candidate ID:** `{c_id}` | **Category:** `{cat_val}` | **Normalized Rule:** `{rule_val}`")
                    st.write(f"**Target:** `{targ_val}` | **AI Confidence:** `{conf_val:.2f}` | **Status:** `CANDIDATE`")
                    st.write(f"**Contribution Type:** `{t_type}` | **Contribution Score:** `{t_score:.2f}`")
                    st.write(f"**Description:** {getattr(cand, 'description', '')}")
                    st.write(f"**Reasoning Summary:** {getattr(cand, 'observation', getattr(cand, 'claim', title_val))}")
        else:
            st.info("No raw AI candidates available for display.")

    with tab7:
        st.write("##### 📊 Test Lab Suite Benchmark Overview")
        st.caption("Aggregate benchmark performance evaluation across all 5 Consolidated Test Lab Benchmark Suites.")
        active = st.session_state.get("active_provider", {"provider_type": "mock", "model_name": None})
        st.caption(f"Runs with the provider selected in the sidebar: **{active['provider_type']}** ({active['model_name']}).")
        if st.button("📊 Evaluate Full 5-Suite Test Lab Benchmark"):
            with st.spinner("Evaluating all 5 Consolidated Benchmark Suites..."):
                lab_dir = settings.BASE_DIR / "test_lab"
                lab_sites = TestLabLauncher.list_sites()
                engine = AURAEngine(session_state=st.session_state, **active)

                try:
                    run = run_all_suites(engine, lab_sites, viewport_preset="Desktop (1440x900)", headless=True,
                                         enable_interactions=True, skip_ai=False)
                except ProviderPreflightBlocked as blocked:
                    st.error(f"⛔ Not started: AI provider preflight {blocked.result.status}: {blocked.result.reason}")
                else:
                    if run["stopped"]:
                        st.warning(f"⚠️ Stopped before {run['stopped']['suite']}: AI provider {run['stopped']['status']}; remaining suites NOT EVALUABLE.")
                    suite_metrics = EvaluationEngine.evaluate_suite(lab_dir, run["suite_results"], precomputed=run["suite_evals"])
                    suite_metrics["provider"] = f"{active['provider_type']} ({active['model_name']})"
                    st.session_state["suite_metrics"] = suite_metrics

        if "suite_metrics" in st.session_state:
            sm = st.session_state["suite_metrics"]
            provider_lbl = sm.get("provider", "unknown")
            st.caption(f"Provider used for this benchmark: **{provider_lbl}**")
            if provider_lbl.startswith("mock"):
                st.warning("⚠️ Mock provider: candidates are scripted per suite, so these numbers validate the pipeline only and are not a measure of AI capability.")
            if sm.get("not_evaluable_suites"):
                st.warning(f"⚠️ Excluded as NOT EVALUABLE (AI provider unavailable): {', '.join(sm['not_evaluable_suites'])}")
            st.markdown(f"#### Overall Suite F1 Score: **{sm['overall_f1_formatted']}** (Precision: **{sm['overall_precision_formatted']}**, Recall: **{sm['overall_recall_formatted']}**)")
            st.markdown(f"#### Macro F1 Score: **{sm.get('macro_f1_formatted', '0%')}** | Micro F1 Score: **{sm.get('micro_f1_formatted', '0%')}**")
            
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Macro Precision", sm.get("macro_precision_formatted", "N/A"))
            c2.metric("Macro Recall", sm.get("macro_recall_formatted", "0%"))
            c3.metric("Macro F1", sm.get("macro_f1_formatted", "0.000"))
            c4.metric("Total Expected", sm.get("total_expected_defects", 0))
            c5.metric("Total TP", sm.get("total_true_positives", 0))
            c6.metric("Total FP", sm.get("total_false_positives", 0))

            st.write("##### 📁 Category-Level Benchmark Breakdown:")
            cat_table = []
            for cat_name, cat_data in sm.get("category_metrics", {}).items():
                cat_table.append({
                    "Category": cat_name,
                    "Expected": cat_data.get("expected", 0),
                    "TP": cat_data.get("tp", 0),
                    "FP": cat_data.get("fp", 0),
                    "FN": cat_data.get("fn", 0),
                    "Precision": cat_data.get("precision_formatted", "N/A"),
                    "Recall": cat_data.get("recall_formatted", "N/A"),
                    "F1 Score": cat_data.get("f1_formatted", "N/A")
                })
            st.dataframe(cat_table, use_container_width=True)

            st.write("##### 🏥 Consolidated Suite Status Breakdown:")
            clean_evals = []
            for ev in sm.get("suite_evaluations", sm.get("scenario_evaluations", [])):
                clean_evals.append({
                    "Suite": ev.get("site_name"),
                    "Expected": ev.get("expected_count"),
                    "Detected": ev.get("detected_count"),
                    "TP": ev.get("true_positives"),
                    "FP": ev.get("false_positives"),
                    "FN": ev.get("false_negatives"),
                    "Precision": ev.get("precision_formatted"),
                    "Recall": ev.get("recall_formatted"),
                    "F1 Score": ev.get("f1_formatted"),
                    "Status": ev.get("status_icon"),
                    "Integrity": ev.get("integrity_status")
                })
            st.dataframe(clean_evals, use_container_width=True)

            with st.expander("🔍 View Per-Suite Benchmark Traceability Audit Matrices", expanded=False):
                for ev in sm.get("suite_evaluations", sm.get("scenario_evaluations", [])):
                    if ev.get("traceability"):
                        st.markdown(f"**Suite:** `{ev.get('site_name')}` | Expected: `{ev.get('expected_count')}` | TP: `{ev.get('true_positives')}` | FP: `{ev.get('false_positives')}` | FN: `{ev.get('false_negatives')}`")
                        st.dataframe(ev["traceability"], use_container_width=True)
                        st.markdown("---")



if __name__ == "__main__":
    main()
