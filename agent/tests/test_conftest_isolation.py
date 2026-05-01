"""
test_conftest_isolation.py — Verify that conftest.py safety fixtures actually work.

If these tests fail it means the test infrastructure itself is broken and
every other test result is unreliable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_layla_db_is_not_real_db():
    """The active DB path must be inside a pytest tmp dir, never the operator's real DB."""
    import layla.memory.db as db_mod

    db_path = Path(str(db_mod._DB_PATH))
    real_db_candidates = [
        AGENT_DIR / "layla.db",
        AGENT_DIR.parent / "layla.db",
        Path.home() / "layla-workspace" / "layla.db",
        Path.home() / ".layla" / "layla.db",
    ]
    for candidate in real_db_candidates:
        assert db_path != candidate.resolve(), (
            f"Tests are writing to the real DB at {candidate}! "
            f"Active _DB_PATH={db_path}"
        )

    # Must be inside a temp directory
    tmp_markers = ["tmp", "Temp", "pytest", "layla_data"]
    assert any(m in str(db_path) for m in tmp_markers), (
        f"DB path doesn't look like a temp path: {db_path}"
    )


def test_layla_data_dir_env_is_set():
    """LAYLA_DATA_DIR env var must point to a temp dir (not a real data dir)."""
    data_dir = os.environ.get("LAYLA_DATA_DIR", "")
    assert data_dir, "LAYLA_DATA_DIR not set — conftest session fixture may have failed"
    tmp_markers = ["tmp", "Temp", "pytest", "layla_data"]
    assert any(m in data_dir for m in tmp_markers), (
        f"LAYLA_DATA_DIR doesn't look like a temp path: {data_dir}"
    )


def test_config_cache_reset_between_tests_first():
    """Populate runtime_safety config cache — next test verifies it was cleared."""
    import runtime_safety as rs
    rs._config_cache = {"sentinel_value": "test_conftest_isolation_marker", "max_tool_calls": 99}
    rs._config_last_check = 1e15  # Far future — would never expire on its own
    # This fixture ensures the NEXT test sees a cleared cache.
    # (The autouse _reset_volatile_module_state fixture runs before the next test.)


def test_config_cache_was_cleared_by_autouse_fixture():
    """Verify _reset_volatile_module_state cleared the cache set by the previous test."""
    import runtime_safety as rs
    # If the autouse fixture ran correctly, _config_cache is None and
    # the sentinel we set previously is gone.
    assert rs._config_cache is None or rs._config_cache.get("sentinel_value") != "test_conftest_isolation_marker", (
        "_config_cache was NOT reset between tests — "
        "_reset_volatile_module_state autouse fixture is broken"
    )


def test_learning_rate_limiter_reset_between_tests_first():
    """Fill the rate-limiter deque — next test verifies it was cleared."""
    import layla.memory.learnings as lm
    # Simulate a nearly-full rate limiter (19 of 20 slots used)
    import time
    now = time.time()
    for _ in range(19):
        lm._recent_learning_ts.append(now)
    assert len(lm._recent_learning_ts) == 19


def test_learning_rate_limiter_was_cleared():
    """Verify _reset_volatile_module_state cleared the deque set by the previous test."""
    import layla.memory.learnings as lm
    assert len(lm._recent_learning_ts) == 0, (
        f"_recent_learning_ts was NOT cleared between tests "
        f"(has {len(lm._recent_learning_ts)} entries) — "
        "_reset_volatile_module_state autouse fixture is broken"
    )
