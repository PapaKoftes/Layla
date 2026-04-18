#!/usr/bin/env python3
"""
Hardware summary for Layla setup (thin wrapper around agent/services/hardware_detect.py).

Prints JSON suitable for model selection on stdout with --json.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "agent"


def _ensure_psutil() -> None:
    try:
        import psutil  # noqa: F401
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "psutil"],
            cwd=str(REPO_ROOT),
            check=False,
        )


def summarize_hardware() -> dict[str, Any]:
    """Map services.hardware_detect output to the installer contract shape."""
    _ensure_psutil()
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))

    from services.hardware_detect import detect_hardware

    h = detect_hardware()
    accel = (h.get("acceleration_backend") or "none").lower()
    gpu = "nvidia" if accel == "cuda" else "none"
    vram = h.get("vram_gb")
    if gpu == "none":
        vram_gb = None
    else:
        try:
            vram_gb = float(vram) if vram is not None else None
        except (TypeError, ValueError):
            vram_gb = None

    return {
        "cpu_cores": int(h.get("cpu_cores") or os.cpu_count() or 1),
        "cpu_architecture": platform.machine() or platform.processor() or "unknown",
        "ram_gb": float(h.get("ram_gb") or 0.0),
        "gpu": gpu,
        "gpu_vram_gb": vram_gb,
        # Full detect_hardware dict for recommend_model()
        "_detect_hardware": h,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Layla hardware detection (JSON for setup).")
    parser.add_argument("--json", action="store_true", help="Print JSON summary only")
    args = parser.parse_args()

    try:
        summary = summarize_hardware()
    except Exception as e:
        print(f"[hardware_detect] ERROR: {e}", file=sys.stderr)
        return 1

    # Do not leak internal key to JSON consumers
    public = {k: v for k, v in summary.items() if not k.startswith("_")}
    if args.json:
        print(json.dumps(public, indent=2))
        return 0

    print("Hardware summary:")
    for k, v in public.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
