from __future__ import annotations

import json

from second_brain.doctor import doctor
from second_brain.paths import BrainPaths
from second_brain.rebuild import RebuildService


def test_phase25_doctor_covers_release_health_surfaces(isolated_brain: BrainPaths) -> None:
    RebuildService(isolated_brain).rebuild()
    checks = doctor(isolated_brain)
    by_name = {check.name: check for check in checks}
    required = {
        "vault",
        "write_permissions",
        "schema_version",
        "database",
        "fts5",
        "embedding_provider",
        "embedding_profile",
        "vector_freshness",
        "raw_source_integrity",
        "resolution_ledgers",
        "project_history",
        "knowledge_gap_history",
        "transaction_consistency",
        "writer_lock",
        "daemon_lock",
        "daemon_heartbeat",
        "queue",
        "ai_provider",
        "mcp",
        "obsidian",
        "pending_reviews",
        "backup_freshness",
        "canonical_consistency",
    }
    assert required <= set(by_name)
    failures = {name: check.detail for name, check in by_name.items() if not check.ok}
    assert failures == {}


def test_doctor_reports_stale_writer_lock_without_deleting_it(isolated_brain: BrainPaths) -> None:
    RebuildService(isolated_brain).rebuild()
    lock = isolated_brain.locks / "writer.lock"
    lock.write_text(
        json.dumps(
            {
                "schema_version": "process-lock-v1",
                "token": "stale-doctor-test",
                "pid": 999999,
                "process_started_at": 1.0,
                "hostname": "test-host",
                "created_at": "2026-01-01T00:00:00+00:00",
                "lock_type": "writer",
                "operation_id": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    check = next(item for item in doctor(isolated_brain) if item.name == "writer_lock")
    assert not check.ok
    assert "stale" in check.detail.lower()
    assert lock.exists()
