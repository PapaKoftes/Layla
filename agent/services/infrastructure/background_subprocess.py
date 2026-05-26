"""
Spawn and manage background agent jobs in a separate OS process (hard cancel).

See background_job_worker.py and routers/agent.py integration.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent
WORKER_SCRIPT = AGENT_DIR / "background_job_worker.py"


def _popen_kwargs() -> dict[str, Any]:
    kw: dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "cwd": str(AGENT_DIR),
    }
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kw["start_new_session"] = True
    return kw


def _worker_argv(python_executable: str) -> list[str]:
    """Python argv to run background_job_worker.py; optional operator wrapper prefix from config."""
    import runtime_safety

    cfg = runtime_safety.load_config()
    exe = python_executable
    script = str(WORKER_SCRIPT)
    wrap = cfg.get("background_worker_wrapper_command")
    if isinstance(wrap, list) and len(wrap) > 0:
        return [str(x) for x in wrap if str(x).strip()] + [exe, script]
    return [exe, script]


def spawn_background_worker(job: dict[str, Any], *, python_executable: str | None = None) -> subprocess.Popen:
    """Start background_job_worker.py with JSON job on stdin."""
    import runtime_safety

    exe = python_executable or sys.executable
    if not WORKER_SCRIPT.is_file():
        raise FileNotFoundError(f"worker script missing: {WORKER_SCRIPT}")
    line = json.dumps(job, default=str, ensure_ascii=False)
    argv = _worker_argv(exe)
    proc = subprocess.Popen(  # noqa: S603 — argv is trusted local worker + optional operator wrapper
        argv,
        **_popen_kwargs(),
    )
    cfg = runtime_safety.load_config()
    try:
        from services.worker_cgroup_linux import maybe_attach_worker_to_cgroup

        _cg_rel = maybe_attach_worker_to_cgroup(proc, cfg)
        if _cg_rel:
            setattr(proc, "_layla_cgroup_rel", _cg_rel)
    except Exception:
        logger.debug("maybe_attach_worker_to_cgroup skipped", exc_info=True)
    try:
        from services.worker_os_limits import attach_windows_job_memory_limit

        attach_windows_job_memory_limit(proc, cfg)
    except Exception:
        logger.debug("attach_windows_job_memory_limit skipped", exc_info=True)
    if proc.stdin:
        proc.stdin.write(line + "\n")
        proc.stdin.close()
    return proc


def _kill_process_tree_posix(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _kill_process_tree_psutil(pid: int) -> None:
    try:
        import psutil
    except ImportError:
        return
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for c in children:
            try:
                c.kill()
            except psutil.Error:
                pass
        try:
            parent.kill()
        except psutil.Error:
            pass
    except psutil.Error:
        pass


def cleanup_worker_cgroup(proc: subprocess.Popen | None) -> None:
    """Remove leaf cgroup created for this worker, if any (Linux best-effort)."""
    if proc is None:
        return
    rel = getattr(proc, "_layla_cgroup_rel", None)
    if not rel:
        return
    try:
        from services.worker_cgroup_linux import maybe_remove_worker_cgroup

        maybe_remove_worker_cgroup(rel)
    except Exception:
        logger.debug("cleanup_worker_cgroup failed", exc_info=True)
    finally:
        try:
            delattr(proc, "_layla_cgroup_rel")
        except Exception:
            pass


def cancel_worker(proc: subprocess.Popen | None, *, grace_seconds: float = 4.0) -> None:
    """SIGTERM / terminate, wait, then SIGKILL / kill; optional psutil tree cleanup."""
    if proc is None:
        return
    if proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if os.name != "nt" and pid and pid > 0:
            _kill_process_tree_posix(pid, signal.SIGTERM)
        proc.terminate()
    except (ProcessLookupError, OSError) as e:
        logger.debug("cancel_worker terminate: %s", e)
    deadline = time.monotonic() + max(0.1, float(grace_seconds))
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    if proc.poll() is not None:
        return
    try:
        _kill_process_tree_psutil(pid)
        if os.name != "nt" and pid and pid > 0:
            _kill_process_tree_posix(pid, signal.SIGKILL)
        proc.kill()
    except (ProcessLookupError, OSError) as e:
        logger.debug("cancel_worker kill: %s", e)


def wait_worker_result(
    proc: subprocess.Popen,
    *,
    max_stdout_bytes: int = 8_000_000,
    max_stderr_bytes: int = 2_000_000,
    on_progress_event: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """
    Read stdout (final JSON) and stderr (NDJSON progress lines + tail).
    Returns (parsed_json_or_none, stderr_full_text).
    If stdout exceeds max_stdout_bytes, kills process and returns error dict.
    """
    out_parts: list[str] = []
    err_parts: list[str] = []
    total = 0
    stderr_bytes = 0
    assert proc.stdout is not None and proc.stderr is not None

    def _drain_stderr_lines() -> None:
        nonlocal stderr_bytes
        try:
            while True:
                line = proc.stderr.readline()
                if not line:
                    break
                stderr_bytes += len(line.encode("utf-8", errors="ignore"))
                if stderr_bytes > max_stderr_bytes:
                    break
                err_parts.append(line)
                if on_progress_event:
                    s = line.strip()
                    if s.startswith("{"):
                        try:
                            o = json.loads(s)
                            if isinstance(o, dict) and o.get("type") == "progress":
                                on_progress_event(o)
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass

    import threading

    t_err = threading.Thread(target=_drain_stderr_lines, daemon=True)
    t_err.start()

    try:
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_stdout_bytes:
                    cancel_worker(proc, grace_seconds=0.5)
                    proc.wait(timeout=30)
                    t_err.join(timeout=5.0)
                    return (
                        {"ok": False, "error": "stdout_exceeded_cap", "detail": str(max_stdout_bytes)},
                        "".join(err_parts),
                    )
                out_parts.append(chunk)
        finally:
            t_err.join(timeout=120.0)

        if proc.poll() is None:
            try:
                proc.wait(timeout=300)
            except subprocess.TimeoutExpired:
                cancel_worker(proc, grace_seconds=1.0)
                proc.wait(timeout=60)
        rc = proc.returncode
        stdout = "".join(out_parts).strip()
        stderr = "".join(err_parts)

        if rc not in (0, None) and not stdout:
            return (
                {"ok": False, "error": "worker_nonzero_exit", "detail": f"exit={rc}", "stderr": stderr[-4000:]},
                stderr,
            )

        if not stdout:
            return (
                {"ok": False, "error": "empty_worker_stdout", "detail": f"exit={rc}", "stderr": stderr[-4000:]},
                stderr,
            )

        try:
            return json.loads(stdout), stderr
        except json.JSONDecodeError as e:
            return (
                {
                    "ok": False,
                    "error": "worker_stdout_not_json",
                    "detail": str(e),
                    "preview": stdout[:500],
                },
                stderr,
            )
    finally:
        cleanup_worker_cgroup(proc)
