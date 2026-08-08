"""Single-writer atomic file transaction manager with backup and rollback."""

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

from second_brain.exceptions import TransactionError
from second_brain.models import OperationPlan, PlannedWrite
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore

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

    def apply(self, plan: OperationPlan, db_action: DBAction | None = None) -> str:
        if plan.permission_level >= 3:
            raise TransactionError("Level 3 operations cannot be applied automatically")
        history_dir = self.paths.history / plan.operation_id
        transaction_dir = self.paths.transactions / plan.operation_id
        history_dir.mkdir(parents=True, exist_ok=True)
        transaction_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = transaction_dir / "manifest.json"
        ledger_path = self.paths.brain / "ledgers" / f"{plan.operation_id}.json"

        resolved = [(write, self._resolve_target(write)) for write in plan.writes]
        self._verify_preconditions(resolved)
        manifest = {
            "operation_id": plan.operation_id,
            "description": plan.description,
            "permission_level": plan.permission_level,
            "created_at": plan.created_at.isoformat(),
            "state": "planned",
            "writes": [],
        }
        self._write_json_atomic(manifest_path, manifest)
        self._record_operation(plan, "planned")

        with self._writer_lock():
            self._verify_preconditions(resolved)
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

    def rollback(self, operation_id: str) -> None:
        transaction_dir = self.paths.transactions / operation_id
        manifest_path = transaction_dir / "manifest.json"
        if not manifest_path.exists():
            raise TransactionError(f"Operation manifest not found: {operation_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("writes", [])
        if not isinstance(entries, list):
            raise TransactionError(f"Invalid operation manifest: {operation_id}")
        history_dir = self.paths.history / operation_id
        with self._writer_lock():
            self._restore_from_entries(entries, history_dir)
            manifest["state"] = "rolled_back"
            manifest["rolled_back_at"] = datetime.now(UTC).isoformat()
            self._write_json_atomic(manifest_path, manifest)
            self._write_json_atomic(self.paths.brain / "ledgers" / f"{operation_id}.json", manifest)
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE operations SET status = ?, completed_at = ? WHERE operation_id = ?",
                    ("rolled_back", datetime.now(UTC).isoformat(), operation_id),
                )

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
            with self._writer_lock():
                self._restore_from_entries(entries, self.paths.history / operation_id)
                manifest["state"] = "recovered_rollback"
                manifest["recovered_at"] = datetime.now(UTC).isoformat()
                self._write_json_atomic(manifest_path, manifest)
                self._write_json_atomic(
                    self.paths.brain / "ledgers" / f"{operation_id}.json", manifest
                )
                with self.store.transaction() as conn:
                    conn.execute(
                        "UPDATE operations SET status = ?, completed_at = ? WHERE operation_id = ?",
                        ("recovered_rollback", datetime.now(UTC).isoformat(), operation_id),
                    )
            recovered.append(operation_id)
        return recovered

    def _resolve_target(self, write: PlannedWrite) -> Path:
        raw = Path(write.path)
        target = raw.resolve() if raw.is_absolute() else (self.paths.vault / raw).resolve()
        vault = self.paths.vault.resolve()
        if target != vault and vault not in target.parents:
            raise TransactionError(f"Canonical write escapes vault: {write.path}")
        protected = {
            (vault / "AGENTS.md").resolve(),
        }
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
        self, resolved: list[tuple[PlannedWrite, Path]], history_dir: Path
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
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
