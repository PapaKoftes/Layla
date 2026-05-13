"""Background job functions for the Layla APScheduler.

Every function uses **lazy imports** inside the body to avoid circular
imports at module-load time — this is intentional (same pattern as
the original main.py inline definitions).
"""

import logging
import time
from pathlib import Path

from layla.scheduler.activity import get_last_activity_ts, is_game_running

logger = logging.getLogger("layla")

# Paths needed by _bg_cleanup — derived the same way main.py computes them.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent
_GOV_PATH = _AGENT_DIR / ".governance"
_AUDIT_LOG = _GOV_PATH / "audit.log"


# ── mission worker ──────────────────────────────────────────────────────
def _mission_worker_job() -> None:
    """Background job: run next step of active missions.  Persists progress for restart recovery."""
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


# ── background reflection ──────────────────────────────────────────────
def _bg_reflect() -> None:
    try:
        from services.background_intelligence import run_reflection_scan

        run_reflection_scan()
    except Exception as _e:
        logger.warning("background_reflection: %s", _e)


# ── background codex entity nudge ──────────────────────────────────────
def _bg_codex() -> None:
    try:
        from services.background_intelligence import run_codex_entity_nudge

        run_codex_entity_nudge()
    except Exception as _e:
        logger.warning("background_codex: %s", _e)


# ── background memory consolidation ────────────────────────────────────
def _bg_memory() -> None:
    try:
        from services.memory_consolidation import consolidate_periodic

        consolidate_periodic()
    except Exception as _e:
        logger.warning("background_memory_consolidation: %s", _e)


# ── background initiative / project proposals ──────────────────────────
def _bg_initiative() -> None:
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


# ── background memory cleanup + audit-log rotation ─────────────────────
def _bg_cleanup() -> None:
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
            if max_bytes > 0 and _AUDIT_LOG.exists():
                try:
                    sz = int(_AUDIT_LOG.stat().st_size)
                except Exception:
                    sz = 0
                if sz > max_bytes:
                    try:
                        with open(str(_AUDIT_LOG), "rb") as f:
                            f.seek(-max_bytes, 2)
                            tail = f.read(max_bytes)
                        # Ensure we start at a line boundary if possible.
                        try:
                            i = tail.find(b"\n")
                            if i > 0 and i < len(tail) - 1:
                                tail = tail[i + 1:]
                        except Exception:
                            pass
                        with open(str(_AUDIT_LOG), "wb") as f:
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
                out_dir = _REPO_ROOT / ".research_output"
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


# ── repo reindex (Phase B) ─────────────────────────────────────────────
def _bg_repo_reindex() -> None:
    try:
        import runtime_safety as _rs
        from services.repo_indexer import index_workspace_repo

        _c = _rs.load_config()
        _ws = (_c.get("sandbox_root") or "").strip()
        if _ws:
            index_workspace_repo(_ws)
    except Exception as _e:
        logger.warning("background_repo_reindex: %s", _e)
        try:
            from services.degraded import mark_degraded

            mark_degraded("repo_indexer", str(_e))
        except Exception:
            pass


# ── scheduled autonomous study ─────────────────────────────────────────
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
        if time.time() - get_last_activity_ts() > activity_min * 60:
            return
        if is_game_running():
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


# ── intelligence (distillation + replay + curiosity) ───────────────────
def _intelligence_job() -> None:
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
        from services.memory_router import save_learning  # canonical write path

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


# ── RL preference update ──────────────────────────────────────────────
def _rl_preference_job() -> None:
    try:
        from services.rl_feedback import run_preference_update_job

        run_preference_update_job()
    except Exception:
        pass
