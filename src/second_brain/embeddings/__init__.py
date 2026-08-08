"""Local embedding providers."""

from second_brain.embeddings.base import EmbeddingMetadata, EmbeddingProvider
from second_brain.embeddings.learned import LearnedLocalEmbeddingProvider
from second_brain.embeddings.local import HashingEmbeddingProvider, LocalEmbeddingProvider

__all__ = [
    "EmbeddingMetadata",
    "EmbeddingProvider",
    "HashingEmbeddingProvider",
    "LearnedLocalEmbeddingProvider",
    "LocalEmbeddingProvider",
]
