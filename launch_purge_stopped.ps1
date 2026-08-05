# DEPRECATED: use launch_gc_module.ps1
# Forwards to GC module (unified 7-day retention; not immediate .stop purge).
param(
    [double]$IntervalSec = 0,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
Write-Warning "launch_purge_stopped.ps1 is deprecated; use launch_gc_module.ps1"
$RepoRoot = $PSScriptRoot
$launcher = Join-Path $RepoRoot "launch_gc_module.ps1"
$launchArgs = @()
if ($IntervalSec -gt 0) {
    $launchArgs += @("-IntervalSec", $IntervalSec)
} else {
    $launchArgs += "-Once"
}
if ($DryRun) { $launchArgs += "-DryRun" }
& $launcher @launchArgs
