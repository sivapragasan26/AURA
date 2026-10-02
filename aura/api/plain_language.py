"""
Plain-language wording for findings.

The engine speaks in rule ids ("link-name", "bad_visual_hierarchy") and detector terms. Those stay in the
finding's technical details; the panel leads with a sentence a person can act on. Nothing here adds a claim:
the wording only restates what the detector found, and the "how to improve" text is generic advice for that
rule, never a promise about this page.
"""
from typing import Any, Dict, Optional, Tuple

# axe-core rule -> (what was detected, why it matters, how to improve)
AXE_RULES: Dict[str, Tuple[str, str, str]] = {
    "image-alt": ("Some images have no text alternative",
                  "Screen readers announce images by their alternative text. Without it, people who cannot see the image are told nothing about it.",
                  "Give each meaningful image an alt text that describes it. Decorative images can use an empty alt."),
    "link-name": ("Some links don't have clear names",
                  "Screen readers read links out of context, so a link with no readable name gives no idea where it leads.",
                  "Give every link visible text, or an accessible label that says where it goes."),
    "button-name": ("Some buttons don't have clear names",
                    "A button with no readable name is announced as just \"button\", so its purpose is unclear.",
                    "Put visible text in the button, or give it an accessible label describing the action."),
    "label": ("Some form fields have no label",
              "Without a label, assistive technology cannot say what a field expects, which makes the form hard to complete.",
              "Connect a visible label to each field, or give the field an accessible label."),
    "color-contrast": ("Some text is hard to read against its background",
                       "Low contrast text is difficult to read for people with reduced vision, and for anyone in bright light.",
                       "Increase the contrast between the text and its background (4.5:1 for normal text, 3:1 for large text)."),
    "heading-order": ("Headings skip levels",
                      "People who navigate by headings use the levels to understand structure; skipped levels make the outline confusing.",
                      "Use heading levels in order, without skipping from one level to a much deeper one."),
    "landmark-one-main": ("The page has no main landmark",
                          "A main landmark lets assistive technology jump straight to the primary content.",
                          "Wrap the primary content of the page in a <main> element."),
    "region": ("Some content sits outside any landmark",
               "Content outside landmarks is hard to reach for people who navigate by regions.",
               "Place page content inside landmarks such as header, nav, main and footer."),
    "html-has-lang": ("The page doesn't declare its language",
                      "Screen readers use the page language to choose pronunciation.",
                      "Add a lang attribute to the html element, for example lang=\"en\"."),
    "document-title": ("The page has no descriptive title",
                       "The title is the first thing announced and it identifies the tab.",
                       "Give the page a title that describes its purpose."),
    "duplicate-id": ("Some element ids are used more than once",
                     "Duplicate ids can send assistive technology and scripts to the wrong element.",
                     "Make every id unique on the page."),
    "list": ("Some lists are not marked up correctly",
             "Screen readers announce how many items a list has; broken markup loses that.",
             "Keep only list items as direct children of ul and ol elements."),
    "listitem": ("Some list items are outside a list",
                 "List semantics are lost when items are not inside a list.",
                 "Place li elements inside a ul or ol."),
    "nested-interactive": ("Some controls contain other controls",
                           "Nested controls confuse assistive technology about what can be activated.",
                           "Keep interactive elements separate rather than nesting them."),
    "meta-viewport": ("The page blocks zooming",
                      "People with low vision often need to zoom in to read.",
                      "Allow zooming: avoid user-scalable=no and a maximum-scale below 2."),
    "frame-title": ("Some frames have no title",
                    "A frame without a title gives no clue about its content.",
                    "Give each iframe a title that describes its content."),
    "aria-allowed-attr": ("Some ARIA attributes aren't allowed on their element",
                          "Invalid ARIA can make an element announce the wrong thing.",
                          "Use only the ARIA attributes allowed for that role."),
    "aria-required-attr": ("Some ARIA roles are missing required attributes",
                           "Without the required attributes the role is announced incompletely.",
                           "Add the attributes the role requires, or remove the role."),
    "aria-valid-attr-value": ("Some ARIA attributes have invalid values",
                              "An invalid value can point at nothing, so the element is announced incorrectly.",
                              "Correct the attribute values, including references to element ids."),
    "aria-hidden-focus": ("Hidden content can still be focused",
                          "Focusing something hidden from assistive technology leaves people lost.",
                          "Remove the elements from the tab order when they are aria-hidden."),
    "target-size": ("Some controls are very small to tap",
                    "Small targets are hard to hit accurately, especially on touch screens.",
                    "Give controls a target area of at least 24x24 pixels, or more spacing."),
    "scrollable-region-focusable": ("A scrollable area can't be reached by keyboard",
                                    "People who use a keyboard cannot scroll a region they cannot focus.",
                                    "Make scrollable regions focusable, for example with tabindex=\"0\"."),
}

# AI rule id -> (what was detected, why it matters)
AI_RULES: Dict[str, Tuple[str, str]] = {
    "weak_primary_cta": ("The main action doesn't stand out",
                         "When the primary action looks like everything around it, people hesitate or pick the wrong control."),
    "bad_visual_hierarchy": ("The most prominent control isn't the main action",
                             "People reach for whatever looks most important, so a stronger secondary or destructive control invites mistakes."),
    "competing_cta": ("Several actions compete for attention",
                      "When actions look equally important, it is unclear which one to use."),
    "misleading_visual_emphasis": ("A less important action looks like the main one",
                                   "Strong emphasis on a secondary action draws attention away from the primary task."),
    "destructive_action_without_clear_warning": ("A destructive action isn't clearly marked",
                                                 "Actions that delete or cancel something should be obvious before they are used."),
    "confusing_form": ("This form is hard to follow",
                       "Unclear fields and grouping make people guess what to enter, which causes errors."),
    "ambiguous_label": ("A label doesn't say what it does",
                        "People rely on labels to predict what will happen."),
    "unclear_instruction": ("Instructions are unclear",
                            "Without clear guidance people fill in the wrong thing or stop."),
    "poor_error_recovery": ("Error messages don't say how to recover",
                            "An error that doesn't explain the fix leaves people stuck."),
    "insufficient_feedback": ("An action gives no visible feedback",
                              "Without feedback people repeat the action or assume it failed."),
    "misleading_feedback": ("Feedback doesn't match what happened",
                            "Misleading feedback makes people trust the wrong outcome."),
    "interaction_failure": ("A control doesn't do what it promises",
                            "Controls that do nothing, or raise an error, block the task."),
    "non_responsive_control": ("A control doesn't respond", "People cannot complete the task the control belongs to."),
    "click_without_feedback": ("Clicking gives no visible result", "People cannot tell whether the action worked."),
    "broken_form_submission": ("Submitting this form doesn't work as expected",
                               "The task cannot be completed, or data is lost."),
    "false_affordance": ("Something looks clickable but isn't",
                         "People click it, nothing happens, and they lose confidence in the page."),
    "bad_navigation": ("Navigation doesn't behave as expected",
                       "Navigation that leads nowhere, or somewhere unexpected, makes the site hard to move through."),
    "broken_menu": ("A menu doesn't open as expected", "The items inside the menu cannot be reached."),
    "horizontal_overflow": ("The page scrolls sideways",
                            "Sideways scrolling hides content and is awkward, especially on phones."),
    "clipped_content": ("Some content is cut off", "Text or controls that are cut off cannot be read or used."),
    "overlapping_elements": ("Elements overlap each other", "Overlapping controls can hide or block each other."),
    "offscreen_control": ("A control sits outside the visible area", "Controls off screen are easy to miss or unreachable."),
    "excessive_information_density": ("This section packs in a lot at once",
                                      "Dense sections take longer to scan and make it easy to miss the important part."),
    "cognitive_load_problem": ("This part asks a lot of the reader at once",
                               "Too much at once slows people down and causes mistakes."),
    "poor_grouping": ("Related things aren't grouped together", "Scattered related content is harder to understand."),
    "poor_spacing_consistency": ("Spacing is inconsistent", "Uneven spacing makes a layout feel unstructured and harder to scan."),
    "poor_alignment": ("Elements aren't aligned consistently", "Misalignment makes a layout harder to scan."),
    "typography_hierarchy_issue": ("Text sizes don't show what's most important",
                                   "Type size and weight tell people what to read first."),
    "discoverability_problem": ("Something important is hard to find", "When key tools or actions are hidden, visitors take longer to finish their goal."),
    "dead_end_workflow": ("This path leads to a dead end", "People reach a point with no way forward."),
    "unclear_system_status": ("The page doesn't say what is happening", "Without status, people wait or repeat actions."),
    "application_console_error": ("The page reported an error while running",
                                  "Runtime errors often mean part of the page silently stopped working."),
    "application_runtime_exception": ("The page raised an uncaught error",
                                      "An uncaught error can leave part of the page broken."),
    "application_network_failure": ("A request the page made failed",
                                    "Failed requests usually mean missing content or a feature that doesn't work."),
}

# AURA's canonical ids for the same deterministic rules, in case a finding arrives normalized
CANONICAL_ALIASES = {
    "image_alt_missing": "image-alt", "image_alt": "image-alt", "missing_alt": "image-alt",
    "color_contrast": "color-contrast", "unlabelled_button": "button-name", "button_name": "button-name",
    "missing_label": "label", "link_name": "link-name", "landmark_one_main": "landmark-one-main",
    "heading_order": "heading-order", "html_has_lang": "html-has-lang", "document_title": "document-title",
    "target_size": "target-size", "duplicate_id": "duplicate-id",
}

RUNTIME_FALLBACK = ("The page reported a problem while running",
                    "Runtime problems often mean part of the page did not work as intended.")


def plain_for(rule: Optional[str], category: str, source: str, title: str, description: str,
              why_it_matters: Optional[str], recommendation: Optional[str]) -> Dict[str, Any]:
    """Human wording for one finding. Falls back to what the detector itself reported."""
    key = (rule or "").strip().lower()
    key = CANONICAL_ALIASES.get(key, key)
    if key in AXE_RULES:
        headline, why, fix = AXE_RULES[key]
        return {"headline": headline, "why": why, "fix": fix, "wording": "aura"}
    if key in AI_RULES:
        headline, why = AI_RULES[key]
        return {"headline": headline, "why": why, "fix": recommendation or "", "wording": "aura"}
    if source == "Runtime":
        headline, why = RUNTIME_FALLBACK
        return {"headline": headline, "why": why_it_matters or why, "fix": recommendation or "", "wording": "detector"}
    # Unknown rule: keep the detector's own words rather than inventing a description
    clean = title.split("]: ")[-1] if title.startswith("WCAG [") else title
    return {"headline": clean, "why": why_it_matters or description or "", "fix": recommendation or "", "wording": "detector"}


DETECTOR_LABELS = {
    "axe-core": "axe-core",
    "Runtime": "Browser runtime",
    "Interaction": "Interaction test",
    "AI": "AI-assisted",
}

STATUS_LABELS = {
    "CONFIRMED": "Confirmed",
    "LIKELY": "Likely",
    "UNCERTAIN": "Uncertain",
    "REJECTED": "Rejected",
}

STATUS_MEANING = {
    "CONFIRMED": "Browser evidence supports this finding.",
    "LIKELY": "Evidence points this way, but it could not be fully proven.",
    "UNCERTAIN": "AURA suspects this, but the evidence collected does not confirm it.",
    "REJECTED": "Evidence showed this was not a defect.",
}
