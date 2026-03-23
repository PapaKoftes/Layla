"""Narrow adapter to a deterministic build/eval kernel. Stub + subprocess echo for tests.
Also provides DXFBuildRunner for real DXF output via ezdxf.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fabrication_assist.assist.schemas import BuildResult, FabricationJob, ProductResultModel

log = logging.getLogger("fabrication_assist.runner")

# Repo root (parent of `fabrication_assist` package) for subprocess PYTHONPATH
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    root = str(_REPO_ROOT)
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root if not prev else f"{root}{os.pathsep}{prev}"
    return env


@runtime_checkable
class BuildRunner(Protocol):
    """Contract for invoking an external or internal deterministic evaluator (subprocess, API, in-proc, etc.)."""

    def run_build(self, config: dict[str, Any]) -> dict[str, Any]:
        """Run one build/eval for a variant config; return ProductResult-shaped dict."""
        ...


class StubRunner:
    """Deterministic synthetic results for demos and tests — not fabrication truth."""

    def run_build(self, config: dict[str, Any]) -> dict[str, Any]:
        vid = str(config.get("id") or config.get("name") or "variant")
        seed = hashlib.sha256(vid.encode()).hexdigest()[:8]
        base = 0.5 + (int(seed[:4], 16) % 5000) / 20000.0
        raw = {
            "variant_id": vid,
            "label": config.get("label", vid),
            "score": round(min(0.99, base), 4),
            "metrics": {
                "assembly_simplicity": round(base * 0.9, 4),
                "material_efficiency": round(base * 0.85, 4),
                "machining_time_proxy": round(1.0 - base * 0.3, 4),
            },
            "notes": f"stub outcome seed={seed} (swap in a real BuildRunner)",
            "feasible": True,
        }
        return ProductResultModel.model_validate(raw).model_dump()


class SubprocessJsonRunner:
    """
    Invokes `python -m fabrication_assist.assist.echo_kernel` with a temp JSON config file.
    Validates stdout as ProductResultModel.
    """

    def __init__(self, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run_build(self, config: dict[str, Any]) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(config, tmp)
            tmp_path = Path(tmp.name)
        try:
            cmd = [
                sys.executable,
                "-m",
                "fabrication_assist.assist.echo_kernel",
                str(tmp_path),
            ]
            log.debug("subprocess runner: %s", cmd)
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=_subprocess_env(),
            )
            log.debug("subprocess returncode=%s stderr=%r", proc.returncode, proc.stderr[:500] if proc.stderr else "")
            if proc.returncode != 0:
                from fabrication_assist.assist.errors import RunnerError

                raise RunnerError(
                    f"echo_kernel exited {proc.returncode}: {proc.stderr or proc.stdout or 'no output'}",
                    variant_id=str(config.get("id")),
                    details={"stderr": proc.stderr, "stdout": proc.stdout},
                )
            line = (proc.stdout or "").strip().splitlines()
            last = line[-1] if line else ""
            try:
                data = json.loads(last)
            except json.JSONDecodeError as e:
                from fabrication_assist.assist.errors import RunnerError

                raise RunnerError(
                    f"invalid JSON from kernel: {e}",
                    variant_id=str(config.get("id")),
                    cause=e,
                    details={"stdout": proc.stdout},
                ) from e
            if not isinstance(data, dict):
                from fabrication_assist.assist.errors import RunnerError

                raise RunnerError("kernel stdout is not a JSON object", variant_id=str(config.get("id")))
            return ProductResultModel.model_validate(data).model_dump()
        except subprocess.TimeoutExpired as e:
            from fabrication_assist.assist.errors import RunnerError

            raise RunnerError(
                f"kernel timeout after {self.timeout_seconds}s",
                variant_id=str(config.get("id")),
                cause=e,
            ) from e
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

class DXFBuildRunner:
    """
    Real fabrication runner: converts FabricationJob schemas to DXF files using ezdxf.
    Handles: rectangular cuts, circular holes, slots, pockets, profiles.
    Output: .dxf file written to output_dir.
    """

    def __init__(self, output_dir: str | Path | None = None) -> None:
        if output_dir is None:
            output_dir = Path(tempfile.gettempdir()) / "layla_dxf_output"
        self.output_dir = Path(output_dir)

    def run(self, job: FabricationJob) -> BuildResult:
        """Convert a FabricationJob to a DXF file. Returns BuildResult."""
        try:
            import ezdxf
        except ImportError:
            raise RuntimeError("ezdxf required: pip install ezdxf")

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            doc = ezdxf.new(dxfversion="R2010")
            msp = doc.modelspace()

            warnings: list[str] = []

            for op in job.operations:
                op_type = (op.type or "").lower().strip()
                try:
                    if op_type == "cut_rect":
                        # Closed rectangle as LWPolyline
                        x, y, w, h = op.x, op.y, op.width, op.height
                        points = [
                            (x, y),
                            (x + w, y),
                            (x + w, y + h),
                            (x, y + h),
                        ]
                        msp.add_lwpolyline(points, close=True)

                    elif op_type == "cut_circle":
                        msp.add_circle(center=(op.x, op.y), radius=op.radius)

                    elif op_type == "cut_slot":
                        # Slot: two parallel lines + two semicircles
                        # start/end are center points of the two ends
                        if len(op.start) >= 2 and len(op.end) >= 2:
                            sx, sy = op.start[0], op.start[1]
                            ex, ey = op.end[0], op.end[1]
                            r = op.radius if op.radius > 0 else 3.0
                            # Direction vector
                            dx = ex - sx
                            dy = ey - sy
                            length = math.hypot(dx, dy) or 1.0
                            # Normal perpendicular to slot axis
                            nx = -dy / length * r
                            ny = dx / length * r
                            # Two parallel lines
                            msp.add_line((sx + nx, sy + ny), (ex + nx, ey + ny))
                            msp.add_line((sx - nx, sy - ny), (ex - nx, ey - ny))
                            # Semicircles at each end
                            angle_deg = math.degrees(math.atan2(dy, dx))
                            msp.add_arc(
                                center=(sx, sy), radius=r,
                                start_angle=angle_deg + 90,
                                end_angle=angle_deg + 270,
                            )
                            msp.add_arc(
                                center=(ex, ey), radius=r,
                                start_angle=angle_deg - 90,
                                end_angle=angle_deg + 90,
                            )
                        else:
                            warnings.append(f"cut_slot: missing start/end; skipped")

                    elif op_type == "pocket":
                        if op.path_points and len(op.path_points) >= 3:
                            pts = [(pt[0], pt[1]) for pt in op.path_points if len(pt) >= 2]
                            msp.add_lwpolyline(pts, close=True)
                            # HATCH for visual pocket indication
                            hatch = msp.add_hatch(color=7)
                            hatch.paths.add_polyline_path(pts, is_closed=True)
                        else:
                            warnings.append("pocket: path_points must have >= 3 points; skipped")

                    elif op_type == "profile":
                        if op.path_points and len(op.path_points) >= 2:
                            pts = [(pt[0], pt[1]) for pt in op.path_points if len(pt) >= 2]
                            msp.add_lwpolyline(pts, close=False)
                        else:
                            warnings.append("profile: path_points must have >= 2 points; skipped")

                    else:
                        warnings.append(f"Unknown operation type '{op.type}'; skipped")

                except Exception as op_err:
                    warnings.append(f"Operation '{op.type}' error: {op_err}")
                    log.warning("DXFBuildRunner: op '%s' failed: %s", op.type, op_err)

            safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in job.name)
            output_file = self.output_dir / f"{safe_name}.dxf"
            doc.saveas(str(output_file))

            return BuildResult(ok=True, output_path=str(output_file), warnings=warnings)

        except RuntimeError:
            raise
        except Exception as e:
            log.error("DXFBuildRunner.run failed: %s", e)
            return BuildResult(ok=False, error=str(e), warnings=[])

    def run_build(self, config: dict[str, Any]) -> dict[str, Any]:
        """Compatibility shim: wraps run() for BuildRunner protocol usage."""
        from fabrication_assist.assist.schemas import FabricationOperation
        ops_raw = config.get("operations") or []
        ops = [FabricationOperation.model_validate(o) if isinstance(o, dict) else o for o in ops_raw]
        job = FabricationJob(
            name=str(config.get("name") or config.get("id") or "job"),
            operations=ops,
            units=str(config.get("units") or "mm"),
            material=str(config.get("material") or ""),
            notes=str(config.get("notes") or ""),
        )
        result = self.run(job)
        # Return ProductResultModel-compatible dict for the protocol
        return {
            "variant_id": job.name,
            "label": job.name,
            "score": 1.0 if result.ok else 0.0,
            "metrics": {"output_path": result.output_path},
            "feasible": result.ok,
            "notes": result.error or ("; ".join(result.warnings) if result.warnings else ""),
        }
