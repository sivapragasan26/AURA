import re
from typing import Dict, Any, List, Tuple, Optional
from aura.models.findings import CandidateFinding, AccessibilityViolation, RuntimeTelemetry
from aura.agent.analyzer_agent import normalize_rule_type

# Interaction-behavior claims: verified only by an interaction on the claimed target (or inside it)
INTERACTION_RULES = {
    "interaction_failure", "non_responsive_control", "click_without_feedback", "dead_button", "broken_menu",
    "broken_toggle", "broken_modal", "broken_form_submission", "failed_form_interaction",
    "validation_feedback_failure", "incorrect_state_transition", "interaction_dead_end", "false_affordance",
}

VISUAL_QUALIFIERS = {
    "OVERLAP": ("overlap", "covered", "covers", "behind", "on top of", "stacked"),
    "NOT_DISCOVERABLE": ("discoverab", "hard to find", "easy to miss", "lost among", "buried"),
    "DE_EMPHASIS": ("prominen", "de-emphasi", "deemphasi", "emphasis", "subtle", "tiny", "too small", "faint",
                    "low contrast", "barely", "nearly invisible", "almost invisible", "hierarchy", "visually hidden",
                    "visually"),
    "VISUAL_OBSCURITY": ("obscur", "hard to see", "difficult to see"),
}
DOM_ABSENCE_PHRASES = ("missing from", "absent from", "not present", "does not exist", "not in the dom", "not rendered", "is absent")
CSS_HIDDEN_PHRASES = ("is hidden", "are hidden", "appears hidden", "appear hidden", "hidden from view", "not visible",
                      "invisible", "display: none", "display:none")

# The screenshot is direct evidence of rendered reality. A claim that the rendered page is cut off,
# clipped or pushed off-screen is checked against the measured geometry of the element it names.
CLIPPING_CLAIM = re.compile(r"\b(clipp?ed|cut ?off|truncat\w*|off[- ]?screen|outside the (viewport|screen|visible area)|"
                            r"beyond the (viewport|screen|fold)|overflow\w*|does not fit)\b", re.I)

# A claim about a viewport AURA did not measure cannot be contradicted by the one it did. "Clipped under
# narrow viewports" says nothing about the desktop screenshot in front of us.
OTHER_VIEWPORT_CLAIM = re.compile(r"\b(mobile|phone|tablet|narrow|small(er)? (screen|viewport|device)|"
                                  r"under .{0,20}viewport|responsive breakpoint|at \d+ ?px)\b", re.I)

# Element kinds a visibility claim can be about directly. When the claim names a control but the matched
# target is a container, the container being on screen says nothing about the control inside it.
SUBJECT_TAGS = {"button", "a", "input", "select", "textarea", "img", "svg", "label", "h1", "h2", "h3"}
CONTROL_NOUN = re.compile(r"\b(button|link|field|input|menu|icon|checkbox|dropdown|image|logo|label|tab|"
                          r"control|action|cta)\b", re.I)

VISUAL_CONTRADICTION_REASON = "Visual evidence contradicts the AI observation."

# "The button is missing" is a claim about rendered reality and the screenshot can refute it.
# "The button is missing a label" is a claim about a property of an element that is plainly there, and the
# screenshot says nothing about it. The negative lookahead keeps the two apart.
_PROPERTY_NOUNS = (r"alt|alternative|label|labelling|labeling|name|naming|title|description|descriptions|text|"
                   r"attribute|attributes|placeholder|caption|heading|headings|contrast|value|values|role|"
                   r"landmark|landmarks|lang|language|feedback|confirmation|indicator|state|focus|outline|"
                   r"instruction|instructions|context|information")
ELEMENT_ABSENCE_CLAIM = re.compile(
    r"\b(?:not\s+visible|cannot\s+be\s+seen|can'?t\s+be\s+seen|hardly\s+visible|missing|not\s+found|absent|"
    r"not\s+present|not\s+rendered|invisible|hidden|no\s+longer\s+(?:visible|present))\b",
    re.I,
)

# "Missing form input label" and "links lack accessible names" are claims about a PROPERTY of an element
# that is plainly on the page. The property can sit a couple of words after the absence word, so a simple
# lookahead is not enough: the whole clause is checked and, when it names a property, the blunt
# element-absence rule stands down and leaves the claim to the detector that can actually measure it.
PROPERTY_ABSENCE_CLAIM = re.compile(
    rf"\b(?:missing|lacks?|lacking|without|absent|no|has\s+no|does\s+not\s+have)\b"
    rf"(?:\s+\S+){{0,3}}\s*\b(?:{_PROPERTY_NOUNS})\b",
    re.I,
)


def element_absence_claimed(text: str) -> bool:
    """True when the claim says the ELEMENT itself is not there, rather than one of its properties."""
    if PROPERTY_ABSENCE_CLAIM.search(text or ""):
        return False
    return bool(ELEMENT_ABSENCE_CLAIM.search(text or ""))


def _rendered_visible(el: Dict[str, Any], viewport: Optional[Dict[str, Any]] = None) -> bool:
    """True when the collected geometry shows this element actually rendered with a usable box."""
    if not el.get("visible", True):
        return False
    box = el.get("bounding_box") or {}
    w, h = float(box.get("width") or 0), float(box.get("height") or 0)
    x, y = float(box.get("x") or 0), float(box.get("y") or 0)
    return w > 5 and h > 5 and (x + w) > 0 and (y + h) > 0


def classify_visibility_claim(text: str) -> str:
    """
    Classifies what a visibility-related claim actually asserts, so it can be checked against measurements
    instead of rejected on keywords: DOM_ABSENCE, CSS_HIDDEN, OVERLAP, NOT_DISCOVERABLE, DE_EMPHASIS,
    VISUAL_OBSCURITY or NONE. Visual qualifiers win: "visually hidden behind secondary links" is about
    prominence/overlap, not about the element being absent or display:none.
    """
    t = (text or "").lower()
    for kind in ("OVERLAP", "NOT_DISCOVERABLE", "VISUAL_OBSCURITY", "DE_EMPHASIS"):
        if any(q in t for q in VISUAL_QUALIFIERS[kind]):
            return kind
    if any(p in t for p in DOM_ABSENCE_PHRASES):
        return "DOM_ABSENCE"
    if any(p in t for p in CSS_HIDDEN_PHRASES):
        return "CSS_HIDDEN"
    return "NONE"


def check_visual_contradiction(
    candidate: CandidateFinding,
    matching_elements: List[Dict[str, Any]],
    all_dom_elements: List[Dict[str, Any]],
    target_match_method: Optional[str] = None
) -> Optional[str]:
    """
    Checks if an AI candidate finding's visual observation of absence or invisibility
    is contradicted by actual rendered browser evidence (e.g. 'Add to cart is not visible'
    when 'Add to cart' is rendered and visible in the viewport).
    """
    claim_text = f"{candidate.title} {candidate.description or ''} {candidate.observation or ''}".lower()

    # 1. Direct contradiction on matched target element
    if matching_elements:
        first = matching_elements[0]
        box = first.get("bounding_box") or {}
        w = float(box.get("width") or 0)
        h = float(box.get("height") or 0)
        x = float(box.get("x") or 0)
        y = float(box.get("y") or 0)
        is_visible_on_screen = first.get("visible", True) and w > 5 and h > 5 and (x + w) > 0 and (y + h) > 0

        kind = classify_visibility_claim(claim_text)
        # A visual qualifier wins: "visually hidden behind the delete button" is a claim about overlap or
        # emphasis, not about the element being absent, and the screenshot cannot refute it by itself.
        visual_qualifier = kind in ("OVERLAP", "NOT_DISCOVERABLE", "DE_EMPHASIS", "VISUAL_OBSCURITY")
        has_absence_phrase = not visual_qualifier and element_absence_claimed(claim_text)
        # The matched element must plausibly BE what the claim is about. "Container clips its content and
        # the button is hidden" matched to the container is not refuted by the container being on screen:
        # the claim is about the button inside it, which the subject search below handles properly.
        target_is_subject = (first.get("tag") or "").lower() in SUBJECT_TAGS
        claim_names_a_control = bool(CONTROL_NOUN.search(claim_text))
        subject_matches_target = target_is_subject or not claim_names_a_control

        if is_visible_on_screen and subject_matches_target and (
                kind in ("DOM_ABSENCE", "CSS_HIDDEN") or has_absence_phrase):
            return VISUAL_CONTRADICTION_REASON

        # Clipping / off-screen claims: the measured box settles them, but only for the viewport that was
        # measured. A claim about a narrower screen is outside what this screenshot can show.
        if (CLIPPING_CLAIM.search(claim_text) and is_visible_on_screen and subject_matches_target
                and not OTHER_VIEWPORT_CLAIM.search(claim_text)):
            measured_clip = bool(first.get("clipped") or first.get("overflows_viewport")
                                 or first.get("contains_overflow") or first.get("is_offscreen"))
            # Every geometry fact must be present and negative. One key happening to be False is not
            # evidence that the rendered page contradicts the claim.
            geometry_complete = all(k in first for k in ("clipped", "overflows_viewport", "contains_overflow"))
            if geometry_complete and not measured_clip:
                return VISUAL_CONTRADICTION_REASON

    # 2. Candidate claims absence of a named action or control across the page/section
    # Examples: 'Primary purchase actions (add to cart) are not visible', 'Search is missing', 'Login button not found'
    is_invisibility_claim = (classify_visibility_claim(claim_text) not in
                             ("OVERLAP", "NOT_DISCOVERABLE", "DE_EMPHASIS", "VISUAL_OBSCURITY")
                             and element_absence_claimed(claim_text))
    if is_invisibility_claim and all_dom_elements:
        subjects = set()
        # Look in parentheses / quotes: e.g. (add to cart), "add to cart", 'buy now'
        for m in re.findall(r'["\']([^"\']+)["\']|\(([^)]+)\)', claim_text):
            cleaned = (m[0] or m[1] or "").strip().lower()
            if len(cleaned) >= 3 and not any(w in cleaned for w in ("css", "html", "dom", "selector", "rule", "wcag")):
                subjects.add(cleaned)

        # Look for standard high-intent action keywords in claim text
        KEY_ACTIONS = [
            "add to cart", "buy now", "purchase", "checkout", "search", "sign in", "login",
            "shopping cart", "navigation", "main menu", "cart", "submit"
        ]
        for act in KEY_ACTIONS:
            if act in claim_text:
                subjects.add(act)

        # Also check target text if specified
        target_text = ""
        if isinstance(candidate.affected_element, dict):
            target_text = (candidate.affected_element.get("text") or "").strip().lower()
        elif hasattr(candidate.affected_element, "text"):
            target_text = (getattr(candidate.affected_element, "text", "") or "").strip().lower()
        # The target's own text, but only when it reads like a name. A container's concatenated text is
        # not the subject of the claim, and searching for it always finds the container again.
        if target_text and 3 <= len(target_text) <= 40:
            subjects.add(target_text)

        for subj in subjects:
            for el in all_dom_elements:
                if not el.get("visible", True):
                    continue
                box = el.get("bounding_box") or {}
                w = float(box.get("width") or 0)
                h = float(box.get("height") or 0)
                x = float(box.get("x") or 0)
                y = float(box.get("y") or 0)
                if w <= 5 or h <= 5 or (x + w) <= 0 or (y + h) <= 0:
                    continue

                el_text = (el.get("text") or "").lower()
                el_acc = (el.get("accessible_name") or "").lower()
                el_aria = (el.get("aria_label") or "").lower()
                el_placeholder = (el.get("placeholder") or "").lower()
                el_id = (el.get("id") or "").lower()

                if (subj in el_text or subj in el_acc or subj in el_aria or subj in el_placeholder or (len(subj) > 5 and subj in el_id)):
                    return VISUAL_CONTRADICTION_REASON

    return None


def _candidate_ids(selector: str) -> List[str]:
    return [m.lower() for m in re.findall(r"#([A-Za-z0-9_\-]+)", selector or "")]


def target_interactions(target_selector: str, interaction_log: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Executed interactions on the claimed target itself or on a control inside it."""
    if not interaction_log or not target_selector:
        return []
    sel = target_selector.strip().lower()
    ids = _candidate_ids(sel)
    # the last id in the selector is the most specific container the claim points at
    anchor = ids[-1] if ids else None
    hits = []
    for e in interaction_log:
        if e.get("status") != "executed":
            continue
        e_sel = (e.get("element_selector") or e.get("target") or "").strip().lower()
        chain = [str(i).lower() for i in (e.get("element_id_chain") or [])]
        if e_sel == sel or (anchor and anchor in chain and (sel == f"#{anchor}" or e_sel.startswith(sel))):
            hits.append(e)
    return hits


class EvidenceMatcher:
    """Matches Candidate Finding details against physical browser evidence with multi-tier target resolution."""

    def evaluate_evidence(
        self,
        candidate: CandidateFinding,
        all_dom_elements: List[Dict[str, Any]],
        accessibility_violations: List[AccessibilityViolation],
        telemetry: RuntimeTelemetry,
        interaction_log: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Dict[str, bool], List[str], List[str], List[Dict[str, Any]], Optional[str], Optional[str]]:
        """
        Returns:
          - flags: Dict[str, bool] (screenshot, dom, accessibility, runtime, interaction)
          - sources: List[str] (human readable source descriptions)
          - evidence_ids: List[str] (e.g. ['DOM-001', 'AXE-004'])
          - matching_elements: List[Dict[str, Any]]
          - contradiction_reason: Optional[str]
          - target_match_method: Optional[str]
        """
        has_screenshot = bool(
            (telemetry and getattr(telemetry, "screenshot_path", None)) or
            (telemetry is None and candidate.evidence and getattr(candidate.evidence, "type", None) == "visual")
        )
        flags = {"screenshot": has_screenshot, "dom": False, "accessibility": False, "runtime": False, "interaction": False}
        sources: List[str] = ["Screenshot visual observation captured"] if has_screenshot else []
        evidence_ids: List[str] = ["EV-SCREEN-001", "SCREENSHOT-001"] if has_screenshot else []
        matching_elements: List[Dict[str, Any]] = []
        contradiction_reason: Optional[str] = None
        target_match_method: Optional[str] = None

        cand_rule = (getattr(candidate, "normalized_rule", None) or 
                     normalize_rule_type(candidate.rule_type or candidate.title))
        cat_upper = candidate.category.upper()

        # Extract target information
        target_selector = ""
        target_tag = ""
        target_text = ""
        target_id = ""

        if isinstance(candidate.affected_element, dict):
            target_selector = (candidate.affected_element.get("selector") or "").lower().strip()
            target_tag = (candidate.affected_element.get("tag") or "").lower().strip()
            target_text = (candidate.affected_element.get("text") or "").lower().strip()
            target_id = (candidate.affected_element.get("id") or "").lower().strip()
        elif hasattr(candidate.affected_element, "selector"):
            target_selector = (getattr(candidate.affected_element, "selector", "") or "").lower().strip()
            target_tag = (getattr(candidate.affected_element, "tag", "") or "").lower().strip()
            target_text = (getattr(candidate.affected_element, "text", "") or "").lower().strip()
        elif isinstance(candidate.affected_element, str):
            target_selector = candidate.affected_element.lower().strip()

        # Multi-Tier Semantic Target Matching
        if all_dom_elements:
            for elem in all_dom_elements:
                elem_tag = (elem.get("tag") or "").lower().strip()
                elem_id = (elem.get("id") or "").lower().strip()
                elem_class = (elem.get("class") or elem.get("class_name") or "").lower().strip()
                elem_text = (elem.get("text") or "").lower().strip()
                elem_acc = (elem.get("accessible_name") or "").lower().strip()
                elem_testid = (elem.get("data-testid") or elem.get("data_testid") or "").lower().strip()
                elem_role = (elem.get("role") or "").lower().strip()

                method = None

                # Tier 0: unique selector (targets mapped from evidence-packet refs)
                if target_selector and (elem.get("selector") or "").lower() == target_selector:
                    method = "unique_selector"

                # Tier 1: Exact selector
                if not method and target_selector and ("#" in target_selector or "." in target_selector or target_selector == elem_tag):
                    if "#" in target_selector:
                        parts = target_selector.split("#", 1)
                        if (not parts[0] or elem_tag == parts[0]) and elem_id == parts[1]:
                            method = "exact_selector"
                    elif "." in target_selector:
                        parts = target_selector.split(".", 1)
                        if (not parts[0] or elem_tag == parts[0]) and (parts[1] in elem_class.split()):
                            method = "exact_selector"
                    elif target_selector == elem_tag and target_selector not in ("div", "span", "body"):
                        method = "exact_selector"

                # Tier 2: Element ID
                if not method and (target_id or target_selector.replace("#", "")) and elem_id:
                    check_id = target_id or target_selector.replace("#", "")
                    if check_id == elem_id:
                        method = "element_id"

                # Tier 3: data-testid
                if not method and elem_testid and (target_selector and elem_testid in target_selector):
                    method = "data_testid"

                # Tier 4: Exact text + tag
                if not method and target_text and target_tag and elem_tag == target_tag and target_text == elem_text:
                    method = "visible_text_tag"

                # Tier 5: Normalized text + role
                if not method and target_text and (target_text in elem_text or target_text in elem_acc):
                    method = "visible_text_role"

                # Tier 6: Tag match for key interactive/semantic elements
                if not method and cand_rule == "image_alt" and elem_tag == "img":
                    method = "semantic_dom_match"
                elif not method and cand_rule in ("weak_cta", "dead_button", "false_affordance") and elem_tag in ("button", "a", "div", "span"):
                    method = "semantic_dom_match"
                elif not method and cand_rule in ("confusing_form", "unusable_mobile_form") and elem_tag in ("form", "input", "select", "button"):
                    method = "semantic_dom_match"

                if method:
                    # Target accuracy: never match control-level issues to broad containers
                    claim_text_lower = f"{candidate.title} {candidate.description or ''}".lower()
                    is_control_claim = bool(re.search(r"\b(search|button|link|nav|navigation|input|cta|menu|icon|select|dropdown|field)\b", claim_text_lower))
                    is_broad_container = (elem_tag in ("header", "main", "body", "html", "section") or 
                                          elem_id in ("main", "root", "app", "content") or 
                                          elem.get("selector") in ("body", "html", "#main", "#root", "#app"))
                    if is_control_claim and is_broad_container:
                        child_control = None
                        for cand_child in all_dom_elements:
                            c_tag = (cand_child.get("tag") or "").lower()
                            c_text = (cand_child.get("text") or "").lower()
                            c_acc = (cand_child.get("accessible_name") or "").lower()
                            if c_tag in ("input", "button", "a", "select") or cand_child.get("role") in ("button", "link", "searchbox"):
                                if target_text and (target_text in c_text or target_text in c_acc):
                                    child_control = cand_child
                                    break
                        if child_control:
                            elem = child_control
                            method = "child_control_isolated"
                        else:
                            method = "area_level"
                            elem = {
                                **elem,
                                "kind": "area",
                                "label": f"{elem_tag.capitalize()} navigation area" if elem_tag in ("header", "nav") else f"{elem_tag.capitalize()} area",
                                "note": "No single element could be confidently isolated."
                            }
                    matching_elements.append(elem)
                    target_match_method = method
                    break

        if matching_elements:
            flags["dom"] = True
            first_match = matching_elements[0]
            dom_id_val = f"EV-DOM-{len(evidence_ids):03d}"
            evidence_ids.extend([dom_id_val, f"DOM-{len(evidence_ids) + 1:03d}"])
            sources.append(f"DOM match found: <{first_match.get('tag')}> id='{first_match.get('id')}' text='{first_match.get('text', '')[:30]}'")

        # ---------------------------------------------------------------------
        # Universal screenshot-contradiction rule.
        # Applies to EVERY AI claim about visual state, whatever category the model assigned it to. The
        # rendered page (screenshot + measured geometry) is direct evidence of reality: when it shows the
        # opposite of what the model claimed, the candidate is rejected here, not merely downgraded.
        # ---------------------------------------------------------------------
        contradiction_reason = check_visual_contradiction(
            candidate=candidate,
            matching_elements=matching_elements,
            all_dom_elements=all_dom_elements,
            target_match_method=target_match_method,
        )
        if contradiction_reason:
            sources.append("Rendered page evidence (screenshot and measured geometry) contradicts this claim.")

        # ---------------------------------------------------------------------
        # Rule-Specific Verification & Contradiction Evaluation
        # ---------------------------------------------------------------------

        # 1. ACCESSIBILITY & image_alt
        if cand_rule == "image_alt" or ("image" in candidate.title.lower() and "alt" in candidate.title.lower()):
            axe_match = False
            for viol in accessibility_violations:
                if viol.rule == "image-alt" or "alt" in viol.rule:
                    axe_match = True
                    flags["accessibility"] = True
                    evidence_ids.extend(["EV-AXE-001", "AXE-001"])
                    sources.append(f"axe-core WCAG violation match: [image-alt] on {viol.target}")

            if matching_elements:
                img_elem = matching_elements[0]
                alt_val = img_elem.get("alt")
                if alt_val is None or str(alt_val).strip() == "":
                    flags["dom"] = True
                    sources.append("DOM element <img> missing valid non-empty 'alt' attribute.")
                elif not contradiction_reason:
                    contradiction_reason = f"Image element <img id='{img_elem.get('id')}'> has valid non-empty alt attribute: '{alt_val}'"
            elif axe_match:
                flags["dom"] = True
            else:
                sources.append("No missing alt attribute found in DOM or axe-core.")

        # 2. RESPONSIVENESS & layout overflow / breaks
        elif cand_rule in ("horizontal_overflow", "mobile_layout_break", "clipped_content", "overlapping_elements") or cat_upper == "RESPONSIVENESS":
            dom_sum = getattr(telemetry, "dom_summary", {})
            has_overflow = dom_sum.get("has_horizontal_overflow", False)
            scroll_w = dom_sum.get("doc_scroll_width", 0)
            view_w = dom_sum.get("doc_viewport_width", telemetry.viewport.get("width", 1440))

            doc_overflow = bool(has_overflow or (scroll_w > view_w + 5))
            target = matching_elements[0] if matching_elements else {}
            flags["document_overflow"] = doc_overflow
            page_level = target_selector in ("", "body", "html", "window", "document", "page")
            # a page-level claim is measured by the document itself
            flags["target_overflow"] = bool(target.get("overflows_viewport") or target.get("contains_overflow")
                                            or (page_level and doc_overflow))
            flags["target_clipped"] = bool(target.get("clipped"))
            if flags["target_overflow"] or flags["target_clipped"]:
                flags["dom"] = True
                evidence_ids.extend(["EV-RESPONSIVE-001", "DOM-OVERFLOW"])
                sources.append(f"Measured on target <{target.get('tag')}>: extends beyond viewport={target.get('overflows_viewport')}, "
                               f"content overflow={target.get('contains_overflow')}, clipped={target.get('clipped')}.")
            elif doc_overflow:
                flags["dom"] = bool(matching_elements)
                evidence_ids.extend(["EV-RESPONSIVE-001", "DOM-OVERFLOW"])
                sources.append(f"Document scrollWidth ({scroll_w}px) exceeds viewport ({view_w}px); overflow not attributed to the claimed target.")
            elif not matching_elements and not contradiction_reason:
                contradiction_reason = f"Document scrollWidth ({scroll_w}px) does not exceed viewport ({view_w}px) and no element found."

        # 3. NAVIGATION / INTERACTION & broken_navigation / dead_button / false_affordance
        elif cand_rule in INTERACTION_RULES or cand_rule in ("broken_navigation", "bad_navigation", "false_affordance", "misleading_cta") or cat_upper in ("NAVIGATION", "INTERACTION"):
            if matching_elements:
                flags["dom"] = True
                target_elem = matching_elements[0]
                href_val = (target_elem.get("href") or "").strip().lower()
                placeholder = href_val in ("", "#", "javascript:void(0)", "javascript:;") and target_elem.get("tag") == "a"
                if not placeholder and target_elem.get("id"):
                    # container target (e.g. a nav): placeholder links inside it
                    tid = target_elem["id"].lower()
                    placeholder = any(
                        e.get("tag") == "a" and tid in [str(i).lower() for i in (e.get("id_chain") or [])]
                        and ((e.get("href") or "").strip().lower() in ("", "#") or (e.get("href") or "").strip().lower().startswith("javascript:"))
                        for e in all_dom_elements)
                if placeholder:
                    flags["placeholder_href"] = True
                    evidence_ids.extend(["EV-DOM-NAV-PLACEHOLDER", "DOM-NAV-PLACEHOLDER"])
                    sources.append("Link target href is a non-functional placeholder (empty, '#' or javascript:).")
                if cls_overlap_needed(candidate):
                    flags["layout_overlap"] = _has_overlap(target_elem, all_dom_elements)

            hits = target_interactions(target_selector, interaction_log)
            if hits:
                flags["interaction"] = True
                flags["interaction_error"] = any(h.get("errors_after_action") for h in hits)
                flags["interaction_no_effect"] = any(not h.get("dom_changed") and not h.get("url_changed") and not h.get("errors_after_action") for h in hits)
                flags["interaction_visible_effect"] = any(h.get("dom_changed") or h.get("url_changed") for h in hits)
                evidence_ids.extend(["EV-INTERACTION-001", "INTERACTION-001"])
                for h in hits[:2]:
                    sources.append(f"Target interaction: {h.get('action')} on {h.get('element_selector')} -> "
                                   f"errors={h.get('errors_after_action') or []}, visible change={h.get('dom_changed')}, "
                                   f"navigated={h.get('url_changed')}")
            elif cand_rule in INTERACTION_RULES or cat_upper == "INTERACTION":
                sources.append("Claimed target was not exercised by any controlled interaction.")

        # 4. RUNTIME & console / network failures
        elif cand_rule in ("runtime_api_failure", "console_error", "application_console_error", "application_runtime_exception", "application_network_failure", "insufficient_feedback", "poor_error_recovery") or cat_upper == "RUNTIME":
            app_failures = [n for n in telemetry.network_failures if n.status >= 400]
            app_console = [c for c in telemetry.console_errors if c.type.lower() in ("error", "exception", "warning")]
            if app_failures or app_console or getattr(telemetry, "classified_events", []):
                flags["runtime"] = True
                evidence_ids.extend(["EV-RUNTIME-001", "RUNTIME-001"])
                sources.append(f"Live telemetry recorded {len(app_failures)} network 4xx/5xx failures and {len(app_console)} console/runtime errors.")
            else:
                if cand_rule not in ("insufficient_feedback", "poor_error_recovery") and not contradiction_reason:
                    contradiction_reason = "No target-owned console errors or HTTP network failures recorded in runtime telemetry."

        # 5. Visibility claims: judged on measurements, never on keywords alone
        else:
            claim_text = f"{candidate.title} {candidate.description or ''} {candidate.observation or ''}"
            kind = classify_visibility_claim(claim_text)
            # The screenshot contradiction check already ran universally above.
            if kind != "NONE":
                sources.append(f"Visibility claim type: {kind} (checked against measurements, not keywords)")
            if not contradiction_reason:
                strong_match = target_match_method in ("unique_selector", "exact_selector", "element_id")
                if matching_elements and strong_match:
                    first_match = matching_elements[0]
                    box = first_match.get("bounding_box") or {}
                    on_screen = bool(box) and box.get("width", 0) > 0 and box.get("height", 0) > 0 and box.get("x", 0) + box.get("width", 0) > 0
                    if (kind in ("DOM_ABSENCE", "CSS_HIDDEN")) and first_match.get("visible", True) and on_screen:
                        contradiction_reason = VISUAL_CONTRADICTION_REASON
                    elif kind == "DOM_ABSENCE":
                        contradiction_reason = f"Claimed absent, but element <{first_match.get('tag')}> is present in DOM ({target_match_method})"
            if kind == "OVERLAP" and matching_elements:
                flags["layout_overlap"] = _has_overlap(matching_elements[0], all_dom_elements)
                if flags["layout_overlap"]:
                    sources.append("Measured bounding-box overlap between interactive elements at the claimed target.")

        # Check axe-core correlation for any remaining candidate
        for viol in accessibility_violations:
            rule_clean = viol.rule.lower()
            if rule_clean in candidate.title.lower() or rule_clean in (candidate.description or "").lower():
                flags["accessibility"] = True
                if "AXE-001" not in evidence_ids:
                    evidence_ids.append("AXE-001")
                if "EV-AXE-001" not in evidence_ids:
                    evidence_ids.append("EV-AXE-001")
                sources.append(f"axe-core WCAG violation match: [{viol.rule}]")

        return flags, sources, evidence_ids, matching_elements, contradiction_reason, target_match_method


def _has_overlap(target: Dict[str, Any], elements: List[Dict[str, Any]]) -> bool:
    """True if visible interactive elements at/inside the target overlap each other."""
    tid = (target.get("id") or "").lower()
    def inside(e):
        return e is target or (tid and tid in [str(i).lower() for i in (e.get("id_chain") or [])])
    boxes = [e.get("bounding_box") for e in elements
             if e.get("visible") and e.get("bounding_box") and e.get("tag") in ("a", "button", "input") and inside(e)]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ix = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
            iy = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
            if ix > 1 and iy > 1:
                return True
    return False


def cls_overlap_needed(candidate: CandidateFinding) -> bool:
    return classify_visibility_claim(f"{candidate.title} {candidate.description or ''} {candidate.observation or ''}") == "OVERLAP"
