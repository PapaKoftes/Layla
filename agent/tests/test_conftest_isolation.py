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


def test_config_cache_reset_is_self_contained():
    """Set the sentinel, run the SAME reset the autouse fixture runs, verify it cleared — in ONE test,
    so it detects a broken reset regardless of collection order (audit round-4 #1: the old populate→verify
    PAIR passed vacuously when the verifier ran without its populator, since _config_cache defaults None)."""
    import runtime_safety as rs
    from tests.conftest import reset_volatile_module_state

    rs._config_cache = {"sentinel_value": "test_conftest_isolation_marker", "max_tool_calls": 99}
    rs._config_last_check = 1e15  # far future — would never expire on its own
    reset_volatile_module_state()
    assert rs._config_cache is None, "_reset_volatile_module_state did not clear runtime_safety._config_cache"


def test_learning_rate_limiter_reset_is_self_contained():
    import time

    import layla.memory.learnings as lm
    from tests.conftest import reset_volatile_module_state

    now = time.time()
    for _ in range(19):
        lm._recent_learning_ts.append(now)
    assert len(lm._recent_learning_ts) == 19
    reset_volatile_module_state()
    assert len(lm._recent_learning_ts) == 0, "_reset_volatile_module_state did not clear _recent_learning_ts"
