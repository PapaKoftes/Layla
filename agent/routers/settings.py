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
from services.infrastructure.route_helpers import (
    sync_apply_runtime_preset,
    sync_save_appearance,
    sync_save_settings,
)

logger = logging.getLogger("layla")
router = APIRouter(tags=["settings"])

# Security-critical config keys that a REMOTE client must never be able to change
# via POST /settings (it is on the remote allowlist). Editing these could widen
# the file sandbox, disable safe mode, or rotate/disable the remote auth itself.
# Local (loopback) operators are unaffected.
_REMOTE_PROTECTED_KEYS = frozenset({
    "sandbox_root",
    "safe_mode",
    "uncensored",
    "remote_enabled",
    "remote_api_key",
    "allow_legacy_remote_api_key",
    "remote_rate_limit_per_minute",
    "remote_allowlist",
    "allowed_hosts",
    "tunnel_enabled",
    "tunnel_token_hash",
    # Security review Findings 7/8: a remote /settings write must not be able to point
    # plugin/MCP/model loading at attacker-staged files or executables.
    "plugins_dir",
    "mcp_stdio_servers",
    "mcp_client_enabled",
    "onnx_model_path",
    "vision_model_path",
    "vision_mmproj_path",
    # audit round-5 #9: plugins_enabled is the MASTER plugin-code-execution consent gate — a remote
    # write could flip it on (its sibling safe_mode is already protected here) and the next plugin
    # (re)load would exec_module() any tools.py in plugins_dir. Protect the gate itself, plus the hook /
    # skill-venv code-execution toggles.
    "plugins_enabled",
    "agent_hooks_enabled",
    "hooks_require_allow_run",
    "skill_venv_enabled",
    # Same class as plugins_enabled: this is the consent gate for EXECUTING a skill
    # pack's third-party Python at operator privilege. A remote /settings write must
    # not be able to flip it on.
    "skill_packs_execute_enabled",
    # Approval-bypassing controls: a remote client must never be able to set these. The bypass is
    # already ignored while remote_enabled is on, but protecting the keys stops a remote write from
    # pre-arming them for when the server is later taken off the network.
    "tool_approval_bypass",
    "admin_mode",
    "admin_blocklist_override",
})


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
    # A truncated/HTML "model" must NOT read as ready — validate the GGUF, not just existence.
    model_found = not placeholder and _rs.is_valid_gguf(model_path)
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
        from services.infrastructure.setup_engine import detect_gpu, detect_ram_gb, recommend_model

        ram = detect_ram_gb()
        vendor, vram = detect_gpu()
        rec = recommend_model(ram, vram, vendor)
        hw = {"ram_gb": ram, "gpu_vendor": vendor, "vram_gb": vram, "tier": rec["model_tier"], "suggestion": rec["suggestion"]}
    except Exception:
        pass
    performance_mode = str(cfg.get("performance_mode", "auto") or "auto").strip()
    model_valid = bool(not placeholder and _rs.is_valid_gguf(model_path))
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
        # Server-side "first-run already done" truth so the UI wizard doesn't
        # re-nag on every launch (localStorage is per-browser + fragile, and the
        # CLI installer sets up a model without ever running the GUI wizard).
        "wizard_complete": bool(cfg.get("wizard_complete", False)),
    }
    if not model_valid:
        try:
            from services.infrastructure.dependency_recovery import missing_gguf_recovery

            out["recovery"] = missing_gguf_recovery(
                model_filename if not placeholder else "",
                models_dir,
                resolved_path=model_path if model_path.exists() else None,
            )
        except Exception:
            out["recovery"] = {"what_failed": "Model file missing; see MODELS.md in repo root"}
    return out


@router.get("/setup/models")
def setup_models(uncensored_first: bool = True):
    """Model catalog for the install/first-run picker — the full 42-model catalog,
    hardware-filtered and ordered with **uncensored/jailbroken models first** (the
    operator wants a model that answers everything as correctly as possible), then
    biggest-that-fits (quality). Each row carries `uncensored`/`category`/`quant` so the
    UI can badge + group them; `recommended` is the best companion-suitable uncensored
    pick for this box."""
    try:
        from install.model_selector import models_for_picker
        from services.infrastructure.setup_engine import detect_gpu, detect_ram_gb

        ram = detect_ram_gb() or 0
        _vendor, vram = detect_gpu()
        picker = models_for_picker(ram, vram or 0, uncensored_first=bool(uncensored_first))
        # shape each entry for models.js (name/key/viable/recommended/desc/ram_gb/url) while
        # keeping the richer fields (uncensored/category/quant/size/repo_id).
        catalog = []
        for e in picker["models"]:
            catalog.append({
                "key": e["filename"],
                "name": e["name"],
                "filename": e["filename"],
                "url": e.get("download_url", ""),
                "repo_id": e.get("repo_id", ""),
                "ram_gb": e["ram_required"],
                "desc": e["desc"],
                "category": e["category"],
                "size": e["size"],
                "quant": e["quant"],
                "uncensored": e["uncensored"],
                "viable": e["viable"],
                "recommended": e["recommended"],
                "recommended_coding": e.get("recommended_coding", False),
            })
        return {
            "ok": True,
            "catalog": catalog,
            "ram_gb": ram,
            "vram_gb": vram or 0,
            "recommended_key": picker["recommended"],
            "recommended_coding_key": picker.get("recommended_coding"),
            "categories": picker["categories"],
            "uncensored_first": bool(uncensored_first),
            "hardware_note": picker.get("hardware_note", ""),
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


@router.post("/setup/download-hf")
def setup_download_hf(body: dict):
    """Pull a GGUF straight from the HuggingFace Hub by repo id (BL-159).

    Body: {repo_id: "TheBloke/Model-GGUF", filename: "model.Q4_K_M.gguf"}. Downloads into the
    models dir via huggingface_hub (resumable + cached). Returns the local path; the caller then
    sets `model_filename` to the file. Validated to a plain .gguf basename (no path traversal)."""
    from pathlib import Path as _P

    body = body or {}
    repo_id = str(body.get("repo_id") or "").strip()
    filename = str(body.get("filename") or "").strip()
    if not repo_id or "/" not in repo_id or ".." in repo_id:
        return {"ok": False, "error": "repo_id required, e.g. 'TheBloke/Model-GGUF'"}
    fname = _P(filename).name.strip()
    if not fname or not fname.endswith(".gguf") or "\x00" in fname or any(ord(c) < 32 for c in fname):
        return {"ok": False, "error": "filename required, must be a plain *.gguf name"}
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return {"ok": False, "error": "huggingface_hub not installed"}
    cfg = _rs.load_config()
    md_raw = cfg.get("models_dir")
    models_dir = _P(md_raw).expanduser().resolve() if md_raw else _rs.default_models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)
    try:
        # BL-181: standard tenacity-backed retry for the flaky network fetch.
        from services.infrastructure.retry_util import retry_call
        path = retry_call(
            lambda: hf_hub_download(repo_id=repo_id, filename=fname, local_dir=str(models_dir)),
            attempts=3, label="hf_hub_download",
        )
        # Guard: the resolved file must live under the models dir.
        _P(path).resolve().relative_to(models_dir.resolve())
        return {"ok": True, "path": str(path), "filename": fname, "repo_id": repo_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/setup/download")
async def setup_download(url: str, filename: str = ""):
    """Stream model download progress as SSE events. url: HuggingFace direct .gguf URL."""
    # SSRF / local-file guard: urllib.urlretrieve honors file:// and ftp://, and
    # would happily reach localhost, cloud metadata (169.254.169.254) or LAN hosts.
    # Restrict to public http/https only before touching the URL.
    from services.safety.url_guard import is_safe_url
    if not is_safe_url(url):
        return _sse_error("URL not allowed — only public http(s) model URLs are permitted")
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
                    # Route through the resumable downloader: HTTP Range + .part.meta resume,
                    # sha256/GGUF validation, atomic rename. (Was a bare urlretrieve that
                    # restarted a multi-GB model from byte 0 on any dropped connection.)
                    from install.model_downloader import download_model

                    def _cb(written, total):
                        pct = min(100, int(written * 100 / total)) if total and total > 0 else 0
                        progress_queue.put({
                            "pct": pct,
                            "dl_mb": round(written / (1024 * 1024), 1),
                            "tot_mb": round((total or 0) / (1024 * 1024), 1),
                        })

                    res = download_model(
                        {"download_url": url, "filename": fname},
                        models_dir,
                        progress=False,
                        progress_cb=_cb,
                    )
                    if not res.get("ok"):
                        error_holder[0] = res.get("error") or "download failed"
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
                # download_model already validated (GGUF magic + size) and atomically placed
                # the file at dest — just record it as the active model.
                try:
                    cfg2 = {}
                    if _rs.CONFIG_FILE.exists():
                        try:
                            cfg2 = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    if not cfg2:
                        from services.infrastructure.setup_engine import (
                            DEFAULTS,
                            detect_gpu,
                            detect_ram_gb,
                            recommend_model,
                        )

                        ram = detect_ram_gb()
                        vendor, vram = detect_gpu()
                        rec = recommend_model(ram, vram, vendor)
                        cfg2 = {**DEFAULTS, **rec["config"]}
                    cfg2["model_filename"] = fname
                    cfg2["models_dir"] = str(models_dir)
                    _rs.atomic_write_config(cfg2)
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
    from services.safety.secret_filter import REDACTED, is_secret_key

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
        # Never disclose stored secrets (remote_api_key, *_token, *_secret, …).
        # The UI shows a masked placeholder; saving the mask is ignored on POST.
        if is_secret_key(k) and out[k] not in (None, "", [], {}):
            out[k] = REDACTED
    return out


@router.get("/settings/schema")
def get_settings_schema():
    """Return config schema for UI."""
    from config_schema import get_schema_for_api

    return get_schema_for_api()


@router.get("/settings/themes")
def get_feature_themes_route():
    """Feature areas (grouped capabilities) with their current on/off state."""
    from config_schema import get_feature_themes

    return {"ok": True, "themes": get_feature_themes(_rs.load_config())}


@router.post("/settings/themes")
async def apply_feature_theme_route(req: Request):
    """Switch a feature area on/off. Body: {key: str, enabled: bool}. Only the theme's own
    flags are written (whitelist), so this can never set an arbitrary config key."""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    key = str((body or {}).get("key") or "").strip()
    enabled = bool((body or {}).get("enabled"))
    from config_schema import feature_theme_updates
    updates = feature_theme_updates(key, enabled)
    if updates is None:
        return JSONResponse({"ok": False, "error": "unknown theme"}, status_code=400)
    try:
        # editable_only=False: some theme flags (cluster_enabled, scheduler_study_enabled) are
        # not individually in EDITABLE_SCHEMA. Safe because `updates` is the theme whitelist.
        saved = _rs.save_config_keys(updates, editable_only=False, clamp=False)
        return JSONResponse({"ok": True, "key": key, "enabled": enabled, "saved": saved})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/settings/appearance")
def get_settings_appearance():
    """Read back the UI-only appearance keys.

    Derived from the same APPEARANCE_KEYS tuple the POST writes — a second hand-copied list here is how
    a key becomes writable but not readable, so a control saves correctly and then renders blank on
    reload, which reads to the user as "it didn't save".
    """
    from services.infrastructure.route_helpers import APPEARANCE_KEYS

    c = _rs.load_config()
    return {k: c.get(k) for k in APPEARANCE_KEYS}


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
    # Drop redaction-mask placeholders so re-saving the form (which receives a
    # masked secret from GET /settings) never overwrites the real stored secret.
    if isinstance(body, dict):
        from services.safety.secret_filter import REDACTED
        body = {k: v for k, v in body.items() if v != REDACTED}

        # Remote clients may not change security-critical keys (sandbox, safe
        # mode, remote auth). Use is_direct_local (proxy-aware) — a bare host check
        # would treat tunnelled requests (which arrive from 127.0.0.1) as local.
        from services.safety.auth import is_direct_local
        socket_host = req.client.host if req.client else None
        if not is_direct_local(req.headers, socket_host):
            blocked = _REMOTE_PROTECTED_KEYS.intersection(body)
            if blocked:
                for k in blocked:
                    body.pop(k, None)
                logger.warning(
                    "settings: blocked remote write to protected keys from %s: %s",
                    socket_host, sorted(blocked),
                )
    # REQ-12: route secret-typed keys into the OS keyring instead of writing them
    # plaintext to runtime_config.json (no-op when no keyring backend exists).
    if isinstance(body, dict):
        try:
            from services.safety.secret_store import persist_secret_keys
            body, _stored = persist_secret_keys(body)
            if _stored:
                logger.info("settings: stored %d secret(s) in the OS keyring (not plaintext)", len(_stored))
        except Exception as e:
            logger.debug("keyring secret persist skipped: %s", e)
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
        import runtime_safety
        from services.infrastructure.system_doctor import run_diagnostics

        def _run():
            cfg = runtime_safety.load_config()
            out = {"ok": True, "steps": []}
            try:
                doc = run_diagnostics(include_llm=False)
                out["doctor"] = doc.get("status", "unknown")
                out["steps"].append("doctor")
            except Exception as e:
                out["steps"].append(f"doctor_failed:{e}")
            out["steps"].append("config_loaded")
            out["model_filename"] = (cfg.get("model_filename") or "").strip()
            return out

        return await asyncio.to_thread(_run)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/settings/optional_features")
def settings_optional_features():
    """Optional Python feature bundles (voice, llama_cpp, etc.) for the Features panel."""
    try:
        from services.infrastructure.dependency_recovery import get_optional_features

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
        from services.infrastructure.dependency_recovery import install_feature

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
        from services.safety.admin_checkpoint import git_revert_last_checkpoint

        return JSONResponse(git_revert_last_checkpoint(ws))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── Operator quiz + profile (Layla v3) ───────────────────────────────────────


@router.get("/operator/quiz/stage/{stage_idx}")
def operator_quiz_stage(stage_idx: int):
    """Return quiz questions for a stage (scenario-based, game-flavored)."""
    try:
        from services.personality.operator_quiz import get_stage

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
        from services.personality.operator_quiz import load_profile, save_identity_kv, score_answers

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
        from services.personality.maturity_engine import (
            all_unlocks,
            check_unlocks,
            get_milestones_status,
            get_state,
            xp_needed_for_next,
        )
        from services.personality.operator_quiz import load_profile

        prof = load_profile() or {}
        try:
            ms = get_state()
            need = xp_needed_for_next(ms.rank)
            maturity = prof.get("maturity") if isinstance(prof.get("maturity"), dict) else {}
            maturity["xp_to_next"] = int(need) if need is not None else None
            maturity["milestones"] = get_milestones_status(ms.phase)
            # Ensure phase reflects engine mapping even if older user_identity stored legacy labels.
            maturity["phase"] = str(ms.phase)
            # Unlocked abilities for the growth dashboard — the frontend (growth.js) reads
            # maturity.unlocks[{name,rank_required}] but the endpoint never populated it, so the
            # "Unlocked Abilities" panel was permanently empty. check_unlocks() already returns that shape.
            # unlocks_all carries the whole ladder so the frontend renders the locked preview
            # from the real table instead of a hardcoded duplicate that drifts out of sync.
            try:
                maturity["unlocks"] = check_unlocks({"rank": ms.rank})
                maturity["unlocks_all"] = all_unlocks(ms.rank)
            except Exception:
                maturity["unlocks"] = []
                maturity["unlocks_all"] = []
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
        from services.personality.frame_modifier import _FRAME_AXES
        from services.personality.operator_quiz import STAT_IDS, _clamp_int

        # Accept both the generic competency stats AND the FRAME voice axes (edge/nerve/signal/…)
        # so `layla stat edge 8` etc. can retune the voice.
        known = tuple(STAT_IDS) + _FRAME_AXES
        if stat not in known:
            return JSONResponse({"ok": False, "error": "unknown_stat", "known": list(known)}, status_code=400)
        v = _clamp_int(value, 1, 10, 5)
        set_user_identity(f"stat_{stat}", str(v))
        return JSONResponse({"ok": True, "stat": stat, "value": v})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
