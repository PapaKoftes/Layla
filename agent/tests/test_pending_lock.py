"""Tests that concurrent pending.json writes don't corrupt the file."""
import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_concurrent_pending_writes_do_not_corrupt(tmp_path):
    """
    Simulate many concurrent threads writing to pending.json.
    Result should be a valid JSON list, not corrupted.
    """
    import main  # noqa: F401 (sets up _pending_file_lock)
    from main import _read_pending, _write_pending_list

    pending_file = tmp_path / "pending.json"

    # Patch PENDING_FILE and GOV_PATH to use tmp_path
    with (
        patch("main.PENDING_FILE", pending_file),
        patch("main.GOV_PATH", tmp_path),
    ):
        # Write initial data
        _write_pending_list([])

        errors = []

        def _write(idx):
            try:
                existing = _read_pending()
                existing.append({"id": idx})
                _write_pending_list(existing)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent writes: {errors}"

        # File should be valid JSON list
        content = pending_file.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, list)


def test_pending_lock_exists():
    """Verify that _pending_file_lock is a threading.Lock."""
    import threading

    import main
    lock = main._pending_file_lock
    assert isinstance(lock, type(threading.Lock()))
