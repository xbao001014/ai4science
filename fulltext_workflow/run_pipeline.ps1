# fulltext_workflow/run_pipeline.ps1
# 用法:
#   .\run_pipeline.ps1                  # 交互菜单
#   .\run_pipeline.ps1 -Stage all       # 跑完整推荐流水线（不含 gap-debate）
#   .\run_pipeline.ps1 -Stage fetch     # 只跑某一阶段
#   .\run_pipeline.ps1 -Stage weekly          # 每周增量（fetch 最近 14 天 EDAT）
#   .\run_pipeline.ps1 -Stage fetch -SinceDays 14

param(
    [ValidateSet("init", "fetch", "enrich", "fulltext", "extract", "build", "analyze", "debate", "landscape", "stats", "all", "quick", "weekly")]
    [string]$Stage = "",
    [int]$ExtractLimit = 0,
    [int]$SinceDays = 0,
    [switch]$NoResume,
    [switch]$SkipEnrich,
    [switch]$CoreOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$py = Join-Path $Root ".." ".venv" "Scripts" "python.exe"

if (-not (Test-Path $py)) {
    $py = "python"
}

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Args
    )
    Write-Host "`n========== $Name ==========" -ForegroundColor Cyan
    & $py main.py @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Failed: main.py $($Args -join ' ')"
    }
}

function Show-Menu {
    Write-Host @"

Full-Text Workflow Pipeline
---------------------------
  1  init
  2  fetch (+ watch-fetch 请另开终端)
  3  enrich-s2 + import-if (可选)
  4  fetch-fulltext
  5  extract
  6  build
  7  analyze
  8  bootstrap-landscape
  9  gap-debate
  0  run-all (quick, limit=30)
  s  stats
  q  quit
"@
}

if (-not $Stage) {
    Show-Menu
    $choice = Read-Host "Select"
    switch ($choice) {
        "1" { $Stage = "init" }
        "2" { $Stage = "fetch" }
        "3" { $Stage = "enrich" }
        "4" { $Stage = "fulltext" }
        "5" { $Stage = "extract" }
        "6" { $Stage = "build" }
        "7" { $Stage = "analyze" }
        "8" { $Stage = "landscape" }
        "9" { $Stage = "debate" }
        "0" { $Stage = "quick" }
        "s" { $Stage = "stats" }
        "q" { exit 0 }
        default { Write-Host "Invalid"; exit 1 }
    }
}

$fetchArgs = @("fetch")
if ($NoResume) { $fetchArgs += "--no-resume" }
if ($SinceDays -gt 0) { $fetchArgs += @("--since-days", "$SinceDays") }

$extractArgs = @("extract", "--limit", "$ExtractLimit")
if ($CoreOnly) { $extractArgs += "--core-only" }

switch ($Stage) {
    "init" {
        Invoke-Step "init" @("init")
    }
    "fetch" {
        Invoke-Step "fetch" $fetchArgs
    }
    "enrich" {
        Invoke-Step "enrich-s2" @("enrich-s2")
        Invoke-Step "import-if" @("import-if")
    }
    "fulltext" {
        Invoke-Step "fetch-fulltext" @("fetch-fulltext")
    }
    "extract" {
        Invoke-Step "extract" $extractArgs
    }
    "build" {
        Invoke-Step "build" @("build")
    }
    "analyze" {
        Invoke-Step "analyze" @("analyze")
    }
    "landscape" {
        Invoke-Step "bootstrap-landscape" @("bootstrap-landscape", "--force")
    }
    "debate" {
        Invoke-Step "gap-debate" @("gap-debate", "-o", "output/gap_debate_report.md")
    }
    "stats" {
        Invoke-Step "stats" @("stats")
    }
    "weekly" {
        if ($SinceDays -le 0) { $SinceDays = 14 }
        $fetchArgs = @("fetch", "--since-days", "$SinceDays")
        if ($NoResume) { $fetchArgs += "--no-resume" }
        Invoke-Step "fetch (weekly EDAT)" $fetchArgs
        if (-not $SkipEnrich) { Invoke-Step "enrich-s2" @("enrich-s2") }
        Invoke-Step "fetch-fulltext" @("fetch-fulltext")
        $weeklyExtract = @("extract", "--limit", "$ExtractLimit", "--core-only")
        Invoke-Step "extract" $weeklyExtract
        Invoke-Step "build" @("build")
        Invoke-Step "analyze" @("analyze")
        Invoke-Step "stats" @("stats")
    }
    "quick" {
        $qa = @("run-all", "--limit", "30")
        if ($NoResume) { $qa += "--no-resume" }
        Invoke-Step "run-all" $qa
    }
    "all" {
        Invoke-Step "init" @("init")
        Invoke-Step "fetch" $fetchArgs
        if (-not $SkipEnrich) {
            Invoke-Step "enrich-s2" @("enrich-s2")
            Invoke-Step "import-if" @("import-if")
        }
        Invoke-Step "fetch-fulltext" @("fetch-fulltext")
        Invoke-Step "extract" $extractArgs
        Invoke-Step "build" @("build")
        Invoke-Step "analyze" @("analyze")
        Invoke-Step "stats" @("stats")
    }
}

Write-Host "`nDone." -ForegroundColor Green
