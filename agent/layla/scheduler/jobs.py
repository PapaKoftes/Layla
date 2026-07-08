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
_EXEC_LOG = _GOV_PATH / "execution_log.jsonl"          # append-only tool log (C1)
_EXEC_LOG_LEGACY = _GOV_PATH / "execution_log.json"    # pre-1.0 array format — remove once
_AUTONOMOUS_AUDIT = _GOV_PATH / "autonomous_audit.jsonl"  # per-step autonomous log (H7)


def _prune_old_models(cfg: dict) -> int:
    """Delete GGUF models beyond the newest `models_max_keep`, ALWAYS keeping the active one.

    OFF by default (models_max_keep=0): superseded GGUFs are tens of GB (audit H8), but a user's
    downloaded models must never be auto-deleted by surprise — this only prunes when the operator
    opts in by setting a keep-count. Returns count deleted."""
    try:
        keep = int(cfg.get("models_max_keep", 0) or 0)
        if keep <= 0:
            return 0
        import runtime_safety as _rs
        mdir = Path(cfg.get("models_dir") or _rs.default_models_dir())
        if not mdir.is_dir():
            return 0
        active = (cfg.get("model_filename") or "").strip()
        ggufs = sorted(mdir.glob("*.gguf"), key=lambda p: p.stat().st_mtime, reverse=True)
        candidates = [g for g in ggufs if g.name != active]  # newest-first, never the active model
        deleted = 0
        for g in candidates[keep:]:
            try:
                g.unlink()
                deleted += 1
                logger.info("_bg_cleanup: pruned superseded model %s", g.name)
            except Exception:
                pass
        return deleted
    except Exception:
        return 0


def _prune_temp_tool_outputs(days: int = 7) -> int:
    """Remove Layla's tool-output files (charts/TTS/screenshots/extracted frames) left in the
    system temp dir older than `days` (M7). Targets ONLY Layla's own 'layla_*'/'frames_*' names,
    so no unrelated temp files are touched. Returns count removed."""
    import shutil
    import tempfile
    import time as _t
    removed = 0
    try:
        if days <= 0:
            return 0
        tmp = Path(tempfile.gettempdir())
        cutoff = _t.time() - days * 86400
        for p in tmp.glob("layla_*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except Exception:
                pass
        for d in tmp.glob("frames_*"):
            try:
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(str(d), ignore_errors=True)
                    removed += 1
            except Exception:
                pass
    except Exception:
        pass
    return removed


def _tail_trim_file(path: Path, max_bytes: int) -> None:
    """Best-effort: if `path` exceeds max_bytes, keep only the trailing max_bytes, starting at a
    line boundary. Shared by the flat audit log and the append-only JSONL logs so none grows
    without bound over a year of operation."""
    try:
        if max_bytes <= 0 or not path.exists():
            return
        if int(path.stat().st_size) <= max_bytes:
            return
        with open(str(path), "rb") as f:
            f.seek(-max_bytes, 2)
            tail = f.read(max_bytes)
        i = tail.find(b"\n")
        if 0 < i < len(tail) - 1:
            tail = tail[i + 1:]
        with open(str(path), "wb") as f:
            f.write(tail)
    except Exception:
        pass


# ── mission worker ──────────────────────────────────────────────────────
def _mission_worker_job() -> None:
    """Background job: run next step of active missions.  Persists progress for restart recovery."""
    try:
        from layla.memory.db import get_active_missions
        from services.planning.mission_manager import execute_next_step

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
        from services.infrastructure.background_intelligence import run_reflection_scan

        run_reflection_scan()
    except Exception as _e:
        logger.warning("background_reflection: %s", _e)


# ── background codex entity nudge ──────────────────────────────────────
def _bg_codex() -> None:
    try:
        from services.infrastructure.background_intelligence import run_codex_entity_nudge

        run_codex_entity_nudge()
    except Exception as _e:
        logger.warning("background_codex: %s", _e)


# ── background memory consolidation ────────────────────────────────────
def _bg_memory() -> None:
    try:
        from services.memory.memory_consolidation import consolidate_periodic

        consolidate_periodic()
    except Exception as _e:
        logger.warning("background_memory_consolidation: %s", _e)


# ── background initiative / project proposals ──────────────────────────
def _bg_initiative() -> None:
    try:
        import runtime_safety as _rs
        from services.infrastructure.initiative_engine import generate_project_proposals
        from services.personality.maturity_engine import get_trust_tier

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
        from services.memory.memory_consolidation import (
            apply_retention_policies,
            decay_stored_confidence,
            prune_low_confidence_learnings,
        )

        _c = _rs.load_config()
        # B2: decay stored confidence FIRST so stale memories drift below the threshold, THEN
        # archive the ones that crossed it — this is what makes the store actually forget.
        decay_stored_confidence(_c)
        th = float(_c.get("memory_cleanup_confidence_threshold", 0.08) or 0.08)
        prune_low_confidence_learnings(threshold=th)
        apply_retention_policies(_c)
        try:
            # Keep the append-only logs bounded (best-effort) — tail-trim to the configured cap.
            _tail_trim_file(_AUDIT_LOG, int(_c.get("audit_log_max_bytes", 2_000_000) or 2_000_000))
            _tail_trim_file(_EXEC_LOG, int(_c.get("execution_log_max_bytes", 5_000_000) or 5_000_000))
            _tail_trim_file(_AUTONOMOUS_AUDIT, int(_c.get("autonomous_audit_max_bytes", 5_000_000) or 5_000_000))
            # LOW: the other append-only logs + crash dumps also had no rotation.
            _tail_trim_file(_GOV_PATH / "layla-events.log", int(_c.get("events_log_max_bytes", 2_000_000) or 2_000_000))
            _tail_trim_file(Path.home() / ".layla" / "investigation_reuse.jsonl",
                            int(_c.get("investigation_reuse_max_bytes", 5_000_000) or 5_000_000))
            try:
                _cd = Path.home() / ".layla" / "crashes"
                if _cd.is_dir():
                    _keep = int(_c.get("crash_dumps_keep", 50) or 50)
                    _dumps = sorted(_cd.glob("crash_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                    for _old in _dumps[_keep:]:
                        try:
                            _old.unlink()
                        except Exception:
                            pass
            except Exception:
                pass
            # One-time: drop the pre-1.0 whole-file execution_log.json (superseded by .jsonl).
            if _EXEC_LOG_LEGACY.exists():
                try:
                    _EXEC_LOG_LEGACY.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # Reclaim disk: VACUUM oversized fallback vector stores (self-gating on size), and
            # incremental-vacuum the live DB (effective on new auto_vacuum=INCREMENTAL installs).
            from layla.memory.fallback_store import vacuum_open_fallback_stores
            vacuum_open_fallback_stores(int(_c.get("vector_vacuum_min_bytes", 20_000_000) or 20_000_000))
            from layla.memory.db_connection import _conn
            with _conn() as db:
                db.execute("PRAGMA incremental_vacuum")
                db.commit()
            _prune_old_models(_c)  # opt-in GGUF retention (models_max_keep); no-op by default
            _prune_temp_tool_outputs(int(_c.get("retention_temp_output_days", 7) or 7))  # M7
        except Exception:
            pass
        try:
            # Populate the people codex from recent conversations (wires the previously-orphan
            # people_codex module). Best-effort; gated so operators can turn it off.
            if _c.get("people_codex_enabled", True):
                from services.memory.people_codex import save_people_to_codex, scan_conversations_for_people
                _ppl = scan_conversations_for_people(limit=int(_c.get("people_codex_scan_limit", 100) or 100))
                if _ppl:
                    save_people_to_codex(_ppl)
        except Exception as _pe:
            logger.debug("people_codex scan skipped: %s", _pe)
        try:
            # Bound the in-memory conversation registries — they grew one entry per distinct
            # conversation for the whole process lifetime (durable copies are in SQLite).
            from services.infrastructure.session_context import prune_stale_sessions
            _idle = float(_c.get("session_idle_prune_seconds", 3600) or 3600)
            _npr = prune_stale_sessions(max_age_seconds=_idle)
            import shared_state as _ss
            _npr += _ss.prune_conversation_histories(int(_c.get("conversation_history_max", 500) or 500))
            if _npr:
                logger.debug("_bg_cleanup: pruned %d idle session/history entries", _npr)
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
        from services.workspace.repo_indexer import index_workspace_repo

        _c = _rs.load_config()
        _ws = (_c.get("sandbox_root") or "").strip()
        if _ws:
            index_workspace_repo(_ws)
    except Exception as _e:
        logger.warning("background_repo_reindex: %s", _e)
        try:
            from services.infrastructure.degraded import mark_degraded

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
        from services.memory.study_service import run_autonomous_study_for_plan

        summary = run_autonomous_study_for_plan(plan)
        if domain_id:
            try:
                usefulness = cap_mod.run_learning_validation(summary)
                cap_mod.record_practice(domain_id, mission_id=plan.get("id"), usefulness_score=usefulness)
                append_scheduler_history(domain_id, plan.get("id"))
            except Exception as e:
                logger.warning("capability record_practice failed: %s", e)
        logger.info("scheduled_study completed topic=%s domain_id=%s", plan.get("topic"), domain_id)
        # Maturity: award XP for completing a study session
        try:
            from services.personality.maturity_engine import award_xp
            award_xp(20, reason="study_session")
        except Exception:
            pass
    except Exception as e:
        logger.exception("scheduled_study failed: %s", e)


# ── intelligence (distillation + replay + curiosity) ───────────────────
def _intelligence_job() -> None:
    try:
        from services.memory.knowledge_distiller import run_periodic_distillation

        run_periodic_distillation()
    except Exception as _e:
        logger.warning("intelligence_job: knowledge_distiller failed: %s", _e)
    try:
        from services.infrastructure.experience_replay import run_experience_replay

        replay_summary = run_experience_replay()
        if replay_summary:
            logger.info("experience_replay summary: %s", replay_summary)
    except Exception as _e:
        logger.warning("intelligence_job: experience_replay failed: %s", _e)
    try:
        from services.memory.curiosity_engine import get_curiosity_suggestions
        from services.memory.memory_router import save_learning  # canonical write path

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


# ── P1-9: reindex failed learnings (dual-write consistency) ──────────
def _bg_reindex() -> None:
    """Background job: re-embed learnings whose ChromaDB write failed."""
    try:
        from layla.memory.learnings import reindex_failed_learnings

        count = reindex_failed_learnings()
        if count > 0:
            logger.info("bg_reindex: reindexed %d failed learnings", count)
    except Exception as _e:
        logger.warning("bg_reindex: %s", _e)


# ── RL preference update ──────────────────────────────────────────────
def _rl_preference_job() -> None:
    try:
        from services.infrastructure.rl_feedback import run_preference_update_job

        run_preference_update_job()
    except Exception:
        pass


# ── nightly DB backup (P1-5) ─────────────────────────────────────────
def _bg_backup() -> None:
    """Create a nightly SQLite backup via the .backup() API."""
    try:
        from services.infrastructure.db_backup import backup_database

        result = backup_database()
        if result.get("ok"):
            logger.info(
                "nightly_backup: %s (%.1f KB, pruned %d)",
                result.get("backup_path", "?"),
                result.get("size_kb", 0),
                result.get("pruned", 0),
            )
        else:
            logger.warning("nightly_backup: %s", result)
    except Exception as _e:
        logger.warning("nightly_backup: %s", _e)


# ── capability decay (daily) ─────────────────────────────────────────
def _bg_capability_decay() -> None:
    """Apply capability decay for unpracticed skills (daily)."""
    try:
        from layla.memory.capabilities import apply_decay_if_needed
        apply_decay_if_needed()
    except Exception as e:
        logger.debug("capability_decay job failed: %s", e)
