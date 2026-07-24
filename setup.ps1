param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$ConfigDir = "$ProjectRoot\config"
$HermesHome = "$ProjectRoot\hermes-home"
$TemplatesDir = "$ConfigDir\skills-templates"
$SkillsDir = "$HermesHome\skills"
$ConfigPath = "$ConfigDir\config.yaml"

Write-Host "=== Hermes-Auto-Extract Setup ===" -ForegroundColor Cyan
Write-Host "Config source:  $ConfigDir"
Write-Host "Hermes HOME:    $HermesHome"
Write-Host ""

# ── 1. Create conda environment ──
Write-Host "[1/4] Creating conda environment 'agent-ida'..." -ForegroundColor Yellow
if (-not (Test-Path "$ProjectRoot\environment.yml")) {
    Write-Host "  SKIP: environment.yml not found" -ForegroundColor DarkYellow
} else {
    if ($Force) {
        conda env remove -n agent-ida -y 2>$null
    }
    $envExists = conda env list 2>$null | Select-String -Pattern "^\s*agent-ida\s"
    if (-not $envExists) {
        conda env create -f "$ProjectRoot\environment.yml"
        Write-Host "  DONE" -ForegroundColor Green
    } else {
        Write-Host "  SKIP: environment 'agent-ida' already exists (use -Force to recreate)" -ForegroundColor DarkYellow
    }
}

# ── 2. Copy config.yaml to hermes-home ──
Write-Host "[2/4] Copying config to hermes-home..." -ForegroundColor Yellow
if (-not (Test-Path $ConfigPath)) {
    Write-Host "  ERROR: $ConfigPath not found" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $HermesHome)) { New-Item -ItemType Directory -Path $HermesHome -Force | Out-Null }
Copy-Item $ConfigPath "$HermesHome\config.yaml" -Force
Write-Host "  config.yaml copied"

# ── 3. Render skill templates ──
Write-Host "[3/4] Rendering skill templates..." -ForegroundColor Yellow

$yaml = Get-Content $ConfigPath -Raw
function Get-YamlValue($yaml, $key) {
    $m = [regex]::Match($yaml, "$key\s*:\s*`"([^`"]*)`"")
    if ($m.Success) { return $m.Groups[1].Value }
    $m = [regex]::Match($yaml, "$key\s*:\s*'([^']*)'")
    if ($m.Success) { return $m.Groups[1].Value }
    $m = [regex]::Match($yaml, "$key\s*:\s*(\S+)")
    if ($m.Success) { return $m.Groups[1].Value }
    return ""
}

$toolConfig = @{
    ASSETSTUDIO_PATH   = Get-YamlValue $yaml "assetstudio"
    IL2CPP_PATH        = Get-YamlValue $yaml "il2cppdumper"
    IL2CPP_CONFIG_PATH = Get-YamlValue $yaml "il2cppdumper_config"
    HERMES_ROOT        = $HermesHome.Replace('\', '/')
    HERMES_ROOT_WIN    = $HermesHome
}

Write-Host "  ASSETSTUDIO_PATH = $($toolConfig.ASSETSTUDIO_PATH)"
Write-Host "  IL2CPP_PATH = $($toolConfig.IL2CPP_PATH)"

if (Test-Path $TemplatesDir) {
    Get-ChildItem $TemplatesDir -Recurse -Filter "SKILL.md" | ForEach-Object {
        $content = Get-Content $_.FullName -Raw
        foreach ($key in $toolConfig.Keys) {
            $content = $content -replace "{{$key}}", $toolConfig[$key]
        }
        $relPath = $_.FullName.Substring($TemplatesDir.Length + 1)
        $outPath = Join-Path $SkillsDir $relPath
        $outDir = Split-Path $outPath -Parent
        if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
        Set-Content -Path $outPath -Value $content -NoNewline
        Write-Host "  SKILL: $relPath" -ForegroundColor Gray
    }
    Get-ChildItem $TemplatesDir -Recurse -File | Where-Object { $_.Name -ne "SKILL.md" } | ForEach-Object {
        $relPath = $_.FullName.Substring($TemplatesDir.Length + 1)
        $outPath = Join-Path $SkillsDir $relPath
        $outDir = Split-Path $outPath -Parent
        if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
        Copy-Item $_.FullName $outPath -Force
        Write-Host "  FILE: $relPath" -ForegroundColor Gray
    }
    Write-Host "  DONE" -ForegroundColor Green
} else {
    Write-Host "  SKIP: $TemplatesDir not found" -ForegroundColor DarkYellow
}

# ── 4. Check .env ──
Write-Host "[4/4] Checking .env..." -ForegroundColor Yellow
$envDest = "$HermesHome\.env"
$envExample = "$ConfigDir\.env.example"
if (-not (Test-Path $envDest) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envDest
    Write-Host "  Created .env from .env.example" -ForegroundColor Green
    Write-Host "  ⚠  Please edit $envDest and fill in API keys" -ForegroundColor Yellow
} elseif (Test-Path $envDest) {
    Write-Host "  OK: .env exists" -ForegroundColor Green
} else {
    Write-Host "  SKIP: .env.example not found" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Cyan
Write-Host "Run launch.ps1 to start the pipeline:" -ForegroundColor White
Write-Host "  .\launch.ps1" -ForegroundColor Green
