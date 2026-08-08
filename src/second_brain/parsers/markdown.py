"""Markdown parser preserving heading-oriented locators."""

from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_bytes

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class MarkdownParser(BaseParser):
    extensions = frozenset({".md", ".markdown"})

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        match = from_bytes(path.read_bytes()).best()
        text = str(match) if match is not None else path.read_text(encoding="utf-8", errors="replace")
        segments: list[ParsedSegment] = []
        current: list[str] = []
        heading = "document start"
        start_line = 1

        def flush(end_line: int) -> None:
            nonlocal current, start_line
            body = "\n".join(current).strip()
            if body:
                segments.append(
                    ParsedSegment(
                        segment_id=f"{source_id}:seg:{len(segments)}",
                        text=body,
                        locator=f"{heading} (lines {start_line}-{end_line})",
                        position=len(segments),
                    )
                )
            current = []

        lines = text.splitlines()
        for number, line in enumerate(lines, start=1):
            if line.startswith("#") and line.lstrip("#").startswith(" "):
                flush(number - 1)
                heading = line.lstrip("#").strip() or "untitled heading"
                start_line = number
            current.append(line)
        flush(len(lines))
        if not segments:
            segments.append(
                ParsedSegment(segment_id=f"{source_id}:seg:0", text=text, locator="document", position=0)
            )
        return self.document(path, source_id, segments, mime_type="text/markdown")
