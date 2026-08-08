"""Content-addressed source identity."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_id(content_hash: str) -> str:
    if len(content_hash) != 64:
        raise ValueError("source hash must be a full SHA256 hex digest")
    return f"SRC-{content_hash[:16].lower()}"
