# Launch GC module from repo root.
# One-shot (Task Scheduler):
#   .\launch_gc_module.ps1 -Once
# Dry-run:
#   .\launch_gc_module.ps1 -Once -DryRun
# Long-running loop (default interval from GC_INTERVAL_SEC or 3600):
#   .\launch_gc_module.ps1
param(
    [switch]$Once,
    [switch]$DryRun,
    [double]$IntervalSec = -1
)
$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$launcher = Join-Path $RepoRoot "apps\gc-module\launch.ps1"
$launchArgs = @()
if ($Once) { $launchArgs += "-Once" }
if ($DryRun) { $launchArgs += "-DryRun" }
if ($IntervalSec -ge 0) { $launchArgs += @("-IntervalSec", $IntervalSec) }
& $launcher @launchArgs
