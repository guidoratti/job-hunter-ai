#!/usr/bin/env bash
set -e

echo "=== Job Hunter AI Setup (macOS / Linux) ==="

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11+ is required. Install it from https://www.python.org/downloads/ or via Homebrew/apt."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment (.venv)..."
  python3 -m venv .venv
fi

echo "Installing Python dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "Installing Playwright Chromium..."
.venv/bin/playwright install chromium

echo ""
echo "Setup complete! Run ./run.sh to launch Job Hunter AI."
