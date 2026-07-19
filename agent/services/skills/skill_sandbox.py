"""
Skill pack DEPENDENCY ISOLATION via per-pack virtual environments.

Each skill pack runs in its own venv under ~/.layla/skill_envs/<pack_name>/.
This prevents dependency conflicts between packs and with Layla's core environment.

This module is named "sandbox" for historical reasons and the name oversells it.
It is NOT a security sandbox. There is no filesystem jail and no network
namespace: a pack's entry point is an ordinary subprocess running at the
operator's full user privilege, and it can read or write anything that account
can. What is actually enforced here is narrow and worth knowing exactly:

  - dependency isolation (a venv per pack)
  - an environment allowlist, applied to BOTH the run path and the pip path, so
    operator secrets are not handed to third-party code
  - entry-point path confinement (the resolved entry point must be inside the
    pack directory)
  - a wall-clock timeout and output truncation

The consent gates (skill_venv_enabled, skill_packs_execute_enabled) are the real
protection. See docs/SKILL_PACKS.md, "Execution: dependency isolation, NOT a
security sandbox".

Execution model:
  1. Create venv on install
  2. Install pack's declared dependencies into the venv (this executes the
     dependencies' build backends — installing is a form of executing)
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

# `None` means "resolve per call" (tests pin it by assigning a tmp dir). Was `Path.home() /
# ".layla" / "skill_envs"` at import: ignored LAYLA_DATA_DIR and was frozen before any fixture
# could redirect it.
ENVS_DIR: Path | None = None


def _envs_dir() -> Path:
    """`<LAYLA_DATA_DIR or ~>/.layla/skill_envs`, resolved per call."""
    if ENVS_DIR is not None:
        return Path(ENVS_DIR)
    from services.infrastructure.data_paths import layla_data_file
    return layla_data_file("skill_envs")

# Environment allowlist. Anything not named here is withheld from third-party code —
# pack entry points AND dependency build backends alike. Deny-by-default: a new secret
# added to Layla's environment is withheld automatically rather than leaking until
# someone remembers to blocklist it.
_SAFE_KEYS = frozenset({
    "PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "LANG",
    "SYSTEMROOT", "COMSPEC", "PATHEXT", "VIRTUAL_ENV",
})

# pip needs a little more than an entry point does: a cache location and, on
# networks that require one, a proxy and a CA bundle — otherwise installs fail on
# perfectly ordinary corporate setups. These carry no credentials.
#
# Deliberately NOT included: PIP_INDEX_URL / PIP_EXTRA_INDEX_URL and friends. A
# private-index URL routinely embeds a token, and handing that to an untrusted build
# backend is the exact leak this allowlist exists to stop. Operators who need a
# private index should configure it in pip.conf/pip.ini, which pip reads from disk.
_PIP_EXTRA_KEYS = frozenset({
    "APPDATA", "LOCALAPPDATA", "XDG_CACHE_HOME",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
})


def _filtered_env(extra_keys: frozenset[str] = frozenset()) -> dict[str, str]:
    """Layla's environment reduced to the allowlist. Never returns operator secrets."""
    import os
    allowed = _SAFE_KEYS | extra_keys
    return {k: v for k, v in os.environ.items() if k in allowed}


def _venv_dir(pack_name: str) -> Path:
    """Path to a pack's venv directory."""
    return _envs_dir() / pack_name.strip()


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
        _envs_dir().mkdir(parents=True, exist_ok=True)
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
            # Installing is executing. A dependency's PEP 517 build backend is
            # third-party code that runs during `pip install`, and with no env= it
            # inherited Layla's whole environment — proven with canaries: a spec of
            # the form "pkg @ file:///..." saw GITHUB_TOKEN and OPENAI_API_KEY. That
            # made the install path leakier than the run path, which has always
            # filtered. Same allowlist both sides now.
            env=_filtered_env(_PIP_EXTRA_KEYS),
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
    Run a pack's entry point using its dedicated venv's interpreter.

    NOT a security boundary: this is a subprocess at the operator's full
    privilege with a filtered environment, a timeout and a path-confinement
    check — no filesystem jail, no network namespace. See the module docstring.

    Returns:
        {"ok": bool, "stdout": str, "stderr": str, "exit_code": int, "timed_out": bool}
    """
    python = _venv_python(pack_name)
    if not python.exists():
        return {"ok": False, "stdout": "", "stderr": f"venv Python not found: {python}", "exit_code": -1, "timed_out": False}

    # Confinement: the resolved entry point must fall INSIDE the pack directory.
    # This was a string prefix test (``str(entry).startswith(str(pack_dir.resolve()))``),
    # which a sibling directory whose NAME EXTENDS the pack dir satisfies: pack "weather"
    # with entry_point "../weather-extra/payload.py" resolves to <base>/weather-extra/...,
    # which startswith("<base>/weather") — so it EXECUTED. Real shape: pack A runs pack B's
    # code, installed but never meant to run. ``is_relative_to`` compares path COMPONENTS
    # (the idiom already used correctly in layla/tools/impl/general.py) and has no such hole.
    # .resolve() must be INSIDE the try: it is the call that actually raises. An entry_point
    # containing a NUL byte raises ValueError ("embedded null character"), which is not an OSError
    # — so with resolve() on the line above, it escaped this handler and crashed the tool call
    # instead of returning the standard error dict.
    try:
        entry = (pack_dir / entry_point).resolve()
        _confined = entry.is_relative_to(pack_dir.resolve())
    except (OSError, ValueError) as e:
        return {"ok": False, "stdout": "", "stderr": f"invalid entry point path: {e}", "exit_code": -1, "timed_out": False}
    if not _confined:
        return {"ok": False, "stdout": "", "stderr": f"Entry point escapes pack directory: {entry_point}", "exit_code": -1, "timed_out": False}
    if not entry.exists():
        return {"ok": False, "stdout": "", "stderr": f"Entry point not found: {entry}", "exit_code": -1, "timed_out": False}

    cmd = [str(python), str(entry)]
    if args:
        cmd.extend(args)

    # Minimal environment — don't leak operator secrets into pack code.
    env = _filtered_env()
    env["LAYLA_SKILL_PACK"] = pack_name
    env["LAYLA_PACK_DIR"] = str(pack_dir)
    if env_extra:
        env.update(env_extra)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            # `stdin_data` was accepted as a parameter but never forwarded, so the
            # documented "your entry point can read JSON from stdin" contract
            # (docs/SKILL_PACKS.md) silently delivered nothing — every pack that
            # did `json.load(sys.stdin)` blocked or got EOF. Forward it.
            input=stdin_data,
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
    if not _envs_dir().exists():
        return []
    return [d.name for d in _envs_dir().iterdir() if d.is_dir()]
