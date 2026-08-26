"""Tests for system optimizer."""


def test_collect_metrics():
    from services.infrastructure.system_optimizer import collect_metrics
    m = collect_metrics()
    assert "cpu_percent" in m
    assert "ram_percent" in m
    assert "gpu_percent" in m
    assert "token_throughput" in m
    assert "tool_latency_ms" in m
    assert "retrieval_latency_ms" in m
    assert "timestamp" in m


def test_get_effective_config():
    from services.infrastructure.system_optimizer import get_effective_config
    # Pin performance_mode: its default "auto" resolves to a hardware TIER, and a strong GPU box
    # legitimately RAISES n_ctx above the base (correct product behavior) — which used to fail the old
    # `<= 4096` assertion only on high-tier dev machines. With a fixed mode the result is deterministic.
    cfg = get_effective_config({"n_ctx": 4096, "max_tool_calls": 5, "performance_mode": "low"})
    assert isinstance(cfg["n_ctx"], int) and cfg["n_ctx"] >= 256      # a valid context size
    assert cfg["n_ctx"] <= 4096                                        # low mode never raises above base
    assert cfg["max_tool_calls"] <= 5


def test_get_summary():
    from services.infrastructure.system_optimizer import get_summary
    s = get_summary()
    assert "metrics" in s
    assert "overrides" in s
    assert "parallel_tasks_suggested" in s


def test_get_effective_config_does_not_persist():
    """Ensure we never write to runtime_config.json."""
    import runtime_safety
    from services.infrastructure.system_optimizer import get_effective_config
    base = runtime_safety.load_config()
    before_mtime = runtime_safety.CONFIG_FILE.stat().st_mtime if runtime_safety.CONFIG_FILE.exists() else 0
    get_effective_config(base)
    after_mtime = runtime_safety.CONFIG_FILE.stat().st_mtime if runtime_safety.CONFIG_FILE.exists() else 0
    assert before_mtime == after_mtime
