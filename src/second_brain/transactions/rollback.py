"""Compatibility entry point for operation rollback."""

from __future__ import annotations

from second_brain.transactions.manager import TransactionManager


def rollback_operation(operation_id: str, manager: TransactionManager | None = None) -> None:
    (manager or TransactionManager()).rollback(operation_id)
