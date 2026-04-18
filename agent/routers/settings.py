"""Setup wizard, settings GET/POST, appearance."""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

import runtime_safety as _rs
from services.route_helpers import (
    sync_apply_runtime_preset,
    sync_save_appearance,
    sync_save_settings,
)

logger = logging.getLogger("layla")
router = APIRouter(tags=["settings"])


@router.get("/setup_status")
def setup_status():
    """Returns readiness state for the UI first-run overlay."""
    config_exists = _rs.CONFIG_FILE.exists()
    cfg = {}
    try:
        cfg = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8")) if config_exists else {}
    except Exception:
        pass
    model_filename = cfg.get("model_filename", "")
    placeholder = not model_filename or model_filename == "your-model.gguf"
    models_dir_raw = cfg.get("models_dir")
    models_dir = Path(models_dir_raw).expanduser().resolve() if models_dir_raw else _rs.default_models_dir()
    model_path = _rs.resolve_model_path(cfg)
    model_found = not placeholder and model_path.exists()
    _search_roots = _rs.model_search_roots(cfg)
    models_search_roots = [str(r) for r in _search_roots]
    _seen_gguf: set[str] = set()
    available_models: list[str] = []
    for root in _search_roots:
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.gguf")):
            if p.name not in _seen_gguf:
                _seen_gguf.add(p.name)
                available_models.append(p.name)
    available_models.sort()
    hw = {}
    try:
        from services.setup_engine import detect_gpu, detect_ram_gb, recommend_model

        ram = detect_ram_gb()
        vendor, vram = detect_gpu()
        rec = recommend_model(ram, vram, vendor)
        hw = {"ram_gb": ram, "gpu_vendor": vendor, "vram_gb": vram, "tier": rec["model_tier"], "suggestion": rec["suggestion"]}
    except Exception:
        pass
    performance_mode = str(cfg.get("performance_mode", "auto") or "auto").strip()
    model_valid = bool(not placeholder and model_path.exists())
    resolved_model = model_path.name if model_found else (available_models[0] if available_models else "")

    sandbox_raw = (cfg.get("sandbox_root") or "").strip()
    sandbox_root = ""
    if sandbox_raw:
        try:
            sandbox_root = str(Path(sandbox_raw).expanduser().resolve())
        except Exception:
            sandbox_root = sandbox_raw

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

    models_dir_str = str(models_dir)

    out = {
        "ready": model_found,
        "model_valid": model_valid,
        "config_exists": config_exists,
        "model_filename": model_filename if not placeholder else "",
        "model_found": model_found,
        "resolved_model": resolved_model,
        "model_route_hint": model_route_hint,
        "available_models": available_models,
        "models_search_roots": models_search_roots,
        "models_dir": models_dir_str,
        "sandbox_root": sandbox_root,
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


@router.get("/setup/models")
def setup_models():
    """Return the model catalog for the first-run picker."""
    try:
        from services.setup_engine import MODELS_CATALOG as _MODELS_CATALOG
        from services.setup_engine import detect_gpu, detect_ram_gb, recommend_model

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
            is_rec = bool(viable and (m.get("key") in preferred) and not rec_matched)
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


def _sse_error(msg: str) -> StreamingResponse:
    async def _err():
        yield f"data: {json.dumps({'error': msg})}\n\n"

    return StreamingResponse(
        _err(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/setup/download")
async def setup_download(url: str, filename: str = ""):
    """Stream model download progress as SSE events. url: HuggingFace direct .gguf URL."""
    cfg = _rs.load_config()
    models_dir_raw = cfg.get("models_dir")
    models_dir = Path(models_dir_raw).expanduser().resolve() if models_dir_raw else _rs.default_models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)
    raw = (filename or url.rstrip("/").split("/")[-1] or "").strip()
    fname = Path(raw).name.strip()
    if not fname or fname in (".", ".."):
        return _sse_error("Invalid filename")
    if "\x00" in fname or any(ord(c) < 32 for c in fname):
        return _sse_error("Invalid filename")
    if not fname.endswith(".gguf"):
        fname += ".gguf"
    dest = models_dir / fname
    try:
        md_res = models_dir.resolve()
        dest_res = dest.resolve()
        dest_res.relative_to(md_res)
    except (OSError, ValueError):
        return _sse_error("Invalid destination path")

    async def _stream():
        try:
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
                try:
                    cfg2 = {}
                    if _rs.CONFIG_FILE.exists():
                        try:
                            cfg2 = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    if not cfg2:
                        from services.setup_engine import DEFAULTS, detect_gpu, detect_ram_gb, recommend_model

                        ram = detect_ram_gb()
                        vendor, vram = detect_gpu()
                        rec = recommend_model(ram, vram, vendor)
                        cfg2 = {**DEFAULTS, **rec["config"]}
                    cfg2["model_filename"] = fname
                    cfg2["models_dir"] = str(models_dir)
                    _rs.CONFIG_FILE.write_text(json.dumps(cfg2, indent=2), encoding="utf-8")
                    _rs.invalidate_config_cache()
                except Exception as cfg_err:
                    logger.warning("setup_download: config save failed: %s", cfg_err)
                yield f"data: {json.dumps({'pct': 100, 'done': True, 'filename': fname})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/settings")
def get_settings():
    """Return all editable settings. Missing keys use schema defaults."""
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


@router.get("/settings/schema")
def get_settings_schema():
    """Return config schema for UI."""
    from config_schema import get_schema_for_api

    return get_schema_for_api()


@router.get("/settings/appearance")
def get_settings_appearance():
    c = _rs.load_config()
    keys = ("ui_avatar_seed", "ui_avatar_style", "ui_tts_rate", "chat_lite_mode", "ui_decision_trace_enabled")
    return {k: c.get(k) for k in keys}


@router.post("/settings/appearance")
async def save_settings_appearance(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    try:
        return await asyncio.to_thread(sync_save_appearance, body if isinstance(body, dict) else {})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/settings")
async def save_settings(req: Request):
    """Update runtime_config.json."""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    try:
        return await asyncio.to_thread(sync_save_settings, body)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/settings/preset")
async def apply_runtime_preset(req: Request):
    """Merge a named preset into runtime_config.json."""
    from config_schema import SETTINGS_PRESETS

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
        return await asyncio.to_thread(sync_apply_runtime_preset, name)
    except ValueError as ve:
        if str(ve) == "unknown_preset":
            return JSONResponse({"ok": False, "error": "unknown_preset"}, status_code=400)
        return JSONResponse({"ok": False, "error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/setup/auto")
async def setup_auto():
    """Run idempotent auto-setup (doctor, config sanity) after the character creator / wizard."""
    try:
        from services.auto_setup import run_auto_setup

        return await asyncio.to_thread(run_auto_setup)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/settings/optional_features")
def settings_optional_features():
    """Optional Python feature bundles (voice, llama_cpp, etc.) for the Features panel."""
    try:
        from services.dependency_recovery import get_optional_features

        return JSONResponse({"ok": True, "features": get_optional_features()})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/settings/install_feature")
async def settings_install_feature(req: Request):
    """Allowlisted pip install for one feature id (explicit operator action)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    fid = str((body or {}).get("feature_id") or "").strip()
    if not fid:
        return JSONResponse({"ok": False, "error": "feature_id required"}, status_code=400)
    try:
        from services.dependency_recovery import install_feature

        return JSONResponse(install_feature(fid))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/settings/git_undo_checkpoint")
async def settings_git_undo_checkpoint(req: Request):
    """Revert the last Layla admin checkpoint commit in the given workspace (git)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    ws = str((body or {}).get("workspace_root") or "").strip()
    if not ws:
        return JSONResponse({"ok": False, "error": "workspace_root required"}, status_code=400)
    try:
        from services.admin_checkpoint import git_revert_last_checkpoint

        return JSONResponse(git_revert_last_checkpoint(ws))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── Operator quiz + profile (Layla v3) ───────────────────────────────────────


@router.get("/operator/quiz/stage/{stage_idx}")
def operator_quiz_stage(stage_idx: int):
    """Return quiz questions for a stage (scenario-based, game-flavored)."""
    try:
        from services.operator_quiz import get_stage

        return JSONResponse(get_stage(stage_idx))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/operator/quiz/submit")
async def operator_quiz_submit(req: Request):
    """
    Submit quiz answers and optionally persist the resulting identity snapshot.

    Body:
      - answers: [{question_id, option_id}, ...]
      - finalize: bool (default false). If true, stores stats/prefs in user_identity.
    """
    try:
        body = await req.json()
    except Exception:
        body = {}
    answers = (body or {}).get("answers") or []
    finalize = bool((body or {}).get("finalize") or False)
    if not isinstance(answers, list):
        return JSONResponse({"ok": False, "error": "answers must be a list"}, status_code=400)
    try:
        from services.operator_quiz import load_profile, save_identity_kv, score_answers

        seed = (load_profile() or {}).get("raw") or {}
        preview, kv = score_answers(answers, seed_identity=seed)
        if finalize:
            save_identity_kv(kv)
        return JSONResponse({"ok": True, "preview": preview, "stored": finalize})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/operator/profile")
def operator_profile():
    """Return the current operator profile (stats, maturity seed, prefs) from user_identity."""
    try:
        from services.maturity_engine import get_milestones_status, get_state, xp_needed_for_next
        from services.operator_quiz import load_profile

        prof = load_profile() or {}
        try:
            ms = get_state()
            need = xp_needed_for_next(ms.rank)
            maturity = prof.get("maturity") if isinstance(prof.get("maturity"), dict) else {}
            maturity["xp_to_next"] = int(need) if need is not None else None
            maturity["milestones"] = get_milestones_status(ms.phase)
            # Ensure phase reflects engine mapping even if older user_identity stored legacy labels.
            maturity["phase"] = str(ms.phase)
            prof["maturity"] = maturity
        except Exception:
            pass
        return JSONResponse(prof)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/operator/profile/stat")
async def operator_profile_set_stat(req: Request):
    """Manual override for one stat (1-10). Body: {stat: technical|creative|..., value: 1..10}."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    stat = str((body or {}).get("stat") or "").strip().lower()
    value = (body or {}).get("value")
    if not stat:
        return JSONResponse({"ok": False, "error": "stat required"}, status_code=400)
    try:
        from layla.memory.db import set_user_identity
        from services.operator_quiz import STAT_IDS, _clamp_int

        if stat not in STAT_IDS:
            return JSONResponse({"ok": False, "error": "unknown_stat", "known": list(STAT_IDS)}, status_code=400)
        v = _clamp_int(value, 1, 10, 5)
        set_user_identity(f"stat_{stat}", str(v))
        return JSONResponse({"ok": True, "stat": stat, "value": v})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
