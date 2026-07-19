"""DATA-INTEGRITY: the writers of user-critical files must be locked + crash-atomic. Regressions here
silently LOSE data (queued approvals, all settings). Source-contract guards so a future edit can't drop
the lock / atomic-rename / fsync without a red test."""
import inspect
import sys
from pathlib import Path
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_write_pending_is_locked_and_atomic():
    from services.agent import approval_helpers as ah
    src = inspect.getsource(ah._write_pending)
    assert "pending_file_lock" in src, "the pending-approval RMW must hold the shared lock (lost-update race)"
    assert "os.replace" in src, "the pending-approval write must be atomic temp+replace (torn-read wipe)"


def test_config_writers_fsync_before_replace():
    import runtime_safety
    # The functions that actually perform the write. save_config_keys became a thin wrapper
    # over save_config_keys_detailed (which reports clamped/coerced values), so the durability
    # guarantee now lives in the latter — assert it there rather than dropping the check.
    for fn in (runtime_safety.atomic_write_config, runtime_safety.save_config_keys_detailed):
        src = inspect.getsource(fn)
        assert "os.fsync" in src, f"{fn.__name__} must fsync before os.replace (power-loss truncates config)"
        assert "os.replace" in src


def test_save_config_keys_delegates_instead_of_writing_its_own_way():
    """The wrapper must stay a wrapper. If it ever grows its own write path it would bypass
    the fsync-before-replace guarantee above while still passing that test."""
    import runtime_safety
    src = inspect.getsource(runtime_safety.save_config_keys)
    assert "save_config_keys_detailed" in src, "save_config_keys must delegate to the durable writer"
    for forbidden in ("open(", "write_text", "os.replace"):
        assert forbidden not in src, f"save_config_keys grew its own write path ({forbidden})"


def test_save_history_is_atomic():
    import main
    src = inspect.getsource(main._save_history)
    assert "os.replace" in src, "_save_history must write atomically (crash mid-write truncates it)"
