"""Abstract backend for geometry operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from layla.geometry.schema import GeometryOp


@dataclass
class StepResult:
    ok: bool
    message: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """Mutable context passed through the executor."""

    sandbox_root: Any  # Path
    output_dir: Any  # Path
    cfg: dict[str, Any]
    # ezdxf session
    dxf_doc: Any | None = None
    bridge_depth: int = 0


class GeometryBackend(ABC):
    """Pluggable kernel for a family of ops."""

    name: str = "base"

    @abstractmethod
    def supports(self, op: GeometryOp) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, ctx: ExecutionContext, op: GeometryOp) -> StepResult:
        raise NotImplementedError
