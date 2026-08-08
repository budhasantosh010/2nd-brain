[CmdletBinding()]
param(
    [switch]$RegisterAtLogin
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$BrainExe = Join-Path $RepoRoot '.venv\Scripts\second-brain.exe'
$TaskName = 'Global Second Brain'

function Invoke-Brain {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if (Test-Path $BrainExe) {
        & $BrainExe @Arguments
    }
    elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv run second-brain @Arguments
    }
    else {
        throw 'second-brain is not installed. Run setup again after installing Python 3.12+ or uv.'
    }
    if ($LASTEXITCODE -ne 0) {
        throw "second-brain $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Set-Location $RepoRoot
Write-Host "Setting up Global Second Brain in: $RepoRoot"

if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv sync
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed with exit code $LASTEXITCODE" }
}
else {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    if (-not $Python) { $Python = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $Python) { throw 'Python 3.12+ or uv is required.' }
    & $Python.Source -m venv (Join-Path $RepoRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Creating .venv failed.' }
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -e $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw 'Installing global-second-brain failed.' }
}

Invoke-Brain init
Invoke-Brain doctor

$VaultPath = Join-Path $RepoRoot 'vault'
Write-Host "Obsidian vault: $VaultPath"

if ($RegisterAtLogin) {
    $StartScript = Join-Path $PSScriptRoot 'start_brain.ps1'
    $Action = New-ScheduledTaskAction `
        -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`""
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Description 'Starts the local Global Second Brain daemon at user logon.' `
        -Force | Out-Null
    Write-Host "Registered '$TaskName' to start at logon."
}

Write-Host 'Setup complete.'
