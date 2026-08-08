"""JSON-lines structured logging with conservative secret redaction."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from second_brain.paths import BrainPaths

SECRET_VALUE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{12,}|bearer\s+[A-Za-z0-9._~+/-]{12,}|-----BEGIN[^-]*PRIVATE KEY-----)"
)
SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token"}


def _redact(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, str):
        return SECRET_VALUE.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class StructuredLogger:
    def __init__(self, paths: BrainPaths | None = None, filename: str = "brain.jsonl") -> None:
        self.paths = paths or BrainPaths.discover()
        self.path = self.paths.logs / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            **fields,
        }
        safe = _redact(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, sort_keys=True, ensure_ascii=False) + "\n")
