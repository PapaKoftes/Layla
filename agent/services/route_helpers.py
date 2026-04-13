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
    from services.plugin_loader import load_plugins

    _plugins_cache = load_plugins(cfg)
    _plugins_cache_ts = now
    return _plugins_cache


def coerce_setting_value(key: str, v: Any, schema: list[dict]) -> Any:
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


def sync_save_settings(body: dict) -> dict:
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
            coerced = coerce_setting_value(k, v, EDITABLE_SCHEMA)
            cfg[k] = coerced
            saved.append(k)
    _rs.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _rs.CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _rs.invalidate_config_cache()
    return {"ok": True, "saved": saved}


def sync_apply_runtime_preset(name: str) -> dict:
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
        merged[k] = coerce_setting_value(k, merged[k], EDITABLE_SCHEMA)
    _rs.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _rs.CONFIG_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    _rs.invalidate_config_cache()
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
    from services.doc_ingestion import ingest_docs

    return ingest_docs(source, label)


def sync_create_and_run_mission(body: dict) -> dict:
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


def sync_save_appearance(body: dict) -> dict:
    import json as _json

    import runtime_safety as _rs

    cfg: dict = {}
    if _rs.CONFIG_FILE.exists():
        try:
            cfg = _json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    for k in ("ui_avatar_seed", "ui_avatar_style", "ui_tts_rate", "chat_lite_mode", "ui_decision_trace_enabled", "ui_appearance_json"):
        if k in body:
            cfg[k] = body[k]
    _rs.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _rs.CONFIG_FILE.write_text(_json.dumps(cfg, indent=2), encoding="utf-8")
    _rs.invalidate_config_cache()
    _allowed = frozenset(
        {"ui_avatar_seed", "ui_avatar_style", "ui_tts_rate", "chat_lite_mode", "ui_decision_trace_enabled", "ui_appearance_json"}
    )
    return {"ok": True, "saved": [k for k in body if k in _allowed]}


def sync_compact_history() -> dict:
    """Summarize in-memory chat history when over context threshold."""
    import runtime_safety
    from services.context_manager import summarize_history
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
