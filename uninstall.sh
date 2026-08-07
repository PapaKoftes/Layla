#!/usr/bin/env bash
# ============================================================================
# Layla - Clean Uninstaller (macOS / Linux)
# Removes the uv-bootstrap install: .venv, models (optional), data (optional).
#
#   ./uninstall.sh            interactive - asks what to keep
#   ./uninstall.sh --purge    COMPLETE wipe, no prompts (venv + models + data +
#                             config + knowledge + logs)
#
# The shared uv-managed Python is left in place (other apps may use it).
# ============================================================================
set -u
REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"

PURGE=0
case "${1:-}" in
  --purge|--all|-p) PURGE=1 ;;
  "" ) ;;
  * ) echo "unknown option: $1 (use --purge for a full wipe)" >&2; exit 2 ;;
esac

echo ""
echo "  . LAYLA - Uninstaller"
echo "  -------------------------"
echo ""

# 1) stop any running Layla server (started from this repo)
echo "  [1/4] Stopping any running Layla ..."
pkill -f "$REPO.*serve.py"   >/dev/null 2>&1 || true
pkill -f "$REPO.*main:app"   >/dev/null 2>&1 || true

# 2) decide what to remove
LAYLA_HOME="$HOME/.layla"
if [ "$PURGE" = "1" ]; then
  echo "  [2/4] --purge: removing EVERYTHING (venv, models, data, config, knowledge, logs)."
  KEEP_MODELS=n; KEEP_DATA=n
else
  echo "  [2/4] What would you like to keep?   (tip: ./uninstall.sh --purge wipes all)"
  printf "        Keep downloaded AI models? (Y/n) "; read -r KEEP_MODELS || true
  printf "        Keep your data, memories & conversations? (Y/n) "; read -r KEEP_DATA || true
  KEEP_MODELS="${KEEP_MODELS:-Y}"; KEEP_DATA="${KEEP_DATA:-Y}"
fi

# 3) remove the virtual environment
echo "  [3/4] Removing virtual environment ..."
[ -d "$REPO/.venv" ] && rm -rf "$REPO/.venv" && echo "        Removed .venv" || echo "        No .venv found."

# 4) optional models + data
echo "  [4/4] Cleaning up ..."
lc() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

if [ "$(lc "$KEEP_MODELS")" = "n" ]; then
  echo "        Removing downloaded models ..."
  rm -rf "$REPO/models" "$LAYLA_HOME/models" 2>/dev/null || true
  [ -n "${LAYLA_DATA_DIR:-}" ] && rm -rf "$LAYLA_DATA_DIR/models" 2>/dev/null || true
fi

if [ "$(lc "$KEEP_DATA")" = "n" ]; then
  echo "        Removing data, config and secrets ..."
  rm -f  "$REPO/layla.db" "$REPO/layla.db-wal" "$REPO/layla.db-shm" 2>/dev/null || true
  rm -f  "$REPO/agent/runtime_config.json" 2>/dev/null || true
  rm -rf "$REPO/agent/.layla" "$LAYLA_HOME" 2>/dev/null || true
  [ -n "${LAYLA_DATA_DIR:-}" ] && rm -rf "$LAYLA_DATA_DIR" 2>/dev/null || true
fi

# always-safe housekeeping
rm -rf "$REPO/agent/logs" 2>/dev/null || true
find "$REPO" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "  -------------------------"
echo "  Layla has been removed."
if [ "$(lc "$KEEP_DATA")" != "n" ]; then
  echo "  Your data is preserved at: $LAYLA_HOME (re-install to continue where you left off)."
fi
echo "  Note: the shared uv-managed Python was left in place (uninstall via 'uv python uninstall 3.12' if unused)."
echo ""
