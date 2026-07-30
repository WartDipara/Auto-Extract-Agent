# Launch Auto-Extract-Agent module A (long-running inbox pipeline).
# Usage: from repo root or this folder:
#   .\apps\auto-extract\launch.ps1
$ErrorActionPreference = "Stop"
$AppRoot = $PSScriptRoot
$Src = Join-Path $AppRoot "src"
$RepoRoot = (Resolve-Path (Join-Path $AppRoot "..\..")).Path
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$AppRoot;$Src;$RepoRoot"
Set-Location $AppRoot
Write-Host "Auto-Extract-Agent / auto-extract"
Write-Host "  app:  $AppRoot"
Write-Host "  repo: $RepoRoot"
python (Join-Path $Src "main.py")
