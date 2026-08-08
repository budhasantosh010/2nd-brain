"""PDF parser with page-level locators and scanned-PDF detection metadata."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class PDFParser(BaseParser):
    extensions = frozenset({".pdf"})

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        reader = PdfReader(str(path))
        segments: list[ParsedSegment] = []
        nonempty = 0
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                nonempty += 1
            segments.append(
                ParsedSegment(
                    segment_id=f"{source_id}:seg:{index - 1}",
                    text=text.strip(),
                    locator=f"page {index}",
                    position=index - 1,
                )
            )
        scanned_likely = bool(reader.pages) and nonempty == 0
        return self.document(
            path,
            source_id,
            segments,
            mime_type="application/pdf",
            metadata={
                "pages": len(reader.pages),
                "scanned_likely": scanned_likely,
                "requires_ocr": scanned_likely,
            },
        )
