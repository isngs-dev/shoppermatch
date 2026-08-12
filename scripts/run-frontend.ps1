# Runs the React dev server (Vite) on http://localhost:5173.
# It proxies /api, /r and /track to the backend on :8000.
# Requires: Node 18+ and npm on PATH. Start the backend first.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\frontend"

if (-not (Test-Path node_modules)) {
    Write-Host "Installing dependencies…" -ForegroundColor Cyan
    npm install
}

Write-Host "Starting frontend on http://localhost:5173…" -ForegroundColor Green
npm run dev
