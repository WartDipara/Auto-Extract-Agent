# Launch Auto-Extract-Agent module B (archive index / follow-up).
$ErrorActionPreference = "Stop"
$AppRoot = $PSScriptRoot
$Src = Join-Path $AppRoot "src"
$RepoRoot = (Resolve-Path (Join-Path $AppRoot "..\..")).Path
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$RepoRoot"
Set-Location $AppRoot
Write-Host "Auto-Extract-Agent / archive-followup"
Write-Host "  app:  $AppRoot"
Write-Host "  repo: $RepoRoot"
python (Join-Path $Src "main.py") @args
