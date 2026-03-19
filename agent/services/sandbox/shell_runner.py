"""Sandboxed shell command execution: timeout, cwd check, optional allowlist."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_DEFAULT_BLOCKLIST = (
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


def _runner_timeout_seconds(default: float = 60.0) -> float:
    try:
        import runtime_safety

        return max(5.0, float(runtime_safety.load_config().get("sandbox_runner_timeout_seconds", default)))
    except Exception:
        return default


def _allowlist_config() -> tuple[bool, frozenset[str]]:
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        restrict = bool(cfg.get("shell_restrict_to_allowlist", False))
        extra = cfg.get("shell_allowlist_extra")
        names: set[str] = set()
        if isinstance(extra, list):
            names.update(str(x).strip().lower() for x in extra if str(x).strip())
        elif isinstance(extra, str) and extra.strip():
            names.update(x.strip().lower() for x in extra.split(",") if x.strip())
        return restrict, frozenset(names)
    except Exception:
        return False, frozenset()


def _cmd_blocked(argv: list[str], blocklist: tuple[str, ...] = _DEFAULT_BLOCKLIST) -> str | None:
    if not argv:
        return "Empty command"
    cmd = argv[0].lower().lstrip("./\\")
    for blocked in blocklist:
        if cmd == blocked or cmd.endswith(blocked):
            return f"Command blocked: {argv[0]}"
    restrict, allow_extra = _allowlist_config()
    if restrict:
        allowed = {"git", "python", "pytest", "pip", "uv", "cargo", "go", "npm", "node", "rg", "dir", "ls"} | set(allow_extra)
        base = cmd.split("/")[-1].split("\\")[-1]
        if base not in allowed:
            return f"Command not in allowlist: {argv[0]}"
    return None


def run_shell_argv(
    argv: list[str],
    cwd: Path,
    *,
    inside_sandbox_check: Any = None,
) -> dict[str, Any]:
    """
    Run argv with cwd. inside_sandbox_check: callable(Path) -> bool; if None, caller must ensure cwd is safe.
    """
    if inside_sandbox_check is not None and not inside_sandbox_check(cwd):
        return {"ok": False, "error": "cwd outside sandbox"}
    err = _cmd_blocked(argv)
    if err:
        return {"ok": False, "error": err}
    timeout = _runner_timeout_seconds(60.0)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "")[:4000],
            "stderr": (proc.stderr or "")[:2000],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out ({int(timeout)}s)"}
    except Exception as e:
        logger.debug("run_shell_argv: %s", e)
        return {"ok": False, "error": str(e)}
