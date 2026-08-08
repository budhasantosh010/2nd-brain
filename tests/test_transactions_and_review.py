from __future__ import annotations

import json

import pytest

from second_brain.exceptions import TransactionError
from second_brain.models import PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.review.service import ReviewService
from second_brain.storage.markdown import file_sha256
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.db_mutations import DatabaseMutationPlan, DatabaseRowScope
from second_brain.transactions.manager import TransactionManager
from second_brain.transactions.plan import build_plan


def test_atomic_apply_and_manual_rollback_restore_previous_file(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    target = isolated_brain.vault / "03 Knowledge" / "Concepts" / "atomic.md"
    target.write_text("old value\n", encoding="utf-8")
    manager = TransactionManager(isolated_brain, store)
    plan = build_plan(
        "atomic test",
        [
            PlannedWrite(
                path="03 Knowledge/Concepts/atomic.md",
                content="new value\n",
                expected_hash=file_sha256(target),
            )
        ],
    )
    operation_id = manager.apply(plan)
    assert target.read_text(encoding="utf-8") == "new value\n"
    assert (isolated_brain.history / operation_id / "03 Knowledge" / "Concepts" / "atomic.md").is_file()
    manager.rollback(operation_id)
    assert target.read_text(encoding="utf-8") == "old value\n"


def test_precondition_mismatch_rejects_write_without_mutation(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    target = isolated_brain.vault / "03 Knowledge" / "Concepts" / "precondition.md"
    target.write_text("current\n", encoding="utf-8")
    plan = build_plan(
        "stale edit",
        [
            PlannedWrite(
                path="03 Knowledge/Concepts/precondition.md",
                content="wrong replacement\n",
                expected_hash="0" * 64,
            )
        ],
    )
    with pytest.raises(TransactionError, match="Precondition mismatch"):
        TransactionManager(isolated_brain, store).apply(plan)
    assert target.read_text(encoding="utf-8") == "current\n"


def test_database_failure_rolls_back_files_and_database_transaction(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    target = isolated_brain.vault / "03 Knowledge" / "Concepts" / "db-failure.md"
    target.write_text("before\n", encoding="utf-8")
    manager = TransactionManager(isolated_brain, store)
    plan = build_plan(
        "db failure rollback",
        [
            PlannedWrite(
                path="03 Knowledge/Concepts/db-failure.md",
                content="after\n",
                expected_hash=file_sha256(target),
            )
        ],
    )

    def db_action(conn) -> None:  # type: ignore[no-untyped-def]
        conn.execute(
            "INSERT INTO questions(id,question,status,searched_json,found_json,missing_evidence,created_at,metadata_json) "
            "VALUES ('QUE-rollback','temporary','open','[]','[]','','2000-01-01T00:00:00+00:00','{}')"
        )
        raise RuntimeError("synthetic db failure")

    with pytest.raises(TransactionError, match="rolled back"):
        manager.apply(
            plan,
            db_action=db_action,
            db_plan=DatabaseMutationPlan(
                scopes=[
                    DatabaseRowScope(
                        table="questions",
                        where_sql="id = ?",
                        params=["QUE-rollback"],
                    )
                ]
            ),
        )
    assert target.read_text(encoding="utf-8") == "before\n"
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM questions WHERE id='QUE-rollback'").fetchone()[0] == 0


def test_writer_lock_prevents_concurrent_canonical_mutation(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    lock = isolated_brain.locks / "writer.lock"
    lock.write_text("synthetic lock", encoding="utf-8")
    plan = build_plan(
        "concurrent write",
        [PlannedWrite(path="03 Knowledge/Concepts/blocked.md", content="blocked\n")],
    )
    try:
        with pytest.raises(TransactionError, match="writer lock"):
            TransactionManager(isolated_brain, store).apply(plan)
    finally:
        lock.unlink(missing_ok=True)
    assert not (isolated_brain.vault / "03 Knowledge" / "Concepts" / "blocked.md").exists()


def test_interrupted_applying_operation_is_recovered_from_history(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    manager = TransactionManager(isolated_brain, store)
    operation_id = "OP-synthetic-recovery"
    relative = "03 Knowledge/Concepts/recovery.md"
    target = isolated_brain.vault / relative
    target.write_text("partially applied\n", encoding="utf-8")
    history_file = isolated_brain.history / operation_id / relative
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text("original\n", encoding="utf-8")
    manifest = {
        "operation_id": operation_id,
        "description": "synthetic interrupted operation",
        "permission_level": 1,
        "created_at": "2000-01-01T00:00:00+00:00",
        "state": "applying",
        "writes": [
            {
                "path": relative,
                "existed": True,
                "original_hash": None,
                "new_hash": None,
                "backup": relative,
            }
        ],
    }
    manifest_path = isolated_brain.transactions / operation_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO operations(operation_id,status,description,permission_level,created_at,payload_json) "
            "VALUES (?, 'applying', 'synthetic', 1, '2000-01-01T00:00:00+00:00', '{}')",
            (operation_id,),
        )
    recovered = manager.recover_interrupted()
    assert recovered == [operation_id]
    assert target.read_text(encoding="utf-8") == "original\n"
    final_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert final_manifest["state"] == "recovered_rollback"


def test_review_stage_reject_approve_and_rollback_file_change(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    target = isolated_brain.vault / "03 Knowledge" / "Concepts" / "reviewed.md"
    target.write_text("old reviewed value\n", encoding="utf-8")
    reviews = ReviewService(isolated_brain, store)

    reject_plan = build_plan(
        "reject proposal",
        [
            PlannedWrite(
                path="03 Knowledge/Concepts/reviewed.md",
                content="rejected value\n",
                expected_hash=file_sha256(target),
            )
        ],
        permission_level=2,
    )
    rejected = reviews.stage(
        reject_plan,
        review_type="knowledge-update",
        risk="medium",
        proposal="Test rejection",
        reason="Synthetic review test",
    )
    reviews.reject(rejected.review_id)
    assert target.read_text(encoding="utf-8") == "old reviewed value\n"
    assert reviews.get(rejected.review_id).status == "rejected"

    approve_plan = build_plan(
        "approve proposal",
        [
            PlannedWrite(
                path="03 Knowledge/Concepts/reviewed.md",
                content="approved value\n",
                expected_hash=file_sha256(target),
            )
        ],
        permission_level=2,
    )
    approved = reviews.stage(
        approve_plan,
        review_type="knowledge-update",
        risk="medium",
        proposal="Test approval",
        reason="Synthetic review test",
    )
    reviews.approve(approved.review_id)
    assert target.read_text(encoding="utf-8") == "approved value\n"
    assert reviews.get(approved.review_id).status == "applied"
    reviews.rollback(approved.review_id)
    assert target.read_text(encoding="utf-8") == "old reviewed value\n"
    assert reviews.get(approved.review_id).status == "rolled_back"


def test_protected_paths_and_raw_sources_cannot_use_generic_transaction_manager(
    isolated_brain: BrainPaths, store: SQLiteStore
) -> None:
    manager = TransactionManager(isolated_brain, store)
    for relative in ("AGENTS.md", "10 System/SYSTEM.md", "02 Sources/Raw/Other/forbidden.txt"):
        with pytest.raises(TransactionError, match="Protected|Raw evidence"):
            manager.apply(build_plan("forbidden", [PlannedWrite(path=relative, content="forbidden")]))
