"""
System doctor. Full system diagnostics.
Run via: python layla.py doctor or GET /doctor when server is up.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_DIR = Path(__file__).resolve().parent.parent


def python_support_status() -> dict[str, Any]:
    """
    Match startup policy in main.py (see setup/python_compat.check_python_compatibility):
    3.11–3.12 production-supported; 3.13+ allowed only when stack self-check passes (supported_unofficial).
    """
    try:
        from setup.python_compat import BLOCKER_CHROMADB_INCOMPATIBLE, check_python_compatibility

        r = check_python_compatibility()
    except Exception as e:
        logger.debug("python_support_status compat import failed: %s", e)
        return {
            "python_ok": False,
            "supported_runtime": False,
            "unsupported_reason": f"Compatibility check failed: {e}",
        }

    status = r.get("status")
    issues = r.get("issues") or []
    blockers = list(r.get("critical_blockers") or [])
    safe_mode = bool(r.get("safe_mode"))

    if status == "unsupported":
        return {
            "python_ok": False,
            "supported_runtime": False,
            "unsupported_reason": "; ".join(issues) if issues else "Unsupported Python/runtime.",
            "critical_blockers": blockers,
            "compatibility_safe_mode": safe_mode,
            "semantic_memory_disabled": False,
        }
    if status == "supported":
        return {
            "python_ok": True,
            "supported_runtime": True,
            "unsupported_reason": None,
            "critical_blockers": [],
            "compatibility_safe_mode": False,
            "semantic_memory_disabled": False,
        }

    semantic_off = BLOCKER_CHROMADB_INCOMPATIBLE in blockers
    # supported_unofficial — full stack OK vs degraded (Chroma off)
    detail = (
        f"Python {r.get('version')} — CONDITIONALLY supported "
        f"(critical_blockers={blockers}, safe_mode={safe_mode}); "
        "prefer Python 3.11 or 3.12 for production."
        if semantic_off or safe_mode
        else (
            f"Python {r.get('version')} is best-effort (3.13+ dependency stack OK); "
            "prefer Python 3.11 or 3.12 for production."
        )
    )
    return {
        "python_ok": True,
        "supported_runtime": False,
        "unsupported_reason": detail,
        "critical_blockers": blockers,
        "compatibility_safe_mode": safe_mode,
        "semantic_memory_disabled": semantic_off,
    }


def run_capability_probe(
    *,
    browser_launch: bool = False,
    voice_micro: bool = False,
) -> dict[str, Any]:
    """
    Optional subsystem checks for operators / deep verification.
    Keeps imports cheap unless browser_launch or voice_micro requests heavier work.
    """
    out: dict[str, Any] = {"status": "ok", "checks": {}, "warnings": []}

    # Inference backend + GPU vs config
    try:
        import runtime_safety
        from services.inference_router import effective_inference_backend, inference_backend_uses_local_gguf

        cfg = runtime_safety.load_config()
        backend = effective_inference_backend(cfg)
        n_gpu = int(cfg.get("n_gpu_layers", 0) or 0)
        out["checks"]["inference"] = {
            "backend": backend,
            "n_gpu_layers": n_gpu,
            "local_gguf": inference_backend_uses_local_gguf(cfg),
        }
        try:
            from services.hardware_detect import detect_hardware

            hw = detect_hardware()
            accel = hw.get("acceleration_backend") or "none"
            has_gpu = accel in ("cuda", "rocm") or (hw.get("vram_gb") or 0) > 0
            if has_gpu and backend == "llama_cpp" and n_gpu == 0:
                out["warnings"].append(
                    "GPU detected but n_gpu_layers is 0; local llama_cpp will use CPU unless you raise n_gpu_layers."
                )
            if not has_gpu and backend == "llama_cpp" and n_gpu != 0:
                out["warnings"].append(
                    "n_gpu_layers is non-zero but no CUDA/ROCm GPU was detected; build may fall back or fail."
                )
        except Exception as e:
            out["checks"]["inference"]["hardware_note"] = str(e)
    except Exception as e:
        out["checks"]["inference"] = {"error": str(e)}
        out["status"] = "warnings"

    # llama_cpp import (no model load)
    try:
        import llama_cpp  # noqa: F401

        ver = getattr(llama_cpp, "__version__", None)
        out["checks"]["llama_cpp"] = {"import_ok": True, "version": str(ver) if ver is not None else "unknown"}
    except Exception as e:
        out["checks"]["llama_cpp"] = {"import_ok": False, "error": str(e)}
        out["warnings"].append("llama_cpp import failed — local GGUF inference unavailable.")
        out["status"] = "warnings"

    # Playwright
    try:
        from playwright.sync_api import sync_playwright

        out["checks"]["playwright"] = {"import_ok": True, "chromium_launch_ok": None}
        if browser_launch:
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                out["checks"]["playwright"]["chromium_launch_ok"] = True
            except Exception as e:
                out["checks"]["playwright"]["chromium_launch_ok"] = False
                out["checks"]["playwright"]["chromium_error"] = str(e)
                out["warnings"].append(
                    "Playwright Chromium failed to launch — run: python -m playwright install chromium"
                )
                out["status"] = "warnings"
    except ImportError as e:
        out["checks"]["playwright"] = {"import_ok": False, "error": str(e)}
        out["status"] = "warnings"
    except Exception as e:
        out["checks"]["playwright"] = {"import_ok": False, "error": str(e)}
        out["status"] = "warnings"

    # Voice stacks (import-only unless voice_micro)
    fw_ok = False
    try:
        import faster_whisper  # noqa: F401

        fw_ok = True
    except Exception as e:
        out["checks"]["faster_whisper"] = {"import_ok": False, "error": str(e)}
    else:
        out["checks"]["faster_whisper"] = {"import_ok": True, "micro_transcribe_ok": None}
    ko_ok = False
    try:
        import kokoro_onnx  # noqa: F401

        ko_ok = True
    except Exception as e:
        out["checks"]["kokoro_onnx"] = {"import_ok": False, "error": str(e)}
    else:
        out["checks"]["kokoro_onnx"] = {"import_ok": True, "micro_speak_ok": None}

    if voice_micro and fw_ok:
        try:
            from services.stt import transcribe_bytes

            # Minimal silent WAV (valid header); may return '' without loading heavy model if bytes invalid
            silent_wav = (
                b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
                b"\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
            )
            text = transcribe_bytes(silent_wav)
            out["checks"]["faster_whisper"]["micro_transcribe_ok"] = isinstance(text, str)
            if not text and out["checks"]["faster_whisper"]["micro_transcribe_ok"]:
                out["checks"]["faster_whisper"]["micro_transcribe_note"] = "empty transcript (expected for silence or if model not loaded)"
        except Exception as e:
            out["checks"]["faster_whisper"]["micro_transcribe_ok"] = False
            out["checks"]["faster_whisper"]["micro_transcribe_error"] = str(e)
            out["warnings"].append(f"faster_whisper micro transcribe failed: {e}")
            out["status"] = "warnings"

    if voice_micro and ko_ok:
        try:
            from services.tts import speak_to_bytes

            raw = speak_to_bytes("ok")
            out["checks"]["kokoro_onnx"]["micro_speak_ok"] = bool(raw and len(raw) > 100)
            if not out["checks"]["kokoro_onnx"]["micro_speak_ok"]:
                out["warnings"].append("kokoro TTS returned empty or very short audio")
                out["status"] = "warnings"
        except Exception as e:
            out["checks"]["kokoro_onnx"]["micro_speak_ok"] = False
            out["checks"]["kokoro_onnx"]["micro_speak_error"] = str(e)
            out["warnings"].append(f"kokoro micro speak failed: {e}")
            out["status"] = "warnings"

    if out["warnings"]:
        out["status"] = "warnings" if out["status"] == "ok" else out["status"]
    return out


def run_diagnostics(include_llm: bool = False) -> dict[str, Any]:
    """
    Run full system diagnostics. Returns structured report.
    include_llm: if True, may load LLM (slow); else skip.
    """
    py = python_support_status()
    report: dict[str, Any] = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok": py["python_ok"],
        "supported_runtime": py["supported_runtime"],
        "unsupported_reason": py.get("unsupported_reason"),
        "critical_blockers": py.get("critical_blockers") or [],
        "compatibility_safe_mode": py.get("compatibility_safe_mode", False),
        "semantic_memory_disabled": py.get("semantic_memory_disabled", False),
        "checks": {},
        "status": "ok",
    }
    errors: list[str] = []
    if not py["python_ok"]:
        errors.append(py.get("unsupported_reason") or "Python version not acceptable for this runtime")
        report["status"] = "warnings"

    # Dependencies
    deps = ["fastapi", "uvicorn", "chromadb", "sentence_transformers", "llama_cpp", "psutil"]
    missing = []
    dep_map = {"llama_cpp": "llama-cpp-python", "sentence_transformers": "sentence-transformers"}
    for d in deps:
        try:
            __import__(d)
        except ImportError:
            missing.append(dep_map.get(d, d))
        except Exception:
            missing.append(dep_map.get(d, d))
    report["checks"]["dependencies"] = {"ok": len(missing) == 0, "missing": missing}
    if missing:
        errors.append(f"Missing: {', '.join(missing)}")

    # Model directory (from config, else repo models)
    try:
        cfg = json.loads((AGENT_DIR / "runtime_config.json").read_text(encoding="utf-8-sig"))
    except Exception:
        cfg = {}
    models_dir_raw = cfg.get("models_dir")
    models_dir = Path(models_dir_raw).expanduser().resolve() if models_dir_raw else REPO_ROOT / "models"
    report["checks"]["model_dir"] = {
        "path": str(models_dir),
        "exists": models_dir.exists(),
        "gguf_count": len(list(models_dir.glob("*.gguf"))) if models_dir.exists() else 0,
    }
    if not models_dir.exists():
        errors.append("models/ directory missing")

    # Config
    cfg_path = AGENT_DIR / "runtime_config.json"
    report["checks"]["config"] = {"exists": cfg_path.exists(), "path": str(cfg_path)}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            report["checks"]["config"]["model_filename"] = cfg.get("model_filename", "")
        except Exception as e:
            report["checks"]["config"]["error"] = str(e)

    # GPU detection
    try:
        from services.hardware_detect import detect_hardware
        hw = detect_hardware()
        report["checks"]["hardware"] = {
            "cpu_cores": hw.get("cpu_cores"),
            "ram_gb": hw.get("ram_gb"),
            "gpu_name": hw.get("gpu_name", "none"),
            "vram_gb": hw.get("vram_gb", 0),
            "acceleration": hw.get("acceleration_backend", "none"),
        }
    except Exception as e:
        report["checks"]["hardware"] = {"error": str(e)}

    # Database
    db_path = REPO_ROOT / "layla.db"
    report["checks"]["database"] = {
        "path": str(db_path),
        "exists": db_path.exists(),
    }
    if db_path.exists():
        try:
            import sqlite3
            with sqlite3.connect(str(db_path)) as c:
                r = c.execute("SELECT COUNT(*) FROM learnings").fetchone()
                report["checks"]["database"]["learnings_count"] = r[0] if r else 0
        except Exception as e:
            report["checks"]["database"]["error"] = str(e)

    # Plugins
    try:
        import runtime_safety
        from services.plugin_loader import load_plugins
        cfg = runtime_safety.load_config()
        pl = load_plugins(cfg)
        report["checks"]["plugins"] = {
            "skills_added": pl.get("skills_added", 0),
            "tools_added": pl.get("tools_added", 0),
            "capabilities_added": pl.get("capabilities_added", 0),
            "errors": pl.get("errors", []),
        }
    except Exception as e:
        report["checks"]["plugins"] = {"error": str(e)}

    # Port 8000
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(("127.0.0.1", 8000))
        s.close()
        report["checks"]["port_8000"] = {"in_use": result == 0}
    except Exception as e:
        report["checks"]["port_8000"] = {"error": str(e)}

    # Optional OpenClaw / sidecar gateway reachability (config-gated)
    try:
        import urllib.error
        import urllib.parse
        import urllib.request

        import runtime_safety

        _cfg = runtime_safety.load_config()
        gw_raw = (_cfg.get("openclaw_gateway_url") or "").strip()
        if gw_raw:
            parsed = urllib.parse.urlparse(gw_raw)
            if parsed.scheme not in ("http", "https"):
                report["checks"]["openclaw_gateway"] = {
                    "ok": False,
                    "error": "openclaw_gateway_url must be http(s)",
                }
            else:
                check_url = (
                    gw_raw.rstrip("/") + "/health"
                    if parsed.path in ("", "/")
                    else gw_raw
                )
                try:
                    req = urllib.request.Request(check_url, method="GET")
                    with urllib.request.urlopen(req, timeout=3) as r:
                        report["checks"]["openclaw_gateway"] = {
                            "ok": 200 <= (r.status or 0) < 500,
                            "url": check_url,
                            "http_status": r.status,
                        }
                except urllib.error.HTTPError as e:
                    report["checks"]["openclaw_gateway"] = {
                        "ok": e.code in (401, 403, 404),
                        "url": check_url,
                        "http_status": e.code,
                        "note": "reachable but non-200",
                    }
                except Exception as e:
                    report["checks"]["openclaw_gateway"] = {
                        "ok": False,
                        "url": check_url,
                        "error": str(e),
                    }
        else:
            report["checks"]["openclaw_gateway"] = {
                "skipped": True,
                "reason": "openclaw_gateway_url not set",
            }
    except Exception as e:
        report["checks"]["openclaw_gateway"] = {"error": str(e)}

    # Skills registry
    try:
        from layla.skills.registry import SKILLS
        report["checks"]["skills"] = {"count": len(SKILLS)}
    except Exception as e:
        report["checks"]["skills"] = {"error": str(e)}

    # System optimizer
    try:
        from services.system_optimizer import get_summary
        report["system_optimizer"] = get_summary()
    except Exception as e:
        report["system_optimizer"] = {"error": str(e)}

    # Tools registry
    try:
        from layla.tools.registry import TOOLS
        report["checks"]["tools"] = {"count": len(TOOLS)}
    except Exception as e:
        report["checks"]["tools"] = {"error": str(e)}

    if errors:
        report["status"] = "warnings"
        report["errors"] = errors
    return report


def format_diagnostics(report: dict[str, Any]) -> str:
    """Format diagnostics report as human-readable text."""
    prod = report.get("supported_runtime")
    py_note = "[OK]"
    if not report.get("python_ok"):
        py_note = "[!!] (not runnable under main.py policy)"
    elif prod is False:
        py_note = "[~~] (best-effort; not production-supported)"
    lines = [
        "",
        "  LAYLA - System Doctor",
        "  -------------------------",
        f"  Python: {report.get('python_version', '?')} {py_note}",
        "",
    ]
    if report.get("critical_blockers"):
        lines.append(f"  critical_blockers: {report['critical_blockers']}")
        lines.append("")
    if report.get("semantic_memory_disabled"):
        lines.append("  Semantic memory (Chroma): disabled for this interpreter / wheels.")
        lines.append("")
    if report.get("unsupported_reason"):
        lines.append(f"  Note: {report['unsupported_reason']}")
        lines.append("")
    for name, check in report.get("checks", {}).items():
        ok = check.get("ok", check.get("exists", "error" not in check))
        sym = "[OK]" if ok else "[!!]"
        lines.append(f"  {sym} {name}: {check}")
    if report.get("errors"):
        lines.append("")
        lines.append("  Issues:")
        for e in report["errors"]:
            lines.append(f"    - {e}")
    lines.append("")
    return "\n".join(lines)
