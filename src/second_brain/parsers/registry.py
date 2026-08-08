"""Parser registry with deterministic extension dispatch."""

from __future__ import annotations

from pathlib import Path

from second_brain.exceptions import UnsupportedSourceError
from second_brain.parsers.archive import ArchiveParser
from second_brain.parsers.audio_video import AudioVideoParser
from second_brain.parsers.base import BaseParser
from second_brain.parsers.csv import CSVParser
from second_brain.parsers.docx import DOCXParser
from second_brain.parsers.email import EmailParser
from second_brain.parsers.html import HTMLParser
from second_brain.parsers.image import ImageParser
from second_brain.parsers.json_yaml import JsonYamlParser
from second_brain.parsers.markdown import MarkdownParser
from second_brain.parsers.pdf import PDFParser
from second_brain.parsers.pptx import PPTXParser
from second_brain.parsers.text import TextParser
from second_brain.parsers.xlsx import XLSXParser


class ParserRegistry:
    def __init__(self, parsers: list[BaseParser] | None = None) -> None:
        self.parsers = parsers or []

    def register(self, parser: BaseParser) -> None:
        self.parsers.append(parser)

    def get(self, path: Path) -> BaseParser:
        for parser in self.parsers:
            if parser.supports(path):
                return parser
        raise UnsupportedSourceError(f"No parser registered for {path.suffix or path.name}")

    def supports(self, path: Path) -> bool:
        return any(parser.supports(path) for parser in self.parsers)

    @property
    def extensions(self) -> set[str]:
        return {extension for parser in self.parsers for extension in parser.extensions}


def default_registry() -> ParserRegistry:
    return ParserRegistry(
        [
            MarkdownParser(),
            CSVParser(),
            JsonYamlParser(),
            HTMLParser(),
            PDFParser(),
            DOCXParser(),
            PPTXParser(),
            XLSXParser(),
            EmailParser(),
            ImageParser(),
            AudioVideoParser(),
            ArchiveParser(),
            TextParser(),
        ]
    )
