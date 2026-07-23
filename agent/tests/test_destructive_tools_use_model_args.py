"""QW-1: write_file / shell / fetch_url must honour the model's structured args, not re-parse the goal.

P13-E1 fixed the READ-side handlers (read_file, list_dir, grep_code, apply_patch) to take
decision["args"] first. The three most consequential handlers were left re-parsing the goal STRING:

  write_file  needs the literal "with content" + a path token containing a slash or colon in the goal
  shell       needs a quoted command in the goal
  fetch_url   needs a bare http... word in the goal

So a correct emission like {"tool":"write_file","args":{"path":"notes.md","content":"hi"}} with a
natural goal ("save my notes") returned no target -> status="parse_failed" -> the prose fallback
FABRICATED. That is the same fabrication defect, still live in the DESTRUCTIVE tools. These tests
drive each handler with args-only (goal deliberately carries no extractable target) and assert it
runs against the model's args instead of bailing to parse_failed.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.tools import tool_dispatch as td
from services.tools.tool_dispatch_base import DispatchContext


def _ctx(decision, goal="do the thing", **over):
    base = dict(
        state={"original_goal": goal, "steps": [], "tool_calls": 0, "last_tool_used": None, "status": "running"},
        cfg={}, workspace="/tmp/ws", decision=decision,
        allow_write=True, allow_run=True, reasoning_mode="light",
        ux_state_queue=None, show_thinking=False,
    )
    base.update(over)
    return DispatchContext(**base)


@pytest.fixture
def bypass_approval():
    # These are the destructive tools; the point of the test is arg PLUMBING, not the approval gate,
    # which is exercised elsewhere. Bypass approval so we reach the tool call.
    with patch.object(td, "_is_approval_bypassed", return_value=True):
        yield


class TestWriteFileUsesArgs:
    def test_args_path_and_content_are_honoured_when_goal_has_neither(self, bypass_approval):
        captured = {}

        def _fake_write(path, content):
            captured["path"] = path
            captured["content"] = content
            return {"ok": True, "path": path}

        al, _, TOOLS = td._imports()
        with patch.dict(TOOLS["write_file"], {"fn": _fake_write}):
            # goal carries NO "with content" and NO path token: the old heuristic returns (None, None)
            ctx = _ctx({"args": {"path": "notes.md", "content": "hello"}}, goal="save my notes please")
            td._handle_write_file("write_file", "save my notes please", ctx)

        assert ctx.state["status"] != "parse_failed", "args carried a path; must not bail to parse_failed"
        assert captured.get("path") == "notes.md"
        assert captured.get("content") == "hello"


class TestFetchUrlUsesArgs:
    def test_args_url_is_honoured_when_goal_has_no_http_word(self, bypass_approval):
        captured = {}
        al, _, TOOLS = td._imports()

        def _fake_fetch(**kw):
            captured.update(kw)
            return {"ok": True}

        with patch.dict(TOOLS["fetch_url"], {"fn": _fake_fetch}):
            ctx = _ctx({"args": {"url": "https://example.com/page"}}, goal="grab that page for me")
            td._handle_fetch_url("fetch_url", "grab that page for me", ctx)

        assert ctx.state["status"] != "parse_failed", "args carried a url; must not bail"
        assert "example.com" in str(captured), f"the model's url was not used: {captured}"


class TestShellUsesArgs:
    def test_command_string_in_args_is_parsed_to_argv(self, bypass_approval):
        captured = {}
        al, _, TOOLS = td._imports()

        def _fake_shell(argv, cwd):
            captured["argv"] = argv
            return {"ok": True, "stdout": ""}

        with patch.dict(TOOLS["shell"], {"fn": _fake_shell}):
            ctx = _ctx({"args": {"command": "ls -la /tmp"}}, goal="run it")
            td._handle_shell("shell", "run it", ctx)

        assert ctx.state["status"] != "parse_failed", "args carried a command; must not bail"
        assert captured.get("argv") == ["ls", "-la", "/tmp"], f"command string not parsed to argv: {captured}"

    def test_argv_list_in_args_is_used_directly(self, bypass_approval):
        captured = {}
        al, _, TOOLS = td._imports()

        def _fake_shell(argv, cwd):
            captured["argv"] = argv
            return {"ok": True}

        with patch.dict(TOOLS["shell"], {"fn": _fake_shell}):
            ctx = _ctx({"args": {"argv": ["echo", "hi"]}}, goal="run it")
            td._handle_shell("shell", "run it", ctx)

        assert captured.get("argv") == ["echo", "hi"]


def test_the_goal_heuristic_still_works_as_a_fallback():
    """No decision args at all -> the old goal-text extraction must still function (back-compat)."""
    al, _, TOOLS = td._imports()
    # fetch_url with a bare http word in the goal, no args.
    captured = {}
    with patch.object(td, "_is_approval_bypassed", return_value=True), \
         patch.dict(TOOLS["fetch_url"], {"fn": lambda **kw: captured.update(kw) or {"ok": True}}):
        ctx = _ctx(None, goal="fetch https://fallback.example/x")
        td._handle_fetch_url("fetch_url", "fetch https://fallback.example/x", ctx)
    assert "fallback.example" in str(captured), "goal-text fallback broke"
