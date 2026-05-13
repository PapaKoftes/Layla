"""
Tests for the extracted layla.scheduler package.
Run from agent/: pytest tests/test_scheduler_registry.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_create_scheduler_returns_scheduler_with_default_config():
    """create_scheduler({}) returns a BackgroundScheduler with expected jobs."""
    from layla.scheduler import create_scheduler

    sched = create_scheduler({})
    jobs = {j.id: j for j in sched.get_jobs() if j.id}

    # Core jobs that are always registered
    assert "mission_worker" in jobs
    assert "background_reflection" in jobs
    assert "background_codex" in jobs
    assert "background_memory_consolidation" in jobs
    assert "background_initiative" in jobs
    assert "background_memory_cleanup" in jobs
    assert "repo_reindex" in jobs

    # Study-gated jobs (scheduler_study_enabled defaults True)
    assert "intelligence" in jobs
    assert "rl_preference_update" in jobs


def test_create_scheduler_study_disabled():
    """When scheduler_study_enabled=False, study-gated jobs are not registered."""
    from layla.scheduler import create_scheduler

    sched = create_scheduler({"scheduler_study_enabled": False})
    job_ids = {j.id for j in sched.get_jobs() if j.id}

    assert "mission_worker" in job_ids
    assert "background_reflection" in job_ids
    # Study-gated jobs should be absent
    assert "intelligence" not in job_ids
    assert "rl_preference_update" not in job_ids


def test_get_scheduler_returns_last_created():
    """get_scheduler() returns the scheduler from the last create_scheduler call."""
    from layla.scheduler import create_scheduler, get_scheduler

    sched = create_scheduler({})
    assert get_scheduler() is sched


def test_activity_record_and_check():
    """record_activity() updates the timestamp so is_active_window returns True."""
    from layla.scheduler.activity import is_active_window, record_activity

    record_activity()
    assert is_active_window(max_idle_minutes=1)


def test_activity_idle_window():
    """is_active_window returns False when idle time exceeds the threshold."""
    import time as _time

    from layla.scheduler import activity

    # Simulate old activity
    activity._last_activity_ts = _time.time() - 7200  # 2 hours ago
    assert not activity.is_active_window(max_idle_minutes=60)
    # Restore
    activity.record_activity()


def test_game_detection_with_mock_psutil():
    """is_game_running() detects a known game process via mocked psutil."""
    mock_proc = MagicMock()
    mock_proc.info = {"name": "Valorant.exe"}

    mock_psutil = MagicMock()
    mock_psutil.process_iter.return_value = [mock_proc]
    mock_psutil.NoSuchProcess = Exception
    mock_psutil.AccessDenied = Exception

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        from layla.scheduler.activity import is_game_running

        assert is_game_running() is True


def test_game_detection_no_game_with_mock_psutil():
    """is_game_running() returns False when no game processes are found."""
    mock_proc = MagicMock()
    mock_proc.info = {"name": "python.exe"}

    mock_psutil = MagicMock()
    mock_psutil.process_iter.return_value = [mock_proc]
    mock_psutil.NoSuchProcess = Exception
    mock_psutil.AccessDenied = Exception

    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        from layla.scheduler.activity import is_game_running

        assert is_game_running() is False


def test_game_detection_no_psutil():
    """is_game_running() gracefully returns False when psutil is unavailable."""
    from layla.scheduler.activity import is_game_running

    # Patch sys.modules so `import psutil` inside the function raises ImportError
    with patch.dict("sys.modules", {"psutil": None}):
        assert is_game_running() is False


def test_scheduler_skip_processes_is_frozenset():
    """SCHEDULER_SKIP_PROCESSES is exported and is a frozenset."""
    from layla.scheduler.activity import SCHEDULER_SKIP_PROCESSES

    assert isinstance(SCHEDULER_SKIP_PROCESSES, frozenset)
    assert "valorant" in SCHEDULER_SKIP_PROCESSES
    assert "steam" in SCHEDULER_SKIP_PROCESSES


def test_custom_mission_worker_interval():
    """Mission worker interval respects config key."""
    from layla.scheduler import create_scheduler

    sched = create_scheduler({"mission_worker_interval_minutes": 5})
    jobs = {j.id: j for j in sched.get_jobs() if j.id}
    assert "mission_worker" in jobs
    # The trigger should have 5-minute interval
    trigger = jobs["mission_worker"].trigger
    assert trigger.interval.total_seconds() == 5 * 60
