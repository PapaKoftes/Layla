from __future__ import annotations


def test_model_outcomes_roundtrip():
    from layla.memory.db import get_model_success_rates, log_model_outcome

    # Insert a few samples for one model/task.
    for _ in range(6):
        log_model_outcome(
            model_used="a.gguf",
            task_type="coding",
            success=1,
            score=0.9,
            latency_ms=123.0,
        )
    stats = get_model_success_rates(min_count=5)
    assert "a.gguf" in stats
    assert "coding" in stats["a.gguf"]
    row = stats["a.gguf"]["coding"]
    assert row["count"] >= 5
    assert row["success_rate"] >= 0.99

