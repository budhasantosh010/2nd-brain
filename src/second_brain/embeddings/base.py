"""Embedding provider contracts and durable generated-index metadata."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from pydantic import BaseModel


class EmbeddingMetadata(BaseModel):
    provider: str
    model: str
    revision: str
    dimensions: int
    schema_version: str = "embedding-v2"
    learned: bool
    created_at: str = ""

    def profile_key(self) -> tuple[str, str, str, int, str]:
        return (
            self.provider,
            self.model,
            self.revision,
            self.dimensions,
            self.schema_version,
        )

    def with_timestamp(self) -> EmbeddingMetadata:
        if self.created_at:
            return self
        return self.model_copy(update={"created_at": datetime.now(UTC).isoformat()})


class EmbeddingProvider(ABC):
    name: str
    dimensions: int

    @property
    @abstractmethod
    def metadata(self) -> EmbeddingMetadata:
        """Describe the exact generated-vector schema."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Create one normalized local vector."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def prepare(self) -> EmbeddingMetadata:
        """Explicitly acquire/initialize optional model resources without embedding user text."""
        return self.metadata
