"""Typed configuration with safe defaults and runtime overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from second_brain.exceptions import ConfigurationError
from second_brain.paths import BrainPaths


class VaultConfig(BaseModel):
    timezone: str = "Asia/Dubai"


class IngestionConfig(BaseModel):
    watch_enabled: bool = True
    recursive_folder_import: bool = True
    settle_seconds: float = 1.0


class AIConfig(BaseModel):
    provider: str = "none"
    model: str | None = None
    allow_cloud_ai: bool = False


class EmbeddingsConfig(BaseModel):
    provider: str = "hashing"
    model: str | None = None
    revision: str = "fastembed-model-registry"
    dimensions: int = Field(default=384, ge=64, le=4096)
    schema_version: str = "embedding-v2"


class EnrichmentConfig(BaseModel):
    ocr_provider: str = "none"
    vision_provider: str = "none"
    transcription_provider: str = "none"


class RetrievalConfig(BaseModel):
    lexical_enabled: bool = True
    semantic_enabled: bool = True
    graph_hops: int = Field(default=1, ge=0, le=3)
    result_limit: int = Field(default=12, ge=1, le=100)


class MaintenanceConfig(BaseModel):
    nightly_enabled: bool = True
    weekly_enabled: bool = True
    monthly_enabled: bool = True


class SecurityConfig(BaseModel):
    secret_scanning: bool = True
    raw_sources_immutable: bool = True
    follow_symlinks: bool = False


class ReviewConfig(BaseModel):
    destructive_changes: str = "block"
    semantic_merges: str = "stage"


class BrainConfig(BaseModel):
    vault: VaultConfig = Field(default_factory=VaultConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"Configuration root must be a mapping: {path}")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(paths: BrainPaths | None = None) -> BrainConfig:
    paths = paths or BrainPaths.discover()
    merged = _deep_merge(
        _load_yaml(paths.repo / "config" / "default.yaml"),
        _load_yaml(paths.brain / "config.yaml"),
    )
    env_provider = os.getenv("SECOND_BRAIN_AI_PROVIDER")
    if env_provider:
        merged.setdefault("ai", {})["provider"] = env_provider
    env_model = os.getenv("SECOND_BRAIN_AI_MODEL")
    if env_model:
        merged.setdefault("ai", {})["model"] = env_model
    embedding_provider = os.getenv("SECOND_BRAIN_EMBEDDING_PROVIDER")
    if embedding_provider:
        merged.setdefault("embeddings", {})["provider"] = embedding_provider
    embedding_model = os.getenv("SECOND_BRAIN_EMBEDDING_MODEL")
    if embedding_model:
        merged.setdefault("embeddings", {})["model"] = embedding_model
    return BrainConfig.model_validate(merged)
