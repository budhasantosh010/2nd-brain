from __future__ import annotations

import json
import os

import pytest

from second_brain.config import load_config
from second_brain.exceptions import TransactionError
from second_brain.locks import (
    LockHeldError,
    LockMetadata,
    ProcessLockManager,
    current_process_started_at,
)
from second_brain.maintenance.daemon import BrainDaemon
from second_brain.models import PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.storage.durable import read_jsonl
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.db_mutations import DatabaseMutationPlan, DatabaseRowScope
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan


def _write_lock(paths: BrainPaths, lock_type: str, metadata: LockMetadata) -> None:
    path = paths.locks / f"{lock_type}.lock"
    path.write_text(
        json.dumps(metadata.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _dead_lock(lock_type: str) -> LockMetadata:
    return LockMetadata(
        pid=2_000_000_000,
        process_started_at=1.0,
        hostname="synthetic-dead-host",
        created_at="2026-01-01T00:00:00+00:00",
        lock_type=lock_type,  # type: ignore[arg-type]
        operation_id="OP-dead-lock-fixture" if lock_type == "writer" else None,
    )


def test_stale_writer_lock_is_cleared_and_transaction_continues(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    _write_lock(isolated_brain, "writer", _dead_lock("writer"))
    manager = TransactionManager(isolated_brain, store)
    target = isolated_brain.vault / "07 Operations" / "CURRENT.md"
    plan = build_plan(
        "stale writer recovery fixture",
        [
            PlannedWrite(
                path="07 Operations/CURRENT.md",
                content="# Current Operations\n\nstale writer recovered\n",
                expected_hash=None,
            )
        ],
        permission_level=1,
    )
    manager.apply(plan)
    assert "stale writer recovered" in target.read_text(encoding="utf-8")
    assert not (isolated_brain.locks / "writer.lock").exists()
    events = read_jsonl(isolated_brain.brain / "ledgers" / "stale-lock-recovery.jsonl")
    assert any(event.get("lock_type") == "writer" for event in events)


def test_stale_daemon_lock_is_cleared_and_daemon_can_acquire(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    _write_lock(isolated_brain, "daemon", _dead_lock("daemon"))
    daemon = BrainDaemon(isolated_brain, load_config(isolated_brain), store)
    with daemon._daemon_lock():
        metadata = json.loads((isolated_brain.locks / "daemon.lock").read_text(encoding="utf-8"))
        assert metadata["pid"] == os.getpid()
        assert metadata["lock_type"] == "daemon"
    assert not (isolated_brain.locks / "daemon.lock").exists()


def test_live_lock_rejects_second_owner_and_pid_reuse_is_recovered(
    isolated_brain: BrainPaths,
) -> None:
    manager = ProcessLockManager(isolated_brain.locks, isolated_brain.brain / "ledgers")
    with manager.acquire("writer"):
        with pytest.raises(LockHeldError, match="live pid"):
            manager.clear_if_stale("writer")
        with pytest.raises(LockHeldError), manager.acquire("writer"):
            pass

    reused = LockMetadata(
        pid=os.getpid(),
        process_started_at=current_process_started_at() - 86_400,
        hostname="same-host-new-process",
        created_at="2026-01-01T00:00:00+00:00",
        lock_type="writer",
    )
    _write_lock(isolated_brain, "writer", reused)
    assert manager.clear_if_stale("writer") is True
    assert not (isolated_brain.locks / "writer.lock").exists()


def test_interrupted_applying_operation_plus_stale_writer_lock_recovers_files_and_db(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    manager = TransactionManager(isolated_brain, store)
    target = isolated_brain.vault / "07 Operations" / "CURRENT.md"
    before = target.read_text(encoding="utf-8")
    plan = build_plan(
        "crash recovery file and database fixture",
        [
            PlannedWrite(
                path="07 Operations/CURRENT.md",
                content="# Current Operations\n\ncrash-after-apply\n",
            )
        ],
        permission_level=1,
    )

    def db_action(conn):  # type: ignore[no-untyped-def]
        conn.execute(
            """
            INSERT INTO questions(id, question, status, searched_json, found_json, missing_evidence, created_at, metadata_json)
            VALUES ('QUE-crash-recovery', 'temporary crash state', 'open', '[]', '[]', '', '2026-01-01T00:00:00+00:00', '{}')
            """
        )

    manager.apply(
        plan,
        db_action=db_action,
        db_plan=DatabaseMutationPlan(
            scopes=[
                DatabaseRowScope(
                    table="questions",
                    where_sql="id = ?",
                    params=["QUE-crash-recovery"],
                )
            ],
            description="Crash recovery fixture",
        ),
    )
    assert "crash-after-apply" in target.read_text(encoding="utf-8")
    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM questions WHERE id='QUE-crash-recovery'"
        ).fetchone()[0] == 1

    manifest_path = isolated_brain.transactions / plan.operation_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "applying"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_lock(isolated_brain, "writer", _dead_lock("writer"))

    recovered = TransactionManager(isolated_brain, store).recover_interrupted()
    assert recovered == [plan.operation_id]
    assert target.read_text(encoding="utf-8") == before
    with store.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM questions WHERE id='QUE-crash-recovery'"
        ).fetchone()[0] == 0
    assert not (isolated_brain.locks / "writer.lock").exists()
    recovered_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert recovered_manifest["state"] == "recovered_rollback"


def test_daemon_prepare_startup_refuses_live_daemon_owner(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    daemon = BrainDaemon(isolated_brain, load_config(isolated_brain), store)
    manager = ProcessLockManager(isolated_brain.locks, isolated_brain.brain / "ledgers")
    with manager.acquire("daemon"), pytest.raises(LockHeldError):
        daemon.prepare_startup()


def test_transaction_manager_rejects_live_writer_owner(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
) -> None:
    manager = ProcessLockManager(isolated_brain.locks, isolated_brain.brain / "ledgers")
    with manager.acquire("writer"):
        plan = build_plan(
            "live writer rejection",
            [PlannedWrite(path="07 Operations/CURRENT.md", content="# blocked\n")],
            permission_level=1,
        )
        with pytest.raises(TransactionError, match="live pid"):
            TransactionManager(isolated_brain, store).apply(plan)
