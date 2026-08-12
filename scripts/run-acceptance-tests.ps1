# Runs the end-to-end acceptance test (section 29 of the scope) in-process.
# Requires: Python 3.11+ on PATH.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\backend"

if (-not (Test-Path .venv)) {
    python -m venv .venv
}
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt

Write-Host "Running acceptance tests…" -ForegroundColor Green
& $py -m pytest
