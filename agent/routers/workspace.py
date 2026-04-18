"""Platform control center, project context, file helpers, discovery."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import runtime_safety
from routers.paths import AGENT_DIR, REPO_ROOT
from services.route_helpers import get_cached_plugins, sync_set_project_context

logger = logging.getLogger("layla")
router = APIRouter(tags=["workspace"])


@router.get("/platform/models")
def platform_models():
    try:
        from services.model_manager import list_models

        cfg = runtime_safety.load_config()
        models = list_models()
        active = cfg.get("model_filename", "")
        catalog = []
        try:
            cat_path = AGENT_DIR / "models" / "model_catalog.json"
            if cat_path.exists():
                import json

                data = json.loads(cat_path.read_text(encoding="utf-8"))
                catalog = data.get("models", [])[:12]
        except Exception:
            pass
        benchmarks = {}
        try:
            from services.model_benchmark import get_all_benchmarks

            benchmarks = get_all_benchmarks() or {}
        except Exception:
            pass
        routing = {}
        try:
            from services.model_router import get_model_routing_summary

            routing = get_model_routing_summary(cfg)
        except Exception:
            pass
        return {
            "models": models,
            "active": active,
            "catalog": catalog,
            "benchmarks": benchmarks,
            "model_routing": routing,
        }
    except Exception as e:
        return {"models": [], "active": "", "catalog": [], "benchmarks": {}, "model_routing": {}, "error": str(e)}


@router.get("/platform/plugins")
def platform_plugins():
    try:
        cfg = runtime_safety.load_config()
        pl = get_cached_plugins(cfg)
        skills = []
        try:
            from layla.skills.registry import SKILLS

            skills = [{"name": k, "description": (v.get("description") or "")[:80]} for k, v in list(SKILLS.items())[:30]]
        except Exception:
            pass
        try:
            from capabilities.registry import CAPABILITIES

            caps_summary = {k: len(v) for k, v in CAPABILITIES.items()}
        except Exception:
            caps_summary = {}
        return {
            "skills_added": pl.get("skills_added", 0),
            "tools_added": pl.get("tools_added", 0),
            "capabilities_added": pl.get("capabilities_added", 0),
            "errors": pl.get("errors", []),
            "capabilities_by_type": caps_summary,
            "skills": skills[:15],
        }
    except Exception as e:
        return {"skills_added": 0, "tools_added": 0, "capabilities_added": 0, "errors": [str(e)], "skills": []}


@router.get("/platform/knowledge")
def platform_knowledge():
    try:
        from layla.memory.db import (
            get_all_user_identity,
            get_recent_conversation_summaries,
            get_recent_learnings,
            get_recent_relationship_memories,
            get_recent_timeline_events,
        )

        summaries = get_recent_conversation_summaries(n=5)
        rel_mems = get_recent_relationship_memories(n=5)
        learnings = get_recent_learnings(n=10)
        timeline = get_recent_timeline_events(n=10, min_importance=0.0)
        user_identity = get_all_user_identity()
        nodes = []
        try:
            from layla.memory.memory_graph import get_recent_nodes

            nodes = get_recent_nodes(n=20)
        except Exception:
            pass
        return {
            "summaries": [{"id": s.get("id"), "summary": (s.get("summary") or "")[:200]} for s in summaries],
            "relationship_memories": [{"id": r.get("id"), "user_event": (r.get("user_event") or "")[:150]} for r in rel_mems],
            "learnings": [{"id": lr.get("id"), "content": (lr.get("content") or "")[:120], "type": lr.get("type")} for lr in learnings],
            "graph_nodes": [{"label": n.get("label"), "id": n.get("id")} for n in nodes],
            "timeline": [{"id": t.get("id"), "event_type": t.get("event_type"), "content": (t.get("content") or "")[:150], "timestamp": t.get("timestamp"), "importance": t.get("importance")} for t in timeline],
            "user_identity": user_identity,
        }
    except Exception as e:
        return {"summaries": [], "relationship_memories": [], "learnings": [], "graph_nodes": [], "timeline": [], "user_identity": {}, "error": str(e)}


@router.get("/platform/projects")
def platform_projects():
    try:
        from layla.memory.db import get_project_context

        return get_project_context()
    except Exception as e:
        return {"project_name": "", "goals": "", "progress": "", "blockers": "", "last_discussed": "", "error": str(e)}


@router.get("/project_context")
def get_project_context_api():
    try:
        from layla.memory.db import get_project_context

        return get_project_context()
    except Exception as e:
        logger.warning("get_project_context failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/file_intent")
def get_file_intent_api(path: str = ""):
    if not path:
        return JSONResponse({"ok": False, "error": "path required"}, status_code=400)
    try:
        from layla.file_understanding import analyze_file

        return analyze_file(file_path=path)
    except Exception as e:
        logger.warning("file_intent failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/project_context")
async def set_project_context_api(req: Request):
    try:
        try:
            body = await req.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return await asyncio.to_thread(sync_set_project_context, body)
    except Exception as e:
        logger.warning("set_project_context failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/project_discovery")
def get_project_discovery_api():
    try:
        from services.project_discovery import run_project_discovery

        return run_project_discovery()
    except Exception as e:
        logger.warning("project_discovery failed: %s", e)
        return JSONResponse(
            {"opportunities": [], "ideas": [], "feasibility_notes": [], "error": str(e)},
            status_code=500,
        )


@router.post("/workspace/awareness/refresh")
async def workspace_awareness_refresh(request: Request):
    """Force project memory re-scan + Chroma index for a workspace (no debounce)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    root = str((body or {}).get("workspace_root") or "").strip()
    if not root:
        return JSONResponse({"ok": False, "error": "workspace_root required"}, status_code=400)
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        from pathlib import Path

        from layla.tools.registry import inside_sandbox

        rp = Path(root).expanduser().resolve()
        if not rp.is_dir() or not inside_sandbox(rp):
            return JSONResponse({"ok": False, "error": "workspace_root invalid or outside sandbox"}, status_code=400)
        from services.workspace_awareness import refresh_for_workspace_sync

        out = refresh_for_workspace_sync(root, cfg)
        return JSONResponse({"ok": True, **out})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/workspace/project_memory")
def workspace_project_memory(workspace_root: str = ""):
    """Read-only view of `.layla/project_memory.json` for the active workspace."""
    try:
        from layla.tools.registry import inside_sandbox
        from services import project_memory as pm

        root = (workspace_root or "").strip()
        if not root:
            root = str(Path.cwd())
        rp = Path(root).expanduser().resolve()
        if not rp.is_dir() or not inside_sandbox(rp):
            return JSONResponse({"ok": False, "error": "workspace_root invalid or outside sandbox"}, status_code=400)
        doc = pm.load_project_memory(rp)
        return JSONResponse({"ok": True, "project_memory": doc or {}, "workspace_root": str(rp)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/workspace/symbol_search")
def workspace_symbol_search(q: str = "", workspace_root: str = ""):
    """Thin read-only wrapper around `search_codebase` for the Web UI."""
    try:
        from layla.tools.impl.code import search_codebase
        from layla.tools.registry import inside_sandbox

        sym = (q or "").strip()
        if not sym:
            return JSONResponse({"ok": False, "error": "q required"}, status_code=400)
        root = (workspace_root or "").strip()
        if not root:
            root = str(Path.cwd())
        rp = Path(root).expanduser().resolve()
        if not rp.is_dir() or not inside_sandbox(rp):
            return JSONResponse({"ok": False, "error": "workspace_root invalid or outside sandbox"}, status_code=400)
        out = search_codebase(symbol=sym, root=str(rp))
        if isinstance(out, dict):
            out.setdefault("ok", True)
            return JSONResponse(out)
        return JSONResponse({"ok": True, "result": out})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/file_content")
def read_file_content(path: str = ""):
    if not path:
        return JSONResponse({"error": "path required"}, status_code=400)
    import runtime_safety as _rs

    try:
        cfg = _rs.load_config()
        sandbox = (cfg.get("sandbox_root") or "").strip()
        if not sandbox:
            return JSONResponse({"error": "sandbox_root not configured; file_content disabled"}, status_code=403)
        p = Path(path).resolve()
        if sandbox:
            sb = Path(sandbox).resolve()
            try:
                p.relative_to(sb)
            except ValueError:
                return JSONResponse({"error": "path outside sandbox"}, status_code=403)
        if not p.exists():
            return JSONResponse({"exists": False, "content": ""})
        if p.stat().st_size > 500_000:
            return JSONResponse({"error": "file too large (>500 KB)"}, status_code=413)
        content = p.read_text(encoding="utf-8", errors="replace")
        return JSONResponse({"exists": True, "content": content, "path": str(p)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
