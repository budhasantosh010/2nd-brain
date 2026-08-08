[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PidFile = Join-Path $RepoRoot 'vault\.brain\runtime\daemon-process.json'

if (-not (Test-Path $PidFile)) {
    Write-Host 'No launcher PID file exists. The daemon may already be stopped.'
    exit 0
}

try {
    $State = Get-Content -Raw -Path $PidFile | ConvertFrom-Json
    $PidValue = [int]$State.pid
    $Process = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
    if ($Process) {
        Stop-Process -Id $PidValue -Force
        $Process.WaitForExit(10000)
        Write-Host "Stopped Global Second Brain daemon (PID $PidValue)."
    }
    else {
        Write-Host "Recorded daemon PID $PidValue is not running."
    }
}
finally {
    Remove-Item -Force -Path $PidFile -ErrorAction SilentlyContinue
}
