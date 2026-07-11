"""LLM provider adapters."""

from .base import ProviderResult, TextGenerationRequest, TextProvider
from .offline_provider import OfflineProvider
from .openai_compatible_provider import OpenAICompatibleProvider
from .dashscope_provider import DashScopeProvider

__all__ = [
    "ProviderResult",
    "TextGenerationRequest",
    "TextProvider",
    "OfflineProvider",
    "OpenAICompatibleProvider",
    "DashScopeProvider",
]
