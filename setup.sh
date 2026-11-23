#!/usr/bin/env bash
set -e

echo "=== Job Hunter AI Setup (macOS / Linux) ==="

# Prefer Python 3.12 / 3.11 / 3.10 if installed (macOS system python3 is often 3.9)
PYTHON_BIN=""
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    PYTHON_BIN="$cand"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.10+ is required. Install it via Homebrew (brew install python@3.12) or https://www.python.org/downloads/."
  exit 1
fi

echo "Using Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment (.venv)..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "Installing Python dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "Installing Playwright Chromium..."
.venv/bin/playwright install chromium

echo ""
echo "Setup complete! Run ./run.sh to launch Job Hunter AI."
