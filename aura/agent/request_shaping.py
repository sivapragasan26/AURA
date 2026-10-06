"""
Shaping a request to fit a provider's input allowance.

Some free tiers meter the *input* side of a call. Groq's free tier allows 7,000 input tokens per minute,
and a single scan of an ordinary page can exceed that on its own: a long page's evidence packet runs to
13 KB of text and its full-page capture to twelve screens, which together were measured at 7,016 tokens
against that 7,000 limit. The provider then refuses the whole request and the scan has no AI analysis at
all.

This module holds the part of the fix that both halves of AURA need. The engine's own Groq client has
shaped its requests this way for some time; when the model call moved into the browser the browser began
sending the unshaped prompt, so the same logic has to be reachable from the API that prepares it.

The image is shaped where the image lives - in the browser, by the extension - from the directive in
aura/config/models.py, because the engine never receives the screenshot.
"""
import json
import re
from typing import Optional

from aura.utils.logger import logger


def compact_packet_prompt(prompt: str, max_dom_elements: int = 18, max_chars: int = 8000,
                          fallback_dom_elements: int = 15) -> str:
    """
    Trims the evidence packet inside a prompt to fit an input allowance.

    Only the element list is shortened: the instructions, the response schema and the page metadata are
    what make the answer usable, so they are kept whole and the elements - which are already ordered by
    how likely they are to matter - are cut from the end. If the result still exceeds the character
    budget, the list is cut again to `fallback_dom_elements`.
    """
    if not prompt:
        return prompt
    m = re.search(r"```json\s*(.*?)\s*```", prompt, re.DOTALL)
    if not m:
        if len(prompt) > max_chars:
            return prompt[:max_chars] + "\n\nRespond with valid JSON."
        return prompt
    try:
        data = json.loads(m.group(1))
        if isinstance(data, dict):
            dom = data.get("targeted_dom", [])
            if len(dom) > max_dom_elements:
                data["targeted_dom"] = dom[:max_dom_elements]
            compact_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            new_prompt = prompt[:m.start()] + "```json\n" + compact_json + "\n```" + prompt[m.end():]
            if len(new_prompt) > max_chars:
                data["targeted_dom"] = dom[:min(fallback_dom_elements, max_dom_elements)]
                compact_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                new_prompt = prompt[:m.start()] + "```json\n" + compact_json + "\n```" + prompt[m.end():]
            return new_prompt
    except Exception as e:
        logger.debug(f"[request_shaping] Prompt JSON compaction skipped: {e}")
    if len(prompt) > max_chars:
        return prompt[:max_chars] + "\n\nRespond with valid JSON."
    return prompt


def shaped_prompt(prompt: str, shaping: Optional[dict]) -> str:
    """The prompt a model with this shaping should be sent. No shaping means the prompt is left alone."""
    if not shaping:
        return prompt
    return compact_packet_prompt(
        prompt,
        max_dom_elements=int(shaping.get("max_dom_elements", 18)),
        max_chars=int(shaping.get("max_prompt_chars", 8000)),
    )
