#!/usr/bin/env python3
"""
Desktop launcher entrypoint for Layla (bundled via PyInstaller or run with system Python).

Starts uvicorn against agent/main.py using the repo .venv interpreter and opens the Web UI.
Locates the repository without embedded paths (cwd walk, exe directory, or LAYLA_REPO).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def is_valid_repo_root(p: Path) -> bool:
    """Require both main entrypoint and runtime_safety (matches installer expectations)."""
    return (p / "agent" / "main.py").is_file() and (p / "agent" / "runtime_safety.py").is_file()


def discover_repo_root() -> Path | None:
    """Find repo root containing agent/main.py and agent/runtime_safety.py."""
    raw = (os.environ.get("LAYLA_REPO") or "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
        if is_valid_repo_root(p):
            return p

    def walk_parents(start: Path) -> Path | None:
        cur = start.resolve()
        for _ in range(28):
            if is_valid_repo_root(cur):
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
        return None

    hit = walk_parents(Path.cwd())
    if hit:
        return hit

    argv0 = Path(sys.argv[0]).resolve()
    hit = walk_parents(argv0.parent)
    if hit:
        return hit

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        hit = walk_parents(exe_dir)
        if hit:
            return hit

    return None


def _venv_python(repo: Path) -> Path:
    if sys.platform == "win32":
        return repo / ".venv" / "Scripts" / "python.exe"
    return repo / ".venv" / "bin" / "python"


def _load_port(agent_dir: Path) -> int:
    cfg_path = agent_dir / "runtime_config.json"
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return int(cfg.get("port", 8000))
        except Exception:
            pass
    return 8000


def main() -> int:
    repo = discover_repo_root()
    if repo is None:
        sys.stderr.write(
            "Layla: could not find this repository (expected agent/main.py and agent/runtime_safety.py).\n"
            "  Run from the repo root, place Layla.exe next to the clone, or set LAYLA_REPO to the clone path.\n"
        )
        return 1

    agent = repo / "agent"
    py = _venv_python(repo)
    if not py.is_file():
        print(f"Layla: missing venv Python at {py}. Run: python scripts/setup_layla.py")
        return 1
    port = _load_port(agent)
    url = f"http://127.0.0.1:{port}/ui"
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", f"--port={port}"],
        cwd=str(agent),
        env=env,
    )
    time.sleep(2.0)
    webbrowser.open(url)
    try:
        return int(proc.wait())
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
