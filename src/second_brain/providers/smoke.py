"""Provider acceptance smoke checks without exposing credentials."""

from __future__ import annotations

import importlib.util
import os
from dataclasses import asdict, dataclass

from second_brain.config import BrainConfig
from second_brain.models import KnowledgeExtraction
from second_brain.providers.factory import create_provider


@dataclass(frozen=True, slots=True)
class ProviderSmokeResult:
    provider: str
    model: str | None
    sdk_available: bool
    credential_configured: bool
    health: str
    structured_generation_smoke: str
    real_provider_acceptance: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _sdk_module(name: str) -> str | None:
    return {
        "openai": "openai",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "gemini": "google.genai",
        "google": "google.genai",
        "local": None,
        "ollama": None,
        "mock": None,
    }.get(name)


def _credential_present(name: str) -> bool:
    env = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "google": "GOOGLE_API_KEY",
    }.get(name)
    if env is None:
        return name in {"local", "ollama", "mock"}
    return bool(os.getenv(env))


def provider_smoke(config: BrainConfig) -> ProviderSmokeResult:
    name = config.ai.provider.strip().lower() or "none"
    if name == "none":
        return ProviderSmokeResult(
            provider="none",
            model=None,
            sdk_available=False,
            credential_configured=False,
            health="not configured",
            structured_generation_smoke="NOT VERIFIED",
            real_provider_acceptance="NOT VERIFIED",
            detail="REAL PROVIDER ACCEPTANCE: NOT VERIFIED",
        )
    module = _sdk_module(name)
    sdk_available = True if module is None else importlib.util.find_spec(module) is not None
    credential = _credential_present(name)
    try:
        provider = create_provider(config)
    except Exception as exc:
        return ProviderSmokeResult(name, config.ai.model, sdk_available, credential, "unavailable", "FAIL", "FAIL", type(exc).__name__)
    if provider is None:
        return ProviderSmokeResult(name, config.ai.model, sdk_available, credential, "unavailable", "NOT VERIFIED", "NOT VERIFIED", "provider factory returned none")
    health = provider.health_check()
    if not health.available:
        return ProviderSmokeResult(name, provider.model, sdk_available, credential, "unavailable", "NOT VERIFIED", "NOT VERIFIED", health.detail)
    try:
        payload = provider.generate_structured(
            task="compile_knowledge",
            text="PURPOSE: provider acceptance smoke\nCLAIM: provider smoke works | smoke",
            schema=KnowledgeExtraction.model_json_schema(),
            context={"source_id": "SRC-provider-smoke"},
        )
        KnowledgeExtraction.model_validate(payload)
    except Exception as exc:
        return ProviderSmokeResult(name, provider.model, sdk_available, credential, "available", "FAIL", "FAIL", type(exc).__name__)
    real = "NOT VERIFIED" if name == "mock" else "PASS"
    return ProviderSmokeResult(name, provider.model, sdk_available, credential, "available", "PASS", real, health.detail)
