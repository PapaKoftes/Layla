from services.outcome_evaluation import evaluate_outcome, evaluate_outcome_structured


def test_evaluate_outcome_all_ok():
    state = {
        "status": "finished",
        "steps": [
            {"action": "read_file", "result": {"ok": True, "path": "a.py"}},
            {"action": "reason", "result": "done"},
        ],
    }
    out = evaluate_outcome(state)
    assert out["success"] is True
    assert out["tool_fail"] == 0
    assert out["score"] > 0.5


def test_evaluate_outcome_with_failures():
    state = {
        "status": "finished",
        "steps": [
            {"action": "shell", "result": {"ok": False, "error": "nope"}},
        ],
    }
    out = evaluate_outcome(state)
    assert out["tool_fail"] >= 1
    assert out["issues"]
    assert out["success"] is False
    assert out["score"] < 0.85


def test_evaluate_outcome_structured_has_metrics_and_reason():
    state = {
        "status": "finished",
        "start_time": __import__("time").time() - 2.0,
        "steps": [
            {"action": "read_file", "result": {"ok": True, "path": "a.py"}},
            {"action": "reason", "result": "done"},
        ],
    }
    s = evaluate_outcome_structured(state)
    assert s["success"] is True
    assert s["reason"] == "ok"
    assert "metrics" in s and s["metrics"]["wall_time_seconds"] >= 0
    assert "cost_score" in s
    assert "confidence" in s
    assert "improvement" in s


def test_evaluate_outcome_structured_refused():
    state = {
        "status": "finished",
        "refused": True,
        "steps": [{"action": "reason", "result": "no"}],
    }
    s = evaluate_outcome_structured(state)
    assert s["success"] is False
    assert s["reason"] == "refused"


def test_strategy_stats_record_and_read(tmp_path, monkeypatch):
    import layla.memory.db as dbm
    import layla.memory.migrations as mig

    monkeypatch.setattr(dbm, "_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(mig, "_MIGRATED", False)
    if hasattr(dbm, "_MIGRATED"):
        monkeypatch.setattr(dbm, "_MIGRATED", False)

    from layla.memory.strategy_stats import get_strategy_stat_row, record_strategy_stat

    record_strategy_stat("task-a", "morrigan", success=True)
    record_strategy_stat("task-a", "morrigan", success=False)
    row = get_strategy_stat_row("task-a", "morrigan")
    assert row is not None
    assert row["success_count"] == 1
    assert row["fail_count"] == 1
