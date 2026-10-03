"""
The privacy policy has to stay true.

Two things go wrong with a policy: the two copies of it drift apart, and the code changes underneath it.
Both are cheap to catch. Every number the policy quotes is read back out of the code here, so a change to
a retention limit or a cap fails this test rather than quietly making a published promise false.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN = ROOT / "PRIVACY.md"
PAGE = ROOT / "docs" / "privacy.html"


def text_of(path):
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        raw = re.sub(r"<[^>]+>", "", raw)
        raw = raw.replace("&mdash;", "—").replace("&rsquo;", "'").replace("&amp;", "&")
    else:
        raw = raw.replace("**", "")   # markdown emphasis is not part of what the policy says
    # One space everywhere, so a line break in one copy and not the other does not matter.
    return " ".join(raw.split())


PROMISES = [
    "Stays in this extension. Sent only to the provider you chose. The AURA service never receives it.",
    "Stay in this browser.",
    "never written to disk.",
    "Nothing is collected until you press",
    "it has no content scripts",
    "the extractor leaves form field values out entirely",
    "your browser",
    "does not have your key",
    "one screenshot of the visible part of the page",
    "may include personal information on the page",
    "An audit belongs to the install that made it",
    "logs contain no page address and no page title",
    "It runs no remote code",
    "no identifiers that follow you",
    "AURA has no model of its own to train",
]


def test_both_copies_exist_and_make_the_same_promises():
    assert MARKDOWN.is_file() and PAGE.is_file()
    md, html = text_of(MARKDOWN), text_of(PAGE)
    for promise in PROMISES:
        assert promise in md, f"PRIVACY.md no longer says: {promise}"
        assert promise in html, f"docs/privacy.html no longer says: {promise}"


def test_the_numbers_in_the_policy_are_the_numbers_in_the_code():
    from aura.api.relay import PENDING_TTL_SECONDS
    from aura.api.store import MAX_IN_MEMORY
    from aura.browser.interaction_policy import InteractionPolicy
    from aura.evidence.bundle import MAX_ELEMENTS, MAX_TEXT

    md, html = text_of(MARKDOWN), text_of(PAGE)
    quoted = {
        f"at most {MAX_IN_MEMORY} at a time": "how many audits are held in memory",
        f"at most {PENDING_TTL_SECONDS // 60} minutes": "how long prepared evidence waits",
        f"up to {MAX_ELEMENTS:,} elements": "the element cap",
        f"shortened to {MAX_TEXT} characters each": "the text cap",
    }
    # Written out in words in the prose, so either spelling counts.
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    budget = InteractionPolicy.LIVE_SESSION_BUDGET
    quoted[f"at most {budget} harmless controls"] = "the interaction budget"
    for phrase, what in quoted.items():
        spelled = phrase.replace(f" {budget} ", f" {words.get(budget, budget)} ")
        for copy, name in ((md, "PRIVACY.md"), (html, "docs/privacy.html")):
            assert phrase in copy or spelled in copy, (
                f"{name} states {what} differently from the code (expected {phrase!r})")


def test_the_policy_names_every_provider_the_extension_can_call():
    providers = (ROOT / "extension" / "sidepanel" / "providers.js").read_text(encoding="utf-8")
    md = text_of(MARKDOWN)
    for label, name in (("Groq", "groq"), ("OpenAI", "openai"), ("Gemini", "gemini"), ("Anthropic", "anthropic")):
        if f"  {name}: {{" in providers:
            assert label in md, f"the extension can call {label} but the policy does not say so"
    # And it must not promise the evidence stays local, which stopped being true with the hosted service.
    for untrue in ("nothing leaves your machine", "only to your local AURA server",
                   "stays on your computer"):
        assert untrue not in md.lower(), f"the policy still claims: {untrue}"


def test_the_policy_is_reachable_from_the_readme_and_the_extension_listing_notes():
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").is_file() else ""
    listing = (ROOT / "docs" / "STORE-LISTING.md")
    assert listing.is_file(), "the store listing notes are what carry the policy URL into the submission"
    assert "privacy" in listing.read_text(encoding="utf-8").lower()
    assert not readme or "PRIVACY" in readme.upper() or "privacy" in readme.lower()
