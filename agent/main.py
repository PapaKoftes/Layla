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

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
        # Start async LLM request queue worker
        try:
            from services.llm_gateway import llm_request_queue
            llm_request_queue.start()
            logger.info("LLM request queue worker started")
        except Exception as e:
            logger.warning("LLM request queue start failed: %s", e)
        # Pre-warm LLM in background thread - first request will be instant
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
                    except Exception:
                        pass
                    try:
                        from services.experience_replay import run_experience_replay
                        run_experience_replay()
                    except Exception:
                        pass
                sched.add_job(_intelligence_job, IntervalTrigger(minutes=60), id="intelligence")
            except Exception:
                pass
            # RL preference update job (every 30 min)
            try:
                from services.rl_feedback import run_preference_update_job as _rl_job
                sched.add_job(_rl_job, IntervalTrigger(minutes=30), id="rl_preference_update")
                logger.info("RL preference update scheduled every 30 min")
            except Exception as e:
                logger.debug("RL preference job not scheduled: %s", e)
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
    try:
        from services.llm_gateway import llm_request_queue
        await llm_request_queue.stop()
    except Exception:
        pass


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


# Lock for pending.json reads+writes to prevent race conditions from concurrent requests
_pending_file_lock = threading.Lock()


def _read_pending() -> list:
    with _pending_file_lock:
        try:
            if PENDING_FILE.exists():
                data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.debug("_read_pending failed: %s", e)
        return []


def _write_pending_list(data: list) -> None:
    with _pending_file_lock:
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
app.include_router(research_router.router)
app.include_router(memory_router.router)

if DOCS_DIR.exists():
    app.mount("/docs", StaticFiles(directory=str(DOCS_DIR)), name="docs")


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Â§16 Remote: auth and endpoint allowlist (production-safe, minimal)
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def _remote_allowed_paths(cfg: dict) -> list[str]:
    """Derive allowlist from remote_mode if remote_allow_endpoints not set."""
    explicit = cfg.get("remote_allow_endpoints") or []
    if isinstance(explicit, list) and len(explicit) > 0:
        return [str(p).strip() for p in explicit if p]
    mode = (cfg.get("remote_mode") or "observe").strip().lower()
    if mode == "interactive":
        return ["/wakeup", "/project_discovery", "/health", "/agent", "/v1/chat/completions", "/learn/"]
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


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Health
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
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


@app.get("/version")
def version():
    return {"ok": True, "version": __version__}


@app.get("/rl/preferences")
def rl_preferences():
    """Return current RL tool preference table as JSON."""
    try:
        from layla.memory.db import get_rl_preferences
        prefs = get_rl_preferences()
        return {"ok": True, "preferences": prefs}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


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


@app.post("/agent/cancel/{conversation_id}")
async def cancel_agent(conversation_id: str):
    """Signal cancellation for the given conversation_id. Returns immediately."""
    from shared_state import set_cancel
    found = set_cancel(conversation_id)
    return JSONResponse({"ok": True, "found": found, "conversation_id": conversation_id})


@app.delete("/agent")
async def cancel_agent_latest():
    """Cancel the most recently active agent request."""
    from shared_state import get_most_recent_conv_id, set_cancel
    conv_id = get_most_recent_conv_id()
    if conv_id:
        found = set_cancel(conv_id)
        return JSONResponse({"ok": True, "found": found, "conversation_id": conv_id})
    return JSONResponse({"ok": False, "error": "No active request"})


@app.get("/aspects/reload")
def aspects_reload():
    """Force-reload all aspect JSON files and return count of loaded aspects."""
    try:
        import orchestrator as _orch
        aspects = _orch.reload_aspects()
        return JSONResponse({"ok": True, "loaded": len(aspects)})
    except Exception as e:
        logger.warning("aspects reload failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e), "loaded": 0})


@app.post("/memory/rebuild")
async def memory_rebuild():
    """Trigger async rebuild of the ChromaDB vector collection from SQLite learnings."""
    async def _do_rebuild():
        try:
            from layla.memory.vector_store import rebuild_collection
            rebuild_collection()
            logger.info("memory rebuild complete")
        except Exception as e:
            logger.warning("memory rebuild failed: %s", e)

    asyncio.create_task(_do_rebuild())
    return JSONResponse({"ok": True, "status": "rebuilding"})


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
    if not ok:
        payload["detail"] = detail
        return JSONResponse(payload, status_code=503)
    return payload


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Setup status + settings (for first-run overlay and settings panel)
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

@app.get("/health/deps")
def health_deps(request: Request):
    """Lightweight dependency matrix; optional Chroma vector probe via ?deep=true."""
    deep = ((request.query_params.get("deep") or "").strip().lower() == "true")
    try:
        from services.health_snapshot import build_dependency_status

        return {"dependencies": build_dependency_status(probe_chroma=deep)}
    except Exception as e:
        return {"dependencies": {}, "error": str(e)}


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
    try:
        cfg = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8")) if _rs.CONFIG_FILE.exists() else {}
    except Exception:
        cfg = {}
    out = {}
    for e in EDITABLE_SCHEMA:
        k = e["key"]
        if k in cfg:
            out[k] = cfg[k]
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


@app.post("/settings")
async def save_settings(req: Request):
    """Update runtime_config.json. Merges with existing config. Only editable keys accepted."""
    import runtime_safety as _rs
    from config_schema import EDITABLE_SCHEMA, get_editable_keys
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    editable = get_editable_keys()
    try:
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
        # Preserve full config: merge with existing, write complete file
        _rs.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _rs.CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        if hasattr(_rs, "_config_cache"):
            _rs._config_cache = None
        return {"ok": True, "saved": saved}
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
    import runtime_safety as _rs
    try:
        cfg: dict = {}
        if _rs.CONFIG_FILE.exists():
            try:
                cfg = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        merged, applied = apply_settings_preset(cfg, name)
        if merged is None:
            return JSONResponse({"ok": False, "error": "unknown_preset"}, status_code=400)
        for k in applied:
            merged[k] = _coerce_setting_value(k, merged[k], EDITABLE_SCHEMA)
        _rs.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _rs.CONFIG_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        if hasattr(_rs, "_config_cache"):
            _rs._config_cache = None
        return {"ok": True, "preset": name.lower(), "applied": applied}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Project context (North Star Â§3)
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
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
        from layla.memory.db import PROJECT_LIFECYCLE_STAGES, set_project_context
        try:
            body = await req.json()
        except Exception:
            body = {}
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


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# OpenAI-compatible model list
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
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


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# OpenAI-compatible chat completions
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
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
                    # True incremental streaming for normal chat path.
                    gen_tokens = stream_reason(
                        goal=goal,
                        context=system_ctx,
                        conversation_history=conversation_history,
                        aspect_id=aspect_id,
                        show_thinking=show_thinking,
                    )
                    for token in gen_tokens:
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


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# System export
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
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
        git_branch = (r.stdout or "").strip() or ""
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


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Learnings API â€" paginated read + delete
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

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
    try:
        from services.doc_ingestion import ingest_docs

        out = ingest_docs(str(body.get("source") or ""), str(body.get("label") or ""))
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


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

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


# Missions API (v1.1 - long-running research/engineering tasks)

@app.post("/mission")
async def create_mission_api(req: Request):
    """Create and start a mission. Body: { "goal": str, "workspace_root": str?, "allow_write": bool?, "allow_run": bool? }."""
    try:
        body = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        from services.mission_manager import create_mission, run_mission
        goal = (body.get("goal") or "").strip()
        if not goal:
            return JSONResponse({"error": "goal required"}, status_code=400)
        mission = create_mission(
            goal=goal,
            workspace_root=(body.get("workspace_root") or "").strip(),
            allow_write=bool(body.get("allow_write")),
            allow_run=bool(body.get("allow_run")),
        )
        if not mission:
            return JSONResponse({"error": "mission creation failed (plan empty or planner error)"}, status_code=500)
        run_mission(mission["id"])
        return JSONResponse({"ok": True, "mission": mission})
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
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

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
        text = transcribe_bytes(audio_bytes)
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
        wav = speak_to_bytes(text)
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


@app.websocket("/voice/stream")
async def voice_stream_ws(websocket: WebSocket):
    """
    WebSocket endpoint for streaming voice input.
    Client sends raw audio chunks (WebM/PCM 16kHz int16 mono).
    Server sends back partial transcription tokens as JSON:
      {"text": "...", "is_final": false}
    Final message: {"text": "...", "is_final": true}
    Error message: {"error": "...", "is_final": true}
    Send "END" as a text message to signal end of audio stream.
    """
    await websocket.accept()

    # Check STT availability upfront
    _stt_ready = False
    _transcribe_streaming = None
    try:
        from services.stt import is_stt_ready as _is_stt_ready
        from services.stt import transcribe_streaming as _ts
        _stt_ready = _is_stt_ready()
        _transcribe_streaming = _ts
    except Exception:
        pass

    if not _stt_ready or _transcribe_streaming is None:
        await websocket.send_json({
            "error": "STT not available. Install faster-whisper: pip install faster-whisper",
            "is_final": True,
        })
        await websocket.close()
        return

    # Audio accumulation — 16kHz int16 mono = 32000 bytes/second; collect ~2 s per chunk
    _CHUNK_BYTES = 32000 * 2  # 2 seconds of 16kHz int16
    audio_buffer = bytearray()
    final_text = ""

    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=30.0)
            except asyncio.TimeoutError:
                break

            if message["type"] == "websocket.disconnect":
                break

            if message["type"] == "websocket.receive":
                # Text control message
                if message.get("text") is not None:
                    text_msg = (message["text"] or "").strip()
                    if text_msg.upper() == "END":
                        # Process remaining buffer as final
                        if audio_buffer:
                            try:
                                for partial, is_final in _transcribe_streaming(bytes(audio_buffer)):
                                    final_text = partial
                                    await websocket.send_json({
                                        "text": partial,
                                        "is_final": is_final,
                                    })
                                audio_buffer.clear()
                            except Exception as e:
                                logger.warning("voice_stream_ws transcription error: %s", e)
                        break
                    continue

                # Binary audio data
                if message.get("bytes") is not None:
                    chunk = message["bytes"]
                    if chunk:
                        audio_buffer.extend(chunk)

                # Process when we have enough audio (~2 seconds)
                if len(audio_buffer) >= _CHUNK_BYTES:
                    try:
                        chunk_data = bytes(audio_buffer[:_CHUNK_BYTES])
                        audio_buffer = audio_buffer[_CHUNK_BYTES:]
                        for partial, is_final_seg in _transcribe_streaming(chunk_data):
                            if partial:
                                final_text = partial
                                await websocket.send_json({
                                    "text": partial,
                                    "is_final": False,
                                })
                    except Exception as e:
                        logger.warning("voice_stream_ws partial transcription error: %s", e)

        # Send final result
        await websocket.send_json({"text": final_text, "is_final": True})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("voice_stream_ws error: %s", e)
        try:
            await websocket.send_json({"error": str(e), "is_final": True})
        except Exception:
            pass


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Rich occult web UI â€" served at /ui
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
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


_INLINE_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>âˆ´ LAYLA</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Cinzel:wght@400;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<style>
  :root {
    --bg: #0a0008;
    --bg2: #100010;
    --crimson: #8b0000;
    --violet: #3d0050;
    --accent: #c0006a;
    --text: #d4c5e2;
    --text-dim: #7a6a8a;
    --code-bg: #1a001a;
    --border: #3d0050;
    --glow: #8b000088;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    min-height: 100vh;
    overflow-x: hidden;
  }
  /* Scanline overlay */
  body::after {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.08) 2px,
      rgba(0,0,0,0.08) 4px
    );
    pointer-events: none;
    z-index: 9999;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--bg2);
  }
  .title { font-family: 'Cinzel', serif; color: var(--crimson); font-size: 1.3rem; letter-spacing: 0.2em; }
  .aspect-badge {
    font-size: 0.75rem;
    color: var(--accent);
    border: 1px solid var(--accent);
    padding: 3px 10px;
    border-radius: 2px;
    letter-spacing: 0.15em;
  }
  .layout {
    display: flex;
    height: calc(100vh - 56px);
  }
  .sidebar {
    width: 220px;
    min-width: 180px;
    border-right: 1px solid var(--border);
    background: var(--bg2);
    padding: 16px 12px;
    display: flex;
    flex-direction: column;
    gap: 24px;
    overflow-y: auto;
  }
  .sidebar h3 {
    font-family: 'Cinzel', serif;
    font-size: 0.7rem;
    color: var(--text-dim);
    letter-spacing: 0.2em;
    text-transform: uppercase;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 4px;
  }
  .aspect-btn {
    display: block;
    width: 100%;
    padding: 7px 10px;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    cursor: pointer;
    text-align: left;
    border-radius: 2px;
    margin-bottom: 4px;
    transition: all 0.15s;
  }
  .aspect-btn:hover, .aspect-btn.active { background: var(--violet); border-color: var(--accent); color: #fff; }
  .aspect-option { margin-bottom: 10px; }
  .aspect-desc { display: block; font-size: 0.68rem; color: var(--text-dim); margin-top: 2px; margin-left: 2px; line-height: 1.25; }
  .main-area {
    flex: 1;
    display: flex;
    flex-direction: column;
  }
  #chat {
    flex: 1;
    overflow-y: auto;
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .msg { max-width: 720px; }
  .msg-you { align-self: flex-end; }
  .msg-layla { align-self: flex-start; }
  .msg-label {
    font-size: 0.72rem;
    color: var(--text-dim);
    margin-bottom: 4px;
    letter-spacing: 0.08em;
  }
  .msg-bubble {
    padding: 14px 18px;
    border-radius: 4px;
    line-height: 1.65;
    font-size: 0.95rem;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg-you .msg-bubble { background: var(--violet); border-left: 3px solid var(--accent); }
  .msg-layla .msg-bubble { background: var(--code-bg); border-left: 3px solid var(--crimson); }
  .msg-aspect { font-size: 0.68rem; color: var(--accent); margin-top: 6px; letter-spacing: 0.08em; font-style: italic; }
  .deliberation { background: #1a001a; border: 1px solid var(--border); padding: 10px 12px; margin-top: 8px; font-size: 0.82rem; color: var(--text-dim); border-radius: 4px; }
  .deliberation .deliberation-label { font-style: italic; margin-bottom: 4px; }
  .tool-trace { font-size: 0.72rem; color: var(--text-dim); margin-top: 6px; cursor: pointer; }
  .typing-indicator { padding: 10px 16px; color: var(--text-dim); font-style: italic; font-size: 0.88rem; }
  .sidebar-hint { font-size: 0.7rem; color: var(--text-dim); line-height: 1.4; margin-top: 8px; }
  .tool-trace summary { list-style: none; }
  .tool-trace summary::-webkit-details-marker { display: none; }
  .tool-trace-content { margin-top: 6px; padding: 8px; background: var(--bg); border-radius: 2px; font-size: 0.7rem; max-height: 120px; overflow-y: auto; }
  .msg-bubble .md-content { white-space: normal; }
  .msg-bubble .md-content pre { margin: 8px 0; overflow-x: auto; }
  .msg-bubble .md-content code { padding: 2px 6px; }
  .separator { text-align: center; color: var(--border); font-size: 0.8rem; margin: 4px 0; }
  .input-area {
    border-top: 1px solid var(--border);
    padding: 14px 20px;
    background: var(--bg2);
    display: flex;
    gap: 10px;
    align-items: center;
  }
  .toggles { display: flex; gap: 8px; align-items: center; }
  .toggle-label { font-size: 0.7rem; color: var(--text-dim); }
  .toggle-danger { color: #ff4444; }
  input[type=checkbox] { accent-color: var(--crimson); }
  #msg-input {
    flex: 1;
    padding: 10px 14px;
    background: var(--code-bg);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.9rem;
    border-radius: 2px;
    outline: none;
  }
  #msg-input:focus { border-color: var(--crimson); }
  #send-btn {
    padding: 10px 18px;
    background: var(--crimson);
    border: none;
    color: #fff;
    font-family: 'Cinzel', serif;
    font-size: 0.8rem;
    letter-spacing: 0.1em;
    cursor: pointer;
    border-radius: 2px;
    transition: background 0.15s;
  }
  #send-btn:hover { background: var(--accent); }
  .panels {
    width: 240px;
    border-left: 1px solid var(--border);
    background: var(--bg2);
    padding: 14px 12px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .panel-title {
    font-family: 'Cinzel', serif;
    font-size: 0.7rem;
    color: var(--text-dim);
    letter-spacing: 0.2em;
    text-transform: uppercase;
    border-bottom: 1px solid var(--border);
    padding-bottom: 4px;
    margin-bottom: 8px;
  }
  .panel-item {
    font-size: 0.75rem;
    color: var(--text);
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 2px;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
  }
  .approve-btn {
    padding: 3px 8px;
    background: var(--crimson);
    border: none;
    color: #fff;
    font-size: 0.65rem;
    cursor: pointer;
    border-radius: 2px;
    font-family: 'JetBrains Mono', monospace;
  }
  .study-add { display: flex; gap: 6px; margin-top: 6px; }
  .study-add input {
    flex: 1;
    padding: 5px 8px;
    background: var(--code-bg);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    border-radius: 2px;
  }
  .study-add button {
    padding: 5px 8px;
    background: var(--violet);
    border: 1px solid var(--border);
    color: var(--text);
    font-size: 0.75rem;
    cursor: pointer;
    border-radius: 2px;
  }
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  .greeting-banner {
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 14px 18px;
    font-size: 0.92rem;
    line-height: 1.5;
    color: var(--text);
    align-self: flex-start;
    max-width: 720px;
  }
  .greeting-banner .from { font-size: 0.72rem; color: var(--accent); margin-bottom: 6px; letter-spacing: 0.06em; font-style: italic; }
  code { background: var(--code-bg); padding: 1px 5px; border-radius: 2px; font-family: 'JetBrains Mono', monospace; color: #ff4466; }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.6/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
</head>
<body>
<header>
  <div class="title">âˆ´ LAYLA</div>
  <div id="aspect-badge" class="aspect-badge">âˆ´ MORRIGAN</div>
  <div style="display:flex;gap:12px;font-size:0.72rem;color:var(--text-dim)">
    <span id="session-time"></span>
    <a href="/system_export" target="_blank" style="color:var(--text-dim);text-decoration:none">âŠ• export</a>
  </div>
</header>

<div class="layout">
  <!-- Aspect sidebar -->
  <div class="sidebar">
    <div>
      <h3>Voices</h3>
      <p class="sidebar-hint">Talk to Layla or choose a voice. She remembers and grows with you.</p>
      <div class="aspect-option">
        <button class="aspect-btn active" onclick="setAspect('morrigan')" id="btn-morrigan">&#9876; Morrigan</button>
        <span class="aspect-desc">Code, debug, review. The blade. Default for engineering.</span>
      </div>
      <div class="aspect-option">
        <button class="aspect-btn" onclick="setAspect('nyx')" id="btn-nyx">&#9733; Nyx</button>
        <span class="aspect-desc">Research, study sessions, depth and patterns.</span>
      </div>
      <div class="aspect-option">
        <button class="aspect-btn" onclick="setAspect('echo')" id="btn-echo">&#9678; Echo</button>
        <span class="aspect-desc">Companion, growth tracker, session greeter.</span>
      </div>
      <div class="aspect-option">
        <button class="aspect-btn" onclick="setAspect('eris')" id="btn-eris">&#9889; Eris</button>
        <span class="aspect-desc">Chaos, banter, games, music. Unhinged in the best way.</span>
      </div>
      <div class="aspect-option">
        <button class="aspect-btn" onclick="setAspect('lilith')" id="btn-lilith">&#8859; Lilith</button>
        <span class="aspect-desc">Core authority, ethics. NSFW register: use keyword (e.g. intimate, nsfw) in message.</span>
      </div>
    </div>
    <div>
      <h3>Options</h3>
      <label style="display:flex;gap:8px;align-items:center;font-size:0.75rem;cursor:pointer;margin-bottom:8px" title="See her reply as it types">
        <input type="checkbox" id="stream-toggle"> Stream
      </label>
      <label style="display:flex;gap:8px;align-items:center;font-size:0.75rem;cursor:pointer;margin-bottom:8px" title="Let her think with her inner voices before answering">
        <input type="checkbox" id="show-thinking"> Her thoughts
      </label>
      <label style="display:flex;gap:8px;align-items:center;font-size:0.75rem;cursor:pointer;color:#ff4444;margin-bottom:4px">
        <input type="checkbox" id="allow-write"> Allow Write
      </label>
      <label style="display:flex;gap:8px;align-items:center;font-size:0.75rem;cursor:pointer;color:#ff4444">
        <input type="checkbox" id="allow-run"> Allow Run
      </label>
    </div>
  </div>

  <!-- Chat area -->
  <div class="main-area">
    <div id="chat"></div>
    <div class="input-area">
      <input type="text" id="msg-input" placeholder="What's on your mind?" onkeydown="if(event.key==='Enter')send()">
      <button id="send-btn" onclick="send()">Send</button>
    </div>
  </div>

  <!-- Panels -->
  <div class="panels">
    <div>
      <div class="panel-title">Pending Approvals</div>
      <div id="approvals-list"><span style="color:var(--text-dim);font-size:0.75rem">none</span></div>
    </div>
    <div>
      <div class="panel-title">Study Plans</div>
      <div id="study-list"><span style="color:var(--text-dim);font-size:0.75rem">none</span></div>
      <div class="study-add">
        <input type="text" id="study-input" placeholder="New topic...">
        <button onclick="addStudyPlan()">+</button>
      </div>
    </div>
  </div>
</div>

<script>
let currentAspect = 'morrigan';
const sessionStart = Date.now();

function setAspect(id) {
  currentAspect = id;
  document.querySelectorAll('.aspect-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + id)?.classList.add('active');
  document.getElementById('aspect-badge').textContent = 'âˆ´ ' + id.toUpperCase();
}

function cleanLaylaText(s) {
  if (typeof s !== 'string') return (s == null || s === undefined) ? '' : String(s);
  return s.replace(/\\s*\\[EARNED_TITLE:\\s*[^\\]]+\\]\\s*$/gi, '').trim();
}

function addMsg(role, text, aspectName, deliberated, steps) {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg msg-' + (role === 'you' ? 'you' : 'layla');
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = role === 'you' ? 'You' : 'Layla';
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  if (role === 'layla') {
    text = cleanLaylaText(text || '');
    if (typeof marked !== 'undefined') {
      const md = document.createElement('div');
      md.className = 'md-content';
      md.innerHTML = marked.parse(text || '');
      bubble.appendChild(md);
      bubble.querySelectorAll('pre code').forEach((el) => { if (window.hljs) hljs.highlightElement(el); });
    } else {
      bubble.textContent = text;
    }
  } else {
    bubble.textContent = text;
  }
  div.appendChild(label);
  div.appendChild(bubble);
  if (role !== 'you' && aspectName) {
    const asp = document.createElement('div');
    asp.className = 'msg-aspect';
    asp.textContent = 'â€" ' + aspectName;
    div.appendChild(asp);
  }
  if (steps && steps.length > 0) {
    const trace = document.createElement('details');
    trace.className = 'tool-trace';
    trace.innerHTML = '<summary>What she did (' + steps.length + ')</summary>';
    const pre = document.createElement('div');
    pre.className = 'tool-trace-content';
    pre.textContent = steps.map(s => s.action + ': ' + JSON.stringify(s.result).slice(0, 200)).join('\n');
    trace.appendChild(pre);
    div.appendChild(trace);
  }
  if (deliberated) {
    const d = document.createElement('div');
    d.className = 'deliberation';
    d.innerHTML = '<span class="deliberation-label">Her thoughts</span><br>She considered this with her inner voices before answering.';
    div.appendChild(d);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function addSeparator() {
  const chat = document.getElementById('chat');
  const sep = document.createElement('div');
  sep.className = 'separator';
  sep.textContent = 'â"€â"€â"€ âœ¦ â"€â"€â"€';
  chat.appendChild(sep);
}

async function send() {
  const input = document.getElementById('msg-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  addMsg('you', msg);
  addSeparator();

  const streamMode = document.getElementById('stream-toggle')?.checked || false;
  const payload = {
    message: msg,
    aspect_id: currentAspect,
    show_thinking: document.getElementById('show-thinking').checked,
    allow_write: document.getElementById('allow-write').checked,
    allow_run: document.getElementById('allow-run').checked,
    stream: streamMode,
  };

  const chatEl = document.getElementById('chat');
  function showTyping() {
    const wrap = document.createElement('div');
    wrap.className = 'msg msg-layla';
    wrap.id = 'typing-wrap';
    wrap.innerHTML = '<div class="msg-label">Layla</div><div class="msg-bubble typing-indicator">Thinkingâ€¦</div>';
    chatEl.appendChild(wrap);
    chatEl.scrollTop = chatEl.scrollHeight;
  }
  function removeTyping() {
    const w = document.getElementById('typing-wrap');
    if (w) w.remove();
  }

  try {
    if (streamMode) {
      showTyping();
      const res = await fetch('/agent', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!res.ok || !res.body) { removeTyping(); let errMsg = res.statusText; try { const t = await res.text(); if (t) try { const d = JSON.parse(t); errMsg = d.response || errMsg; } catch(_) { errMsg = t.length < 120 ? t : errMsg; } } catch(_) {} addMsg('layla', errMsg, null, false, null); refreshApprovals(); return; }
      removeTyping();
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = '';
      const div = document.createElement('div');
      div.className = 'msg msg-layla';
      div.innerHTML = '<div class="msg-label">Layla</div><div class="msg-bubble"><div class="md-content"></div></div>';
      chatEl.appendChild(div);
      const bubble = div.querySelector('.md-content');
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = dec.decode(value, { stream: true });
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const obj = JSON.parse(line.slice(6));
              if (obj.token) { full += obj.token; bubble.innerHTML = typeof marked !== 'undefined' ? marked.parse(full) : full; bubble.querySelectorAll('pre code').forEach(el => { if (window.hljs) hljs.highlightElement(el); }); }
              if (obj.done) break;
            } catch (_) {}
          }
        }
      }
      full = cleanLaylaText(full);
      bubble.innerHTML = typeof marked !== 'undefined' ? marked.parse(full) : full;
      bubble.querySelectorAll('pre code').forEach(el => { if (window.hljs) hljs.highlightElement(el); });
      const asp = document.createElement('div');
      asp.className = 'msg-aspect';
      asp.textContent = 'â€" ' + (currentAspect || '');
      div.appendChild(asp);
      chatEl.scrollTop = chatEl.scrollHeight;
      refreshApprovals();
      return;
    }
    showTyping();
    const res = await fetch('/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    removeTyping();
    if (!res.ok) {
      let errBody = '';
      try { errBody = await res.text(); } catch (_) {}
      addMsg('layla', 'Error ' + res.status + (errBody && errBody.length < 150 ? ': ' + errBody : ''));
      refreshApprovals();
      return;
    }
    let data = {};
    try { data = await res.json(); } catch (_) {
      addMsg('layla', 'Invalid response from server (non-JSON).');
      refreshApprovals();
      return;
    }
    let msg = data.response;
    if (!msg && data.state?.status === 'system_busy') msg = 'System is under load. Try again in a moment.';
    if (!msg && data.state?.status === 'timeout') msg = 'Request took too long. Try again.';
    if (!msg) msg = data.response || 'No response â€" try again.';
    addMsg('layla', msg, data.aspect_name, data.state?.steps?.some(s => s.deliberated), data.state?.steps);
    if (data.refused && data.refusal_reason) {
      const refDiv = document.createElement('div');
      refDiv.className = 'deliberation';
      refDiv.innerHTML = '<span class="deliberation-label">She declined</span><br>' + (data.refusal_reason || '').replace(/</g, '&lt;');
      document.getElementById('chat').lastElementChild?.appendChild(refDiv);
    }
    refreshApprovals();
  } catch (e) {
    removeTyping();
    const err = ((e && (e.message || e.reason)) || String(e || '')).toLowerCase();
    const isNetwork = err.includes('fetch') || err.includes('network') || err.includes('load failed');
    const msg = isNetwork ? "Can't reach Layla â€" is the server running at http://127.0.0.1:8000?" : ('Something went wrong: ' + (e && (e.message || e.reason)) || 'unknown error');
    addMsg('layla', msg);
  }
}

async function refreshApprovals() {
  try {
    const res = await fetch('/pending');
    const data = await res.json();
    const list = document.getElementById('approvals-list');
    const pending = (data.pending || []).filter(e => e.status === 'pending');
    if (!pending.length) { list.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">none</span>'; return; }
    list.innerHTML = '';
    pending.forEach(e => {
      const item = document.createElement('div');
      item.className = 'panel-item';
      item.innerHTML = '<span style="font-size:0.7rem">' + e.tool + '<br><span style="color:var(--text-dim)">' + e.id.slice(0,8) + '</span></span>';
      const btn = document.createElement('button');
      btn.className = 'approve-btn';
      btn.textContent = 'Approve';
      btn.onclick = () => approveId(e.id);
      item.appendChild(btn);
      list.appendChild(item);
    });
  } catch {}
}

async function approveId(id) {
  await fetch('/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  refreshApprovals();
}

async function refreshStudyPlans() {
  try {
    const res = await fetch('/study_plans');
    const data = await res.json();
    const list = document.getElementById('study-list');
    const plans = (data.plans || []).filter(p => p.status === 'active');
    if (!plans.length) { list.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">none</span>'; return; }
    list.innerHTML = '';
    plans.forEach(p => {
      const item = document.createElement('div');
      item.className = 'panel-item';
      item.style.display = 'flex';
      item.style.justifyContent = 'space-between';
      item.style.alignItems = 'center';
      item.style.gap = '6px';
      item.innerHTML = '<span style="font-size:0.72rem">' + (p.topic || '').replace(/</g, '&lt;') + '</span>';
      const studyBtn = document.createElement('button');
      studyBtn.className = 'approve-btn';
      studyBtn.textContent = 'Study now';
      studyBtn.onclick = () => studyNow(p.topic);
      item.appendChild(studyBtn);
      list.appendChild(item);
    });
  } catch {}
}

async function studyNow(topic) {
  if (!topic) return;
  const payload = { message: 'Study session on: ' + topic + '. Explain key concepts, list important points, and suggest resources.', aspect_id: 'nyx', show_thinking: false, allow_write: false, allow_run: false };
  addMsg('you', 'Study now: ' + topic);
  addSeparator();
  try {
    const res = await fetch('/agent', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    addMsg('layla', data.response || '', data.aspect_name, data.state?.steps?.some(s => s.deliberated), data.state?.steps);
  } catch (e) { addMsg('layla', 'Error: ' + e.message); }
  refreshStudyPlans();
}

async function addStudyPlan() {
  const input = document.getElementById('study-input');
  const topic = input.value.trim();
  if (!topic) return;
  input.value = '';
  await fetch('/study_plans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic }),
  });
  refreshStudyPlans();
}

async function doWakeup() {
  try {
    const res = await fetch('/wakeup');
    const data = await res.json();
    if (data.greeting) {
      const chat = document.getElementById('chat');
      const banner = document.createElement('div');
      banner.className = 'greeting-banner';
      banner.innerHTML = '<div class="from">â€" Echo (session start)</div>' + data.greeting;
      chat.appendChild(banner);
    }
  } catch {}
}

// Session timer
setInterval(() => {
  const elapsed = Math.floor((Date.now() - sessionStart) / 1000);
  const m = Math.floor(elapsed / 60).toString().padStart(2,'0');
  const s = (elapsed % 60).toString().padStart(2,'0');
  document.getElementById('session-time').textContent = m + ':' + s;
}, 1000);

// Init
doWakeup();
refreshApprovals();
refreshStudyPlans();
</script>
</body>
</html>
"""


