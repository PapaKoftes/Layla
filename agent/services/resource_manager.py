"""
Resource manager. Track CPU, RAM, GPU usage.
Adapt context size, parallel tasks, model switching based on load.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

_cache: dict[str, Any] | None = None


def get_resource_usage() -> dict[str, Any]:
    """
    Return current CPU, RAM, GPU usage.
    Cached briefly to avoid excessive psutil/nvidia-smi calls.
    """
    global _cache
    try:
        import time

        import psutil
        now = time.monotonic()
        if _cache and (now - _cache.get("_ts", 0)) < 5.0:
            return {k: v for k, v in _cache.items() if k != "_ts"}
    except Exception:
        pass

    result: dict[str, Any] = {
        "cpu_percent": 0.0,
        "ram_percent": 0.0,
        "ram_available_gb": 0.0,
        "gpu_used_mb": 0,
        "gpu_total_mb": 0,
        "gpu_percent": 0.0,
    }

    try:
        import psutil
        result["cpu_percent"] = round(psutil.cpu_percent(interval=0.1), 1)
        mem = psutil.virtual_memory()
        result["ram_percent"] = round(mem.percent, 1)
        result["ram_available_gb"] = round(mem.available / (1024**3), 2)
    except Exception:
        pass

    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            line = r.stdout.strip().split("\n")[0]
            parts = [p.strip().replace("MiB", "").replace("MB", "") for p in line.split(",")]
            if len(parts) >= 2:
                try:
                    used = int(parts[0])
                    total = int(parts[1])
                    result["gpu_used_mb"] = used
                    result["gpu_total_mb"] = total
                    result["gpu_percent"] = round(100.0 * used / total, 1) if total > 0 else 0
                except ValueError:
                    pass
    except Exception:
        pass

    _cache = {**result, "_ts": __import__("time").monotonic()}
    return result


def suggest_context_size(n_ctx_default: int = 4096) -> int:
    """
    Suggest context size based on available RAM.
    Reduces n_ctx when RAM is tight.
    """
    usage = get_resource_usage()
    ram_avail = usage.get("ram_available_gb", 8.0)
    if ram_avail < 2.0:
        return min(2048, n_ctx_default)
    if ram_avail < 4.0:
        return min(3072, n_ctx_default)
    if ram_avail < 8.0:
        return min(4096, n_ctx_default)
    return n_ctx_default


def suggest_parallel_tasks() -> int:
    """Suggest max parallel tasks (e.g. for GraphExecutor) based on load."""
    usage = get_resource_usage()
    cpu = usage.get("cpu_percent", 0)
    ram = usage.get("ram_percent", 0)
    if cpu > 90 or ram > 90:
        return 1
    if cpu > 70 or ram > 80:
        return 2
    return 3


def should_switch_model(current_model: str, task_type: str) -> bool:
    """
    True if resource pressure suggests switching to a lighter model.
    Used with model_router when under memory pressure.
    """
    usage = get_resource_usage()
    if usage.get("ram_percent", 0) > 85:
        return True
    if usage.get("gpu_percent", 0) > 95:
        return True
    return False
