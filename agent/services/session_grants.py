"""
agent/services/session_grants.py — D6: Per-session permission allowlist.

Session grants are in-memory only — they never persist to disk.
Lifetime: until the process restarts.

Pattern matching:
  scope="exact"   — args must exactly match grant_args
  scope="command" — grant args["command"] matches shell command via prefix/glob
  scope="tool"    — any call to that tool is allowed this session
"""
from __future__ import annotations

import fnmatch
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("layla")

_lock = threading.Lock()

@dataclass
class SessionGrant:
    tool: str
    scope: str = "tool"          # "tool" | "command" | "exact"
    args: dict = field(default_factory=dict)


_session_grants: list[SessionGrant] = []


def add_session_grant(tool: str, scope: str = "tool", args: dict | None = None) -> None:
    """Register an in-memory grant for this session.  Never touches the DB."""
    grant = SessionGrant(tool=tool, scope=scope, args=args or {})
    with _lock:
        _session_grants.append(grant)
    logger.info("session_grant added: tool=%s scope=%s", tool, scope)


def has_session_grant(tool: str, call_args: dict | None = None) -> bool:
    """Return True if a session grant covers this tool call."""
    call_args = call_args or {}
    with _lock:
        grants = list(_session_grants)
    for g in grants:
        if g.tool != tool:
            continue
        if g.scope == "tool":
            return True
        if g.scope == "exact":
            if _args_match_exact(g.args, call_args):
                return True
        if g.scope == "command":
            g_cmd = g.args.get("command", "")
            c_cmd = call_args.get("command", "")
            if g_cmd and c_cmd and fnmatch.fnmatch(c_cmd, g_cmd):
                return True
    return False


def clear_session_grants() -> None:
    """Remove all session grants (called on wakeup / session reset)."""
    with _lock:
        _session_grants.clear()
    logger.info("session_grants cleared")


def list_session_grants() -> list[dict[str, Any]]:
    with _lock:
        return [
            {"tool": g.tool, "scope": g.scope, "args": g.args}
            for g in _session_grants
        ]


# ── helpers ──────────────────────────────────────────────────────────────────

def _args_match_exact(grant_args: dict, call_args: dict) -> bool:
    """All keys in grant_args must match call_args (call_args may have extra keys)."""
    for k, v in grant_args.items():
        if call_args.get(k) != v:
            return False
    return True
