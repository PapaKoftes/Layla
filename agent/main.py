import asyncio
import json
import logging
import os
import queue
import shutil
import sys

# Python runtime gate: 3.11–3.12 supported; 3.13+ only if stack self-check passes (see setup/python_compat.py).
try:
    from setup.python_compat import (
        BLOCKER_CHROMADB_INCOMPATIBLE,
    )
    from setup.python_compat import (
        check_python_compatibility as _check_python_compatibility,
    )
except Exception as _compat_import_exc:
    sys.stderr.write(f"Layla: failed to load setup.python_compat: {_compat_import_exc}\n")
    raise SystemExit(1) from _compat_import_exc

_compat_result = _check_python_compatibility()
_compat_status = _compat_result.get("status")
_compat_blockers = list(_compat_result.get("critical_blockers") or [])

if _compat_status == "unsupported":
    sys.stderr.write(
        "Layla cannot start on this Python/runtime:\n"
        + "\n".join(f"  - {x}" for x in (_compat_result.get("issues") or ["unknown issue"]))
        + f"\nInterpreter: {_compat_result.get('version')}\n"
        "Install dependencies (see agent/requirements.txt) or use Python 3.11 or 3.12.\n"
    )
    raise SystemExit(1)

if _compat_status == "supported_unofficial":
    if BLOCKER_CHROMADB_INCOMPATIBLE in _compat_blockers:
        os.environ["LAYLA_CHROMA_DISABLED"] = "1"
        sys.stderr.write(
            "Layla: Semantic memory disabled (Chroma unavailable).\n"
            "Vector learnings / Chroma-backed retrieval are off until the stack matches this interpreter.\n"
        )
        sys.stderr.write(
            f"Layla: Python {_compat_result.get('version')} — CONDITIONALLY supported "
            f"(critical_blockers={_compat_blockers}, safe_mode={_compat_result.get('safe_mode')}). "
            "Prefer Python 3.11 or 3.12 for production.\n"
        )
    else:
        sys.stderr.write(
            f"Layla: Python {_compat_result.get('version')} — best-effort mode (dependency stack OK). "
            "Prefer Python 3.11 or 3.12 for production.\n"
        )

import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
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
            format="%(asctime)s [%(levelname)s] %(name)s: %(task_ctx)s%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    # Phase 4.3: install task-context filter so concurrent runs don't mix logs
    try:
        from services.task_context import install_filter as _install_task_ctx_filter
        _install_task_ctx_filter("layla")
    except Exception:
        pass
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
                    def _bg_index_knowledge() -> None:
                        try:
                            index_knowledge_docs(knowledge_dir)
                            logger.info("knowledge docs indexed for Chroma")
                        except Exception as _e:
                            logger.warning("knowledge index failed: %s", _e)

                    threading.Thread(
                        target=_bg_index_knowledge,
                        daemon=True,
                        name="knowledge-index-startup",
                    ).start()
                    logger.info("knowledge indexing thread started")
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
        try:
            from services.llm_gateway import llm_request_queue

            llm_request_queue.start()
            logger.info("LLM request queue worker started")
        except Exception as e:
            logger.warning("LLM request queue start failed: %s", e)
        # Sweep orphaned worktrees from prior crashes (best-effort).
        try:
            max_age_s = int(float(cfg.get("worktree_orphan_max_age_seconds", 3600) or 3600))
            if max_age_s > 0:
                wt_root = REPO_ROOT.parent / ".layla_worktrees"
                if wt_root.exists():
                    cutoff = time.time() - max_age_s
                    for d in wt_root.iterdir():
                        try:
                            if not d.is_dir():
                                continue
                            if d.stat().st_mtime < cutoff:
                                shutil.rmtree(str(d), ignore_errors=True)
                        except Exception:
                            pass
        except Exception:
            pass
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
        # Phase 0.5: pre-embed recent learnings at startup so first-turn retrieval is fast
        if cfg.get("embedding_cache_warmup_enabled", True):
            def _warmup_embedding_cache() -> None:
                try:
                    from layla.memory.db import get_recent_learnings
                    from layla.memory.vector_store import embed_batch

                    learnings = get_recent_learnings(n=5000)
                    texts = [
                        l.get("content") or ""
                        for l in (learnings or [])
                        if (l.get("content") or "").strip()
                    ][:2000]
                    if not texts:
                        return
                    logger.info("embedding_cache_warmup: pre-embedding %d learnings", len(texts))
                    embed_batch(texts)
                    logger.info("embedding_cache_warmup: done")
                except Exception as _we:
                    logger.debug("embedding_cache_warmup failed (non-critical): %s", _we)

            threading.Thread(
                target=_warmup_embedding_cache,
                daemon=True,
                name="embedding-cache-warmup",
            ).start()

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
        # Architecture overhaul: background intelligence + consolidation
        try:
            def _bg_reflect():
                try:
                    from services.background_intelligence import run_reflection_scan

                    run_reflection_scan()
                except Exception as _e:
                    logger.warning("background_reflection: %s", _e)

            def _bg_codex():
                try:
                    from services.background_intelligence import run_codex_entity_nudge

                    run_codex_entity_nudge()
                except Exception as _e:
                    logger.warning("background_codex: %s", _e)

            def _bg_memory():
                try:
                    from services.memory_consolidation import consolidate_periodic

                    consolidate_periodic()
                except Exception as _e:
                    logger.warning("background_memory_consolidation: %s", _e)

            def _bg_initiative():
                try:
                    import runtime_safety as _rs
                    from services.initiative_engine import generate_project_proposals
                    from services.maturity_engine import get_trust_tier

                    _c = _rs.load_config()
                    if not bool(_c.get("initiative_project_proposals_enabled", False)):
                        return
                    if int(get_trust_tier(_c)) < 2:
                        return
                    _ = generate_project_proposals()
                except Exception as _e:
                    logger.warning("background_initiative: %s", _e)

            def _bg_cleanup():
                try:
                    import runtime_safety as _rs
                    from services.memory_consolidation import apply_retention_policies, prune_low_confidence_learnings

                    _c = _rs.load_config()
                    th = float(_c.get("memory_cleanup_confidence_threshold", 0.08) or 0.08)
                    prune_low_confidence_learnings(threshold=th)
                    apply_retention_policies(_c)
                    try:
                        # Keep flat audit log bounded (best-effort). If it's too large, keep only the tail.
                        max_bytes = int(_c.get("audit_log_max_bytes", 2_000_000) or 2_000_000)
                        if max_bytes > 0 and AUDIT_LOG.exists():
                            try:
                                sz = int(AUDIT_LOG.stat().st_size)
                            except Exception:
                                sz = 0
                            if sz > max_bytes:
                                try:
                                    with open(str(AUDIT_LOG), "rb") as f:
                                        f.seek(-max_bytes, 2)
                                        tail = f.read(max_bytes)
                                    # Ensure we start at a line boundary if possible.
                                    try:
                                        i = tail.find(b"\n")
                                        if i > 0 and i < len(tail) - 1:
                                            tail = tail[i + 1 :]
                                    except Exception:
                                        pass
                                    with open(str(AUDIT_LOG), "wb") as f:
                                        f.write(tail)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    try:
                        # Research output retention (best-effort): remove old timestamped markdown files.
                        days = int(_c.get("retention_research_output_days", 90) or 90)
                        if days > 0:
                            cutoff_ts = time.time() - (days * 86400)
                            out_dir = REPO_ROOT / ".research_output"
                            if out_dir.exists():
                                for p in out_dir.glob("*.md"):
                                    if p.name == "last_research.md":
                                        continue
                                    try:
                                        if p.stat().st_mtime < cutoff_ts:
                                            p.unlink(missing_ok=True)
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                except Exception as _e:
                    logger.warning("background_memory_cleanup: %s", _e)

            _rmin = max(1, int(float(cfg.get("background_reflection_interval_minutes", 5) or 5)))
            _cmin = max(1, int(float(cfg.get("background_codex_update_interval_minutes", 10) or 10)))
            _mmin = max(5, int(float(cfg.get("background_memory_consolidation_interval_minutes", 30) or 30)))
            _imin = max(5, int(float(cfg.get("background_initiative_interval_minutes", 30) or 30)))
            sched.add_job(_bg_reflect, IntervalTrigger(minutes=_rmin), id="background_reflection")
            sched.add_job(_bg_codex, IntervalTrigger(minutes=_cmin), id="background_codex")
            sched.add_job(_bg_memory, IntervalTrigger(minutes=_mmin), id="background_memory_consolidation")
            sched.add_job(_bg_initiative, IntervalTrigger(minutes=_imin), id="background_initiative")
            sched.add_job(_bg_cleanup, IntervalTrigger(hours=24), id="background_memory_cleanup")
            logger.info(
                "background jobs: reflection %s min, codex %s min, memory %s min, initiative %s min, cleanup daily",
                _rmin,
                _cmin,
                _mmin,
                _imin,
            )
        except Exception as _bg_e:
            logger.warning("background intelligence schedule not started: %s", _bg_e)
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
                        from layla.memory.db import save_learning
                        from services.curiosity_engine import get_curiosity_suggestions
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
            try:

                def _rl_preference_job():
                    try:
                        from services.rl_feedback import run_preference_update_job

                        run_preference_update_job()
                    except Exception:
                        pass

                sched.add_job(_rl_preference_job, IntervalTrigger(minutes=30), id="rl_preference_update")
                logger.info("RL preference update scheduled every 30 min")
            except Exception as _rl_e:
                logger.debug("RL preference job not scheduled: %s", _rl_e)
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

try:
    import runtime_safety as _cors_rs

    _origins = _cors_rs.load_config().get("remote_cors_origins") or []
    if isinstance(_origins, list) and any(str(o).strip() for o in _origins):
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(o).strip() for o in _origins if str(o).strip()],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = Path(__file__).resolve().parent
DOCS_DIR = REPO_ROOT / "docs"
HISTORY_FILE = REPO_ROOT / "conversation_history.json"
GOV_PATH = AGENT_DIR / ".governance"
PENDING_FILE = GOV_PATH / "pending.json"
AUDIT_LOG = GOV_PATH / "audit.log"

# In-memory conversation history (max 20 turns); also persisted to disk
_history: deque = deque(maxlen=20)
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


from shared_state import pending_file_lock as _pending_file_lock  # noqa: E402


def _read_pending() -> list:
    try:
        with _pending_file_lock:
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
        logger.debug("_audit flat write failed: %s", e)
    try:
        from layla.memory.db import log_audit as _log_audit_sql

        _log_audit_sql(tool, args_summary, approved_by, result_ok)
    except Exception as e:
        logger.debug("_audit sqlite write failed: %s", e)


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
from routers import autonomous as autonomous_router  # noqa: E402
from routers import memory as memory_router  # noqa: E402
from routers import research as research_router  # noqa: E402
from routers import system as system_router
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
app.include_router(system_router.router)
app.include_router(approvals.router)
app.include_router(agent_router.router)
app.include_router(agents_router.router)
app.include_router(research_router.router)
app.include_router(memory_router.router)
app.include_router(autonomous_router.router)  # /autonomous/run
from routers import aspects as aspects_router
from routers import codex as codex_router
from routers import improvements as improvements_router
from routers import journal as journal_router
from routers import plan_file as plan_file_router
from routers import plans as plans_router
from routers import projects as projects_router

app.include_router(codex_router.router)
app.include_router(aspects_router.router)
app.include_router(journal_router.router)
app.include_router(improvements_router.router)
app.include_router(projects_router.router)
app.include_router(plans_router.router)
app.include_router(plan_file_router.router)

from routers import (  # noqa: E402
    conversations as conversations_router,
)
from routers import (
    knowledge as knowledge_router,
)
from routers import (
    missions as missions_router,
)
from routers import (
    openai_compat as openai_compat_router,
)
from routers import (
    session as session_router,
)
from routers import (
    settings as settings_router,
)
from routers import (
    tools_history as tools_history_router,
)
from routers import (
    voice as voice_router,
)
from routers import (
    workspace as workspace_router,
)
from routers import (
    search as search_router,
)
from routers import (
    obsidian as obsidian_router,
)
from routers import (
    german as german_router,
)

app.include_router(settings_router.router)
app.include_router(session_router.router)
app.include_router(conversations_router.router)
app.include_router(knowledge_router.router)
app.include_router(workspace_router.router)
app.include_router(openai_compat_router.router)
app.include_router(missions_router.router)
app.include_router(voice_router.router)
app.include_router(tools_history_router.router)  # Phase 0.2: tool call history
app.include_router(search_router.router)  # Phase 1.4: global smart search
app.include_router(obsidian_router.router)  # Phase 5.1: Obsidian vault connector
app.include_router(german_router.router)   # Item #10: German language learning mode

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


@app.get("/sw.js", include_in_schema=False)
def serve_service_worker():
    """PWA service worker (offline-friendly UI assets)."""
    p = _UI_DIR / "sw.js"
    if not p.is_file():
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    return FileResponse(str(p), media_type="application/javascript; charset=utf-8")


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
            "/health/",
            "/agent",
            "/v1/chat/completions",
            "/learn/",
            "/memories",
            "/schedule",
            "/conversations",
            "/local_access_info",
            "/ui",
            "/projects",
            "/session/export",
            "/session/",
            "/compact",
            "/ctx_viz",
            "/audit",
            "/learnings",
            "/system_export",
            "/values.md",
            "/settings",
            "/setup_status",
            "/setup/models",
            "/setup/download",
            "/setup/auto",
            "/approve",
            "/pending",
            "/doctor",
            "/usage",
            "/undo",
            "/version",
            "/knowledge/",
            "/workspace/",
            "/plan/",
            "/plans",
            "/skill_packs",
            "/remote/",
            "/codex/",
            "/research_mission",
            "/voice/",
            "/agents/",
            "/execute_plan",
            "/manifest.json",
            "/sw.js",
            "/layla-ui",
            "/update/",
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
async def remote_rate_limit_middleware(request: Request, call_next):
    """When remote_enabled: cap requests per minute per client IP (non-localhost only)."""
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
    try:
        lim = int(float(cfg.get("remote_rate_limit_per_minute", 100)))
    except (TypeError, ValueError):
        lim = 100
    try:
        from services.remote_rate_limit import check_rate_limit

        ok, reason = check_rate_limit(client_host or "unknown", lim)
        if not ok:
            return JSONResponse(
                {
                    "ok": False,
                    "error": reason,
                    "detail": "Too many requests from this address. Try again in a minute.",
                },
                status_code=429,
            )
    except Exception:
        pass
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


