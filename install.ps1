# Job Hunter AI — Interactive Windows Installer
# Usage: irm https://raw.githubusercontent.com/guidoratti/job-hunter-ai/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

function Ask-YesNo([string]$Prompt, [bool]$DefaultYes = $true) {
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $ans = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($ans)) { return $DefaultYes }
    return $ans.Trim().ToLower().StartsWith("y")
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "   🎯 Job Hunter AI — Windows Installer" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$repoUrl = "https://github.com/guidoratti/job-hunter-ai.git"
$installDir = Join-Path $env:USERPROFILE "JobHunterAI"

# 1. Check Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git was not found (required to download and update Job Hunter AI)." -ForegroundColor Yellow
    if (Ask-YesNo "Install Git via winget now?" $true) {
        winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    } else {
        Write-Host "Cannot continue without Git. Install Git from https://git-scm.com/ and re-run." -ForegroundColor Red
        exit 1
    }
}

# 2. Check Python 3.10+
$pythonExe = $null
$candidates = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "C:\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
if ($candidates) {
    $pythonExe = $candidates[0].FullName
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = "python"
}

if (-not $pythonExe) {
    Write-Host "Python 3.12 was not found (required to run Job Hunter AI)." -ForegroundColor Yellow
    if (Ask-YesNo "Install Python 3.12 via winget now?" $true) {
        winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
        $candidates = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
        if ($candidates) {
            $pythonExe = $candidates[0].FullName
        } else {
            Write-Host "Python 3.12 installed! Please close and reopen PowerShell, then re-run this installer." -ForegroundColor Yellow
            exit 0
        }
    } else {
        Write-Host "Cannot continue without Python 3.10+. Install from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Using Python: $pythonExe" -ForegroundColor Green

# 3. Check Google Chrome (recommended for persistent browser automation)
$hasChrome = (Test-Path "$env:ProgramFiles\Google\Chrome\Application\chrome.exe") -or (Test-Path "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe") -or (Test-Path "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
if (-not $hasChrome) {
    Write-Host "Google Chrome was not detected (recommended for LinkedIn & ATS forms; Microsoft Edge will be used as fallback)." -ForegroundColor Yellow
    if (Ask-YesNo "Install Google Chrome via winget now?" $false) {
        winget install --id Google.Chrome -e --source winget --accept-package-agreements --accept-source-agreements
    }
}

# 4. Clone or update repository
if (Test-Path (Join-Path $installDir ".git")) {
    Write-Host "Updating existing installation in $installDir ..." -ForegroundColor Cyan
    Push-Location $installDir
    git pull origin main
} else {
    Write-Host "Cloning Job Hunter AI into $installDir ..." -ForegroundColor Cyan
    git clone $repoUrl $installDir
    Push-Location $installDir
}

# 5. Install Python dependencies & Playwright browser
if (Ask-YesNo "Create virtual environment and install Python packages + Playwright browser?" $true) {
    if (-not (Test-Path ".venv")) {
        & $pythonExe -m venv .venv
    }
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\pip.exe install -r requirements.txt
    .\.venv\Scripts\playwright.exe install chromium
}

# 6. Optional: Ollama (100% Free Local AI)
$hasOllama = (Get-Command ollama -ErrorAction SilentlyContinue) -or (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")
if (-not $hasOllama) {
    Write-Host ""
    Write-Host "Optional: Ollama lets you run 100% free, unlimited local AI models (no API bills)." -ForegroundColor Cyan
    if (Ask-YesNo "Install Ollama for free local AI now? (Skip if you prefer OpenRouter/Gemini/OpenAI/Claude)" $false) {
        irm https://ollama.com/install.ps1 | iex
        Write-Host "Ollama installed! Inside Job Hunter AI -> Settings, click 'Setup Local Server' to download models." -ForegroundColor Green
    }
}

# 7. Create Windows Start Menu shortcut with Digital Brain icon
try {
    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Job Hunter AI.lnk"
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($startMenu)
    $sc.TargetPath = Join-Path $installDir "run.bat"
    $sc.WorkingDirectory = $installDir
    $sc.Description = "Launch Job Hunter AI"
    $iconPath = Join-Path $installDir "static\app_icon.ico"
    if (Test-Path $iconPath) {
        $sc.IconLocation = "$iconPath,0"
    }
    $sc.Save()
    Write-Host "Created Windows Start Menu shortcut: Job Hunter AI" -ForegroundColor Green
} catch {
    Write-Host "Note: Could not create Start Menu shortcut automatically ($_)." -ForegroundColor Yellow
}

Pop-Location

Write-Host ""
Write-Host "✅ Job Hunter AI installed successfully!" -ForegroundColor Green
Write-Host "   Folder: $installDir" -ForegroundColor Gray
Write-Host "   Launch anytime from your Windows Start Menu ('Job Hunter AI')." -ForegroundColor Gray
Write-Host ""

if (Ask-YesNo "Launch Job Hunter AI now?" $true) {
    Start-Process -FilePath (Join-Path $installDir "run.bat") -WorkingDirectory $installDir
}
