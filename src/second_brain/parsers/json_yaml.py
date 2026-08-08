"""JSON and YAML structured-text parser."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class JsonYamlParser(BaseParser):
    extensions = frozenset({".json", ".yaml", ".yml"})

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        text = path.read_text(encoding="utf-8-sig")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
            normalized = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
            fmt = "json"
        else:
            data = yaml.safe_load(text)
            normalized = yaml.safe_dump(data, sort_keys=True, allow_unicode=True)
            fmt = "yaml"
        segment = ParsedSegment(
            segment_id=f"{source_id}:seg:0",
            text=normalized,
            locator="document root",
            position=0,
            metadata={"format": fmt},
        )
        return self.document(path, source_id, [segment], metadata={"format": fmt})
