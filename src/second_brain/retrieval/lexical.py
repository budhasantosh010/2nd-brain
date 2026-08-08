"""FTS5 lexical retrieval optimized for exact identifiers and phrases."""

from __future__ import annotations

from second_brain.models import SearchHit
from second_brain.storage.sqlite import SQLiteStore


class LexicalRetriever:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(self, query: str, *, limit: int = 30) -> list[SearchHit]:
        rows = self.store.search_fts(query, limit=limit)
        hits: list[SearchHit] = []
        for rank, row in enumerate(rows, start=1):
            # SQLite bm25 values are lower/better and may be negative. Rank position is a stable
            # positive retrieval score; final fusion uses list rank rather than raw engine scale.
            hits.append(
                SearchHit(
                    object_id=str(row["object_id"]),
                    object_type=str(row["object_type"]),
                    title=str(row["title"]),
                    text=str(row["text"]),
                    score=1.0 / rank,
                    source_id=str(row["source_id"]) if row.get("source_id") else None,
                    locator=str(row["locator"]) if row.get("locator") else None,
                    metadata={"channel": "lexical", "bm25": row.get("rank")},
                )
            )
        return hits
