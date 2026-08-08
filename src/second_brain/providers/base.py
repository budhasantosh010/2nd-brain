"""Provider-neutral AI interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    available: bool
    provider: str
    model: str
    detail: str = ""


class AIProvider(ABC):
    """Knowledge/retrieval code depends only on this interface."""

    name: str
    model: str
    is_cloud: bool = False

    @abstractmethod
    def generate_structured(
        self,
        *,
        task: str,
        text: str,
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return JSON-like data; caller must validate it against the requested model/schema."""

    @abstractmethod
    def generate_text(
        self,
        *,
        task: str,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate provider-neutral free text."""

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Return availability without exposing credentials."""
