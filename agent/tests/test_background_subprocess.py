"""background_subprocess spawn/cancel helpers and enqueue subprocess flag."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_cancel_worker_calls_terminate_then_kill():
    from services import background_subprocess as bs

    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 4242
    bs.cancel_worker(proc, grace_seconds=0.05)
    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()


def test_cancel_worker_noop_when_already_dead():
    from services import background_subprocess as bs

    proc = MagicMock()
    proc.poll.return_value = 0
    bs.cancel_worker(proc, grace_seconds=0.05)
    proc.terminate.assert_not_called()
    proc.kill.assert_not_called()


def test_compute_background_job_sandbox_rejects_outside_when_forced(monkeypatch, tmp_path):
    import routers.agent as ra
    import runtime_safety
    from layla.tools.registry import set_effective_sandbox

    inner = tmp_path / "in"
    inner.mkdir()
    evil = tmp_path.parent / "evil_outside_sandbox_xyz"
    evil.mkdir(exist_ok=True)
    set_effective_sandbox(str(tmp_path))
    try:
        cfg = {"sandbox_root": str(tmp_path), "background_worker_force_sandbox_only": True}
        monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
        err, _sand = ra._compute_background_job_sandbox(cfg, str(evil))
        assert err is not None
        err2, sand2 = ra._compute_background_job_sandbox(cfg, str(inner))
        assert err2 is None
        assert sand2 == str(tmp_path.resolve())
    finally:
        set_effective_sandbox(None)


def test_enqueue_subprocess_mode_returns_worker_mode(monkeypatch, tmp_path):
    import threading

    import routers.agent as ra
    import runtime_safety
    from services import inference_router as ir

    cfg = {
        "sandbox_root": str(tmp_path),
        "background_use_subprocess_workers": True,
        "background_worker_force_sandbox_only": False,
        "background_subprocess_local_gguf_policy": "allow",
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    monkeypatch.setattr(ir, "inference_backend_uses_local_gguf", lambda c: False)
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)

    def noop_subprocess(task_id, payload):
        return None

    monkeypatch.setattr(ra, "_run_background_subprocess_task", noop_subprocess)
    out = ra.enqueue_threaded_autonomous(
        {"message": "hello subprocess", "workspace_root": str(tmp_path)},
        default_priority=2,
        kind="background",
    )
    assert out.get("ok") is True
    assert out.get("worker_mode") == "subprocess"


def test_enqueue_subprocess_rejects_local_gguf_when_policy_reject(monkeypatch, tmp_path):
    import threading

    import routers.agent as ra
    import runtime_safety
    from services import inference_router as ir

    cfg = {
        "sandbox_root": str(tmp_path),
        "background_use_subprocess_workers": True,
        "background_worker_force_sandbox_only": False,
        "background_subprocess_local_gguf_policy": "reject",
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    monkeypatch.setattr(ir, "inference_backend_uses_local_gguf", lambda c: True)
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    out = ra.enqueue_threaded_autonomous(
        {"message": "hello", "workspace_root": str(tmp_path)},
        default_priority=2,
        kind="background",
    )
    assert out.get("ok") is False
    assert out.get("error") == "background_subprocess_local_gguf_rejected"


def test_cleanup_worker_cgroup_calls_remove_and_clears_attr(monkeypatch):
    from services import background_subprocess as bs
    import services.worker_cgroup_linux as wcl

    seen: list[str | None] = []

    def _fake_remove(rel: str | None) -> None:
        seen.append(rel)

    monkeypatch.setattr(wcl, "maybe_remove_worker_cgroup", _fake_remove)
    proc = MagicMock()
    proc._layla_cgroup_rel = "slice/layla-bg-1"
    bs.cleanup_worker_cgroup(proc)
    assert seen == ["slice/layla-bg-1"]
    assert getattr(proc, "_layla_cgroup_rel", None) is None


def test_wait_worker_result_invokes_progress_callback():
    from services import background_subprocess as bs

    events: list[dict] = []
    proc = MagicMock()
    proc.stdout = io.StringIO(json.dumps({"ok": True, "response": "x"}))
    proc.stderr = io.StringIO('{"type":"progress","seq":1,"preview":"p"}\n')
    proc.poll.return_value = 0

    parsed, err = bs.wait_worker_result(proc, on_progress_event=lambda o: events.append(dict(o)))
    assert parsed is not None
    assert parsed.get("ok") is True
    assert len(events) == 1
    assert events[0].get("seq") == 1
    assert "progress" in err


def test_worker_argv_inserts_wrapper(monkeypatch):
    import runtime_safety
    import services.background_subprocess as bs

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"background_worker_wrapper_command": ["echo", "wrap"]},
    )
    v = bs._worker_argv("/usr/bin/python3")
    assert v[:2] == ["echo", "wrap"]
    assert v[-2] == "/usr/bin/python3"
    assert v[-1] == str(bs.WORKER_SCRIPT)
