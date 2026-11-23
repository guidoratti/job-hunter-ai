#!/usr/bin/env bash
# Job Hunter AI — Interactive macOS & Linux Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/guidoratti/job-hunter-ai/main/install.sh | bash
set -e

ask_yes_no() {
  local prompt="$1"
  local default_yes="$2"
  local suffix="[Y/n]"
  if [ "$default_yes" = "false" ]; then suffix="[y/N]"; fi
  local ans=""
  if [ -r /dev/tty ]; then
    read -r -p "$prompt $suffix " ans < /dev/tty || true
  fi
  if [ -z "$ans" ]; then
    [ "$default_yes" = "true" ] && return 0 || return 1
  fi
  case "$ans" in
    [Yy]*) return 0 ;;
    *) return 1 ;;
  esac
}

echo ""
echo "=============================================="
echo "   🎯 Job Hunter AI — macOS / Linux Installer"
echo "=============================================="
echo ""

OS_NAME="$(uname -s)"
REPO_URL="https://github.com/guidoratti/job-hunter-ai.git"
INSTALL_DIR="$HOME/JobHunterAI"

# 1. Check git
if ! command -v git >/dev/null 2>&1; then
  echo "git was not found (required to download Job Hunter AI)."
  if [ "$OS_NAME" = "Darwin" ]; then
    if ask_yes_no "Trigger macOS Command Line Tools (git) installation now?" true; then
      xcode-select --install || true
      echo "Complete the macOS dialog, then re-run this installer."
      exit 0
    fi
  elif command -v apt-get >/dev/null 2>&1; then
    if ask_yes_no "Install git via apt now?" true; then
      sudo apt-get update && sudo apt-get install -y git
    fi
  fi
  if ! command -v git >/dev/null 2>&1; then
    echo "❌ Cannot continue without git."
    exit 1
  fi
fi

# 2. Check Python 3.10+ (macOS default python3 is often 3.9)
PYTHON_BIN=""
for cand in python3.12 python3.11 python3.10; do
  if command -v "$cand" >/dev/null 2>&1; then
    PYTHON_BIN="$cand"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PY_VER="$(python3 --version 2>&1)"
    echo "Detected $PY_VER (Python 3.10+ is recommended, though 3.9 is supported via backport)."
    if [ "$OS_NAME" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
      if ask_yes_no "Install Python 3.12 via Homebrew now?" true; then
        brew install python@3.12
        PYTHON_BIN="python3.12"
      else
        PYTHON_BIN="python3"
      fi
    else
      PYTHON_BIN="python3"
    fi
  else
    echo "Python 3 was not found (required to run Job Hunter AI)."
    if [ "$OS_NAME" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
      if ask_yes_no "Install Python 3.12 via Homebrew now?" true; then
        brew install python@3.12
        PYTHON_BIN="python3.12"
      fi
    elif command -v apt-get >/dev/null 2>&1; then
      if ask_yes_no "Install python3 & python3-venv via apt now?" true; then
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
        PYTHON_BIN="python3"
      fi
    fi
  fi
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "❌ Python 3.10+ is required. Install from https://www.python.org/downloads/ and re-run."
  exit 1
fi
echo "Using Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

# 3. Clone or update repository
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "Updating existing installation in $INSTALL_DIR ..."
  cd "$INSTALL_DIR"
  git pull origin main
else
  echo "Cloning Job Hunter AI into $INSTALL_DIR ..."
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

chmod +x setup.sh run.sh

# 4. Install Python dependencies & Playwright Chromium
if ask_yes_no "Create virtual environment and install Python packages + Playwright Chromium?" true; then
  ./setup.sh
fi

# 5. Optional: Ollama (100% Free Local AI)
if ! command -v ollama >/dev/null 2>&1; then
  echo ""
  echo "Optional: Ollama lets you run 100% free, unlimited local AI models (no API bills)."
  if ask_yes_no "Install Ollama for free local AI now? (Skip if you prefer OpenRouter/Gemini/OpenAI/Claude)" false; then
    curl -fsSL https://ollama.com/install.sh | sh
    echo "✅ Ollama installed! Inside Job Hunter AI -> Settings, click 'Setup Local Server' to download models."
  fi
fi

# 6. Create desktop / app-menu launcher
if [ "$OS_NAME" = "Darwin" ]; then
  DESKTOP_CMD="$HOME/Desktop/Job Hunter AI.command"
  cat > "$DESKTOP_CMD" <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
./run.sh
EOF
  chmod +x "$DESKTOP_CMD"
  echo "✅ Created macOS double-click launcher: $DESKTOP_CMD"
elif [ "$OS_NAME" = "Linux" ]; then
  APP_DIR="$HOME/.local/share/applications"
  mkdir -p "$APP_DIR"
  cat > "$APP_DIR/job-hunter-ai.desktop" <<EOF
[Desktop Entry]
Name=Job Hunter AI
Comment=Local-First AI Job Search & Application Assistant
Exec=$INSTALL_DIR/run.sh
Path=$INSTALL_DIR
Icon=$INSTALL_DIR/static/app_icon.png
Terminal=true
Type=Application
Categories=Utility;Office;
EOF
  echo "✅ Created Linux application launcher: $APP_DIR/job-hunter-ai.desktop"
fi

echo ""
echo "✅ Job Hunter AI installed successfully!"
echo "   Folder: $INSTALL_DIR"
echo ""

if ask_yes_no "Launch Job Hunter AI now?" true; then
  ./run.sh
fi
