"""Health, version, updates, diagnostics, usage, and related system endpoints (extracted from main)."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from version import __version__

logger = logging.getLogger("layla")

router = APIRouter(tags=["system"])

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _health_checks() -> tuple[bool, str]:
    """Returns (ok, detail). Config and DB must pass; model/remote not checked (slow)."""
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        if not isinstance(cfg, dict):
            return False, "config_invalid"
    except Exception as e:
        logger.debug("health config: %s", e)
        return False, "config_load_failed"
    try:
        from layla.memory.db import get_recent_learnings

        get_recent_learnings(n=1)
    except Exception as e:
        logger.debug("health db: %s", e)
        return False, "db_unavailable"
    return True, "ok"


@router.get("/debug/state")
def debug_execution_state(conversation_id: str = ""):
    """Last execution snapshot for a conversation (coordinator / agent loop)."""
    try:
        from shared_state import get_last_execution_snapshot

        cid = (conversation_id or "").strip() or "default"
        snap = get_last_execution_snapshot(cid)
        return {"ok": True, "conversation_id": cid, "snapshot": snap}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/debug/tasks")
def debug_tasks(conversation_id: str = "", limit: int = 40):
    """Recent persisted coordinator tasks."""
    try:
        from layla.memory.db import list_persistent_tasks

        rows = list_persistent_tasks(
            limit=limit,
            conversation_id=(conversation_id or "").strip() or None,
        )
        return {"ok": True, "tasks": rows}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "tasks": []}, status_code=500)


@router.get("/usage")
def usage():
    """Per-session token usage (prompt, completion, request count)."""
    try:
        from services.llm_gateway import get_token_usage

        return get_token_usage()
    except Exception as e:
        logger.debug("usage endpoint: %s", e)
        return {"error": str(e)}


@router.get("/history")
def session_prompt_history(limit: int = 50):
    """Recent user prompts stored from /agent (for UI recall)."""
    try:
        from layla.memory.db import get_recent_session_prompts

        return {"prompts": get_recent_session_prompts(limit=limit)}
    except Exception as e:
        return JSONResponse({"error": str(e), "prompts": []}, status_code=500)


@router.get("/skills")
def list_skills_api():
    """Markdown skills under workspace .layla/skills, skills/, .claude/skills."""
    try:
        import runtime_safety
        from services import skills as skills_mod

        cfg = runtime_safety.load_config()
        wr = (cfg.get("sandbox_root") or str(REPO_ROOT)).strip()
        loaded = skills_mod.load_skills(wr)
        return {
            "skills": [
                {"name": s.name, "triggers": s.triggers, "description": s.description, "path": s.path}
                for s in loaded
            ]
        }
    except Exception as e:
        return JSONResponse({"error": str(e), "skills": []}, status_code=500)


@router.get("/version")
def version():
    return {"ok": True, "version": __version__}


@router.get("/update/check")
def update_check():
    try:
        import runtime_safety
        from services.auto_updater import check_update
        from services.release_updater import is_installed_mode

        cfg = runtime_safety.load_config()
        out = check_update(__version__, str(cfg.get("github_repo") or ""))
        if isinstance(out, dict):
            out["update_channel"] = "release" if is_installed_mode() else "git"
        return out
    except Exception as e:
        return {"ok": False, "error": f"update_check_failed: {e}"}


@router.post("/update/apply")
def update_apply(req: dict | None = None):
    req = req or {}
    allow_run = req.get("allow_run") is True
    if not allow_run:
        return JSONResponse({"ok": False, "error": "allow_run_required"}, status_code=403)
    try:
        import runtime_safety
        from services.auto_updater import apply_update
        from services.release_updater import apply_release_update, is_installed_mode

        if not runtime_safety.is_tool_allowed("shell"):
            return JSONResponse({"ok": False, "error": "approval_required_for_shell"}, status_code=403)
        if is_installed_mode():
            return apply_release_update()
        return apply_update(REPO_ROOT)
    except Exception as e:
        return {"ok": False, "error": f"update_apply_failed: {e}"}


@router.post("/undo")
def undo():
    """Revert last Layla auto-commit (git revert HEAD --no-edit). Requires git_auto_commit."""
    try:
        from shared_state import get_last_layla_commit

        repo, _ = get_last_layla_commit()
        if not repo:
            return JSONResponse({"ok": False, "error": "No Layla commit to undo"})
        r = subprocess.run(
            ["git", "revert", "HEAD", "--no-edit"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return JSONResponse({"ok": False, "error": r.stderr or r.stdout or "git revert failed"})
        return {"ok": True, "message": "Reverted last Layla commit"}
    except Exception as e:
        logger.debug("undo failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/health")
def health(request: Request):
    ok, detail = _health_checks()
    try:
        from services.llm_gateway import _llm, model_loaded_status

        model_loaded = _llm is not None
        model_status = model_loaded_status()
    except Exception:
        model_loaded = False
        model_status = {}
    try:
        from layla.tools.registry import TOOLS

        tools_registered = len(TOOLS)
    except Exception:
        tools_registered = 0
    try:
        from layla.memory.db import count_learnings, get_active_study_plans

        learnings = count_learnings()
        study_plans = len(get_active_study_plans())
    except Exception:
        learnings = 0
        study_plans = 0
    cfg: dict = {}
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        vector_store = "enabled" if cfg.get("use_chroma") else "disabled"
    except Exception:
        vector_store = "unknown"
    db_ok = ok
    chroma_ok = False
    deep = ((request.query_params.get("deep") or "").strip().lower() == "true")
    uptime_seconds = time.time() - getattr(request.app.state, "start_time", time.time())
    payload = {
        "status": "ok" if ok else "degraded",
        "db_ok": db_ok,
        "chroma_ok": chroma_ok,
        "uptime_seconds": uptime_seconds,
        "model_loaded": model_loaded,
        "tools_registered": tools_registered,
        "learnings": learnings,
        "study_plans": study_plans,
        "vector_store": vector_store,
        "knowledge_index_ready": getattr(request.app.state, "knowledge_index_ready", None),
        "knowledge_index_status": getattr(request.app.state, "knowledge_index_status", None),
    }
    try:
        import urllib.error
        import urllib.request

        ollama_url = (cfg.get("ollama_base_url") or "").strip().rstrip("/")
        ollama_st = "not_configured"
        if ollama_url:
            try:
                urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=2)
                ollama_st = "ok"
            except (urllib.error.URLError, TimeoutError, OSError):
                ollama_st = "unreachable"
        payload["backends"] = {
            "llama_cpp": {"status": "ok" if model_loaded else "not_loaded"},
            "ollama": {"status": ollama_st, "url": ollama_url or None},
        }
    except Exception:
        pass
    _kie = getattr(request.app.state, "knowledge_index_error", None)
    if _kie:
        payload["knowledge_index_error"] = _kie
    if model_status:
        payload["model_error"] = model_status.get("error")
    try:
        mw = ""
        if isinstance(model_status, dict):
            mw = (model_status.get("error") or "").strip()
        remote_ok = bool(isinstance(model_status, dict) and model_status.get("remote"))
        http_backend = bool((cfg.get("llama_server_url") or "").strip() or (cfg.get("ollama_base_url") or "").strip())
        pending_bg = (REPO_ROOT / "agent" / ".layla_pending_model.json").is_file()
        payload["pending_background_model"] = pending_bg
        model_on_disk = False
        try:
            import runtime_safety as _rs

            model_on_disk = _rs.resolve_model_path(cfg).exists()
        except Exception:
            model_on_disk = False
        try:
            if model_on_disk:
                (REPO_ROOT / "agent" / ".layla_model_ready.flag").unlink(missing_ok=True)
        except Exception:
            pass
        if not mw and not model_loaded and not remote_ok and not http_backend:
            mw = "Model not loaded into inference engine."
        # Only soften warnings while a background download is in flight and the GGUF is not on disk yet.
        if mw and pending_bg and not model_on_disk:
            mw = ""
        if mw:
            payload["model_health_warning"] = mw
    except Exception:
        pass
    try:
        from services.system_optimizer import get_summary

        payload["system_optimizer"] = get_summary()
    except Exception:
        pass
    try:
        from services.resource_manager import classify_load

        payload["resource_load"] = classify_load()
    except Exception:
        pass
    try:
        from services.llm_gateway import get_token_usage

        payload["token_usage"] = get_token_usage()
    except Exception:
        pass
    try:
        from services.completion_cache import get_cache_stats

        payload["cache_stats"] = get_cache_stats()
    except Exception:
        pass
    try:
        from services.response_cache import get_response_cache_stats

        payload["response_cache_stats"] = get_response_cache_stats()
    except Exception:
        pass
    try:
        from services.health_snapshot import (
            build_dependency_status,
            build_effective_config_public,
            build_features_enabled,
        )
        from services.system_optimizer import get_effective_config

        _eff = get_effective_config(cfg)
        payload["effective_limits"] = {
            "max_tool_calls": _eff.get("max_tool_calls"),
            "max_runtime_seconds": _eff.get("max_runtime_seconds"),
            "research_max_tool_calls": _eff.get("research_max_tool_calls"),
            "research_max_runtime_seconds": _eff.get("research_max_runtime_seconds"),
            "completion_max_tokens": _eff.get("completion_max_tokens"),
            "tool_loop_detection_enabled": bool(_eff.get("tool_loop_detection_enabled")),
            "performance_mode": cfg.get("performance_mode"),
            "completion_cache_enabled": bool(_eff.get("completion_cache_enabled")),
            "response_cache_enabled": bool(_eff.get("response_cache_enabled")),
            "anti_drift_prompt_enabled": bool(_eff.get("anti_drift_prompt_enabled", True)),
            "max_active_runs": cfg.get("max_active_runs"),
            "max_cpu_percent": cfg.get("max_cpu_percent"),
            "max_ram_percent": cfg.get("max_ram_percent"),
            "warn_cpu_percent": cfg.get("warn_cpu_percent"),
            "hard_cpu_percent": cfg.get("hard_cpu_percent"),
            "chat_light_max_runtime_seconds": _eff.get("chat_light_max_runtime_seconds")
            if _eff.get("chat_light_max_runtime_seconds") is not None
            else cfg.get("chat_light_max_runtime_seconds"),
            "ui_agent_stream_timeout_seconds": cfg.get("ui_agent_stream_timeout_seconds"),
            "ui_agent_json_timeout_seconds": cfg.get("ui_agent_json_timeout_seconds"),
            "ui_stalled_silence_ms": cfg.get("ui_stalled_silence_ms"),
        }
        try:
            mf = (cfg.get("model_filename") or "")
            payload["active_model"] = Path(str(mf)).name if mf else ""
        except Exception:
            payload["active_model"] = ""
        payload["effective_config"] = build_effective_config_public(cfg, _eff)
        payload["features_enabled"] = build_features_enabled(cfg, _eff)
        deps = build_dependency_status(probe_chroma=deep)
        payload["dependencies"] = deps
        if deep and deps.get("chroma") != "missing":
            payload["chroma_ok"] = deps.get("chroma") == "ok"
    except Exception:
        pass
    try:
        from services.model_router import get_model_routing_summary

        payload["model_routing"] = get_model_routing_summary(cfg)
    except Exception:
        pass
    try:
        if not getattr(request.app.state, "subproc_gguf_operator_hint_shown", False):
            from services.inference_router import inference_backend_uses_local_gguf

            if bool(cfg.get("background_use_subprocess_workers")) and inference_backend_uses_local_gguf(cfg):
                request.app.state.subproc_gguf_operator_hint_shown = True
                payload.setdefault("operator_hints", []).append(
                    "background_use_subprocess_workers with local llama_cpp loads a GGUF per worker process; "
                    "set llama_server_url or ollama_base_url for centralized HTTP inference."
                )
    except Exception:
        pass
    if not ok:
        payload["detail"] = detail
        return JSONResponse(payload, status_code=503)
    return payload


@router.get("/health/context_budget")
def health_context_budget():
    """
    Per-section context token usage vs allocated budgets.

    Returns sections dict (used/budget/pct per key), warnings, dropped/truncated lists.
    Call after any /agent run to see how context was allocated last turn.
    """
    try:
        from services.context_budget import build_budget_telemetry
        from services.context_manager import get_last_prompt_metrics

        metrics, n_ctx = get_last_prompt_metrics()
        return {"ok": True, **build_budget_telemetry(n_ctx=n_ctx, last_metrics=metrics)}
    except Exception as e:
        logger.debug("context_budget endpoint: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/health/deps")
def health_deps(request: Request):
    """Lightweight dependency matrix; optional Chroma vector probe via ?deep=true."""
    deep = ((request.query_params.get("deep") or "").strip().lower() == "true")
    try:
        from services.health_snapshot import build_dependency_status

        return {"dependencies": build_dependency_status(probe_chroma=deep)}
    except Exception as e:
        return {"dependencies": {}, "error": str(e)}


@router.get("/local_access_info")
def local_access_info():
    """Return LAN URL for phone/remote access. Safe to call from the UI."""
    import socket

    import runtime_safety

    cfg = runtime_safety.load_config()
    port = int(cfg.get("port", 8000))
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            lan_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            lan_ip = "127.0.0.1"
    url = f"http://{lan_ip}:{port}"
    remote_enabled = bool(cfg.get("remote_enabled", False))
    api_key_set = bool(cfg.get("remote_api_key", "").strip())
    return {
        "ok": True,
        "url": url,
        "lan_ip": lan_ip,
        "port": port,
        "remote_enabled": remote_enabled,
        "api_key_required": api_key_set,
        "ui_url": url + "/ui",
    }


@router.get("/doctor")
def doctor():
    """Full system diagnostics. Same as `layla doctor`."""
    try:
        from services.system_doctor import run_diagnostics

        return run_diagnostics(include_llm=False)
    except Exception as e:
        return {"status": "error", "error": str(e), "checks": {}}


@router.get("/doctor/capabilities")
def doctor_capabilities(
    browser_launch: bool = False,
    voice_micro: bool = False,
):
    """
    Extended capability probe (optional subsystems). Cheap by default.
    Set browser_launch=true to verify Chromium can launch (Playwright).
    Set voice_micro=true to run tiny STT/TTS calls (may download models; slow).
    """
    try:
        from services.system_doctor import run_capability_probe, run_diagnostics

        base = run_diagnostics(include_llm=False)
        probe = run_capability_probe(
            browser_launch=bool(browser_launch),
            voice_micro=bool(voice_micro),
        )
        base["capability_probe"] = probe
        return base
    except Exception as e:
        return {"status": "error", "error": str(e), "checks": {}}


@router.get("/session/stats")
def session_stats():
    """Alias-style session metrics (token_usage includes tool_calls, elapsed, tok/s)."""
    try:
        from services.llm_gateway import get_token_usage

        return get_token_usage()
    except Exception as e:
        return {"error": str(e)}


@router.post("/remote/tunnel/start")
def remote_tunnel_start():
    """Start cloudflared quick tunnel (HTTPS URL) to this machine's Layla port."""
    try:
        import runtime_safety
        from services.tunnel_manager import start_quick_tunnel

        cfg = runtime_safety.load_config()
        port = int(cfg.get("port", 8000))
        local = f"http://127.0.0.1:{port}"
        cf = (cfg.get("cloudflared_path") or "").strip() or None
        return start_quick_tunnel(local_url=local, cloudflared=cf)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/remote/tunnel/status")
def remote_tunnel_status():
    from services.tunnel_manager import tunnel_status

    return tunnel_status()


@router.post("/remote/tunnel/stop")
def remote_tunnel_stop():
    from services.tunnel_manager import stop_tunnel

    return stop_tunnel()


@router.get("/skill_packs")
def skill_packs_list():
    from services.skill_packs import list_installed

    return {"packs": list_installed()}


@router.post("/skill_packs/install")
async def skill_packs_install(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    url = (body.get("url") or "").strip()
    name = (body.get("name") or "").strip() or None
    if not url:
        return JSONResponse({"ok": False, "error": "url required"}, status_code=400)
    from services.skill_packs import install_from_git

    return install_from_git(url, name=name)


@router.post("/skill_packs/remove")
async def skill_packs_remove(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    pid = (body.get("id") or "").strip()
    if not pid:
        return JSONResponse({"ok": False, "error": "id required"}, status_code=400)
    from services.skill_packs import remove_pack

    return remove_pack(pid)


@router.get("/rl/preferences")
def rl_preferences():
    """Return current RL tool preference table (PR #1 integration)."""
    try:
        from layla.memory.db import get_rl_preferences

        prefs = get_rl_preferences()
        return {"ok": True, "preferences": prefs}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@router.post("/memory/rebuild")
async def memory_rebuild():
    """Rebuild Chroma learnings collection from SQLite (async fire-and-forget)."""

    async def _do_rebuild():
        try:
            from layla.memory.vector_store import rebuild_collection

            rebuild_collection()
            logger.info("memory rebuild complete")
        except Exception as e:
            logger.warning("memory rebuild failed: %s", e)

    asyncio.create_task(_do_rebuild())
    return JSONResponse({"ok": True, "status": "rebuilding"})


@router.get("/aspects/reload")
def aspects_reload():
    """Hot-reload aspect JSON definitions."""
    try:
        import orchestrator as _orch

        aspects = _orch.reload_aspects()
        return JSONResponse({"ok": True, "loaded": len(aspects)})
    except Exception as e:
        logger.warning("aspects reload failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e), "loaded": 0})


@router.post("/agent/cancel/{conversation_id}")
def cancel_agent_run(conversation_id: str):
    """Signal cooperative cancellation for an in-flight agent run."""
    try:
        from shared_state import set_cancel

        cid = (conversation_id or "").strip() or "default"
        return {"ok": bool(set_cancel(cid))}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/agent/cot_stats")
def get_cot_stats():
    """Phase 4.1: Return dual-model CoT cost accumulator stats (per-phase token estimates)."""
    try:
        from services.model_router import get_cot_stats, split_cot_models
        stats = get_cot_stats()
        split = split_cot_models()
        return {
            "ok": True,
            "split_config": split,
            "accumulated": stats,
            "total_calls": sum(s.get("calls", 0) for s in stats),
            "total_estimated_tokens": sum(s.get("estimated_tokens", 0) for s in stats),
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.delete("/agent")
def cancel_latest_agent_run():
    """Cancel the most recently started conversation run (same as PR #1 DELETE /agent)."""
    try:
        from shared_state import get_most_recent_conv_id, set_cancel

        cid = get_most_recent_conv_id()
        if not cid:
            return {"ok": False, "error": "no active conversation"}
        return {"ok": bool(set_cancel(cid))}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
