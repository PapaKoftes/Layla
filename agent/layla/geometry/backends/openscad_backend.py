"""OpenSCAD CLI backend."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from layla.geometry.backends.base import ExecutionContext, GeometryBackend, StepResult

if TYPE_CHECKING:
    from layla.geometry.schema import GeometryOp


class OpenScadBackend(GeometryBackend):
    name = "openscad"

    def supports(self, op: GeometryOp) -> bool:
        return op.op == "openscad_render"

    def execute(self, ctx: ExecutionContext, op: GeometryOp) -> StepResult:
        if op.op != "openscad_render":
            return StepResult(False, "internal")
        enabled = ctx.cfg.get("geometry_frameworks_enabled") or {}
        if isinstance(enabled, list):
            enabled = {k: True for k in enabled}
        if not enabled.get("openscad", True):
            return StepResult(False, "openscad disabled in geometry_frameworks_enabled")

        exe = (ctx.cfg.get("openscad_executable") or "openscad").strip() or "openscad"
        out = _resolve(ctx, op.output_path)
        if isinstance(out, str):
            return StepResult(False, out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(ctx.output_dir) / "_layla_temp.scad"
        tmp.write_text(op.scad_source, encoding="utf-8")
        timeout = float(ctx.cfg.get("geometry_subprocess_timeout_seconds") or 120.0)
        try:
            proc = subprocess.run(
                [exe, "-o", str(out), str(tmp)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(ctx.output_dir),
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "openscad failed")[:2000]
                return StepResult(False, err)
            return StepResult(True, "openscad_render", {"path": str(out)})
        except FileNotFoundError:
            return StepResult(False, f"OpenSCAD executable not found: {exe}")
        except subprocess.TimeoutExpired:
            return StepResult(False, "openscad timeout")
        except Exception as e:
            return StepResult(False, str(e))


def _resolve(ctx: ExecutionContext, rel: str) -> Path | str:
    root = Path(ctx.sandbox_root).resolve()
    p = (Path(ctx.output_dir) / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return "path escapes sandbox"
    return p
