"""Inbox filesystem watcher feeding the same ingestion service used by CLI/daemon."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from second_brain.ingest.service import IngestionService


class _InboxHandler(FileSystemEventHandler):
    def __init__(self, service: IngestionService, settle_seconds: float) -> None:
        self.service = service
        self.settle_seconds = settle_seconds
        self._recent: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path_value = getattr(event, "dest_path", None) or event.src_path
        path = Path(str(path_value))
        now = time.monotonic()
        with self._lock:
            previous = self._recent.get(str(path), 0.0)
            if now - previous < max(self.settle_seconds, 0.2):
                return
            self._recent[str(path)] = now
        threading.Thread(target=self._settle_and_ingest, args=(path,), daemon=True).start()

    def _settle_and_ingest(self, path: Path) -> None:
        time.sleep(self.settle_seconds)
        if path.exists() and path.is_file():
            self.service.ingest_file(path)


class InboxWatcher:
    def __init__(self, service: IngestionService | None = None) -> None:
        self.service = service or IngestionService()
        self.observer = Observer()

    def start(self) -> None:
        handler = _InboxHandler(self.service, self.service.config.ingestion.settle_seconds)
        self.observer.schedule(handler, str(self.service.paths.inbox), recursive=True)
        self.observer.start()

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join(timeout=10)

    def run_forever(self) -> None:
        self.start()
        try:
            while self.observer.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
