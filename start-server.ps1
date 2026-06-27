# Naukri AI Job Agent - Start Script
# Launches both backend (FastAPI) and frontend (React) servers

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
if (-not $root) { $root = Get-Location }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Naukri.com AI Job Agent - Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment if present
$venvActivate = Join-Path $root ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    Write-Host "[*] Activating Python virtual environment..." -ForegroundColor Yellow
    & $venvActivate
}

# Start frontend dev server (Vite on port 3000) as a background job
Write-Host "[*] Starting frontend server (port 3000)..." -ForegroundColor Yellow
$frontendJob = Start-Job -ScriptBlock {
    Set-Location $using:root\webapp
    npm run dev
}

Start-Sleep -Seconds 2

# Open browser
Write-Host "[*] Opening http://localhost:3000 in browser..." -ForegroundColor Green
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Both servers starting!" -ForegroundColor Green
Write-Host "  Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "  Frontend: http://localhost:3000" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop both servers." -ForegroundColor Gray
Write-Host ""

# Start backend server (FastAPI on port 8000) in foreground
try {
    Set-Location $root
    python server.py
} finally {
    # Cleanup: stop frontend job when backend stops
    Write-Host "`n[*] Stopping frontend server..." -ForegroundColor Yellow
    Stop-Job -Job $frontendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $frontendJob -Force -ErrorAction SilentlyContinue
    Get-Process -Name node -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "[*] All servers stopped." -ForegroundColor Green
}
