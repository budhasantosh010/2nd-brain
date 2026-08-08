"""Operation-ledger helpers. Ledgers are local runtime audit evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_ledger(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Ledger is not a JSON object: {path}")
    return value


def list_ledgers(directory: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            records.append(read_ledger(path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return records
