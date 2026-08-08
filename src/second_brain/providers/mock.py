"""Deterministic provider for tests, offline demos and Phase 1 manual workflow."""

from __future__ import annotations

import re
from typing import Any

from second_brain.providers.base import AIProvider, ProviderHealth

MARKER = re.compile(r"^(?P<kind>[A-Z ]+):\s*(?P<value>.+?)\s*$")


class MockProvider(AIProvider):
    name = "mock"
    model = "deterministic-v1"
    is_cloud = False

    def generate_structured(
        self,
        *,
        task: str,
        text: str,
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del schema
        if task != "compile_knowledge":
            return {}
        source_id = str((context or {}).get("source_id", "SRC-mock"))
        purpose = ""
        entities: list[dict[str, Any]] = []
        projects: list[dict[str, Any]] = []
        claims: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        concepts: list[dict[str, Any]] = []
        open_loops: list[dict[str, Any]] = []
        questions: list[str] = []

        for raw_line in text.splitlines():
            match = MARKER.match(raw_line.strip())
            if not match:
                continue
            kind = match.group("kind").strip()
            value = match.group("value").strip()
            if kind == "PURPOSE":
                purpose = value
            elif kind == "ENTITY":
                name, _, entity_type = value.partition("|")
                entities.append(
                    {
                        "name": name.strip(),
                        "entity_type": entity_type.strip() or "unknown",
                        "source_ids": [source_id],
                    }
                )
            elif kind == "PROJECT":
                name, _, rationale = value.partition("|")
                projects.append(
                    {
                        "name": name.strip(),
                        "rationale": rationale.strip() or "Explicit project marker in source.",
                        "confidence_state": "provisional",
                    }
                )
            elif kind == "CLAIM":
                statement, _, locator = value.partition("|")
                claims.append(
                    {
                        "statement": statement.strip(),
                        "source_id": source_id,
                        "source_locator": locator.strip() or "document",
                        "confidence_state": "provisional",
                    }
                )
            elif kind == "DECISION":
                decision, _, reasoning = value.partition("|")
                decisions.append(
                    {
                        "decision": decision.strip(),
                        "reasoning": reasoning.strip(),
                        "source_ids": [source_id],
                        "status": "active",
                    }
                )
            elif kind == "CONCEPT":
                title, _, summary = value.partition("|")
                concepts.append(
                    {
                        "title": title.strip(),
                        "summary": summary.strip() or title.strip(),
                        "source_ids": [source_id],
                        "status": "provisional",
                        "verification_state": "provisional",
                    }
                )
            elif kind in {"OPEN LOOP", "TASK"}:
                open_loops.append({"text": value, "source_id": source_id, "status": "open"})
            elif kind == "QUESTION":
                questions.append(value)

        if not purpose:
            purpose = "Deterministic mock compilation of preserved source."
        return {
            "purpose": purpose,
            "entities": entities,
            "project_candidates": projects,
            "claims": claims,
            "decisions": decisions,
            "concepts": concepts,
            "open_loops": open_loops,
            "questions": questions,
        }

    def generate_text(
        self,
        *,
        task: str,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        del context
        return f"[{self.name}:{task}] {text.strip()}"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, self.name, self.model, "Deterministic local mock provider.")
