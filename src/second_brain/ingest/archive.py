"""Recursive folder import discovery with ignore and symlink safety."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from second_brain.exceptions import SecurityViolation

IGNORED_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".next",
    ".cache",
    ".idea",
    ".vscode",
}
IGNORED_FILE_SUFFIXES = {".pyc", ".pyo", ".obj", ".o", ".class"}


def discover_folder_files(root: Path, *, follow_symlinks: bool = False) -> Iterator[Path]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in current.iterdir():
            if entry.is_symlink():
                if follow_symlinks:
                    raise SecurityViolation(
                        "Following arbitrary symlinks is intentionally unsupported in V1 folder imports"
                    )
                continue
            if entry.is_dir():
                if entry.name in IGNORED_DIR_NAMES:
                    continue
                stack.append(entry)
                continue
            if entry.is_file() and entry.suffix.lower() not in IGNORED_FILE_SUFFIXES:
                yield entry
