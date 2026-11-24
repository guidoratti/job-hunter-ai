#!/usr/bin/env bash
set -e

if [ ! -f ".venv/bin/python" ]; then
  echo "Virtual environment not found. Running ./setup.sh first..."
  ./setup.sh
fi

# Ensure Python 3.9 compatibility backport is present in existing macOS venvs
.venv/bin/python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null || \
  .venv/bin/python -c "import eval_type_backport" 2>/dev/null || \
  .venv/bin/pip install -q "eval_type_backport>=0.2.0" || true

# Auto-start Ollama in background if installed and not already running
if command -v ollama >/dev/null 2>&1; then
  if ! curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Starting local Ollama server in background..."
    nohup ollama serve >/dev/null 2>&1 &
  fi
fi

echo "Starting Job Hunter AI at http://127.0.0.1:8000 ..."
(sleep 2 && (open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" 2>/dev/null || true)) &
.venv/bin/python run_server.py
