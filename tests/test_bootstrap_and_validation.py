from __future__ import annotations

import json
import shutil
from pathlib import Path

from second_brain.bootstrap import REQUIRED_DIRS, REQUIRED_FILES, initialize_vault
from second_brain.paths import BrainPaths
from second_brain.validation import validate_vault


def test_vault_bootstrap_exact_required_structure(isolated_brain: BrainPaths) -> None:
    for relative in REQUIRED_FILES:
        assert (isolated_brain.vault / relative).is_file(), relative
    for relative in REQUIRED_DIRS:
        assert (isolated_brain.vault / relative).is_dir(), relative


def test_init_is_idempotent_and_does_not_overwrite_existing_vault(isolated_brain: BrainPaths) -> None:
    profile = isolated_brain.vault / "09 Identity" / "PROFILE.md"
    original = profile.read_text(encoding="utf-8")
    profile.write_text(original + "\nRUNTIME-SENTINEL\n", encoding="utf-8")
    result = initialize_vault(isolated_brain)
    assert result.created is False
    assert "RUNTIME-SENTINEL" in profile.read_text(encoding="utf-8")


def test_runtime_path_with_spaces_is_supported(isolated_brain: BrainPaths) -> None:
    assert " " in str(isolated_brain.vault)
    assert isolated_brain.db.parent.is_dir()


def test_init_recreates_required_empty_directories_missing_from_git_clone(
    isolated_brain: BrainPaths,
) -> None:
    targets = [
        "03 Knowledge/Principles",
        "04 Projects/_Project Template/Inputs",
        "05 Areas/Business",
        "08 Briefs/Weekly",
    ]
    for relative in targets:
        path = isolated_brain.vault / relative
        shutil.rmtree(path)
        assert not path.exists()
    result = initialize_vault(isolated_brain)
    assert result.ready
    assert all((isolated_brain.vault / relative).is_dir() for relative in targets)


def test_all_templates_and_skills_validate(isolated_brain: BrainPaths) -> None:
    report = validate_vault(isolated_brain.vault)
    assert report.ok, report.errors
    assert report.checked >= 20


def test_exported_json_schemas_are_valid_json() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas"
    schemas = sorted(root.glob("*.schema.json"))
    assert len(schemas) >= 9
    for path in schemas:
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["type"] == "object"


def test_runtime_vault_is_gitignored() -> None:
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "vault/" in gitignore
    assert ".env" in gitignore
    assert "*.sqlite" in gitignore
