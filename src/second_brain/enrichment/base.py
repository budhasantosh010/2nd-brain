"""Capability interfaces for optional local/cloud multimodal enrichment."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EnrichedSegment:
    text: str
    locator: str
    confidence: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VisionResult:
    description: str
    visible_text: str = ""
    objects: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    confidence: float | None = None


class OCRProvider(ABC):
    name: str = "none"

    @property
    def available(self) -> bool:
        return False

    @abstractmethod
    def extract_pages(self, path: Path) -> list[EnrichedSegment]:
        """Return page-located OCR segments."""


class VisionProvider(ABC):
    name: str = "none"

    @property
    def available(self) -> bool:
        return False

    @abstractmethod
    def describe(self, path: Path) -> VisionResult:
        """Describe image content without mutating the source."""


class TranscriptionProvider(ABC):
    name: str = "none"

    @property
    def available(self) -> bool:
        return False

    @abstractmethod
    def transcribe(self, path: Path) -> list[EnrichedSegment]:
        """Return timestamp-located transcript segments."""


class UnavailableOCRProvider(OCRProvider):
    def extract_pages(self, path: Path) -> list[EnrichedSegment]:
        del path
        raise RuntimeError("OCR capability is not configured")


class UnavailableVisionProvider(VisionProvider):
    def describe(self, path: Path) -> VisionResult:
        del path
        raise RuntimeError("Vision capability is not configured")


class UnavailableTranscriptionProvider(TranscriptionProvider):
    def transcribe(self, path: Path) -> list[EnrichedSegment]:
        del path
        raise RuntimeError("Transcription capability is not configured")
