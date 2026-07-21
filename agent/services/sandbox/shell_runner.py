"""Sandboxed shell command execution: timeout, cwd check, optional allowlist."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_DEFAULT_BLOCKLIST = (
    # Destructive / system-modifying primitives
    "rm",
    "del",
    "rmdir",
    "format",
    "mkfs",
    "dd",
    "shutdown",
    "reboot",
    "reg",
    "netsh",
    "sc",
    "taskkill",
    "cipher",
    "wmic",
    # Shell INTERPRETERS: each runs arbitrary sub-commands (e.g. `bash -c "rm -rf /"`),
    # nullifying this argv-level blocklist, so the interpreter itself must be blocked.
    # (BL-296: pwsh/bash were missing — powershell/cmd were already here.)
    "powershell",
    "cmd",
    "pwsh",
    "bash",
    # P13-C4: `sh`, `zsh` and `wsl` were still missing, which left the previous round half-done —
    # blocking `bash` while allowing `sh -c "..."` blocks a name, not a capability. Git for Windows
    # ships sh.exe on the vast majority of dev machines, so this was reachable here specifically.
    # `wsl` matters most: on Windows `wsl <cmd>` runs the command in a full Linux environment, i.e.
    # entirely outside every guard in this file. Basename EQUALITY means "ssh" and "sha256sum" are
    # unaffected — only a command literally named `sh` matches.
    "sh",
    "zsh",
    "wsl",
    # LOLBins: download / remote-exec primitives (the URL-ingestion injection path the
    # threat frame names). curl.exe is intentionally NOT here — it ships with Windows,
    # is commonly legitimate, and app network egress is governed by url_guard, not this
    # blocklist; wget is not shipped by default so blocking it costs nothing. (BL-296.)
    "wget",
    "certutil",
    "bitsadmin",
    "mshta",
    "rundll32",
)

# Suffixes Windows will execute; strip ONE of these before matching so "powershell.exe",
# "PowerShell.EXE" and r"C:\Windows\System32\rm.exe" all normalize to the bare name the
# blocklist is written in. The filesystem jail (layla/tools/sandbox_core.py) already
# normalizes-then-compares and survived every escape; the shell blocklist compared WITHOUT
# normalizing and let every .exe form through — this closes that gap. (BL-296.)
_EXECUTABLE_SUFFIXES = frozenset({".exe", ".cmd", ".bat", ".com", ".ps1", ".msc", ".scr", ".pif", ".vbs"})


def _normalize_cmd_name(raw: str) -> str:
    """Reduce an argv[0] to the bare, lower-cased command name for blocklist matching.

    Strips surrounding quotes, any directory prefix (both separators), and a single
    trailing executable extension. "charm"/"disc"/"add" are untouched (basename equality,
    not endswith), so legitimate names that merely embed a blocked token are not caught.
    """
    s = (raw or "").strip().strip('"').strip("'")
    base = s.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    # Windows resolves an executable name by STRIPPING trailing dots and spaces first, so `rm.exe.`,
    # `rm.exe ` and `rm.exe...` all launch `rm.exe`. And a single splitext left one exec suffix on
    # `rm.exe.exe`. Both were live bypasses (verified: `rm.exe.` slipped the blocklist). Loop, peeling a
    # trailing exec suffix OR trailing dots/spaces each pass, until the name is stable — so no stacking of
    # dots/spaces/suffixes can smuggle a blocked command past basename equality.
    while True:
        stripped = base.rstrip(". ")            # Windows drops trailing dots and spaces on resolution
        root, ext = os.path.splitext(stripped)
        if ext in _EXECUTABLE_SUFFIXES:
            stripped = root
        if stripped == base:
            break
        base = stripped
    return base


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
    # Normalize (strip dir, casefold, strip a trailing .exe/.cmd/.bat/... ) BEFORE matching,
    # so powershell.exe / PowerShell.EXE / C:\...\rm.exe cannot walk past a blocklist written
    # in bare names. Basename equality, NOT endswith, so "charm"/"disc"/"add" are not caught.
    name = _normalize_cmd_name(argv[0])
    if name in blocklist:
        return f"Command blocked: {argv[0]}"
    restrict, allow_extra = _allowlist_config()
    if restrict:
        allowed = {"git", "python", "pytest", "pip", "uv", "cargo", "go", "npm", "node", "rg", "dir", "ls"} | set(allow_extra)
        if name not in allowed:
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
