import asyncio
import json
import logging
import os
import queue
import sys
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent_loop import _is_junk_reply, _quick_reply_for_trivial_turn, autonomous_run, stream_reason
from layla.time_utils import utcnow
from version import __version__

logger = logging.getLogger("layla")

# Anonymous access: we do not log client IP, auth headers, or other PII. No auth required for local use.
# Initialized to startup time so scheduled study can run from first boot, not just after first message
_last_activity_ts: float = time.time()


def touch_activity() -> None:
    """Call from /agent, /wakeup, /learn, /ui to mark recent activity for scheduler."""
    global _last_activity_ts
    _last_activity_ts = time.time()

# Process names (lowercase) that cause study job to skip so we don't override you
_SCHEDULER_SKIP_PROCESSES = frozenset({
    "overwatch", "valorant", "valorant", "steam", "fortniteclient", "riotclient",
    "league of legends", "dota 2", "elden ring", "eldenring", "hogwarts", "cyberpunk",
    "game", "games", "ea", "origin", "ubisoft", "battle.net", "epicgames",
})


def _game_or_fullscreen_running() -> bool:
    """True if a known game process is running so we skip scheduled study."""
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            try:
                name = (p.info.get("name") or "").lower()
                if any(skip in name for skip in _SCHEDULER_SKIP_PROCESSES):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def _scheduled_study_job() -> None:
    """Run one autonomous study plan only when you're there and not gaming.
    When scheduler_use_capabilities is true, picks plan by urgency + diversification and records capability growth."""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        if not cfg.get("scheduler_study_enabled", True):
            return
        try:
            # Default 1440 min (24 h) so study runs any time the server is up, not just during active use
            activity_min = max(1, int(float(cfg.get("scheduler_recent_activity_minutes", 1440))))
        except (TypeError, ValueError):
            activity_min = 1440
        if time.time() - _last_activity_ts > activity_min * 60:
            return
        if _game_or_fullscreen_running():
            return
        from layla.memory import capabilities as cap_mod
        from layla.memory.db import append_scheduler_history, get_active_study_plans
        plans = get_active_study_plans()
        if not plans:
            return
        use_capabilities = bool(cfg.get("scheduler_use_capabilities", False))
        plan, domain_id = cap_mod.get_next_plan_for_study(plans, use_capabilities=use_capabilities)
        if not plan:
            return
        from services.study_service import run_autonomous_study_for_plan
        summary = run_autonomous_study_for_plan(plan)
        if domain_id:
            try:
                usefulness = cap_mod.run_learning_validation(summary)
                cap_mod.record_practice(domain_id, mission_id=plan.get("id"), usefulness_score=usefulness)
                append_scheduler_history(domain_id, plan.get("id"))
            except Exception as e:
                logger.warning("capability record_practice failed: %s", e)
        logger.info("scheduled_study completed topic=%s domain_id=%s", plan.get("topic"), domain_id)
    except Exception as e:
        logger.exception("scheduled_study failed: %s", e)


def _mission_worker_job() -> None:
    """Background job: run next step of active missions. Persists progress for restart recovery."""
    try:
        from layla.memory.db import get_active_missions
        from services.mission_manager import execute_next_step
        missions = get_active_missions(limit=1)
        for m in missions:
            try:
                execute_next_step(m["id"])
                break
            except Exception as e:
                logger.warning("mission_worker step failed: %s", e)
    except Exception as e:
        logger.warning("mission_worker failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    _start_time = time.time()
    app.state.start_time = _start_time
    app.state.knowledge_index_ready = None
    app.state.knowledge_index_status = "unknown"
    app.state.knowledge_index_error = None
    try:
        from services.observability import log_agent_started
        log_agent_started()
    except Exception:
        pass
    import logging as _logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(_logging, log_level, _logging.INFO)
    if os.getenv("LAYLA_LOG_JSON") == "1":
        import logging.handlers
        class JsonFormatter(_logging.Formatter):
            def format(self, record):
                return json.dumps({
                    "time": self.formatTime(record),
                    "level": record.levelname,
                    "name": record.name,
                    "message": record.getMessage(),
                })
        h = _logging.StreamHandler()
        h.setFormatter(JsonFormatter())
        _logging.getLogger().handlers = [h]
        _logging.getLogger().setLevel(log_level)
    else:
        _logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        if cfg.get("hardware_aware_startup", True):
            try:
                from services.hardware_detect import detect_hardware
                from services.model_recommender import recommend_from_hardware
                h = detect_hardware()
                rec = recommend_from_hardware()
                logger.info(
                    "Hardware: %s RAM %.0fGB VRAM %.0fGB tier=%s | Recommended: %s",
                    h.get("acceleration_backend", "none"),
                    h.get("ram_gb", 0),
                    h.get("vram_gb", 0),
                    h.get("machine_tier", ""),
                    rec.get("model_tier", ""),
                )
            except Exception as e:
                logger.debug("hardware startup log skipped: %s", e)
        if cfg.get("use_chroma"):
            try:
                from layla.memory.vector_store import index_knowledge_docs
                knowledge_dir = REPO_ROOT / "knowledge"
                if knowledge_dir.exists():
                    index_knowledge_docs(knowledge_dir)
                    logger.info("knowledge docs indexed for Chroma")
            except Exception as e:
                logger.warning("knowledge index failed: %s", e)
        # Run DB migration once at startup (not on every DB call)
        try:
            from layla.memory.db import migrate
            migrate()
            logger.info("DB migration complete")
        except Exception as e:
            logger.warning("DB migration failed: %s", e)
        try:
            from layla.tools.registry import validate_tools_registry
            validate_tools_registry()
            logger.info("Tools registry validated")
        except Exception as e:
            logger.warning("Tools registry validation failed: %s", e)
        try:
            from services.plugin_loader import load_plugins
            plug_result = load_plugins(cfg)
            if plug_result["skills_added"] or plug_result["tools_added"] or plug_result.get("capabilities_added"):
                logger.info(
                    "Plugins loaded: %d skills, %d tools, %d capabilities",
                    plug_result["skills_added"],
                    plug_result["tools_added"],
                    plug_result.get("capabilities_added", 0),
                )
            for err in plug_result.get("errors", [])[:5]:
                logger.warning("Plugin error: %s", err)
        except Exception as e:
            logger.warning("Plugin load failed: %s", e)
        # Pre-warm LLM in background thread â€” first request will be instant
        try:
            from services.llm_gateway import prewarm_llm
            prewarm_llm()
            logger.info("LLM pre-warm thread started")
        except Exception as e:
            logger.warning("LLM pre-warm thread failed: %s", e)
        if cfg.get("benchmark_on_load"):
            def _startup_capability_benchmarks() -> None:
                try:
                    from services.benchmark_suite import run_benchmark
                    run_benchmark("embedding", "sentence_transformers", "sentence-transformers")
                    run_benchmark("vector_search", "chromadb", "chromadb")
                except Exception as e:
                    logger.debug("startup capability benchmarks skipped: %s", e)

            threading.Thread(
                target=_startup_capability_benchmarks,
                daemon=True,
                name="capability-benchmark-startup",
            ).start()
            logger.info("Capability benchmark startup thread started (benchmark_on_load)")
        # Preload embedder so first /agent request does not block on model load
        # Optional and disabled by default for stability on some Python/torchao combos.
        if cfg.get("embedder_prewarm_enabled", False):
            try:
                import threading as _t

                from layla.memory.vector_store import embed
                _t.Thread(target=lambda: embed("warmup"), daemon=True, name="embed-prewarm").start()
                logger.info("embedder pre-warm thread started")
            except Exception as e:
                logger.warning("embedder preload failed: %s", e)
        # Prewarm voice models (optional; default off to avoid startup spikes)
        if cfg.get("voice_stt_prewarm_enabled", False):
            try:
                from services.stt import prewarm as stt_prewarm
                stt_prewarm()
            except Exception:
                pass
        if cfg.get("voice_tts_prewarm_enabled", False):
            try:
                from services.tts import prewarm as tts_prewarm
                tts_prewarm()
            except Exception:
                pass
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        sched = BackgroundScheduler(timezone="UTC")
        # Mission worker: always run (v1.1 long-running tasks)
        try:
            mission_interval_min = max(1, min(10, int(float(cfg.get("mission_worker_interval_minutes", 2)))))
            sched.add_job(_mission_worker_job, IntervalTrigger(minutes=mission_interval_min), id="mission_worker")
            logger.info("mission_worker scheduled every %s min", mission_interval_min)
        except (TypeError, ValueError):
            sched.add_job(_mission_worker_job, IntervalTrigger(minutes=2), id="mission_worker")
        if cfg.get("scheduler_study_enabled", True):
            try:
                interval_min = max(5, min(120, int(float(cfg.get("scheduler_interval_minutes", 30)))))
            except (TypeError, ValueError):
                interval_min = 30
            sched.add_job(_scheduled_study_job, IntervalTrigger(minutes=interval_min))
            # Knowledge distillation + experience replay (intelligence systems)
            try:
                def _intelligence_job():
                    try:
                        from services.knowledge_distiller import run_periodic_distillation
                        run_periodic_distillation()
                    except Exception as _e:
                        logger.warning("intelligence_job: knowledge_distiller failed: %s", _e)
                    try:
                        from services.experience_replay import run_experience_replay
                        replay_summary = run_experience_replay()
                        if replay_summary:
                            logger.info("experience_replay summary: %s", replay_summary)
                    except Exception as _e:
                        logger.warning("intelligence_job: experience_replay failed: %s", _e)
                    try:
                        from services.curiosity_engine import get_curiosity_suggestions
                        from layla.memory.db import save_learning
                        suggestions = get_curiosity_suggestions()
                        for suggestion in suggestions[:3]:
                            if suggestion and len(suggestion.strip()) > 10:
                                save_learning(
                                    content=f"Curiosity: {suggestion.strip()}",
                                    kind="curiosity",
                                    source="curiosity_engine",
                                )
                    except Exception as _e:
                        logger.warning("intelligence_job: curiosity_engine failed: %s", _e)
                sched.add_job(_intelligence_job, IntervalTrigger(minutes=60), id="intelligence")
            except Exception:
                pass
            if cfg.get("enable_lens_refresh") and cfg.get("lens_refresh_interval_days"):
                try:
                    days = max(1, min(365, int(cfg["lens_refresh_interval_days"])))
                    from lens_refresh import rebuild_lens_knowledge
                    sched.add_job(rebuild_lens_knowledge, IntervalTrigger(days=days))
                    logger.info("lens refresh scheduled every %s days", days)
                except (TypeError, ValueError) as e:
                    logger.warning("lens refresh not scheduled: %s", e)
            logger.info("scheduler started (study every %s min when active)", interval_min)
        sched.start()
        app.state.scheduler = sched
    except Exception as e:
        logger.warning("scheduler not started: %s", e)
    yield
    # Shutdown
    try:
        from services.observability import log_agent_shutdown
        duration_ms = (time.time() - _start_time) * 1000
        log_agent_shutdown(duration_ms=duration_ms)
    except Exception:
        pass
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown(wait=False)


app = FastAPI(
    lifespan=lifespan,
    title="Layla",
    description="Local-first AI companion and engineering agent",
    version=__version__,
)
app.add_middleware(GZipMiddleware, minimum_size=500)  # compress responses > 500 bytes

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = Path(__file__).resolve().parent
DOCS_DIR = REPO_ROOT / "docs"
HISTORY_FILE = REPO_ROOT / "conversation_history.json"
GOV_PATH = AGENT_DIR / ".governance"
PENDING_FILE = GOV_PATH / "pending.json"
AUDIT_LOG = GOV_PATH / "audit.log"

# In-memory conversation history (max 20 turns); also persisted to disk
_history: deque = deque(maxlen=20)
_plugins_cache: dict = {}
_plugins_cache_ts: float = 0.0
_PLUGINS_CACHE_TTL: float = 60.0


def _load_history() -> None:
    try:
        if not HISTORY_FILE.exists():
            return
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return
        # If any assistant message is junk or echoed instructions, clear history to avoid poisoning the prompt
        def _assistant_poison(item: dict) -> bool:
            if item.get("role") != "assistant":
                return False
            c = (item.get("content") or "").strip()
            if _is_junk_reply(c):
                return True
            c_lower = c.lower()
            if "you are layla" in c_lower and ("use the identity" in c_lower or "rules below" in c_lower):
                return True
            if c.startswith("[") and "you are" in c_lower:
                return True
            return False

        for item in data[-20:]:
            if _assistant_poison(item):
                _history.clear()
                HISTORY_FILE.write_text("[]", encoding="utf-8")
                return
        for item in data[-20:]:
            _history.append(item)
    except Exception as e:
        logger.debug("_load_history failed: %s", e)


def _save_history() -> None:
    try:
        HISTORY_FILE.write_text(json.dumps(list(_history), indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("_save_history failed: %s", e)


def _append_history(role: str, content: str) -> None:
    _history.append({"role": role, "content": content})
    _save_history()


def _sync_compact_history() -> dict:
    """Summarize in-memory chat history when over context threshold; persists via _save_history."""
    import runtime_safety
    from services.context_manager import summarize_history

    cfg = runtime_safety.load_config()
    n_ctx = int(cfg.get("n_ctx", 4096))
    ratio = float(cfg.get("context_auto_compact_ratio", 0.75))
    dict_msgs = [{"role": m.get("role"), "content": m.get("content", "")} for m in _history if isinstance(m, dict)]
    if not dict_msgs:
        return {"ok": True, "summary": "", "messages_remaining": 0}
    new_msgs = summarize_history(dict_msgs, n_ctx=n_ctx, threshold_ratio=ratio)
    summary = ""
    if new_msgs and str(new_msgs[0].get("role", "")).lower() == "system":
        summary = str(new_msgs[0].get("content", ""))
    _history.clear()
    for m in new_msgs:
        _history.append(m)
    _save_history()
    return {"ok": True, "summary": summary[:12000], "messages_remaining": len(_history)}


def _get_cached_plugins(cfg: dict) -> dict:
    """Avoid rescanning plugins on every UI refresh."""
    global _plugins_cache, _plugins_cache_ts
    now = time.time()
    if _plugins_cache and (now - _plugins_cache_ts) < _PLUGINS_CACHE_TTL:
        return _plugins_cache
    from services.plugin_loader import load_plugins

    _plugins_cache = load_plugins(cfg)
    _plugins_cache_ts = now
    return _plugins_cache


def _read_pending() -> list:
    try:
        if PENDING_FILE.exists():
            data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug("_read_pending failed: %s", e)
    return []


def _write_pending_list(data: list) -> None:
    GOV_PATH.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _audit(tool: str, args_summary: str, approved_by: str, result_ok: bool) -> None:
    GOV_PATH.mkdir(parents=True, exist_ok=True)
    line = f"{utcnow().isoformat()} | {tool} | {args_summary[:80]} | {approved_by} | {'ok' if result_ok else 'fail'}\n"
    try:
        with open(str(AUDIT_LOG), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.debug("_audit write failed: %s", e)


def _read_study_plans() -> list:
    try:
        from layla.memory.db import get_active_study_plans
        return get_active_study_plans()
    except Exception as e:
        logger.debug("_read_study_plans failed: %s", e)
        return []


def _read_wakeup_log() -> dict:
    try:
        from layla.memory.db import get_last_wakeup
        row = get_last_wakeup()
        return row or {}
    except Exception as e:
        logger.debug("_read_wakeup_log failed: %s", e)
        return {}


# Load history at startup
_load_history()

from routers import agent as agent_router  # noqa: E402
from routers import agents as agents_router  # noqa: E402
from routers import approvals, study  # noqa: E402
from routers import memory as memory_router  # noqa: E402
from routers import research as research_router  # noqa: E402
from services import study_service  # noqa: E402
from shared_state import set_refs  # noqa: E402

set_refs(
    _history,
    touch_activity,
    _read_pending,
    _write_pending_list,
    _audit,
    _append_history,
    run_autonomous_study=study_service.run_autonomous_study_for_plan,
)
app.include_router(study.router)
app.include_router(approvals.router)
app.include_router(agent_router.router)
app.include_router(agents_router.router)
app.include_router(research_router.router)
app.include_router(memory_router.router)
from routers import projects as projects_router
from routers import plan_file as plan_file_router
from routers import plans as plans_router

app.include_router(projects_router.router)
app.include_router(plans_router.router)
app.include_router(plan_file_router.router)

if DOCS_DIR.exists():
    app.mount("/docs", StaticFiles(directory=str(DOCS_DIR)), name="docs")


@app.get("/values.md", include_in_schema=False)
def serve_values_md():
    """Serve repo-root VALUES.md for Web UI / onboarding links (local-first framing)."""
    p = REPO_ROOT / "VALUES.md"
    if not p.is_file():
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    return FileResponse(str(p), media_type="text/markdown; charset=utf-8")


_UI_DIR = (AGENT_DIR / "ui").resolve()
if _UI_DIR.is_dir():
    app.mount("/layla-ui", StaticFiles(directory=str(_UI_DIR)), name="layla_ui_assets")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Â§16 Remote: auth and endpoint allowlist (production-safe, minimal)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _remote_allowed_paths(cfg: dict) -> list[str]:
    """Derive allowlist from remote_mode if remote_allow_endpoints not set."""
    explicit = cfg.get("remote_allow_endpoints") or []
    if isinstance(explicit, list) and len(explicit) > 0:
        return [str(p).strip() for p in explicit if p]
    mode = (cfg.get("remote_mode") or "observe").strip().lower()
    if mode == "interactive":
        return [
            "/wakeup",
            "/project_discovery",
            "/health",
            "/agent",
            "/v1/chat/completions",
            "/learn/",
            "/conversations",
            "/local_access_info",
            "/ui",
            "/projects",
            "/session/export",
            "/values.md",
        ]
    return ["/wakeup", "/project_discovery", "/health"]


def _is_localhost(host: str | None) -> bool:
    if not host:
        return True
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1", "testclient")


@app.middleware("http")
async def remote_auth_middleware(request: Request, call_next):
    """When remote_enabled: require Bearer token for non-localhost; enforce endpoint allowlist."""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        if not cfg.get("remote_enabled"):
            return await call_next(request)
    except Exception:
        return await call_next(request)

    client_host = request.client.host if request.client else None
    if _is_localhost(client_host):
        return await call_next(request)

    # Non-localhost: require API key
    api_key = cfg.get("remote_api_key")
    if not api_key or not str(api_key).strip():
        return JSONResponse(
            {"ok": False, "error": "remote_access_requires_api_key", "detail": "Set remote_api_key in config."},
            status_code=403,
        )
    auth = request.headers.get("Authorization") or ""
    expected = f"Bearer {api_key.strip()}"
    if auth.strip() != expected:
        return JSONResponse(
            {"ok": False, "error": "unauthorized", "detail": "Invalid or missing Authorization header."},
            status_code=401,
        )

    # Endpoint allowlist
    allowed = _remote_allowed_paths(cfg)
    path = (request.url.path or "").strip()
    ok = any(path == p or path.startswith(p.rstrip("/") + "/") or path == p.rstrip("/") for p in allowed)
    if not ok:
        return JSONResponse(
            {"ok": False, "error": "forbidden", "detail": "Endpoint not allowed for remote mode."},
            status_code=403,
        )

    return await call_next(request)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """Optional: add X-Trace-Id to responses for debugging. Propagate from request or generate new."""
    response = await call_next(request)
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        if not cfg.get("trace_id_enabled"):
            return response
    except Exception:
        return response
    trace_id = (request.headers.get("X-Trace-Id") or "").strip() or str(uuid.uuid4())
    if getattr(response, "headers", None) is not None:
        response.headers["X-Trace-Id"] = trace_id
    return response


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Health
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


@app.get("/usage")
def usage():
    """Per-session token usage (prompt, completion, request count)."""
    try:
        from services.llm_gateway import get_token_usage
        return get_token_usage()
    except Exception as e:
        logger.debug("usage endpoint: %s", e)
        return {"error": str(e)}


@app.post("/compact")
async def compact_conversation():
    """Compact server in-memory conversation history (same deque as /agent append)."""
    return await asyncio.to_thread(_sync_compact_history)


@app.get("/ctx_viz")
def ctx_viz():
    """Rough token breakdown for debugging context (conversation slice of server history)."""
    import runtime_safety
    from services.context_budget import get_budgets
    from services.context_manager import token_estimate_messages

    cfg = runtime_safety.load_config()
    n_ctx = int(cfg.get("n_ctx", 4096))
    budgets = get_budgets(n_ctx, cfg)
    dict_msgs = [{"role": m.get("role"), "content": m.get("content", "")} for m in _history if isinstance(m, dict)]
    conv = token_estimate_messages(dict_msgs)
    return {"n_ctx": n_ctx, "budgets": budgets, "sections": {"conversation_history": conv}}


@app.get("/session/stats")
def session_stats():
    """Alias-style session metrics (token_usage includes tool_calls, elapsed, tok/s)."""
    try:
        from services.llm_gateway import get_token_usage
        return get_token_usage()
    except Exception as e:
        return {"error": str(e)}


@app.get("/session/export")
def session_export(conversation_id: str | None = None):
    """Operator-owned JSON checkpoint: DB messages for a thread, pending approvals, server history tail."""
    from datetime import datetime, timezone

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
        out["server_history_tail"] = list(_history)[-50:]
    except Exception:
        out["server_history_tail"] = []
    try:
        out["pending_approvals"] = [p for p in _read_pending() if p.get("status") == "pending"]
    except Exception as e:
        out["pending_approvals"] = []
        out["pending_error"] = str(e)
    return JSONResponse(out)


@app.get("/history")
def session_prompt_history(limit: int = 50):
    """Recent user prompts stored from /agent (for UI recall)."""
    try:
        from layla.memory.db import get_recent_session_prompts
        return {"prompts": get_recent_session_prompts(limit=limit)}
    except Exception as e:
        return JSONResponse({"error": str(e), "prompts": []}, status_code=500)


@app.get("/skills")
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


@app.get("/version")
def version():
    return {"ok": True, "version": __version__}


@app.get("/update/check")
def update_check():
    try:
        import runtime_safety
        from services.auto_updater import check_update

        cfg = runtime_safety.load_config()
        return check_update(__version__, str(cfg.get("github_repo") or ""))
    except Exception as e:
        return {"ok": False, "error": f"update_check_failed: {e}"}


@app.post("/update/apply")
def update_apply(req: dict | None = None):
    req = req or {}
    allow_run = req.get("allow_run") is True
    if not allow_run:
        return JSONResponse({"ok": False, "error": "allow_run_required"}, status_code=403)
    try:
        import runtime_safety
        from services.auto_updater import apply_update

        # Align with existing dangerous-tool approval config.
        if not runtime_safety.require_approval("shell"):
            return JSONResponse({"ok": False, "error": "approval_required_for_shell"}, status_code=403)
        return apply_update(REPO_ROOT)
    except Exception as e:
        return {"ok": False, "error": f"update_apply_failed: {e}"}


@app.post("/undo")
def undo():
    """Revert last Layla auto-commit (git revert HEAD --no-edit). Requires git_auto_commit.
    Note: Request body (e.g. id) is ignored; this endpoint only performs git revert."""
    try:
        from shared_state import get_last_layla_commit
        repo, _ = get_last_layla_commit()
        if not repo:
            return JSONResponse({"ok": False, "error": "No Layla commit to undo"})
        import subprocess
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


@app.get("/health")
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

        payload["model_routing"] = get_model_routing_summary()
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Setup status + settings (for first-run overlay and settings panel)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/health/deps")
def health_deps(request: Request):
    """Lightweight dependency matrix; optional Chroma vector probe via ?deep=true."""
    deep = ((request.query_params.get("deep") or "").strip().lower() == "true")
    try:
        from services.health_snapshot import build_dependency_status

        return {"dependencies": build_dependency_status(probe_chroma=deep)}
    except Exception as e:
        return {"dependencies": {}, "error": str(e)}


@app.get("/local_access_info")
def local_access_info():
    """Return LAN URL for phone/remote access. Safe to call from the UI."""
    import socket
    cfg = runtime_safety.load_config()
    port = int(cfg.get("port", 8000))
    try:
        # Get the LAN-facing IP (not 127.0.0.1)
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


@app.get("/doctor")
def doctor():
    """Full system diagnostics. Same as `layla doctor`."""
    try:
        from services.system_doctor import run_diagnostics
        return run_diagnostics(include_llm=False)
    except Exception as e:
        return {"status": "error", "error": str(e), "checks": {}}


# ─── Platform Control Center API ────────────────────────────────────────────

@app.get("/platform/models")
def platform_models():
    """List models, active model, catalog (jinx/dolphin/hermes/qwen), and benchmarks for UI control center."""
    try:
        import runtime_safety
        from services.model_manager import list_models
        cfg = runtime_safety.load_config()
        models = list_models()
        active = cfg.get("model_filename", "")
        catalog = []
        try:
            cat_path = Path(__file__).resolve().parent / "models" / "model_catalog.json"
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


@app.get("/platform/plugins")
def platform_plugins():
    """List loaded plugins, skills, capabilities for UI."""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        pl = _get_cached_plugins(cfg)
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


@app.get("/platform/knowledge")
def platform_knowledge():
    """Conversation summaries, learnings preview, knowledge graph nodes, timeline, user identity for UI."""
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


@app.get("/platform/projects")
def platform_projects():
    """Project context for UI: goals, progress, blockers, last_discussed."""
    try:
        from layla.memory.db import get_project_context
        return get_project_context()
    except Exception as e:
        return {"project_name": "", "goals": "", "progress": "", "blockers": "", "last_discussed": "", "error": str(e)}


@app.get("/setup_status")
def setup_status():
    """Returns readiness state for the UI first-run overlay."""
    import runtime_safety as _rs
    config_exists = _rs.CONFIG_FILE.exists()
    cfg = {}
    try:
        cfg = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8")) if config_exists else {}
    except Exception:
        pass
    model_filename = cfg.get("model_filename", "")
    placeholder = not model_filename or model_filename == "your-model.gguf"
    models_dir_raw = cfg.get("models_dir")
    models_dir = Path(models_dir_raw).expanduser().resolve() if models_dir_raw else REPO_ROOT / "models"
    model_path = _rs.resolve_model_path(cfg)
    model_found = not placeholder and model_path.exists()
    # Find any .gguf in models/
    available_models = [p.name for p in sorted(models_dir.glob("*.gguf"))] if models_dir.exists() else []
    # Hardware probe
    hw = {}
    try:
        from first_run import detect_gpu, detect_ram_gb, recommend_model
        ram = detect_ram_gb()
        vendor, vram = detect_gpu()
        rec = recommend_model(ram, vram, vendor)
        hw = {"ram_gb": ram, "gpu_vendor": vendor, "vram_gb": vram,
              "tier": rec["model_tier"], "suggestion": rec["suggestion"]}
    except Exception:
        pass
    performance_mode = str(cfg.get("performance_mode", "auto") or "auto").strip()
    model_valid = bool(not placeholder and model_path.exists())
    resolved_model = (
        model_path.name
        if model_found
        else (available_models[0] if available_models else "")
    )

    def _cfg_basename(key: str) -> str:
        raw = (cfg.get(key) or "").strip()
        if not raw:
            return ""
        try:
            return Path(raw).name
        except Exception:
            return raw.split("/")[-1].split("\\")[-1]

    model_route_hint = ""
    if resolved_model:
        coding_n = _cfg_basename("coding_model")
        chat_n = _cfg_basename("chat_model")
        reason_n = _cfg_basename("reasoning_model")
        mb = cfg.get("models")
        if isinstance(mb, dict):
            if not coding_n:
                coding_n = _cfg_basename(str(mb.get("code") or ""))
            if not chat_n:
                chat_n = _cfg_basename(str(mb.get("fast") or ""))
        if coding_n and coding_n == resolved_model:
            model_route_hint = "code"
        elif chat_n and chat_n == resolved_model:
            model_route_hint = "chat"
        elif reason_n and reason_n == resolved_model:
            model_route_hint = "reasoning"

    out = {
        "ready": model_found,
        "model_valid": model_valid,
        "config_exists": config_exists,
        "model_filename": model_filename if not placeholder else "",
        "model_found": model_found,
        "resolved_model": resolved_model,
        "model_route_hint": model_route_hint,
        "available_models": available_models,
        "hardware": hw,
        "performance_mode": performance_mode,
    }
    if not model_valid:
        try:
            from services.dependency_recovery import missing_gguf_recovery

            out["recovery"] = missing_gguf_recovery(
                model_filename if not placeholder else "",
                models_dir,
                resolved_path=model_path if model_path.exists() else None,
            )
        except Exception:
            out["recovery"] = {"what_failed": "Model file missing; see MODELS.md in repo root"}
    return out


@app.get("/setup/models")
def setup_models():
    """Return the model catalog for the first-run picker."""
    try:
        from first_run import _MODELS_CATALOG, detect_gpu, detect_ram_gb, recommend_model
        ram = detect_ram_gb()
        vendor, vram = detect_gpu()
        rec = recommend_model(ram or 0, vram or 0, vendor or "none")
        tier = rec.get("model_tier") or "medium"
        tier_keys = {
            "tiny": ("phi3-mini",),
            "small": ("dolphin-mistral-7b",),
            "medium": ("dolphin-llama3-8b", "hermes-3-8b", "dolphin-mistral-7b"),
            "medium-large": ("dolphin-llama3-8b", "hermes-3-8b"),
            "large": ("dolphin-llama3-70b",),
        }
        preferred = list(tier_keys.get(tier, ("dolphin-mistral-7b",)))
        catalog = []
        recommended_key = None
        rec_matched = False
        for m in _MODELS_CATALOG:
            viable = m.get("ram_gb", 99) <= (ram or 99)
            is_rec = bool(
                viable
                and (m.get("key") in preferred)
                and not rec_matched
            )
            if is_rec:
                rec_matched = True
                recommended_key = m.get("key")
            catalog.append({**m, "viable": viable, "recommended": is_rec})
        if not recommended_key:
            for m in catalog:
                if m.get("viable"):
                    recommended_key = m.get("key")
                    m["recommended"] = True
                    break
        return {
            "ok": True,
            "catalog": catalog,
            "ram_gb": ram,
            "recommended_key": recommended_key,
            "recommended_tier": tier,
            "suggestion": rec.get("suggestion") or "",
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "catalog": []}


@app.get("/setup/download")
async def setup_download(url: str, filename: str = ""):
    """Stream model download progress as SSE events. url: HuggingFace direct .gguf URL."""
    import urllib.request

    import runtime_safety as _rs
    cfg = _rs.load_config()
    models_dir_raw = cfg.get("models_dir")
    models_dir = Path(models_dir_raw).expanduser().resolve() if models_dir_raw else REPO_ROOT / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    fname = filename or url.rstrip("/").split("/")[-1]
    if not fname.endswith(".gguf"):
        fname += ".gguf"
    dest = models_dir / fname

    async def _stream():
        try:
            # Start download in thread
            done_event = threading.Event()
            progress_queue: queue.Queue = queue.Queue()
            error_holder = [None]

            def _do_download():
                try:
                    def _cb(block_num, block_size, total):
                        dl = block_num * block_size
                        pct = min(100, int(dl * 100 / total)) if total > 0 else 0
                        dl_mb = dl / (1024 * 1024)
                        tot_mb = total / (1024 * 1024) if total > 0 else 0
                        progress_queue.put({"pct": pct, "dl_mb": round(dl_mb, 1), "tot_mb": round(tot_mb, 1)})
                    urllib.request.urlretrieve(url, str(dest), _cb)
                except Exception as exc:
                    error_holder[0] = str(exc)
                finally:
                    done_event.set()

            t = threading.Thread(target=_do_download, daemon=True)
            t.start()

            last_pct = -1
            while not done_event.is_set() or not progress_queue.empty():
                try:
                    prog = progress_queue.get(timeout=0.3)
                    if prog["pct"] != last_pct:
                        last_pct = prog["pct"]
                        yield f"data: {json.dumps(prog)}\n\n"
                except queue.Empty:
                    if done_event.is_set():
                        break
                    yield f"data: {json.dumps({'pct': last_pct, 'status': 'downloading'})}\n\n"
                await asyncio.sleep(0)

            if error_holder[0]:
                yield f"data: {json.dumps({'error': error_holder[0]})}\n\n"
            else:
                # Save config with this model
                try:
                    import runtime_safety as _rs
                    cfg = {}
                    if _rs.CONFIG_FILE.exists():
                        try:
                            cfg = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    if not cfg:
                        from first_run import DEFAULTS, detect_gpu, detect_ram_gb, recommend_model
                        ram = detect_ram_gb()
                        vendor, vram = detect_gpu()
                        rec = recommend_model(ram, vram, vendor)
                        cfg = {**DEFAULTS, **rec["config"]}
                    cfg["model_filename"] = fname
                    cfg["models_dir"] = str(models_dir)
                    _rs.CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
                except Exception as cfg_err:
                    logger.warning("setup_download: config save failed: %s", cfg_err)
                yield f"data: {json.dumps({'pct': 100, 'done': True, 'filename': fname})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/settings")
def get_settings():
    """Return all editable settings. Missing keys use schema defaults."""
    import runtime_safety as _rs
    from config_schema import EDITABLE_SCHEMA
    full_cfg = _rs.load_config()
    out = {}
    for e in EDITABLE_SCHEMA:
        k = e["key"]
        if k in full_cfg:
            out[k] = full_cfg[k]
        elif "default" in e:
            out[k] = e["default"]
        else:
            out[k] = None
    return out


@app.get("/settings/schema")
def get_settings_schema():
    """Return config schema for UI. Advanced users: edit agent/runtime_config.json directly."""
    from config_schema import get_schema_for_api
    return get_schema_for_api()


def _coerce_setting_value(key: str, v: Any, schema: list[dict]) -> Any:
    """Coerce value to schema type (number, boolean) when needed."""
    for e in schema:
        if e.get("key") == key:
            t = e.get("type")
            if t == "number" and v is not None:
                try:
                    return float(v) if isinstance(v, str) and "." in str(v) else int(v)
                except (ValueError, TypeError):
                    return v
            if t == "boolean":
                if isinstance(v, bool):
                    return v
                return str(v).lower() in ("true", "1", "yes", "on")
            break
    return v


def _sync_save_settings(body: dict) -> dict:
    """Blocking: merge editable keys into runtime_config.json and invalidate config cache."""
    import runtime_safety as _rs
    from config_schema import EDITABLE_SCHEMA, get_editable_keys
    editable = get_editable_keys()
    cfg = {}
    if _rs.CONFIG_FILE.exists():
        try:
            cfg = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    saved = []
    for k, v in body.items():
        if k in editable:
            coerced = _coerce_setting_value(k, v, EDITABLE_SCHEMA)
            cfg[k] = coerced
            saved.append(k)
    _rs.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _rs.CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _rs.invalidate_config_cache()
    return {"ok": True, "saved": saved}


def _sync_apply_runtime_preset(name: str) -> dict:
    """Blocking: merge named preset into runtime_config.json."""
    import runtime_safety as _rs
    from config_schema import EDITABLE_SCHEMA, SETTINGS_PRESETS, apply_settings_preset
    if name.lower() not in SETTINGS_PRESETS:
        raise ValueError("unknown_preset")
    cfg: dict = {}
    if _rs.CONFIG_FILE.exists():
        try:
            cfg = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    merged, applied = apply_settings_preset(cfg, name)
    if merged is None:
        raise ValueError("unknown_preset")
    for k in applied:
        merged[k] = _coerce_setting_value(k, merged[k], EDITABLE_SCHEMA)
    _rs.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _rs.CONFIG_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    _rs.invalidate_config_cache()
    return {"ok": True, "preset": name.lower(), "applied": applied}


def _sync_set_project_context(body: dict) -> dict:
    from layla.memory.db import PROJECT_LIFECYCLE_STAGES, set_project_context
    set_project_context(
        project_name=body.get("project_name", ""),
        domains=body.get("domains"),
        key_files=body.get("key_files"),
        goals=body.get("goals", ""),
        lifecycle_stage=body.get("lifecycle_stage", ""),
        progress=body.get("progress", ""),
        blockers=body.get("blockers", ""),
        last_discussed=body.get("last_discussed", ""),
    )
    return {"ok": True, "lifecycle_stages": list(PROJECT_LIFECYCLE_STAGES)}


def _sync_ingest_docs(source: str, label: str) -> dict:
    from services.doc_ingestion import ingest_docs
    return ingest_docs(source, label)


def _sync_create_and_run_mission(body: dict) -> dict:
    from services.mission_manager import create_mission, run_mission
    goal = (body.get("goal") or "").strip()
    if not goal:
        raise ValueError("goal required")
    mission = create_mission(
        goal=goal,
        workspace_root=(body.get("workspace_root") or "").strip(),
        allow_write=bool(body.get("allow_write")),
        allow_run=bool(body.get("allow_run")),
    )
    if not mission:
        raise ValueError("mission creation failed (plan empty or planner error)")
    run_mission(mission["id"])
    return {"ok": True, "mission": mission}


@app.post("/settings")
async def save_settings(req: Request):
    """Update runtime_config.json. Merges with existing config. Only editable keys accepted."""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    try:
        return await asyncio.to_thread(_sync_save_settings, body)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/settings/preset")
async def apply_runtime_preset(req: Request):
    """Merge a named preset (e.g. potato) into runtime_config.json. Only schema-editable keys are written."""
    from config_schema import EDITABLE_SCHEMA, SETTINGS_PRESETS, apply_settings_preset
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    name = (body.get("preset") or body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "preset required"}, status_code=400)
    if name.lower() not in SETTINGS_PRESETS:
        return JSONResponse(
            {"ok": False, "error": "unknown_preset", "known": list(SETTINGS_PRESETS.keys())},
            status_code=400,
        )
    try:
        return await asyncio.to_thread(_sync_apply_runtime_preset, name)
    except ValueError as ve:
        if str(ve) == "unknown_preset":
            return JSONResponse({"ok": False, "error": "unknown_preset"}, status_code=400)
        return JSONResponse({"ok": False, "error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Project context (North Star Â§3)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/project_context")
def get_project_context_api():
    """Return current project context: name, domains, key_files, goals, lifecycle_stage. Read-only for Layla."""
    try:
        from layla.memory.db import get_project_context
        return get_project_context()
    except Exception as e:
        logger.warning("get_project_context failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/file_intent")
def get_file_intent_api(path: str = ""):
    """Read-only file intent (North Star Â§4). Query param: path. Returns format, intent, and format-specific keys."""
    if not path:
        return JSONResponse({"ok": False, "error": "path required"}, status_code=400)
    try:
        from layla.file_understanding import analyze_file
        return analyze_file(file_path=path)
    except Exception as e:
        logger.warning("file_intent failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/project_context")
async def set_project_context_api(req: Request):
    """Update project context. Body: project_name?, domains?, key_files?, goals?, lifecycle_stage?, progress?, blockers?, last_discussed?."""
    try:
        try:
            body = await req.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return await asyncio.to_thread(_sync_set_project_context, body)
    except Exception as e:
        logger.warning("set_project_context failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/workspace/index")
def workspace_index(req: dict):
    """Index workspace for semantic code search. body: {workspace_root: path}."""
    root = (req or {}).get("workspace_root", "")
    if not root:
        return JSONResponse({"ok": False, "error": "workspace_root required"})
    try:
        resolved = Path(root).expanduser().resolve()
        if not resolved.exists():
            return JSONResponse({"ok": False, "error": "workspace_root path does not exist"})
        if not resolved.is_dir():
            return JSONResponse({"ok": False, "error": "workspace_root must be a directory"})
        from services.workspace_index import index_workspace
        result = index_workspace(str(resolved))
        return {"ok": True, "indexed": result.get("indexed", 0), "skipped": result.get("skipped", 0), "errors": result.get("errors", [])}
    except Exception as e:
        logger.debug("workspace index failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/workspace/cognition/sync")
def workspace_cognition_sync(req: dict):
    """Build durable repo cognition packs for one or more roots. body: { workspace_roots: [path, ...], index_semantic?: bool, labels?: {path: name} }."""
    body = req or {}
    roots = body.get("workspace_roots")
    if isinstance(roots, str):
        roots = [roots]
    if not isinstance(roots, list) or not roots:
        return JSONResponse({"ok": False, "error": "workspace_roots (non-empty list) required"}, status_code=400)
    index_semantic = bool(body.get("index_semantic", False))
    labels = body.get("labels") if isinstance(body.get("labels"), dict) else {}
    try:
        from services.repo_cognition import sync_repo_cognition

        out = sync_repo_cognition(
            [str(x) for x in roots if str(x).strip()],
            index_semantic=index_semantic,
            labels={str(k): str(v) for k, v in labels.items()},
        )
        return JSONResponse(out)
    except Exception as e:
        logger.warning("workspace cognition sync failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/workspace/cognition")
def workspace_cognition_list(limit: int = 50):
    """List stored repo cognition snapshots (newest first)."""
    try:
        from layla.memory.db import list_repo_cognition_snapshots

        return JSONResponse({"ok": True, "snapshots": list_repo_cognition_snapshots(limit=limit)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/project_discovery")
def get_project_discovery_api():
    """North Star Â§18: detect opportunities, ideas, feasibility from project context + learnings."""
    try:
        from services.project_discovery import run_project_discovery
        return run_project_discovery()
    except Exception as e:
        logger.warning("project_discovery failed: %s", e)
        return JSONResponse(
            {"opportunities": [], "ideas": [], "feasibility_notes": [], "error": str(e)},
            status_code=500,
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# OpenAI-compatible model list
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/v1/models")
def v1_models():
    base = {
        "object": "model",
        "created": 1700000000,
        "owned_by": "local",
    }
    try:
        import orchestrator as _orch

        aspect_ids = [str(a.get("id", "")).strip() for a in (_orch._load_aspects() or []) if str(a.get("id", "")).strip()]
    except Exception:
        aspect_ids = ["morrigan", "nyx", "echo", "eris", "cassandra", "lilith"]
    models = [{"id": "layla", **base}]
    models.extend({"id": f"layla-{aid}", **base} for aid in aspect_ids)
    return JSONResponse({
        "object": "list",
        "data": models,
    })


# OpenAI-like error envelope helpers
def _v1_error(message: str, code: str = "invalid_request_error", status_code: int = 400, param: str | None = None):
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "param": param, "code": code}},
        status_code=status_code,
    )


def _normalize_openai_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = str(part.get("type", "")).strip().lower()
            if ptype in {"text", "input_text"}:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _parse_v1_model(model_name: str) -> tuple[str, str]:
    raw = (model_name or "layla").strip()
    if raw == "layla":
        return raw, ""
    if raw.startswith("layla-"):
        aspect = raw[len("layla-") :].strip()
        if aspect:
            return raw, aspect
    raise ValueError(f"Unsupported model '{raw}'. Use 'layla' or 'layla-<aspect_id>'.")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# OpenAI-compatible chat completions
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.post("/v1/chat/completions")
async def v1_chat_completions(req: dict):
    body = req or {}
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return _v1_error("'messages' must be a non-empty array.", param="messages")
    try:
        _, parsed_aspect = _parse_v1_model(str(body.get("model", "layla") or "layla"))
    except ValueError as e:
        return _v1_error(str(e), code="model_not_found", status_code=404, param="model")

    stream = bool((req or {}).get("stream", False))
    workspace_root = (req or {}).get("workspace_root", "") or ""
    allow_write = (req or {}).get("allow_write") is True
    allow_run = (req or {}).get("allow_run") is True
    aspect_id = (req or {}).get("aspect_id", "") or parsed_aspect
    show_thinking = bool((req or {}).get("show_thinking", False))
    conversation_id = ((req or {}).get("conversation_id") or "").strip() or str(uuid.uuid4())
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    goal = ""
    system_ctx = ""
    conversation_history: list[dict[str, str]] = []
    # Preserve full multi-turn context from OpenAI-style message arrays.
    # Use all prior user/assistant turns as history, and the last user turn as goal.
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = (msg.get("role", "") or "").strip()
        content = _normalize_openai_content(msg.get("content", ""))
        if role == "system":
            system_ctx = f"{system_ctx}\n{content}".strip() if content else system_ctx
            continue
        if role not in ("user", "assistant"):
            continue
        is_last = idx == (len(messages) - 1)
        if role == "user" and is_last:
            goal = content
        else:
            conversation_history.append({"role": role, "content": content})

    if not goal and messages:
        # Fallback: pick the last user message as goal even if trailing assistant/system entries exist.
        for msg in reversed(messages):
            if isinstance(msg, dict) and (msg.get("role", "") or "").strip() == "user":
                goal = _normalize_openai_content(msg.get("content", ""))
                break

    if not goal:
        return _v1_error("No user message content found in 'messages'.", param="messages")

    if stream:
        async def gen():
            response_text = ""
            model_name = f"layla-{aspect_id or 'morrigan'}"
            # First delta chunk with assistant role for parser compatibility.
            first_evt = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(first_evt)}\n\n"
            if not allow_write and not allow_run:
                quick = _quick_reply_for_trivial_turn(goal)
                if quick:
                    response_text = quick
                    evt = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {"content": quick}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(evt)}\n\n"
                else:
                    # Parser-safe progress marker (extra field should be ignored by OpenAI clients).
                    progress_evt = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                        "layla_progress": {"state": "waiting_first_token"},
                    }
                    yield f"data: {json.dumps(progress_evt)}\n\n"
                    # True incremental streaming: iterate generator in a worker thread (non-blocking event loop).
                    tok_q: queue.Queue = queue.Queue()

                    def _stream_worker() -> None:
                        try:
                            gen_tokens = stream_reason(
                                goal=goal,
                                context=system_ctx,
                                conversation_history=conversation_history,
                                aspect_id=aspect_id,
                                show_thinking=show_thinking,
                            )
                            for t in gen_tokens:
                                tok_q.put(t)
                        except Exception as ex:
                            logger.warning("v1 stream worker: %s", ex)
                        finally:
                            tok_q.put(None)

                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, _stream_worker)
                    while True:
                        token = await asyncio.to_thread(tok_q.get)
                        if token is None:
                            break
                        if not token:
                            continue
                        response_text += token
                        evt = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(evt)}\n\n"
            else:
                # Fallback to autonomous_run when write/run capabilities are requested.
                result = await asyncio.to_thread(
                    autonomous_run,
                    goal,
                    context=system_ctx,
                    workspace_root=workspace_root,
                    allow_write=allow_write,
                    allow_run=allow_run,
                    conversation_history=conversation_history,
                    aspect_id=aspect_id,
                    show_thinking=show_thinking,
                    conversation_id=conversation_id,
                )
                model_name = f"layla-{result.get('aspect', aspect_id or 'morrigan')}"
                response_text = (result.get("response") or "").strip()
                if not response_text:
                    steps = result.get("steps") or []
                    final = steps[-1].get("result", "") if steps else ""
                    response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
                if not response_text:
                    response_text = "No response."
                for chunk in [response_text[i:i + 120] for i in range(0, len(response_text), 120)]:
                    evt = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(evt)}\n\n"
            if not response_text:
                response_text = "No response."
            done_evt = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            _append_history("user", goal)
            _append_history("assistant", response_text)
            try:
                from layla.memory.db import append_conversation_message, create_conversation

                create_conversation(conversation_id, aspect_id=aspect_id)
                append_conversation_message(conversation_id, "user", goal, aspect_id=aspect_id)
                append_conversation_message(conversation_id, "assistant", response_text, aspect_id=aspect_id)
            except Exception:
                pass
            yield f"data: {json.dumps(done_evt)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    # Fast path for tiny chat turns in non-stream mode too.
    if not allow_write and not allow_run:
        quick = _quick_reply_for_trivial_turn(goal)
        if quick:
            response_text = quick
            _append_history("user", goal)
            _append_history("assistant", response_text)
            try:
                from layla.memory.db import append_conversation_message, create_conversation

                create_conversation(conversation_id, aspect_id=aspect_id)
                append_conversation_message(conversation_id, "user", goal, aspect_id=aspect_id)
                append_conversation_message(conversation_id, "assistant", response_text, aspect_id=aspect_id)
            except Exception:
                pass
            return JSONResponse({
                "id": completion_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": f"layla-{aspect_id or 'morrigan'}",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": len((goal or "").split()),
                    "completion_tokens": len((response_text or "").split()),
                    "total_tokens": len((goal or "").split()) + len((response_text or "").split()),
                },
                "aspect": aspect_id or "morrigan",
                "conversation_id": conversation_id,
            })

    try:
        result = await asyncio.to_thread(
            autonomous_run,
            goal,
            context=system_ctx,
            workspace_root=workspace_root,
            allow_write=allow_write,
            allow_run=allow_run,
            conversation_history=conversation_history,
            aspect_id=aspect_id,
            show_thinking=show_thinking,
            conversation_id=conversation_id,
        )
    except Exception as e:
        logger.exception("/v1/chat/completions failed")
        return _v1_error(f"Internal server error: {e}", code="internal_server_error", status_code=500)

    response_text = (result.get("response") or "").strip()
    if not response_text:
        steps = result.get("steps") or []
        final = steps[-1].get("result", "") if steps else ""
        response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
    if not response_text and result.get("status") == "system_busy":
        response_text = "System is under load (CPU or RAM). Try again in a moment."
    elif not response_text and result.get("status") == "timeout":
        response_text = "Request took too long and was stopped. Try a shorter message or try again."
    elif not response_text and result.get("status") == "tool_limit":
        response_text = "Stopped after maximum tool calls. Try a simpler request or say 'continue'."
    elif not response_text and result.get("status") == "parse_failed":
        response_text = "I couldn't understand the request. Please rephrase."
    elif not response_text:
        response_text = "No response. Try again or rephrase."

    _append_history("user", goal)
    _append_history("assistant", response_text)
    try:
        from layla.memory.db import append_conversation_message, create_conversation

        create_conversation(conversation_id, aspect_id=result.get("aspect", ""))
        append_conversation_message(conversation_id, "user", goal, aspect_id=result.get("aspect", ""))
        append_conversation_message(conversation_id, "assistant", response_text, aspect_id=result.get("aspect", ""))
    except Exception:
        pass

    return JSONResponse({
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"layla-{result.get('aspect', aspect_id or 'morrigan')}",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len((goal or "").split()),
            "completion_tokens": len((response_text or "").split()),
            "total_tokens": len((goal or "").split()) + len((response_text or "").split()),
        },
        "aspect": result.get("aspect", ""),
        "conversation_id": conversation_id,
    })


@app.post("/conversations")
def create_conversation_api(req: dict = Body(default={})):
    """Create an empty conversation row (for New chat in UI)."""
    import uuid

    try:
        from layla.memory.db import create_conversation

        body = req if isinstance(req, dict) else {}
        cid = (body.get("conversation_id") or "").strip() or str(uuid.uuid4())
        title = (body.get("title") or "").strip()
        aspect_id = (body.get("aspect_id") or "").strip()
        row = create_conversation(cid, title=title, aspect_id=aspect_id)
        return JSONResponse({"ok": True, "conversation": row})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/conversations")
def list_conversations_api(limit: int = 200):
    try:
        from layla.memory.db import list_conversations

        return JSONResponse({"ok": True, "conversations": list_conversations(limit=limit)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/conversations/search")
def search_conversations_api(q: str = "", limit: int = 50):
    try:
        from layla.memory.db import search_conversations

        return JSONResponse({"ok": True, "conversations": search_conversations(q, limit=limit)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/conversations/{conversation_id}")
def get_conversation_api(conversation_id: str):
    try:
        from layla.memory.db import get_conversation

        row = get_conversation(conversation_id)
        if not row:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        return JSONResponse({"ok": True, "conversation": row})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/conversations/{conversation_id}/messages")
def get_conversation_messages_api(conversation_id: str, limit: int = 300):
    try:
        from layla.memory.db import get_conversation_messages

        return JSONResponse({"ok": True, "messages": get_conversation_messages(conversation_id, limit=limit)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/conversations/{conversation_id}/rename")
def rename_conversation_api(conversation_id: str, req: dict):
    title = ((req or {}).get("title") or "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "title required"}, status_code=400)
    try:
        from layla.memory.db import rename_conversation

        ok = rename_conversation(conversation_id, title)
        if not ok:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete("/conversations/{conversation_id}")
def delete_conversation_api(conversation_id: str):
    try:
        from layla.memory.db import delete_conversation

        ok = delete_conversation(conversation_id)
        if not ok:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# System export
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/system_export")
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

    import subprocess
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
        git_branch = (r.stdout or "").strip() or "â€”"
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Learnings API â€” paginated read + delete
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/learnings")
def list_learnings(page: int = 1, limit: int = 20, type: str = ""):
    """Paginated list of learnings. Optional ?type= filter (fact, preference, strategy, identity, distilled)."""
    try:
        from layla.memory.db import _conn, migrate
        migrate()
        offset = (max(1, page) - 1) * limit
        with _conn() as db:
            if type:
                rows = db.execute(
                    "SELECT id, content, type, created_at, embedding_id FROM learnings WHERE type=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (type, limit, offset)
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM learnings WHERE type=?", (type,)).fetchone()[0]
            else:
                rows = db.execute(
                    "SELECT id, content, type, created_at, embedding_id FROM learnings ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        return JSONResponse({
            "page": page, "limit": limit, "total": total,
            "items": [dict(r) for r in rows],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/knowledge/ingest/sources")
def knowledge_ingest_sources_list():
    """List folders under knowledge/_ingested (Knowledge Manager)."""
    try:
        from services.doc_ingestion import list_ingested_sources

        return {"sources": list_ingested_sources()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/knowledge/ingest")
async def knowledge_ingest_run(request: Request):
    """Ingest URL or sandbox folder into knowledge/_ingested (re-index on next knowledge refresh)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        out = await asyncio.to_thread(
            _sync_ingest_docs,
            str(body.get("source") or ""),
            str(body.get("label") or ""),
        )
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete("/learnings/{learning_id}")
def delete_learning(learning_id: int):
    """Delete a learning by id. Also removes its vector from ChromaDB."""
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


@app.get("/audit")
def list_audit(page: int = 1, limit: int = 50, tool: str = ""):
    """Paginated audit log. Optional ?tool= filter."""
    try:
        from layla.memory.db import _conn, migrate
        migrate()
        offset = (max(1, page) - 1) * limit
        with _conn() as db:
            if tool:
                rows = db.execute(
                    "SELECT id, timestamp, tool, args_summary, approved_by, result_ok FROM audit WHERE tool=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (tool, limit, offset)
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM audit WHERE tool=?", (tool,)).fetchone()[0]
            else:
                rows = db.execute(
                    "SELECT id, timestamp, tool, args_summary, approved_by, result_ok FROM audit ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                ).fetchall()
                total = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        return JSONResponse({
            "page": page, "limit": limit, "total": total,
            "items": [dict(r) for r in rows],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Study plans API

@app.get("/study_plans")
def list_study_plans():
    try:
        from layla.memory.db import _conn, get_active_study_plans, migrate
        migrate()
        plans = get_active_study_plans()
        enriched = []
        with _conn() as db:
            for p in plans:
                topic_snip = (p.get("topic") or "")[:30]
                try:
                    row = db.execute(
                        "SELECT COUNT(*) as cnt, MAX(timestamp) as last FROM audit WHERE tool='study' AND args_summary LIKE ?",
                        (f"%{topic_snip}%",)
                    ).fetchone()
                    sessions = row["cnt"] if row else 0
                    last = row["last"] if row else None
                except Exception:
                    sessions = 0
                    last = None
                enriched.append({
                    "id": p.get("id"),
                    "topic": p.get("topic", ""),
                    "notes": p.get("notes", "") or "",
                    "created_at": p.get("created_at", ""),
                    "study_sessions": sessions,
                    "last_studied": last,
                })
        return JSONResponse({"plans": enriched})
    except Exception as e:
        return JSONResponse({"error": str(e), "plans": []})


@app.delete("/study_plans/{plan_id}")
def delete_study_plan(plan_id: int):
    try:
        from layla.memory.db import _conn, migrate
        migrate()
        with _conn() as db:
            db.execute("DELETE FROM study_plans WHERE id=?", (plan_id,))
            db.commit()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Missions API (v1.1 — long-running research/engineering tasks)

@app.post("/mission")
async def create_mission_api(req: Request):
    """Create and start a mission. Body: { "goal": str, "workspace_root": str?, "allow_write": bool?, "allow_run": bool? }."""
    try:
        body = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        try:
            result = await asyncio.to_thread(_sync_create_and_run_mission, body)
            return JSONResponse(result)
        except ValueError as ve:
            msg = str(ve)
            if msg == "goal required":
                return JSONResponse({"error": msg}, status_code=400)
            return JSONResponse({"error": msg}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/mission/{mission_id}")
def get_mission_api(mission_id: str):
    """Fetch a mission by id."""
    try:
        from layla.memory.db import get_mission
        mission = get_mission(mission_id)
        if not mission:
            return JSONResponse({"error": "mission not found"}, status_code=404)
        return JSONResponse(mission)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/missions")
def list_missions_api(status: str = "", limit: int = 50):
    """List missions. Query: status (pending|running|completed|failed), limit."""
    try:
        from layla.memory.db import get_missions
        status_filter = status if status in ("pending", "running", "completed", "failed") else None
        missions = get_missions(limit=max(1, min(100, limit)), status_filter=status_filter)
        return JSONResponse({"missions": missions})
    except Exception as e:
        return JSONResponse({"error": str(e), "missions": []})


# File content (safe read for diff viewer)

@app.get("/file_content")
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


# Voice endpoints
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/voice/transcribe")
async def voice_transcribe(request: Request):
    """
    Transcribe audio to text using faster-whisper.
    POST raw audio bytes (WAV/WebM/OGG/MP3).
    Returns: {"text": "...", "ok": true}
    """
    try:
        from services.stt import get_stt_recovery, is_stt_ready, transcribe_bytes

        audio_bytes = await request.body()
        if not audio_bytes:
            return JSONResponse({"ok": False, "error": "No audio data"}, status_code=400)
        if not is_stt_ready():
            rec = get_stt_recovery()
            return JSONResponse(
                {
                    "ok": False,
                    "text": "",
                    "error": "Speech-to-text is not available",
                    "recovery": rec or {"what_failed": "faster-whisper not loaded"},
                },
                status_code=503,
            )
        text = await asyncio.to_thread(transcribe_bytes, audio_bytes)
        return JSONResponse({"ok": True, "text": text})
    except Exception as e:
        logger.warning("STT error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/voice/speak")
async def voice_speak(request: Request):
    """
    Text-to-speech via kokoro-onnx (or pyttsx3 fallback).
    POST JSON: {"text": "Hello!"} or plain text body.
    Returns: WAV audio bytes (audio/wav).
    """
    try:
        from services.tts import get_tts_recovery, speak_to_bytes

        body = await request.body()
        try:
            import json as _j
            data = _j.loads(body)
            text = data.get("text", "")
        except Exception:
            text = body.decode("utf-8", errors="replace").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "No text provided"}, status_code=400)
        wav = await asyncio.to_thread(speak_to_bytes, text)
        if wav is None:
            rec = get_tts_recovery()
            return JSONResponse(
                {
                    "ok": False,
                    "error": "TTS not available",
                    "recovery": rec
                    or {
                        "what_failed": "No TTS engine",
                        "next_steps": ["pip install kokoro-onnx soundfile", "or: pip install pyttsx3"],
                    },
                },
                status_code=503,
            )
        from fastapi.responses import Response
        return Response(content=wav, media_type="audio/wav")
    except Exception as e:
        logger.warning("TTS error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Rich occult web UI â€” served at /ui
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/manifest.json")
def manifest():
    """PWA manifest."""
    manifest_file = AGENT_DIR / "ui" / "manifest.json"
    if manifest_file.exists():
        try:
            return JSONResponse(json.loads(manifest_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return JSONResponse({"name": "Layla", "short_name": "Layla", "start_url": "/ui", "display": "standalone"})


_UI_NO_CACHE = {"Cache-Control": "no-store"}


@app.get("/ui", response_class=HTMLResponse)
def ui_rich():
    touch_activity()
    ui_file = (AGENT_DIR / "ui" / "index.html").resolve()
    if ui_file.is_file():
        try:
            return HTMLResponse(ui_file.read_text(encoding="utf-8"), headers=_UI_NO_CACHE)
        except Exception as e:
            logger.warning("ui file read failed: %s", e)
    logger.warning("Serving fallback _INLINE_UI (file missing or unreadable): %s", ui_file)
    return HTMLResponse(_INLINE_UI, headers=_UI_NO_CACHE)


# Root serves the same full UI as /ui so chat works identically (no stale inline copy)
@app.get("/", response_class=HTMLResponse)
def ui_root():
    touch_activity()
    ui_file = (AGENT_DIR / "ui" / "index.html").resolve()
    if ui_file.is_file():
        try:
            return HTMLResponse(ui_file.read_text(encoding="utf-8"), headers=_UI_NO_CACHE)
        except Exception as e:
            logger.warning("ui file read failed: %s", e)
    logger.warning("Serving fallback _INLINE_UI (file missing or unreadable): %s", ui_file)
    return HTMLResponse(_INLINE_UI, headers=_UI_NO_CACHE)


_INLINE_UI = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Layla</title></head><body>
<h2>Layla UI unavailable</h2>
<p>The UI file <code>agent/ui/index.html</code> could not be read. Check that the file exists and the server has read access.</p>
</body></html>"""


