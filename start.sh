#!/usr/bin/env bash
# Layla — Linux / macOS launcher
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo ""
  echo "  [!] Virtual environment not found."
  echo "      Run: bash install.sh"
  echo ""
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
    print("")
    print("  [!] No model configured or found in models/")
    print("")
    print("  Quick fix:")
    print("    1. Run  python agent/first_run.py  — wizard can download a model")
    print("    2. Or put a .gguf in models/ and run first_run.py to select it")
    print("    3. See MODELS.md for recommendations")
    print("")
    sys.exit(1)
EOF

echo ""
echo "  ∴ Layla — http://localhost:8000/ui"
echo "  Press Ctrl+C to stop."
echo ""

# Open browser after delay (best-effort)
(sleep 3 && (xdg-open http://localhost:8000/ui 2>/dev/null || open http://localhost:8000/ui 2>/dev/null)) &

cd agent
uvicorn main:app --host 127.0.0.1 --port 8000
