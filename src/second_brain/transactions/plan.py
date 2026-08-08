"""Operation-plan builders."""

from __future__ import annotations

from datetime import UTC, datetime

from second_brain.models import OperationPlan, PlannedWrite


def build_plan(
    description: str,
    writes: list[PlannedWrite],
    *,
    permission_level: int = 1,
) -> OperationPlan:
    return OperationPlan(
        created_at=datetime.now(UTC),
        permission_level=permission_level,
        description=description,
        writes=writes,
    )
