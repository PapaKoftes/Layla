"""
Optional operator hooks (Claude-Code-style lifecycle hooks, local-first).

Configured via runtime_config.json:
  agent_hooks_enabled: bool (default True)
  hooks_require_allow_run: bool (default True) — pre_tool/post_tool run only if allow_run or this is False
  agent_hooks: list of { "event": "session_start"|"pre_tool"|"post_tool", "command": ["exe", "arg", ...], "timeout_seconds": number }

Environment for subprocesses:
  LAYLA_HOOK_EVENT, LAYLA_TOOL, LAYLA_CONVERSATION_ID, LAYLA_WORKSPACE_ROOT, LAYLA_TOOL_OK (post_tool only: "1" or "0")
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger("layla")


def _should_run(cfg: dict[str, Any], event: str, allow_run: bool) -> bool:
    if not cfg.get("agent_hooks_enabled", True):
        return False
    if event == "session_start":
        return True
    if not cfg.get("hooks_require_allow_run", True):
        return True
    return bool(allow_run)


def run_agent_hooks(
    event: str,
    *,
    tool_name: str = "",
    allow_run: bool = False,
    conversation_id: str = "",
    workspace_root: str = "",
    tool_ok: bool | None = None,
) -> None:
    """Run all hooks matching event. Failures are logged; never raises."""
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
    except Exception as e:
        logger.debug("agent_hooks: load_config failed: %s", e)
        return

    if not _should_run(cfg, event, allow_run):
        return

    raw = cfg.get("agent_hooks")
    if not isinstance(raw, list) or not raw:
        return

    env = os.environ.copy()
    env["LAYLA_HOOK_EVENT"] = event
    env["LAYLA_TOOL"] = tool_name or ""
    env["LAYLA_CONVERSATION_ID"] = conversation_id or ""
    env["LAYLA_WORKSPACE_ROOT"] = workspace_root or ""
    if tool_ok is not None:
        env["LAYLA_TOOL_OK"] = "1" if tool_ok else "0"

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        ev = str(entry.get("event") or "").strip().lower()
        if ev != event:
            continue
        cmd = entry.get("command")
        if not isinstance(cmd, list) or not cmd:
            logger.warning("agent_hooks: skip hook with invalid command for event=%s", event)
            continue
        argv = [str(x) for x in cmd]
        try:
            timeout = float(entry.get("timeout_seconds") or entry.get("timeout") or 5.0)
        except (TypeError, ValueError):
            timeout = 5.0
        timeout = max(0.5, min(120.0, timeout))
        cwd = workspace_root.strip() if workspace_root and os.path.isdir(workspace_root) else None
        try:
            r = subprocess.run(
                argv,
                env=env,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            if r.returncode != 0:
                logger.warning(
                    "agent_hooks: event=%s cmd=%s rc=%s stderr=%s",
                    event,
                    argv[0],
                    r.returncode,
                    (r.stderr or "")[:500],
                )
        except subprocess.TimeoutExpired:
            logger.warning("agent_hooks: event=%s cmd=%s timed out after %ss", event, argv[0], timeout)
        except Exception as e:
            logger.warning("agent_hooks: event=%s failed: %s", event, e)
