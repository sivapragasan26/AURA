"""
"Explain with AURA": the whole problem, in words a non-technical person can act on.

The finding card carries one short sentence. This is where the full account lives: what is happening, who
it affects and what to change. It is assembled ONLY from what the audit recorded for that finding, makes no
AI request, and adds no new claims, so it can never contradict the evidence.

Nothing technical belongs here. Rule ids, selectors, detector names, WCAG references, verification scores
and reproduction states are all in Technical details instead; anything that slips through is rewritten or
dropped by `plain_only()` before it reaches the panel.
"""
import re
from typing import Any, Dict, List, Optional

STATUS_PLAIN = {
    "CONFIRMED": "AURA measured this on the page, so it is not a guess.",
    "LIKELY": "AURA found the thing it describes, but could not measure the harm itself, so treat this as "
              "a strong suggestion rather than a proven fault.",
    "UNCERTAIN": "AURA could not confirm this from the page, so treat it as something to look at rather "
                 "than something to fix straight away.",
    "REJECTED": "AURA checked this and the page showed the opposite, so it is not reported as a problem.",
}

# Words a reader should never have to meet in this panel. Each maps to how a person would say it.
PLAIN_REPLACEMENTS = [
    (r"\bWCAG(?:\s*\d(?:\.\d+)*)?\b", "accessibility guidelines"),
    (r"\baxe-core\b", "AURA's built-in checks"),
    (r"\bARIA\b", "accessibility information"),
    (r"\baria-[a-z-]+\b", "accessibility information"),
    (r"\bDOM\b", "page structure"),
    (r"\bCSS\b", "styling"),
    (r"\bHTML\b", "page code"),
    (r"\bselector\b", "location"),
    (r"\blandmark\b", "page section"),
    (r"\bsemantic(?:s|ally)?\b", "meaningful"),
    (r"\bassistive technolog(?:y|ies)\b", "screen readers"),
    (r"\bviewport\b", "visible screen area"),
    (r"\battribute\b", "setting"),
    (r"\btabindex\b", "keyboard order setting"),
    (r"\belement\b", "item"),
]


def plain_only(text: Optional[str]) -> str:
    """Rewrites any technical term that reached a user-facing sentence."""
    out = (text or "").strip()
    for pattern, replacement in PLAIN_REPLACEMENTS:
        out = re.sub(pattern, replacement, out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip()


# What a reader most wants after "what is wrong": what it is like to run into this, and what the fixed
# version looks like. Keyed by the family of the rule, so one entry serves every rule in that family.
RULE_CONTEXT = [
    ("contrast",
     "Someone with tired eyes, an older screen, or sunlight on their phone reads this as a smudge rather "
     "than words. People with reduced vision may not see it at all.",
     "Dark text on a light background, or light on dark, with enough difference that the words stay "
     "readable when you glance at the screen from arm's length."),
    ("heading",
     "People who use a screen reader often move through a page heading by heading, the way a sighted "
     "reader skims bold text. That only works when the headings are there and in a sensible order.",
     "A clear top heading naming what the page is, then headings stepping down one level at a time, so "
     "the list of them reads like a table of contents."),
    ("region",
     "Screen readers offer a list of page areas — header, navigation, main content, footer — so someone "
     "can jump straight where they want. Content that belongs to no area never appears in that list.",
     "Every block of the page sitting inside a named area, with the primary content in the main one."),
    ("landmark",
     "Without one clear main area, a keyboard or screen-reader user has to go through the header and "
     "navigation on every single page before reaching what they came for.",
     "One clearly marked main area holding the page's own content, and nothing else."),
    ("link",
     "Screen readers can read out just the links on a page. A link whose text is \"click here\", an icon, "
     "or a bare web address tells the listener nothing about where it goes.",
     "Link text that would still make sense read on its own, away from the sentence around it."),
    ("button",
     "Someone hearing the page announced is told only \"button\" and has to press it to find out what it "
     "does — which is a poor thing to do with a button that deletes or sends something.",
     "A name on every button that says what pressing it will do."),
    ("label",
     "A field with no visible label leaves people guessing what belongs in it, and anyone returning to a "
     "half-finished form has nothing to remind them.",
     "A visible label beside each field that stays on screen while it is being filled in."),
    ("image",
     "People who cannot see the image are told nothing. If it carried the price, the rating or the only "
     "copy of some information, that information is simply gone for them.",
     "A short description for images that carry information, and images that are pure decoration marked "
     "as decorative so they are skipped."),
    ("aria",
     "Extra information can be attached to a control to tell screen readers what it is. When that "
     "information does not match the control, the screen reader describes something that is not there.",
     "Controls described as what they actually are, or built from standard page items that describe "
     "themselves."),
    ("list",
     "A screen reader announces \"list, 6 items\" and lets someone step through them. Items that are not "
     "grouped lose that count and that way of moving through them.",
     "Related items grouped as one list, with nothing else mixed in among them."),
    ("zoom",
     "Someone who needs bigger text pinches to zoom without thinking about it. When a page blocks that, "
     "their usual way of reading anything simply stops working.",
     "A page that can be zoomed as far as the reader wants, reflowing rather than breaking."),
    ("overflow",
     "Content wider than the screen means scrolling sideways to read a sentence, and parts of the page "
     "sitting off the edge where nobody thinks to look.",
     "Everything fitting the width of the screen, so the only scrolling is downwards."),
    ("clipp",
     "Text cut off mid-word leaves people guessing at the rest, and a button only half visible is easy "
     "to miss and awkward to hit.",
     "Room for content to grow, so nothing is sliced off by the box around it."),
    ("keyboard",
     "Not everyone uses a mouse. Someone moving through the page with the Tab key can only reach what the "
     "page lets them reach, and can get stuck where it does not.",
     "Everything that can be clicked also reachable and usable with the keyboard alone."),
    ("language",
     "Screen readers choose their pronunciation from the page's declared language. Undeclared or wrong, "
     "and the text is read out in the wrong accent — often to the point of being unintelligible.",
     "The page stating its language, and any passage in another language saying so."),
    ("title",
     "The title is what someone sees in a crowded row of tabs, and the first thing a screen reader "
     "announces when the page opens.",
     "A title that names this page and the site, specific enough to pick out among other tabs."),
]


def extra_context(rule: str, title: str, summary: str) -> Optional[tuple]:
    """(what it is like, what good looks like) for this rule's family, or None when AURA has nothing to add."""
    haystack = f"{rule} {title} {summary}".lower().replace("_", " ").replace("-", " ")
    for token, experience, good in RULE_CONTEXT:
        if token in haystack:
            return experience, good
    return None


PAGE_WIDE = ("the page as a whole", "whole page", "the page", "one item on this page")


def _scale(count: int, location: str) -> str:
    where = plain_only(location).strip()
    low = where.lower()
    page_wide = any(low.startswith(p) for p in PAGE_WIDE)
    if count and count > 1:
        if where and not page_wide:
            return f"This affects {count} places on the page, starting with {where[0].lower() + where[1:]}."
        return f"This affects {count} places on the page."
    if page_wide:
        return "It applies to the page as a whole rather than to one place on it."
    if where and not low.startswith(("specific item", "one item")):
        return f"You will find it at {where[0].lower() + where[1:]}."
    return ""


def explain_finding(finding: Dict[str, Any]) -> Dict[str, Any]:
    """finding: an entry of the audit view's `findings` list (aura.api.views.finding_view)."""
    human = finding.get("human") or {}
    conclusion = finding.get("conclusion") or {}
    status = finding.get("verification_status") or "UNCERTAIN"
    count = finding.get("affected_count") or 1

    what = plain_only(human.get("summary") or finding.get("description") or finding.get("title"))
    why = plain_only(human.get("why_it_matters") or finding.get("why_it_matters"))
    todo = plain_only(human.get("what_to_do") or finding.get("recommendation"))
    scale = _scale(count, human.get("location") or finding.get("location_description") or "")
    fact = plain_only(conclusion.get("known_fact") or human.get("known_fact"))

    sections: List[Dict[str, Any]] = [
        {"heading": "What is happening", "body": " ".join(p for p in (what, scale) if p)
            or "AURA recorded this condition but could not describe it in plain language."},
    ]
    if why:
        sections.append({"heading": "Why this matters to people using the page", "body": why})

    context = extra_context(str(finding.get("rule") or finding.get("normalized_rule") or ""),
                            human.get("title") or "", human.get("summary") or "")
    if context:
        experience, good = context
        sections.append({"heading": "What it is like to run into this", "body": experience})
        sections.append({"heading": "What it looks like when it is right", "body": good})

    if todo:
        sections.append({"heading": "What to change", "body": todo})
    sections.append({"heading": "How sure AURA is", "body": " ".join(p for p in (
        STATUS_PLAIN.get(status, ""), fact) if p)})

    return {
        "finding_id": finding.get("id"),
        "title": plain_only(human.get("title") or finding.get("title")),
        "sections": sections,
        "grounding": "Put together from what AURA recorded during the scan. No new AI request was made. "
                     "Open Technical details for the location, the check that found it and how it was verified.",
    }
