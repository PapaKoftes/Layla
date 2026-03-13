#!/usr/bin/env bash
# Layla — Linux / macOS installer
set -e
cd "$(dirname "$0")"

echo ""
echo "  ∴ LAYLA — Installer (Linux / macOS)"
echo "  ──────────────────────────────────────"
echo ""

# Python check
if ! command -v python3 &>/dev/null; then
  echo "  [!] python3 not found."
  echo "      Install it from https://www.python.org/downloads/"
  echo "      or via your package manager: sudo apt install python3 python3-venv"
  exit 1
fi
PYVER=$(python3 --version 2>&1 | awk '{print $2}')
echo "  Python $PYVER found."

# venv
if [ ! -d ".venv" ]; then
  echo "  Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

# Dependencies
echo "  Installing dependencies (may take several minutes)..."
pip install -q --upgrade pip
pip install -r agent/requirements.txt

# Playwright
echo "  Setting up browser automation..."
playwright install chromium 2>/dev/null || echo "  [note] Playwright chromium install skipped."

# Config wizard
echo ""
echo "  Running hardware detection and config setup..."
python agent/first_run.py || echo "  [note] Config wizard skipped. Edit agent/runtime_config.json manually."

# Make launchers executable
chmod +x start.sh install.sh 2>/dev/null || true

echo ""
echo "  ════════════════════════════════════════"
echo "   DONE. Next: get a model."
echo "   See MODELS.md for recommendations."
echo "   Put the .gguf file in models/"
echo "   Then run: bash start.sh"
echo "  ════════════════════════════════════════"
echo ""
