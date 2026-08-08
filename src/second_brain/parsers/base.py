"""Parser interface and segment helpers."""

from __future__ import annotations

import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path

from second_brain.models import ParsedDocument, ParsedSegment


class BaseParser(ABC):
    extensions: frozenset[str] = frozenset()

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    @abstractmethod
    def parse(self, path: Path, source_id: str) -> ParsedDocument:
        """Parse a preserved local source into normalized text/segments."""

    @staticmethod
    def mime_type(path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    @staticmethod
    def document(
        path: Path,
        source_id: str,
        segments: list[ParsedSegment],
        *,
        mime_type: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ParsedDocument:
        return ParsedDocument(
            source_id=source_id,
            title=path.name,
            mime_type=mime_type or BaseParser.mime_type(path),
            text="\n\n".join(segment.text for segment in segments if segment.text),
            metadata=metadata or {},
            segments=segments,
        )
