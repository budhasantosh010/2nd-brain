"""Audio/video metadata parser; transcription is optional and explicit."""

from __future__ import annotations

from pathlib import Path

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class AudioVideoParser(BaseParser):
    extensions = frozenset({".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4", ".mov", ".mkv", ".webm", ".avi"})

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        stat = path.stat()
        metadata: dict[str, object] = {
            "size_bytes": stat.st_size,
            "requires_transcription": True,
            "transcription_configured": False,
        }
        segment = ParsedSegment(
            segment_id=f"{source_id}:seg:0",
            text=f"Media file {path.name}; transcription not configured.",
            locator="media metadata",
            position=0,
            metadata=metadata,
        )
        return self.document(path, source_id, [segment], metadata=metadata)
