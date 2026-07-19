# fulltext_workflow/run_pipeline.ps1
# Usage:
#   .\run_pipeline.ps1                  # interactive menu
#   .\run_pipeline.ps1 -Stage all       # full pipeline (no gap-debate)
#   .\run_pipeline.ps1 -Stage fetch     # single stage
#   .\run_pipeline.ps1 -Stage weekly    # weekly: EDAT → extract → lifecycle → hotspot → build/analyze
#   .\run_pipeline.ps1 -Stage db        # DB only: fetch → enrich → fulltext → extract

param(
    [ValidateSet("init", "fetch", "enrich", "fulltext", "extract", "build", "analyze", "debate", "landscape", "stats", "all", "quick", "weekly", "db")]
    [string]$Stage = "",
    [int]$ExtractLimit = 0,
    [int]$SinceDays = 0,
    [switch]$NoResume,
    [switch]$SkipEnrich,
    [switch]$CoreOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path -Parent $Root
Set-Location $Root
# Windows PowerShell 5.1 Join-Path only accepts 2 args; keep child as one relative path
$py = Join-Path $Repo ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    $py = "python"
}

function Invoke-Step {
    param(
        [string]$Name,
        # Do not name this $Args — conflicts with PowerShell automatic $args
        [string[]]$CmdArgs
    )
    Write-Host "`n========== $Name ==========" -ForegroundColor Cyan
    & $py main.py @CmdArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed: main.py $($CmdArgs -join ' ')"
    }
}

function Show-Menu {
    Write-Host @"

Full-Text Workflow Pipeline
---------------------------
  1  init
  2  fetch (+ watch-fetch in another terminal)
  3  enrich-s2 + import-if (optional)
  4  fetch-fulltext
  5  extract
  6  build
  7  analyze
  8  bootstrap-landscape
  9  gap-debate
  0  run-all (quick, limit=30)
  d  run-db (fetch -> enrich -> fulltext -> extract)
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
        "d" { $Stage = "db" }
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
        Invoke-Step "compute-gap-lifecycle" @("compute-gap-lifecycle")
        Invoke-Step "hotspot-report" @("hotspot-report")
        Invoke-Step "hotspot-brief" @("hotspot-brief")
        Invoke-Step "build" @("build")
        Invoke-Step "analyze" @("analyze")
        Invoke-Step "stats" @("stats")
    }
    "quick" {
        $qa = @("run-all", "--limit", "30")
        if ($NoResume) { $qa += "--no-resume" }
        Invoke-Step "run-all" $qa
    }
    "db" {
        $dbArgs = @("run-db", "--limit", "$ExtractLimit")
        if ($NoResume) { $dbArgs += "--no-resume" }
        if ($SinceDays -gt 0) { $dbArgs += @("--since-days", "$SinceDays") }
        if ($SkipEnrich) { $dbArgs += "--skip-enrich" }
        if ($CoreOnly) { $dbArgs += "--core-only" }
        Invoke-Step "run-db" $dbArgs
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
        Invoke-Step "compute-gap-lifecycle" @("compute-gap-lifecycle")
        Invoke-Step "build" @("build")
        Invoke-Step "analyze" @("analyze")
        Invoke-Step "stats" @("stats")
    }
}

Write-Host "`nDone." -ForegroundColor Green
