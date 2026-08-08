"""Audited source-level cloud eligibility and trusted-path controls."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import frontmatter

from second_brain.exceptions import SecurityViolation
from second_brain.ingest.security import TrustStore, classify_source
from second_brain.models import Sensitivity
from second_brain.paths import BrainPaths
from second_brain.storage.durable import append_jsonl_event, atomic_json
from second_brain.storage.sqlite import SQLiteStore


class SourceEgressService:
    def __init__(
        self,
        paths: BrainPaths | None = None,
        store: SQLiteStore | None = None,
    ) -> None:
        self.paths = paths or BrainPaths.discover()
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.trust = TrustStore(self.paths)
        self.audit_path = self.paths.brain / "ledgers" / "egress-audit.jsonl"

    def show(self, source_id: str) -> dict[str, Any]:
        row = self.store.source_by_id(source_id)
        if row is None:
            raise KeyError(f"Source not found: {source_id}")
        manifest_path = self.paths.manifests / f"{source_id}.json"
        reasons: list[str] = []
        if manifest_path.exists():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                values = payload.get("security_reasons", []) if isinstance(payload, dict) else []
                if isinstance(values, list):
                    reasons = [str(value) for value in values]
            except (OSError, json.JSONDecodeError):
                pass
        return {
            "source_id": source_id,
            "title": str(row["title"]),
            "original_path": str(row["original_path"]),
            "raw_path": str(row["raw_path"] or ""),
            "sensitivity": str(row["sensitivity"]),
            "security_reasons": reasons,
            "cloud_eligible": str(row["sensitivity"]) == Sensitivity.CLOUD_ALLOWED.value,
        }

    def allow_cloud(self, source_id: str) -> dict[str, Any]:
        row = self.store.source_by_id(source_id)
        if row is None:
            raise KeyError(f"Source not found: {source_id}")
        raw = Path(str(row["raw_path"] or ""))
        if not raw.is_file():
            raise FileNotFoundError(f"Preserved raw source missing: {raw}")
        # Re-scan the preserved bytes. Explicit allow can never override secret/sensitive detection.
        classification = classify_source(
            raw,
            scan_secrets=True,
            explicit_cloud_allowed=True,
        )
        if classification.sensitivity in {Sensitivity.BLOCKED, Sensitivity.SENSITIVE}:
            raise SecurityViolation(
                "Cloud permission denied by higher-priority security classification: "
                + ", ".join(classification.reasons)
            )
        self._set_permission(
            source_id,
            Sensitivity.CLOUD_ALLOWED,
            reason="explicit source allow-cloud",
        )
        return self.show(source_id)

    def local_only(self, source_id: str) -> dict[str, Any]:
        if self.store.source_by_id(source_id) is None:
            raise KeyError(f"Source not found: {source_id}")
        self._set_permission(source_id, Sensitivity.LOCAL_ONLY, reason="explicit source local-only")
        return self.show(source_id)

    def _set_permission(self, source_id: str, sensitivity: Sensitivity, *, reason: str) -> None:
        before = self.show(source_id)
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE sources SET sensitivity=? WHERE id=?",
                (sensitivity.value, source_id),
            )
        self._update_manifest(source_id, sensitivity, reason)
        self._update_source_record(source_id, sensitivity)
        event_id = f"EGR-{uuid4()}"
        append_jsonl_event(
            self.audit_path,
            {
                "event_id": event_id,
                "action": "source_permission_change",
                "timestamp": datetime.now(UTC).isoformat(),
                "source_id": source_id,
                "before": before["sensitivity"],
                "after": sensitivity.value,
                "reason": reason,
            },
            event_id=event_id,
        )

    def _update_manifest(self, source_id: str, sensitivity: Sensitivity, reason: str) -> None:
        path = self.paths.manifests / f"{source_id}.json"
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        source = payload.get("source")
        if isinstance(source, dict):
            source["sensitivity"] = sensitivity.value
        payload["permission_override"] = {
            "sensitivity": sensitivity.value,
            "reason": reason,
            "changed_at": datetime.now(UTC).isoformat(),
        }
        atomic_json(path, payload)

    def _update_source_record(self, source_id: str, sensitivity: Sensitivity) -> None:
        path = self.paths.records / f"{source_id}.md"
        if not path.exists():
            return
        post = frontmatter.load(path)
        post.metadata["sensitivity"] = sensitivity.value
        path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
