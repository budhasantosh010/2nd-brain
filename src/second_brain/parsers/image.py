"""Image metadata parser; optional AI description is a separate provider capability."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class ImageParser(BaseParser):
    extensions = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"})

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        with Image.open(path) as image:
            metadata: dict[str, object] = {
                "width": image.width,
                "height": image.height,
                "format": image.format,
                "mode": image.mode,
                "requires_vision_for_description": True,
            }
        segment = ParsedSegment(
            segment_id=f"{source_id}:seg:0",
            text=f"Image {path.name}: {metadata['width']}x{metadata['height']} {metadata['format']}",
            locator="image metadata",
            position=0,
            metadata=metadata,
        )
        return self.document(path, source_id, [segment], metadata=metadata)
