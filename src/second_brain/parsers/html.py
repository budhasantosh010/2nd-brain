"""HTML parser that extracts readable sections with heading locators."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class HTMLParser(BaseParser):
    extensions = frozenset({".html", ".htm"})

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else path.name
        segments: list[ParsedSegment] = []
        current_heading = "document"
        current: list[str] = []

        def flush() -> None:
            nonlocal current
            body = "\n".join(current).strip()
            if body:
                segments.append(
                    ParsedSegment(
                        segment_id=f"{source_id}:seg:{len(segments)}",
                        text=body,
                        locator=current_heading,
                        position=len(segments),
                    )
                )
            current = []

        for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote"]):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            if element.name and element.name.startswith("h"):
                flush()
                current_heading = f"heading: {text}"
            current.append(text)
        flush()
        if not segments:
            segments.append(
                ParsedSegment(
                    segment_id=f"{source_id}:seg:0",
                    text=soup.get_text("\n", strip=True),
                    locator="document",
                    position=0,
                )
            )
        doc = self.document(path, source_id, segments, mime_type="text/html", metadata={"html_title": title})
        doc.title = title
        return doc
