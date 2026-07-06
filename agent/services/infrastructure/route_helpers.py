"""Helpers shared by FastAPI routers (extracted from main)."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_plugins_cache: dict = {}
_plugins_cache_ts: float = 0.0
_PLUGINS_CACHE_TTL: float = 60.0


def get_cached_plugins(cfg: dict) -> dict:
    """Avoid rescanning plugins on every UI refresh."""
    global _plugins_cache, _plugins_cache_ts
    now = time.time()
    if _plugins_cache and (now - _plugins_cache_ts) < _PLUGINS_CACHE_TTL:
        return _plugins_cache
    from services.skills.plugin_loader import load_plugins

    _plugins_cache = load_plugins(cfg)
    _plugins_cache_ts = now
    return _plugins_cache


def sync_save_settings(body: dict) -> dict:
    """Blocking: merge editable keys into runtime_config.json (race-safe, atomic, clamped)."""
    import runtime_safety as _rs

    # save_config_keys reads+writes under _config_lock and clamps each value to the
    # schema (config_schema.coerce_and_clamp), so out-of-range input can't be persisted
    # and two concurrent writers can't lose each other's changes.
    saved = _rs.save_config_keys(body, editable_only=True, clamp=True)
    return {"ok": True, "saved": saved}


def sync_apply_runtime_preset(name: str) -> dict:
    """Blocking: merge named preset into runtime_config.json (race-safe, atomic, clamped)."""
    import runtime_safety as _rs
    from config_schema import SETTINGS_PRESETS, apply_settings_preset

    if name.lower() not in SETTINGS_PRESETS:
        raise ValueError("unknown_preset")
    merged, applied = apply_settings_preset({}, name)
    if merged is None:
        raise ValueError("unknown_preset")
    _rs.save_config_keys({k: merged[k] for k in applied}, editable_only=True, clamp=True)
    return {"ok": True, "preset": name.lower(), "applied": applied}


def sync_set_project_context(body: dict) -> dict:
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


def sync_ingest_docs(source: str, label: str) -> dict:
    from services.workspace.doc_ingestion import ingest_docs

    return ingest_docs(source, label)


def sync_create_and_run_mission(body: dict) -> dict:
    from services.planning.mission_manager import create_mission, run_mission

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


def sync_save_appearance(body: dict) -> dict:
    import runtime_safety as _rs

    _allowed = ("ui_avatar_seed", "ui_avatar_style", "ui_tts_rate", "chat_lite_mode", "ui_decision_trace_enabled", "ui_appearance_json")
    # These are UI-only keys (not in EDITABLE_SCHEMA) → editable_only=False, clamp=False.
    # Still race-safe + atomic via save_config_keys.
    updates = {k: body[k] for k in _allowed if k in body}
    saved = _rs.save_config_keys(updates, editable_only=False, clamp=False)
    return {"ok": True, "saved": saved}


def sync_compact_history() -> dict:
    """Summarize in-memory chat history when over context threshold."""
    import runtime_safety
    from services.context.context_manager import summarize_history
    from shared_state import get_history

    cfg = runtime_safety.load_config()
    n_ctx = int(cfg.get("n_ctx", 4096))
    ratio = float(cfg.get("context_auto_compact_ratio", 0.75))
    _history = get_history()
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
    try:
        from routers.paths import REPO_ROOT

        hist_file = REPO_ROOT / "conversation_history.json"
        hist_file.write_text(json.dumps(list(_history), indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("sync_compact_history save failed: %s", e)
    return {"ok": True, "summary": summary[:12000], "messages_remaining": len(_history)}
