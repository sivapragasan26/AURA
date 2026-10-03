"""
The model registry has to describe models that exist.

A model id that the provider has retired is not a cosmetic problem: the provider answers 404, the scan
comes back with no AI findings, and it looks like AURA failing rather than a stale list. Every id in
aura/config/models.py was checked against the provider's own documentation on 3 October 2026; these tests
hold the table together so an edit cannot leave it inconsistent between then and the next check.

They cannot tell whether an id still exists upstream - only a live call can, which is what
tests/live_provider_check.py is for.
"""
import pytest

from aura.api.provider_config import PROVIDER_LABELS, SUPPORTED, ProviderConfig
from aura.config.models import (
    DEFAULT_MODELS,
    MODEL_CAPABILITIES,
    PROVIDER_MODELS,
    PROVIDER_PRICING,
    supports_vision,
)

FREE = {"groq", "gemini"}
PAID = {"openai", "anthropic"}

# Ids the providers have retired. If one comes back into the registry it is almost certainly a bad merge
# or an old file restored, and the scan it produces would fail in a way nobody would attribute to this.
RETIRED = {
    "gpt-4o", "gpt-4o-mini", "o3-mini",
    "claude-3-5-sonnet-20241022", "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022",
    "gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro",
    "qwen/qwen3.6-27b",
}


@pytest.mark.parametrize("provider", sorted(set(DEFAULT_MODELS)))
def test_each_default_is_a_listed_model_with_known_capabilities(provider):
    default = DEFAULT_MODELS[provider]
    assert default in PROVIDER_MODELS[provider], (
        f"{provider}'s default '{default}' is not in its model list, so the picker offers one set of "
        f"models and a scan uses another")
    assert default in MODEL_CAPABILITIES, (
        f"'{default}' has no capability entry, so the browser cannot know whether to attach the "
        f"screenshot and will send none")


def test_every_listed_model_has_capabilities():
    missing = sorted(m for models in PROVIDER_MODELS.values() for m in models if m not in MODEL_CAPABILITIES)
    assert not missing, f"no capability entry for {missing}: a scan with one of these sends no screenshot"


def test_no_retired_model_is_offered():
    offered = {m for models in PROVIDER_MODELS.values() for m in models}
    assert not (offered & RETIRED), (
        f"the registry offers models the provider has retired: {sorted(offered & RETIRED)}. A scan with "
        f"one of these gets 404 and reports no AI findings.")
    assert not (set(DEFAULT_MODELS.values()) & RETIRED)


def test_every_default_can_be_shown_a_screenshot():
    """
    AURA's analysis is multimodal. A default that cannot take an image silently halves what the model
    sees, so the cheapest model with vision is chosen rather than the cheapest model.
    """
    for provider, model in DEFAULT_MODELS.items():
        assert supports_vision(provider, model), f"{provider}'s default '{model}' cannot be shown the page"


def test_capabilities_are_fully_specified():
    for model, caps in MODEL_CAPABILITIES.items():
        assert set(caps) >= {"image_input", "json_mode", "max_images"}, f"{model} is missing a capability"
        assert isinstance(caps["image_input"], bool) and isinstance(caps["json_mode"], bool), model
        assert caps["max_images"] >= (1 if caps["image_input"] else 0), model


def test_the_providers_and_their_prices_line_up():
    assert set(PROVIDER_PRICING) == set(PROVIDER_MODELS) == set(DEFAULT_MODELS) == set(PROVIDER_LABELS)
    assert {p for p, price in PROVIDER_PRICING.items() if price == "free tier"} == FREE
    assert {p for p, price in PROVIDER_PRICING.items() if price == "paid account"} == PAID
    assert set(SUPPORTED) == set(PROVIDER_MODELS)


def test_the_extension_is_told_the_price_and_the_capabilities():
    """The picker and the scan both read this: the price to show, the capabilities to decide the image."""
    described = {p["provider"]: p for p in ProviderConfig().describe()}
    for provider in SUPPORTED:
        entry = described[provider]
        assert entry["pricing"] == PROVIDER_PRICING[provider]
        assert entry["default_model"] == DEFAULT_MODELS[provider]
        for model in entry["models"]:
            assert entry["model_capabilities"][model] == MODEL_CAPABILITIES[model]
        assert "api_key" not in str(entry).lower()
