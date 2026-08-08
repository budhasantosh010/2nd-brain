"""Convert retrieval hits into verified evidence records."""

from __future__ import annotations

from second_brain.models import EvidenceItem, QueryType, SearchHit, VerificationState
from second_brain.storage.sqlite import SQLiteStore
from second_brain.verification.provenance import check_provenance
from second_brain.verification.temporal import check_temporal


def evidence_from_hit(
    store: SQLiteStore,
    hit: SearchHit,
    query_type: QueryType,
) -> tuple[EvidenceItem | None, list[str]]:
    warnings: list[str] = []
    provenance = check_provenance(store, hit)
    if not provenance.available or provenance.source_id is None:
        return None, [provenance.detail]
    temporal = check_temporal(store, hit, query_type)
    state = temporal.state
    if not provenance.locator_available and hit.object_type == "source-segment":
        state = VerificationState.UNCERTAIN
        warnings.append(provenance.detail)
    if temporal.state in {VerificationState.STALE, VerificationState.CONTRADICTED}:
        warnings.append(temporal.detail)
    excerpt = " ".join(hit.text.split())
    if len(excerpt) > 900:
        excerpt = excerpt[:897].rstrip() + "..."
    source_row = store.source_by_id(provenance.source_id)
    authority = str(source_row["authority"]) if source_row is not None else "unknown"
    return (
        EvidenceItem(
            source_id=provenance.source_id,
            locator=hit.locator,
            title=hit.title,
            excerpt=excerpt,
            authority=authority,
            verification_state=state,
        ),
        warnings,
    )
