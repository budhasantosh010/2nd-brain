"""Construct the smallest sufficient evidence context with deduplication."""

from __future__ import annotations

from dataclasses import dataclass

from second_brain.models import SearchHit


@dataclass(frozen=True, slots=True)
class BuiltContext:
    text: str
    hits: list[SearchHit]
    characters: int


class ContextBuilder:
    def __init__(self, max_characters: int = 24_000, max_items: int = 12) -> None:
        self.max_characters = max_characters
        self.max_items = max_items

    def build(self, hits: list[SearchHit]) -> BuiltContext:
        selected: list[SearchHit] = []
        blocks: list[str] = []
        fingerprints: set[str] = set()
        used = 0
        for hit in hits:
            normalized = " ".join(hit.text.lower().split())[:500]
            if normalized in fingerprints:
                continue
            fingerprints.add(normalized)
            citation = hit.source_id or hit.object_id
            locator = f" @ {hit.locator}" if hit.locator else ""
            block = (
                f"[{citation}{locator}] {hit.title}\n"
                f"type={hit.object_type}; score={hit.score:.6f}\n"
                f"{hit.text.strip()}"
            ).strip()
            if selected and used + len(block) + 2 > self.max_characters:
                break
            if len(block) > self.max_characters and not selected:
                block = block[: self.max_characters]
            blocks.append(block)
            selected.append(hit)
            used += len(block) + 2
            if len(selected) >= self.max_items:
                break
        return BuiltContext("\n\n".join(blocks), selected, used)
