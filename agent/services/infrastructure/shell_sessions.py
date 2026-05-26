"""
Background shell sessions (OpenClaw-style process tool subset).
"""
from __future__ import annotations

import logging
import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}

_MAX_OUT_LINES = 500
_MAX_SESSIONS = 5
_ARGV_BLOCKLIST = (
    "rm",
    "del",
    "rmdir",
    "format",
    "mkfs",
    "dd",
    "shutdown",
    "reboot",
    "powershell",
    "cmd",
    "reg",
    "netsh",
    "sc",
    "taskkill",
    "cipher",
)


def _buf_append(buf: deque[str], text: str) -> None:
    for line in (text or "").splitlines():
        buf.append(line)
        while len(buf) > _MAX_OUT_LINES:
            buf.popleft()


def session_start(argv: list[str], cwd: str) -> dict[str, Any]:
    if not argv:
        return {"ok": False, "error": "Empty argv"}
    cmd0 = argv[0].lower().lstrip("./\\")
    for blocked in _ARGV_BLOCKLIST:
        if cmd0 == blocked or cmd0.endswith(blocked):
            return {"ok": False, "error": f"Command blocked: {argv[0]}"}
    cwd_path = Path(cwd).resolve()

    with _lock:
        if len(_sessions) >= _MAX_SESSIONS:
            return {"ok": False, "error": "Too many shell sessions; kill one first."}

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    sid = str(uuid.uuid4())[:12]
    buf: deque[str] = deque(maxlen=_MAX_OUT_LINES)
    with _lock:
        # Re-check after acquiring lock (another thread may have filled slots)
        if len(_sessions) >= _MAX_SESSIONS:
            try:
                proc.terminate()
            except Exception:
                pass
            return {"ok": False, "error": "Too many shell sessions; kill one first."}
        _sessions[sid] = {
            "proc": proc,
            "argv": argv,
            "cwd": str(cwd_path),
            "buffer": buf,
            "done": False,
        }

    def reader() -> None:
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    with _lock:
                        ent = _sessions.get(sid)
                        if ent:
                            _buf_append(ent["buffer"], line.rstrip("\n\r"))
        except Exception as ex:
            logger.debug("shell_session reader ended: %s", ex)
        finally:
            with _lock:
                ent = _sessions.get(sid)
                if ent:
                    ent["done"] = True

    threading.Thread(target=reader, daemon=True).start()
    return {"ok": True, "session_id": sid, "pid": proc.pid}


def session_poll(sid: str) -> dict[str, Any]:
    with _lock:
        s = _sessions.get(sid)
    if not s:
        return {"ok": False, "error": "Unknown session_id"}
    proc = s["proc"]
    code = proc.poll()
    with _lock:
        lines = len(s["buffer"])
        done = s.get("done", False)
    return {
        "ok": True,
        "running": code is None and not done,
        "returncode": code,
        "lines": lines,
    }


def session_log(sid: str, limit: int = 80) -> dict[str, Any]:
    with _lock:
        s = _sessions.get(sid)
    if not s:
        return {"ok": False, "error": "Unknown session_id"}
    proc = s["proc"]
    code = proc.poll()
    with _lock:
        lines = list(s["buffer"])[-max(1, min(limit, 500)) :]
        done = s.get("done", False)
    return {
        "ok": True,
        "output": "\n".join(lines),
        "returncode": code,
        "done": done and code is not None,
    }


def session_kill(sid: str) -> dict[str, Any]:
    with _lock:
        s = _sessions.pop(sid, None)
    if not s:
        return {"ok": False, "error": "Unknown session_id"}
    proc = s["proc"]
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return {"ok": True, "message": "Session terminated"}


def shell_session_tool(
    action: str,
    argv: list[str] | None = None,
    cwd: str = "",
    session_id: str = "",
    limit: int = 80,
) -> dict[str, Any]:
    from layla.tools.registry import inside_sandbox

    act = (action or "poll").strip().lower()

    if act == "start":
        cwd_path = Path(cwd or ".").resolve()
        if not inside_sandbox(cwd_path):
            return {"ok": False, "error": "cwd outside sandbox"}
        return session_start(list(argv or []), str(cwd_path))
    if act == "poll":
        return session_poll(session_id.strip())
    if act in ("log", "output"):
        return session_log(session_id.strip(), limit=limit)
    if act in ("kill", "stop"):
        return session_kill(session_id.strip())
    return {"ok": False, "error": f"Unknown action {act}; use start|poll|log|kill"}
