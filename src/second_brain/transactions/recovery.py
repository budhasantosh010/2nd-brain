"""Interrupted canonical-operation recovery."""

from __future__ import annotations

from second_brain.transactions.manager import TransactionManager


def recover(manager: TransactionManager | None = None) -> list[str]:
    return (manager or TransactionManager()).recover_interrupted()
