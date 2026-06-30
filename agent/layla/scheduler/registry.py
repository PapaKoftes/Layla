"""Scheduler registry — creates and configures the APScheduler BackgroundScheduler.

``create_scheduler(cfg)`` wires up every background job with the same
intervals, IDs, and conditional gates that were previously inline in
``main.py``'s ``lifespan()`` function.
"""

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from layla.scheduler.jobs import (
    _bg_backup,
    _bg_capability_decay,
    _bg_cleanup,
    _bg_codex,
    _bg_initiative,
    _bg_memory,
    _bg_reflect,
    _bg_reindex,
    _bg_repo_reindex,
    _intelligence_job,
    _mission_worker_job,
    _rl_preference_job,
    _scheduled_study_job,
)

logger = logging.getLogger("layla")

_scheduler: Optional[BackgroundScheduler] = None


def _instrumented(job_name: str, fn):
    """Wrap a job function to record Prometheus scheduler metrics."""
    def wrapper():
        try:
            fn()
            try:
                from services.observability.prom_metrics import record_scheduler_run
                record_scheduler_run(job_name, "ok")
            except Exception:
                pass
        except Exception as exc:
            try:
                from services.observability.prom_metrics import record_scheduler_run
                record_scheduler_run(job_name, "error")
            except Exception:
                pass
            raise exc
    wrapper.__name__ = fn.__name__
    return wrapper


def get_scheduler() -> Optional[BackgroundScheduler]:
    """Return the current scheduler instance (or ``None`` if not yet created)."""
    return _scheduler


def create_scheduler(cfg: dict) -> BackgroundScheduler:
    """Build a :class:`BackgroundScheduler`, register every background job,
    and return it **without** calling ``.start()`` (the caller starts it).

    Parameters
    ----------
    cfg:
        The Layla runtime-safety config dict (``runtime_safety.load_config()``).
    """
    global _scheduler

    sched = BackgroundScheduler(timezone="UTC")

    # ── Mission worker: always run (v1.1 long-running tasks) ────────────
    try:
        mission_interval_min = max(1, min(10, int(float(cfg.get("mission_worker_interval_minutes", 2)))))
        sched.add_job(_instrumented("mission_worker", _mission_worker_job), IntervalTrigger(minutes=mission_interval_min), id="mission_worker")
        logger.info("mission_worker scheduled every %s min", mission_interval_min)
    except (TypeError, ValueError):
        sched.add_job(_instrumented("mission_worker", _mission_worker_job), IntervalTrigger(minutes=2), id="mission_worker")

    # ── Architecture overhaul: background intelligence + consolidation ──
    try:
        _rmin = max(1, int(float(cfg.get("background_reflection_interval_minutes", 5) or 5)))
        _cmin = max(1, int(float(cfg.get("background_codex_update_interval_minutes", 10) or 10)))
        _mmin = max(5, int(float(cfg.get("background_memory_consolidation_interval_minutes", 30) or 30)))
        _imin = max(5, int(float(cfg.get("background_initiative_interval_minutes", 30) or 30)))
        sched.add_job(_bg_reflect, IntervalTrigger(minutes=_rmin), id="background_reflection")
        sched.add_job(_bg_codex, IntervalTrigger(minutes=_cmin), id="background_codex")
        sched.add_job(_bg_memory, IntervalTrigger(minutes=_mmin), id="background_memory_consolidation")
        sched.add_job(_bg_initiative, IntervalTrigger(minutes=_imin), id="background_initiative")
        sched.add_job(_bg_cleanup, IntervalTrigger(hours=24), id="background_memory_cleanup")

        # Nightly DB backup (P1-5): safe hot backup via SQLite .backup() API
        sched.add_job(_instrumented("nightly_backup", _bg_backup), IntervalTrigger(hours=24), id="nightly_db_backup")

        # Repo indexer: periodic reindex of the workspace repo (Phase B wiring).
        sched.add_job(_bg_repo_reindex, IntervalTrigger(minutes=30), id="repo_reindex", replace_existing=True)

        # P1-9: re-embed learnings whose ChromaDB write failed (dual-write consistency)
        sched.add_job(_instrumented("reindex_failed", _bg_reindex), IntervalTrigger(minutes=30), id="reindex_failed_learnings")

        logger.info(
            "background jobs: reflection %s min, codex %s min, memory %s min, initiative %s min, cleanup daily",
            _rmin,
            _cmin,
            _mmin,
            _imin,
        )
    except Exception as _bg_e:
        logger.warning("background intelligence schedule not started: %s", _bg_e)

    # ── Study + intelligence + RL (gated by scheduler_study_enabled) ────
    if cfg.get("scheduler_study_enabled", True):
        try:
            interval_min = max(5, min(120, int(float(cfg.get("scheduler_interval_minutes", 30)))))
        except (TypeError, ValueError):
            interval_min = 30
        sched.add_job(_scheduled_study_job, IntervalTrigger(minutes=interval_min))

        # Knowledge distillation + experience replay (intelligence systems)
        try:
            sched.add_job(_intelligence_job, IntervalTrigger(minutes=60), id="intelligence")
        except Exception:
            pass

        try:
            sched.add_job(_rl_preference_job, IntervalTrigger(minutes=30), id="rl_preference_update")
            logger.info("RL preference update scheduled every 30 min")
        except Exception as _rl_e:
            logger.debug("RL preference job not scheduled: %s", _rl_e)

        # Capability decay: penalise unpracticed skills once per day
        sched.add_job(
            _bg_capability_decay,
            IntervalTrigger(hours=24),
            id="capability_decay",
            replace_existing=True,
            name="capability_decay",
        )

        # Lens refresh (separately gated by its own config keys)
        if cfg.get("enable_lens_refresh") and cfg.get("lens_refresh_interval_days"):
            try:
                days = max(1, min(365, int(cfg["lens_refresh_interval_days"])))
                from lens_refresh import rebuild_lens_knowledge

                sched.add_job(rebuild_lens_knowledge, IntervalTrigger(days=days))
                logger.info("lens refresh scheduled every %s days", days)
            except (TypeError, ValueError) as e:
                logger.warning("lens refresh not scheduled: %s", e)

        logger.info("scheduler created (study every %s min when active)", interval_min)

    # ── Resource Governor tick ───────────────────────────────────────────
    if cfg.get("resource_governor_enabled", True):
        try:
            tick_sec = max(5, min(60, int(cfg.get("governor_tick_seconds", 15))))
            from services.infrastructure.resource_governor import governor_tick
            sched.add_job(
                _instrumented("governor_tick", governor_tick),
                IntervalTrigger(seconds=tick_sec),
                id="resource_governor_tick",
                replace_existing=True,
            )
            logger.info("resource governor tick scheduled every %s sec", tick_sec)
        except Exception as _gov_e:
            logger.warning("resource governor not scheduled: %s", _gov_e)

    # ── Cluster sync (Phase 3C) ────────────────────────────────────────
    if cfg.get("cluster_enabled", False):
        try:
            sync_interval = max(60, int(cfg.get("cluster_sync_interval", 300)))
            from services.cluster.node_sync import sync_now
            sched.add_job(
                _instrumented("cluster_sync", sync_now),
                IntervalTrigger(seconds=sync_interval),
                id="cluster_sync",
                replace_existing=True,
            )
            logger.info("cluster sync scheduled every %s sec", sync_interval)
        except Exception as _sync_e:
            logger.warning("cluster sync not scheduled: %s", _sync_e)

    # ── Task queue maintenance ──────────────────────────────────────────
    try:
        def _task_queue_maintenance():
            from services.cluster.work_unit import get_task_queue
            q = get_task_queue()
            q.reset_stuck()
            q.cleanup_stale()

        sched.add_job(
            _instrumented("task_queue_maintenance", _task_queue_maintenance),
            IntervalTrigger(hours=1),
            id="task_queue_maintenance",
            replace_existing=True,
        )
    except Exception as _tq_e:
        logger.debug("task queue maintenance not scheduled: %s", _tq_e)

    _scheduler = sched
    return sched
