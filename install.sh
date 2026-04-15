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
  echo "  Install Python 3.11 or 3.12 from https://www.python.org/downloads/"
  echo "  or via your package manager:"
  echo "    Debian/Ubuntu:  sudo apt install python3 python3-venv python3-dev"
  echo "    Fedora:         sudo dnf install python3 python3-pip python3-devel"
  echo "    Arch:           sudo pacman -S python"
  echo "    macOS:          brew install python@3.11"
  echo ""
  exit 1
fi

PYVER=$(python3 --version 2>&1 | awk '{print $2}')
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] in ((3, 11), (3, 12)) else 1)' 2>/dev/null; then
  echo ""
  echo "  [!] Python 3.11 or 3.12 is required (3.13+ not supported yet). You have $PYVER."
  echo ""
  echo "  Upgrade via your package manager or python.org (use 3.11 or 3.12 only)"
  echo "    Debian/Ubuntu:  sudo apt install python3.12 python3.12-venv"
  echo "    Fedora:         sudo dnf install python3.12 python3-devel"
  echo ""
  exit 1
fi
echo "      Python $PYVER found."
echo ""

# ── [2/6] System build dependencies (Linux) ─────────────────────────────────
if [ "$(uname -s)" = "Linux" ]; then
  echo "  [2/6]  Checking system build dependencies (required for llama-cpp-python)..."
  MISSING=""
  command -v gcc &>/dev/null || MISSING="${MISSING} gcc"
  command -v g++ &>/dev/null || MISSING="${MISSING} g++"
  command -v cmake &>/dev/null || MISSING="${MISSING} cmake"
  if [ -n "$MISSING" ]; then
    echo ""
    echo "  [!] Build tools missing. Install them first, then re-run install.sh:"
    echo ""
    echo "    Debian/Ubuntu:  sudo apt install build-essential cmake libsndfile1"
    echo "    Fedora:         sudo dnf install python3-devel gcc-c++ cmake libsndfile"
    echo "    Arch:           sudo pacman -S base-devel cmake libsndfile"
    echo ""
    echo "  (llama-cpp-python compiles C++ code; python3-devel provides Python.h)"
    echo ""
    exit 1
  fi
  echo "      Build tools OK (gcc, g++, cmake)."
else
  echo "  [2/6]  Skipping build-deps check (non-Linux)."
fi
echo ""

# ── [3/6] Virtual environment ───────────────────────────────────────────────
echo "  [3/6]  Creating virtual environment..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  echo "      Done."
else
  echo "      .venv already exists, skipping."
fi
source .venv/bin/activate
echo ""

# ── [4/6] Dependencies ───────────────────────────────────────────────────────
echo "  [4/6]  Installing dependencies (this may take 5–15 minutes)..."
echo "        llama-cpp-python compiles on first install — be patient."
echo ""
pip install -q --upgrade pip
if ! pip install -r agent/requirements.txt; then
  echo ""
  echo "  [!] Dependency install failed."
  echo "      Check your internet connection and try again."
  echo ""
  echo "      On Linux, if you see 'No CMAKE_CXX_COMPILER' or 'Python.h not found':"
  echo "        Ubuntu: sudo apt install build-essential cmake libsndfile1"
  echo "        Fedora: sudo dnf install python3-devel gcc-c++ cmake libsndfile"
  echo "      Then re-run: bash install.sh"
  echo ""
  exit 1
fi
echo "      Dependencies installed."
echo ""

# ── [5/6] Playwright browser ────────────────────────────────────────────────
echo "  [5/6]  Setting up browser automation (Playwright)..."
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

# ── [6/6] Config wizard + verify ────────────────────────────────────────────
echo "  [6/6]  Detecting hardware, setting up config, and verifying..."
echo ""
if ! python agent/install/run_first_time.py; then
  echo ""
  echo "  [!] Setup had issues. See above for details."
  echo "      Run: python agent/diagnose_startup.py"
  echo "      See: knowledge/troubleshooting.md"
  echo ""
  exit 1
fi

# ── Launchers ───────────────────────────────────────────────────────────────
echo "  Making launchers executable..."
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
echo "   • Run  python agent/install/run_first_time.py  (or python agent/first_run.py) to configure"
echo ""
echo "   When you have a model:  bash start.sh"
echo "   Layla opens at:         http://localhost:8000/ui"
echo ""
echo "   If startup fails (Linux):  python agent/diagnose_startup.py"
echo "   See knowledge/troubleshooting.md for fixes."
echo ""
echo "   Repair deps:    .venv/bin/python agent/install/installer_cli.py repair"
echo "   Health check:   .venv/bin/python agent/install/installer_cli.py doctor"
echo "   Optional packs: .venv/bin/python agent/install/installer_cli.py packs list"
echo "   Force model URL: .venv/bin/python agent/install/installer_cli.py download '<https://...gguf>'"
echo ""
echo "  ============================================================="
echo ""
