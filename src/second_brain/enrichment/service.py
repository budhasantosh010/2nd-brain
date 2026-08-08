"""Capability-driven enrichment orchestrator layered after deterministic parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from second_brain.enrichment.base import (
    OCRProvider,
    TranscriptionProvider,
    UnavailableOCRProvider,
    UnavailableTranscriptionProvider,
    UnavailableVisionProvider,
    VisionProvider,
)
from second_brain.models import ParsedDocument, ParsedSegment

TIMESTAMP_LOCATOR = re.compile(r"^\d{2}:\d{2}:\d{2}(?:\.\d+)?[–-]\d{2}:\d{2}:\d{2}(?:\.\d+)?$")


@dataclass(frozen=True, slots=True)
class EnrichmentOutcome:
    document: ParsedDocument
    enriched: bool
    needs_enrichment: bool
    next_action: str = ""
    capability: str = ""


class EnrichmentService:
    def __init__(
        self,
        *,
        ocr: OCRProvider | None = None,
        vision: VisionProvider | None = None,
        transcription: TranscriptionProvider | None = None,
    ) -> None:
        self.ocr = ocr or UnavailableOCRProvider()
        self.vision = vision or UnavailableVisionProvider()
        self.transcription = transcription or UnavailableTranscriptionProvider()

    def enrich(self, path: Path, document: ParsedDocument) -> EnrichmentOutcome:
        metadata = dict(document.metadata)
        if bool(metadata.get("requires_ocr")):
            if not self.ocr.available:
                return EnrichmentOutcome(
                    document,
                    enriched=False,
                    needs_enrichment=True,
                    next_action="Configure an OCRProvider and retry enrichment for this scanned PDF.",
                    capability="ocr",
                )
            pages = self.ocr.extract_pages(path)
            segments = [
                ParsedSegment(
                    segment_id=f"{document.source_id}:seg:{index}",
                    text=item.text,
                    locator=item.locator or f"page {index + 1}",
                    position=index,
                    metadata={
                        **item.metadata,
                        "confidence": item.confidence,
                        "enrichment_provider": self.ocr.name,
                    },
                )
                for index, item in enumerate(pages)
            ]
            if not segments:
                return EnrichmentOutcome(
                    document,
                    enriched=False,
                    needs_enrichment=True,
                    next_action="OCR provider returned no page text; inspect scan quality or provider configuration.",
                    capability="ocr",
                )
            metadata.update(
                {
                    "requires_ocr": False,
                    "ocr_enriched": True,
                    "ocr_provider": self.ocr.name,
                }
            )
            return EnrichmentOutcome(
                document.model_copy(update={"segments": segments, "metadata": metadata}),
                enriched=True,
                needs_enrichment=False,
                capability="ocr",
            )

        if bool(metadata.get("requires_vision_for_description")):
            if not self.vision.available:
                return EnrichmentOutcome(
                    document,
                    enriched=False,
                    needs_enrichment=True,
                    next_action="Configure a VisionProvider to describe this image; raw image is already preserved.",
                    capability="vision",
                )
            result = self.vision.describe(path)
            parts = [result.description.strip()]
            if result.visible_text.strip():
                parts.append(f"Visible text: {result.visible_text.strip()}")
            if result.objects:
                parts.append("Important objects/entities: " + ", ".join(result.objects))
            if result.limitations:
                parts.append("Limitations: " + "; ".join(result.limitations))
            segment = ParsedSegment(
                segment_id=f"{document.source_id}:seg:0",
                text="\n".join(part for part in parts if part),
                locator="image",
                position=0,
                metadata={
                    "confidence": result.confidence,
                    "objects": list(result.objects),
                    "limitations": list(result.limitations),
                    "enrichment_provider": self.vision.name,
                },
            )
            metadata.update(
                {
                    "requires_vision_for_description": False,
                    "vision_enriched": True,
                    "vision_provider": self.vision.name,
                }
            )
            return EnrichmentOutcome(
                document.model_copy(update={"segments": [segment], "metadata": metadata}),
                enriched=True,
                needs_enrichment=False,
                capability="vision",
            )

        if bool(metadata.get("requires_transcription")):
            if not self.transcription.available:
                return EnrichmentOutcome(
                    document,
                    enriched=False,
                    needs_enrichment=True,
                    next_action="Configure a TranscriptionProvider and retry; raw media is already preserved.",
                    capability="transcription",
                )
            transcript = self.transcription.transcribe(path)
            transcription_segments: list[ParsedSegment] = []
            for index, item in enumerate(transcript):
                locator = item.locator.strip()
                if not TIMESTAMP_LOCATOR.match(locator):
                    raise ValueError(
                        "Transcription provider must return timestamped locators such as 00:04:15–00:04:36"
                    )
                transcription_segments.append(
                    ParsedSegment(
                        segment_id=f"{document.source_id}:seg:{index}",
                        text=item.text,
                        locator=locator,
                        position=index,
                        metadata={
                            **item.metadata,
                            "confidence": item.confidence,
                            "enrichment_provider": self.transcription.name,
                        },
                    )
                )
            if not transcription_segments:
                return EnrichmentOutcome(
                    document,
                    enriched=False,
                    needs_enrichment=True,
                    next_action="Transcription provider returned no timestamped segments.",
                    capability="transcription",
                )
            metadata.update(
                {
                    "requires_transcription": False,
                    "transcription_configured": True,
                    "transcription_enriched": True,
                    "transcription_provider": self.transcription.name,
                }
            )
            return EnrichmentOutcome(
                document.model_copy(update={"segments": transcription_segments, "metadata": metadata}),
                enriched=True,
                needs_enrichment=False,
                capability="transcription",
            )

        return EnrichmentOutcome(document, enriched=False, needs_enrichment=False)
