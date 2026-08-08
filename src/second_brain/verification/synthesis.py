"""Grounded multi-source synthesis with deterministic evidence validation."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field

from second_brain.models import BrainAnswer, SearchHit
from second_brain.providers.base import AIProvider

EXACT_TOKEN_PATTERN = re.compile(
    r"\b(?:[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+|[a-fA-F0-9]{12,})\b"
)


class SynthesizedClaim(BaseModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class SynthesisOutput(BaseModel):
    answer: str
    claims: list[SynthesizedClaim] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SynthesisValidation:
    ok: bool
    errors: tuple[str, ...] = ()


class GroundedSynthesizer:
    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider

    def synthesize(
        self,
        question: str,
        base: BrainAnswer,
        hits: list[SearchHit],
        *,
        evidence_id_exists: Callable[[str], bool],
    ) -> BrainAnswer | None:
        evidence_hits = hits[:8]
        allowed_ids = {
            value
            for hit in evidence_hits
            for value in (hit.object_id, hit.source_id)
            if value
        }
        evidence_pack = [
            {
                "object_id": hit.object_id,
                "source_id": hit.source_id,
                "title": hit.title,
                "locator": hit.locator,
                "text": hit.text[:2000],
            }
            for hit in evidence_hits
        ]
        payload = self.provider.generate_structured(
            task="grounded_multi_source_synthesis_v1",
            text=question,
            schema=SynthesisOutput.model_json_schema(),
            context={
                "instructions": (
                    "Use only the supplied evidence. Every factual claim must list one or more evidence_ids "
                    "from object_id/source_id values in the evidence pack. Surface supplied conflicts and uncertainty."
                ),
                "evidence": evidence_pack,
                "known_conflicts": base.conflicts,
                "extractive_baseline": base.answer,
            },
        )
        try:
            output = SynthesisOutput.model_validate(payload)
        except ValueError:
            return None
        validation = self.validate(
            output,
            allowed_ids=allowed_ids,
            evidence_text="\n".join(hit.text for hit in evidence_hits),
            conflicts=base.conflicts,
            evidence_id_exists=evidence_id_exists,
        )
        if not validation.ok:
            return None
        return BrainAnswer(
            answer=output.answer,
            evidence=base.evidence,
            citations=base.citations,
            conflicts=sorted(set(base.conflicts + output.conflicts)),
            uncertainty=sorted(set(base.uncertainty + output.uncertainty)),
            missing_information=base.missing_information,
            query_type=base.query_type,
        )

    @staticmethod
    def validate(
        output: SynthesisOutput,
        *,
        allowed_ids: set[str],
        evidence_text: str,
        conflicts: list[str],
        evidence_id_exists: Callable[[str], bool],
    ) -> SynthesisValidation:
        errors: list[str] = []
        if not output.answer.strip():
            errors.append("empty answer")
        for claim in output.claims:
            for evidence_id in claim.evidence_ids:
                if evidence_id not in allowed_ids:
                    errors.append(f"claim cites evidence outside bounded pack: {evidence_id}")
                    continue
                if not evidence_id_exists(evidence_id):
                    errors.append(f"claim cites missing evidence: {evidence_id}")
        if conflicts and not output.conflicts:
            errors.append("known conflicts were omitted")
        lower_evidence = evidence_text.lower()
        allowed_lower = {value.lower() for value in allowed_ids}
        for token in EXACT_TOKEN_PATTERN.findall(output.answer):
            if token.lower() not in lower_evidence and token.lower() not in allowed_lower:
                errors.append(f"unsupported exact-looking identifier in answer: {token}")
        for claim in output.claims:
            for token in EXACT_TOKEN_PATTERN.findall(claim.text):
                if token.lower() not in lower_evidence and token.lower() not in allowed_lower:
                    errors.append(f"unsupported exact-looking identifier in claim: {token}")
        return SynthesisValidation(not errors, tuple(sorted(set(errors))))
