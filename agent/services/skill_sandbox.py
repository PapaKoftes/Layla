"""
Skill pack sandboxing via per-pack virtual environments.

Each skill pack runs in its own venv under ~/.layla/skill_envs/<pack_name>/.
This prevents dependency conflicts between packs and with Layla's core environment.

Execution model:
  1. Create venv on install
  2. Install pack's declared dependencies into the venv
  3. Run entry_point via subprocess with the venv's Python
  4. Capture stdout/stderr, enforce timeout
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

ENVS_DIR = Path.home() / ".layla" / "skill_envs"


def _venv_dir(pack_name: str) -> Path:
    """Path to a pack's venv directory."""
    return ENVS_DIR / pack_name.strip()


def _venv_python(pack_name: str) -> Path:
    """Path to the Python executable inside a pack's venv."""
    vdir = _venv_dir(pack_name)
    if sys.platform == "win32":
        return vdir / "Scripts" / "python.exe"
    return vdir / "bin" / "python"


def create_venv(pack_name: str) -> tuple[bool, str]:
    """Create a virtual environment for a pack. Returns (success, message)."""
    vdir = _venv_dir(pack_name)
    if vdir.exists():
        return True, f"venv already exists: {vdir}"
    try:
        ENVS_DIR.mkdir(parents=True, exist_ok=True)
        venv.create(str(vdir), with_pip=True, clear=False)
        python = _venv_python(pack_name)
        if not python.exists():
            return False, f"venv created but Python not found at {python}"
        return True, f"venv created: {vdir}"
    except Exception as e:
        return False, f"Failed to create venv: {e}"


def install_dependencies(pack_name: str, dependencies: list[str]) -> tuple[bool, str]:
    """Install pip dependencies into a pack's venv."""
    if not dependencies:
        return True, "No dependencies to install"

    python = _venv_python(pack_name)
    if not python.exists():
        return False, f"venv Python not found: {python}"

    try:
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet"] + dependencies,
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()[:500]
            return False, f"pip install failed (exit {result.returncode}): {stderr}"
        return True, f"Installed {len(dependencies)} dependencies"
    except subprocess.TimeoutExpired:
        return False, "pip install timed out (300s)"
    except Exception as e:
        return False, f"pip install error: {e}"


def run_entry_point(
    pack_name: str,
    pack_dir: Path,
    entry_point: str,
    *,
    args: list[str] | None = None,
    stdin_data: str | None = None,
    timeout_seconds: int = 60,
    env_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Run a pack's entry point in its sandboxed venv.

    Returns:
        {"ok": bool, "stdout": str, "stderr": str, "exit_code": int, "timed_out": bool}
    """
    python = _venv_python(pack_name)
    if not python.exists():
        return {"ok": False, "stdout": "", "stderr": f"venv Python not found: {python}", "exit_code": -1, "timed_out": False}

    entry = pack_dir / entry_point
    if not entry.exists():
        return {"ok": False, "stdout": "", "stderr": f"Entry point not found: {entry}", "exit_code": -1, "timed_out": False}

    cmd = [str(python), str(entry)]
    if args:
        cmd.extend(args)

    import os
    env = dict(os.environ)
    env["LAYLA_SKILL_PACK"] = pack_name
    env["LAYLA_PACK_DIR"] = str(pack_dir)
    if env_extra:
        env.update(env_extra)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(pack_dir),
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:5000],
            "exit_code": result.returncode,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Timed out after {timeout_seconds}s",
            "exit_code": -1,
            "timed_out": True,
        }
    except Exception as e:
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(e)[:2000],
            "exit_code": -1,
            "timed_out": False,
        }


def remove_venv(pack_name: str) -> tuple[bool, str]:
    """Remove a pack's virtual environment."""
    import shutil
    vdir = _venv_dir(pack_name)
    if not vdir.exists():
        return True, "venv does not exist"
    try:
        shutil.rmtree(str(vdir))
        return True, f"Removed venv: {vdir}"
    except Exception as e:
        return False, f"Failed to remove venv: {e}"


def venv_exists(pack_name: str) -> bool:
    """Check if a pack has a venv."""
    return _venv_python(pack_name).exists()


def list_venvs() -> list[str]:
    """List all pack names with venvs."""
    if not ENVS_DIR.exists():
        return []
    return [d.name for d in ENVS_DIR.iterdir() if d.is_dir()]
