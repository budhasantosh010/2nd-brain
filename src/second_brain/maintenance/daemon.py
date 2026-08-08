"""Single-instance background daemon: Inbox watch + durable work + missed maintenance."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime

from second_brain.config import BrainConfig, load_config
from second_brain.ingest.service import IngestionService
from second_brain.ingest.watcher import InboxWatcher
from second_brain.maintenance.monthly import MonthlyMaintenance
from second_brain.maintenance.nightly import NightlyMaintenance
from second_brain.maintenance.scheduler import MaintenanceScheduler
from second_brain.maintenance.weekly import WeeklyMaintenance
from second_brain.observability.logging import StructuredLogger
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore


class BrainDaemon:
    def __init__(
        self,
        paths: BrainPaths | None = None,
        config: BrainConfig | None = None,
        store: SQLiteStore | None = None,
    ) -> None:
        self.paths = paths or BrainPaths.discover()
        self.config = config or load_config(self.paths)
        self.store = store or SQLiteStore(self.paths.db)
        self.store.initialize()
        self.paths.ensure_runtime_dirs()
        self.scheduler = MaintenanceScheduler(self.paths, self.config)
        self.logger = StructuredLogger(self.paths, "daemon.jsonl")
        self.ingestion = IngestionService(self.paths, self.config, self.store)
        self.watcher = InboxWatcher(self.ingestion)
        self._stop = False

    def run_once(self) -> dict[str, object]:
        results: dict[str, object] = {}
        # Inbox is continuous work, not a nightly-only job. This catches files that arrived while
        # the machine/daemon was offline even when today's scheduled maintenance already succeeded.
        results["inbox_processed"] = NightlyMaintenance(
            self.paths, self.config, self.store
        ).process_inbox()
        due = self.scheduler.due()
        for routine in due:
            started = time.monotonic()
            try:
                if routine.name == "nightly":
                    value = NightlyMaintenance(self.paths, self.config, self.store).run()
                elif routine.name == "weekly":
                    value = WeeklyMaintenance(self.paths, self.config, self.store).run()
                elif routine.name == "monthly":
                    value = MonthlyMaintenance(self.paths, self.config, self.store).run()
                else:  # pragma: no cover - scheduler owns names
                    continue
                self.scheduler.mark_success(routine.name)
                results[routine.name] = value
                self.logger.log(
                    "maintenance_complete",
                    stage=routine.name,
                    duration=time.monotonic() - started,
                    result="success",
                    missed_recovery=routine.missed,
                )
            except Exception as exc:
                self.logger.log(
                    "maintenance_failed",
                    stage=routine.name,
                    duration=time.monotonic() - started,
                    result="failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    missed_recovery=routine.missed,
                )
                results[routine.name] = {"error_type": type(exc).__name__, "error": str(exc)}
        self._write_heartbeat("idle")
        return results

    def run_forever(self, poll_seconds: float = 60.0) -> None:
        with self._daemon_lock():
            self.logger.log("daemon_start", result="started")
            # Process pre-existing Inbox material and missed schedules before relying on FS events.
            self.run_once()
            self.watcher.start()
            try:
                while not self._stop:
                    self._write_heartbeat("running")
                    self.run_once()
                    time.sleep(max(poll_seconds, 1.0))
            finally:
                self.watcher.stop()
                self._write_heartbeat("stopped")
                self.logger.log("daemon_stop", result="stopped")

    def stop(self) -> None:
        self._stop = True

    @contextmanager
    def _daemon_lock(self) -> Iterator[None]:
        path = self.paths.locks / "daemon.lock"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"Another second-brain daemon appears active: {path}") from exc
        try:
            os.write(fd, f"pid={os.getpid()}\nstarted={datetime.now(UTC).isoformat()}\n".encode())
            os.close(fd)
            yield
        finally:
            with suppress(OSError):
                os.close(fd)
            path.unlink(missing_ok=True)

    def _write_heartbeat(self, state: str) -> None:
        path = self.paths.brain / "runtime" / "heartbeat.json"
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        payload = {
            "pid": os.getpid(),
            "state": state,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)
