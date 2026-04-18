#!/usr/bin/env python3
"""
Build Desktop/Layla.exe via PyInstaller (one-file) from repo-root launcher.py.

The launcher resolves the repo at runtime (no embedded paths).

Usage (from repo root):
  python scripts/build_launcher.py

Requires: pip install pyinstaller
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "launcher.py"


def main() -> int:
    if not LAUNCHER.is_file():
        print(f"Missing {LAUNCHER}")
        return 1

    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], cwd=str(REPO_ROOT), check=False)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--onefile",
        "--name",
        "Layla",
        str(LAUNCHER),
    ]
    print("Running:", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if r.returncode != 0:
        return int(r.returncode)

    built = REPO_ROOT / "dist" / ("Layla.exe" if sys.platform == "win32" else "Layla")
    if not built.is_file():
        print(f"Expected output missing: {built}")
        return 1

    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        dest = desktop / ("Layla.exe" if sys.platform == "win32" else "Layla")
        shutil.copy2(built, dest)
        print(f"Copied to {dest}")
    else:
        print(f"No Desktop folder at {desktop}; exe is at {built}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
