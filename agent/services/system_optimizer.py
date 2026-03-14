"""
System optimizer. Monitors runtime performance and adjusts parameters automatically.
Collects CPU, RAM, GPU, token throughput, tool latency, retrieval latency.
Applies adaptive runtime overrides (context size, parallel tasks, retrieval depth).
Changes are runtime-only; never persist to runtime_config.json.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("layla")

# Keys we may override at runtime (never persist)
_RUNTIME_OVERRIDE_KEYS = frozenset({
    "n_ctx", "max_tool_calls", "research_max_tool_calls",
    "semantic_k", "knowledge_chunks_k", "knowledge_max_bytes",
})


def collect_metrics() -> dict[str, Any]:
    """
    Collect current system metrics.
    Returns: cpu_percent, ram_percent, gpu_percent, token_throughput, tool_latency_ms, retrieval_latency_ms.
    """
    result: dict[str, Any] = {
        "cpu_percent": 0.0,
        "ram_percent": 0.0,
        "gpu_percent": 0.0,
        "token_throughput": 0.0,
        "tool_latency_ms": 0.0,
        "retrieval_latency_ms": 0.0,
        "agent_decision_ms": 0.0,
        "timestamp": time.time(),
    }

    try:
        from services.resource_manager import get_resource_usage
        usage = get_resource_usage()
        result["cpu_percent"] = usage.get("cpu_percent", 0.0)
        result["ram_percent"] = usage.get("ram_percent", 0.0)
        result["gpu_percent"] = usage.get("gpu_percent", 0.0)
    except Exception as e:
        logger.debug("system_optimizer resource_usage: %s", e)

    try:
        from services.performance_monitor import get_stats, get_tool_latency_stats
        tok = get_stats("token_throughput", window_sec=60)
        if tok.get("count", 0) > 0:
            result["token_throughput"] = tok.get("mean", 0)

        tool = get_tool_latency_stats(tool_name=None, window_sec=60)
        if tool.get("count", 0) > 0:
            result["tool_latency_ms"] = tool.get("mean_ms", 0)

        ret = get_stats("retrieval_latency_ms", window_sec=60)
        if ret.get("count", 0) > 0:
            result["retrieval_latency_ms"] = ret.get("mean", 0)

        agent_dec = get_stats("agent_decision_ms", window_sec=60)
        if agent_dec.get("count", 0) > 0:
            result["agent_decision_ms"] = agent_dec.get("mean", 0)
    except Exception as e:
        logger.debug("system_optimizer performance_monitor: %s", e)

    return result


def get_effective_config(base_cfg: dict | None = None) -> dict:
    """
    Return config with runtime overrides applied. Never writes to runtime_config.json.
    Priority: base config (from runtime_safety.load_config) + adaptive overrides.
    """
    if base_cfg is None:
        try:
            import runtime_safety
            base_cfg = runtime_safety.load_config()
        except Exception:
            base_cfg = {}

    cfg = dict(base_cfg)
    metrics = collect_metrics()
    cpu = metrics.get("cpu_percent", 0)
    ram = metrics.get("ram_percent", 0)
    gpu = metrics.get("gpu_percent", 0)

    # Under pressure: reduce context, tool calls, retrieval depth
    n_ctx_base = int(cfg.get("n_ctx", 4096))
    max_tool_base = int(cfg.get("max_tool_calls", 5))
    research_max_base = int(cfg.get("research_max_tool_calls", 20))
    semantic_k_base = int(cfg.get("semantic_k", 5))
    chunks_k_base = int(cfg.get("knowledge_chunks_k", 5))
    knowledge_max_base = int(cfg.get("knowledge_max_bytes", 4000))

    if cpu > 90 or ram > 90 or gpu > 95:
        cfg["n_ctx"] = min(2048, n_ctx_base)
        cfg["max_tool_calls"] = min(3, max_tool_base)
        cfg["research_max_tool_calls"] = min(10, research_max_base)
        cfg["semantic_k"] = min(3, semantic_k_base)
        cfg["knowledge_chunks_k"] = min(3, chunks_k_base)
        cfg["knowledge_max_bytes"] = min(2000, knowledge_max_base)
    elif cpu > 75 or ram > 80 or gpu > 85:
        cfg["n_ctx"] = min(3072, n_ctx_base)
        cfg["max_tool_calls"] = min(4, max_tool_base)
        cfg["research_max_tool_calls"] = min(15, research_max_base)
        cfg["semantic_k"] = min(4, semantic_k_base)
        cfg["knowledge_chunks_k"] = min(4, chunks_k_base)
        cfg["knowledge_max_bytes"] = min(3000, knowledge_max_base)
    # else: use base values as-is

    return cfg


def suggest_parallel_tasks() -> int:
    """Suggest max parallel tasks based on current load. Uses resource_manager."""
    try:
        from services.resource_manager import suggest_parallel_tasks as _suggest
        return _suggest()
    except Exception:
        return 2


def suggest_context_size(n_ctx_default: int = 4096) -> int:
    """Suggest context size based on available RAM. Uses resource_manager."""
    try:
        from services.resource_manager import suggest_context_size as _suggest
        return _suggest(n_ctx_default)
    except Exception:
        return n_ctx_default


def should_switch_model(current_model: str, task_type: str) -> bool:
    """True if resource pressure suggests switching to a lighter model."""
    try:
        from services.resource_manager import should_switch_model as _should
        return _should(current_model, task_type)
    except Exception:
        return False


def get_summary() -> dict[str, Any]:
    """
    Get optimizer summary for health/doctor endpoints.
    Includes metrics (token throughput, tool latency, retrieval latency, agent decision time),
    recent values, and any active runtime overrides.
    """
    metrics = collect_metrics()
    performance: dict[str, Any] = {}
    try:
        from services.performance_monitor import get_stats, get_tool_latency_stats
        for name, key in [
            ("token_throughput", "token_throughput"),
            ("retrieval_latency_ms", "retrieval_latency_ms"),
            ("agent_decision_ms", "agent_decision_ms"),
        ]:
            s = get_stats(key, window_sec=60)
            if s.get("count", 0) > 0:
                performance[key] = {"mean": s["mean"], "p95": s["p95"], "count": s["count"]}
        tool_stats = get_tool_latency_stats(tool_name=None, window_sec=60)
        if tool_stats.get("count", 0) > 0:
            performance["tool_latency_ms"] = {
                "mean_ms": tool_stats["mean_ms"],
                "p95_ms": tool_stats["p95_ms"],
                "count": tool_stats["count"],
            }
    except Exception:
        pass

    try:
        import runtime_safety
        base = runtime_safety.load_config()
    except Exception:
        base = {}
    effective = get_effective_config(base)

    # Include stored model benchmarks from ~/.layla/benchmarks.json
    model_benchmarks: dict[str, Any] = {}
    try:
        from services.model_benchmark import get_all_benchmarks
        stored = get_all_benchmarks()
        if stored:
            model_benchmarks = dict(stored)
    except Exception:
        pass

    overrides: dict[str, Any] = {}
    for k in _RUNTIME_OVERRIDE_KEYS:
        if k in effective and effective.get(k) != base.get(k):
            overrides[k] = {"base": base.get(k), "effective": effective[k]}

    return {
        "metrics": metrics,
        "performance": performance,
        "model_benchmarks": model_benchmarks,
        "overrides": overrides,
        "parallel_tasks_suggested": suggest_parallel_tasks(),
    }
