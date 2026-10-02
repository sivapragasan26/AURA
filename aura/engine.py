from pathlib import Path
from typing import Dict, Any, Optional, Callable
from aura.config import settings
from aura.agent.provider import AIProvider
from aura.agents.orchestrator import AURAOrchestrator


class AURAEngine:
    """Core entry engine delegating V0.4 workflow execution to AURAOrchestrator."""

    def __init__(
        self,
        provider: Optional[AIProvider] = None,
        session_state: Optional[Dict[str, Any]] = None,
        step_callback: Optional[Callable[[str, str], None]] = None,
        provider_type: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.orchestrator = AURAOrchestrator(
            provider=provider,
            session_state=session_state,
            step_callback=step_callback,
            provider_type=provider_type,
            model_name=model_name
        )

    def run_analysis(
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
        """Executes full V0.4 analysis workflow for given URL in Test Lab Mode or External URL Mode."""
        return self.orchestrator.run_audit(
            url=url,
            viewport_preset=viewport_preset,
            headless=headless,
            enable_interactions=enable_interactions,
            mode=mode,
            site_dir=site_dir,
            skip_ai=skip_ai,
            preflight=preflight,
            fallback_context=fallback_context
        )
