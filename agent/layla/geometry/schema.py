"""Versioned GeometryProgram schema: CAD-like op sequences (v1)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

# --- Operation models (discriminated by `op`) ---


class DxfBegin(BaseModel):
    op: Literal["dxf_begin"] = "dxf_begin"
    units: Literal["mm", "in"] = "mm"


class DxfLine(BaseModel):
    op: Literal["dxf_line"] = "dxf_line"
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "0"


class DxfCircle(BaseModel):
    op: Literal["dxf_circle"] = "dxf_circle"
    cx: float
    cy: float
    radius: float
    layer: str = "0"


class DxfLwPolyline(BaseModel):
    op: Literal["dxf_lwpolyline"] = "dxf_lwpolyline"
    points: list[tuple[float, float]] = Field(min_length=2)
    layer: str = "0"
    closed: bool = False


class DxfSave(BaseModel):
    op: Literal["dxf_save"] = "dxf_save"
    path: str = Field(description="Relative path under workspace / output dir")


class CqBox(BaseModel):
    """Extruded box via cadquery (optional dep). Exports STEP or STL."""

    op: Literal["cq_box"] = "cq_box"
    dx: float = Field(gt=0)
    dy: float = Field(gt=0)
    dz: float = Field(gt=0)
    path: str = Field(description="Output path .step or .stl")


class OpenScadRender(BaseModel):
    """Write OpenSCAD source and invoke openscad CLI."""

    op: Literal["openscad_render"] = "openscad_render"
    scad_source: str
    output_path: str = Field(description="Relative path, typically .stl")


class MeshInfo(BaseModel):
    """Load mesh with trimesh and return bbox / vertex count."""

    op: Literal["mesh_info"] = "mesh_info"
    path: str


class CadBridgeFetch(BaseModel):
    """POST to allowlisted geometry bridge; response must be JSON GeometryProgram or {program: {...}}."""

    op: Literal["cad_bridge_fetch"] = "cad_bridge_fetch"
    path: str = ""
    body: dict[str, Any] = Field(default_factory=dict)


GeometryOp = Annotated[
    Union[
        DxfBegin,
        DxfLine,
        DxfCircle,
        DxfLwPolyline,
        DxfSave,
        CqBox,
        OpenScadRender,
        MeshInfo,
        CadBridgeFetch,
    ],
    Field(discriminator="op"),
]


class GeometryProgram(BaseModel):
    """Root program: ordered ops executed by the executor."""

    version: Literal["1"] = "1"
    ops: list[GeometryOp]


_adapter: TypeAdapter[GeometryProgram] | None = None


def _get_adapter() -> TypeAdapter[GeometryProgram]:
    global _adapter
    if _adapter is None:
        _adapter = TypeAdapter(GeometryProgram)
    return _adapter


def parse_program(data: dict[str, Any] | str) -> GeometryProgram:
    """Parse and validate a geometry program."""
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError("program must be a JSON object or string")
    return _get_adapter().validate_python(data)


def validate_program_dict(data: dict[str, Any] | str) -> tuple[bool, str, GeometryProgram | None]:
    """Return (ok, message, program_or_none)."""
    try:
        p = parse_program(data)
        return True, "ok", p
    except Exception as e:
        return False, str(e), None
