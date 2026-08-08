[CmdletBinding()]
param(
    [switch]$RemoveEnvironment
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TaskName = 'Global Second Brain'
$StopScript = Join-Path $PSScriptRoot 'stop_brain.ps1'

& $StopScript

$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed Windows scheduled task '$TaskName'."
}

if ($RemoveEnvironment) {
    $Venv = Join-Path $RepoRoot '.venv'
    if (Test-Path $Venv) {
        Remove-Item -Recurse -Force -Path $Venv
        Write-Host 'Removed the local Python virtual environment.'
    }
}

Write-Host 'Windows integration removed.'
Write-Host "Personal brain data was NOT deleted: $(Join-Path $RepoRoot 'vault')"
