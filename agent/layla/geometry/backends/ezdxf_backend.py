"""2D DXF generation via ezdxf."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from layla.geometry.backends.base import ExecutionContext, GeometryBackend, StepResult

if TYPE_CHECKING:
    from layla.geometry.schema import GeometryOp


class EzdxfBackend(GeometryBackend):
    name = "ezdxf"

    def supports(self, op: GeometryOp) -> bool:
        return op.op in (
            "dxf_begin",
            "dxf_line",
            "dxf_circle",
            "dxf_lwpolyline",
            "dxf_save",
        )

    def execute(self, ctx: ExecutionContext, op: GeometryOp) -> StepResult:
        try:
            import ezdxf
        except ImportError:
            return StepResult(False, "ezdxf not installed: pip install ezdxf")

        o = op.op
        if o == "dxf_begin":
            ctx.dxf_doc = ezdxf.new("R2010")
            return StepResult(True, "dxf_begin", {"units": op.units})

        if ctx.dxf_doc is None:
            return StepResult(False, "dxf_begin required before other DXF ops")

        doc = ctx.dxf_doc
        msp = doc.modelspace()

        if o == "dxf_line":
            msp.add_line((op.x1, op.y1), (op.x2, op.y2), dxfattribs={"layer": op.layer})
            return StepResult(True, "dxf_line")

        if o == "dxf_circle":
            msp.add_circle((op.cx, op.cy), op.radius, dxfattribs={"layer": op.layer})
            return StepResult(True, "dxf_circle")

        if o == "dxf_lwpolyline":
            pts = [(p[0], p[1]) for p in op.points]
            pl = msp.add_lwpolyline(pts, dxfattribs={"layer": op.layer})
            if op.closed:
                pl.close()
            return StepResult(True, "dxf_lwpolyline")

        if o == "dxf_save":
            out = _resolve_out(ctx, op.path)
            if isinstance(out, str):
                return StepResult(False, out)
            out.parent.mkdir(parents=True, exist_ok=True)
            doc.saveas(str(out))
            ctx.dxf_doc = None
            return StepResult(True, "dxf_save", {"path": str(out)})

        return StepResult(False, f"unhandled op {o}")


def _resolve_out(ctx: ExecutionContext, rel: str) -> Path | str:
    root: Path = ctx.sandbox_root
    out_dir: Path = ctx.output_dir
    p = (out_dir / rel).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return "path escapes sandbox"
    return p
