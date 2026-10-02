"""
Test Lab "Run All": the 5 suites run strictly one after another (AI concurrency = 1).

Suite N+1 starts only after suite N has completed. Between suites the runner waits (bounded) for the
provider's reported capacity (pacing.wait_for_provider_capacity). If the provider becomes unavailable
mid-run, suites already evaluated are kept and the remaining ones are reported as NOT_EVALUABLE "not run";
nothing is retried in parallel and no benchmark value is invented.
"""
from typing import Any, Callable, Dict, List, Optional

from aura.agent.pacing import wait_for_provider_capacity
from aura.agent.provider_status import ProviderPreflightBlocked
from aura.evaluation.evaluator import EvaluationEngine


def run_all_suites(
    engine: Any,
    sites: List[Dict[str, Any]],
    *,
    viewport_preset: str,
    headless: bool,
    enable_interactions: bool,
    skip_ai: bool,
    fallback_context: Optional[Dict[str, Any]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    max_pacing_wait_s: float = 90.0,
) -> Dict[str, Any]:
    """
    Returns {"suite_results", "suite_evals", "last_report", "stopped": None | {suite, status, reason}}.
    Raises ProviderPreflightBlocked only if the FIRST suite is blocked (nothing ran; the caller offers
    the explicit deterministic-only choice, as for a single audit).
    """
    say = on_progress or (lambda _msg: None)
    provider = engine.orchestrator.provider
    suite_results: Dict[str, Any] = {}
    suite_evals: Dict[str, Dict[str, Any]] = {}
    last_report = None
    stopped = None

    for idx, site in enumerate(sites):
        if idx > 0 and not skip_ai:
            wait_for_provider_capacity(
                provider, max_wait_s=max_pacing_wait_s,
                on_wait=lambda s, why: say(f"⏸️ Waiting {s:.0f}s before {site['name']} ({why})"))
        say(f"⏳ **[{idx + 1}/{len(sites)}] Auditing {site['name']}...**")
        try:
            res = engine.run_analysis(
                url=site["url"], viewport_preset=viewport_preset, headless=headless,
                enable_interactions=enable_interactions, mode="test_lab", site_dir=site["dir"],
                skip_ai=skip_ai, fallback_context=fallback_context,
            )
        except ProviderPreflightBlocked as blocked:
            if idx == 0:
                raise
            r = blocked.result
            stopped = {"suite": site["id"], "status": r.status, "reason": r.reason}
            say(f"⛔ AI provider unavailable before {site['name']} ({r.status}); remaining suites not run.")
            for rest in sites[idx:]:
                suite_evals[rest["id"]] = EvaluationEngine.not_run(rest["dir"], f"AI provider preflight {r.status}: {r.reason}")
            break
        suite_results[site["id"]] = res["aggregation"].all_active_findings
        suite_evals[site["id"]] = res["evaluation"]
        last_report = res
    return {"suite_results": suite_results, "suite_evals": suite_evals, "last_report": last_report, "stopped": stopped}
