"""Centralized registry of validated model options per AI Provider."""

PROVIDER_MODELS = {
    "gemini": [
        "gemini-3.6-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro"
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "o3-mini"
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-haiku-20241022"
    ],
    "groq": [
        "qwen/qwen3.8-27b",
        "qwen/qwen3.6-27b"
    ],
    "mock": [
        "mock-assurance-v0.3"
    ]
}

# Capabilities AURA relies on, per model, as documented by the provider. A model missing here is
# "unknown" (not assumed capable).
MODEL_CAPABILITIES = {
    # Groq docs (vision + reasoning pages): image input, JSON mode, reasoning_format parsed/hidden with JSON mode
    "qwen/qwen3.8-27b": {"image_input": True, "json_mode": True, "max_images": 3, "reasoning": True},
    "qwen/qwen3.6-27b": {"image_input": True, "json_mode": True, "max_images": 5, "reasoning": True},

    # Google Gemini docs (multimodal vision + structured JSON output)
    "gemini-3.6-flash": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": True},
    "gemini-2.5-flash": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": True},
    "gemini-2.5-pro": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": True},
    "gemini-1.5-flash": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": False},
    "gemini-1.5-pro": {"image_input": True, "json_mode": True, "max_images": 16, "reasoning": False},

    # OpenAI docs
    "gpt-4o": {"image_input": True, "json_mode": True, "max_images": 10, "reasoning": False},
    "gpt-4o-mini": {"image_input": True, "json_mode": True, "max_images": 10, "reasoning": False},
    "o3-mini": {"image_input": False, "json_mode": True, "max_images": 0, "reasoning": True},

    # Anthropic Claude docs
    "claude-3-5-sonnet-20241022": {"image_input": True, "json_mode": False, "max_images": 20, "reasoning": False},
    "claude-3-7-sonnet-20250219": {"image_input": True, "json_mode": False, "max_images": 20, "reasoning": True},
    "claude-3-5-haiku-20241022": {"image_input": True, "json_mode": False, "max_images": 20, "reasoning": False},

    # Mock provider
    "mock-assurance-v0.3": {"image_input": True, "json_mode": True, "max_images": 5, "reasoning": False},
}

DEFAULT_MODELS = {
    "gemini": "gemini-3.6-flash",
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-20241022",
    "groq": "qwen/qwen3.8-27b",
    "mock": "mock-assurance-v0.3"
}
AVAILABLE_MODELS = PROVIDER_MODELS


def supports_vision(provider_key: str, model: str) -> bool:
    """Returns True if the specified model is registered with image_input support."""
    caps = MODEL_CAPABILITIES.get(model)
    if caps:
        return bool(caps.get("image_input", False))
    return False

