"""Single-writer canonical transaction manager with reversible DB/index snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from second_brain.exceptions import TransactionError
from second_brain.models import OperationPlan, PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore
from second_brain.transactions.db_mutations import (
    DatabaseMutationPlan,
    TransactionSnapshot,
    capture_snapshot,
    restore_snapshot,
    snapshots_equal,
)

DBAction = Callable[[sqlite3.Connection], None]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TransactionManager:
    def __init__(self, paths: BrainPaths | None = None, store: SQLiteStore | None = None) -> None:
        self.paths = paths or BrainPaths.discover()
        self.store = store or SQLiteStore(self.paths.db)
        self.paths.ensure_runtime_dirs()
        self.store.initialize()

    @contextmanager
    def _writer_lock(self):  # type: ignore[no-untyped-def]
        lock_path = self.paths.locks / "writer.lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise TransactionError(f"Canonical writer lock is already held: {lock_path}") from exc
        try:
            os.write(fd, f"pid={os.getpid()}\n".encode())
            os.close(fd)
            yield
        finally:
            with suppress(OSError):
                os.close(fd)
            lock_path.unlink(missing_ok=True)

    def apply(
        self,
        plan: OperationPlan,
        db_action: DBAction | None = None,
        db_plan: DatabaseMutationPlan | None = None,
    ) -> str:
        """Apply canonical files and declared DB/index mutations as one logical operation.

        A DB callback is allowed only when its affected logical rows are declared.  The before
        snapshot is persisted while the writer lock is held, before any canonical mutation.
        Therefore both explicit rollback and crash recovery can restore the exact logical state
        without replacing the whole SQLite database.
        """

        if plan.permission_level >= 3:
            raise TransactionError("Level 3 operations cannot be applied automatically")
        if db_action is not None and db_plan is None:
            raise TransactionError(
                "Database mutations require a reversible DatabaseMutationPlan"
            )

        history_dir = self.paths.history / plan.operation_id
        transaction_dir = self.paths.transactions / plan.operation_id
        history_dir.mkdir(parents=True, exist_ok=True)
        transaction_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = transaction_dir / "manifest.json"
        ledger_path = self.paths.brain / "ledgers" / f"{plan.operation_id}.json"

        resolved = [(write, self._resolve_target(write)) for write in plan.writes]
        self._verify_preconditions(resolved)
        manifest: dict[str, Any] = {
            "operation_id": plan.operation_id,
            "description": plan.description,
            "permission_level": plan.permission_level,
            "created_at": plan.created_at.isoformat(),
            "state": "planned",
            "writes": [],
            "database": None,
        }
        self._write_json_atomic(manifest_path, manifest)
        self._record_operation(plan, "planned")

        with self._writer_lock():
            self._verify_preconditions(resolved)
            database_before: TransactionSnapshot | None = None
            if db_plan is not None:
                with self.store.connect() as conn:
                    database_before = capture_snapshot(conn, db_plan)
                manifest["database"] = {
                    "plan": db_plan.model_dump(mode="json"),
                    "before": database_before.model_dump(mode="json"),
                    "after": None,
                }

            backup_entries = self._backup_targets(resolved, history_dir)
            manifest["writes"] = backup_entries
            manifest["state"] = "applying"
            self._write_json_atomic(manifest_path, manifest)
            self._record_operation(plan, "applying")

            try:
                for write, target in resolved:
                    self._atomic_text_replace(target, write.content)
                if db_action is not None:
                    with self.store.transaction() as conn:
                        db_action(conn)
                if db_plan is not None:
                    with self.store.connect() as conn:
                        database_after = capture_snapshot(conn, db_plan)
                    database_payload = manifest.get("database")
                    if isinstance(database_payload, dict):
                        database_payload["after"] = database_after.model_dump(mode="json")

                manifest["state"] = "applied"
                manifest["completed_at"] = datetime.now(UTC).isoformat()
                self._write_json_atomic(manifest_path, manifest)
                self._write_json_atomic(ledger_path, manifest)
                self._record_operation(plan, "applied", completed=True)
                return plan.operation_id
            except Exception as exc:
                rollback_error: Exception | None = None
                try:
                    self._restore_from_entries(backup_entries, history_dir)
                    if database_before is not None:
                        with self.store.transaction() as conn:
                            restore_snapshot(conn, database_before)
                except Exception as rollback_exc:  # pragma: no cover - catastrophic path
                    rollback_error = rollback_exc
                manifest["state"] = "failed"
                manifest["error_type"] = type(exc).__name__
                manifest["error_message"] = str(exc)
                manifest["rollback_error"] = str(rollback_error) if rollback_error else None
                self._write_json_atomic(manifest_path, manifest)
                self._write_json_atomic(ledger_path, manifest)
                self._record_operation(
                    plan,
                    "failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                if rollback_error:
                    raise TransactionError(
                        f"Operation failed and rollback also failed: {rollback_error}"
                    ) from exc
                raise TransactionError(f"Operation failed and was rolled back: {exc}") from exc

    def rollback(self, operation_id: str) -> str:
        """Apply a compensating operation that restores the operation's bounded prior state."""

        transaction_dir = self.paths.transactions / operation_id
        manifest_path = transaction_dir / "manifest.json"
        if not manifest_path.exists():
            raise TransactionError(f"Operation manifest not found: {operation_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("writes", [])
        if not isinstance(entries, list):
            raise TransactionError(f"Invalid operation manifest: {operation_id}")
        if manifest.get("state") != "applied":
            raise TransactionError(
                f"Only a completed applied operation can be rolled back: {operation_id}"
            )
        if manifest.get("rolled_back_by"):
            raise TransactionError(
                f"Operation already has a compensating rollback: {manifest['rolled_back_by']}"
            )

        db_plan, database_before, database_after = self._database_manifest(manifest)
        history_dir = self.paths.history / operation_id
        rollback_id = f"OP-{uuid4()}"
        rollback_plan = OperationPlan(
            operation_id=rollback_id,
            created_at=datetime.now(UTC),
            permission_level=1,
            description=f"Rollback of {operation_id}",
            writes=[],
            metadata={"rollback_of": operation_id},
        )
        rollback_history = self.paths.history / rollback_id
        rollback_transaction = self.paths.transactions / rollback_id
        rollback_history.mkdir(parents=True, exist_ok=True)
        rollback_transaction.mkdir(parents=True, exist_ok=True)
        rollback_manifest_path = rollback_transaction / "manifest.json"
        rollback_manifest: dict[str, Any] = {
            "operation_id": rollback_id,
            "rollback_of": operation_id,
            "description": rollback_plan.description,
            "permission_level": 1,
            "created_at": rollback_plan.created_at.isoformat(),
            "state": "planned",
            "writes": [],
            "database": None,
        }
        self._write_json_atomic(rollback_manifest_path, rollback_manifest)
        self._record_operation(rollback_plan, "planned")

        with self._writer_lock():
            self._verify_rollback_file_preconditions(entries)
            if db_plan is not None and database_after is not None:
                with self.store.connect() as conn:
                    current_snapshot = capture_snapshot(conn, db_plan)
                if not snapshots_equal(current_snapshot, database_after):
                    raise TransactionError(
                        "Rollback refused because affected database rows changed after the operation"
                    )
                rollback_manifest["database"] = {
                    "plan": db_plan.model_dump(mode="json"),
                    "before_rollback": current_snapshot.model_dump(mode="json"),
                    "target": (
                        database_before.model_dump(mode="json")
                        if database_before is not None
                        else None
                    ),
                }

            rollback_manifest["writes"] = self._backup_manifest_targets(
                entries,
                rollback_history,
            )
            rollback_manifest["state"] = "applying"
            self._write_json_atomic(rollback_manifest_path, rollback_manifest)
            self._record_operation(rollback_plan, "applying")

            self._restore_from_entries(entries, history_dir)
            if database_before is not None and db_plan is not None:
                with self.store.transaction() as conn:
                    restore_snapshot(conn, database_before)
                with self.store.connect() as conn:
                    restored = capture_snapshot(conn, db_plan)
                if not snapshots_equal(restored, database_before):
                    raise TransactionError(
                        f"Rollback consistency validation failed for {operation_id}"
                    )
                database_record = rollback_manifest.get("database")
                if isinstance(database_record, dict):
                    database_record["after_rollback"] = restored.model_dump(mode="json")

            rollback_manifest["state"] = "applied"
            rollback_manifest["completed_at"] = datetime.now(UTC).isoformat()
            self._write_json_atomic(rollback_manifest_path, rollback_manifest)
            self._write_json_atomic(
                self.paths.brain / "ledgers" / f"{rollback_id}.json",
                rollback_manifest,
            )
            self._record_operation(rollback_plan, "applied", completed=True)

            rollback_events = manifest.setdefault("rollback_events", [])
            if not isinstance(rollback_events, list):
                rollback_events = []
                manifest["rollback_events"] = rollback_events
            rollback_events.append(
                {
                    "operation_id": rollback_id,
                    "rolled_back_at": datetime.now(UTC).isoformat(),
                }
            )
            manifest["rolled_back_by"] = rollback_id
            self._write_json_atomic(manifest_path, manifest)
            self._write_json_atomic(
                self.paths.brain / "ledgers" / f"{operation_id}.json",
                manifest,
            )
        return rollback_id

    def recover_interrupted(self) -> list[str]:
        recovered: list[str] = []
        for manifest_path in sorted(self.paths.transactions.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("state") != "applying":
                continue
            operation_id = str(manifest.get("operation_id", manifest_path.parent.name))
            entries = manifest.get("writes", [])
            if not isinstance(entries, list):
                continue
            _db_plan, database_before, _database_after = self._database_manifest(manifest)
            with self._writer_lock():
                self._restore_from_entries(entries, self.paths.history / operation_id)
                if database_before is not None:
                    with self.store.transaction() as conn:
                        restore_snapshot(conn, database_before)
                manifest["state"] = "recovered_rollback"
                manifest["recovered_at"] = datetime.now(UTC).isoformat()
                self._write_json_atomic(manifest_path, manifest)
                self._write_json_atomic(
                    self.paths.brain / "ledgers" / f"{operation_id}.json",
                    manifest,
                )
                with self.store.transaction() as conn:
                    conn.execute(
                        "UPDATE operations SET status = ?, completed_at = ? WHERE operation_id = ?",
                        ("recovered_rollback", datetime.now(UTC).isoformat(), operation_id),
                    )
            recovered.append(operation_id)
        return recovered

    def _database_manifest(
        self,
        manifest: dict[str, Any],
    ) -> tuple[
        DatabaseMutationPlan | None,
        TransactionSnapshot | None,
        TransactionSnapshot | None,
    ]:
        payload = manifest.get("database")
        if not isinstance(payload, dict):
            return None, None, None
        plan_payload = payload.get("plan")
        before_payload = payload.get("before")
        after_payload = payload.get("after")
        db_plan = (
            DatabaseMutationPlan.model_validate(plan_payload)
            if isinstance(plan_payload, dict)
            else None
        )
        before = (
            TransactionSnapshot.model_validate(before_payload)
            if isinstance(before_payload, dict)
            else None
        )
        after = (
            TransactionSnapshot.model_validate(after_payload)
            if isinstance(after_payload, dict)
            else None
        )
        return db_plan, before, after

    def _resolve_target(self, write: PlannedWrite) -> Path:
        raw = Path(write.path)
        target = raw.resolve() if raw.is_absolute() else (self.paths.vault / raw).resolve()
        vault = self.paths.vault.resolve()
        if target != vault and vault not in target.parents:
            raise TransactionError(f"Canonical write escapes vault: {write.path}")
        protected = {(vault / "AGENTS.md").resolve()}
        protected_system = (vault / "10 System").resolve()
        if plan_target_is_protected(target, protected, protected_system):
            raise TransactionError(f"Protected system file cannot be changed automatically: {target}")
        raw_root = (vault / "02 Sources" / "Raw").resolve()
        if target == raw_root or raw_root in target.parents:
            raise TransactionError(f"Raw evidence cannot be changed through generic transactions: {target}")
        return target

    def _verify_preconditions(self, resolved: list[tuple[PlannedWrite, Path]]) -> None:
        for write, target in resolved:
            if write.expected_hash is None:
                continue
            current_hash = _sha256_file(target) if target.exists() else "MISSING"
            if current_hash != write.expected_hash:
                raise TransactionError(
                    f"Precondition mismatch for {write.path}: expected {write.expected_hash}, got {current_hash}"
                )

    def _backup_targets(
        self,
        resolved: list[tuple[PlannedWrite, Path]],
        history_dir: Path,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        vault = self.paths.vault.resolve()
        for write, target in resolved:
            relative = target.relative_to(vault).as_posix()
            entry: dict[str, Any] = {
                "path": relative,
                "existed": target.exists(),
                "original_hash": _sha256_file(target) if target.exists() else None,
                "new_hash": _sha256_bytes(write.content.encode("utf-8")),
            }
            if target.exists():
                backup = history_dir / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                entry["backup"] = relative
            entries.append(entry)
        return entries

    def _restore_from_entries(self, entries: list[dict[str, Any]], history_dir: Path) -> None:
        vault = self.paths.vault.resolve()
        for entry in reversed(entries):
            relative = str(entry["path"])
            target = (vault / relative).resolve()
            if target != vault and vault not in target.parents:
                raise TransactionError(f"Rollback path escapes vault: {relative}")
            if bool(entry.get("existed")):
                backup = history_dir / str(entry.get("backup", relative))
                if not backup.exists():
                    raise TransactionError(f"Rollback backup missing: {backup}")
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(f".{target.name}.rollback.tmp")
                shutil.copy2(backup, temp)
                os.replace(temp, target)
            else:
                target.unlink(missing_ok=True)

    def _verify_rollback_file_preconditions(self, entries: list[dict[str, Any]]) -> None:
        vault = self.paths.vault.resolve()
        for entry in entries:
            relative = str(entry["path"])
            target = (vault / relative).resolve()
            expected = entry.get("new_hash")
            current = _sha256_file(target) if target.exists() else None
            if expected != current:
                raise TransactionError(
                    f"Rollback refused because {relative} changed after the operation"
                )

    def _backup_manifest_targets(
        self,
        entries: list[dict[str, Any]],
        history_dir: Path,
    ) -> list[dict[str, Any]]:
        vault = self.paths.vault.resolve()
        result: list[dict[str, Any]] = []
        for entry in entries:
            relative = str(entry["path"])
            target = (vault / relative).resolve()
            record: dict[str, Any] = {
                "path": relative,
                "existed": target.exists(),
                "original_hash": _sha256_file(target) if target.exists() else None,
                "restores_hash": entry.get("original_hash"),
            }
            if target.exists():
                backup = history_dir / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                record["backup"] = relative
            result.append(record)
        return result

    @staticmethod
    def _atomic_text_replace(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        data = content.encode("utf-8")
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)

    def _record_operation(
        self,
        plan: OperationPlan,
        status: str,
        *,
        completed: bool = False,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO operations(
                    operation_id, status, description, permission_level, created_at,
                    completed_at, payload_json, error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operation_id) DO UPDATE SET
                    status=excluded.status,
                    completed_at=excluded.completed_at,
                    payload_json=excluded.payload_json,
                    error_type=excluded.error_type,
                    error_message=excluded.error_message
                """,
                (
                    plan.operation_id,
                    status,
                    plan.description,
                    plan.permission_level,
                    plan.created_at.isoformat(),
                    datetime.now(UTC).isoformat() if completed else None,
                    json.dumps(plan.model_dump(mode="json"), sort_keys=True),
                    error_type,
                    error_message,
                ),
            )


def plan_target_is_protected(target: Path, protected: set[Path], protected_system: Path) -> bool:
    return target in protected or target == protected_system or protected_system in target.parents
