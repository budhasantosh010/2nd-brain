"""Compatibility entry point for applying operation plans."""

from __future__ import annotations

from second_brain.models import OperationPlan
from second_brain.transactions.manager import TransactionManager


def apply_plan(plan: OperationPlan, manager: TransactionManager | None = None) -> str:
    return (manager or TransactionManager()).apply(plan)
