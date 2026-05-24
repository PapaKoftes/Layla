#!/usr/bin/env python3
"""
Startup diagnostic for Layla. Run from repo root: python agent/diagnose_startup.py
Or from agent/: python diagnose_startup.py

Identifies common Linux (Ubuntu/Fedora) failure points before running uvicorn.
Uses install.checks for shared verification logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure agent/ is on path
AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from install.checks import (  # noqa: E402
    verify_build_tools,
    verify_config,
    verify_core_imports,
    verify_model,
    verify_python_version,
)


def main() -> int:
    print("")
    print("  Layla — Startup Diagnostic")
    print("  ------------------------------")
    print("")

    failed = []

    # Python version
    py_ok, py_msg = verify_python_version()
    if not py_ok:
        print(f"  [FAIL] {py_msg}")
        failed.append("Python version")
    else:
        print(f"  [OK] {py_msg}")

    # Build tools (Linux)
    for tool, ok, msg in verify_build_tools():
        if ok:
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failed.append(tool)

    # Core + optional imports
    for mod, ok, msg, optional in verify_core_imports():
        if ok:
            print(f"  [OK] {msg}")
        elif optional:
            print(f"  [--] {msg} (optional)")
        else:
            print(f"  [FAIL] {msg}")
            failed.append(mod)

    # Config
    cfg_ok, cfg_msg, cfg_path = verify_config(AGENT_DIR)
    if cfg_ok:
        print(f"  [OK] {cfg_msg}")
    else:
        print(f"  [FAIL] {cfg_msg}")
        failed.append("config")

    # Model
    model_ok, model_msg = verify_model(cfg_path)
    if model_ok:
        print(f"  [OK] {model_msg}")
    else:
        print(f"  [--] {model_msg}")

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
        if "llama_cpp" in failed:
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
