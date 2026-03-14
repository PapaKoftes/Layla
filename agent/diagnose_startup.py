#!/usr/bin/env python3
"""
Startup diagnostic for Layla. Run from repo root: python agent/diagnose_startup.py
Or from agent/: python diagnose_startup.py

Identifies common Linux (Ubuntu/Fedora) failure points before running uvicorn.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure agent/ is on path
AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

def _check(name: str, fn, optional: bool = False) -> bool:
    try:
        fn()
        print(f"  [OK] {name}")
        return True
    except Exception as e:
        if optional:
            print(f"  [--] {name} (optional, skipped: {e})")
        else:
            print(f"  [FAIL] {name}: {e}")
        return False


def main() -> int:
    print("")
    print("  Layla — Startup Diagnostic")
    print("  ------------------------------")
    print("")

    failed = []

    # Python
    v = sys.version_info
    if v >= (3, 11):
        print(f"  [OK] Python {v.major}.{v.minor}.{v.micro}")
    else:
        print(f"  [FAIL] Python 3.11+ required, have {v.major}.{v.minor}.{v.micro}")
        failed.append("Python version")

    # Build tools (Linux)
    if sys.platform == "linux":
        import shutil
        for cmd, pkg in [("gcc", "build-essential"), ("g++", "build-essential"), ("cmake", "cmake")]:
            if shutil.which(cmd):
                print(f"  [OK] {cmd} found")
            else:
                print(f"  [FAIL] {cmd} not found — install: sudo apt install {pkg} (Ubuntu) or sudo dnf install gcc-c++ cmake (Fedora)")
                failed.append(cmd)

    # Core imports
    _check("fastapi", lambda: __import__("fastapi"))
    _check("uvicorn", lambda: __import__("uvicorn"))
    if not _check("llama_cpp", lambda: __import__("llama_cpp"), optional=False):
        failed.append("llama_cpp — run: pip install llama-cpp-python (needs build-essential/cmake on Linux)")
    _check("chromadb", lambda: __import__("chromadb"), optional=True)
    _check("sentence_transformers", lambda: __import__("sentence_transformers"))
    _check("psutil", lambda: __import__("psutil"))

    # Optional
    _check("playwright", lambda: __import__("playwright"), optional=True)
    _check("soundfile", lambda: __import__("soundfile"), optional=True)
    _check("faster_whisper", lambda: __import__("faster_whisper"), optional=True)

    # Config
    cfg_path = REPO_ROOT / "agent" / "runtime_config.json"
    if not cfg_path.exists():
        cfg_path = AGENT_DIR / "runtime_config.json"
    if cfg_path.exists():
        print("  [OK] Config:", cfg_path)
    else:
        print("  [FAIL] No runtime_config.json — run: python agent/first_run.py")
        failed.append("config")

    # Model
    try:
        import json
        raw = cfg_path.read_text().strip() if cfg_path.exists() else ""
        cfg = json.loads(raw) if raw else {}
        m = cfg.get("model_filename", "")
        md = cfg.get("models_dir", "~/.layla/models")
        from pathlib import Path
        models_dir = Path(md).expanduser().resolve()
        model_path = models_dir / m if m else None
        if model_path and model_path.exists():
            print(f"  [OK] Model: {model_path}")
        elif cfg.get("llama_server_url"):
            print(f"  [OK] Remote LLM: {cfg.get('llama_server_url')}")
        else:
            print(f"  [--] No model file — configure model_filename and place .gguf in models/ or {md}")
    except Exception as e:
        print(f"  [--] Model check: {e}")

    # App load (the real test)
    print("")
    print("  Loading main:app...")
    try:
        import main
        assert main.app is not None
        print("  [OK] main:app loaded")
    except Exception as e:
        print(f"  [FAIL] Could not load main:app: {e}")
        failed.append("app load")
        import traceback
        traceback.print_exc()

    print("")
    if failed:
        print("  ----------------------------------------")
        print("   FIXES:")
        print("  ----------------------------------------")
        if "gcc" in failed or "g++" in failed or "cmake" in failed:
            print("  • Ubuntu: sudo apt install build-essential cmake libsndfile1")
            print("  • Fedora: sudo dnf install python3-devel gcc-c++ cmake libsndfile")
        if "llama_cpp" in str(failed):
            print("  • pip install llama-cpp-python  (after installing build tools)")
        if "config" in failed:
            print("  • python agent/first_run.py  or  python agent/install/installer_cli.py")
        print("  See: knowledge/troubleshooting.md")
        print("")
        return 1
    run_cmd = "START.bat" if sys.platform == "win32" else "bash start.sh"
    print(f"  All checks passed. Run: {run_cmd}  or  cd agent && python -m uvicorn main:app")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
