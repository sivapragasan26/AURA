from typing import Optional, Dict
from aura.config import settings
from aura.config.models import DEFAULT_MODELS, PROVIDER_MODELS
from aura.security.credentials import SessionCredentialsManager
from aura.agent.provider import AIProvider
from aura.agent.mock_provider import MockAIProvider
from aura.agent.openai_provider import OpenAIProvider
from aura.agent.gemini_provider import GeminiProvider
from aura.agent.anthropic_provider import AnthropicProvider
from aura.agent.groq_provider import GroqProvider
from aura.utils.logger import logger


def get_ai_provider(
    provider_type: str = settings.AI_PROVIDER,
    model_name: Optional[str] = None,
    session_state: Optional[Dict] = None
) -> AIProvider:
    """
    Factory function returning configured AIProvider instance.
    Resolves credentials via SessionCredentialsManager (Session -> Env -> Mock).
    """
    provider_type = (provider_type or "mock").lower()

    key, source = SessionCredentialsManager.get_credential_for_provider(provider_type, session_state)
    target_model = model_name or DEFAULT_MODELS.get(provider_type, "")

    if model_name and provider_type in PROVIDER_MODELS:
        known = PROVIDER_MODELS[provider_type]
        if target_model not in known:
            logger.warning(
                f"[Provider Factory] Requested model '{target_model}' is not in known models for '{provider_type}': {known}"
            )

    if provider_type == "openai":
        return OpenAIProvider(api_key=key, model=target_model)
    elif provider_type == "gemini":
        return GeminiProvider(api_key=key, model=target_model)
    elif provider_type == "anthropic":
        return AnthropicProvider(api_key=key, model=target_model)
    elif provider_type == "groq":
        return GroqProvider(api_key=key, model=target_model)
    else:
        return MockAIProvider()
