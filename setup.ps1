# Job Hunter AI - Windows One-Click Setup
$ErrorActionPreference = "Stop"

Write-Host "=== Job Hunter AI Setup ===" -ForegroundColor Cyan

# Find Python (PATH or standard install locations)
$pythonExe = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = "python"
} else {
    $candidates = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "C:\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    if ($candidates) {
        $pythonExe = $candidates[0].FullName
    }
}

if (-not $pythonExe) {
    Write-Host "Python 3.11+ was not found. Install it with: winget install Python.Python.3.12" -ForegroundColor Yellow
    exit 1
}

Write-Host "Using Python: $pythonExe" -ForegroundColor Green

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Cyan
    & $pythonExe -m venv .venv
}

Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt

Write-Host "Installing Playwright Chromium browser..." -ForegroundColor Cyan
.\.venv\Scripts\playwright.exe install chromium

Write-Host ""
Write-Host "Setup complete! Run .\run.bat or .\run.ps1 to start Job Hunter AI." -ForegroundColor Green
