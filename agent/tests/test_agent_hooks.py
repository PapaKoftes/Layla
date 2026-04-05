"""services.agent_hooks — optional pre_tool/post_tool/session_start subprocess hooks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_pre_tool_hook_runs_when_hooks_require_allow_run_false(monkeypatch, tmp_path):
    import runtime_safety
    from services.agent_hooks import run_agent_hooks

    marker = tmp_path / "ran.txt"
    py = f"from pathlib import Path; Path({str(marker)!r}).write_text('x')"
    cfg = {
        "agent_hooks_enabled": True,
        "hooks_require_allow_run": False,
        "agent_hooks": [{"event": "pre_tool", "command": [sys.executable, "-c", py], "timeout_seconds": 5}],
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    run_agent_hooks("pre_tool", tool_name="read_file", allow_run=False, conversation_id="c1", workspace_root=str(tmp_path))
    assert marker.read_text() == "x"


def test_pre_tool_skipped_when_hooks_require_allow_run_and_no_allow_run(monkeypatch, tmp_path):
    import runtime_safety
    from services.agent_hooks import run_agent_hooks

    marker = tmp_path / "ran.txt"
    py = f"from pathlib import Path; Path({str(marker)!r}).write_text('x')"
    cfg = {
        "agent_hooks_enabled": True,
        "hooks_require_allow_run": True,
        "agent_hooks": [{"event": "pre_tool", "command": [sys.executable, "-c", py], "timeout_seconds": 5}],
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    run_agent_hooks("pre_tool", tool_name="read_file", allow_run=False, conversation_id="c1", workspace_root=str(tmp_path))
    assert not marker.exists()


def test_session_start_runs_even_without_allow_run(monkeypatch, tmp_path):
    import runtime_safety
    from services.agent_hooks import run_agent_hooks

    marker = tmp_path / "ss.txt"
    py = f"from pathlib import Path; Path({str(marker)!r}).write_text('ss')"
    cfg = {
        "agent_hooks_enabled": True,
        "hooks_require_allow_run": True,
        "agent_hooks": [{"event": "session_start", "command": [sys.executable, "-c", py], "timeout_seconds": 5}],
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    run_agent_hooks("session_start", allow_run=False, conversation_id="c1", workspace_root=str(tmp_path))
    assert marker.read_text() == "ss"
