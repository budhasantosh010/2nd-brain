from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REQUIRED_WINDOWS_SCRIPTS = {
    "setup_windows.ps1",
    "start_brain.ps1",
    "stop_brain.ps1",
    "uninstall_windows.ps1",
}


def test_required_windows_scripts_exist_and_preserve_vault() -> None:
    root = Path(__file__).resolve().parents[1]
    scripts = root / "scripts"
    assert {path.name for path in scripts.glob("*.ps1")} >= REQUIRED_WINDOWS_SCRIPTS
    uninstall = (scripts / "uninstall_windows.ps1").read_text(encoding="utf-8")
    assert "Personal brain data was NOT deleted" in uninstall
    assert "RemoveEnvironment" in uninstall
    assert "Remove-Item -Recurse -Force -Path $Venv" in uninstall
    assert "Remove-Item -Recurse -Force -Path $RepoRoot" not in uninstall


def test_windows_scripts_parse_in_powershell() -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable on this CI runner")
    root = Path(__file__).resolve().parents[1]
    paths = [root / "scripts" / name for name in sorted(REQUIRED_WINDOWS_SCRIPTS)]
    quoted = ",".join("'" + str(path).replace("'", "''") + "'" for path in paths)
    command = (
        "$ErrorActionPreference='Stop'; $failed=$false; "
        f"foreach($p in @({quoted})) {{ "
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$tokens,[ref]$errors) | Out-Null; "
        "if($errors.Count -gt 0){$failed=$true; $errors | ForEach-Object { Write-Error $_.Message }} }; "
        "if($failed){exit 1}"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_public_repo_safety_scanner_passes_for_current_tracked_tree() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/verify_public_repo.py"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
