"""Repository/runtime template validation used by CI, doctor and verify."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
from pydantic import ValidationError

from second_brain.bootstrap import validate_vault_structure
from second_brain.models import CanonicalFrontmatter, ReviewItemModel, SourceRecord


class ValidationReport:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.checked = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_vault(vault: Path, *, require_runtime_dirs: bool = True) -> ValidationReport:
    report = ValidationReport()
    missing_files, missing_dirs = validate_vault_structure(
        vault, require_runtime_dirs=require_runtime_dirs
    )
    report.errors.extend(f"missing file: {value}" for value in missing_files)
    report.errors.extend(f"missing directory: {value}" for value in missing_dirs)

    template_dir = vault / "11 Templates"
    for path in sorted(template_dir.glob("*.md")):
        report.checked += 1
        try:
            post = frontmatter.load(path)
        except Exception as exc:
            report.errors.append(f"{path}: invalid frontmatter: {exc}")
            continue
        metadata: dict[str, Any] = dict(post.metadata)
        try:
            if path.name == "Source.md":
                SourceRecord.model_validate(metadata)
            elif path.name == "Review Item.md":
                ReviewItemModel.model_validate(metadata)
            elif path.name == "Decision.md":
                required = {
                    "id",
                    "type",
                    "project_id",
                    "status",
                    "decided_at",
                    "supersedes",
                    "superseded_by",
                    "source_ids",
                }
                missing = sorted(required - set(metadata))
                if missing:
                    raise ValueError(f"missing required decision fields: {missing}")
            else:
                CanonicalFrontmatter.model_validate(metadata)
        except (ValidationError, ValueError) as exc:
            report.errors.append(f"{path}: {exc}")

    skills_dir = vault / "06 Skills"
    for path in sorted(skills_dir.rglob("*.md")):
        if path.name == "SKILLS INDEX.md":
            continue
        report.checked += 1
        try:
            post = frontmatter.load(path)
            canonical = CanonicalFrontmatter.model_validate(dict(post.metadata))
            if canonical.type != "skill":
                report.errors.append(f"{path}: expected type=skill, got {canonical.type}")
            permission = post.metadata.get("permission_level")
            if not isinstance(permission, int) or permission not in {0, 1, 2, 3}:
                report.errors.append(f"{path}: invalid permission_level={permission!r}")
        except (ValidationError, OSError, ValueError) as exc:
            report.errors.append(f"{path}: {exc}")
    return report
