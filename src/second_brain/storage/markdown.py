"""Canonical Markdown/frontmatter helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import frontmatter
import yaml
from pydantic import ValidationError

from second_brain.models import CanonicalFrontmatter


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_note(path: Path) -> tuple[dict[str, Any], str]:
    post = frontmatter.load(path)
    return dict(post.metadata), post.content


def render_note(metadata: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{yaml_text}\n---\n\n{body.rstrip()}\n"


def validate_common_frontmatter(path: Path) -> list[str]:
    metadata, _ = parse_note(path)
    try:
        CanonicalFrontmatter.model_validate(metadata)
    except ValidationError as exc:
        return [f"{path}: {error['loc']}: {error['msg']}" for error in exc.errors()]
    return []


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(content, encoding="utf-8", newline="\n")
    temp.replace(path)
