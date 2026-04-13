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
from routers.paths import REPO_ROOT
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
    models_dir = Path(models_dir_raw).expanduser().resolve() if models_dir_raw else REPO_ROOT / "models"
    model_path = _rs.resolve_model_path(cfg)
    model_found = not placeholder and model_path.exists()
    available_models = [p.name for p in sorted(models_dir.glob("*.gguf"))] if models_dir.exists() else []
    hw = {}
    try:
        from first_run import detect_gpu, detect_ram_gb, recommend_model

        ram = detect_ram_gb()
        vendor, vram = detect_gpu()
        rec = recommend_model(ram, vram, vendor)
        hw = {"ram_gb": ram, "gpu_vendor": vendor, "vram_gb": vram, "tier": rec["model_tier"], "suggestion": rec["suggestion"]}
    except Exception:
        pass
    performance_mode = str(cfg.get("performance_mode", "auto") or "auto").strip()
    model_valid = bool(not placeholder and model_path.exists())
    resolved_model = model_path.name if model_found else (available_models[0] if available_models else "")

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


@router.get("/setup/models")
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


@router.get("/setup/download")
async def setup_download(url: str, filename: str = ""):
    """Stream model download progress as SSE events. url: HuggingFace direct .gguf URL."""
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
                        from first_run import DEFAULTS, detect_gpu, detect_ram_gb, recommend_model

                        ram = detect_ram_gb()
                        vendor, vram = detect_gpu()
                        rec = recommend_model(ram, vram, vendor)
                        cfg2 = {**DEFAULTS, **rec["config"]}
                    cfg2["model_filename"] = fname
                    cfg2["models_dir"] = str(models_dir)
                    _rs.CONFIG_FILE.write_text(json.dumps(cfg2, indent=2), encoding="utf-8")
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
