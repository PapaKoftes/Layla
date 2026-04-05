"""worker_os_limits: POSIX rlimits and helpers (mocked where OS-specific)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_apply_posix_rlimit_skipped_when_disabled():
    from services.worker_os_limits import apply_background_worker_posix_rlimits

    apply_background_worker_posix_rlimits({"background_worker_rlimits_enabled": False})


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX")
def test_apply_posix_rlimit_calls_setrlimit():
    from services import worker_os_limits as wo

    cfg = {"background_worker_rlimits_enabled": True, "background_worker_rlimit_as_bytes": 1_000_000}
    with patch("resource.setrlimit") as mock_rl:
        wo.apply_background_worker_posix_rlimits(cfg)
        mock_rl.assert_called_once()
        args = mock_rl.call_args[0]
        import resource

        assert args[0] == resource.RLIMIT_AS
        assert args[1] == (1_000_000, 1_000_000)


def test_attach_windows_job_skipped_on_posix():
    from services.worker_os_limits import attach_windows_job_memory_limit

    proc = MagicMock()
    attach_windows_job_memory_limit(
        proc,
        {
            "background_worker_windows_job_limits_enabled": True,
            "background_worker_windows_job_memory_mb": 512,
        },
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object is Windows-only")
def test_attach_windows_job_smoke_skipped_if_no_handle():
    from services.worker_os_limits import attach_windows_job_memory_limit

    proc = MagicMock(spec=["pid"])
    proc._handle = None
    attach_windows_job_memory_limit(
        proc,
        {
            "background_worker_windows_job_limits_enabled": True,
            "background_worker_windows_job_memory_mb": 128,
        },
    )
