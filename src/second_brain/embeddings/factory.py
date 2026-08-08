"""Embedding provider selection without eager model acquisition."""

from __future__ import annotations

from second_brain.config import BrainConfig
from second_brain.embeddings.base import EmbeddingProvider
from second_brain.embeddings.learned import DEFAULT_MODEL, LearnedLocalEmbeddingProvider
from second_brain.embeddings.local import HashingEmbeddingProvider
from second_brain.paths import BrainPaths


def create_embedding_provider(config: BrainConfig, paths: BrainPaths) -> EmbeddingProvider:
    name = config.embeddings.provider.strip().lower()
    if name in {"hashing", "local", "fuzzy", "local-fuzzy"}:
        return HashingEmbeddingProvider(config.embeddings.dimensions)
    if name in {"learned", "fastembed", "semantic"}:
        model = config.embeddings.model or DEFAULT_MODEL
        cache_dir = str(paths.brain / "cache" / "embeddings")
        return LearnedLocalEmbeddingProvider(
            model=model,
            revision=config.embeddings.revision,
            dimensions=config.embeddings.dimensions,
            cache_dir=cache_dir,
        )
    raise ValueError(f"Unknown embedding provider: {config.embeddings.provider}")
