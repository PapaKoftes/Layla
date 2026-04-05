"""Structured tool result shapes for plan governance (optional Pydantic validation)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WriteFileToolResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False
    path: str = ""


class ApplyPatchToolResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False
    path: str = ""
    backup: str = ""


class WriteFilesBatchToolResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False
    written: list[str] = Field(default_factory=list)
    count: int = 0


class RunTestsToolResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False
    returncode: int | None = None
    passed: int = 0
    failed: int = 0
    output: str = ""
    stdout: str = ""
    runner: str = ""


def coerce_tool_result(action: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    """Return normalized dict if Pydantic accepts, else None (caller keeps heuristics)."""
    if not isinstance(raw, dict):
        return None
    try:
        if action == "write_file":
            return WriteFileToolResult.model_validate(raw).model_dump()
        if action == "apply_patch":
            return ApplyPatchToolResult.model_validate(raw).model_dump()
        if action == "write_files_batch":
            return WriteFilesBatchToolResult.model_validate(raw).model_dump()
        if action == "run_tests":
            return RunTestsToolResult.model_validate(raw).model_dump()
    except Exception:
        return None
    return None
