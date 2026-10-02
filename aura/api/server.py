"""
AURA local API: the boundary between the Chrome extension (primary product) and the AURA engine.

    Chrome extension (side panel) --HTTP, 127.0.0.1 + pairing token--> this API --> AURAOrchestrator.analyze_evidence

Endpoints
  GET  /api/health                                   engine + provider status (no secrets); `paired` if token valid
  POST /api/interaction-plan                         live-session interaction plan (policy is enforced HERE)
  POST /api/audits                                   analyse an EvidenceBundle -> audit view
  GET  /api/audits/{audit_id}                        stored audit view
  POST /api/audits/{audit_id}/findings/{fid}/explain grounded explanation (no AI request)
  GET  /api/audits/{audit_id}/findings/{fid}/screenshot  the capture, cropped to that finding
  POST /api/audits/{audit_id}/ask                    Ask AURA (one AI request; foundation)

AI concurrency is 1: every AI-using request is serialized by one lock (provider rate limits, reliability).
"""
import json
import threading
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from aura import __version__ as ENGINE_VERSION
from aura.agent.provider_status import run_preflight
from aura.agent.providers import get_ai_provider
from aura.agents.browser_agent import BrowserAgent
from aura.agents.orchestrator import AURAOrchestrator
from aura.api import security
from aura.api.provider_config import PROVIDER_LABELS, ProviderConfig
from aura.api import shots
from aura.api.store import AuditStore
from aura.api.views import build_audit_view
from aura.assistant.chat import ask as ask_aura
from aura.assistant.explain import explain_finding
from aura.browser.interaction_policy import InteractionPolicy
from aura.config import settings
from aura.evidence.bundle import EvidenceBundle
from aura.security.credentials import sanitize_provider_error
from aura.utils.logger import logger

API_VERSION = "1"
MAX_PLAN_ELEMENTS = 400

# One AI request at a time across the whole server (sequential AI execution)
AI_LOCK = threading.Lock()

# Provider selection lives here, in the server process. The extension picks a provider and may hand over an
# API key once; the key never comes back out (see aura/api/provider_config.py).
PROVIDERS = ProviderConfig()


def configured_provider() -> Tuple[str, Optional[str]]:
    """The provider and model the NEXT scan will use."""
    selection = PROVIDERS.selection()
    return selection.provider, selection.model


def make_provider(provider: Optional[str] = None, model: Optional[str] = None):
    """Builds the selected provider with its server-side credentials (never a silent Mock fallback)."""
    if provider is None:
        provider, model = configured_provider()
    return get_ai_provider(provider_type=provider, model_name=model, session_state=PROVIDERS.session_state())


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status)


def create_app(token: Optional[str] = None, store: Optional[AuditStore] = None) -> Starlette:
    api_token = token or security.load_or_create_token()
    audit_store = store or AuditStore()
    allow_list = security.allowed_origins()

    def guard(request: Request, require_token: bool = True) -> Optional[JSONResponse]:
        if not security.host_allowed(request.headers.get("host")):
            return _error(403, "HOST_NOT_ALLOWED", "The AURA API only answers on the loopback interface.")
        if not security.origin_allowed(request.headers.get("origin"), allow_list):
            return _error(403, "ORIGIN_NOT_ALLOWED", "Requests from web pages are not accepted.")
        if require_token and not security.token_matches(api_token, request.headers.get(security.TOKEN_HEADER)):
            return _error(401, "UNAUTHORIZED", "Missing or invalid pairing token. Paste the token printed by the AURA "
                                               "server into the extension's settings.")
        return None

    async def read_json(request: Request) -> Tuple[Optional[Any], Optional[JSONResponse]]:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > security.MAX_BODY_BYTES:
            return None, _error(413, "PAYLOAD_TOO_LARGE", "Evidence bundle is too large.")
        body = await request.body()
        if len(body) > security.MAX_BODY_BYTES:
            return None, _error(413, "PAYLOAD_TOO_LARGE", "Evidence bundle is too large.")
        try:
            return json.loads(body or b"{}"), None
        except ValueError:
            return None, _error(400, "INVALID_JSON", "Request body is not valid JSON.")

    async def health(request: Request) -> JSONResponse:
        denied = guard(request, require_token=False)
        if denied:
            return denied
        provider_key, model = configured_provider()
        provider = make_provider(provider_key, model)
        pf = run_preflight(provider, check_remote=False)  # local tracked state only: no network, no inference
        return JSONResponse({
            "status": "ok",
            "engine_version": ENGINE_VERSION,
            "api_version": API_VERSION,
            "paired": security.token_matches(api_token, request.headers.get(security.TOKEN_HEADER)),
            "ai": {"provider": provider_key, "label": PROVIDER_LABELS.get(provider_key, provider_key),
                   "is_mock": provider_key == "mock",
                   "model": getattr(provider, "model", model), "configured": pf.status != "NOT_CONFIGURED",
                   "key_configured": PROVIDERS.has_key(provider_key) or provider_key == "mock",
                   "preflight_status": pf.status, "preflight_reason": pf.reason, "blocked": pf.blocked,
                   "blocked_until": pf.blocked_until, "concurrency": 1,
                   "requests_per_scan": 0 if provider_key == "mock" else 1},
        })

    async def list_providers(request: Request) -> JSONResponse:
        denied = guard(request)
        if denied:
            return denied
        return JSONResponse({"providers": PROVIDERS.describe(), "selected": configured_provider()[0],
                             "model": configured_provider()[1]})

    async def select_provider(request: Request) -> JSONResponse:
        """Chooses the provider for the NEXT scan. An API key given here stays in this process."""
        denied = guard(request)
        if denied:
            return denied
        data, err = await read_json(request)
        if err:
            return err
        try:
            selection = PROVIDERS.set(str((data or {}).get("provider") or ""), (data or {}).get("model"),
                                      (data or {}).get("api_key"))
        except ValueError as e:
            return _error(400, "UNKNOWN_PROVIDER", str(e))
        logger.info(f"AI provider selected: {selection.provider} / {selection.model}")  # never logs the key
        return JSONResponse({"providers": PROVIDERS.describe(), "selected": selection.provider, "model": selection.model})

    def _test_provider() -> Dict[str, Any]:
        provider_key, model = configured_provider()
        provider = make_provider(provider_key, model)
        if provider_key == "mock":
            return {"status": "READY", "detail": "Mock AI is built in: it returns scripted findings for demos and tests, "
                                                 "not real model analysis.", "provider": provider_key, "model": model}
        if not PROVIDERS.has_key(provider_key):
            return {"status": "NOT_CONFIGURED", "detail": f"No API key for {PROVIDER_LABELS.get(provider_key, provider_key)}.",
                    "provider": provider_key, "model": model}
        with AI_LOCK:
            result = run_preflight(provider, check_remote=True)  # model metadata only: never an inference
        return {"status": result.status, "detail": result.reason, "provider": provider_key, "model": model,
                "blocked": result.blocked, "checked_remotely": result.checked_remotely}

    async def test_provider(request: Request) -> JSONResponse:
        denied = guard(request)
        if denied:
            return denied
        try:
            return JSONResponse(await run_in_threadpool(_test_provider))
        except Exception as e:
            return JSONResponse({"status": "CONNECTION_FAILED", "detail": sanitize_provider_error(e)[:300]})

    async def interaction_plan(request: Request) -> JSONResponse:
        denied = guard(request)
        if denied:
            return denied
        data, err = await read_json(request)
        if err:
            return err
        page_url = str((data or {}).get("page_url") or "")
        elements = (data or {}).get("elements") or []
        if not isinstance(elements, list):
            return _error(400, "INVALID_REQUEST", "elements must be a list")
        elements = [e for e in elements[:MAX_PLAN_ELEMENTS] if isinstance(e, dict) and isinstance(e.get("selector"), str)]
        budget = InteractionPolicy.LIVE_SESSION_BUDGET
        plan, blocked = [], []
        for _, action, item in BrowserAgent.plan_interactions(elements):
            if action != "click":
                continue  # typing into fields never happens in the user's session
            ok, reason = InteractionPolicy.is_action_safe_live_session("click", item, current_url=page_url)
            entry = {"selector": item["selector"], "action": "click", "text": str(item.get("text") or "")[:80], "reason": reason}
            if ok and len(plan) < budget:
                plan.append(entry)
            elif not ok:
                blocked.append(entry)
        return JSONResponse({"plan": plan, "blocked": blocked[:50], "budget": budget,
                             "policy": "AURA live-session policy: clicks only; no typing, form submission or navigation."})

    def _run_audit(bundle: EvidenceBundle, use_ai: bool) -> Dict[str, Any]:
        provider_key, model = configured_provider()
        with AI_LOCK:
            orchestrator = AURAOrchestrator(provider=make_provider(provider_key, model))
            report = orchestrator.analyze_evidence(bundle, skip_ai=not use_ai)
        return build_audit_view(report)

    async def create_audit(request: Request) -> JSONResponse:
        denied = guard(request)
        if denied:
            return denied
        data, err = await read_json(request)
        if err:
            return err
        options = (data or {}).get("options") or {}
        try:
            bundle = EvidenceBundle(**((data or {}).get("bundle") or {}))
        except ValidationError as e:
            problems = [{"field": ".".join(str(p) for p in d.get("loc", [])), "problem": d.get("msg")} for d in e.errors()[:10]]
            return _error(422, "INVALID_EVIDENCE", "Evidence bundle failed validation.", problems=problems)
        try:
            view = await run_in_threadpool(_run_audit, bundle, bool(options.get("ai", True)))
        except ValueError as e:
            return _error(400, "INVALID_EVIDENCE", sanitize_provider_error(e)[:300])
        except Exception as e:  # engine failure: report it as a failed scan, never as an empty result
            logger.error(f"Extension audit failed: {sanitize_provider_error(e)}")
            return _error(500, "SCAN_FAILED", "The AURA engine failed to analyse this page.",
                          detail=sanitize_provider_error(e)[:300])
        audit_store.put(view)
        return JSONResponse(view)

    async def get_audit(request: Request) -> JSONResponse:
        denied = guard(request)
        if denied:
            return denied
        view = audit_store.get(request.path_params["audit_id"])
        if view is None:
            return _error(404, "NOT_FOUND", "Audit not found.")
        return JSONResponse(view)

    async def finding_shot(request: Request) -> Any:
        """The part of the scan's capture this finding is about, with the element boxed."""
        denied = guard(request)
        if denied:
            return denied
        audit_id = request.path_params["audit_id"]
        view = audit_store.get(audit_id)
        if view is None:
            return _error(404, "NOT_FOUND", "Audit not found.")
        fid = request.path_params["finding_id"]
        finding = next((f for f in view.get("findings") or [] if f.get("id") == fid), None)
        if finding is None:
            return _error(404, "NOT_FOUND", "Finding not found in this audit.")
        if not shots.has_capture(audit_id):
            return _error(404, "NO_CAPTURE", "No screenshot was kept for this scan. Scan the page again to "
                                             "capture one.")
        viewport_width = (view.get("viewport") or {}).get("width")
        png = await run_in_threadpool(shots.render, audit_id, finding, viewport_width)
        if png is None:
            return _error(404, "NO_REGION", "AURA has no part of the screenshot for this one: the "
                                            "screenshot covers what was on screen during the scan, and "
                                            "this sits outside it or has no recorded position.")
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    async def explain(request: Request) -> JSONResponse:
        denied = guard(request)
        if denied:
            return denied
        view = audit_store.get(request.path_params["audit_id"])
        if view is None:
            return _error(404, "NOT_FOUND", "Audit not found.")
        fid = request.path_params["finding_id"]
        finding = next((f for f in view.get("findings") or [] if f.get("id") == fid), None)
        if finding is None:
            return _error(404, "NOT_FOUND", "Finding not found in this audit.")
        return JSONResponse(explain_finding(finding))

    def _ask(view: Dict[str, Any], question: str, finding_id: Optional[str]) -> Dict[str, Any]:
        with AI_LOCK:
            return ask_aura(make_provider(), view, question, finding_id)

    async def ask(request: Request) -> JSONResponse:
        denied = guard(request)
        if denied:
            return denied
        view = audit_store.get(request.path_params["audit_id"])
        if view is None:
            return _error(404, "NOT_FOUND", "Audit not found.")
        data, err = await read_json(request)
        if err:
            return err
        question = str((data or {}).get("question") or "")
        finding_id = (data or {}).get("finding_id")
        finding_id = finding_id if isinstance(finding_id, str) and finding_id else None
        # The answer is scoped to the finding named in THIS request. A finding id that does not belong to
        # this audit is an error, never a silent fall back to some other finding's context.
        if finding_id and not any(f.get("id") == finding_id for f in view.get("findings") or []):
            return _error(404, "FINDING_NOT_FOUND", "That finding is not part of this audit.")
        result = await run_in_threadpool(_ask, view, question, finding_id)
        return JSONResponse(result)

    routes = [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/providers", list_providers, methods=["GET"]),
        Route("/api/providers/select", select_provider, methods=["POST"]),
        Route("/api/providers/test", test_provider, methods=["POST"]),
        Route("/api/interaction-plan", interaction_plan, methods=["POST"]),
        Route("/api/audits", create_audit, methods=["POST"]),
        Route("/api/audits/{audit_id}", get_audit, methods=["GET"]),
        Route("/api/audits/{audit_id}/findings/{finding_id}/explain", explain, methods=["POST"]),
        Route("/api/audits/{audit_id}/findings/{finding_id}/screenshot", finding_shot, methods=["GET"]),
        Route("/api/audits/{audit_id}/ask", ask, methods=["POST"]),
    ]
    return Starlette(routes=routes)
