# Launch Gap Debate Streamlit UI with the project virtualenv.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path -Parent $Root
$Streamlit = Join-Path $Repo ".venv\Scripts\streamlit.exe"

if (-not (Test-Path $Streamlit)) {
    Write-Error "Project venv not found. From repo root run: python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}

Set-Location $Root
& $Streamlit run gap_ui.py @args
