# Launch IM module (Feishu WS or DingTalk Stream courier).
# Prerequisite: fill apps/im-module/.env ; start Module A separately.
$ErrorActionPreference = "Stop"
$AppRoot = $PSScriptRoot
$Src = Join-Path $AppRoot "src"
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$Src"
Set-Location $AppRoot
Write-Host "Auto-Extract-Agent / im-module"
Write-Host "  app: $AppRoot"
python (Join-Path $Src "main.py")
