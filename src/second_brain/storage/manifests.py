"""Source-manifest read helpers used by integrity verification and rebuild."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Manifest is not a JSON object: {path}")
    return value


def source_manifests(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("SRC-*.json")):
        try:
            result.append((path, read_manifest(path)))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return result
