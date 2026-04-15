from __future__ import annotations

from services.worker_pool import hardware_class, max_parallel_workers, tool_batch_max_workers


def test_hardware_class_tiers():
    assert hardware_class({"machine_tier": "tier1"}) == "potato"
    assert hardware_class({"machine_tier": "tier3"}) == "strong"


def test_max_parallel_workers():
    assert max_parallel_workers({"worker_pool_enabled": False}) == 1
    assert tool_batch_max_workers({"worker_pool_enabled": True, "max_workers": 3}, 10) <= 3
