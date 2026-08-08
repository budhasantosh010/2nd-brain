"""Query-aware temporal/authority reranking after hybrid fusion."""

from __future__ import annotations

from datetime import UTC, datetime

from second_brain.models import QueryType, SearchHit

CURRENT_BOOSTS = {
    "project-state": 1.8,
    "project": 1.45,
    "decision": 1.35,
    "source-record": 1.1,
    "source-segment": 1.0,
}
HISTORICAL_BOOSTS = {
    "source-segment": 1.35,
    "source": 1.25,
    "decision": 1.2,
    "concept": 0.95,
}


def rerank(hits: list[SearchHit], query_type: QueryType, *, limit: int = 20) -> list[SearchHit]:
    now = datetime.now(UTC)
    ranked: list[SearchHit] = []
    for hit in hits:
        score = hit.score
        if query_type == QueryType.CURRENT_STATE:
            score *= CURRENT_BOOSTS.get(hit.object_type, 1.0)
            score *= _recency_factor(hit.updated_at, now, floor=0.75)
            if bool(hit.metadata.get("superseded")) or hit.metadata.get("status") == "superseded":
                score *= 0.35
        elif query_type == QueryType.HISTORICAL:
            score *= HISTORICAL_BOOSTS.get(hit.object_type, 1.0)
        elif query_type == QueryType.EXACT:
            if bool(hit.metadata.get("exact_identifier")):
                score *= 4.0
            if "metadata" in hit.metadata.get("channels", []):
                score *= 1.5
        elif query_type == QueryType.DECISION and hit.object_type == "decision":
            score *= 1.8
        elif query_type == QueryType.SOURCE_LOOKUP and hit.object_type in {"source", "source-record", "source-segment"}:
            score *= 1.7
        hit.score = score
        ranked.append(hit)
    ranked.sort(key=lambda item: (-item.score, item.object_id))
    return ranked[:limit]


def _recency_factor(value: datetime | None, now: datetime, *, floor: float) -> float:
    if value is None:
        return floor
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    age_days = max((now - aware.astimezone(UTC)).total_seconds() / 86400.0, 0.0)
    return max(floor, 1.35 / (1.0 + age_days / 180.0))
