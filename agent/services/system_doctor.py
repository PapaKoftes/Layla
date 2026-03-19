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


def run_diagnostics(include_llm: bool = False) -> dict[str, Any]:
    """
    Run full system diagnostics. Returns structured report.
    include_llm: if True, may load LLM (slow); else skip.
    """
    report: dict[str, Any] = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok": sys.version_info >= (3, 11),
        "checks": {},
        "status": "ok",
    }
    errors: list[str] = []

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
        import runtime_safety
        import urllib.error
        import urllib.parse
        import urllib.request

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
    lines = [
        "",
        "  LAYLA - System Doctor",
        "  -------------------------",
        f"  Python: {report.get('python_version', '?')} {'[OK]' if report.get('python_ok') else '[!!] (need 3.11+)'}",
        "",
    ]
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
