"""Runtime vault bootstrap and structural validation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from second_brain.paths import BrainPaths
from second_brain.storage.sqlite import SQLiteStore

REQUIRED_FILES = (
    "HOME.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "README.md",
    "00 Home/Dashboard.md",
    "00 Home/Current Context.md",
    "00 Home/Brain Status.md",
    "00 Home/Processing Status.md",
    "00 Home/Needs Review.md",
    "01 Inbox/DROP FILES HERE.md",
    "02 Sources/Source Index.md",
    "04 Projects/PROJECT INDEX.md",
    "05 Areas/AREA INDEX.md",
    "06 Skills/SKILLS INDEX.md",
    "07 Operations/CURRENT.md",
    "09 Identity/PROFILE.md",
    "10 System/SYSTEM.md",
    "10 System/INGESTION.md",
    "10 System/RETRIEVAL.md",
    "10 System/KNOWLEDGE SCHEMA.md",
    "10 System/SOURCE POLICY.md",
    "10 System/LINKING RULES.md",
    "10 System/MEMORY POLICY.md",
    "10 System/PERMISSIONS.md",
    "10 System/EGRESS POLICY.md",
    "10 System/CHANGE POLICY.md",
    "10 System/VERIFICATION.md",
    "10 System/CONFIDENCE.md",
    "10 System/RESTRUCTURING.md",
    "10 System/AUTOMATIONS.md",
    "10 System/REVIEW POLICY.md",
    "10 System/FAILURE HANDLING.md",
    ".brain/config.yaml",
)

REQUIRED_DIRS = (
    "01 Inbox/Text Captures",
    "01 Inbox/Voice Captures",
    "01 Inbox/Web Captures",
    "01 Inbox/Folder Imports",
    "02 Sources/Raw/Documents",
    "02 Sources/Raw/Conversations",
    "02 Sources/Raw/Videos",
    "02 Sources/Raw/Audio",
    "02 Sources/Raw/Images",
    "02 Sources/Raw/Websites",
    "02 Sources/Raw/Code",
    "02 Sources/Raw/Other",
    "02 Sources/Records",
    "02 Sources/Extracted",
    "03 Knowledge/Concepts",
    "03 Knowledge/Principles",
    "03 Knowledge/Strategies",
    "03 Knowledge/Tactics",
    "03 Knowledge/Decisions",
    "03 Knowledge/Claims",
    "03 Knowledge/Lessons",
    "03 Knowledge/Anti-Patterns",
    "03 Knowledge/Frameworks",
    "03 Knowledge/Questions",
    "03 Knowledge/Entities",
    "03 Knowledge/Entities/People",
    "03 Knowledge/Entities/Companies",
    "03 Knowledge/Entities/Products",
    "03 Knowledge/Entities/Tools",
    "03 Knowledge/Entities/Technologies",
    "03 Knowledge/Maps",
    "04 Projects/Active Projects",
    "04 Projects/_Project Template/Inputs",
    "04 Projects/_Project Template/Working",
    "04 Projects/_Project Template/Outputs",
    "04 Projects/_Project Template/Feedback",
    "05 Areas/Business",
    "05 Areas/Content",
    "05 Areas/Software",
    "05 Areas/Learning",
    "05 Areas/Personal",
    "06 Skills/Knowledge",
    "06 Skills/Research",
    "06 Skills/Content",
    "06 Skills/Software",
    "06 Skills/Communication",
    "06 Skills/Project Management",
    "08 Briefs/Daily",
    "08 Briefs/Weekly",
    "08 Briefs/Monthly",
    "08 Briefs/Project Briefs",
    "12 Staging/Knowledge Changes",
    "12 Staging/System Changes",
    "12 Staging/Project Changes",
    "12 Staging/Restructuring",
    "99 Archive/Projects",
    "99 Archive/Knowledge",
    "99 Archive/Briefs",
    ".brain/db",
    ".brain/indexes",
    ".brain/ledgers",
    ".brain/manifests",
    ".brain/queue",
    ".brain/transactions",
    ".brain/history",
    ".brain/cache",
    ".brain/logs",
    ".brain/locks",
    ".brain/runtime",
)


@dataclass(slots=True)
class BootstrapResult:
    created: bool
    vault: Path
    missing_files: list[str]
    missing_dirs: list[str]

    @property
    def ready(self) -> bool:
        return not self.missing_files and not self.missing_dirs


def validate_vault_structure(vault: Path) -> tuple[list[str], list[str]]:
    missing_files = [rel for rel in REQUIRED_FILES if not (vault / rel).is_file()]
    missing_dirs = [rel for rel in REQUIRED_DIRS if not (vault / rel).is_dir()]
    return missing_files, missing_dirs


def initialize_vault(paths: BrainPaths | None = None) -> BootstrapResult:
    paths = paths or BrainPaths.discover()
    if not paths.template.is_dir():
        raise FileNotFoundError(f"Vault template is missing: {paths.template}")

    created = False
    if not paths.vault.exists():
        shutil.copytree(paths.template, paths.vault)
        created = True

    # Git does not preserve empty directories, so recreate the contractual topology
    # explicitly after copying the tracked template. This is safe for existing vaults:
    # mkdir(exist_ok=True) never rewrites user/canonical Markdown.
    for relative in REQUIRED_DIRS:
        (paths.vault / relative).mkdir(parents=True, exist_ok=True)

    # Never overwrite an existing vault. We only create machine runtime subdirs that are
    # contractually generated and absent; human/canonical Markdown is left untouched.
    paths.ensure_runtime_dirs()
    SQLiteStore(paths.db).initialize()
    missing_files, missing_dirs = validate_vault_structure(paths.vault)
    return BootstrapResult(created, paths.vault, missing_files, missing_dirs)
