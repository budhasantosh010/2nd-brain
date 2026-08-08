"""Lazy CPU-capable learned local embeddings powered by FastEmbed/ONNX."""

from __future__ import annotations

import math
from typing import Any

from second_brain.embeddings.base import EmbeddingMetadata, EmbeddingProvider

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_REVISION = "fastembed-model-registry"
DEFAULT_DIMENSIONS = 384


class LearnedLocalEmbeddingProvider(EmbeddingProvider):
    """A real learned sentence embedding provider that never sends text to cloud.

    FastEmbed/model resources are imported/initialized only on `prepare()` or first
    embedding call; constructing the provider has no network/model-download side effect.
    """

    name = "fastembed-local-v1"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        revision: str = DEFAULT_REVISION,
        dimensions: int = DEFAULT_DIMENSIONS,
        cache_dir: str | None = None,
    ) -> None:
        self.model = model
        self.revision = revision
        self.dimensions = dimensions
        self.cache_dir = cache_dir
        self._engine: Any | None = None

    @property
    def metadata(self) -> EmbeddingMetadata:
        return EmbeddingMetadata(
            provider=self.name,
            model=self.model,
            revision=self.revision,
            dimensions=self.dimensions,
            learned=True,
        )

    def _load(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Learned embeddings require the 'semantic' extra: uv sync --extra semantic"
            ) from exc
        if self.cache_dir:
            self._engine = TextEmbedding(model_name=self.model, cache_dir=self.cache_dir)
        else:
            self._engine = TextEmbedding(model_name=self.model)
        return self._engine

    def prepare(self) -> EmbeddingMetadata:
        self._load()
        return self.metadata

    def embed(self, text: str) -> list[float]:
        values = self.embed_batch([text])
        return values[0] if values else [0.0] * self.dimensions

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        engine = self._load()
        vectors = engine.embed(texts)
        result: list[list[float]] = []
        for raw in vectors:
            vector = [float(value) for value in raw]
            if len(vector) != self.dimensions:
                raise RuntimeError(
                    f"Embedding dimension mismatch for {self.model}: "
                    f"expected {self.dimensions}, got {len(vector)}"
                )
            magnitude = math.sqrt(sum(value * value for value in vector))
            result.append([value / magnitude for value in vector] if magnitude else vector)
        if len(result) != len(texts):
            raise RuntimeError(
                f"Embedding provider returned {len(result)} vectors for {len(texts)} inputs"
            )
        return result
