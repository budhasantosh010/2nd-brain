"""Relationship builders that preserve source provenance."""

from __future__ import annotations

from second_brain.models import RelationshipRecord, RelationshipType


def derived_from(object_id: str, source_id: str) -> RelationshipRecord:
    return RelationshipRecord(
        from_id=object_id,
        to_id=source_id,
        relation=RelationshipType.DERIVED_FROM,
        source_id=source_id,
        provisional=True,
    )


def related_to(left_id: str, right_id: str, source_id: str) -> RelationshipRecord:
    return RelationshipRecord(
        from_id=left_id,
        to_id=right_id,
        relation=RelationshipType.RELATED_TO,
        source_id=source_id,
        provisional=True,
    )


def supports(claim_id: str, source_id: str) -> RelationshipRecord:
    return RelationshipRecord(
        from_id=source_id,
        to_id=claim_id,
        relation=RelationshipType.SUPPORTS,
        source_id=source_id,
        provisional=False,
    )
