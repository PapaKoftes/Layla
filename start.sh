#!/usr/bin/env bash
# Layla — Linux / macOS launcher
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[!] Virtual environment not found. Run: bash install.sh"
  exit 1
fi
source .venv/bin/activate

# Check for a model
python - <<'EOF'
import json, pathlib, sys
cfg_path = pathlib.Path("agent/runtime_config.json")
cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
m = cfg.get("model_filename", "")
f = pathlib.Path("models") / m if m else None
if not (f and f.exists()):
    print("\n  [!] No model found in models/")
    print("      Open MODELS.md to choose one, then update agent/runtime_config.json\n")
    sys.exit(1)
EOF

echo "  Starting Layla at http://localhost:8000/ui"
echo "  Press Ctrl+C to stop."
echo

# Open browser after delay (best-effort)
(sleep 3 && (xdg-open http://localhost:8000/ui 2>/dev/null || open http://localhost:8000/ui 2>/dev/null)) &

cd agent
uvicorn main:app --host 127.0.0.1 --port 8000
