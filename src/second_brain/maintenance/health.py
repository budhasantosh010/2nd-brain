"""Source integrity and operational health checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from second_brain.ingest.fingerprint import sha256_file
from second_brain.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class IntegrityFinding:
    source_id: str
    ok: bool
    detail: str


def verify_source_integrity(store: SQLiteStore, *, limit: int | None = None) -> list[IntegrityFinding]:
    sql = "SELECT id, content_hash, raw_path FROM sources ORDER BY ingested_at DESC"
    params: tuple[object, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    with store.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    findings: list[IntegrityFinding] = []
    for row in rows:
        source_id = str(row["id"])
        raw_value = row["raw_path"]
        if not raw_value:
            findings.append(IntegrityFinding(source_id, False, "Canonical raw path is missing."))
            continue
        raw_path = Path(str(raw_value))
        if not raw_path.exists():
            findings.append(IntegrityFinding(source_id, False, "Canonical raw file does not exist."))
            continue
        actual = sha256_file(raw_path)
        expected = str(row["content_hash"])
        findings.append(
            IntegrityFinding(
                source_id,
                actual == expected,
                "SHA256 matches." if actual == expected else f"CORRUPTION: expected {expected}, got {actual}",
            )
        )
    return findings
