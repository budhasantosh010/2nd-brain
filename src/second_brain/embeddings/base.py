"""Embedding provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    name: str
    dimensions: int

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Create a deterministic local vector for text."""
