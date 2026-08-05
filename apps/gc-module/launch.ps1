# Launch GC module (mark-sweep reclaim of Module A artifacts).
# Usage:
#   .\apps\gc-module\launch.ps1
#   .\apps\gc-module\launch.ps1 -Once
#   .\apps\gc-module\launch.ps1 -DryRun -Once
param(
    [switch]$Once,
    [switch]$DryRun,
    [double]$IntervalSec = -1
)
$ErrorActionPreference = "Stop"
$AppRoot = $PSScriptRoot
$Src = Join-Path $AppRoot "src"
$RepoRoot = (Resolve-Path (Join-Path $AppRoot "..\..")).Path
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$AppRoot;$Src;$RepoRoot"
Set-Location $AppRoot
Write-Host "Auto-Extract-Agent / gc-module"
Write-Host "  app:  $AppRoot"
Write-Host "  repo: $RepoRoot"
$argv = @()
if ($Once) { $argv += "--once" }
if ($DryRun) { $argv += "--dry-run" }
if ($IntervalSec -ge 0) { $argv += @("--interval", "$IntervalSec") }
python (Join-Path $Src "main.py") @argv
