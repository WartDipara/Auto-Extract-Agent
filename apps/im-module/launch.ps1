# Launch IM module (Feishu WS or DingTalk Stream courier).
# Prerequisite: fill apps/im-module/.env ; start Module A separately.
$ErrorActionPreference = "Stop"
$AppRoot = $PSScriptRoot
$Src = Join-Path $AppRoot "src"
$RepoRoot = (Resolve-Path (Join-Path $AppRoot "..\..")).Path
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$Src;$RepoRoot"
Set-Location $AppRoot
Write-Host "Auto-Extract-Agent / im-module"
Write-Host "  app:  $AppRoot"
Write-Host "  repo: $RepoRoot"
python (Join-Path $Src "main.py")
