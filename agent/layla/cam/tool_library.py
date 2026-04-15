"""Small static tool-type catalog for planning copy (rule-based)."""

from __future__ import annotations


def list_tool_types() -> dict[str, str]:
    return {
        "flat_endmill": "General pocket/profile; prefer climb conventional per machine doc.",
        "ball_endmill": "3D surfacing; smaller stepover for finish.",
        "vbit": "Chamfer/engrave; verify tip angle and Z-zero.",
        "drill": "Plunge-only; peck for deep holes.",
    }
