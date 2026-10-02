"""
Extension-facing view of an audit.

Built from the engine's report_data, it keeps AURA's semantic distinctions explicit:
  - findings: FINAL (canonical) findings only, each labelled with its origin (deterministic evidence vs a
    verified AI candidate), verification status and AI contribution;
  - rejected_ai_candidates: AI hypotheses the verifier rejected. Listed for transparency, never as problems;
  - ai: what happened to AI analysis (never "0 problems found" when AI did not run).
It never contains ground truth, benchmark data, provider credentials or raw screenshots.
"""
from typing import Any, Dict, List, Optional

from aura.api.plain_language import DETECTOR_LABELS, STATUS_LABELS, STATUS_MEANING, plain_for

PAGE_LEVEL_TARGETS = {"", "window", "document", "body", "html", "element", "document element", "window / document",
                      "window / network", "page", "network"}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
VERIFICATION_ORDER = {"CONFIRMED": 0, "LIKELY": 1, "UNCERTAIN": 2, "REJECTED": 3}


def _val(v: Any) -> Any:
    return getattr(v, "value", v)


def ai_state(diagnostics: Any, preflight: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Maps pipeline diagnostics to a user-facing AI state:
      AI_OK, AI_OFF (user chose deterministic-only), AI_UNAVAILABLE, AI_RATE_LIMITED, AI_QUOTA_EXHAUSTED,
      AI_RESPONSE_INVALID.
    """
    if diagnostics is None:
        return {"state": "AI_UNAVAILABLE", "message": "AI analysis did not run."}
    status = _val(diagnostics.status)
    reason = diagnostics.ai_failure_reason or diagnostics.ai_parse_failure_reason or diagnostics.ai_schema_failure_reason
    base = {"provider_status": status, "reason": reason, "retry_after_seconds": diagnostics.retry_after_seconds,
            "rate_limit_kind": getattr(diagnostics, "rate_limit_kind", None)}
    if status in ("SUCCESS_WITH_CANDIDATES", "SUCCESS_ZERO_CANDIDATES"):
        msg = ("AI analysis completed; its candidates were independently verified." if status == "SUCCESS_WITH_CANDIDATES"
               else "AI analysis completed and proposed no candidates.")
        return {**base, "state": "AI_OK", "message": msg}
    if status == "AI_SKIPPED":
        pf_status = (preflight or {}).get("status")
        if reason and reason.startswith("AI provider unavailable"):
            if "QUOTA_EXHAUSTED" in reason:
                state = "AI_QUOTA_EXHAUSTED"
            elif "COOLDOWN_ACTIVE" in reason or "RATE_LIMITED" in reason:
                state = "AI_RATE_LIMITED"
            else:
                state = "AI_UNAVAILABLE"
            return {**base, "state": state, "preflight_status": pf_status,
                    "message": "AI analysis unavailable. Deterministic evidence is available."}
        return {**base, "state": "AI_OFF", "message": "Deterministic-only scan: AI analysis was not requested."}
    if status == "RATE_LIMITED":
        daily = diagnostics.quota_scope == "DAILY"
        return {**base, "state": "AI_QUOTA_EXHAUSTED" if daily else "AI_RATE_LIMITED",
                "message": ("AI provider quota exhausted. " if daily else "AI provider rate limited. ")
                           + "Deterministic evidence is available."}
    if status in ("PARSE_FAILED", "SCHEMA_FAILED", "RESPONSE_EMPTY", "AI_RESPONSE_INVALID"):
        return {**base, "state": "AI_RESPONSE_INVALID",
                "message": "The AI response could not be used. Deterministic evidence is available."}
    return {**base, "state": "AI_UNAVAILABLE", "message": "AI analysis unavailable. Deterministic evidence is available."}


def _describe_target(kind: str, selector: str, text: Optional[str], tag: Optional[str]) -> str:
    """A short human description of the element, so the panel never has to show a raw CSS selector."""
    if kind == "network":
        # Naming the address keeps two failed requests from reading as the same finding.
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(selector)
            where = (parts.netloc + parts.path) if parts.netloc else parts.path
            where = where if len(where) <= 60 else where[:59] + "…"
            return f"the request to {where}" if where else "a request this page made"
        except ValueError:
            return "a request this page made"
    if kind == "page":
        return "the page as a whole"
    label = (text or "").strip()
    if label:
        label = label if len(label) <= 40 else label[:39] + "…"
        return f'the {tag or "element"} "{label}"'
    if tag == "img":
        return "an image on the page"
    named = selector.rsplit(">", 1)[-1].strip()
    return f"the {tag} element ({named})" if tag else f"the element {named}"


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# Selectors that name a whole region of the page rather than one control. A finding matched only to one of
# these is an AREA finding: it is described honestly as an area and is never highlighted as if it were the
# single element the claim was about.
AREA_LEVEL_SELECTORS = {"main", "#main", "body", "html", "#root", "#app", "#__next", "header", "nav", "footer",
                        "aside", "section", "#content", "#page", "#main-content", "#app-root"}
AREA_LABELS = {"header": "Header area", "nav": "Navigation area", "footer": "Page footer area",
               "aside": "Sidebar area", "main": "Main content area", "section": "Page section"}


def _area_label(selector: str, tag: Optional[str]) -> str:
    key = (tag or "").strip().lower() or selector.strip().lower().lstrip("#")
    return AREA_LABELS.get(key, "Page area")


def _target_view(f: Any) -> Dict[str, Any]:
    ae = _field(f, "affected_element")
    target_dict = _field(f, "target") if isinstance(_field(f, "target"), dict) else None
    identity = _field(f, "target_identity") if isinstance(_field(f, "target_identity"), dict) else {}
    selector = (_field(ae, "selector") if ae else None) or (target_dict.get("selector") if target_dict else None) or _field(f, "raw_target") or ""
    selectors = [s for s in ((_field(ae, "target_list") if ae else None) or (target_dict.get("selectors") if target_dict else None) or [selector]) if isinstance(s, str) and s]
    low = selector.strip().lower()
    match_method = (identity or {}).get("target_match_method")
    tag = (_field(ae, "tag") if ae else None) or (target_dict.get("tag") if target_dict else None)
    text = (_field(ae, "text") if ae else None) or (target_dict.get("text") if target_dict else None)
    role = (_field(ae, "role") if ae else None) or (target_dict.get("role") if target_dict else None)
    accessible_name = (_field(ae, "accessible_name") if ae else None) or (identity or {}).get("accessible_name")

    # Did this claim ever match a real element during the scan? For an AI candidate the verifier records
    # that in the evidence flags. A model can name a selector that does not exist on the page
    # ("nav.main-nav"); offering Highlight for it would send the user chasing an element AURA never saw.
    source = _val(_field(f, "source") or _field(f, "detector") or "DETERMINISTIC")
    is_ai = source == "AI" or _field(f, "origin") in ("AI_GENERATED", "VERIFIED_AI_CANDIDATE")
    ev_obj = _field(f, "evidence")
    ev_flags = (_field(ev_obj, "flags") or {}) if ev_obj else {}
    target_unmatched = bool(is_ai and not ev_flags.get("dom"))

    if low.startswith(("http://", "https://", "/")):
        kind = "network"
    elif low in PAGE_LEVEL_TARGETS:
        kind = "page"
    elif match_method == "area_level" or low in AREA_LEVEL_SELECTORS:
        # The verifier could not isolate one control, or the claim landed on a page-level container.
        kind = "area"
    elif target_unmatched:
        kind = "unresolved"
    else:
        kind = (target_dict.get("kind") if target_dict else None) or "element"

    is_element = kind == "element"
    if kind == "area":
        description = (f'{_area_label(selector, tag)} — AURA could not isolate one specific element for this '
                       f'finding.')
    elif kind == "unresolved":
        described = f'"{text.strip()[:40]}"' if (text or "").strip() else "the element it describes"
        description = (f"AURA could not match this suggestion to {described} on the scanned page, so it cannot "
                       f"point at one element.")
    else:
        description = _describe_target(kind, selector, text, tag)

    return {
        "kind": kind,  # element: one control, can be highlighted. area/page/network: no single element.
        "selector": selector if is_element else None,
        "selectors": selectors if is_element else [],
        "label": selector or "page",
        "text": text,
        "accessible_name": accessible_name,
        "role": role,
        "tag": tag,
        "description": description,
        "count": len(selectors) if is_element else 0,
        # Highlight is offered only when there is one real element behind the finding. An area finding says
        # so instead of highlighting an unrelated container.
        "highlightable": bool(is_element and selectors),
        "area_label": _area_label(selector, tag) if kind == "area" else None,
        "match_method": match_method,
        "matched_in_dom": not target_unmatched,
    }


from aura.interpretation import interpret_finding, group_findings_for_presentation


def finding_view(f: Any) -> Dict[str, Any]:
    source = _val(_field(f, "source") or _field(f, "detector") or "DETERMINISTIC")
    is_ai = source == "AI" or _field(f, "origin") == "AI_GENERATED" or _field(f, "origin") == "VERIFIED_AI_CANDIDATE"
    raw_rule = _field(f, "raw_rule") or _field(f, "rule") or ""
    norm_rule = _field(f, "normalized_rule") or raw_rule
    rule = norm_rule if is_ai else raw_rule
    status = _val(_field(f, "verification_status") or "CONFIRMED")
    plain = plain_for(rule, _val(_field(f, "category", "UI")), source, _field(f, "title", ""), _field(f, "description", ""), _field(f, "why_it_matters"), _field(f, "recommendation"))
    interp = interpret_finding(f)

    target_info = _target_view(f)
    # An element target reads better with the interpreter's human location. An area target keeps its own
    # honest wording ("Header area — AURA could not isolate one specific element").
    if target_info["kind"] == "element":
        target_info["description"] = interp["location_description"]
    else:
        interp["location_description"] = target_info["description"]
        interp["human"]["location"] = target_info["description"]

    ev_obj = _field(f, "evidence")
    ev_types = list(_field(ev_obj, "types") or []) if ev_obj else []
    ev_desc = _field(ev_obj, "description") if ev_obj else ""
    ev_sources = list(_field(ev_obj, "sources") or []) if ev_obj else []
    ev_flags = {k: bool(v) for k, v in (_field(ev_obj, "flags") or {}).items()} if ev_obj else {}

    return {
        # Structured Schemas (Phase 4B)
        "human": interp["human"],
        "technical": interp["technical"],

        # Structured Interpretation Layer (Phase 4 primary interface)
        "title": interp["title"],
        "category": interp["category"],
        "severity": interp["severity"],
        "status": interp["status"],
        "summary": interp["summary"],
        "why_it_matters": interp["why_it_matters"],
        "recommendation": interp["recommendation"],
        "location": interp["location_description"],
        "location_description": interp["location_description"],
        "affected_count": interp["affected_count"],
        "what_does_this_mean": interp["what_does_this_mean"],
        "confidence_label": interp["confidence_label"],
        "technical_details": interp["technical"],
        "explanation_specificity": interp["explanation_specificity"],

        # Phase 5 Trust Layer.
        # Finding-level evidence, computed by the interpreter from this finding's own provenance. There is
        # exactly one `evidence` key in this payload: a second one further down used to silently overwrite
        # this, which is how the panel ended up showing audit-wide evidence on every finding.
        "evidence": {
            **(interp.get("evidence") or {}),
            "description": ev_desc,
        },
        "reproduction": interp.get("reproduction"),
        "conclusion": interp.get("conclusion"),
        "why_aura_reported_this": interp.get("why_aura_reported_this"),

        # Preserved core / backward compatibility fields
        "plain": plain,
        "detector": DETECTOR_LABELS.get(source, source),
        "status_label": interp["status"],
        "status_meaning": STATUS_MEANING.get(status, ""),
        "id": _field(f, "id", "F-000"),
        "raw_title": _field(f, "title", ""),
        "description": interp["summary"] or _field(f, "description", ""),
        "observation": _field(f, "observation", ""),
        "verification_status": status,
        "verification_score": _field(f, "verification_score"),
        "verification_note": _field(f, "rejection_reason"),
        "confidence": _field(f, "ai_confidence") if is_ai else _field(f, "confidence"),
        "origin": "VERIFIED_AI_CANDIDATE" if is_ai else _field(f, "origin", "DETERMINISTIC"),
        "source": source,
        "sources": list(_field(f, "sources") or []),
        "rule": rule,
        "normalized_rule": norm_rule,
        "ai_contribution_type": _val(_field(f, "ai_contribution_type")) if _field(f, "ai_contribution_type") else None,
        "ai_contribution_score": _field(f, "ai_contribution_score"),
        "why_ai_needed": _field(f, "why_ai_needed"),
        "candidate_ids": list(_field(f, "candidate_ids") or []),
        "target": target_info,
    }


def _attach_boxes(findings: List[Dict[str, Any]], boxes: Dict[str, Any],
                  capture: Optional[Dict[str, Any]], viewport: Optional[Dict[str, Any]]) -> None:
    """
    Records where each finding's element sat in the capture, so it can be cropped to just that part.

    The capture covers the visible area at scan time. An element further down the page was never in the
    image, so its boxes are dropped and no screenshot is offered for it: a button that can only fail is
    worse than no button.
    """
    if not boxes:
        return
    # The capture is in device pixels, the boxes in CSS pixels. The viewport width gives the ratio.
    visible_height = None
    cap_w = (capture or {}).get("width")
    cap_h = (capture or {}).get("height")
    view_w = (viewport or {}).get("width")
    if cap_w and cap_h and view_w:
        ratio = float(cap_w) / float(view_w)
        if 0.5 <= ratio <= 4.0:
            visible_height = float(cap_h) / ratio

    def in_capture(box: Dict[str, Any]) -> bool:
        if visible_height is None:
            return True
        try:
            return float(box.get("y") or 0) < visible_height
        except (TypeError, ValueError):
            return False

    for f in findings:
        target = f.get("target") or {}
        found = [boxes[s] for s in (target.get("selectors") or []) if s in boxes]
        if not found and target.get("selector") in boxes:
            found = [boxes[target["selector"]]]
        found = [b for b in found if in_capture(b)]
        target["boxes"] = found[:20]
        target["has_shot_region"] = bool(found)
        f["target"] = target


def build_audit_view(report_data: Dict[str, Any]) -> Dict[str, Any]:
    report = report_data["report_model"]
    agg = report_data["aggregation"]
    diag = report_data.get("ai_diagnostics")
    preflight = report_data.get("preflight")
    collection = report_data.get("collection") or {}
    ai = ai_state(diag, preflight)

    raw_findings = [finding_view(f) for f in agg.all_active_findings]
    raw_findings.sort(key=lambda x: (SEVERITY_ORDER.get(x["severity"], 9), VERIFICATION_ORDER.get(x["verification_status"], 9)))

    # A finding AURA cannot explain specifically is not shown as a normal human finding. Its evidence is
    # kept in full and listed separately, so nothing is lost and nothing is padded with filler wording.
    specific = [f for f in raw_findings if f.get("explanation_specificity") != "GENERIC"]
    technical_only = [f for f in raw_findings if f.get("explanation_specificity") == "GENERIC"]
    findings = group_findings_for_presentation(specific)
    _attach_boxes(findings, report_data.get("element_boxes") or {},
                  report_data.get("capture_size"), report.viewport)
    rejected = [{"id": f.id, "candidate_ids": list(f.candidate_ids or []), "title": f.title, "category": _val(f.category),
                 "rule": f.normalized_rule or f.raw_rule, "reason": f.rejection_reason, "target": _target_view(f)}
                for f in agg.rejected_findings]

    scores = report.scores.model_dump()
    coverage = report_data.get("evidence_coverage") or {}
    notices: List[str] = []
    if ai["state"] != "AI_OK":
        notices.append(ai["message"])
    notices.extend(coverage.get("notes") or [])

    if ai["state"] == "AI_OK" and collection.get("axe_available", True):
        result_state = "COMPLETE"
    elif ai["state"] == "AI_RESPONSE_INVALID" or not collection.get("axe_available", True):
        result_state = "PARTIAL"
    else:
        result_state = "DETERMINISTIC_ONLY"

    provider = report_data.get("provider_selection") or {}
    return {
        "audit_id": report_data["audit_id"],
        "page_url": report.url,
        "title": collection.get("title") or report.runtime_telemetry.title,
        "timestamp": report.timestamp,
        "viewport": report.viewport,
        "source": collection.get("source", "playwright"),
        "duration_seconds": report_data.get("duration_seconds"),
        "result_state": result_state,
        "ai": {**ai, "provider": provider.get("provider"), "model": provider.get("actual_model")},
        "scores": {
            "aura": scores.get("overall"),
            "ui": scores.get("ui"),
            "ux": scores.get("ux"),
            "accessibility": scores.get("accessibility") if collection.get("axe_available", True) else "N/A",
            "runtime": scores.get("runtime"),
            "basis": report_data.get("score_basis"),
            "note": "Project-specific AURA scores. The accessibility score is derived from axe-core results and is "
                    "not an official WCAG compliance percentage.",
        },
        "severity_counts": {k: v for k, v in agg.severity_counts.items() if k != "info"},
        "summary": agg.summary_text,
        "findings": findings,
        # Recorded, but held back from the findings list because AURA could not describe them specifically.
        "technical_only_findings": [{"id": f["id"], "rule": f["rule"], "detector": f["detector"],
                                     "raw_title": f["raw_title"], "technical": f["technical"]}
                                    for f in technical_only],
        "rejected_ai_candidates": rejected,
        "ai_candidates": {
            "proposed": getattr(diag, "ai_candidate_count_raw", 0) if diag else 0,
            "verified_confirmed": getattr(diag, "ai_candidate_count_confirmed", 0) if diag else 0,
            "verified_likely": getattr(diag, "ai_candidate_count_likely", 0) if diag else 0,
            "uncertain": getattr(diag, "ai_candidate_count_uncertain", 0) if diag else 0,
            "rejected": getattr(diag, "ai_candidate_count_rejected", 0) if diag else 0,
            "suppressed_as_deterministic_duplicates": getattr(diag, "deterministic_duplicate_count", 0) if diag else 0,
        },
        "evidence_coverage": coverage,
        "notices": notices,
        "steps": [{"title": s.get("title"), "status": s.get("status"), "detail": s.get("detail")}
                  for s in (report.execution_steps or [])],
    }
