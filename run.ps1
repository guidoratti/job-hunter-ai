# Job Hunter AI - Launcher
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual environment not found. Running setup.ps1 first..." -ForegroundColor Yellow
    .\setup.ps1
}

# Auto-start local Ollama server in background if installed and not already running
$ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
if (Test-Path $ollamaExe) {
    $ollamaRunning = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
    if (-not $ollamaRunning) {
        Write-Host "Starting local Ollama server in background..." -ForegroundColor DarkCyan
        Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    }
}

Write-Host "Starting Job Hunter AI at http://127.0.0.1:8000 ..." -ForegroundColor Cyan
Start-Process "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe run_server.py
