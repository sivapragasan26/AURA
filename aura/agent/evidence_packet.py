"""
Focused AI Evidence Packet.

AURA collects far more browser evidence than the AI needs. This module selects only what supports
UI/UX reasoning and builds one provider-neutral packet; each provider only converts the packet's text
and screenshot into its own API format.

Deliberately NOT included: raw DOM/HTML/CSS/JS, element ids and class names (Test Lab ids name the
defects), full console/network logs, third-party noise, duplicate axe/runtime output, ground truth,
benchmark data, previous model answers, credentials and internal AURA state.

Elements are referenced by neutral refs (E1, E2, ...). The ref -> selector map stays inside AURA and is
used to map the AI's targets back to concrete elements.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from aura.config import settings

INTERACTIVE_TAGS = {"button", "a", "input", "select", "textarea"}
STRUCTURE_TAGS = {"form", "label", "nav", "h1", "h2", "h3", "h4", "h5", "h6", "img", "table"}
CONTAINER_TAGS = {"section", "article", "main", "header", "footer", "div"}

MAX_TARGETED_ELEMENTS = 60
MAX_INTERACTIONS = 8
MAX_A11Y_SUMMARIES = 8
MAX_RUNTIME_EVENTS = 5
MAX_LAYOUT_ITEMS = 6


def choose_max_findings(n_interactive: int, configured_cap: Optional[int] = None) -> int:
    """5 candidates for small pages, up to 8 for richer ones, never above the configured cap."""
    cap = configured_cap if configured_cap is not None else settings.AI_MAX_FINDINGS
    wanted = 5 if n_interactive <= 6 else 8
    return max(1, min(cap, wanted))


@dataclass
class EvidencePacket:
    page: Dict[str, Any]
    targeted_dom: List[Dict[str, Any]]
    layout: Dict[str, Any]
    interactions: List[Dict[str, Any]]
    deterministic_findings: Dict[str, List[Dict[str, Any]]]
    max_findings: int
    screenshot_base64: Optional[str] = None
    screenshot_mime: str = "image/png"
    # The screenshot stayed in the browser and the browser attaches it to its own provider request (hosted
    # mode). The image never reaches this process, but the prompt must still tell the model it is looking
    # at one, so the packet is told whether one is attached rather than inferring it from bytes it holds.
    screenshot_in_browser: bool = False
    # AURA-internal: ref -> {selector, tag, text}. Never sent to the AI.
    ref_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_ai_payload(self) -> Dict[str, Any]:
        """The structured evidence the AI receives (the screenshot travels separately as an image)."""
        return {
            "page": self.page,
            "screenshot_attached": bool(self.screenshot_base64) or self.screenshot_in_browser,
            "targeted_dom": self.targeted_dom,
            "layout": self.layout,
            "interactions": self.interactions,
            "deterministic_findings": self.deterministic_findings,
        }

    def to_prompt(self) -> str:
        from aura.agent.prompts import AURA_SYSTEM_PROMPT, build_user_prompt
        return f"{AURA_SYSTEM_PROMPT.format(max_findings=self.max_findings)}\n\n{build_user_prompt(self.to_ai_payload())}"

    def resolve_ref(self, target: Any) -> Optional[Dict[str, Any]]:
        if isinstance(target, str) and target.strip().upper() in self.ref_map:
            return self.ref_map[target.strip().upper()]
        return None


def _short(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _href_kind(href: Optional[str], page_url: str) -> Optional[str]:
    if href is None:
        return None
    h = href.strip().lower()
    if h in ("", "#") or h.startswith("javascript:"):
        return f"placeholder ({_short(href, 24) or 'empty'})"
    if h.startswith("#"):
        return "same-page anchor"
    netloc = urlparse(h).netloc
    if netloc and netloc != urlparse(page_url).netloc:
        return "external"
    return "internal"


def _is_selected(e: Dict[str, Any], status_selectors: set) -> bool:
    tag = e.get("tag")
    if tag in INTERACTIVE_TAGS or tag in STRUCTURE_TAGS or e.get("role") in ("button", "link", "navigation", "alert", "status"):
        return True
    if e.get("selector") in status_selectors:
        return True
    # Important containers only: identified sections/cards, or containers with layout problems
    if tag in CONTAINER_TAGS and e.get("visible"):
        cls = (e.get("class") or e.get("class_name") or "").lower()
        return bool(e.get("id")) or "card" in cls.split() or e.get("overflows_viewport") or e.get("contains_overflow") or e.get("clipped")
    return False


def _selection_priority(e: Dict[str, Any], status_selectors: set) -> int:
    """Lower is kept first when the page has more candidate elements than the packet allows."""
    tag = e.get("tag")
    if (tag in ("button", "input", "select", "textarea", "form", "label", "h1", "h2", "h3")
            or e.get("role") == "button" or e.get("selector") in status_selectors):
        return 0
    if e.get("overflows_viewport") or e.get("contains_overflow") or e.get("clipped"):
        return 0
    if tag in ("nav", "img", "table", "h4", "h5", "h6") or tag in CONTAINER_TAGS:
        return 1
    return 2  # links: often numerous; a page's first links are kept


def _boxes_overlap(a: Dict[str, float], b: Dict[str, float]) -> bool:
    ix = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
    iy = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
    return ix > 1 and iy > 1


def build_evidence_packet(
    telemetry: Any,
    dom_summary: Dict[str, Any],
    accessibility_violations: List[Any],
    interaction_log: Optional[List[Dict[str, Any]]] = None,
    screenshot_base64: Optional[str] = None,
    screenshot_mime: str = "image/png",
    max_findings_cap: Optional[int] = None,
    screenshot_in_browser: bool = False,
) -> EvidencePacket:
    page_url = getattr(telemetry, "url", "")
    elements = dom_summary.get("all_elements") or []
    styles = {r.get("selector"): (r.get("computed_style") or {}) for r in dom_summary.get("raw_elements_with_styles") or []}
    status_selectors = {s.get("selector") for s in dom_summary.get("status_messages") or []}

    # 1. Targeted DOM with neutral refs
    candidates = [(i, e) for i, e in enumerate(elements) if _is_selected(e, status_selectors)]
    kept = sorted(candidates, key=lambda ie: (_selection_priority(ie[1], status_selectors), ie[0]))[:MAX_TARGETED_ELEMENTS]
    selected = [e for _, e in sorted(kept, key=lambda ie: ie[0])]  # back to document order
    ref_map: Dict[str, Dict[str, Any]] = {}
    ref_by_selector: Dict[str, str] = {}
    ref_by_id: Dict[str, str] = {}
    for i, e in enumerate(selected, start=1):
        ref = f"E{i}"
        ref_map[ref] = {"selector": e.get("selector"), "tag": e.get("tag"), "text": _short(e.get("text"), 120)}
        if e.get("selector"):
            ref_by_selector[e["selector"]] = ref
        if e.get("id"):
            ref_by_id[e["id"]] = ref

    targeted_dom = []
    for i, e in enumerate(selected, start=1):
        tag = e.get("tag")
        entry: Dict[str, Any] = {"ref": f"E{i}", "tag": tag}
        if e.get("role"):
            entry["role"] = e["role"]
        text_limit = 60 if tag in CONTAINER_TAGS else 90
        if e.get("text"):
            entry["text"] = _short(e["text"], text_limit)
        elif e.get("accessible_name"):
            entry["accessible_name"] = _short(e["accessible_name"], 60)
        for k in ("type", "placeholder"):
            if e.get(k):
                entry[k] = _short(e[k], 40)
        if tag == "a":
            entry["href"] = _href_kind(e.get("href"), page_url)
        if tag == "img":
            entry["alt"] = "missing" if not e.get("alt") else _short(e["alt"], 40)
        entry["visible"] = bool(e.get("visible"))
        box = e.get("bounding_box")
        if box:
            entry["box"] = [box.get("x"), box.get("y"), box.get("width"), box.get("height")]
        st = styles.get(e.get("selector")) or {}
        if st and e.get("visible") and (tag in INTERACTIVE_TAGS or tag in ("h1", "h2", "h3", "h4", "h5", "h6")):
            entry["style"] = {"font_size": st.get("font_size"), "font_weight": st.get("font_weight"),
                              "color": st.get("color"), "background": st.get("background_color")}
        # nearest identified ancestor that is also in the packet (grouping context, without the id itself)
        for anc_id in (e.get("id_chain") or [])[1:]:
            if anc_id in ref_by_id:
                entry["in"] = ref_by_id[anc_id]
                break
        targeted_dom.append(entry)

    # 2. Layout / responsive summary (measurements only)
    visible_interactive = [(ref_by_selector.get(e.get("selector")), e) for e in selected
                           if e.get("tag") in INTERACTIVE_TAGS and e.get("visible") and e.get("bounding_box")]
    overlaps = []
    for i in range(len(visible_interactive)):
        for j in range(i + 1, len(visible_interactive)):
            (ra, a), (rb, b) = visible_interactive[i], visible_interactive[j]
            if ra and rb and _boxes_overlap(a["bounding_box"], b["bounding_box"]):
                overlaps.append([ra, rb])
    layout = {
        "viewport_width": getattr(telemetry, "viewport", {}).get("width"),
        "document_scroll_width": dom_summary.get("doc_scroll_width"),
        "horizontal_overflow": bool(dom_summary.get("has_horizontal_overflow")),
        "elements_beyond_viewport": [ref_by_selector[e["selector"]] for e in selected
                                     if e.get("overflows_viewport") and e.get("selector") in ref_by_selector][:MAX_LAYOUT_ITEMS],
        "elements_with_overflowing_content": [ref_by_selector[e["selector"]] for e in selected
                                              if e.get("contains_overflow") and e.get("selector") in ref_by_selector][:MAX_LAYOUT_ITEMS],
        "clipped_elements": [ref_by_selector[e["selector"]] for e in selected
                             if e.get("clipped") and e.get("selector") in ref_by_selector][:MAX_LAYOUT_ITEMS],
        "overlapping_interactive_elements": overlaps[:MAX_LAYOUT_ITEMS],
    }

    # 3. Interaction evidence (executed/failed actions only; blocked ones are just counted)
    interactions = []
    blocked = 0
    for entry in interaction_log or []:
        if entry.get("status") == "blocked":
            blocked += 1
            continue
        ref = ref_by_selector.get(entry.get("target")) or ref_by_selector.get(entry.get("element_selector"))
        item = {"target": ref or "unlisted element", "action": entry.get("action"), "status": entry.get("status")}
        # Name the control. A record that says only "E5" forces the model to cross-reference the DOM
        # section to learn what was pressed, and a model that does not bother reports nothing.
        known = ref_map.get(ref) if ref else None
        if known and known.get("text"):
            item["label"] = known["text"]
        for k in ("dom_changed", "url_changed", "visible_change"):
            if k in entry:
                item[k] = entry[k]
        errors = entry.get("errors_after_action") or []
        if errors:
            item["errors_after_action"] = [_short(t, 140) for t in errors[:2]]
        # State the outcome in words. "dom_changed: false" is the evidence of a dead control, but as a
        # bare flag it reads as unremarkable - every record carried it, including the working ones, so a
        # broken button and a working one looked identical. Measured on the Test Lab benchmark: four of
        # the six seeded defects in the navigation suite were missed with the diagnosis "AI produced no
        # candidate", on controls whose failure was sitting in this list unlabelled.
        if entry.get("status") == "executed":
            if errors:
                item["outcome"] = "raised an error in the page"
            elif not any(entry.get(k) for k in ("dom_changed", "url_changed", "visible_change")):
                item["outcome"] = "no visible effect: the page did not change in any way"
            else:
                item["outcome"] = "the page responded"
        if entry.get("hypothesis"):
            item["was_testing"] = _short(entry["hypothesis"], 160)
        interactions.append(item)
    interactions = interactions[:MAX_INTERACTIONS]
    if blocked:
        interactions.append({"note": f"{blocked} action(s) blocked by the safety policy (destructive/sensitive controls)"})

    # 4. Deterministic findings, summarized (no raw logs)
    a11y = []
    for v in accessibility_violations[:MAX_A11Y_SUMMARIES]:
        refs = []
        for t in v.target or []:
            ref = ref_by_selector.get(t) or (ref_by_id.get(t[1:]) if t.startswith("#") else None)
            if ref:
                refs.append(ref)
        a11y.append({"rule": v.rule, "impact": v.impact, "nodes": len(v.target or []), "refs": refs[:3]})

    runtime = []
    seen = set()
    for evt in getattr(telemetry, "classified_events", None) or []:
        category = evt.category.value if hasattr(evt.category, "value") else str(evt.category)
        if category not in ("APPLICATION_ERROR", "API_ERROR") or evt.ownership != "TARGET_APPLICATION":
            continue  # third-party, telemetry, browser warnings: not relevant to UI/UX interpretation
        if evt.source == "network":
            detail = f"HTTP {evt.event_type} {urlparse(evt.url or '').path or evt.detail}"
        else:
            detail = _short(evt.detail, 150)
        key = (evt.source, detail)
        if key in seen:
            continue
        seen.add(key)
        runtime.append({"source": evt.source, "type": evt.event_type, "message": detail})
    runtime = runtime[:MAX_RUNTIME_EVENTS]

    # 5. Page context
    headings = dom_summary.get("headings") or []
    n_interactive = sum(1 for e in selected if e.get("tag") in INTERACTIVE_TAGS)
    vp = getattr(telemetry, "viewport", {}) or {}
    page = {
        "url": page_url,
        "title": getattr(telemetry, "title", ""),
        "viewport": f"{vp.get('width')}x{vp.get('height')}",
        "main_heading": _short(headings[0].get("text"), 90) if headings else None,
        "summary": f"{n_interactive} interactive elements, {len(dom_summary.get('forms') or [])} form(s), "
                   f"{len(dom_summary.get('nav_elements') or [])} navigation region(s)",
    }

    return EvidencePacket(
        page=page,
        targeted_dom=targeted_dom,
        layout=layout,
        interactions=interactions,
        deterministic_findings={"accessibility": a11y, "runtime": runtime},
        max_findings=choose_max_findings(n_interactive, max_findings_cap),
        screenshot_base64=screenshot_base64,
        screenshot_mime=screenshot_mime,
        screenshot_in_browser=screenshot_in_browser,
        ref_map=ref_map,
    )


def packet_json(packet: EvidencePacket) -> str:
    return json.dumps(packet.to_ai_payload(), ensure_ascii=False)
