"""Deterministic reciprocal-rank fusion across heterogeneous retrieval channels."""

from __future__ import annotations

from second_brain.models import SearchHit


def reciprocal_rank_fusion(
    rankings: list[list[SearchHit]], *, k: int = 60, limit: int = 40
) -> list[SearchHit]:
    by_id: dict[str, SearchHit] = {}
    scores: dict[str, float] = {}
    channels: dict[str, set[str]] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.object_id] = scores.get(hit.object_id, 0.0) + 1.0 / (k + rank)
            if hit.object_id not in by_id or hit.score > by_id[hit.object_id].score:
                by_id[hit.object_id] = hit.model_copy(deep=True)
            channel = str(hit.metadata.get("channel", "unknown"))
            channels.setdefault(hit.object_id, set()).add(channel)

    fused: list[SearchHit] = []
    for object_id, hit in by_id.items():
        hit.score = scores[object_id]
        hit.metadata["channels"] = sorted(channels.get(object_id, set()))
        hit.metadata["rrf_score"] = hit.score
        fused.append(hit)
    fused.sort(key=lambda item: (-item.score, item.object_id))
    return fused[:limit]
