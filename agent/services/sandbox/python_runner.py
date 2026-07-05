"""Run a Python snippet from a temp file under sandbox cwd with timeout."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("layla")


def _python_timeout_seconds(default: float = 30.0) -> float:
    try:
        import runtime_safety

        return max(5.0, float(runtime_safety.load_config().get("sandbox_python_timeout_seconds", default)))
    except Exception:
        return default


def _resource_limit_mb() -> int:
    try:
        import runtime_safety

        return max(0, int(runtime_safety.load_config().get("sandbox_python_memory_limit_mb", 0)))
    except Exception:
        return 0


def _apply_resource_limits() -> None:
    try:
        import resource

        mb = _resource_limit_mb()
        if mb > 0:
            bytes_ = mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (bytes_, bytes_))
    except Exception:
        pass


# BL-025: an app-level network jail for sandboxed exec. Loaded via a sitecustomize.py at
# interpreter startup (so it runs before the user script AND doesn't shift its line numbers).
# Blocks the paths every Python HTTP client goes through (socket + DNS), so requests/urllib/
# httpx all fail closed. Not a kernel-level jail (a raw syscall could bypass), but it stops the
# realistic cases and composes with url_guard (egress allowlist) + the OS rlimits/cgroups tier.
_NET_JAIL = (
    "# Layla sandbox network jail (BL-025)\n"
    "try:\n"
    "    import socket as _sk\n"
    "    def _blocked(*a, **k):\n"
    "        raise OSError('network access is disabled in the Layla sandbox')\n"
    "    for _n in ('socket', 'create_connection', 'socketpair', 'create_server',\n"
    "               'getaddrinfo', 'gethostbyname', 'gethostbyname_ex'):\n"
    "        try:\n"
    "            setattr(_sk, _n, _blocked)\n"
    "        except Exception:\n"
    "            pass\n"
    "except Exception:\n"
    "    pass\n"
)


def run_python_file(code: str, cwd: Path, *, inside_sandbox_check: Any = None, allow_network: bool = True) -> dict[str, Any]:
    if inside_sandbox_check is not None and not inside_sandbox_check(cwd):
        return {"ok": False, "error": "cwd outside sandbox"}
    timeout = _python_timeout_seconds(30.0)
    tmpdir: Path | None = None
    preexec: Callable[[], None] | None = None
    if _resource_limit_mb() > 0 and os.name != "nt":
        preexec = _apply_resource_limits
    try:
        tmpdir = Path(tempfile.mkdtemp(prefix="layla_py_"))
        script_path = tmpdir / "script.py"
        script_path.write_text(code or "", encoding="utf-8")
        env: dict[str, str] | None = None
        if not allow_network:
            # sitecustomize is auto-imported at startup when its dir is on PYTHONPATH.
            (tmpdir / "sitecustomize.py").write_text(_NET_JAIL, encoding="utf-8")
            env = dict(os.environ)
            env["PYTHONPATH"] = str(tmpdir) + os.pathsep + env.get("PYTHONPATH", "")
        run_kw: dict[str, Any] = {
            "args": [sys.executable, str(script_path)],
            "cwd": str(cwd),
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": timeout,
        }
        if env is not None:
            run_kw["env"] = env
        if preexec is not None:
            run_kw["preexec_fn"] = preexec
        proc = subprocess.run(**run_kw)
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "")[:4000],
            "stderr": (proc.stderr or "")[:2000],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"run_python timed out ({int(timeout)}s)"}
    except Exception as e:
        logger.debug("run_python_file: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        if tmpdir is not None:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass
