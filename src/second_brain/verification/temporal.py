"""Temporal applicability and supersession checks."""

from __future__ import annotations

from dataclasses import dataclass

from second_brain.models import QueryType, SearchHit, VerificationState
from second_brain.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class TemporalCheck:
    state: VerificationState
    detail: str
    superseded_by: str | None = None


def check_temporal(store: SQLiteStore, hit: SearchHit, query_type: QueryType) -> TemporalCheck:
    if hit.object_type == "decision":
        with store.connect() as conn:
            row = conn.execute("SELECT * FROM decisions WHERE id = ?", (hit.object_id,)).fetchone()
        if row is not None and row["superseded_by"]:
            successor = str(row["superseded_by"])
            if query_type == QueryType.HISTORICAL:
                return TemporalCheck(
                    VerificationState.SUPPORTED,
                    f"Historical decision was later superseded by {successor}.",
                    successor,
                )
            return TemporalCheck(
                VerificationState.STALE,
                f"Decision is superseded by {successor} and should not be presented as current.",
                successor,
            )
    if hit.object_type == "claim":
        with store.connect() as conn:
            row = conn.execute("SELECT * FROM claims WHERE id = ?", (hit.object_id,)).fetchone()
        if row is not None:
            if row["superseded_by"]:
                return TemporalCheck(
                    VerificationState.STALE,
                    f"Claim is superseded by {row['superseded_by']}.",
                    str(row["superseded_by"]),
                )
            if str(row["confidence_state"]) == VerificationState.CONTRADICTED.value:
                return TemporalCheck(VerificationState.CONTRADICTED, "Stored claim is contradicted.")
            if str(row["confidence_state"]) == VerificationState.STALE.value:
                return TemporalCheck(VerificationState.STALE, "Stored claim is marked stale.")
    return TemporalCheck(VerificationState.SUPPORTED, "No stored supersession/staleness signal.")
