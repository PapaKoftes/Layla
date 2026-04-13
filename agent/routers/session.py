"""Session export, compaction, audit, learnings list, system export."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from layla.time_utils import utcnow
from routers.paths import REPO_ROOT
from services.route_helpers import sync_compact_history
from shared_state import get_history, get_read_pending
from version import __version__

logger = logging.getLogger("layla")
router = APIRouter(tags=["session"])


@router.post("/compact")
async def compact_conversation():
    """Compact server in-memory conversation history."""
    return await asyncio.to_thread(sync_compact_history)


@router.get("/ctx_viz")
def ctx_viz():
    import runtime_safety
    from services.context_budget import get_budgets
    from services.context_manager import token_estimate_messages

    cfg = runtime_safety.load_config()
    n_ctx = int(cfg.get("n_ctx", 4096))
    budgets = get_budgets(n_ctx, cfg)
    _history = get_history()
    dict_msgs = [{"role": m.get("role"), "content": m.get("content", "")} for m in _history if isinstance(m, dict)]
    conv = token_estimate_messages(dict_msgs)
    return {"n_ctx": n_ctx, "budgets": budgets, "sections": {"conversation_history": conv}}


@router.get("/session/export")
def session_export(conversation_id: str | None = None):
    cid = (conversation_id or "").strip()
    out: dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "conversation_id": cid or None,
    }
    if cid:
        try:
            from layla.memory.db import get_conversation, get_conversation_messages

            out["conversation"] = get_conversation(cid)
            out["messages"] = get_conversation_messages(cid, limit=500)
        except Exception as e:
            logger.debug("session_export conversation %s: %s", cid, e)
            out["conversation_error"] = str(e)
    try:
        out["server_history_tail"] = list(get_history())[-50:]
    except Exception:
        out["server_history_tail"] = []
    try:
        _read_pending = get_read_pending()
        out["pending_approvals"] = [p for p in _read_pending() if p.get("status") == "pending"]
    except Exception as e:
        out["pending_approvals"] = []
        out["pending_error"] = str(e)
    return JSONResponse(out)


@router.get("/system_export")
def system_export():
    import runtime_safety
    from layla.memory.db import get_active_study_plans, get_last_wakeup, get_recent_audit, get_recent_learnings
    from layla.tools.registry import TOOLS

    cfg = runtime_safety.load_config()
    learnings_count = 0
    try:
        learnings_count = len(get_recent_learnings(n=9999))
    except Exception:
        pass
    _read_pending = get_read_pending()
    pending_list = _read_pending()
    pending_count = len([e for e in pending_list if e.get("status") == "pending"])
    try:
        active_plans = [p.get("topic") for p in get_active_study_plans()]
    except Exception:
        active_plans = []
    try:
        last_wakeup_row = get_last_wakeup()
    except Exception:
        last_wakeup_row = None
    audit_last = []
    try:
        rows = get_recent_audit(n=10)
        audit_last = [
            f"{r['timestamp']} | {r['tool']} | {r['args_summary']} | {r['approved_by']} | {'ok' if r['result_ok'] else 'fail'}"
            for r in rows
        ]
    except Exception:
        pass
    try:
        from orchestrator import _load_aspects

        aspects_loaded = [a.get("id") for a in _load_aspects()]
    except Exception:
        aspects_loaded = []
    model_path = str(runtime_safety.resolve_model_path(cfg))
    git_status = ""
    git_branch = ""
    pip_freeze = ""
    try:
        r = subprocess.run(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        git_status = (r.stdout or "").strip() or (r.stderr or "").strip() or "not a git repo"
    except Exception as e:
        git_status = str(e)
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        git_branch = (r.stdout or "").strip() or "—"
    except Exception as e:
        git_branch = str(e)
    try:
        r = subprocess.run(
            [getattr(sys, "executable", "python"), "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        pip_freeze = (r.stdout or "").strip()
    except Exception as e:
        pip_freeze = str(e)
    _history = get_history()
    return JSONResponse({
        "timestamp": utcnow().isoformat(),
        "config": cfg,
        "pending_count": pending_count,
        "learnings_count": learnings_count,
        "active_study_plans": active_plans,
        "last_wakeup": (last_wakeup_row or {}).get("timestamp"),
        "aspects_loaded": aspects_loaded,
        "tools_registered": list(TOOLS.keys()),
        "conversation_turns_in_memory": len(_history),
        "model_path": model_path,
        "audit_last_10": audit_last,
        "git_status": git_status,
        "git_branch": git_branch,
        "pip_freeze": pip_freeze,
    })


@router.get("/learnings")
def list_learnings(page: int = 1, limit: int = 20, type: str = ""):
    try:
        from layla.memory.db import _conn, migrate

        migrate()
        offset = (max(1, page) - 1) * limit
        with _conn() as db:
            if type:
                rows = db.execute(
                    "SELECT id, content, type, created_at, embedding_id FROM learnings WHERE type=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (type, limit, offset),
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM learnings WHERE type=?", (type,)).fetchone()[0]
            else:
                rows = db.execute(
                    "SELECT id, content, type, created_at, embedding_id FROM learnings ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        return JSONResponse({"page": page, "limit": limit, "total": total, "items": [dict(r) for r in rows]})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/learnings/{learning_id}")
def delete_learning(learning_id: int):
    try:
        from layla.memory.db import _conn, migrate

        migrate()
        with _conn() as db:
            row = db.execute("SELECT embedding_id FROM learnings WHERE id=?", (learning_id,)).fetchone()
            if not row:
                return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
            embedding_id = row["embedding_id"] or ""
            db.execute("DELETE FROM learnings WHERE id=?", (learning_id,))
            db.commit()
        if embedding_id:
            try:
                from layla.memory.vector_store import delete_vectors_by_ids

                delete_vectors_by_ids([embedding_id])
            except Exception:
                pass
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/audit")
def list_audit(page: int = 1, limit: int = 50, tool: str = ""):
    try:
        from layla.memory.db import _conn, migrate

        migrate()
        offset = (max(1, page) - 1) * limit
        with _conn() as db:
            if tool:
                rows = db.execute(
                    "SELECT id, timestamp, tool, args_summary, approved_by, result_ok FROM audit WHERE tool=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (tool, limit, offset),
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM audit WHERE tool=?", (tool,)).fetchone()[0]
            else:
                rows = db.execute(
                    "SELECT id, timestamp, tool, args_summary, approved_by, result_ok FROM audit ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        return JSONResponse({"page": page, "limit": limit, "total": total, "items": [dict(r) for r in rows]})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
