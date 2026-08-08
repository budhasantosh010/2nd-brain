"""Safe archive listing parser; extraction is never allowed to escape its sandbox."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from second_brain.exceptions import SecurityViolation
from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class ArchiveParser(BaseParser):
    extensions = frozenset({".zip", ".tar", ".tgz", ".gz"})

    @staticmethod
    def _validate_member(name: str) -> None:
        normalized = name.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or ".." in pure.parts:
            raise SecurityViolation(f"Archive member path traversal rejected: {name}")

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        names: list[str] = []
        suffix = path.suffix.lower()
        if suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    self._validate_member(info.filename)
                    names.append(info.filename)
        else:
            try:
                with tarfile.open(path) as archive:
                    for member in archive.getmembers():
                        self._validate_member(member.name)
                        if member.issym() or member.islnk():
                            raise SecurityViolation(f"Archive link member rejected: {member.name}")
                        names.append(member.name)
            except tarfile.ReadError:
                names = []
        text = "\n".join(names)
        segment = ParsedSegment(
            segment_id=f"{source_id}:seg:0",
            text=text,
            locator="archive member listing",
            position=0,
            metadata={"members": len(names), "extracted": False},
        )
        return self.document(path, source_id, [segment], metadata={"members": len(names), "extracted": False})
