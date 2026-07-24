$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

$env:HERMES_HOME = "$ProjectRoot\hermes-home"

Write-Host "=== Hermes-Auto-Extract ===" -ForegroundColor Cyan
Write-Host "HERMES_HOME = $env:HERMES_HOME"
Write-Host ""

conda activate agent-ida
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to activate conda env 'agent-ida'. Run setup.ps1 first." -ForegroundColor Red
    exit 1
}

python "$ProjectRoot\src\main.py"
