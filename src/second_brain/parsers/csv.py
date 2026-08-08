"""CSV/TSV parser with row-range locators."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from charset_normalizer import from_bytes

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class CSVParser(BaseParser):
    extensions = frozenset({".csv", ".tsv"})

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        raw = path.read_bytes()
        match = from_bytes(raw).best()
        text = str(match) if match is not None else raw.decode("utf-8", errors="replace")
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        segments: list[ParsedSegment] = []
        chunk_size = 100
        for start in range(0, len(rows), chunk_size):
            end = min(start + chunk_size, len(rows))
            output = io.StringIO()
            writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
            writer.writerows(rows[start:end])
            segments.append(
                ParsedSegment(
                    segment_id=f"{source_id}:seg:{len(segments)}",
                    text=output.getvalue().rstrip(),
                    locator=f"rows {start + 1}-{end}",
                    position=len(segments),
                    metadata={"delimiter": delimiter},
                )
            )
        if not segments:
            segments.append(
                ParsedSegment(segment_id=f"{source_id}:seg:0", text="", locator="rows 1-1", position=0)
            )
        return self.document(path, source_id, segments)
