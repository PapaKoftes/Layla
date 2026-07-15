"""Approval-related helpers extracted from agent_loop.py.

Contains:
    _approval_preview_diff  -- generates unified diff previews for approval UIs
    _has_any_grant          -- checks session grants and DB grants
    _admin_pre_mutate       -- admin-mode git checkpoint + audit before mutations
    _write_pending          -- writes a pending-approval entry to .governance/pending.json
"""

import json
import logging
from pathlib import Path

import runtime_safety
from layla.tools.registry import TOOLS

logger = logging.getLogger("layla")


# ---------------------------------------------------------------------------
# 1. _approval_preview_diff
# ---------------------------------------------------------------------------

def _approval_preview_diff(tool: str, args: dict, workspace: str) -> None:
    """Add unified diff (or patch preview) to approval args for the Web UI."""
    import difflib

    try:
        max_lines = 200
        ws = Path((workspace or "").strip()).expanduser().resolve() if (workspace or "").strip() else None
        if tool == "write_file" and args.get("path") is not None and "content" in args:
            path = Path(str(args["path"]))
            if not path.is_absolute() and ws and ws.exists():
                path = (ws / path).resolve()
            else:
                path = path.expanduser().resolve()
            if not path.exists():
                args["diff"] = "(new file)"
                return
            try:
                cur = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug("approval_preview_diff write_file read failed: %s", e, exc_info=True)
                cur = ""
            newc = str(args.get("content") or "")
            diff = list(
                difflib.unified_diff(
                    cur.splitlines(True),
                    newc.splitlines(True),
                    fromfile=f"a/{path.name}",
                    tofile=f"b/{path.name}",
                    lineterm="",
                )
            )
            if len(diff) > max_lines:
                diff = diff[:max_lines] + [f"\n... ({len(diff) - max_lines} more lines omitted)\n"]
            args["diff"] = "".join(diff) if diff else "(no textual change)"
        elif tool == "apply_patch":
            pt = str(args.get("patch_text") or "")
            lines = pt.splitlines()
            if len(lines) > max_lines:
                lines = lines[:max_lines] + [f"... ({len(lines)} lines truncated)"]
            args["diff"] = "\n".join(lines) if lines else "(empty patch)"
        elif tool == "write_files_batch" and isinstance(args.get("files"), list) and args["files"]:
            first = args["files"][0]
            if isinstance(first, dict) and "path" in first and "content" in first:
                sub = {"path": first["path"], "content": first["content"]}
                _approval_preview_diff("write_file", sub, workspace)
                args["diff"] = "[batch: first file]\n" + str(sub.get("diff", ""))
            else:
                args["diff"] = "(write_files_batch: no preview)"
        elif tool == "replace_in_file" and args.get("path") and "old_text" in args and "new_text" in args:
            path = Path(str(args["path"]))
            if not path.is_absolute() and ws and ws.exists():
                path = (ws / path).resolve()
            else:
                path = path.expanduser().resolve()
            if not path.exists():
                args["diff"] = "(file missing)"
                return
            try:
                cur = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug("approval_preview_diff replace_in_file read failed: %s", e, exc_info=True)
                cur = ""
            ot = str(args.get("old_text") or "")
            nt = str(args.get("new_text") or "")
            if ot not in cur:
                args["diff"] = "(old_text not in file)"
                return
            try:
                cnt = int(args.get("count") or 1)
            except (TypeError, ValueError):
                cnt = 1
            newc = cur
            replaced = 0
            idx = 0
            while replaced < cnt:
                pos = newc.find(ot, idx)
                if pos < 0:
                    break
                newc = newc[:pos] + nt + newc[pos + len(ot) :]
                replaced += 1
                idx = pos + len(nt)
            diff = list(
                difflib.unified_diff(
                    cur.splitlines(True),
                    newc.splitlines(True),
                    fromfile=f"a/{path.name}",
                    tofile=f"b/{path.name}",
                    lineterm="",
                )
            )
            if len(diff) > max_lines:
                diff = diff[:max_lines] + [f"\n... ({len(diff) - max_lines} more lines omitted)\n"]
            args["diff"] = "".join(diff) if diff else "(no textual change)"
        elif tool == "search_replace":
            root = Path(str(args.get("root") or workspace or "")).expanduser().resolve()
            fg = str(args.get("file_glob") or "*")
            find = str(args.get("find") or "")
            repl = str(args.get("replace") or "")
            if root.is_dir() and find:
                for f in root.rglob(fg):
                    if not f.is_file():
                        continue
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                    except Exception as e:
                        logger.debug("approval_preview_diff search_replace file read failed: %s", e, exc_info=True)
                        continue
                    if find not in content:
                        continue
                    newc = content.replace(find, repl, 1)
                    diff = list(
                        difflib.unified_diff(
                            content.splitlines(True),
                            newc.splitlines(True),
                            fromfile=str(f),
                            tofile=str(f),
                            lineterm="",
                        )
                    )
                    args["diff"] = "".join(diff[:max_lines]) if diff else "(no change)"
                    return
            args["diff"] = "(search_replace: no matching file preview)"
    except Exception as e:
        args["diff"] = f"(diff preview failed: {e})"


# ---------------------------------------------------------------------------
# 2. _has_any_grant
# ---------------------------------------------------------------------------

def _has_any_grant(tool: str, args: dict | None = None) -> bool:
    """Return True if either a session grant or a DB grant covers this call (D6)."""
    try:
        from services.safety.session_grants import has_session_grant
        if has_session_grant(tool, args):
            return True
    except Exception as _exc:
        logger.warning("agent_loop:L763: %s", _exc, exc_info=True)
    try:
        from layla.memory.db import tool_grant_matches
        cmd = (args or {}).get("command") or (args or {}).get("path") or ""
        if tool_grant_matches(tool, cmd):
            return True
    except Exception as _exc:
        logger.warning("agent_loop:L770: %s", _exc, exc_info=True)
    return False


# ---------------------------------------------------------------------------
# 3. _admin_pre_mutate
# ---------------------------------------------------------------------------

def _admin_pre_mutate(cfg: dict, workspace: str, tool: str, summary: str) -> None:
    """When admin_mode: git checkpoint + audit line before a mutating tool runs."""
    if not (isinstance(cfg, dict) and cfg.get("admin_mode")):
        return
    if cfg.get("admin_auto_checkpoint", True):
        try:
            from services.safety.admin_checkpoint import git_checkpoint_layla

            git_checkpoint_layla(workspace, tool, summary)
        except Exception as _exc:
            logger.warning("agent_loop: admin checkpoint: %s", _exc, exc_info=True)
    try:
        from shared_state import get_audit

        get_audit()(tool, f"admin_auto {summary[:200]}", "admin_mode", True)
    except Exception as _exc:
        logger.warning("agent_loop: admin audit: %s", _exc, exc_info=True)


# ---------------------------------------------------------------------------
# 4. _write_pending
# ---------------------------------------------------------------------------

def _write_pending(tool: str, args: dict, ttl_seconds: int = 3600) -> str:
    """Write a pending approval entry and return its UUID. Exposes risk_level from registry for UI."""
    import uuid as _uuid
    from datetime import timedelta

    # Audit trail (logger was defined but never wired): a tool required human approval — record the
    # escalation so the security ring shows what was gated.
    try:
        from services.observability.security_audit import log_approval_escalation
        log_approval_escalation(tool, reason="pending approval queued", granted=False)
    except Exception:
        pass

    from layla.time_utils import utcnow
    gov_path = Path(__file__).resolve().parent.parent.parent / ".governance"
    gov_path.mkdir(parents=True, exist_ok=True)
    pending_file = gov_path / "pending.json"
    try:
        data = json.loads(pending_file.read_text(encoding="utf-8")) if pending_file.exists() else []
    except Exception as e:
        logger.warning("pending.json load failed: %s", e)
        data = []
    # Prune old/non-pending approvals to keep file bounded.
    try:
        from datetime import datetime, timedelta

        keep_days = 7
        cutoff = (utcnow() - timedelta(days=keep_days)).isoformat()
        pruned = []
        for r in data if isinstance(data, list) else []:
            if not isinstance(r, dict):
                continue
            st = str(r.get("status") or "pending")
            if st != "pending":
                continue
            req = str(r.get("requested_at") or "")
            if req and req < cutoff:
                continue
            pruned.append(r)
        data = pruned[-500:]
    except Exception as e:
        logger.warning("pending approval prune failed: %s", e, exc_info=True)
    entry_id = str(_uuid.uuid4())
    risk = (TOOLS.get(tool) or {}).get("risk_level") or "medium"
    now = utcnow()
    # TTL from config if available, else use caller-supplied default (3600s = 1h)
    try:
        _pcfg = runtime_safety.load_config()
        ttl_seconds = int(_pcfg.get("approval_ttl_seconds", ttl_seconds) or ttl_seconds)
    except Exception as _exc:
        logger.warning("agent_loop:L795: %s", _exc, exc_info=True)
    data.append({
        "id": entry_id,
        "tool": tool,
        "args": args,
        "requested_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=max(60, ttl_seconds))).isoformat(),
        "status": "pending",
        "risk_level": risk,
    })
    pending_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return entry_id
