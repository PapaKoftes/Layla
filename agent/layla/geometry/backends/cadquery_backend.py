"""3D solids via cadquery (optional). Uses subprocess to isolate OCC crashes."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from layla.geometry.backends.base import ExecutionContext, GeometryBackend, StepResult

if TYPE_CHECKING:
    from layla.geometry.schema import GeometryOp


class CadqueryBackend(GeometryBackend):
    name = "cadquery"

    def supports(self, op: GeometryOp) -> bool:
        return op.op == "cq_box"

    def execute(self, ctx: ExecutionContext, op: GeometryOp) -> StepResult:
        if op.op != "cq_box":
            return StepResult(False, "internal")
        enabled = ctx.cfg.get("geometry_frameworks_enabled") or {}
        if isinstance(enabled, list):
            enabled = {k: True for k in enabled}
        if not enabled.get("cadquery", True):
            return StepResult(False, "cadquery disabled in geometry_frameworks_enabled")

        out = _resolve(ctx, op.path)
        if isinstance(out, str):
            return StepResult(False, out)
        out.parent.mkdir(parents=True, exist_ok=True)
        suffix = out.suffix.lower()
        if suffix not in (".step", ".stl", ".stp"):
            return StepResult(False, "cq_box path must end with .step, .stl, or .stp")

        dx, dy, dz = float(op.dx), float(op.dy), float(op.dz)
        out_path = str(out).replace("\\", "\\\\")

        script = textwrap.dedent(
            f"""
            import sys
            from pathlib import Path
            try:
                import cadquery as cq
            except ImportError:
                print("cadquery not installed: pip install cadquery", file=sys.stderr)
                sys.exit(2)
            w = cq.Workplane("XY").box({dx}, {dy}, {dz})
            p = Path(r"{out_path}")
            p.parent.mkdir(parents=True, exist_ok=True)
            cq.exporters.export(w, str(p))
            print("ok")
            """
        )

        timeout = float(ctx.cfg.get("geometry_subprocess_timeout_seconds") or 120.0)
        try:
            r = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(ctx.sandbox_root),
            )
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "cadquery subprocess failed")[:2000]
                return StepResult(False, err)
            return StepResult(True, "cq_box", {"path": str(out)})
        except subprocess.TimeoutExpired:
            return StepResult(False, "cadquery subprocess timeout")
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
