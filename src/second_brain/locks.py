"""Crash-safe single-owner lock files with process-liveness/PID-reuse checks."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import psutil
from pydantic import BaseModel, Field

from second_brain.storage.durable import append_jsonl_event

LockType = Literal["writer", "daemon"]


class LockMetadata(BaseModel):
    schema_version: str = "process-lock-v1"
    token: str = Field(default_factory=lambda: str(uuid4()))
    pid: int
    process_started_at: float
    hostname: str
    created_at: str
    lock_type: LockType
    operation_id: str | None = None


class LockHeldError(RuntimeError):
    pass


def process_started_at(pid: int) -> float | None:
    try:
        return float(psutil.Process(pid).create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return None


def current_process_started_at() -> float:
    value = process_started_at(os.getpid())
    return value if value is not None else float(datetime.now(UTC).timestamp())


def lock_owner_is_live(metadata: LockMetadata) -> bool:
    observed = process_started_at(metadata.pid)
    if observed is None:
        return False
    # Process creation timestamps have platform-specific precision. A materially different
    # creation time means the PID has been reused and the recorded owner is gone.
    return abs(observed - metadata.process_started_at) < 1.0


def read_lock(path: Path) -> LockMetadata | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return LockMetadata.model_validate(payload)
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    # Phase 1/2 compatibility: legacy lock files used key=value lines.
    try:
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        pid = int(values.get("pid", "0"))
        observed = process_started_at(pid)
        if pid > 0 and observed is not None:
            return LockMetadata(
                pid=pid,
                process_started_at=observed,
                hostname=socket.gethostname(),
                created_at=values.get("started", datetime.now(UTC).isoformat()),
                lock_type="writer" if path.name == "writer.lock" else "daemon",
            )
    except (OSError, ValueError):
        pass
    return None


class ProcessLockManager:
    def __init__(self, locks_dir: Path, ledgers_dir: Path) -> None:
        self.locks_dir = locks_dir
        self.ledgers_dir = ledgers_dir
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        self.ledgers_dir.mkdir(parents=True, exist_ok=True)

    def path(self, lock_type: LockType) -> Path:
        return self.locks_dir / f"{lock_type}.lock"

    def clear_if_stale(self, lock_type: LockType) -> bool:
        path = self.path(lock_type)
        if not path.exists():
            return False
        metadata = read_lock(path)
        if metadata is not None and lock_owner_is_live(metadata):
            raise LockHeldError(
                f"{lock_type} lock belongs to live pid={metadata.pid} "
                f"started={metadata.process_started_at}: {path}"
            )
        recovery_id = f"LKR-{uuid4()}"
        event = {
            "event_id": recovery_id,
            "event": "stale_lock_recovered",
            "lock_type": lock_type,
            "path": str(path),
            "recorded_owner": metadata.model_dump(mode="json") if metadata else None,
            "recovered_at": datetime.now(UTC).isoformat(),
            "recovered_by_pid": os.getpid(),
            "hostname": socket.gethostname(),
        }
        stale_copy = path.with_name(
            f"{path.name}.stale.{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
        )
        try:
            os.replace(path, stale_copy)
            stale_copy.unlink(missing_ok=True)
        except FileNotFoundError:
            return False
        append_jsonl_event(
            self.ledgers_dir / "stale-lock-recovery.jsonl",
            event,
            event_id=recovery_id,
        )
        return True

    @contextmanager
    def acquire(
        self,
        lock_type: LockType,
        *,
        operation_id: str | None = None,
    ) -> Iterator[LockMetadata]:
        path = self.path(lock_type)
        for attempt in range(2):
            metadata = LockMetadata(
                pid=os.getpid(),
                process_started_at=current_process_started_at(),
                hostname=socket.gethostname(),
                created_at=datetime.now(UTC).isoformat(),
                lock_type=lock_type,
                operation_id=operation_id,
            )
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                if attempt == 0:
                    self.clear_if_stale(lock_type)
                    continue
                raise LockHeldError(f"Unable to acquire {lock_type} lock: {path}") from exc
            try:
                data = (json.dumps(metadata.model_dump(mode="json"), sort_keys=True) + "\n").encode()
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                yield metadata
            finally:
                # Never unlink a lock replaced by another owner after an abnormal edge case.
                current = read_lock(path)
                if current is not None and current.token == metadata.token:
                    with suppress(OSError):
                        path.unlink()
            return
        raise LockHeldError(f"Unable to acquire {lock_type} lock: {path}")
