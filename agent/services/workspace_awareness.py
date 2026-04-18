"""Debounced workspace awareness: discovery + project memory scan + semantic index."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_last_scheduled: dict[str, float] = {}
_last_job_lock = threading.Lock()


def refresh_for_workspace(workspace_root: str, cfg: dict[str, Any] | None = None) -> None:
    """Schedule background refresh (discovery, scan_repo → project_memory, workspace index)."""
    import runtime_safety

    c = cfg if isinstance(cfg, dict) else runtime_safety.load_config()
    if not bool(c.get("workspace_awareness_auto_enabled", True)):
        return
    root = (workspace_root or "").strip()
    if not root:
        return
    try:
        rp = Path(root).expanduser().resolve()
    except Exception:
        return
    deb = float(c.get("workspace_awareness_debounce_seconds", 5) or 5)
    deb = max(1.0, min(120.0, deb))
    key = str(rp)
    now = time.monotonic()
    with _last_job_lock:
        if now - _last_scheduled.get(key, 0) < deb:
            return
        _last_scheduled[key] = now

    def _job() -> None:
        try:
            from services.project_discovery import run_project_discovery

            run_project_discovery()
        except Exception as e:
            logger.debug("workspace_awareness discovery: %s", e)
        try:
            from layla.tools.registry import scan_repo, set_effective_sandbox

            set_effective_sandbox(str(rp))
            scan_repo(workspace_root=str(rp), dry_run=False)
        except Exception as e:
            logger.debug("workspace_awareness scan_repo: %s", e)
        finally:
            try:
                set_effective_sandbox(None)
            except Exception:
                pass
        try:
            from services.workspace_index import index_workspace

            index_workspace(str(rp))
        except Exception as e:
            logger.debug("workspace_awareness index_workspace: %s", e)

    threading.Thread(target=_job, name="workspace-awareness", daemon=True).start()


def refresh_for_workspace_sync(workspace_root: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Immediate refresh (used by POST /workspace/awareness/refresh)."""
    import runtime_safety

    c = cfg if isinstance(cfg, dict) else runtime_safety.load_config()
    root = (workspace_root or "").strip()
    out: dict[str, Any] = {
        "ok": True,
        "workspace_root": root,
        "awareness_auto": bool(c.get("workspace_awareness_auto_enabled", True)),
    }
    if not root:
        return {"ok": False, "error": "workspace_root required"}
    rp = Path(root).expanduser().resolve()
    _se = None
    try:
        from layla.tools.registry import scan_repo, set_effective_sandbox

        _se = set_effective_sandbox
        _se(str(rp))
        out["scan_repo"] = scan_repo(workspace_root=str(rp), dry_run=False)
    except Exception as e:
        out["scan_repo_error"] = str(e)
    finally:
        if _se is not None:
            try:
                _se(None)
            except Exception:
                pass
    try:
        from services.workspace_index import index_workspace

        out["index"] = index_workspace(str(rp))
    except Exception as e:
        out["index_error"] = str(e)
    try:
        from services.project_discovery import run_project_discovery

        out["discovery"] = run_project_discovery()
    except Exception as e:
        out["discovery_error"] = str(e)
    return out
