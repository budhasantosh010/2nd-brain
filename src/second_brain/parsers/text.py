"""Plain text and source-code parser with line-range locators."""

from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_bytes

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".kts", ".scala",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".sql", ".r", ".lua",
    ".toml", ".ini", ".cfg", ".conf", ".dockerfile",
}


class TextParser(BaseParser):
    extensions = frozenset({".txt", ".log"} | CODE_EXTENSIONS)

    def supports(self, path: Path) -> bool:
        name = path.name.lower()
        return name == ".env" or name.startswith(".env.") or super().supports(path)

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        raw = path.read_bytes()
        match = from_bytes(raw).best()
        text = str(match) if match is not None else raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        segments: list[ParsedSegment] = []
        chunk_size = 80
        if not lines:
            segments.append(
                ParsedSegment(segment_id=f"{source_id}:seg:0", text="", locator="lines 1-1", position=0)
            )
        for start in range(0, len(lines), chunk_size):
            end = min(start + chunk_size, len(lines))
            segments.append(
                ParsedSegment(
                    segment_id=f"{source_id}:seg:{len(segments)}",
                    text="\n".join(lines[start:end]),
                    locator=f"lines {start + 1}-{end}",
                    position=len(segments),
                )
            )
        return self.document(
            path,
            source_id,
            segments,
            metadata={"encoding": match.encoding if match is not None else "utf-8-replacement"},
        )
