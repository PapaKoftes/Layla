"""Tool implementations — domain: geometry."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {}
def gencad_generate_toolpath(
    file: str = "",
    strategy: str = "pocket",
    workspace_root: str = "",
) -> dict:
    """
    Plugin-style CAM hook: POST JSON to `geometry_external_bridge_url` (operator-hosted service).

    Expected: bridge returns JSON with at least `ok` (bool). Common fields: `output_path`, `message`, `gcode` snippet.
    Layla does not ship a default remote; configure the URL to your CAM microservice.
    """
    import runtime_safety

    cfg = runtime_safety.load_config()
    bridge = str(cfg.get("geometry_external_bridge_url") or "").strip()
    wr = (workspace_root or "").strip()
    if wr:
        p = Path(wr).expanduser().resolve()
        if not inside_sandbox(p):
            return {"ok": False, "error": "workspace_root outside sandbox"}
    if not bridge:
        return {
            "ok": False,
            "error": "gencad_not_configured",
            "hint": "Set geometry_external_bridge_url to your CAM bridge HTTPS endpoint (POST JSON).",
            "file": file,
            "strategy": strategy,
        }
    from urllib.parse import urlparse

    allow_insecure = bool(cfg.get("geometry_external_bridge_allow_insecure_localhost"))
    try:
        bu = urlparse(bridge)
        h = (bu.hostname or "").lower()
    except Exception:
        return {"ok": False, "error": "gencad_invalid_bridge_url", "bridge": bridge[:120]}
    if h in ("127.0.0.1", "localhost", "::1") and not allow_insecure:
        return {
            "ok": False,
            "error": "geometry_bridge_localhost_disabled",
            "hint": "Set geometry_external_bridge_allow_insecure_localhost to true for local dev bridges only.",
            "file": file,
            "strategy": strategy,
        }
    payload = {
        "op": "gencad_generate_toolpath",
        "file": (file or "").strip(),
        "strategy": (strategy or "pocket").strip(),
        "workspace_root": wr,
    }
    try:
        import httpx

        verify = not allow_insecure
        with httpx.Client(timeout=120.0, follow_redirects=True, verify=verify) as client:
            r = client.post(bridge, json=payload)
        txt = (r.text or "")[:4000]
        if r.status_code >= 400:
            return {
                "ok": False,
                "error": "gencad_bridge_http_error",
                "status_code": r.status_code,
                "body_preview": txt,
            }
        try:
            data = r.json()
        except Exception:
            return {
                "ok": True,
                "raw_text": txt,
                "note": "Bridge returned non-JSON body",
            }
        if isinstance(data, dict):
            if data.get("ok") is False:
                return dict(data)
            return dict(data)
        return {"ok": True, "data": data}
    except Exception as e:
        return {
            "ok": False,
            "error": "gencad_bridge_request_failed",
            "detail": str(e),
            "bridge": bridge[:120],
        }

def geometry_extract_machining_ir(dxf_path: str) -> dict:
    """
    Deterministic DXF → machining IR: features, toolpath order, coarse machine_steps preview.
    Read-only; no CAM feeds/offsets. Requires ezdxf for parsing.
    """
    from layla.geometry.machining_ir import build_machining_ir

    p = Path(dxf_path).expanduser().resolve()
    if not inside_sandbox(p):
        return {"ok": False, "error": "Path must be inside sandbox"}
    if not p.is_file():
        return {"ok": False, "error": "DXF file not found"}
    try:
        ir = build_machining_ir(str(p))
        try:
            from layla.geometry.machining_ir import validate_machining_ir_dict

            v = validate_machining_ir_dict(ir)
        except Exception:
            v = {"ok": True, "issues": [], "machine_readiness": "interpretive_preview"}
        ir["machine_readiness"] = v.get("machine_readiness", "interpretive_preview")
        ir["ir_validation"] = v
        ir["disclaimer"] = (
            "NOT_MACHINE_READY: IR is for planning and handoff; no stock, tools, feeds, or collision modeling."
        )
        return {"ok": True, **ir}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def validate_fabrication_bundle(ir_json: str = "", gcode_path: str = "") -> dict:
    """
    Deterministic validation of machining IR JSON and/or G-code file. Does not certify machine safety.
    """
    import json as _json

    from layla.geometry.machining_ir import validate_gcode_text, validate_machining_ir_dict

    out: dict = {"ok": True, "ir": None, "gcode": None}
    issues: list[str] = []
    if (ir_json or "").strip():
        try:
            ir = _json.loads(ir_json)
        except Exception as e:
            return {"ok": False, "error": f"ir_json_parse:{e}"}
        vir = validate_machining_ir_dict(ir if isinstance(ir, dict) else {})
        out["ir"] = vir
        if not vir.get("ok"):
            issues.extend(vir.get("issues") or [])
    gp = (gcode_path or "").strip()
    if gp:
        p = Path(gp).expanduser().resolve()
        if not inside_sandbox(p):
            return {"ok": False, "error": "gcode path outside sandbox"}
        if not p.is_file():
            return {"ok": False, "error": "gcode file not found"}
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        vg = validate_gcode_text(txt)
        out["gcode"] = vg
        if not vg.get("ok"):
            issues.extend(vg.get("issues") or [])
    if not out["ir"] and not out["gcode"]:
        return {
            "ok": False,
            "error": "provide ir_json and/or gcode_path",
            "machine_readiness": "not_validated",
        }
    out["ok"] = len(issues) == 0
    out["issues"] = issues[:30]
    out["machine_readiness"] = "interpretive_preview" if out["ok"] else "not_validated"
    out["disclaimer"] = "Validation is structural only — not CAM-safe or collision-checked."
    return out

def geometry_validate_program(program: str | dict) -> dict:
    """
    Validate a GeometryProgram JSON (v1) without writing files.
    program: JSON string or object with version + ops (see layla.geometry.schema).
    """
    try:
        from layla.geometry.schema import validate_program_dict

        ok, msg, p = validate_program_dict(program)
        n = len(p.ops) if p else 0
        return {"ok": ok, "message": msg, "ops_count": n}
    except Exception as e:
        return {"ok": False, "message": str(e), "ops_count": 0}

def geometry_execute_program(
    program: str | dict,
    workspace_root: str,
    output_basename: str = "geometry_out",
) -> dict:
    """
    Execute a validated GeometryProgram; writes under workspace_root/output_basename/.
    Requires ezdxf for DXF ops; optional cadquery, openscad, trimesh per op.
    """
    try:
        import runtime_safety
        from layla.geometry.executor import execute_program
        from layla.geometry.schema import parse_program

        cfg = runtime_safety.load_config()
        ws = Path(workspace_root).expanduser().resolve()
        if not inside_sandbox(ws):
            return {"ok": False, "error": "workspace_root must be inside sandbox"}
        p = parse_program(program)
        return execute_program(p, str(ws), output_basename=output_basename, cfg=cfg)
    except Exception as e:
        return {"ok": False, "error": str(e), "steps": []}

def geometry_list_frameworks() -> dict:
    """Report which optional geometry libraries / OpenSCAD CLI are available."""
    try:
        import runtime_safety
        from layla.geometry.executor import list_framework_status

        st = list_framework_status(runtime_safety.load_config())
        return {"ok": True, **st}
    except Exception as e:
        return {"ok": False, "error": str(e)}

