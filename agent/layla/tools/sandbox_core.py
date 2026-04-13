import logging
import re
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger("layla")

# Thread-local effective sandbox for research missions (lab path). When set, tools use this instead of config sandbox_root.
_effective_sandbox = threading.local()
# Sandbox path cache (plan §7.1): avoid load_config on every tool call
_sandbox_cache: dict[int, tuple[Path, float]] = {}
_SANDBOX_CACHE_TTL = 2.0  # seconds

# Read-before-write: mtime recorded after read_file; write/apply_patch reject if file changed (Claude Code pattern)
_file_read_ts_lock = threading.Lock()
_FILE_READ_MTIMES: dict[str, float] = {}


def _set_read_freshness(path: Path) -> None:
    try:
        mt = path.resolve().stat().st_mtime
        with _file_read_ts_lock:
            _FILE_READ_MTIMES[str(path.resolve())] = mt
    except Exception:
        pass


def _check_read_freshness(path: Path) -> str | None:
    key = str(path.resolve())
    with _file_read_ts_lock:
        exp = _FILE_READ_MTIMES.get(key)
    if exp is None or not path.exists():
        return None
    try:
        if path.stat().st_mtime != exp:
            return "file changed since last read — re-read before editing"
    except Exception:
        pass
    return None


def _clear_read_freshness(path: Path) -> None:
    with _file_read_ts_lock:
        _FILE_READ_MTIMES.pop(str(path.resolve()), None)


def set_effective_sandbox(path: str | None) -> None:
    """Set the effective sandbox root for this thread (e.g. .research_lab/workspace). Used by research missions so read_file/list_dir accept lab paths. Clear with None when run ends."""
    _effective_sandbox.path = path
    try:
        tid = threading.get_ident()
        _sandbox_cache.pop(tid, None)
    except Exception:
        pass

def _get_sandbox() -> Path:
    import time as _time
    try:
        p = getattr(_effective_sandbox, "path", None)
        if p is not None and str(p).strip():
            return Path(p).expanduser().resolve()
    except Exception:
        pass
    tid = threading.get_ident()
    now = _time.monotonic()
    if tid in _sandbox_cache:
        cached, ts = _sandbox_cache[tid]
        if now - ts < _SANDBOX_CACHE_TTL:
            return cached
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        import runtime_safety
        root = runtime_safety.load_config().get("sandbox_root", str(Path.home()))
        result = Path(root).expanduser().resolve()
        _sandbox_cache[tid] = (result, now)
        return result
    except Exception:
        return Path.home().resolve()

# Commands that are never allowed even with allow_run=True
_SHELL_BLOCKLIST = [
    "rm", "del", "rmdir", "format", "mkfs", "dd",
    "shutdown", "reboot", "powershell", "cmd", "reg",
    "netsh", "sc", "taskkill", "cipher",
]

# Network / remote tooling blocked at shell layer (inspired by Claude Code bash policy)
_SHELL_NETWORK_DENYLIST = frozenset({
    "curl", "wget", "nc", "ncat", "netcat", "socat",
    "ssh", "scp", "sftp", "ftp", "telnet", "nmap",
    "tcpdump", "tshark", "dig", "nslookup",
})

_SHELL_INJECTION_WARN = (
    r";\s*rm\s",
    r";\s*curl\s",
    r";\s*wget\s",
    r"\$\([^)]*\)",
    r"`[^`]*`",
    r">\s*/etc/",
    r">\s*/bin/",
)

_SHELL_SAFE_LINE = (
    r"^git (status|diff|log|branch|show|blame)(\s|$)",
    r"^pwd$",
    r"^which\s",
    r"^date$",
    r"^tree(\s|$)",
    r"^ls(\s|$)",
    r"^echo\s",
    r"^cat\s",
    r"^head\s",
    r"^tail\s",
)


def shell_command_line(argv: list) -> str:
    return " ".join(str(x) for x in (argv or [])).strip()


def shell_command_is_safe_whitelisted(argv: list) -> bool:
    """Read-only / introspection commands that may skip approval when policy allows."""
    line = shell_command_line(argv)
    if not line:
        return False
    import re
    for pat in _SHELL_SAFE_LINE:
        if re.match(pat, line, re.IGNORECASE):
            return True
    return False


def _shell_executable_base(argv: list) -> str:
    if not argv:
        return ""
    a0 = str(argv[0])
    return a0.replace("\\", "/").split("/")[-1].lower().lstrip("./")


def inside_sandbox(path: Path) -> bool:
    """Check whether path is inside the configured sandbox using Path.relative_to (no string prefix tricks)."""
    try:
        sandbox = _get_sandbox()
        resolved = path.resolve()
        resolved.relative_to(sandbox)
        return True
    except (ValueError, Exception):
        return False


def _agent_registry_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _maybe_file_checkpoint(target: Path, tool_name: str) -> None:
    try:
        import runtime_safety
        from services.file_checkpoints import create_checkpoint

        cfg = runtime_safety.load_config()
        if not cfg.get("file_checkpoint_enabled", True):
            return
        create_checkpoint(
            path=target,
            workspace_root=_get_sandbox(),
            agent_dir=_agent_registry_dir(),
            tool_name=tool_name,
            cfg=cfg,
        )
    except Exception:
        pass


def _write_file_limits() -> tuple[int, int]:
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        max_b = max(1024, int(cfg.get("write_file_max_bytes", 500_000)))
        fact = max(2, int(cfg.get("write_file_explosion_factor", 5)))
        return max_b, fact
    except Exception:
        return 500_000, 5


