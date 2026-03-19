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


def run_python_file(code: str, cwd: Path, *, inside_sandbox_check: Any = None) -> dict[str, Any]:
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
        run_kw: dict[str, Any] = {
            "args": [sys.executable, str(script_path)],
            "cwd": str(cwd),
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": timeout,
        }
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
