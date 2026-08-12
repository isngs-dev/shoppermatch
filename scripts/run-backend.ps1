# Runs the FastAPI backend locally with SQLite (no Docker / Postgres needed).
# Requires: Python 3.11+ on PATH.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\backend"

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment…" -ForegroundColor Cyan
    python -m venv .venv
}

$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt

# Keep a caller-supplied PUBLIC_BASE_URL (or the project-root .env value) intact.
# The localhost fallback preserves the Vite development flow when no .env exists.
if (-not $env:PUBLIC_BASE_URL -and -not (Test-Path "$PSScriptRoot\..\.env")) {
    $env:PUBLIC_BASE_URL = "http://localhost:5173"
}

Write-Host "Seeding demo data…" -ForegroundColor Cyan
& $py -m app.seed

Write-Host "Starting API on http://localhost:8000 (docs at /docs)…" -ForegroundColor Green
& $py -m uvicorn app.main:app --reload --port 8000
