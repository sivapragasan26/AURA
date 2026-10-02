"""
AURA Finding Interpretation Layer.

Transforms raw detector observations (axe-core, browser runtime, multimodal AI)
into structured, human-understandable findings that answer four core questions:
1. What is wrong?
2. Why does it matter?
3. What should I do?
4. Where is it?

Strict principles:
- Grounded: never invent user impact; use actual evidence.
- Restrained: subjective AI opinions are never promoted to "Confirmed problem".
- Traceable: all raw technical facts (selectors, rule IDs, verification scores,
  axe descriptions, AI contribution scores) are preserved in `technical_details`.
- Grouped: repetitive instances of the same issue are grouped for presentation
  with an expandable list of affected elements without altering benchmark data.
"""
from typing import Any, Dict, List, Optional, Tuple
import re

# -----------------------------------------------------------------------------
# 1. Human-Readable Rule Dictionaries
# Format: (title, what_is_wrong, why_it_matters, what_to_do)
# -----------------------------------------------------------------------------

AXE_INTERPRETATIONS: Dict[str, Tuple[str, str, str, str]] = {
    # A page can look neatly divided on screen and still leave content unassigned to a section that screen
    # readers can jump to. The wording must not claim the page "is not divided into sections".
    "region": (
        "Some content isn't assigned to a page section",
        "This page may look divided into sections on screen, but some content is not assigned to a page section "
        "that screen readers can jump to.",
        "People who move through a page section by section may have trouble jumping straight to that content.",
        "Assign the content to a clear page section."
    ),
    "landmark-one-main": (
        "The page does not have a clear primary content area",
        "AURA could not identify one clearly defined area containing the page's main content.",
        "A clear structure helps screen readers and keyboard users move directly to the main part of the page.",
        "Define one clear primary content area for the main page content."
    ),
    "page-has-heading-one": (
        "The page doesn't have a clear main heading",
        "AURA could not identify a clear primary heading that introduces the page.",
        "A primary heading gives readers and screen readers immediate context about the page topic.",
        "Add a clear primary heading at the top of the main content."
    ),
    "link-name": (
        "Some links don't have clear names",
        "Some links on this page don't provide enough readable information to tell users where they lead.",
        "People using screen readers may hear an unlabelled link or generic web address without enough context.",
        "Give each link a clear name that describes its destination."
    ),
    "button-name": (
        "Some buttons don't have clear names",
        "Some buttons lack readable text or a clear label describing what action they perform.",
        "Users relying on screen readers may hear only 'button' without knowing what activating it will do.",
        "Add clear descriptive text describing the specific action this button performs."
    ),
    "image-alt": (
        "Some images are missing descriptions",
        "Meaningful images on this page lack text descriptions.",
        "People who cannot view the image miss important visual information or context.",
        "Add a short description to meaningful images, or mark them as decorative if they add no information."
    ),
    "color-contrast": (
        "Text is difficult to read against its background",
        "The contrast between the text color and its background color is too low to read comfortably.",
        "People with low vision or anyone reading in bright light will struggle to read this text.",
        "Darken the text or lighten the background to make the words clearly readable."
    ),
    "aria-prohibited-attr": (
        "This element uses an accessibility setting that doesn't match its purpose",
        "This element uses an accessibility setting that isn't supported for this type of content.",
        "Screen readers and speech tools may ignore the setting or announce confusing information.",
        "Remove the unsupported accessibility setting or apply it to a supported container."
    ),
    "aria-allowed-attr": (
        "Some accessibility settings are not permitted on this control",
        "This element includes an accessibility setting that does not apply to this type of control.",
        "Screen readers may announce inaccurate or confusing properties for this control.",
        "Remove the unsupported setting so screen readers announce the control accurately."
    ),
    "aria-required-attr": (
        "A control is missing a required accessibility setting",
        "An interactive control is missing necessary accessibility information describing its state.",
        "Screen readers cannot fully announce or operate the control without these properties.",
        "Provide the required state or label information for this control."
    ),
    "aria-valid-attr-value": (
        "An accessibility setting has an invalid value",
        "An accessibility property contains an unrecognized value or points to an item that does not exist.",
        "The control may fail to announce its status or relationship correctly.",
        "Correct the property value to match an existing element on the page."
    ),
    "aria-hidden-focus": (
        "Hidden content can still receive keyboard focus",
        "Content that is hidden from screen readers can still be reached using keyboard navigation.",
        "Keyboard users may become disoriented by focusing on invisible or hidden items.",
        "Ensure hidden content cannot be selected with the keyboard."
    ),
    "label": (
        "Some form fields don't have clear labels",
        "Input fields are missing clear labels explaining what information to enter.",
        "Users may not know what information is expected in each field before typing.",
        "Provide a clear, visible label adjacent to each form field."
    ),
    "heading-order": (
        "Some headings jump over levels",
        "The page moves between heading levels without following a consistent order.",
        "People who navigate by headings may find the page structure harder to follow.",
        "Arrange the headings so their levels follow the structure of the content."
    ),
    "document-title": (
        "The page does not have a descriptive title",
        "The page title shown in browser tabs is missing, empty, or uninformative.",
        "Users with multiple tabs or screen-reader users cannot easily identify this page in their browser.",
        "Provide a clear, descriptive title that identifies the page content and website."
    ),
    "html-has-lang": (
        "The page does not declare its primary language",
        "The page does not specify which human language its content is written in.",
        "Screen readers may use incorrect speech pronunciation rules when reading this page aloud.",
        "Specify the primary language of the page so speech tools pronounce words correctly."
    ),
    "target-size": (
        "Interactive controls are too small to tap easily",
        "The clickable or tappable area of a button or link is too small to select reliably.",
        "Users on touchscreens or with limited hand mobility may accidentally tap adjacent items.",
        "Increase the touch area and leave comfortable spacing around interactive controls."
    ),
    "duplicate-id": (
        "Identifier names are repeated on the page",
        "Multiple elements share the same internal identifier on the page.",
        "Page scripts and screen-reader labels may link to the wrong element.",
        "Ensure every identifier on the page is completely unique."
    ),
    "image-redundant-alt": (
        "Image description repeats adjacent text",
        "The image description repeats words already visible right next to it.",
        "Screen readers will announce the exact same information twice, creating a repetitive listening experience.",
        "Remove the duplicate description or leave the image description empty if the text already describes it."
    ),
    "label-title-only": (
        "Form field is missing a visible label",
        "This input field only has hover or tooltip text instead of an always-visible text label.",
        "People filling out the form may forget what belongs in the field once they start typing.",
        "Add a persistent, visible label adjacent to the form field."
    ),
    "landmark-no-duplicate-contentinfo": (
        "Page contains more than one footer section",
        "The page has multiple sections marked as the main footer.",
        "People who navigate by page sections may be confused about where the real page footer is.",
        "Keep a single primary footer section for the page."
    ),
    "landmark-unique": (
        "Page sections share identical labels",
        "Multiple distinct page sections have the exact same label.",
        "Users navigating by page sections cannot easily tell which section is which.",
        "Give each page section a distinct and specific descriptive name."
    ),
    "aria-required-children": (
        "Some controls are missing required child elements",
        "An accessibility container element is missing required internal items, such as list items or tab panels.",
        "Screen readers rely on the parent-child relationship to navigate through groups of controls.",
        "Ensure all required child items are present inside this accessibility container."
    ),
    "aria-required-parent": (
        "Some controls are outside their required container",
        "An accessibility element is placed outside its required parent structure, such as an item outside a list.",
        "Screen readers cannot announce how many items exist in the group or which item is active.",
        "Wrap this item inside its appropriate accessibility container."
    ),
    "aria-roles": (
        "Some controls provide incorrect accessibility information",
        "An element specifies an accessibility role that is invalid or unrecognized.",
        "Assistive technologies may fail to announce the control correctly or ignore its controls.",
        "Use a valid standard accessibility role or use standard HTML elements."
    ),
    "dlitem": (
        "Definition terms are outside a definition list",
        "Terms and their descriptions are not grouped inside the list they belong to.",
        "Screen readers cannot announce term-definition relationships properly.",
        "Group each term together with its description inside one list."
    ),
    "listitem": (
        "List items are not contained inside a list",
        "Items that read as a list are not grouped inside a bulleted or numbered list.",
        "Screen readers cannot announce the total number of items or current position in the list.",
        "Group the items inside one bulleted or numbered list."
    ),
    "list": (
        "List contains elements that are not list items",
        "A list contains things that are not list items.",
        "Assistive technologies may fail to announce list items properly.",
        "Keep only list items directly inside the list."
    ),
    "duplicate-id-aria": (
        "Accessibility labels reference duplicate identifiers",
        "An accessibility label or attribute references an identifier used more than once on the page.",
        "Screen readers and accessibility tools may link to or read the wrong element.",
        "Ensure all elements referenced by accessibility attributes have unique IDs."
    ),
    "nested-interactive": (
        "Interactive controls are nested inside each other",
        "A button or link is nested inside another clickable control.",
        "Users navigating by keyboard or screen reader may trigger the wrong action or get trapped.",
        "Separate nested clickable controls so each button or link is independent."
    ),
    "tabindex": (
        "Custom tab order disrupts natural page navigation",
        "Some elements force their own position in the keyboard order instead of following the page order.",
        "Keyboard users may jump unexpectedly between unrelated parts of the page.",
        "Let the keyboard order follow the order of the content on the page."
    ),
    "bypass": (
        "The page does not provide a shortcut to skip repeated navigation",
        "There is no skip link or shortcut mechanism to bypass repetitive header navigation.",
        "Keyboard and screen reader users must tab through all navigation links before reaching content.",
        "Add a visible skip-to-content link at the very top of the page."
    ),
    "empty-heading": (
        "The page contains empty headings",
        "A heading element exists in the markup without readable text content.",
        "Screen readers announce an empty heading, confusing users navigating the page outline.",
        "Add descriptive text to the heading or remove the empty heading element."
    ),
    "frame-title": (
        "Embedded frame is missing a title description",
        "An embedded iframe element lacks a title attribute describing its contents.",
        "Users relying on screen readers cannot tell what content or service the embedded frame provides.",
        "Add a concise, descriptive title attribute to the iframe."
    ),
    "form-field-multiple-labels": (
        "Form field has multiple conflicting labels",
        "An input field is associated with multiple label elements.",
        "Assistive technologies may announce conflicting or redundant names for the input.",
        "Associate only one clear, unambiguous label with each form field."
    ),
    "select-name": (
        "Dropdown menu does not have a clear label",
        "A select dropdown menu is missing an accessible name or label.",
        "Screen readers cannot announce the purpose of the dropdown menu to users.",
        "Give the dropdown a clear name that says what it selects."
    ),
    "svg-img-alt": (
        "Vector graphic is missing an accessible description",
        "An SVG graphic functioning as an image lacks a readable text alternative.",
        "People who cannot see the graphic will miss the information or icon meaning.",
        "Give the graphic a short description of what it shows or means."
    ),
    "meta-viewport": (
        "Page restricts users from zooming in",
        "The page viewport configuration disables zooming or restricts maximum zoom level.",
        "People with low vision cannot enlarge text and images to read comfortably.",
        "Let people zoom the page as far as they need to."
    ),
    "scrollable-region-focusable": (
        "Scrollable area cannot be reached using the keyboard",
        "A container with scrollable content cannot receive keyboard focus.",
        "Keyboard-only users cannot scroll the area to read clipped or overflowing content.",
        "Let the scrolling area receive keyboard focus, and give it a name."
    ),
    "focus-order-semantics": (
        "Keyboard focus order contains elements with missing roles",
        "An interactive item in the tab focus order does not have an appropriate interactive role.",
        "Keyboard users may focus on an item without knowing how to operate it.",
        "Assign appropriate interactive roles or use standard HTML buttons and links."
    ),
}

AI_INTERPRETATIONS: Dict[str, Tuple[str, str, str, str]] = {
    "weak_primary_cta": (
        "The primary action button does not stand out clearly",
        "The main action button blends into surrounding elements instead of drawing visual attention.",
        "Users may hesitate or struggle to identify the next step in the workflow.",
        "Make the primary button stand out clearly using a solid background color, distinct size, or bolder styling."
    ),
    "bad_visual_hierarchy": (
        "Button styling does not match action priority",
        "A secondary, cancel, or destructive button draws more visual attention than the main action.",
        "Users are drawn to whatever looks biggest and brightest, which may lead to accidental cancellation or deletion.",
        "Give the main action clear visual priority with solid button styling, and use outline or muted styling for secondary actions."
    ),
    "competing_cta": (
        "Multiple actions compete for attention",
        "Two or more adjacent buttons have identical high-contrast visual styling.",
        "Users may experience decision paralysis when trying to determine which action is recommended.",
        "Differentiate the buttons by making one primary (solid fill) and others secondary (outline or text)."
    ),
    "misleading_visual_emphasis": (
        "Secondary control looks like the main action",
        "A less important action has high visual emphasis, misleading the user's focus.",
        "People may accidentally trigger a secondary flow instead of the intended main task.",
        "Apply secondary button styling (such as an outline or muted color) to non-primary actions."
    ),
    "destructive_action_without_clear_warning": (
        "Destructive action lacks a clear visual distinction",
        "An action that permanently deletes, removes, or cancels data looks identical to benign actions.",
        "Users may accidentally trigger irreversible actions without noticing the consequence in advance.",
        "Style destructive actions with distinct warning cues (such as danger coloring) or require confirmation."
    ),
    "ambiguous_label": (
        "This action label may be unclear",
        "The button or control label is terse or vague without sufficient accompanying context.",
        "Users may be uncertain what will happen after clicking the control.",
        "Make the control label more descriptive or provide clear contextual supporting text."
    ),
    "discoverability_problem": (
        "Finding key options may be harder than expected",
        "An important feature is subtle or hidden behind a compact icon without descriptive text.",
        "People looking for this action may overlook it or spend extra time searching the page.",
        "Make the action more visually prominent, such as displaying a visible field or clear label."
    ),
    "search_discoverability": (
        "Finding search may be harder than expected",
        "Search is available through an icon rather than an open, visible search field.",
        "People looking for a specific item may not immediately notice where to search.",
        "Consider making the search option more visually obvious, especially on smaller screens."
    ),
    "unclear_instruction": (
        "Form instructions may be difficult to understand",
        "Guidelines or requirements for completing this task are vague or missing.",
        "Users may make mistakes or abandon the workflow due to uncertainty.",
        "Provide concise, unambiguous instructions explaining the required format or steps."
    ),
    "poor_error_recovery": (
        "Error message does not explain how to fix the issue",
        "An error state appeared without actionable instructions for resolving it.",
        "Users can become stuck when an error does not state what needs correction.",
        "Provide specific, helpful recovery instructions indicating which field needs attention and why."
    ),
    "insufficient_feedback": (
        "An action gave no visible feedback",
        "Activating a control did not display a visible confirmation, loading spinner, or state transition.",
        "Users may repeatedly click the control or wonder whether their action was registered.",
        "Display clear, immediate visual feedback (such as a spinner or toast notification) upon activation."
    ),
    "horizontal_overflow": (
        "The page scrolls horizontally",
        "Content extends beyond the viewport width, causing an unwanted horizontal scrollbar.",
        "Horizontal scrolling can hide important content and creates an awkward experience, particularly on mobile.",
        "Constrain layout elements to fit within the screen width without side-to-side scrolling."
    ),
    "clipped_content": (
        "Content is cut off by its container",
        "Text or controls are clipped by fixed-height container boundaries.",
        "Users may miss critical details or be unable to interact with partially hidden buttons.",
        "Allow container height to expand with content, or remove restrictive clipping boundaries."
    ),
    "overlapping_elements": (
        "Elements visually overlap each other",
        "Multiple elements occupy the same physical coordinates on screen.",
        "Overlapping text makes content illegible, and overlapping buttons can block clicks.",
        "Adjust layout spacing and positioning to give each element dedicated layout space."
    ),
    "poor_spacing_consistency": (
        "Inconsistent spacing between sections",
        "Margins and padding vary unpredictably across adjacent layout components.",
        "The layout can feel unpolished and disorienting, making scanning more strenuous.",
        "Apply a consistent spacing scale across layout containers."
    ),
    "poor_grouping": (
        "Related items are visually scattered",
        "Elements that belong to the same logical group lack clear visual boundaries or proximity.",
        "Users have to search across the screen to locate related information.",
        "Group related elements together inside cards, panels, or distinct visual clusters."
    ),
    "typography_hierarchy_issue": (
        "Heading sizes do not show what to read first",
        "Subheadings and body text have similar font sizes or weights as major headings.",
        "Readers rely on heading sizes to scan the page quickly and find the section they need.",
        "Use distinctly larger font sizes and weights for main headings and smaller sizes for subheadings."
    ),
    "confusing_form": (
        "The form layout may be confusing to complete",
        "Fields and steps are organized in a way that may disorient people filling it out.",
        "Users may hesitate, make input mistakes, or abandon the form before submitting.",
        "Streamline form fields in logical order with clear groupings and helpful hints."
    ),
    "bad_navigation": (
        "Navigation menu items may be difficult to use",
        "Navigation links overlap or lack sufficient separation to click comfortably.",
        "People may accidentally click the wrong destination when trying to browse the site.",
        "Provide clean spacing and clear boundaries between navigation links."
    ),
    "cognitive_load_problem": (
        "This part of the page asks a lot of the reader at once",
        "A single area presents many separate things to read, compare or decide between.",
        "People scanning quickly may miss the one thing they came for, or give up and start again.",
        "Reduce what this area shows at once, or split it into steps or groups with clear names."
    ),
    "excessive_information_density": (
        "A lot is packed into one area",
        "One area of the page holds an unusually high number of items in a small space.",
        "Dense areas are slow to scan, and neighbouring items are easy to mistake for one another.",
        "Give the items more room, or split the area into smaller labelled groups."
    ),
    "excessive_horizontal_scanning": (
        "Related information is spread too far apart across the page",
        "Items that belong together sit far apart horizontally, so the eye has to travel between them.",
        "People lose their place moving between a label on one side and its value on the other.",
        "Bring related items closer together, or align them so one line reads as one thing."
    ),
    "inconsistent_component_styling": (
        "Similar controls are styled differently",
        "Controls that do the same kind of job are presented in visibly different ways.",
        "People learn a control by how it looks; when the look changes they have to work it out again.",
        "Give controls of the same kind the same treatment, and reserve a different look for a different job."
    ),
    "inconsistent_state_styling": (
        "The same state looks different in different places",
        "A state such as selected, disabled or active is shown one way here and another way elsewhere.",
        "People cannot tell at a glance which items are in which state.",
        "Show each state the same way everywhere it appears."
    ),
    "poor_alignment": (
        "Items on this row don't line up",
        "Neighbouring items sit at visibly different positions rather than on a shared line.",
        "A ragged edge makes a list harder to scan, and makes the page look unfinished.",
        "Align the items to a shared edge or baseline."
    ),
    "responsive_spacing_failure": (
        "Spacing breaks down at this screen size",
        "At this width the gaps between elements collapse or grow far beyond the rest of the layout.",
        "Content can end up cramped against an edge or stranded far from what it belongs to.",
        "Set spacing that holds at this width as well as the wider layout."
    ),
    "poor_task_flow": (
        "The steps in this task are hard to follow",
        "The order in which this page presents its steps does not match the order a person works through them.",
        "People backtrack, repeat steps, or stop before finishing.",
        "Put the steps in the order people actually do them, and show where they are in the sequence."
    ),
    "unnecessary_user_step": (
        "This task asks for a step that isn't needed",
        "The flow requires an action that does not change the outcome or that the page could do itself.",
        "Every extra step is another chance to abandon the task.",
        "Remove the step, or do it automatically and let people change it afterwards."
    ),
    "excessive_form_complexity": (
        "This form asks for a lot in one go",
        "The form presents many fields at once without grouping or a sense of progress.",
        "Long undivided forms are abandoned more often than short ones.",
        "Group related fields, and split a long form into steps that show progress."
    ),
    "dead_end_workflow": (
        "This path leaves the reader with nowhere to go",
        "After this point the page offers no next step, and no way back to where the person came from.",
        "People get stuck and use the browser's back button, losing what they had entered.",
        "Offer a clear next step here, and a way back that keeps what was entered."
    ),
    "unclear_information_architecture": (
        "It isn't clear where things live on this site",
        "The grouping and naming on this page do not make it obvious where a given item belongs.",
        "People look in the wrong place first, and give up before finding what they came for.",
        "Name the groups the way people describe what they are looking for, and keep related items together."
    ),
    "unclear_system_status": (
        "The page doesn't say what it is doing",
        "The page changes state without telling the reader that something happened or is in progress.",
        "People repeat an action because nothing told them the first one worked.",
        "Show what is happening, and what finished, where the person is looking."
    ),
    "inconsistent_workflow_behavior": (
        "The same action behaves differently in different places",
        "An action that looks the same produces a different result depending on where it is used.",
        "People carry over what they learned somewhere else and get an outcome they did not expect.",
        "Make the same action behave the same way wherever it appears."
    ),
    "unclear_interactive_affordance": (
        "It isn't obvious that this can be clicked",
        "This element responds to a click but is not presented as something to click.",
        "People never try it, so the feature might as well not be there.",
        "Present it the way the rest of the page presents things that can be clicked."
    ),
    "false_affordance": (
        "This looks clickable but isn't",
        "The element is styled like a control, but nothing happens when it is used.",
        "People click it, get nothing, and start to doubt the rest of the page.",
        "Either make it work, or stop presenting it as a control."
    ),
    "misleading_cta": (
        "This button's label doesn't match what it does",
        "The label promises one outcome and the action produces a different one.",
        "People commit to an action expecting something else, which is hard to undo trust-wise.",
        "Label the control with what it actually does."
    ),
    "misleading_feedback": (
        "The page reports something that didn't happen",
        "A message says an action succeeded or failed in a way the page's own state does not support.",
        "People act on the message and find out later that it was wrong.",
        "Report the result the action actually produced."
    ),
    "unexpected_behavior": (
        "This control does something other than expected",
        "Using this control produces a result that its presentation does not lead a person to expect.",
        "People end up somewhere they did not intend to go.",
        "Make the outcome match what the control leads people to expect, or say up front what it will do."
    ),
    "non_responsive_control": (
        "A control did nothing when it was used",
        "The control was activated and the page showed no change and reported no error.",
        "People read it as broken and click it again, which can make things worse.",
        "Make the control respond, or show why it cannot right now."
    ),
    "dead_button": (
        "A button does nothing when pressed",
        "Pressing this button produced no change anywhere on the page.",
        "People press it repeatedly and conclude the page is broken.",
        "Connect the button to its action, or remove it."
    ),
    "click_without_feedback": (
        "An action gave no sign that it worked",
        "The control was used and the page gave no confirmation, no progress and no change.",
        "People repeat the action, sometimes submitting it twice.",
        "Show immediately that the action was received, and then what it produced."
    ),
    "incorrect_state_transition": (
        "A control ends up in the wrong state",
        "After being used the control shows a state that does not match what happened.",
        "People trust the control's appearance and act on the wrong assumption.",
        "Make the control's state follow the result of the action."
    ),
    "broken_toggle": (
        "A switch doesn't hold its setting",
        "The switch changes appearance but the setting it controls does not follow.",
        "People believe they changed a setting when nothing changed.",
        "Make the switch apply the setting it shows."
    ),
    "broken_menu": (
        "A menu doesn't open or behave as expected",
        "The menu either did not open, or opened without the items it is meant to hold.",
        "People cannot reach whatever lives behind that menu.",
        "Make the menu open reliably with its full contents."
    ),
    "broken_modal": (
        "A dialog doesn't open or close properly",
        "The dialog failed to open, or could not be dismissed once it was open.",
        "A dialog that will not close blocks the whole page.",
        "Make the dialog open on demand and close on every documented way out."
    ),
    "broken_form_submission": (
        "Submitting this form doesn't work",
        "Submitting the form produced no result, or an error that the page did not explain.",
        "People lose what they typed and have no way to complete the task.",
        "Make submission work, and keep what was entered if it fails."
    ),
    "failed_form_interaction": (
        "This form could not be filled in",
        "A field in this form could not accept input during the check.",
        "People cannot complete the task the form exists for.",
        "Make every field accept input, and say clearly when one is unavailable."
    ),
    "validation_feedback_failure": (
        "The form doesn't say what is wrong",
        "The form rejected input without pointing at the field that needs changing.",
        "People guess at what to fix, and often give up.",
        "Point at the field that needs attention and say what is expected there."
    ),
    "interaction_dead_end": (
        "This control leads nowhere",
        "Using the control produced no change and offered no next step.",
        "People stall here with no indication of what to do next.",
        "Give the control an outcome, or a clear next step."
    ),
    "interaction_failure": (
        "A button or control did not respond when activated",
        "Clicking or tapping this control produced no visible change or threw an internal error.",
        "Users may assume the application is broken or frozen.",
        "Verify that the interactive action handler is correctly attached and handles events cleanly."
    ),
}

RUNTIME_INTERPRETATIONS: Dict[str, Tuple[str, str, str, str]] = {
    "application_console_error": (
        "A script on this page stopped with an error",
        "While the page was loading, one of its scripts hit an error it did not handle.",
        "Anything that script was responsible for — a menu, a form check, content that loads as you scroll — "
        "may quietly not work.",
        "Open the browser console, find the error that was logged, and fix the code that raised it."
    ),
    "application_network_failure": (
        "Something the page asked for didn't load",
        "One of the requests this page made came back with an error instead of the content it asked for.",
        "Whatever that request was for — data, an image, part of the layout — may be missing or out of date.",
        "Check that the address the page requests is reachable and returns the expected response."
    ),
    "application_runtime_exception": (
        "An error interrupted part of the page",
        "An error was raised while the page was running and nothing caught it, so that piece of the page "
        "stopped where it was.",
        "Controls that depend on that code may stop responding, or content may never appear.",
        "Find where the error is raised and handle it, so the rest of the page keeps working."
    ),
}

CANONICAL_ALIASES: Dict[str, str] = {
    "page_has_heading_one": "page-has-heading-one",
    "page-has-heading-one": "page-has-heading-one",
    "page_heading_one": "page-has-heading-one",
    "heading_one": "page-has-heading-one",
    "image_alt_missing": "image-alt",
    "image_alt": "image-alt",
    "missing_alt": "image-alt",
    "color_contrast": "color-contrast",
    "unlabelled_button": "button-name",
    "button_name": "button-name",
    "missing_label": "label",
    "link_name": "link-name",
    "landmark_one_main": "landmark-one-main",
    "heading_order": "heading-order",
    "html_has_lang": "html-has-lang",
    "document_title": "document-title",
    "target_size": "target-size",
    "duplicate_id": "duplicate-id",
    "aria_prohibited_attr": "aria-prohibited-attr",
    "aria_allowed_attr": "aria-allowed-attr",
    "aria_required_attr": "aria-required-attr",
    "aria_valid_attr_value": "aria-valid-attr-value",
    "aria_hidden_focus": "aria-hidden-focus",
    "search_discoverability": "search_discoverability",
    "discoverability": "discoverability_problem",
    "discoverability_problem": "discoverability_problem",
    "bad_nav": "bad_navigation",
    "confusing_form": "confusing_form",
    "interaction_failure": "interaction_failure",
}


# -----------------------------------------------------------------------------
# 2. Location Helper ("Where is it?")
# -----------------------------------------------------------------------------

# Words that commonly appear in a selector and name a part of the page a person can find.
SELECTOR_REGIONS = [
    ("search", "search area"), ("cart", "cart area"), ("basket", "cart area"), ("checkout", "checkout area"),
    ("login", "sign-in area"), ("signin", "sign-in area"), ("account", "account area"),
    ("menu", "menu"), ("dropdown", "menu"), ("flyout", "menu"), ("modal", "dialog"), ("dialog", "dialog"),
    ("banner", "banner"), ("hero", "hero area"), ("carousel", "carousel"), ("slider", "carousel"),
    ("filter", "filters"), ("facet", "filters"), ("sort", "sorting controls"),
    ("result", "results list"), ("product", "product area"), ("price", "pricing area"),
    ("review", "reviews area"), ("rating", "ratings area"), ("comment", "comments area"),
    ("breadcrumb", "breadcrumb trail"), ("pagination", "pagination controls"), ("tab", "tab strip"),
    ("list", "list"), ("grid", "grid"), ("table", "table"), ("form", "form"), ("gallery", "image gallery"),
]


def _selector_region(selector: str) -> Optional[str]:
    sel = (selector or "").lower()
    for token, label in SELECTOR_REGIONS:
        if token in sel:
            return label
    return None


def describe_location(
    selector: Optional[str] = None,
    text: Optional[str] = None,
    tag: Optional[str] = None,
    role: Optional[str] = None,
    accessible_name: Optional[str] = None,
    bounding_box: Optional[Dict[str, Any]] = None,
    page_level: bool = False
) -> str:
    """
    Produces a human-readable location description.
    NEVER displays a raw CSS selector as the primary location.
    Examples:
    - 'Create button in the top navigation'
    - 'Verified badge next to video information'
    - 'Search input field'
    Fallback: 'Specific element identified — see Technical Details.'
    """
    if page_level or (selector and selector.strip().lower() in ("body", "html", "page")):
        return "Whole page"

    clean_text = (accessible_name or text or "").strip()
    if clean_text:
        clean_text = clean_text if len(clean_text) <= 30 else clean_text[:29] + "…"

    tag_clean = (tag or "").strip().lower()
    role_clean = (role or "").strip().lower()
    sel = (selector or "").lower()

    # Determine contextual area
    context = ""
    y = (bounding_box or {}).get("y")
    if isinstance(y, (int, float)) and y < 120:
        context = "in the top navigation"
    elif "header" in sel or "nav" in sel or "navbar" in sel or "top" in sel:
        context = "in the header navigation"
    elif "footer" in sel:
        context = "in the page footer"
    elif "sidebar" in sel or "aside" in sel:
        context = "in the sidebar"
    elif "video" in sel or "player" in sel or "metadata" in sel:
        context = "near the video details"
    elif "card" in sel or "container" in sel:
        context = "inside content card"

    # Specific ARIA badge / icon detection
    if "verified" in sel or "verified" in clean_text.lower():
        loc = "Verified badge"
        return f"{loc} {context}".strip() if context else loc
    # Specific Search control recognition
    if "search" in sel or "search" in clean_text.lower():
        loc = "Search button" if (tag_clean == "button" or role_clean == "button") else "Search control"
        return f"{loc} {context}".strip() if context else loc

    if "icon" in sel and not clean_text:
        loc = f"Icon control"
        return f"{loc} {context}".strip() if context else loc

    # Named control
    descriptor = role_clean or tag_clean
    if clean_text:
        base = f'"{clean_text}" {descriptor or "element"}'
        return f"{base} {context}".strip() if context else base

    # Unnamed element with tag
    if tag_clean in ("button", "a", "input", "select", "img"):
        friendly_tag = {
            "button": "Button control",
            "a": "Link",
            "input": "Input field",
            "select": "Dropdown selection",
            "img": "Image"
        }.get(tag_clean, tag_clean)
        return f"{friendly_tag} {context}".strip() if context else f"{friendly_tag} on the page"

    # Fallback: name the region the selector points into, so "Where" is still an answer a person can use.
    if context:
        return f"An element {context}"
    region = _selector_region(sel)
    if region:
        return f"An element in the {region}"
    return "One element on this page (the exact location is in Technical details)"


# -----------------------------------------------------------------------------
# 3. Status and Confidence Mappings
# -----------------------------------------------------------------------------

def map_human_status(verification_status: str, is_ai_hypothesis: bool = False) -> str:
    """
    Translates internal verification enums into trusted user-facing statuses.
    CONFIRMED -> 'Confirmed problem'
    LIKELY -> 'Potential problem'
    UNCERTAIN -> 'Needs review' or 'Advisory'
    """
    status = (verification_status or "").upper()
    if status == "CONFIRMED":
        return "Confirmed problem"
    elif status == "LIKELY":
        return "Potential problem"
    elif status == "UNCERTAIN":
        return "Advisory" if is_ai_hypothesis else "Needs review"
    elif status == "REJECTED":
        return "Rejected"
    return "Needs review"


def map_confidence_label(confidence: Optional[float]) -> str:
    """
    Maps numerical confidence (0.0 to 1.0) into human labels:
    0.85–1.00 -> High
    0.65–0.84 -> Medium
    0.45–0.64 -> Low
    below 0.45 -> Very low
    """
    if confidence is None:
        return "Standard"
    try:
        val = float(confidence)
        if val >= 0.85:
            return "High"
        elif val >= 0.65:
            return "Medium"
        elif val >= 0.45:
            return "Low"
        else:
            return "Very low"
    except (ValueError, TypeError):
        return "Standard"

# -----------------------------------------------------------------------------
# 5. Phase 5: Reproduction, Grounded Evidence & Conclusion Trust Layer
# -----------------------------------------------------------------------------

# One canonical conclusion per finding. The badge in the list, the badge in the detail header, the
# conclusion line in the evidence summary and the technical block all read this single value, so they can
# never disagree with each other.
CONCLUSION_STRENGTHS = ("Confirmed problem", "Potential problem", "Needs review", "Advisory")


def canonical_conclusion(verification_status: str, is_ai_hypothesis: bool = False) -> str:
    """The one final conclusion for a finding. Every surface must show exactly this string."""
    return map_human_status(verification_status, is_ai_hypothesis=is_ai_hypothesis)


def determine_reproduction_and_trust(
    rule_key: str,
    category: str,
    source: str,
    v_status: str,
    flags: Dict[str, Any],
    is_ai: bool,
    selector: Optional[str] = None,
    raw_conf: Optional[float] = None,
    verification_score: Optional[float] = None,
    tag: Optional[str] = None,
    has_visual_evidence: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Evaluates grounded reproduction state, the known browser fact and the inferred user impact.

    The conclusion STRENGTH is not decided here: it is always the canonical conclusion derived from the
    verification status, so no branch can promote a LIKELY finding to "Confirmed problem". Branches only
    describe what was done and what was established.
    """
    # Rule ids reach this layer in both spellings ("aria-allowed-attr" from axe, "aria_allowed_attr" after
    # normalization). Comparing one form only is what left whole rule families on the generic branch.
    r = (rule_key or "").strip().lower().replace("_", "-")
    cat = (category or "").upper()
    src = (source or "").upper()
    sel_low = (selector or "").lower()

    reproduction: Dict[str, Any] = {
        "state": "OBSERVED",
        "action_attempted": "Inspected page structure and element properties.",
        "safety_boundary": None,
        "details": "Directly observed during automated browser inspection.",
    }
    strength = canonical_conclusion(v_status, is_ai_hypothesis=is_ai)
    conclusion: Dict[str, Any] = {
        "strength": strength,
        "known_fact": "Element condition was detected during page analysis.",
        "inferred_judgement": "May affect how easily some visitors complete what they came to do.",
    }

    # 1. Responsive & Layout Geometry
    if cat in ("RESPONSIVENESS", "RESPONSIVE") or r in ("horizontal_overflow", "clipped_content", "viewport_horizontal_scroll", "offscreen_control"):
        if v_status == "CONFIRMED":
            reproduction["state"] = "REPRODUCED"
            reproduction["action_attempted"] = "Measured layout dimensions against the viewport bounds."
            reproduction["details"] = "Issue was reproduced by calculating element dimensions relative to the viewport."
            conclusion["known_fact"] = "Element dimensions extend past the edge of the page viewport."
            conclusion["inferred_judgement"] = "Visitors need to scroll sideways to reach the part of the content that sits outside the screen."
        else:
            reproduction["state"] = "OBSERVED"
            reproduction["action_attempted"] = "Checked layout geometry against viewport constraints."
            reproduction["details"] = "Layout anomaly was observed during viewport analysis."
            conclusion["known_fact"] = "Element positioning suggests the content may extend past the viewport, but this was not measured on the claimed element."
            conclusion["inferred_judgement"] = "Sideways scrolling may appear on some screen sizes."
        conclusion["strength"] = strength
        return reproduction, conclusion

    # 2. Deterministic Accessibility
    if "AXE" in src or cat == "ACCESSIBILITY":
        reproduction["state"] = "OBSERVED"
        reproduction["details"] = "Directly observed in the page document tree during automated inspection."
        if r in ("color-contrast", "color_contrast"):
            reproduction["action_attempted"] = "Measured the text colour against its background colour."
            conclusion["known_fact"] = "The measured contrast between the text and its background is below the readable threshold."
            conclusion["inferred_judgement"] = "People with reduced vision, or anyone reading in bright light, will struggle to read this text."
        elif r in ("link-name", "button-name", "label", "missing_label", "unlabelled_button", "select-name"):
            reproduction["action_attempted"] = "Inspected the control for readable text or a name."
            conclusion["known_fact"] = "The control carries no readable text or name."
            conclusion["inferred_judgement"] = "Someone using a screen reader hears the control announced without learning what it does."
        elif r in ("image-alt", "image_alt_missing", "svg-img-alt"):
            reproduction["action_attempted"] = "Inspected the image for a text description."
            conclusion["known_fact"] = "The image carries no text description."
            conclusion["inferred_judgement"] = "People who cannot see the image miss whatever information it carries."
        elif r == "region":
            reproduction["action_attempted"] = "Checked which page section each block of content belongs to."
            conclusion["known_fact"] = "Some content on the page is not assigned to any page section."
            conclusion["inferred_judgement"] = "People who move through a page section by section cannot jump straight to that content."
        elif r == "heading-order":
            reproduction["action_attempted"] = "Read the heading levels in the order they appear on the page."
            conclusion["known_fact"] = "The heading levels jump over one or more steps."
            conclusion["inferred_judgement"] = "People who navigate by headings get an outline that does not match the content."
        elif r in ("landmark-one-main", "page-has-heading-one"):
            reproduction["action_attempted"] = "Looked for one clear main content area and a main heading."
            conclusion["known_fact"] = "The page does not mark out one clear main content area or main heading."
            conclusion["inferred_judgement"] = "Keyboard and screen-reader users cannot skip straight to the main content."
        elif r.startswith("aria-") or r in ("aria-roles", "role-img-alt"):
            reproduction["action_attempted"] = "Compared the control's accessibility information with the kind of control it is."
            conclusion["known_fact"] = "The control carries accessibility information that does not match how it works."
            conclusion["inferred_judgement"] = "Screen readers may describe the control incorrectly or skip it."
        elif r in ("list", "listitem", "dlitem", "definition-list"):
            reproduction["action_attempted"] = "Checked how the list items are grouped in the page."
            conclusion["known_fact"] = "List items are not grouped inside a proper list."
            conclusion["inferred_judgement"] = "Screen readers cannot announce how many items there are or which one is current."
        elif r == "meta-viewport":
            reproduction["action_attempted"] = "Checked whether the page allows zooming."
            conclusion["known_fact"] = "The page prevents or limits zooming."
            conclusion["inferred_judgement"] = "People who need larger text cannot enlarge the page to read it."
        elif "lang" in r:
            reproduction["action_attempted"] = "Checked which language the page declares for its content."
            conclusion["known_fact"] = "The page does not declare the language of this content, or declares one that is not recognised."
            conclusion["inferred_judgement"] = "Speech tools read the text with the wrong pronunciation rules."
        elif r == "document-title":
            reproduction["action_attempted"] = "Read the title the browser tab shows for this page."
            conclusion["known_fact"] = "The page title is missing or says nothing about the page."
            conclusion["inferred_judgement"] = "People with several tabs open cannot tell which one this is."
        elif "duplicate-id" in r:
            reproduction["action_attempted"] = "Compared the internal identifiers used across the page."
            conclusion["known_fact"] = "More than one element on this page uses the same internal identifier."
            conclusion["inferred_judgement"] = "Labels and scripts can attach to the wrong element, so the page behaves unpredictably."
        elif r == "target-size":
            reproduction["action_attempted"] = "Measured how large the tappable area of the control is."
            conclusion["known_fact"] = "The tappable area of the control is smaller than the comfortable minimum."
            conclusion["inferred_judgement"] = "On a touchscreen people are likely to hit the wrong thing."
        elif r == "nested-interactive":
            reproduction["action_attempted"] = "Checked whether any control sits inside another control."
            conclusion["known_fact"] = "A control on this page is nested inside another control."
            conclusion["inferred_judgement"] = "Keyboard and screen-reader users may trigger the wrong action or get stuck."
        elif r == "bypass":
            reproduction["action_attempted"] = "Looked for a way to skip past the repeated navigation."
            conclusion["known_fact"] = "The page offers no shortcut past its repeated navigation."
            conclusion["inferred_judgement"] = "Keyboard users must tab through the whole navigation before reaching the content."
        else:
            reproduction["action_attempted"] = "Compared the element's markup with the accessibility rules for this kind of control."
            conclusion["known_fact"] = "The element's markup does not follow the accessibility rules for this kind of control."
            conclusion["inferred_judgement"] = "Screen readers and speech tools may announce this element incorrectly."
        conclusion["strength"] = strength
        return reproduction, conclusion

    # 3. Runtime & Console Errors
    if "RUNTIME" in src or "CONSOLE" in src or "NETWORK" in src or cat == "RUNTIME":
        reproduction["state"] = "OBSERVED"
        reproduction["action_attempted"] = "Recorded the browser console, page errors and network activity during the scan."
        reproduction["details"] = "Directly recorded in browser runtime telemetry during page load."
        conclusion["known_fact"] = "The browser logged a script error or a failed network request while the page loaded."
        conclusion["inferred_judgement"] = "Features that depend on that script or request may not work."
        conclusion["strength"] = strength
        return reproduction, conclusion

    # 4. Controlled Interactions
    if cat == "INTERACTION":
        is_sensitive = any(w in sel_low for w in ("submit", "form", "pay", "checkout", "buy", "delete", "destroy", "remove", "login", "password"))
        if is_sensitive:
            reproduction["state"] = "NOT_APPLICABLE"
            reproduction["safety_boundary"] = "Non-destructive verification policy: form submission, checkout, payment, and account mutations are strictly protected."
            reproduction["action_attempted"] = "Checked the interaction safety boundary before doing anything."
            reproduction["details"] = "Automated interaction was skipped because target involves protected actions (e.g. form submission, purchase, or deletion)."
            conclusion["known_fact"] = "The control belongs to a flow AURA is not allowed to trigger, so its behaviour was not tested."
            conclusion["inferred_judgement"] = "Check this control by hand to see how it behaves."
        elif v_status == "CONFIRMED":
            reproduction["state"] = "REPRODUCED"
            reproduction["action_attempted"] = "Clicked the control once and watched what the page did."
            reproduction["details"] = "Interaction was safely executed in the browser; lack of response or visual feedback was reproduced."
            conclusion["known_fact"] = "The control was clicked and the page showed no change and gave no feedback."
            conclusion["inferred_judgement"] = "Visitors are likely to read the control as broken and click it again."
        else:
            reproduction["state"] = "OBSERVED"
            reproduction["action_attempted"] = "Inspected how the control is presented on the page."
            reproduction["details"] = "Interactive control presentation was evaluated in the page structure."
            conclusion["known_fact"] = "The element looks clickable, but its behaviour when clicked was not tested."
            conclusion["inferred_judgement"] = "Visitors will expect it to respond when they click it."
        conclusion["strength"] = strength
        return reproduction, conclusion

    # 5. AI / Visual / UX Findings
    if is_ai or src in ("AI", "GEMINI", "GROQ", "OPENAI", "ANTHROPIC"):
        if has_visual_evidence:
            reproduction["state"] = "SUPPORTED"
            reproduction["action_attempted"] = "Looked at the rendered page screenshot alongside the measured layout."
            reproduction["details"] = "Finding is supported by multimodal visual analysis of the rendered page screenshot."
            conclusion["known_fact"] = ("The element was found on the page, and the rendered screenshot was part of "
                                        "the evidence used to judge how it looks.")
            conclusion["inferred_judgement"] = ("How strongly this reads on screen is a design judgement: the browser "
                                                "can confirm what is there, not whether it draws the eye.")
        else:
            reproduction["state"] = "UNVERIFIED"
            reproduction["action_attempted"] = "Inspected the page structure without a rendered screenshot to compare against."
            reproduction["details"] = "Finding was proposed from structural analysis without visual screenshot confirmation."
            conclusion["known_fact"] = "The element is present in the page, but how it actually looks on screen was not checked."
            conclusion["inferred_judgement"] = ("Without the rendered page, this stays a suggestion rather than "
                                                "something AURA can stand behind.")
        conclusion["strength"] = strength
        return reproduction, conclusion

    conclusion["strength"] = strength
    return reproduction, conclusion


# The six evidence kinds a finding can genuinely rest on. The checklist shown next to a finding is built
# from THAT finding's own provenance, never from everything the scan happened to collect.
EVIDENCE_KINDS = [
    ("Page structure", "STRUCTURAL"),
    ("Visual screenshot", "VISUAL"),
    ("Accessibility information", "ACCESSIBILITY"),
    ("Runtime telemetry", "RUNTIME"),
    ("Layout geometry", "RESPONSIVE"),
    ("Interactive behaviour", "BEHAVIORAL"),
]


def finding_evidence_checklist(evidence_types: List[str]) -> List[Dict[str, Any]]:
    """Only the evidence kinds that actually support this finding are listed as present."""
    present = {str(t).upper() for t in evidence_types or []}
    return [{"name": name, "present": tag in present} for name, tag in EVIDENCE_KINDS]


def generate_evidence_summary(
    observation: str,
    evidence_types: List[str],
    evidence_sources: List[str],
    reproduction: Dict[str, Any],
    conclusion: Dict[str, Any],
    verification_status: str,
    verification_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Creates the structured 'Why AURA reported this' evidence block.
    Answers what was observed, what evidence supports it, how it was verified,
    and what is known vs inferred.
    """
    checklist = finding_evidence_checklist(evidence_types)
    return {
        "observation": observation,
        # Finding-level, not audit-level: an item is present only when this finding actually rests on it.
        # There is deliberately no default entry — a finding with no recorded evidence shows an empty list
        # rather than claiming page structure it never used.
        "checklist": checklist,
        "evaluated_sources": [item["name"] for item in checklist if item["present"]],
        "verification": {
            "status": verification_status,
            "score": verification_score,
            "action": reproduction.get("action_attempted"),
            "safety_boundary": reproduction.get("safety_boundary"),
        },
        "reproduction": {
            "state": reproduction.get("state"),
            "action_attempted": reproduction.get("action_attempted"),
            "safety_boundary": reproduction.get("safety_boundary"),
            "details": reproduction.get("details"),
        },
        "conclusion": {
            "strength": conclusion.get("strength"),
            "known_fact": conclusion.get("known_fact"),
            "inferred_judgement": conclusion.get("inferred_judgement"),
        }
    }


# -----------------------------------------------------------------------------

# Rule families. When a rule has no entry of its own, its family still produces a SPECIFIC explanation
# instead of a generic one: each family says what is wrong, what it costs the reader, and what to change.
# Format: (matcher, title, summary, why_it_matters, what_to_do)
RULE_FAMILIES = [
    ("aria", "Some controls provide incorrect accessibility information",
     "Some controls are marked in a way that doesn't match how they actually work.",
     "Screen readers may describe these controls incorrectly, or skip them altogether.",
     "Correct the accessibility information so it matches what the control really is and does."),
    ("role", "Some controls use an accessibility role that doesn't fit",
     "Some elements claim to be a kind of control they are not.",
     "Screen readers announce the wrong kind of control, so people expect it to behave differently than it does.",
     "Use the role that matches the control, or use the standard HTML element for it."),
    ("landmark", "Some content isn't assigned to a page section",
     "Some content on this page is not assigned to a page section that screen readers can jump to.",
     "People who move through a page section by section cannot jump straight to that content.",
     "Assign the content to a clear page section."),
    ("region", "Some content isn't assigned to a page section",
     "Some content on this page is not assigned to a page section that screen readers can jump to.",
     "People who move through a page section by section cannot jump straight to that content.",
     "Assign the content to a clear page section."),
    ("heading", "The heading structure is incomplete",
     "The page headings do not form a complete, ordered outline of the content.",
     "People who navigate by headings get an outline that does not match what is on the page.",
     "Give the page an ordered set of headings that follows the structure of the content."),
    ("list", "List items are not grouped into a list",
     "Items that read as a list are not grouped inside a list.",
     "Screen readers cannot announce how many items there are or which one is current.",
     "Group the items inside a single list."),
    ("label", "Some controls are missing a clear label",
     "Some controls have no visible label explaining what they are for.",
     "People cannot tell what to enter or what the control does before they use it.",
     "Add a clear, visible label next to each control."),
    ("contrast", "Text is difficult to read against its background",
     "The text colour and its background are too close together to read comfortably.",
     "Low contrast makes text harder to read, especially in bright light or for people with reduced vision.",
     "Darken the text or lighten the background until the words read clearly."),
    ("link", "Some links don't tell users where they go",
     "Some links carry no text that describes their destination.",
     "Someone using a screen reader hears a link without enough context to know what it opens.",
     "Give each link text that names where it leads."),
    ("button", "Some buttons don't clearly explain what they do",
     "Some buttons carry no readable text describing their action.",
     "People may not know what will happen when they press the button.",
     "Give each button text that names the action it performs."),
    ("image", "Some images are missing a description",
     "Images that carry information have no text description.",
     "People who cannot see the image miss whatever information it carries.",
     "Add a short description to images that carry information, or mark decorative ones as decorative."),
    ("frame", "An embedded frame has no description",
     "An embedded frame on this page carries no description of what it contains.",
     "People using a screen reader cannot tell what the embedded content is before entering it.",
     "Give the embedded frame a short title describing its contents."),
    ("form", "A form control is set up in a way that confuses its label",
     "A form control is associated with its label in a way that does not resolve to one clear name.",
     "People may hear a different name than the one printed on the page.",
     "Associate each form control with exactly one clear label."),
    ("focus", "Keyboard focus reaches something it cannot operate",
     "Keyboard focus stops on an item that does not behave like a control.",
     "Keyboard users land on something without learning what it is or how to use it.",
     "Either make the item a real control or take it out of the keyboard order."),
    ("scroll", "A scrollable area cannot be reached with the keyboard",
     "An area that scrolls cannot be focused with the keyboard.",
     "Keyboard-only users cannot scroll it, so they never see the content below the fold.",
     "Let the scrolling area receive keyboard focus and give it a name."),
    ("viewport", "The page prevents zooming",
     "The page is set up to block or limit zooming.",
     "People who need larger text cannot enlarge the page to read it.",
     "Allow the page to be zoomed freely."),
    ("duplicate", "Identifier names are repeated on the page",
     "More than one element on the page uses the same internal identifier.",
     "Labels and scripts can attach to the wrong element, so the page behaves unpredictably.",
     "Make every identifier on the page unique."),
    ("title", "The page has no descriptive title",
     "The title shown in the browser tab is missing or says nothing about the page.",
     "People with several tabs open cannot tell which one this is.",
     "Give the page a title that names its content and the site."),
    ("lang", "The page does not say what language it is in",
     "The page does not declare the language its content is written in.",
     "Speech tools read the page with the wrong pronunciation rules.",
     "Declare the language of the page content."),
]

# Wording that says nothing specific about this finding. It must never reach an active human finding.
BANNED_GENERIC_PHRASES = (
    "this condition may make it more difficult for some people to view or use the page",
    "impacts overall visual hierarchy and user interaction flow",
    "users may have difficulty",
    "people may struggle",
    "may affect usability or accessibility for some visitors",
    "visitors may experience difficulty",
    "clear layout and distinct controls help visitors complete tasks quickly without confusion",
    "users may overlook or misinterpret this element due to unclear visual cues",
)

JARGON_PATTERN = re.compile(
    r"\b(axe-core|wcag|aria|dom|css|landmark|affordance|semantic|assistive technology|cognitive load|"
    r"prominence|materiality|selector|rule id|viewport meta|tabindex)\b", re.I)


def contains_banned_generic(text: Optional[str]) -> bool:
    low = (text or "").strip().lower()
    return any(p in low for p in BANNED_GENERIC_PHRASES)


def sanitize_human_presentation(rule_key: str, raw_title: str, raw_desc: str, raw_why: Optional[str],
                                raw_rec: Optional[str], category: str) -> Tuple[str, str, str, str, str]:
    """
    Builds the human view for a rule that has no entry of its own.

    Returns (title, summary, why_it_matters, what_to_do, specificity) where specificity is SPECIFIC when a
    rule family produced real wording, and GENERIC when AURA could only fall back to filler. A GENERIC
    finding is never surfaced as an active human finding: its evidence is preserved in the technical view.
    """
    cat = (category or "UI").upper()
    # Hyphenated, so a whole-word family match works on "aria_allowed_attr" as well as "aria-allowed-attr".
    r = (rule_key or "").lower().replace("_", "-")
    haystack = f"{r} {raw_title} {raw_desc}".lower()

    # A rule family gives a specific explanation even for a rule AURA has no dedicated entry for. The match
    # is on whole words: "conforms" must not be read as the "form" family.
    for token, title, summary, why, rec in RULE_FAMILIES:
        pattern = re.compile(rf"\b{re.escape(token)}s?\b", re.I)
        if pattern.search(r) or pattern.search(haystack):
            return title, summary, why, rec, "SPECIFIC"

    # The detector's own wording, if it is human and free of jargon, is more specific than any fallback.
    clean_title = raw_title.split("]: ")[-1] if raw_title.startswith("WCAG [") else raw_title
    clean_title = re.sub(r"^Ensures?\s+", "", clean_title).strip()
    usable_title = bool(clean_title) and not JARGON_PATTERN.search(clean_title)
    usable_why = bool(raw_why) and not JARGON_PATTERN.search(raw_why) and not contains_banned_generic(raw_why)
    usable_rec = bool(raw_rec) and not JARGON_PATTERN.search(raw_rec) and not contains_banned_generic(raw_rec)
    usable_desc = bool(raw_desc) and not JARGON_PATTERN.search(raw_desc) and raw_desc.strip() != clean_title.strip()

    if usable_title and usable_why and usable_rec:
        title = clean_title[0].upper() + clean_title[1:]
        summary = raw_desc.strip() if usable_desc else f"{title}."
        return title, summary, raw_why.strip(), raw_rec.strip(), "SPECIFIC"

    # Nothing specific could be produced. The finding keeps its technical record and is held back from the
    # human list rather than shown with filler wording.
    title = (clean_title[0].upper() + clean_title[1:]) if clean_title else "Unclassified page condition"
    summary = raw_desc.strip() or "AURA recorded this condition but could not describe it in plain language."
    why = "AURA could not work out a specific consequence for this condition from the evidence it collected."
    rec = "Open the technical details to see exactly what was recorded for this element."
    return title, summary, why, rec, "GENERIC"


EVIDENCE_PHRASE = {
    "VISUAL": "the page screenshot",
    "STRUCTURAL": "the page structure",
    "ACCESSIBILITY": "the page's accessibility information",
    "RUNTIME": "what the browser logged while the page ran",
    "RESPONSIVE": "the measured layout",
    "BEHAVIORAL": "a controlled interaction with the control",
}


def _describe_observation(detector: str, is_ai: bool, location: str, evidence_types: List[str],
                          raw_observation: str, affected: int) -> str:
    """
    What AURA actually looked at, and where. This is the audit trail entry, deliberately different from
    the human "What is wrong" sentence: repeating that sentence here is what made the card read like it
    was saying the same thing four times.
    """
    looked_at = [EVIDENCE_PHRASE[t] for t in evidence_types if t in EVIDENCE_PHRASE]
    if len(looked_at) > 1:
        sources = ", ".join(looked_at[:-1]) + " and " + looked_at[-1]
    else:
        sources = looked_at[0] if looked_at else "the page"

    where = location[0].lower() + location[1:] if location else "this page"
    # Never the detector's name: that belongs in Technical details, not in the default view.
    if is_ai:
        who = "A suggestion from the AI was checked against"
    elif "runtime" in (detector or "").lower() or "console" in (detector or "").lower():
        who = "The browser's own log recorded this while AURA watched"
    else:
        who = "AURA's own checks found this in"
    count = f" It applies to {affected} elements." if affected > 1 else ""
    detail = ""
    note = (raw_observation or "").strip()
    if note and len(note) < 220:
        detail = f" Recorded at the time: {note}"
    return f"{who} {sources}, at {where}.{count}{detail}"


TAG_NAMES = {"button": "button", "a": "link", "input": "input field", "select": "dropdown",
             "textarea": "text box", "img": "image", "svg": "graphic", "ul": "list", "ol": "list",
             "li": "list item", "nav": "navigation", "form": "form", "table": "table", "dl": "list",
             "h1": "heading", "h2": "heading", "h3": "heading", "h4": "heading", "section": "section",
             "header": "header", "footer": "footer", "aside": "sidebar", "p": "paragraph", "div": "block"}


def _element_phrase(text: Optional[str], tag: Optional[str], role: Optional[str], location: str) -> Optional[str]:
    """A concrete noun phrase for the element AURA actually matched, or None when it knows too little."""
    label = (text or "").strip()
    tag_low = (tag or "").strip().lower()
    # A container's concatenated text is not a name. Quoting half a header as if it were a label reads
    # like noise, so only short text, or text on an element that really has a name, is used.
    if label and tag_low in ("div", "span", "section", "header", "footer", "main", "aside", "nav", "li", "p") \
            and len(label) > 32:
        label = ""
    if len(label) > 48:
        label = label[:47] + "…"
    kind = TAG_NAMES.get(tag_low) or (role or "").strip().lower() or None
    where = (location or "").strip()
    generic_where = (not where or where.lower().startswith(("one element", "specific element", "whole page",
                                                            "the page as a whole")))
    # Only a location that reads as a PLACE is worth appending. "Search control" is another name for the
    # element, and gluing it on produced 'the input field "Work email" ("Work email" input)'.
    tail = "" if generic_where else where[0].lower() + where[1:]
    is_place = bool(tail) and (" in the " in f" {tail} " or tail.startswith(("in ", "inside ", "near ")))

    if label and kind:
        phrase = f'the {kind} "{label}"'
    elif label:
        phrase = f'"{label}"'
    elif kind:
        phrase = f"the {kind}"
    else:
        phrase = None

    if not is_place:
        return phrase
    # The location often already quotes the element's text; appending both says it twice.
    if label and label[:20].lower() in tail.lower():
        return tail if tail.startswith(("a ", "an ", "the ")) else f"the {tail}"
    if phrase is None or not label or (kind and kind in tail.lower()):
        # With no name of its own, the location already describes the element as well as anything can;
        # prefixing it with the tag ("the block <location>") only makes it longer.
        return tail if tail.startswith(("a ", "an ", "the ")) else f"the {tail}"
    return f"{phrase} {tail.split(' ', 2)[-1] if tail.startswith(('an element ', 'a element ', 'element ')) else tail}"


def _specifics(text: Optional[str], tag: Optional[str], role: Optional[str], location: str, count: int) -> str:
    """
    One factual sentence naming what this rule hit ON THIS PAGE.

    Without it every finding of the same rule reads identically on every site, which is what made the
    explanations feel canned. With it, the general statement is followed by the concrete case.
    """
    phrase = _element_phrase(text, tag, role, location)
    if count > 1:
        if phrase:
            return f"On this page {count} elements are affected, starting with {phrase}."
        return f"On this page {count} elements are affected; they are listed in Technical details."
    # With one element and no name or place for it, this sentence would add nothing to the rule's own
    # wording, so it is left out rather than padded.
    has_identity = bool((text or "").strip()) or (phrase or "") != (f"the {TAG_NAMES.get((tag or '').lower())}" )
    if phrase and has_identity:
        return f"On this page that is {phrase}."
    return ""


def is_ai_source(source: str) -> bool:
    up = (source or "").upper()
    return up in ("AI", "GEMINI", "GROQ", "OPENAI", "ANTHROPIC") or "AI" in up


def _first_sentence(text: Optional[str], limit: int = 150) -> str:
    """The opening sentence, for the card. Long explanations belong in Explain, not in the list."""
    body = re.sub(r"\s+", " ", (text or "").strip())
    if not body:
        return ""
    match = re.search(r"(?<=[.!?])\s", body)
    first = body[:match.start() + 1] if match else body
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


def _same_sentence(a: Optional[str], b: Optional[str]) -> bool:
    """True when two human fields say the same thing, ignoring case, spacing and trailing punctuation."""
    norm = lambda t: re.sub(r"[\s.!?]+$", "", re.sub(r"\s+", " ", (t or "").strip().lower()))
    x, y = norm(a), norm(b)
    return bool(x) and x == y


def _distinct_human_fields(title: str, summary: str, why: str, rec: str,
                           conclusion: Dict[str, Any], location: str) -> Tuple[str, str, str, str]:
    """
    Keeps the four human fields in their own roles.

    TITLE says what is wrong, SUMMARY gives the one-sentence context, WHY IT MATTERS gives the practical
    consequence, WHAT TO DO gives the action. When two of them arrive identical, the later one is rebuilt
    from a different part of the record instead of repeating the earlier one.
    """
    if _same_sentence(summary, title):
        summary = conclusion.get("known_fact") or f"{title} on {location}."
    if _same_sentence(why, summary) or _same_sentence(why, title):
        why = conclusion.get("inferred_judgement") or why
    if _same_sentence(rec, why) or _same_sentence(rec, summary) or _same_sentence(rec, title):
        rec = f"Change {location.lower()} so that this no longer applies, then scan the page again to confirm."
    return title, summary, why, rec


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def interpret_finding(finding: Any) -> Dict[str, Any]:
    """
    Produces the complete human-readable interpretation layer for one canonical finding.
    Strictly separates user-facing content (human) from engineering facts (technical).
    """
    raw_rule = _get_val(finding, "raw_rule") or _get_val(finding, "rule") or ""
    norm_rule = _get_val(finding, "normalized_rule") or raw_rule
    rule_key = norm_rule.strip().lower()
    rule_key = CANONICAL_ALIASES.get(rule_key, rule_key)
    rule_key_hyphen = rule_key.replace("_", "-")
    rule_key_under = rule_key.replace("-", "_")

    source = _clean_str(_get_val(finding, "source") or _get_val(finding, "detector") or "Detector")
    is_ai = is_ai_source(source)
    category = _clean_str(_get_val(finding, "category", "UI"))
    severity = _clean_str(_get_val(finding, "severity", "medium")).lower()
    v_status = _clean_str(_get_val(finding, "verification_status", "CONFIRMED")).upper()

    # Look up the human dictionary under either spelling, and keep the spelling that matched: everything
    # downstream (the trust layer, the rule families) compares against this key.
    tup = None
    for k in (rule_key, rule_key_hyphen, rule_key_under):
        for table in (AXE_INTERPRETATIONS, AI_INTERPRETATIONS, RUNTIME_INTERPRETATIONS):
            if k in table:
                tup = table[k]
                rule_key = k
                break
        if tup:
            break

    raw_title = str(_get_val(finding, "title", "") or "")
    raw_desc = str(_get_val(finding, "description", "") or "")
    raw_why = _get_val(finding, "why_it_matters")
    raw_rec = _get_val(finding, "recommendation")
    raw_observation = str(_get_val(finding, "observation", "") or "")

    if tup:
        title, summary, why, rec = tup
        specificity = "SPECIFIC"
    else:
        title, summary, why, rec, specificity = sanitize_human_presentation(rule_key, raw_title, raw_desc, raw_why, raw_rec, category)

    # An AI candidate arrives with wording about THIS page ("Icon-only buttons in the header carry no
    # visible text"). The rule template is a generic stand-in for it. Where the model's own sentence is
    # readable and free of jargon it is kept, because it says something the template never can.
    if is_ai_source(source):
        model_said = (raw_desc or "").strip() or (raw_observation or "").strip()
        if (model_said and len(model_said) > 25 and not JARGON_PATTERN.search(model_said)
                and not contains_banned_generic(model_said)):
            summary = model_said
        model_title = (raw_title or "").strip()
        if model_title and len(model_title) <= 90 and not JARGON_PATTERN.search(model_title):
            title = model_title[0].upper() + model_title[1:]

    # Extract target metadata
    ae = _get_val(finding, "affected_element")
    target_dict = _get_val(finding, "target") if isinstance(_get_val(finding, "target"), dict) else {}
    selector = (_get_val(ae, "selector") if ae else None) or target_dict.get("selector") or _get_val(finding, "raw_target", "") or ""
    selectors = (_get_val(ae, "target_list") if ae else None) or target_dict.get("selectors") or ([selector] if selector else [])
    text = (_get_val(ae, "text") if ae else None) or target_dict.get("text") or _get_val(finding, "target_text")
    tag = (_get_val(ae, "tag") if ae else None) or target_dict.get("tag")
    role = (_get_val(ae, "role") if ae else None) or target_dict.get("role")
    bbox = (_get_val(ae, "bounding_box") if ae else None) or target_dict.get("bounding_box")

    # Human location
    location_desc = describe_location(
        selector=selector,
        text=text,
        tag=tag,
        role=role,
        bounding_box=bbox,
        page_level=selector.strip().lower() in ("body", "html", "page") if selector else False
    )

    # Status & Confidence
    human_status = map_human_status(v_status, is_ai_hypothesis=is_ai)
    raw_conf = _get_val(finding, "confidence")
    if is_ai and _get_val(finding, "ai_confidence") is not None:
        raw_conf = _get_val(finding, "ai_confidence")
    confidence_label = map_confidence_label(raw_conf)


    # Evidence provenance tracking
    evidence_obj = _get_val(finding, "evidence")
    flags = _get_val(evidence_obj, "flags", {}) if evidence_obj else {}
    ev_sources = list(_get_val(evidence_obj, "sources", None) or [])
    ev_types = list(_get_val(evidence_obj, "types", None) or [])

    # Finding-level evidence provenance.
    # Only what actually contributed to THIS finding is listed. The category a finding was filed under, or
    # the fact that a selector string exists, is not evidence: the scan collects screenshots, DOM,
    # accessibility, runtime and interaction data for the whole page, and claiming all of it for every
    # finding is what made the old checklist misleading.
    provenance_tags: List[str] = []
    lower_sources = [str(s).lower().replace("_", " ") for s in ev_sources]
    upper_types = [str(t).upper() for t in ev_types]

    if flags.get("screenshot", False) or "VISUAL" in upper_types or any("screenshot" in s for s in lower_sources) \
            or bool(_get_val(evidence_obj, "has_visual_evidence")):
        provenance_tags.append("VISUAL")

    if flags.get("dom", False) or "DOM" in upper_types or "STRUCTURAL" in upper_types \
            or any(("dom" in s or "computed style" in s or "page structure" in s) for s in lower_sources):
        provenance_tags.append("STRUCTURAL")

    if flags.get("accessibility", False) or "ACCESSIBILITY" in upper_types or "axe" in source.lower() \
            or any("axe" in s or "wcag" in s for s in lower_sources):
        provenance_tags.append("ACCESSIBILITY")

    if flags.get("runtime", False) or "RUNTIME" in upper_types or "runtime" in source.lower() \
            or "console" in source.lower() or any(("telemetry" in s or "console" in s) for s in lower_sources):
        provenance_tags.append("RUNTIME")

    if flags.get("interaction", False) or "BEHAVIORAL" in upper_types \
            or any("interaction" in s for s in lower_sources):
        provenance_tags.append("BEHAVIORAL")

    if any(flags.get(k, False) for k in ("target_overflow", "target_clipped", "document_overflow", "layout_overlap")) \
            or "RESPONSIVE" in upper_types:
        provenance_tags.append("RESPONSIVE")

    has_screenshot = "VISUAL" in provenance_tags

    # Strict Structured Schema Separation (Phase 4B)
    # Phase 5: Reproduction, Conclusion & Evidence Trust Layer
    v_score = _get_val(finding, "verification_score")
    reproduction, conclusion = determine_reproduction_and_trust(
        rule_key=rule_key,
        category=category,
        source=source,
        v_status=v_status,
        flags=flags,
        is_ai=is_ai,
        selector=selector,
        raw_conf=raw_conf,
        verification_score=v_score,
        tag=tag,
        has_visual_evidence=has_screenshot,
    )

    # "What AURA observed" must describe the OBSERVATION, not repeat "What is wrong". It names what was
    # looked at and what was found there, which is a different fact from the human summary above it.
    observation = _describe_observation(detector=source, is_ai=is_ai, location=location_desc,
                                        evidence_types=provenance_tags, raw_observation=raw_observation,
                                        affected=len(selectors) if selectors else 1)

    evidence_summary = generate_evidence_summary(
        observation=observation,
        evidence_types=provenance_tags,
        evidence_sources=ev_sources or [source],
        reproduction=reproduction,
        conclusion=conclusion,
        verification_status=v_status,
        verification_score=v_score,
    )

    evidence_dict = {
        "types": provenance_tags,
        "sources": ev_sources or [source],
        "flags": flags,
        "has_visual_evidence": has_screenshot,
    }

    # Name what this rule actually hit on this page, so two sites never produce the same paragraph.
    specifics = _specifics(text, tag, role, location_desc, len(selectors) if selectors else 1)
    if specifics and specifics.lower() not in summary.lower():
        summary = f"{summary} {specifics}"

    # The card carries one short sentence. The full story belongs to Explain, so the long form is kept
    # separately rather than crammed into the list.
    short_summary = _first_sentence(summary, limit=150)

    # Each human field answers a different question. Where two of them collapsed into the same sentence,
    # the weaker one is rebuilt from a different part of the record rather than repeated.
    title, summary, why, rec = _distinct_human_fields(title, summary, why, rec, conclusion, location_desc)

    # The conclusion's inferred impact is an interpretation of the evidence. When it lands on the same
    # sentence as "Why it matters", only one of them is worth showing, and the card shows that one.
    if _same_sentence(conclusion.get("inferred_judgement"), why):
        conclusion = {**conclusion, "inferred_judgement": None}

    # "What does this mean?" used to be the known fact and the inferred impact glued together, which is
    # exactly what the Conclusion block below it already shows. A card that says the same thing twice is
    # worse than a card that says it once, so this is emitted only when it is genuinely something else.
    # Nothing currently produces such a line, so in practice the panel hides the box.
    what_does_this_mean = None

    # Strict Structured Schema Separation (Phase 4B & Phase 5)
    human = {
        "title": title,
        "summary": summary,
        "short_summary": short_summary,
        "why_it_matters": why,
        "what_to_do": rec,
        "recommendation": rec,
        "location": location_desc,
        "status_label": human_status,
        "confidence_label": confidence_label,
        "what_does_this_mean": what_does_this_mean,
        "affected_count": len(selectors) if selectors else 1,
        "category": category,
        "severity": severity,
        "why_aura_reported_this": evidence_summary,
        "reproduction_state": reproduction["state"],
        "conclusion_strength": conclusion["strength"],
        "known_fact": conclusion["known_fact"],
        "inferred_judgement": conclusion["inferred_judgement"],
        "explanation_specificity": specificity,
    }

    raw_wcag = _get_val(finding, "wcag") or _get_val(finding, "wcag_rule")
    wcag_list = [raw_wcag] if raw_wcag else ([f"WCAG reference for {raw_rule}"] if "axe" in source.lower() else [])

    technical = {
        "rule_id": raw_rule,
        "raw_rule_id": raw_rule,
        "rule": raw_rule,
        "raw_rule": raw_rule,
        "normalized_rule": norm_rule,
        "detector": _get_val(finding, "detector", source),
        "wcag": raw_wcag or (f"WCAG reference for {raw_rule}" if "axe" in source.lower() else None),
        "wcag_criteria": wcag_list,
        "selector": selector,
        "dom_path": _get_val(finding, "dom_path", selector),
        "target_metadata": {
            "tag": tag,
            "role": role,
            "text": text,
            "bounding_box": bbox,
        },
        "verification": v_status,
        "verification_status": v_status,
        "verification_score": v_score,
        "verification_note": _get_val(finding, "rejection_reason"),
        "confidence": raw_conf,
        "confidence_score": raw_conf,
        "materiality": _get_val(finding, "materiality") or _get_val(finding, "materiality_score"),
        "materiality_score": _get_val(finding, "materiality_score") or _get_val(finding, "materiality"),
        "ai_confidence": raw_conf,
        "ai_contribution": _get_val(finding, "ai_contribution_type"),
        "ai_contribution_type": _get_val(finding, "ai_contribution_type"),
        "ai_contribution_score": _get_val(finding, "ai_contribution_score"),
        "evidence": list(_get_val(evidence_obj, "sources", None) or [source]),
        "evidence_sources": list(_get_val(evidence_obj, "sources", None) or [source]),
        "evidence_provenance": provenance_tags,
        "evidence_flags": flags,
        "reproduction": reproduction,
        "conclusion": conclusion,
        "why_aura_reported_this": evidence_summary,
        "raw_message": raw_desc,
        "raw_title": raw_title,
        "raw_description": raw_desc,
        "technical_recommendation": _get_val(finding, "recommendation") or rec,
        "audit_id": _get_val(finding, "audit_id") or _get_val(finding, "id", ""),
        "finding_id": _get_val(finding, "id", ""),
        "affected_targets": selectors,
        "selectors": selectors,
        "affected_count": len(selectors) if selectors else 1,
        "source": source,
        "sources": list(_get_val(finding, "sources", None) or [source]),
        "why_ai_needed": _get_val(finding, "why_ai_needed"),
        "conclusion_strength": conclusion["strength"],
        "explanation_specificity": specificity,
    }

    return {
        # Strict Schemas
        "human": human,
        "technical": technical,
        "technical_details": technical,

        # Phase 5 Trust Layer
        "evidence": evidence_dict,
        "reproduction": reproduction,
        "conclusion": conclusion,
        "why_aura_reported_this": evidence_summary,

        # Top-level human properties (for backward compatibility)
        "title": title,
        "category": category,
        "severity": severity,
        "status": human_status,
        "status_label": human_status,
        "summary": summary,
        "short_summary": short_summary,
        "why_it_matters": why,
        "recommendation": rec,
        "location": location_desc,
        "location_description": location_desc,
        "affected_count": len(selectors) if selectors else 1,
        "what_does_this_mean": what_does_this_mean,
        "confidence_label": confidence_label,
        "detector": source,
        "explanation_specificity": specificity,
        "conclusion_strength": conclusion["strength"],
    }


# -----------------------------------------------------------------------------
# 6. Deterministic rule review and grouping (presentation layer only)
# -----------------------------------------------------------------------------
#
# Every deterministic rule AURA reports is classified here. The goal is not more detections, it is better
# ones. Nothing below changes detection, scoring or the benchmark: this table only decides how a rule is
# presented to a person.
#
#   KEEP              a standalone user-facing finding in its own right
#   GROUP:<key>       shown together with related rules under one user-meaning headline
#   TECHNICAL_ONLY    kept in the technical record, not shown as a standalone human finding
#
DETERMINISTIC_RULE_POLICY: Dict[str, str] = {
    # Read clearly on their own
    "color-contrast": "KEEP",
    "image-alt": "KEEP",
    "svg-img-alt": "KEEP",
    "link-name": "KEEP",
    "button-name": "KEEP",
    "select-name": "KEEP",
    "label": "KEEP",
    "label-title-only": "KEEP",
    "form-field-multiple-labels": "KEEP",
    "heading-order": "KEEP",
    "page-has-heading-one": "KEEP",
    "empty-heading": "KEEP",
    "landmark-one-main": "KEEP",
    "document-title": "KEEP",
    "html-has-lang": "KEEP",
    "meta-viewport": "KEEP",
    "target-size": "KEEP",
    "bypass": "KEEP",
    "frame-title": "KEEP",
    "nested-interactive": "KEEP",
    "scrollable-region-focusable": "KEEP",
    "aria-hidden-focus": "KEEP",          # a keyboard trap, not an attribute mismatch
    "image-redundant-alt": "KEEP",
    "tabindex": "KEEP",
    "focus-order-semantics": "KEEP",

    # One user meaning: "this control is described wrongly"
    "aria-allowed-attr": "GROUP:aria-attribute-issues",
    "aria-prohibited-attr": "GROUP:aria-attribute-issues",
    "aria-required-attr": "GROUP:aria-attribute-issues",
    "aria-required-children": "GROUP:aria-attribute-issues",
    "aria-required-parent": "GROUP:aria-attribute-issues",
    "aria-valid-attr": "GROUP:aria-attribute-issues",
    "aria-valid-attr-value": "GROUP:aria-attribute-issues",
    "aria-roles": "GROUP:aria-attribute-issues",
    "aria-command-name": "GROUP:aria-attribute-issues",
    "aria-toggle-field-name": "GROUP:aria-attribute-issues",

    # One user meaning: "these items should read as a list"
    "list": "GROUP:list-structure-issues",
    "listitem": "GROUP:list-structure-issues",
    "dlitem": "GROUP:list-structure-issues",
    "definition-list": "GROUP:list-structure-issues",

    # One user meaning: "the same name is used twice"
    "duplicate-id": "GROUP:duplicate-identifier-issues",
    "duplicate-id-aria": "GROUP:duplicate-identifier-issues",
    "duplicate-id-active": "GROUP:duplicate-identifier-issues",

    # One user meaning: "content is not inside a clear page section"
    "region": "GROUP:page-section-issues",
    "landmark-unique": "GROUP:page-section-issues",
    "landmark-no-duplicate-contentinfo": "GROUP:page-section-issues",
    "landmark-no-duplicate-banner": "GROUP:page-section-issues",
    "landmark-complementary-is-top-level": "GROUP:page-section-issues",
}

# The human headline each group carries. {n} is the number of affected elements.
GROUP_PRESENTATION: Dict[str, Tuple[str, str, str, str]] = {
    "aria-attribute-issues": (
        "Some controls provide incorrect accessibility information",
        "{n} controls are marked in a way that doesn't match how they work.",
        "Screen readers may misunderstand these controls.",
        "Correct the accessibility information so it matches each control's purpose."),
    "list-structure-issues": (
        "Some lists are not grouped correctly",
        "{n} items that read as a list are not grouped inside a proper list.",
        "Screen readers cannot announce how many items there are or which one is current.",
        "Group the related items inside a single list."),
    "duplicate-identifier-issues": (
        "Identifier names are repeated on the page",
        "{n} elements share an internal identifier with another element.",
        "Labels and scripts can attach to the wrong element, so the page behaves unpredictably.",
        "Make every identifier on the page unique."),
    "page-section-issues": (
        "Some content isn't assigned to a clear page section",
        "{n} parts of this page are not assigned to a page section that screen readers can jump to.",
        "People who move through a page section by section cannot jump straight to that content.",
        "Assign each part of the page to a clear, distinctly named section."),
    # Repeated runtime events. Two failed requests shown as two identical cards are indistinguishable to a
    # reader and produce the same answer to every question; one card that counts them is honest and useful.
    "application_network_failure": (
        "Some things the page asked for didn't load",
        "{n} requests this page made came back with an error instead of the content they asked for.",
        "Whatever those requests were for — data, images, parts of the layout — may be missing or out of date.",
        "Check that each address the page requests is reachable and returns the expected response."),
    "application_console_error": (
        "Scripts on this page stopped with errors",
        "{n} scripts hit an error they did not handle while the page was loading.",
        "Anything those scripts were responsible for may quietly not work.",
        "Open the browser console, read the errors that were logged, and fix the code that raised them."),
    "application_runtime_exception": (
        "Errors interrupted parts of the page",
        "{n} errors were raised while the page was running and nothing caught them.",
        "Controls that depend on that code may stop responding, or content may never appear.",
        "Find where each error is raised and handle it, so the rest of the page keeps working."),
}

# Runtime events that are worth counting rather than listing one by one.
GROUPABLE_RUNTIME_RULES = {"application_network_failure", "application_console_error",
                           "application_runtime_exception"}


def rule_policy(rule: str) -> str:
    """
    The presentation policy for a deterministic rule ("KEEP" when AURA has not classified it).

    The same rule reaches this function as "aria-allowed-attr" from axe and as "aria_allowed_attr" once it
    has been normalized, so both spellings are accepted. Rules of a known family that are not listed
    individually (axe adds new ones) still land in their family's group rather than becoming a card of
    their own with the same headline as its siblings.
    """
    raw = (rule or "").strip().lower()
    for key in (raw, raw.replace("_", "-"), raw.replace("-", "_")):
        if key in DETERMINISTIC_RULE_POLICY:
            return DETERMINISTIC_RULE_POLICY[key]
    hyphen = raw.replace("_", "-")
    if hyphen.startswith("aria-"):
        return "GROUP:aria-attribute-issues"
    if hyphen.startswith("landmark-"):
        return "GROUP:page-section-issues"
    if hyphen.startswith("duplicate-id"):
        return "GROUP:duplicate-identifier-issues"
    return "KEEP"


def group_findings_for_presentation(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Groups repetitive deterministic findings for presentation.

    Two kinds of grouping happen here:
      - repetition: 49 separate "region" violations become one card with 49 affected elements;
      - user meaning: related rules (the ARIA attribute family, the list family, ...) become one card,
        following DETERMINISTIC_RULE_POLICY. Unrelated rules are never merged just because both are
        accessibility rules.

    All raw evidence is preserved underneath: every underlying finding id, selector and rule stays in the
    technical block. Benchmark data is untouched — this runs in the view layer only.
    """
    if not findings:
        return []

    grouped: List[Dict[str, Any]] = []
    bucket_map: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}

    for f in findings:
        tech = f.get("technical", f.get("technical_details", {}))
        rule = _clean_str(tech.get("normalized_rule") or tech.get("rule_id") or f.get("rule") or f.get("normalized_rule") or f.get("title")).lower()
        cat = _clean_str(f.get("category", "")).lower()
        source = _clean_str(tech.get("source") or f.get("source", "")).lower()

        is_det = any(k in source for k in ("axe", "deterministic"))
        is_groupable_cat = any(k in cat for k in ("accessibility", "structure"))
        is_runtime_event = "runtime" in source and rule in GROUPABLE_RUNTIME_RULES
        if is_det and is_groupable_cat:
            policy = rule_policy(rule)
            group_rule = policy.split(":", 1)[1] if policy.startswith("GROUP:") else rule
            bucket_map.setdefault((group_rule, cat, source), []).append(f)
        elif is_runtime_event:
            bucket_map.setdefault((rule, cat, source), []).append(f)
        else:
            # AI candidates stay standalone: each is a separate hypothesis about a separate element.
            grouped.append(f)

    for (rule, cat, source), items in bucket_map.items():
        if len(items) == 1:
            grouped.append(items[0])
            continue

        primary = items[0].copy()
        all_ids = []
        all_elements = []
        all_rules = []

        for item in items:
            t = item.get("technical", item.get("technical_details", {}))
            all_ids.append(t.get("finding_id") or "")
            sel = t.get("selector") or ""
            loc = item.get("location_description") or (item.get("human", {}).get("location") if isinstance(item.get("human"), dict) else "")
            r = _clean_str(t.get("normalized_rule") or t.get("rule_id") or "")
            if r and r not in all_rules:
                all_rules.append(r)
            all_elements.append({
                "finding_id": t.get("finding_id"),
                "selector": sel,
                "location": loc,
                "rule": r,
            })

        total_affected = len(items)
        primary["affected_count"] = total_affected
        primary["affected_elements"] = all_elements

        base_title = primary.get("title") or (primary.get("human", {}) or {}).get("title") or "Accessibility condition"
        if rule in GROUP_PRESENTATION:
            g_title, g_summary, g_why, g_fix = GROUP_PRESENTATION[rule]
            primary["title"] = g_title
            primary["summary"] = g_summary.format(n=total_affected)
            primary["why_it_matters"] = g_why
            primary["recommendation"] = g_fix
        elif "contrast" in base_title.lower() or rule in ("color-contrast", "color_contrast"):
            primary["summary"] = f"{total_affected} text elements are hard to read against their background."
        elif "link" in base_title.lower() or rule == "link-name":
            primary["summary"] = f"{total_affected} links on this page don't say where they go."
        elif "button" in base_title.lower() or rule in ("button-name", "unlabelled_button"):
            primary["summary"] = f"{total_affected} buttons don't say what they do."
        elif "image" in base_title.lower() or rule in ("image-alt", "image_alt_missing"):
            primary["summary"] = f"{total_affected} images are missing a description."
        elif "label" in base_title.lower() or rule in ("label", "missing_label"):
            primary["summary"] = f"{total_affected} form fields are missing a visible label."
        elif "heading" in base_title.lower() or rule in ("heading-order", "empty-heading"):
            primary["summary"] = f"{total_affected} headings break the order of the page outline."
        elif rule == "target-size":
            primary["summary"] = f"{total_affected} controls are too small to tap comfortably."
        else:
            primary["summary"] = f"{total_affected} elements on this page are affected by the same condition."

        is_network_group = rule == "application_network_failure"
        primary["location_description"] = (f"{total_affected} requests this page made" if is_network_group
                                           else f"{total_affected} places on this page" if "runtime" in source
                                           else f"{total_affected} elements across the page")

        if "why_aura_reported_this" in primary and isinstance(primary["why_aura_reported_this"], dict):
            w_copy = primary["why_aura_reported_this"].copy()
            # Describe the observation, not the summary: setting them equal is how the grouped card
            # ended up saying the same sentence under "What is wrong" and "What AURA observed".
            kinds = ", ".join(sorted({r for r in all_rules})[:4]) if all_rules else ""
            w_copy["observation"] = (
                f"AURA found the same condition on {total_affected} separate elements during this scan"
                + (f", across {len(all_rules)} related checks." if len(all_rules) > 1 else ".")
                + (f" Every element and check is listed in Technical details." if kinds else ""))
            primary["why_aura_reported_this"] = w_copy

        if "human" in primary and isinstance(primary["human"], dict):
            h_copy = primary["human"].copy()
            h_copy["affected_count"] = total_affected
            h_copy["title"] = primary["title"]
            h_copy["summary"] = primary["summary"]
            h_copy["why_it_matters"] = primary.get("why_it_matters", h_copy.get("why_it_matters"))
            h_copy["what_to_do"] = primary.get("recommendation", h_copy.get("what_to_do"))
            h_copy["recommendation"] = h_copy["what_to_do"]
            h_copy["location"] = primary["location_description"]
            if "why_aura_reported_this" in primary:
                h_copy["why_aura_reported_this"] = primary["why_aura_reported_this"]
            primary["human"] = h_copy

        # A grouped card covers several elements, so it is an area-level finding: there is no single
        # element to highlight, and the panel offers per-element highlighting instead.
        target = dict(primary.get("target") or {})
        if target:
            if target.get("kind") == "element":
                # A grouped card still points at real elements. Highlight marks every one that resolves
                # uniquely and reports the ones it could not place, rather than refusing outright.
                target["kind"] = "group"
                target["selectors"] = [e["selector"] for e in all_elements if e.get("selector")][:20]
                target["highlightable"] = bool(target["selectors"])
            else:
                target["highlightable"] = False
            target["count"] = total_affected
            target["description"] = primary["location_description"]
            primary["target"] = target

        p_tech = primary.get("technical", primary.get("technical_details", {})).copy()
        p_tech["grouped_instances"] = total_affected
        p_tech["grouped_rules"] = all_rules
        # Grouping is a presentation choice: the raw record of every merged violation stays available.
        p_tech["grouped_details"] = [{
            "finding_id": (it.get("technical") or {}).get("finding_id"),
            "rule": (it.get("technical") or {}).get("normalized_rule") or (it.get("technical") or {}).get("rule_id"),
            "raw_rule": (it.get("technical") or {}).get("raw_rule"),
            "selector": (it.get("technical") or {}).get("selector"),
            "wcag": (it.get("technical") or {}).get("wcag"),
            "raw_title": (it.get("technical") or {}).get("raw_title"),
            "raw_message": (it.get("technical") or {}).get("raw_message"),
            "verification_status": (it.get("technical") or {}).get("verification_status"),
        } for it in items]
        p_tech["all_finding_ids"] = all_ids
        p_tech["all_selectors"] = [e["selector"] for e in all_elements if e.get("selector")]
        p_tech["affected_targets"] = p_tech["all_selectors"]
        if "why_aura_reported_this" in primary:
            p_tech["why_aura_reported_this"] = primary["why_aura_reported_this"]
        primary["technical"] = p_tech
        primary["technical_details"] = p_tech

        grouped.append(primary)

    return grouped
