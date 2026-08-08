"""Parser dispatch kept separate from preservation logic."""

from __future__ import annotations

from pathlib import Path

from second_brain.models import ParsedDocument
from second_brain.parsers.registry import ParserRegistry, default_registry


class ParserDispatcher:
    def __init__(self, registry: ParserRegistry | None = None) -> None:
        self.registry = registry or default_registry()

    def parse(self, path: Path, source_id: str) -> ParsedDocument:
        return self.registry.get(path).parse(path, source_id)

    def supports(self, path: Path) -> bool:
        return self.registry.supports(path)
