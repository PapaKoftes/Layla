#!/usr/bin/env bash
# Layla — Linux / macOS installer
# Linux install flow thanks to Kai.
set -e
cd "$(dirname "$0")"

echo ""
echo "  ∴ LAYLA — Installer (Linux / macOS)"
echo "  ──────────────────────────────────────"
echo "  Linux install flow thanks to Kai."
echo ""

# ── [1/6] Python check ───────────────────────────────────────────────────────
echo "  [1/6]  Checking Python..."
if ! command -v python3 &>/dev/null; then
  echo ""
  echo "  [!] python3 not found."
  echo ""
  echo "  Install Python 3.11+ from https://www.python.org/downloads/"
  echo "  or via your package manager:"
  echo "    Debian/Ubuntu:  sudo apt install python3 python3-venv python3-dev"
  echo "    Fedora:         sudo dnf install python3 python3-pip"
  echo "    Arch:           sudo pacman -S python"
  echo "    macOS:          brew install python@3.11"
  echo ""
  exit 1
fi

PYVER=$(python3 --version 2>&1 | awk '{print $2}')
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo ""
  echo "  [!] Python 3.11+ is required. You have $PYVER."
  echo ""
  echo "  Upgrade via your package manager or python.org"
  echo "    Debian/Ubuntu:  sudo apt install python3.11 python3.11-venv"
  echo "    Fedora:         sudo dnf install python3.11"
  echo ""
  exit 1
fi
echo "      Python $PYVER found."
echo ""

# ── [2/6] Virtual environment ───────────────────────────────────────────────
echo "  [2/6]  Creating virtual environment..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  echo "      Done."
else
  echo "      .venv already exists, skipping."
fi
source .venv/bin/activate
echo ""

# ── [3/6] Dependencies ───────────────────────────────────────────────────────
echo "  [3/6]  Installing dependencies (this may take 5–15 minutes)..."
echo "        llama-cpp-python compiles on first install — be patient."
echo ""
pip install -q --upgrade pip
if ! pip install -r agent/requirements.txt; then
  echo ""
  echo "  [!] Dependency install failed."
  echo "      Check your internet connection and try again."
  echo ""
  exit 1
fi
echo "      Dependencies installed."
echo ""

# ── [4/6] Playwright browser ────────────────────────────────────────────────
echo "  [4/6]  Setting up browser automation (Playwright)..."
if [ "$(uname -s)" = "Linux" ]; then
  echo "        Installing Chromium system libraries (Linux)..."
  playwright install-deps chromium 2>/dev/null || true
fi
if playwright install chromium 2>/dev/null; then
  echo "      Browser ready."
else
  echo "      [note] Playwright setup skipped — browser tools may be limited."
  echo "        Run 'playwright install chromium' later if needed."
fi
echo ""

# ── [5/6] Config wizard ─────────────────────────────────────────────────────
echo "  [5/6]  Detecting hardware and setting up config..."
echo ""
if python agent/first_run.py; then
  echo ""
else
  echo ""
  echo "  [note] Config wizard had issues. You can run it again later:"
  echo "        python agent/first_run.py"
  echo "        Or edit agent/runtime_config.json manually. See MODELS.md."
  echo ""
fi

# ── [6/6] Launchers ─────────────────────────────────────────────────────────
echo "  [6/6]  Making launchers executable..."
chmod +x start.sh install.sh 2>/dev/null || true
echo "      Done."
echo ""

# ── Done ─────────────────────────────────────────────────────────────────────
echo "  ═══════════════════════════════════════════════════════════"
echo "   INSTALLATION COMPLETE"
echo "  ═══════════════════════════════════════════════════════════"
echo ""
echo "   If the setup wizard didn't download a model:"
echo "   • Open MODELS.md to pick one for your hardware"
echo "   • Put the .gguf file in  models/"
echo "   • Run  python agent/first_run.py  to configure it"
echo ""
echo "   When you have a model:  bash start.sh"
echo "   Layla opens at:         http://localhost:8000/ui"
echo ""
echo "  ═══════════════════════════════════════════════════════════"
echo ""
