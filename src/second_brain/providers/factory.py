"""Create configured providers without leaking provider-specific logic into brain services."""

from __future__ import annotations

from second_brain.config import BrainConfig
from second_brain.providers.anthropic import AnthropicProvider
from second_brain.providers.base import AIProvider
from second_brain.providers.gemini import GeminiProvider
from second_brain.providers.local import LocalProvider
from second_brain.providers.mock import MockProvider
from second_brain.providers.openai import OpenAIProvider


def create_provider(config: BrainConfig) -> AIProvider | None:
    name = config.ai.provider.strip().lower()
    model = config.ai.model
    if name in {"", "none"}:
        return None
    if name == "mock":
        return MockProvider()
    if name == "openai":
        return OpenAIProvider(model)
    if name in {"anthropic", "claude"}:
        return AnthropicProvider(model)
    if name in {"gemini", "google"}:
        return GeminiProvider(model)
    if name in {"local", "ollama"}:
        return LocalProvider(model)
    raise ValueError(f"Unsupported AI provider: {config.ai.provider}")
