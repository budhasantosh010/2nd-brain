# Windows Setup

The supported project path may contain spaces. PowerShell scripts derive the repository root from their own location and quote paths rather than assuming a fixed working directory.

## Setup

From PowerShell:

```powershell
cd "C:\Users\Lenovo\Music\Startups\2nd Brain Project"
.\scripts\setup_windows.ps1
```

To also register the local daemon at user logon:

```powershell
.\scripts\setup_windows.ps1 -RegisterAtLogin
```

The script prefers `uv`. If `uv` is unavailable it uses `py`/`python` to create `.venv` and install the package locally. It then runs `second-brain init` and `second-brain doctor`.

Open this exact folder in Obsidian:

```text
C:\Users\Lenovo\Music\Startups\2nd Brain Project\vault
```

## Start / stop

```powershell
.\scripts\start_brain.ps1
.\scripts\stop_brain.ps1
```

The launcher records its process ID under the runtime `.brain/runtime` directory; the daemon itself also owns an exclusive daemon lock, which is the authoritative guard against two instances.

## Remove Windows integration

```powershell
.\scripts\uninstall_windows.ps1
```

This stops the launcher process and removes the scheduled task if present. It never deletes `vault/`.

To also delete only the local virtual environment:

```powershell
.\scripts\uninstall_windows.ps1 -RemoveEnvironment
```

## Troubleshooting

Run:

```powershell
.\.venv\Scripts\second-brain.exe doctor
.\.venv\Scripts\second-brain.exe status
```

If the daemon lock remains after a crash, first confirm no daemon process is running. Use `second-brain recover` for interrupted canonical write transactions. Do not manually remove source evidence or database history as a first response.
<!-- PHASE25_FINAL -->
## Phase 2.5 Windows acceptance

Windows paths containing spaces are supported. Release acceptance is run from the real repository path while `SECOND_BRAIN_VAULT` points to a disposable isolated vault. The acceptance sequence covers init/doctor/verify/status, daemon Inbox ingestion, stop/offline drop/restart missed-work recovery, a forced process death while holding a writer lock, backup create/verify, rebuild, MCP stdio and semantic-model execution. Never hard-crash test against a valuable populated brain.
