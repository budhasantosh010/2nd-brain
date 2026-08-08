"""Optional multimodal enrichment capabilities."""

from second_brain.enrichment.base import (
    EnrichedSegment,
    OCRProvider,
    TranscriptionProvider,
    VisionProvider,
    VisionResult,
)
from second_brain.enrichment.service import EnrichmentOutcome, EnrichmentService

__all__ = [
    "EnrichedSegment",
    "EnrichmentOutcome",
    "EnrichmentService",
    "OCRProvider",
    "TranscriptionProvider",
    "VisionProvider",
    "VisionResult",
]
