"""Narrow adapter to a deterministic build/eval kernel. Stub + subprocess echo for tests."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fabrication_assist.assist.schemas import ProductResultModel

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
