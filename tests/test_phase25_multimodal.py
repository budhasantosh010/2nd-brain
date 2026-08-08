from __future__ import annotations

from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

from second_brain.config import load_config
from second_brain.enrichment.base import (
    EnrichedSegment,
    OCRProvider,
    TranscriptionProvider,
    VisionProvider,
    VisionResult,
)
from second_brain.enrichment.service import EnrichmentService
from second_brain.ingest.service import IngestionService
from second_brain.models import ParsedDocument, ProcessingState
from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore


class FakeOCR(OCRProvider):
    name = "fake-ocr"

    @property
    def available(self) -> bool:
        return True

    def extract_pages(self, path: Path) -> list[EnrichedSegment]:
        del path
        return [EnrichedSegment("Scanned page text", "page 1", confidence=0.99)]


class FakeVision(VisionProvider):
    name = "fake-vision"

    @property
    def available(self) -> bool:
        return True

    def describe(self, path: Path) -> VisionResult:
        del path
        return VisionResult(
            description="A dashboard screenshot.",
            visible_text="Revenue 42",
            objects=("chart", "table"),
            limitations=("small footer unreadable",),
            confidence=0.91,
        )


class FakeTranscription(TranscriptionProvider):
    name = "fake-transcription"

    @property
    def available(self) -> bool:
        return True

    def transcribe(self, path: Path) -> list[EnrichedSegment]:
        del path
        return [
            EnrichedSegment(
                "The launch date moved to October fourth.",
                "00:04:15–00:04:36",
                confidence=0.95,
            )
        ]


def test_unavailable_multimodal_capabilities_preserve_raw_and_mark_needs_enrichment(
    isolated_brain: BrainPaths,
    store: SQLiteStore,
    input_dir: Path,
) -> None:
    image_path = input_dir / "screen.png"
    Image.new("RGB", (32, 32)).save(image_path)
    image_result = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(
        image_path
    )
    assert image_result.state == ProcessingState.NEEDS_ENRICHMENT
    assert image_result.raw_path is not None and image_result.raw_path.is_file()

    media_path = input_dir / "voice.mp3"
    media_path.write_bytes(b"synthetic-media-bytes")
    media_result = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(
        media_path
    )
    assert media_result.state == ProcessingState.NEEDS_ENRICHMENT
    assert "TranscriptionProvider" in media_result.message

    pdf_path = input_dir / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf_path.open("wb") as handle:
        writer.write(handle)
    pdf_result = IngestionService(isolated_brain, load_config(isolated_brain), store).ingest_file(
        pdf_path
    )
    assert pdf_result.state == ProcessingState.NEEDS_ENRICHMENT
    assert "OCRProvider" in pdf_result.message


def test_capability_providers_preserve_locators_and_structured_enrichment(tmp_path: Path) -> None:
    service = EnrichmentService(
        ocr=FakeOCR(),
        vision=FakeVision(),
        transcription=FakeTranscription(),
    )
    source = tmp_path / "placeholder.bin"
    source.write_bytes(b"x")

    scanned = ParsedDocument(
        source_id="SRC-scan",
        title="scan",
        mime_type="application/pdf",
        text="",
        metadata={"requires_ocr": True},
        segments=[],
    )
    ocr = service.enrich(source, scanned)
    assert ocr.enriched and not ocr.needs_enrichment
    assert ocr.document.segments[0].locator == "page 1"
    assert ocr.document.segments[0].text == "Scanned page text"

    image = ParsedDocument(
        source_id="SRC-image",
        title="image",
        mime_type="image/png",
        text="",
        metadata={"requires_vision_for_description": True},
        segments=[],
    )
    vision = service.enrich(source, image)
    assert vision.enriched
    assert "Visible text: Revenue 42" in vision.document.segments[0].text
    assert vision.document.segments[0].metadata["confidence"] == 0.91

    media = ParsedDocument(
        source_id="SRC-media",
        title="media",
        mime_type="audio/mpeg",
        text="",
        metadata={"requires_transcription": True},
        segments=[],
    )
    transcript = service.enrich(source, media)
    assert transcript.enriched
    assert transcript.document.segments[0].locator == "00:04:15–00:04:36"
    assert "launch date moved" in transcript.document.segments[0].text.lower()
