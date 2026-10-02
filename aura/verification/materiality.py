"""
Materiality gate for AI UI/UX candidates.

The verifier used to accept any UI/UX candidate whose target element simply existed and was visible. That let
weak hypotheses through: "large blank area", "this button is small", "layout looks unusual". An unusual visual
pattern is not a defect. This module answers a narrower question, from measurements only:

    Does the collected browser evidence actually show the condition the candidate claims?

Verdicts:
  SUPPORTED    measurements show the claimed condition           -> CONFIRMED
  JUDGEMENT    target verified, but the claim is a design opinion
               that browser evidence cannot settle               -> LIKELY
  WEAK         nothing in the evidence supports the claim        -> UNCERTAIN
  NOT_A_DEFECT evidence shows the condition is harmless or
               is already reported deterministically             -> REJECTED

Measurements come from the same DOM evidence the engine already collects (bounding boxes, computed styles,
visibility, overflow flags) and from axe-core results. Nothing here consults ground truth.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --- claim families -------------------------------------------------------------------------------
# Visual prominence / hierarchy: verifiable by comparing the target with the controls it competes with.
EMPHASIS_RULES = {"weak_primary_cta", "bad_visual_hierarchy", "competing_cta", "misleading_visual_emphasis",
                  "typography_hierarchy_issue", "inconsistent_component_styling", "inconsistent_state_styling",
                  "unclear_interactive_affordance"}
# Density / grouping: verifiable by counting what is inside the claimed container.
DENSITY_RULES = {"excessive_information_density", "cognitive_load_problem", "poor_grouping",
                 "excessive_horizontal_scanning"}
# Spacing / alignment: verifiable from sibling geometry.
SPACING_RULES = {"poor_spacing_consistency", "poor_alignment", "responsive_spacing_failure"}
# Claims that are design judgements: the target can be verified, the opinion cannot be measured.
JUDGEMENT_RULES = {"confusing_form", "ambiguous_label", "unclear_instruction", "poor_error_recovery",
                   "insufficient_feedback", "misleading_feedback", "poor_task_flow", "discoverability_problem",
                   "dead_end_workflow", "unclear_system_status", "destructive_action_without_clear_warning",
                   "inconsistent_workflow_behavior", "unclear_information_architecture", "unnecessary_user_step",
                   "excessive_form_complexity", "misleading_cta", "unexpected_behavior", "false_affordance"}

# Wording that describes empty space or empty containers. Blank space is a layout technique, not a defect:
# a candidate whose whole case rests on it is classified WHITESPACE_ONLY and rejected unless an independent
# measurement (clipping, overflow, overlap, unreachable content, interaction obstruction) shows real harm.
# The wording must be about SPACE, not merely contain a word that can also describe space. "empty href" is
# a broken link and "javascript:void(0)" is a placeholder destination: both are real defects, and matching
# the bare words "empty" and "void" here rejected them as whitespace.
BLANK_CLAIM = re.compile(
    r"\b("
    r"whitespace|white\s*space|"
    r"(blank|empty|unused|dead|void|open|negative)\s+space|"
    r"(large|wide|big|significant|substantial|excessive)\s*(gap|gaps|empty|blank|void|space|area|region)|"
    r"excessive\s*(whitespace|white\s*space|spacing|padding|margin)|"
    r"(area|container|section|layout|card|page|hero|sidebar|banner|panel|column|region|block|slot|row)\s*"
    r"(is|looks|appears|seems|contains|has)?\s*(empty|blank|unused|unfilled|barren|vacant)|"
    r"(empty|blank|unused|unfilled|barren|vacant)\s*"
    r"(hero|sidebar|card|banner|panel|column|region|container|area|block|slot|row|section|state)|"
    r"(does\s*not\s*contain|contains?\s*no|lacks?)\s*(any\s*)?content|"
    r"unfilled\s*(space|area|container)|"
    r"sparse\s*layout|breathing\s*room|unused\s*pixels"
    r")\b",
    re.I
)
WHITESPACE_ONLY_REASON = ("Blank or empty space alone is not a defect (WHITESPACE_ONLY): no clipping, overflow, "
                          "overlap, unreachable content, layout break or interaction obstruction was measured")
# Wording that claims the page/section merely looks unusual, with no user-facing consequence named.
AESTHETIC_ONLY = re.compile(
    r"\b("
    r"unusual|unconventional|odd|strange|inconsistent look|aesthetic|not modern|outdated|"
    r"differing\s*(button|card|icon|size|style|styling|treatment|spacing|dimension)|"
    r"different\s*(button|card|icon|size|style|styling|treatment|dimension)|"
    r"inconsistent\s*(visual\s*)?(styling|component|card|icon|button|size|style|spacing|treatment|appearance|design)|"
    r"variation\s*in\s*(style|size|spacing|treatment|dimension)|"
    r"discrepancy\s*in\s*(size|style|styling|spacing)"
    r")\b",
    re.I
)
# Consequences that make an otherwise cosmetic observation material, when the evidence shows them.
HARM_WORDS = re.compile(r"\b(overlap\w*|obstruct\w*|covers?|covering|hide[sn]?|hidden|cut off|clipped|unreachable|inaccessible|"
                        r"cannot (be )?(see|read|click|reach)|unusable|broken|fails?|error)\b", re.I)

PAGE_LEVEL_CONTAINER_TAGS = {"main", "body", "html"}
PAGE_LEVEL_CONTAINER_SELECTORS = {"main", "#main", "body", "html", "#root", "#app", "#__next", "div#main", "div#root", "div#__next"}
PAGE_LEVEL_CONTAINER_IDS = {"main", "root", "app", "__next", "content", "main-content", "page", "app-root"}
SKIP_LINK_PATTERN = re.compile(r"\b(skip to|skip navigation|screen reader|accessibility help)\b", re.I)


def _is_page_level_container(el: Optional[Dict[str, Any]]) -> bool:
    if not el or not isinstance(el, dict):
        return False
    tag = (el.get("tag") or "").lower().strip()
    sel = (el.get("selector") or "").lower().strip()
    eid = (el.get("id") or "").lower().strip()
    if tag in PAGE_LEVEL_CONTAINER_TAGS:
        return True
    if sel in PAGE_LEVEL_CONTAINER_SELECTORS or sel.startswith("body ") or sel.startswith("html "):
        return True
    if eid in PAGE_LEVEL_CONTAINER_IDS:
        return True
    return False


def _is_valid_peer_control(el: Dict[str, Any]) -> bool:
    if not _is_interactive(el):
        return False
    if not el.get("visible", True):
        return False
    box = el.get("bounding_box") or {}
    w, h = float(box.get("width") or 0), float(box.get("height") or 0)
    if w <= 1 or h <= 1:
        return False
    label = _label(el)
    if SKIP_LINK_PATTERN.search(label):
        return False
    sel = (el.get("selector") or "").lower()
    if "skip" in sel:
        return False
    return True

# axe-core rules whose topic an AI candidate can accidentally repeat in its own words
AXE_TOPICS = {
    "color-contrast": re.compile(r"\b(contrast|low.contrast|hard to read|readab)\w*\b", re.I),
    "image-alt": re.compile(r"\b(alt text|alternative text|image description)\b", re.I),
    "link-name": re.compile(r"\b(link (name|text|label)|unlabelled link)\b", re.I),
    "button-name": re.compile(r"\b(button (name|label)|unlabelled button)\b", re.I),
    "label": re.compile(r"\b(field label|input label|form label|unlabelled (field|input))\b", re.I),
}

# Thresholds (explicit so a reviewer can argue with them)
PROMINENCE_TIE = 1.25        # within 25% = visually comparable
PROMINENCE_CLEAR = 1.60      # 60% larger = clearly dominant
DENSE_CONTAINER_ITEMS = 12   # interactive/heading items inside one container
SPACING_SPREAD_PX = 16       # difference between largest and smallest sibling gap
MIN_PEERS = 1

# Action semantics read from the control's own label: a destructive action that is visually stronger than the
# primary action is a measurable hierarchy problem, whichever page it appears on.
DESTRUCTIVE_LABEL = re.compile(r"\b(delete|remove|cancel|discard|reset|clear|erase|destroy|log ?out|sign ?out|"
                               r"unsubscribe|deactivate|revoke)\b", re.I)
PRIMARY_LABEL = re.compile(r"\b(submit|save|continue|next|apply|confirm|checkout|pay|send|order|buy|place|"
                           r"sign ?in|log ?in|register|sign ?up|create|add|update|search|book|start|finish|done|"
                           r"proceed|accept|subscribe|download|upload)\b", re.I)


def _label(el: Dict[str, Any]) -> str:
    return " ".join(str(el.get(k) or "") for k in ("text", "accessible_name", "aria_label", "type"))


@dataclass
class Materiality:
    verdict: str
    reason: str
    measurements: Dict[str, Any] = field(default_factory=dict)

    @property
    def note(self) -> str:
        if not self.measurements:
            return self.reason
        shown = ", ".join(f"{k}={v}" for k, v in list(self.measurements.items())[:4])
        return f"{self.reason} (measured: {shown})"


def _px(value: Any) -> float:
    try:
        return float(str(value).replace("px", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _weight(value: Any) -> float:
    text = str(value or "").strip().lower()
    if text in ("bold", "bolder"):
        return 700.0
    if text in ("normal", "lighter", ""):
        return 400.0
    try:
        return float(text)
    except ValueError:
        return 400.0


def _filled(style: Dict[str, Any]) -> bool:
    bg = str(style.get("background_color") or "").replace(" ", "").lower()
    return bool(bg) and bg not in ("transparent", "rgba(0,0,0,0)", "none")


def _is_interactive(el: Dict[str, Any]) -> bool:
    tag = (el.get("tag") or "").lower()
    typ = (el.get("type") or "").lower()
    return (tag in ("button", "a") or (tag == "input" and typ in ("button", "submit", "reset"))
            or (el.get("role") or "").lower() == "button")


def _prominence(el: Dict[str, Any], style: Dict[str, Any]) -> Dict[str, Any]:
    """How strongly an element stands out: its area, type size, weight and whether it is filled."""
    box = el.get("bounding_box") or {}
    area = float(box.get("width") or 0) * float(box.get("height") or 0)
    font = _px(style.get("font_size")) or 14.0
    weight = _weight(style.get("font_weight"))
    filled = _filled(style)
    score = (area ** 0.5) * (font / 14.0) * (1.0 + (weight - 400.0) / 600.0) * (1.35 if filled else 1.0)
    return {"area_px2": round(area), "font_size_px": font, "font_weight": weight, "filled": filled,
            "prominence": round(score, 1)}


def _styles_of(dom_summary: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {r.get("selector"): (r.get("computed_style") or {})
            for r in (dom_summary or {}).get("raw_elements_with_styles") or []}


def _peers(target: Dict[str, Any], elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Visible interactive controls the target competes with: same identified container, else nearby vertically."""
    chain = [str(i).lower() for i in (target.get("id_chain") or [])]
    container = chain[1] if len(chain) > 1 else None
    box = target.get("bounding_box") or {}
    top = float(box.get("y") or 0)
    peers = []
    for el in elements:
        if el is target or not _is_valid_peer_control(el) or not el.get("bounding_box"):
            continue
        if el.get("selector") == target.get("selector"):
            continue
        if _is_page_level_container(el):
            continue
        el_chain = [str(i).lower() for i in (el.get("id_chain") or [])]
        same_container = container is not None and container in el_chain
        near = abs(float((el.get("bounding_box") or {}).get("y") or 0) - top) <= 400
        if same_container or (container is None and near):
            peers.append(el)
    return peers


def _inside(container: Dict[str, Any], elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cid = (container.get("id") or "").lower()
    if not cid:
        return []
    return [e for e in elements if e is not container and e.get("visible")
            and cid in [str(i).lower() for i in (e.get("id_chain") or [])]]


def _claim_text(candidate: Any) -> str:
    return " ".join(str(x or "") for x in (candidate.title, candidate.description, getattr(candidate, "observation", ""),
                                           (candidate.evidence.description if getattr(candidate, "evidence", None) else "")))


def assess(candidate: Any, target: Optional[Dict[str, Any]], dom_summary: Dict[str, Any],
           accessibility_violations: Optional[List[Any]] = None, flags: Optional[Dict[str, bool]] = None) -> Materiality:
    """Decides whether the evidence makes this UI/UX candidate material. Never consults ground truth."""
    flags = flags or {}
    rule = (getattr(candidate, "normalized_rule", None) or getattr(candidate, "rule_type", None) or "").lower()
    text = _claim_text(candidate)
    elements = (dom_summary or {}).get("all_elements") or []
    styles = _styles_of(dom_summary)
    measured_harm = bool(flags.get("layout_overlap") or flags.get("target_overflow") or flags.get("target_clipped")
                         or flags.get("interaction_error") or flags.get("interaction_no_effect")
                         or flags.get("placeholder_href") or flags.get("runtime"))

    # 1. Already reported by a deterministic detector on the same element: not a separate finding
    for viol in accessibility_violations or []:
        pattern = AXE_TOPICS.get(viol.rule)
        if not pattern or not pattern.search(text):
            continue
        targets = [str(t).lower() for t in (viol.target or [])]
        tid = f"#{(target or {}).get('id', '')}".lower()
        sel = str((target or {}).get("selector") or "").lower()
        if any(t in (tid, sel) for t in targets) or (target is None and targets):
            return Materiality("NOT_A_DEFECT", f"Already reported deterministically by axe-core ({viol.rule}) for this element",
                               {"axe_rule": viol.rule})

    # 2. Blank space / empty containers: only material with measured obstruction or hidden content
    if BLANK_CLAIM.search(text) and not measured_harm:
        return Materiality("NOT_A_DEFECT", WHITESPACE_ONLY_REASON,
                           {"quality_class": "WHITESPACE_ONLY", "measured_harm": False})

    # 3. Purely aesthetic observations or visual differences with no named, measured consequence
    if AESTHETIC_ONLY.search(text) and not HARM_WORDS.search(text) and not measured_harm:
        return Materiality("NOT_A_DEFECT",
                           "Visual differences or styling variations alone are not a defect: no user-facing harm or layout disruption was measured",
                           {"measured_harm": False})

    if target is None:
        return Materiality("WEAK", "No page element could be matched to this claim, so nothing could be measured")

    # Target mismatch guard (Spotify issue: navigation/search claim matched to page-level container)
    NAV_OR_HEADER_CLAIM = re.compile(r"\b(nav|navigation|header|navbar|menu|search\s*(bar|box|input|button)?|top\s*bar)\b", re.I)
    if NAV_OR_HEADER_CLAIM.search(text) and _is_page_level_container(target):
        return Materiality("WEAK", "The claim discusses navigation, header, or search controls, but the matched target is a page-level container")

    # 4. Hidden target: distinguish responsive/duplicated content from content that is unintentionally unreachable
    if not target.get("visible", True):
        name = (target.get("text") or target.get("accessible_name") or "").strip().lower()
        twin = next((e for e in elements if e is not target and e.get("visible")
                     and (e.get("text") or e.get("accessible_name") or "").strip().lower() == name and name), None)
        if twin:
            return Materiality("NOT_A_DEFECT",
                               "The element is hidden in this viewport but the same content is available in a visible element "
                               "(responsive or duplicated markup)", {"visible_twin": twin.get("selector")})
        return Materiality("WEAK", "The element is not rendered in this viewport; the evidence does not show that it should be")

    style = styles.get(target.get("selector")) or {}

    # 5. Prominence / hierarchy claims.
    # The claim often points at a section rather than a control. Comparing a container with the buttons inside
    # it is meaningless, so for a container the controls INSIDE it are compared with each other: a destructive
    # action that outweighs the primary action is an inverted hierarchy, and that is measurable.
    if rule in EMPHASIS_RULES:
        if not _is_interactive(target):
            if _is_page_level_container(target):
                return Materiality("JUDGEMENT", "Target is a page-level container; visual prominence cannot be evaluated by comparing unrelated nested controls across the whole page")
            controls = [e for e in _inside(target, elements) if _is_valid_peer_control(e) and e.get("bounding_box")]
            if len(controls) >= 2:
                scored = [(_prominence(c, styles.get(c.get("selector")) or {}), c) for c in controls]
                destructive = [(p, c) for p, c in scored if DESTRUCTIVE_LABEL.search(_label(c))]
                primary = [(p, c) for p, c in scored if PRIMARY_LABEL.search(_label(c)) and not DESTRUCTIVE_LABEL.search(_label(c))]
                if destructive and primary:
                    dp, dc = max(destructive, key=lambda z: z[0]["prominence"])
                    pp, pc = max(primary, key=lambda z: z[0]["prominence"])
                    ratio = round((dp["prominence"] or 1) / (pp["prominence"] or 1), 2)
                    m = {"destructive_control": (dc.get("text") or dc.get("selector"))[:40],
                         "destructive_prominence": dp["prominence"],
                         "primary_control": (pc.get("text") or pc.get("selector"))[:40],
                         "primary_prominence": pp["prominence"], "ratio": ratio}
                    if ratio >= PROMINENCE_TIE:
                        return Materiality("SUPPORTED", "Inside this section a destructive action is visually stronger than the primary action", m)
                    if ratio <= 1 / PROMINENCE_CLEAR:
                        return Materiality("NOT_A_DEFECT", "Inside this section the primary action is clearly the strongest control", m)
                    return Materiality("WEAK", "The controls in this section carry comparable visual weight; no inverted hierarchy was measured", m)
                strongest = max(scored, key=lambda z: z[0]["prominence"])
                weakest = min(scored, key=lambda z: z[0]["prominence"])
                ratio = round((strongest[0]["prominence"] or 1) / (weakest[0]["prominence"] or 1), 2)
                m = {"strongest_control": (strongest[1].get("text") or strongest[1].get("selector"))[:40],
                     "weakest_control": (weakest[1].get("text") or weakest[1].get("selector"))[:40], "ratio": ratio,
                     "controls_compared": len(controls)}
                if rule == "competing_cta":
                    if 1 / PROMINENCE_TIE <= ratio <= PROMINENCE_TIE:
                        return Materiality("SUPPORTED", "Multiple controls in this section compete with identical visual weight", m)
                    return Materiality("NOT_A_DEFECT", "Controls in this section have distinct visual weights and do not compete", m)
                return Materiality("NOT_A_DEFECT", "Controls in this section have distinct visual weights, which is expected visual hierarchy", m)
            return Materiality("JUDGEMENT", "This section holds too few controls to measure a visual hierarchy problem")
        peers = _peers(target, elements)
        if len(peers) < MIN_PEERS:
            return Materiality("WEAK", "No competing control was found near the target, so the claimed emphasis problem could not be measured")
        t = _prominence(target, style)
        ranked = sorted(((_prominence(p, styles.get(p.get("selector")) or {}), p) for p in peers),
                        key=lambda x: -x[0]["prominence"])
        top, top_el = ranked[0]
        ratio = round((top["prominence"] or 1) / (t["prominence"] or 1), 2)
        m = {"target_prominence": t["prominence"], "strongest_peer_prominence": top["prominence"],
             "ratio": ratio, "peer": top_el.get("text") or top_el.get("selector"), "peers_compared": len(peers)}
        if rule in ("weak_primary_cta", "bad_visual_hierarchy"):
            if ratio >= 1.0:
                return Materiality("SUPPORTED", "A competing control is visually stronger than the element this claim calls primary", m)
            if ratio <= 1 / PROMINENCE_CLEAR:
                return Materiality("NOT_A_DEFECT", "The element is already clearly the most prominent control near it", m)
            return Materiality("WEAK", "The target and the controls around it are visually comparable; no hierarchy problem was measured", m)
        if 1 / PROMINENCE_TIE <= ratio <= PROMINENCE_TIE:
            return Materiality("SUPPORTED", "Two controls compete at a comparable visual weight", m)
        return Materiality("WEAK", "The controls differ clearly in visual weight; no competing-emphasis problem was measured", m)

    # 6. Density / grouping claims: a high element count is measurable, but AURA's evidence does not carry the
    # text volume a density judgement really needs, so below the threshold this stays a judgement, not a refusal.
    if rule in DENSITY_RULES:
        items = _inside(target, elements)
        interactive = sum(1 for e in items if _is_interactive(e))
        m = {"elements_in_container": len(items), "interactive_in_container": interactive}
        if len(items) >= DENSE_CONTAINER_ITEMS or interactive >= DENSE_CONTAINER_ITEMS // 2:
            return Materiality("SUPPORTED", "The claimed container holds an unusually high number of elements", m)
        return Materiality("JUDGEMENT", "Element counts alone do not settle this claim; AURA cannot measure how much "
                                        "content a reader has to process", m)

    # 7. Spacing / alignment claims: measure sibling geometry
    if rule in SPACING_RULES:
        siblings = [e for e in _peers(target, elements) if e.get("bounding_box")]
        boxes = sorted([target] + siblings, key=lambda e: float((e.get("bounding_box") or {}).get("y") or 0))
        gaps = []
        for a, b in zip(boxes, boxes[1:]):
            ab, bb = a.get("bounding_box") or {}, b.get("bounding_box") or {}
            gaps.append(round(float(bb.get("y") or 0) - (float(ab.get("y") or 0) + float(ab.get("height") or 0))))
        if len(gaps) < 2:
            return Materiality("JUDGEMENT", "Too few neighbouring elements to measure spacing consistency", {"gaps": gaps})
        spread = max(gaps) - min(gaps)
        m = {"gaps_px": gaps[:6], "spread_px": spread}
        if spread >= SPACING_SPREAD_PX:
            return Materiality("SUPPORTED", "Spacing between neighbouring elements varies measurably", m)
        return Materiality("WEAK", "Spacing between neighbouring elements is consistent", m)

    # 8. Design judgements: the target is verified, the opinion is not measurable
    if rule in JUDGEMENT_RULES:
        return Materiality("JUDGEMENT", "The element was verified on the page, but this claim is a design judgement that "
                                        "browser evidence cannot confirm on its own")

    # 9. Anything else: material only if some measurement backs it
    if measured_harm:
        return Materiality("SUPPORTED", "Browser measurements support the claimed problem on this element")
    return Materiality("JUDGEMENT", "The element was verified on the page, but no measurement supports or contradicts the claim")
