"""Stable provider gateway shared by all AI-backed features."""

import os

from core.executors.ai_providers import (
    BaseAIProvider,
    OpenAICompatibleProvider,
    ScreeningResult,
    get_provider,
)
from core.services.ai_models_config import get_model_config


def provider_is_configured(model_id: str) -> bool:
    """Return whether a model can be called with configured credentials."""
    config = get_model_config(model_id)
    return bool(config and config.get('api_key')) or bool(os.environ.get('AI_API_KEY'))


__all__ = [
    'BaseAIProvider', 'OpenAICompatibleProvider', 'ScreeningResult',
    'get_provider', 'provider_is_configured',
]
