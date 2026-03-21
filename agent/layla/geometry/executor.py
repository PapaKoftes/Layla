"""Execute GeometryProgram ops with sandbox and optional backends."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import runtime_safety
from layla.geometry.backends.base import ExecutionContext, StepResult
from layla.geometry.backends.cadquery_backend import CadqueryBackend
from layla.geometry.backends.ezdxf_backend import EzdxfBackend
from layla.geometry.backends.mesh_backend import MeshBackend
from layla.geometry.backends.openscad_backend import OpenScadBackend
from layla.geometry.bridges.http_cad_bridge import fetch_program
from layla.geometry.schema import GeometryOp, GeometryProgram, parse_program

MAX_BRIDGE_DEPTH = 3


def _sandbox_root(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("sandbox_root") or str(Path.home())).expanduser().resolve()


def _inside_sandbox(path: Path, sand: Path) -> bool:
    try:
        path.resolve().relative_to(sand.resolve())
        return True
    except ValueError:
        return False


def _backends():
    return [
        EzdxfBackend(),
        CadqueryBackend(),
        OpenScadBackend(),
        MeshBackend(),
    ]


def execute_program(
    program: GeometryProgram,
    workspace_root: str,
    output_basename: str = "geometry_out",
    cfg: dict[str, Any] | None = None,
    *,
    _depth: int = 0,
) -> dict[str, Any]:
    """
    Run all ops. Writes under workspace_root/output_basename/.
    Returns {ok, steps, artifacts, error?, output_dir}.
    """
    cfg = dict(cfg or runtime_safety.load_config())
    sand = _sandbox_root(cfg)
    root = Path(workspace_root).expanduser().resolve()
    if not _inside_sandbox(root, sand):
        return {"ok": False, "error": "workspace_root must be inside sandbox_root", "steps": [], "artifacts": []}

    out_dir = (root / output_basename).resolve()
    if not _inside_sandbox(out_dir, sand):
        return {"ok": False, "error": "output path escapes sandbox", "steps": [], "artifacts": []}
    out_dir.mkdir(parents=True, exist_ok=True)

    ctx = ExecutionContext(
        sandbox_root=sand,
        output_dir=out_dir,
        cfg=cfg,
        bridge_depth=_depth,
    )
    backends = _backends()
    steps: list[dict[str, Any]] = []
    artifacts: list[str] = []

    def run_one(op: GeometryOp) -> StepResult:
        for b in backends:
            if b.supports(op):
                return b.execute(ctx, op)
        return StepResult(False, f"no backend for op={op.op}")

    for op in program.ops:
        if op.op == "cad_bridge_fetch":
            if _depth >= MAX_BRIDGE_DEPTH:
                steps.append({"op": "cad_bridge_fetch", "ok": False, "error": "max bridge depth"})
                continue
            fr = fetch_program(cfg, path=getattr(op, "path", "") or "", body=getattr(op, "body", None) or {})
            if not fr.get("ok"):
                steps.append({"op": "cad_bridge_fetch", "ok": False, "error": fr.get("error")})
                continue
            try:
                nested = parse_program(fr["program"])
            except Exception as e:
                steps.append({"op": "cad_bridge_fetch", "ok": False, "error": str(e)})
                continue
            sub = execute_program(
                nested,
                str(root),
                output_basename,
                cfg,
                _depth=_depth + 1,
            )
            steps.append({"op": "cad_bridge_fetch", "ok": sub.get("ok"), "nested_steps": len(sub.get("steps", []))})
            steps.extend(sub.get("steps", []))
            artifacts.extend(sub.get("artifacts", []))
            continue

        res = run_one(op)
        entry = {"op": op.op, "ok": res.ok, "message": res.message}
        if res.artifacts:
            entry["artifacts"] = res.artifacts
            pth = res.artifacts.get("path")
            if pth:
                artifacts.append(str(pth))
        if not res.ok:
            entry["error"] = res.message
        steps.append(entry)

    ok = not any(s.get("ok") is False for s in steps)

    return {"ok": ok, "steps": steps, "artifacts": artifacts, "output_dir": str(out_dir)}


def list_framework_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Import / CLI probes for geometry frameworks."""
    cfg = dict(cfg or runtime_safety.load_config())
    enabled = cfg.get("geometry_frameworks_enabled") or {}
    if isinstance(enabled, list):
        enabled = {k: True for k in enabled}

    out: dict[str, Any] = {"geometry_frameworks_enabled": enabled, "modules": {}, "openscad": {}}

    for name, mod in [("ezdxf", "ezdxf"), ("cadquery", "cadquery"), ("trimesh", "trimesh")]:
        try:
            __import__(mod)
            out["modules"][name] = "available"
        except Exception as e:
            out["modules"][name] = f"missing: {e!s}"[:200]

    exe = (cfg.get("openscad_executable") or "openscad").strip() or "openscad"
    out["openscad"]["executable"] = exe
    out["openscad"]["found"] = shutil.which(exe) is not None

    return out
