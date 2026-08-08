"""Provenance/source-locator validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from second_brain.models import SearchHit
from second_brain.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class ProvenanceCheck:
    available: bool
    source_id: str | None
    locator_available: bool
    detail: str


def check_provenance(store: SQLiteStore, hit: SearchHit) -> ProvenanceCheck:
    source_id = hit.source_id
    if hit.object_type == "source" and source_id is None:
        source_id = hit.object_id
    if source_id is None:
        return ProvenanceCheck(False, None, False, "Result has no source provenance.")
    row = store.source_by_id(source_id)
    if row is None:
        return ProvenanceCheck(False, source_id, False, "Referenced source does not exist.")
    raw_path = row["raw_path"]
    if raw_path and not Path(str(raw_path)).exists():
        return ProvenanceCheck(False, source_id, False, "Source record exists but raw evidence is missing.")

    if hit.object_type == "source-segment":
        with store.connect() as conn:
            segment = conn.execute(
                "SELECT locator FROM source_segments WHERE segment_id = ? AND source_id = ?",
                (hit.object_id, source_id),
            ).fetchone()
        if segment is None:
            return ProvenanceCheck(True, source_id, False, "Source exists but segment locator is missing.")
        locator = str(segment["locator"])
        if hit.locator and locator != hit.locator:
            return ProvenanceCheck(True, source_id, False, "Stored segment locator does not match result locator.")
        return ProvenanceCheck(True, source_id, True, "Source and segment locator are available.")

    return ProvenanceCheck(True, source_id, bool(hit.locator), "Source evidence is available.")
