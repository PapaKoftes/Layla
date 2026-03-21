"""Mesh inspection via trimesh (optional)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from layla.geometry.backends.base import ExecutionContext, GeometryBackend, StepResult

if TYPE_CHECKING:
    from layla.geometry.schema import GeometryOp


class MeshBackend(GeometryBackend):
    name = "trimesh"

    def supports(self, op: GeometryOp) -> bool:
        return op.op == "mesh_info"

    def execute(self, ctx: ExecutionContext, op: GeometryOp) -> StepResult:
        if op.op != "mesh_info":
            return StepResult(False, "internal")
        enabled = ctx.cfg.get("geometry_frameworks_enabled") or {}
        if isinstance(enabled, list):
            enabled = {k: True for k in enabled}
        if not enabled.get("trimesh", True):
            return StepResult(False, "trimesh disabled in geometry_frameworks_enabled")

        try:
            import trimesh
        except ImportError:
            return StepResult(False, "trimesh not installed: pip install trimesh")

        p = _resolve(ctx, op.path)
        if isinstance(p, str):
            return StepResult(False, p)
        if not p.exists():
            return StepResult(False, "mesh file not found")

        try:
            loaded = trimesh.load(str(p), force="scene")
            if isinstance(loaded, trimesh.Scene):
                geoms = list(loaded.geometry.values())
                if not geoms:
                    return StepResult(False, "empty mesh scene")
                m = trimesh.util.concatenate(geoms)
            else:
                m = loaded
            bbox = m.bounds.tolist() if hasattr(m, "bounds") else []
            verts = int(len(m.vertices)) if hasattr(m, "vertices") else 0
            return StepResult(True, "mesh_info", {"bbox": bbox, "vertices": verts, "path": str(p)})
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
