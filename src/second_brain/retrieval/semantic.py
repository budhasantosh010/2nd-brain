"""Local semantic retrieval over the rebuildable vector index."""

from __future__ import annotations

from second_brain.storage.vector import VectorStore


class SemanticRetriever:
    def __init__(self, vectors: VectorStore) -> None:
        self.vectors = vectors

    def search(self, query: str, *, limit: int = 30):  # type: ignore[no-untyped-def]
        return self.vectors.search(query, limit=limit)
