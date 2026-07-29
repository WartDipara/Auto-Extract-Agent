# Purge task workspaces marked with .stop.
# One-shot (for Task Scheduler):
#   .\launch_purge_stopped.ps1
# Loop every N seconds:
#   .\launch_purge_stopped.ps1 -IntervalSec 600
param(
    [double]$IntervalSec = 0
)
$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$AppRoot = Join-Path $RepoRoot "apps\auto-extract"
$Src = Join-Path $AppRoot "src"
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$Src;$RepoRoot"
Set-Location $AppRoot
$script = Join-Path $Src "purge_stopped.py"
if ($IntervalSec -gt 0) {
    python $script --interval $IntervalSec
} else {
    python $script
}
