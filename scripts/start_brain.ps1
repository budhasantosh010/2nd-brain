[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BrainExe = Join-Path $RepoRoot '.venv\Scripts\second-brain.exe'
$RuntimeDir = Join-Path $RepoRoot 'vault\.brain\runtime'
$PidFile = Join-Path $RuntimeDir 'daemon-process.json'

if (-not (Test-Path $BrainExe)) {
    throw "second-brain executable not found at '$BrainExe'. Run scripts\setup_windows.ps1 first."
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

if (Test-Path $PidFile) {
    try {
        $Existing = Get-Content -Raw -Path $PidFile | ConvertFrom-Json
        $ExistingProcess = Get-Process -Id ([int]$Existing.pid) -ErrorAction SilentlyContinue
        if ($ExistingProcess) {
            Write-Host "Global Second Brain daemon is already running (PID $($Existing.pid))."
            exit 0
        }
    }
    catch {
        # Stale/corrupt launcher metadata is safe to replace. The daemon has its own lock as authority.
    }
    Remove-Item -Force -Path $PidFile -ErrorAction SilentlyContinue
}

$Process = Start-Process `
    -FilePath $BrainExe `
    -ArgumentList @('daemon') `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -PassThru

@{
    pid = $Process.Id
    started_at = [DateTimeOffset]::UtcNow.ToString('o')
    repo = $RepoRoot
} | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

Write-Host "Global Second Brain daemon started (PID $($Process.Id))."
