"""Query classification and hybrid retrieval orchestration."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from second_brain.config import BrainConfig, load_config
from second_brain.embeddings.factory import create_embedding_provider
from second_brain.models import QueryType, SearchHit
from second_brain.paths import BrainPaths
from second_brain.retrieval.context_builder import BuiltContext, ContextBuilder
from second_brain.retrieval.fusion import reciprocal_rank_fusion
from second_brain.retrieval.graph import GraphRetriever
from second_brain.retrieval.lexical import LexicalRetriever
from second_brain.retrieval.metadata import MetadataRetriever
from second_brain.retrieval.reranker import rerank
from second_brain.retrieval.semantic import SemanticRetriever
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore

EXACT_HINT = re.compile(
    r"(?:\b(?:SRC|KNO|CLM|DEC|PRJ|ENT|SKL|RVW|OP|T)-[A-Za-z0-9-]{5,}\b|"
    r"\b[a-f0-9]{7,40}\b|[A-Za-z]:\\|/[^\s]+/|\"[^\"]+\")",
    re.IGNORECASE,
)
CURRENT_WORDS = ("current", "now", "latest", "next action", "where are we", "status", "blocker")
HISTORY_WORDS = ("old", "previous", "historical", "used to", "before", "what changed", "prior")
DECISION_WORDS = ("decision", "decided", "why did we", "superseded", "alternative")
SOURCE_WORDS = ("source", "file", "document", "pdf", "filename", "where is")
CROSS_WORDS = ("across projects", "all projects", "cross-project", "every project")


class RetrievalService:
    def __init__(
        self,
        paths: BrainPaths | None = None,
        config: BrainConfig | None = None,
        store: SQLiteStore | None = None,
    ) -> None:
        self.paths = paths or BrainPaths.discover()
        self.config = config or load_config(self.paths)
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        embedding = create_embedding_provider(self.config, self.paths)
        self.vectors = VectorStore(self.store, embedding)
        self.lexical = LexicalRetriever(self.store)
        self.semantic = SemanticRetriever(self.vectors)
        self.metadata = MetadataRetriever(self.store)
        self.graph = GraphRetriever(self.store)
        self.context_builder = ContextBuilder()

    def classify(self, query: str) -> QueryType:
        lowered = query.lower()
        if EXACT_HINT.search(query):
            return QueryType.EXACT
        if any(term in lowered for term in CURRENT_WORDS):
            return QueryType.CURRENT_STATE
        if any(term in lowered for term in HISTORY_WORDS):
            return QueryType.HISTORICAL
        if any(term in lowered for term in DECISION_WORDS):
            return QueryType.DECISION
        if any(term in lowered for term in SOURCE_WORDS):
            return QueryType.SOURCE_LOOKUP
        if any(term in lowered for term in CROSS_WORDS):
            return QueryType.CROSS_PROJECT
        return QueryType.CONCEPTUAL

    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        project_id: str | None = None,
    ) -> list[SearchHit]:
        query_type = self.classify(query)
        result_limit = limit or self.config.retrieval.result_limit
        channel_limit = max(result_limit * 3, 24)
        rankings: list[list[SearchHit]] = []
        if self.config.retrieval.lexical_enabled:
            rankings.append(self.lexical.search(query, limit=channel_limit))
        if self.config.retrieval.semantic_enabled:
            semantic = self.semantic.search(query, limit=channel_limit)
            semantic = [hit for hit in semantic if hit.score >= 0.18]
            for hit in semantic:
                hit.metadata["channel"] = "semantic"
                hit.metadata["semantic_score"] = hit.score
            rankings.append(semantic)
        rankings.append(self.metadata.search(query, limit=channel_limit))
        if query_type == QueryType.HISTORICAL and project_id:
            rankings.append(self._historical_project_states(project_id, limit=channel_limit))
        fused = reciprocal_rank_fusion(rankings, limit=channel_limit)
        if project_id:
            fused = self._project_filter_or_boost(fused, project_id)
        if self.config.retrieval.graph_hops > 0:
            graph_hits = self.graph.expand(
                fused,
                hops=self.config.retrieval.graph_hops,
                limit=channel_limit,
            )
            fused = reciprocal_rank_fusion([fused, graph_hits], limit=channel_limit)
        ranked = rerank(fused, query_type, limit=result_limit)
        self._record_event(query, query_type, ranked, answered=bool(ranked))
        return ranked

    def context(
        self,
        query: str,
        *,
        limit: int | None = None,
        project_id: str | None = None,
    ) -> BuiltContext:
        return self.context_builder.build(self.search(query, limit=limit, project_id=project_id))

    @staticmethod
    def _project_filter_or_boost(hits: list[SearchHit], project_id: str) -> list[SearchHit]:
        result: list[SearchHit] = []
        for hit in hits:
            ids = hit.metadata.get("project_ids", [])
            if isinstance(ids, list) and project_id in ids:
                hit.score *= 1.8
                result.append(hit)
            elif hit.object_id == project_id or hit.metadata.get("project_id") == project_id:
                hit.score *= 2.0
                result.append(hit)
            else:
                # Keep global evidence available but lower it. Global storage remains discoverable.
                hit.score *= 0.55
                result.append(hit)
        result.sort(key=lambda item: (-item.score, item.object_id))
        return result

    def _historical_project_states(self, project_id: str, *, limit: int) -> list[SearchHit]:
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT ps.*, p.title AS project_title, p.project_path
                FROM project_states ps
                JOIN projects p ON p.id = ps.project_id
                WHERE ps.project_id = ? AND ps.active = 0
                ORDER BY ps.created_at DESC, ps.id DESC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
        hits: list[SearchHit] = []
        for row in rows:
            try:
                evidence = json.loads(str(row["evidence_json"] or "[]"))
            except json.JSONDecodeError:
                evidence = []
            source_id = next(
                (
                    str(value)
                    for value in evidence
                    if isinstance(value, str) and value.startswith("SRC-")
                ),
                None,
            ) if isinstance(evidence, list) else None
            hits.append(
                SearchHit(
                    object_id=f"PSTH-{row['id']}",
                    object_type="project-state-history",
                    title=f"{row['project_title']} — Historical State",
                    text=(
                        f"Historical state: {row['current_state']}\n"
                        f"Next action at that time: {row['next_action'] or ''}"
                    ),
                    score=1.0,
                    source_id=source_id,
                    locator=f"{row['project_path']}/STATE.md",
                    updated_at=datetime.fromisoformat(str(row["created_at"])),
                    metadata={
                        "channel": "historical-state",
                        "project_id": project_id,
                        "active": False,
                        "evidence": evidence if isinstance(evidence, list) else [],
                    },
                )
            )
        return hits

    def _record_event(
        self,
        query: str,
        query_type: QueryType,
        hits: list[SearchHit],
        *,
        answered: bool,
    ) -> None:
        payload: list[dict[str, Any]] = [
            {
                "object_id": hit.object_id,
                "object_type": hit.object_type,
                "score": hit.score,
                "source_id": hit.source_id,
                "locator": hit.locator,
            }
            for hit in hits
        ]

        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_events(query, query_type, results_json, created_at, answered, metadata_json)
                VALUES (?, ?, ?, ?, ?, '{}')
                """,
                (
                    query,
                    query_type.value,
                    json.dumps(payload, sort_keys=True),
                    datetime.now(UTC).isoformat(),
                    int(answered),
                ),
            )
