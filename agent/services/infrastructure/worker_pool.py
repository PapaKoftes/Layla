"""
Advisory worker limits for parallel I/O (tool batches, task graphs).

Local llama_cpp inference stays serialized in ``llm_gateway``; this module only
caps how many concurrent **tool** threads or graph nodes run on the host.
"""
from __future__ import annotations

from typing import Any


def hardware_class(hw: dict[str, Any] | None) -> str:
    """Map detect_hardware() output to potato | mid | strong | workstation."""
    try:
        from services.hardware_detect import hardware_class as _hwc

        return _hwc(hw)
    except Exception:
        if not hw:
            return "mid"
        tier = str(hw.get("machine_tier") or "tier2")
        if tier == "tier1":
            return "potato"
        if tier == "tier2":
            return "mid"
        if tier == "tier3":
            return "strong"
        return "workstation"


def max_parallel_workers(cfg: dict[str, Any] | None) -> int:
    """
    Upper bound for parallel workers (tool batch, task-graph waves, etc.).
    """
    c = cfg or {}
    if not c.get("worker_pool_enabled", True):
        return 1
    mx = int(c.get("max_workers", 0) or 0)
    if mx > 0:
        return max(1, min(mx, 16))
    try:
        from services.hardware_detect import detect_hardware

        cls = hardware_class(detect_hardware())
    except Exception:
        cls = "mid"
    if cls == "potato":
        return 1
    if cls == "mid":
        return 2
    if cls == "strong":
        return 4
    return 6


def tool_batch_max_workers(cfg: dict[str, Any] | None, batch_len: int) -> int:
    """Cap ThreadPoolExecutor size for concurrent read-only tools."""
    if batch_len <= 1:
        return 1
    return max(1, min(batch_len, max_parallel_workers(cfg)))
