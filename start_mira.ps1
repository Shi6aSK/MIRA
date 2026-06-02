# MIRA Quick Start Script
# Run this to initialize and start the system

Write-Host "🤖 MIRA - Multi-Intelligence Robotic Agent" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
Write-Host "Checking Python installation..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Python not found. Please install Python 3.10+" -ForegroundColor Red
    exit 1
}
Write-Host "✅ $pythonVersion" -ForegroundColor Green

# Check if virtual environment exists
Write-Host ""
Write-Host "Checking virtual environment..." -ForegroundColor Yellow
if (-Not (Test-Path "backend\.venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    cd backend
    python -m venv .venv
    cd ..
    Write-Host "✅ Virtual environment created" -ForegroundColor Green
} else {
    Write-Host "✅ Virtual environment exists" -ForegroundColor Green
}

# Activate virtual environment
Write-Host ""
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& "backend\.venv\Scripts\Activate.ps1"

# Check if requirements are installed
Write-Host ""
Write-Host "Checking dependencies..." -ForegroundColor Yellow
$fastapi = pip show fastapi 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    pip install -r backend\requirements.txt
    Write-Host "✅ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "✅ Dependencies already installed" -ForegroundColor Green
}

# Check if Playwright is installed
Write-Host ""
Write-Host "Checking Playwright..." -ForegroundColor Yellow
$playwrightCheck = playwright --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Playwright browsers..." -ForegroundColor Yellow
    playwright install chromium
    Write-Host "✅ Playwright installed" -ForegroundColor Green
} else {
    Write-Host "✅ Playwright ready" -ForegroundColor Green
}

# Check if .env exists
Write-Host ""
Write-Host "Checking configuration..." -ForegroundColor Yellow
if (-Not (Test-Path "backend\.env")) {
    Write-Host "Creating .env from template..." -ForegroundColor Yellow
    Copy-Item "backend\.env.template" "backend\.env"
    Write-Host "⚠️  Please edit backend\.env with your settings (OpenAI key, robot IP, etc.)" -ForegroundColor Yellow
    Write-Host "✅ Configuration file created" -ForegroundColor Green
} else {
    Write-Host "✅ Configuration exists" -ForegroundColor Green
}

# Check if Ollama is running
Write-Host ""
Write-Host "Checking Ollama (local AI)..." -ForegroundColor Yellow
try {
    $ollamaTest = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -ErrorAction Stop
    Write-Host "✅ Ollama is running" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Ollama not running. Please start it in a separate terminal:" -ForegroundColor Yellow
    Write-Host "   ollama serve" -ForegroundColor Cyan
    Write-Host "   (Download from: https://ollama.com)" -ForegroundColor Cyan
}

# Create directories
Write-Host ""
Write-Host "Creating directories..." -ForegroundColor Yellow
@("memory", "memory\project", "memory\episodes", "memory\sources", "memory\persona", "memory\skills", "memory\interactions", "knowledge_base") | ForEach-Object {
    if (-Not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ -Force | Out-Null
    }
}
Write-Host "✅ Directories created" -ForegroundColor Green

# Summary
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "MIRA Setup Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Edit backend\.env with your configuration" -ForegroundColor White
Write-Host "2. Start Ollama (if not running): ollama serve" -ForegroundColor White
Write-Host "3. Start MIRA backend: python backend\api_server.py" -ForegroundColor White
Write-Host "4. Access API docs: http://localhost:8000/docs" -ForegroundColor White
Write-Host ""
Write-Host "To start MIRA now, run:" -ForegroundColor Yellow
Write-Host "  python backend\api_server.py" -ForegroundColor Cyan
Write-Host ""

# Ask if user wants to start
$response = Read-Host "Start MIRA backend now? (y/n)"
if ($response -eq "y" -or $response -eq "Y") {
    Write-Host ""
    Write-Host "🚀 Starting MIRA..." -ForegroundColor Green
    cd backend
    python api_server.py
}
