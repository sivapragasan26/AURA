"""
Centralized registry of validated model options per AI Provider.

This is the single source of truth for both sides of a scan. The engine picks a model from here, and the
extension - which makes the AI call itself, in the browser - reads MODEL_CAPABILITIES over /api/providers
to decide whether to attach the screenshot and whether to ask for JSON. One table, so the two cannot
disagree about what a model can do.

Every id below was checked against the provider's own documentation on 3 October 2026. A model id that no
longer exists is not a cosmetic problem: the provider answers 404 and the user sees a scan with no AI
findings, which looks like AURA failing rather than a stale list.
"""

# Providers listed free-tier first: Groq and Gemini can be used at no cost, which is what almost everyone
# will do. OpenAI and Anthropic need a funded account and are supported rather than recommended.
PROVIDER_MODELS = {
    "groq": [
        "qwen/qwen3.8-27b",
    ],
    "gemini": [
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ],
    "openai": [
        "gpt-6-luna",
        "gpt-6-astra",
        "gpt-6.1-sol",
    ],
    "anthropic": [
        "claude-haiku-4-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    ],
    "mock": [
        "mock-assurance-v0.3"
    ]
}

# Capabilities AURA relies on, per model, as documented by the provider. A model missing here is
# "unknown", which means no screenshot is attached: never assume a model can see.
MODEL_CAPABILITIES = {
    # Groq: qwen/qwen3.8-27b is the only vision model Groq serves. Its docs give a 3-image limit and a
    # 20 MB cap on a request carrying an image. JSON mode is supported, with reasoning_format hidden.
    "qwen/qwen3.8-27b": {"image_input": True, "json_mode": True, "max_images": 3, "reasoning": True},

    # Google Gemini: multimodal with structured JSON output (responseMimeType: application/json).
    # The 2.5 generation is now closed to accounts that have not already used it, so it is not listed:
    # a new key would get 404 for every one of those ids.
    "gemini-3.6-flash": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": True},
    "gemini-3.8-flash": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": True},
    "gemini-3.5-flash-lite": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": True},
    "gemini-3.1-flash-lite": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": True},

    # OpenAI: gpt-4o, gpt-4o-mini and o3-mini are gone from the API; the only gpt-4o-* ids remaining are
    # audio and transcription variants. gpt-6-luna is the cheapest current model that accepts images.
    "gpt-6-luna": {"image_input": True, "json_mode": True, "max_images": 10, "reasoning": False},
    "gpt-6-astra": {"image_input": True, "json_mode": True, "max_images": 10, "reasoning": True},
    "gpt-6.1-sol": {"image_input": True, "json_mode": True, "max_images": 10, "reasoning": True},

    # Anthropic: the claude-3.x snapshots AURA used are retired. Every current Claude model takes images.
    # None has a JSON response_format, so the prompt's "return JSON only" is what keeps the answer parseable.
    "claude-haiku-4-5": {"image_input": True, "json_mode": False, "max_images": 20, "reasoning": True},
    "claude-sonnet-5-5": {"image_input": True, "json_mode": False, "max_images": 20, "reasoning": True},
    "claude-opus-5-5": {"image_input": True, "json_mode": False, "max_images": 20, "reasoning": True},

    # Mock provider
    "mock-assurance-v0.3": {"image_input": True, "json_mode": True, "max_images": 5, "reasoning": False},
}

# How large a request a model will actually accept, where the provider meters the input side.
#
# Groq's free tier allows 7,000 input tokens per minute, and one scan of an ordinary page can exceed
# that on its own: a long page was measured at 7,016 tokens - 13 KB of evidence packet plus a twelve-
# screen capture - and Groq refused the whole request, leaving the scan with no AI analysis at all. A
# model absent from this table is sent the request unshaped, which is right for the providers whose
# input allowance is far larger.
#
# The numbers are the ones the engine's own Groq client settled on: ~18 elements and 8,000 characters
# of packet, and a 480px JPEG at quality 55, which takes a capture from 4,000-5,000 vision tokens to
# roughly 1,000. The extension reads this from the prepared scan, because the screenshot never leaves
# the browser and can only be resized there.
REQUEST_SHAPING = {
    "qwen/qwen3.8-27b": {
        "reason": "Groq's free tier allows 7,000 input tokens per minute",
        "max_dom_elements": 18,
        "max_prompt_chars": 8000,
        "image_max_dim": 480,
        "image_quality": 55,
        "image_format": "image/jpeg",
    },
}


def shaping_for(model):
    """The input shaping a model needs, or None when it accepts a full-sized request."""
    return REQUEST_SHAPING.get(model or "")


# The cheapest model per provider that can still be shown a screenshot, because the user pays for this.
DEFAULT_MODELS = {
    "groq": "qwen/qwen3.8-27b",
    "gemini": "gemini-3.6-flash",
    "openai": "gpt-6-luna",
    "anthropic": "claude-haiku-4-5",
    "mock": "mock-assurance-v0.3"
}

# What a provider costs the user, shown in the extension's picker so the free ones are obvious.
PROVIDER_PRICING = {
    "groq": "free tier",
    "gemini": "free tier",
    "openai": "paid account",
    "anthropic": "paid account",
    "mock": "built in",
}

AVAILABLE_MODELS = PROVIDER_MODELS


def supports_vision(provider_key: str, model: str) -> bool:
    """Returns True if the specified model is registered with image_input support."""
    caps = MODEL_CAPABILITIES.get(model)
    if caps:
        return bool(caps.get("image_input", False))
    return False
