"""
Resource manager for load-aware scheduling and hardware hints.
"""
from __future__ import annotations

import heapq
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import runtime_safety

PRIORITY_CHAT = 0
PRIORITY_AGENT = 1
PRIORITY_BACKGROUND = 2


@dataclass(order=True)
class _QueuedJob:
    priority: int
    created_at: float
    job_id: int = field(compare=False)


_cv = threading.Condition()
_active_jobs = 0
_queue: list[_QueuedJob] = []
_next_job_id = 1
_cache: dict[str, Any] | None = None


def _load_snapshot() -> dict:
    try:
        import psutil

        vm = psutil.virtual_memory()
        return {
            "cpu_percent": float(psutil.cpu_percent(interval=0)),
            "ram_percent": float(vm.percent),
            "available_ram_gb": float(vm.available) / (1024 ** 3),
        }
    except Exception:
        return {"cpu_percent": 0.0, "ram_percent": 0.0, "available_ram_gb": 0.0}


def get_load_snapshot() -> dict:
    return _load_snapshot()


def classify_load() -> dict:
    cfg = runtime_safety.load_config()
    snap = _load_snapshot()
    warn = float(cfg.get("warn_cpu_percent", 70))
    hard = float(cfg.get("hard_cpu_percent", 85))
    ram_hard = float(cfg.get("max_ram_percent", 90))
    overloaded = snap["cpu_percent"] >= hard or snap["ram_percent"] >= ram_hard
    warning = snap["cpu_percent"] >= warn or snap["ram_percent"] >= (ram_hard - 5)
    return {
        **snap,
        "warning": warning,
        "overloaded": overloaded,
        "warn_cpu_percent": warn,
        "hard_cpu_percent": hard,
        "hard_ram_percent": ram_hard,
    }


def should_use_dual_models() -> bool:
    cfg = runtime_safety.load_config()
    threshold = float(cfg.get("dual_model_threshold_gb", 24))
    available = _load_snapshot().get("available_ram_gb", 0.0)
    return available >= threshold


@contextmanager
def schedule_slot(priority: int = PRIORITY_AGENT):
    """Priority-aware admission gate for autonomous runs."""
    global _active_jobs, _next_job_id
    cfg = runtime_safety.load_config()
    hard_cpu = float(cfg.get("hard_cpu_percent", 85))
    hard_ram = float(cfg.get("max_ram_percent", 90))
    max_active = int(cfg.get("max_active_runs", 1) or 1)

    if priority >= PRIORITY_BACKGROUND:
        snap = _load_snapshot()
        if snap["cpu_percent"] >= hard_cpu or snap["ram_percent"] >= hard_ram:
            raise RuntimeError("system_busy")

    with _cv:
        jid = _next_job_id
        _next_job_id += 1
        entry = _QueuedJob(priority=priority, created_at=time.time(), job_id=jid)
        heapq.heappush(_queue, entry)

        while True:
            top = _queue[0] if _queue else None
            can_run = top is not None and top.job_id == jid and _active_jobs < max_active
            if can_run:
                heapq.heappop(_queue)
                _active_jobs += 1
                break
            _cv.wait(timeout=0.05)

    try:
        yield
    finally:
        with _cv:
            _active_jobs = max(0, _active_jobs - 1)
            _cv.notify_all()


def get_resource_usage() -> dict[str, Any]:
    """Return CPU/RAM/GPU usage; cached briefly to reduce overhead."""
    global _cache
    try:
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
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            line = r.stdout.strip().split("\n")[0]
            parts = [p.strip().replace("MiB", "").replace("MB", "") for p in line.split(",")]
            if len(parts) >= 2:
                used = int(parts[0])
                total = int(parts[1])
                result["gpu_used_mb"] = used
                result["gpu_total_mb"] = total
                result["gpu_percent"] = round(100.0 * used / total, 1) if total > 0 else 0
    except Exception:
        pass

    _cache = {**result, "_ts": time.monotonic()}
    return result


def suggest_context_size(n_ctx_default: int = 4096) -> int:
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
    usage = get_resource_usage()
    cpu = usage.get("cpu_percent", 0)
    ram = usage.get("ram_percent", 0)
    if cpu > 90 or ram > 90:
        return 1
    if cpu > 70 or ram > 80:
        return 2
    return 3


def should_switch_model(current_model: str, task_type: str) -> bool:
    usage = get_resource_usage()
    if usage.get("ram_percent", 0) > 85:
        return True
    if usage.get("gpu_percent", 0) > 95:
        return True
    return False

