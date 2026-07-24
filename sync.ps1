param(
    [switch]$SkillsOnly,   # 只同步 skill 模板
    [switch]$ConfigOnly    # 只同步 config.yaml
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$ConfigDir   = "$ProjectRoot\config"
$HermesHome  = "$ProjectRoot\hermes-home"
$TemplatesDir = "$ConfigDir\skills-templates"
$SkillsDir   = "$HermesHome\skills"
$ConfigPath  = "$ConfigDir\config.yaml"

Write-Host "=== Sync Config & Skills ===" -ForegroundColor Cyan
Write-Host ""

# ── 1. Sync config.yaml ──
if (-not $SkillsOnly) {
    Write-Host "[1/2] Syncing config.yaml -> hermes-home/config.yaml ..." -ForegroundColor Yellow
    if (-not (Test-Path $ConfigPath)) {
        Write-Host "  ERROR: $ConfigPath not found" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $HermesHome)) { New-Item -ItemType Directory -Path $HermesHome -Force | Out-Null }
    Copy-Item $ConfigPath "$HermesHome\config.yaml" -Force
    Write-Host "  DONE" -ForegroundColor Green
}

# ── 2. Render skill templates ──
if (-not $ConfigOnly) {
    Write-Host "[2/2] Rendering skill templates..." -ForegroundColor Yellow

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
}

Write-Host ""
Write-Host "=== Sync complete ===" -ForegroundColor Cyan
Write-Host "Changes take effect on the NEXT hermes invocation (no restart needed for model/provider/skills)." -ForegroundColor White
Write-Host "For MCP server changes, restart the service (.\launch.ps1)." -ForegroundColor DarkGray
