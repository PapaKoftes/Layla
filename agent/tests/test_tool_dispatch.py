"""Tests for services.tool_dispatch — tool intent routing extracted from agent_loop."""
from unittest.mock import MagicMock, patch

import pytest

from services.tool_dispatch import (
    _EXTENDED_TOOLS,
    _HARDCODED_INTENTS,
    DispatchContext,
    DispatchResult,
    _rebuild_goal,
    dispatch_tool_intent,
)


def _make_ctx(**overrides):
    """Create a DispatchContext with sensible defaults for testing."""
    defaults = dict(
        state={
            "original_goal": "test goal",
            "steps": [],
            "tool_calls": 0,
            "last_tool_used": None,
            "status": "running",
        },
        cfg={},
        workspace="/tmp/test_workspace",
        decision=None,
        allow_write=True,
        allow_run=True,
        reasoning_mode="light",
        ux_state_queue=None,
        show_thinking=False,
    )
    defaults.update(overrides)
    return DispatchContext(**defaults)


# ===================================================================
# Data structure tests
# ===================================================================

class TestDispatchResult:
    def test_default_values(self):
        r = DispatchResult()
        assert r.handled is False
        assert r.flow == "continue"
        assert r.goal == ""

    def test_custom_values(self):
        r = DispatchResult(handled=True, flow="break", goal="updated")
        assert r.handled is True
        assert r.flow == "break"
        assert r.goal == "updated"


class TestDispatchContext:
    def test_creation(self):
        ctx = _make_ctx()
        assert ctx.workspace == "/tmp/test_workspace"
        assert ctx.allow_write is True
        assert ctx.allow_run is True

    def test_state_is_mutable(self):
        ctx = _make_ctx()
        ctx.state["test_key"] = "test_value"
        assert ctx.state["test_key"] == "test_value"


# ===================================================================
# dispatch_tool_intent routing tests
# ===================================================================

class TestDispatchRouting:
    def test_unhandled_intent_returns_not_handled(self):
        """Intents like 'reason', 'finish' should not be handled."""
        ctx = _make_ctx()
        result = dispatch_tool_intent("reason", "test goal", ctx)
        assert result.handled is False

    def test_finish_not_handled(self):
        ctx = _make_ctx()
        result = dispatch_tool_intent("finish", "test goal", ctx)
        assert result.handled is False

    def test_unknown_intent_not_handled(self):
        ctx = _make_ctx()
        result = dispatch_tool_intent("nonexistent_tool_xyz_99", "test goal", ctx)
        assert result.handled is False


# ===================================================================
# Constants tests
# ===================================================================

class TestConstants:
    def test_hardcoded_intents_is_frozenset(self):
        assert isinstance(_HARDCODED_INTENTS, frozenset)

    def test_hardcoded_intents_contains_write_file(self):
        assert "write_file" in _HARDCODED_INTENTS
        assert "read_file" in _HARDCODED_INTENTS
        assert "shell" in _HARDCODED_INTENTS

    def test_reason_in_hardcoded_intents(self):
        """'reason' should be in _HARDCODED_INTENTS to prevent generic dispatch."""
        assert "reason" in _HARDCODED_INTENTS

    def test_extended_tools_is_frozenset(self):
        assert isinstance(_EXTENDED_TOOLS, frozenset)

    def test_extended_tools_contents(self):
        assert "json_query" in _EXTENDED_TOOLS
        assert "diff_files" in _EXTENDED_TOOLS
        assert "env_info" in _EXTENDED_TOOLS
        assert "save_note" in _EXTENDED_TOOLS


# ===================================================================
# Handler-level tests (mock agent_loop helpers)
# ===================================================================

class TestWriteFileHandler:
    @patch("services.tool_dispatch._imports")
    def test_parse_failure_breaks(self, mock_imports):
        """write_file with no parseable path should break with parse_failed."""
        al = MagicMock()
        al._extract_file_and_content.return_value = ("", "")
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx()
        result = dispatch_tool_intent("write_file", "no path here", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "parse_failed"

    @patch("services.tool_dispatch._imports")
    def test_lab_root_blocked(self, mock_imports):
        """write_file outside lab root should be blocked."""
        al = MagicMock()
        al._extract_file_and_content.return_value = ("/some/path.py", "content")
        al._path_under_lab.return_value = False
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(state={
            "original_goal": "test",
            "steps": [],
            "tool_calls": 0,
            "research_lab_root": "/lab",
        })
        result = dispatch_tool_intent("write_file", "write /some/path.py content", ctx)
        assert result.handled is True
        assert result.flow == "continue"
        assert ctx.state["tool_calls"] == 1

    @patch("services.tool_dispatch._imports")
    def test_approval_required(self, mock_imports):
        """write_file without write permission should require approval."""
        al = MagicMock()
        al._extract_file_and_content.return_value = ("/some/path.py", "content")
        al._has_any_grant.return_value = False
        al._write_pending.return_value = "approval-123"
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        rs.is_tool_allowed.return_value = False
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(allow_write=False)
        result = dispatch_tool_intent("write_file", "write /path.py content", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "finished"


class TestReadFileHandler:
    @patch("services.tool_dispatch._imports")
    @patch("services.tool_dispatch._deterministic_verify_retry")
    def test_successful_read(self, mock_dvr, mock_imports):
        """read_file with valid path should continue."""
        al = MagicMock()
        al._extract_path.return_value = "/some/file.py"
        al._maybe_preprobe_file.return_value = None
        al._apply_probe_guidance.return_value = True
        al._maybe_validate_tool_output.return_value = {"ok": True, "content": "hello"}
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        TOOLS = {"read_file": {"fn": MagicMock(return_value={"ok": True, "content": "hello"})}}
        mock_imports.return_value = (al, rs, TOOLS)
        mock_dvr.return_value = ({"ok": True, "content": "hello"}, True, "")

        ctx = _make_ctx()
        result = dispatch_tool_intent("read_file", "read /some/file.py", ctx)
        assert result.handled is True
        assert result.flow == "continue"
        assert ctx.state["tool_calls"] == 1
        assert ctx.state["last_tool_used"] == "read_file"

    @patch("services.tool_dispatch._imports")
    def test_no_path_breaks(self, mock_imports):
        """read_file with no parseable path should break."""
        al = MagicMock()
        al._extract_path.return_value = ""
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx()
        result = dispatch_tool_intent("read_file", "read something", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "parse_failed"


class TestSimpleGitHandlers:
    @patch("services.tool_dispatch._imports")
    def test_git_status(self, mock_imports):
        al = MagicMock()
        al._maybe_validate_tool_output.return_value = {"ok": True}
        al._format_steps.return_value = "[]"
        al.UX_STATE_VERIFYING = "verifying"
        rs = MagicMock()
        TOOLS = {"git_status": {"fn": MagicMock(return_value={"ok": True})}}
        mock_imports.return_value = (al, rs, TOOLS)

        ctx = _make_ctx()
        result = dispatch_tool_intent("git_status", "git status", ctx)
        assert result.handled is True
        assert result.flow == "continue"
        TOOLS["git_status"]["fn"].assert_called_once_with(repo="/tmp/test_workspace")

    @patch("services.tool_dispatch._imports")
    def test_git_log_passes_n(self, mock_imports):
        """git_log should pass n=10 to the tool function."""
        al = MagicMock()
        al._maybe_validate_tool_output.return_value = {"ok": True}
        al._format_steps.return_value = "[]"
        al.UX_STATE_VERIFYING = "verifying"
        rs = MagicMock()
        TOOLS = {"git_log": {"fn": MagicMock(return_value={"ok": True})}}
        mock_imports.return_value = (al, rs, TOOLS)

        ctx = _make_ctx()
        dispatch_tool_intent("git_log", "git log", ctx)
        TOOLS["git_log"]["fn"].assert_called_once_with(repo="/tmp/test_workspace", n=10)


class TestShellHandler:
    @patch("services.tool_dispatch._imports")
    def test_lab_blocked(self, mock_imports):
        al = MagicMock()
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(state={
            "original_goal": "test",
            "steps": [],
            "tool_calls": 0,
            "research_lab_root": "/lab",
        })
        result = dispatch_tool_intent("shell", "ls -la", ctx)
        assert result.handled is True
        assert result.flow == "continue"
        assert ctx.state["steps"][-1]["result"]["reason"] == "not_allowed_in_research"

    @patch("services.tool_dispatch._imports")
    def test_no_argv_breaks(self, mock_imports):
        al = MagicMock()
        al._extract_shell_argv.return_value = None
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx()
        result = dispatch_tool_intent("shell", "", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "parse_failed"

    @patch("services.tool_dispatch._imports")
    def test_approval_when_not_allowed(self, mock_imports):
        al = MagicMock()
        al._extract_shell_argv.return_value = ["ls", "-la"]
        al._write_pending.return_value = "approval-456"
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(allow_run=False)
        result = dispatch_tool_intent("shell", "ls -la", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "finished"


class TestMCPHandler:
    @patch("services.tool_dispatch._imports")
    def test_lab_blocked(self, mock_imports):
        al = MagicMock()
        al._normalize_mcp_tool_args.return_value = {"mcp_server": "test", "tool_name": "test"}
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(state={
            "original_goal": "test",
            "steps": [],
            "tool_calls": 0,
            "research_lab_root": "/lab",
        })
        result = dispatch_tool_intent("mcp_tools_call", "mcp call", ctx)
        assert result.handled is True
        assert result.flow == "continue"


class TestExtendedToolsHandler:
    @patch("services.tool_dispatch._imports")
    def test_json_query(self, mock_imports):
        al = MagicMock()
        al._maybe_validate_tool_output.return_value = {"ok": True}
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        TOOLS = {"json_query": {"fn": MagicMock(return_value={"ok": True})}}
        mock_imports.return_value = (al, rs, TOOLS)

        ctx = _make_ctx(decision={"args": {"query": "$.data"}})
        result = dispatch_tool_intent("json_query", "query json", ctx)
        assert result.handled is True
        assert result.flow == "continue"

    @patch("services.tool_dispatch._imports")
    def test_env_info(self, mock_imports):
        al = MagicMock()
        al._maybe_validate_tool_output.return_value = {"ok": True}
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        TOOLS = {"env_info": {"fn": MagicMock(return_value={"ok": True})}}
        mock_imports.return_value = (al, rs, TOOLS)

        ctx = _make_ctx()
        result = dispatch_tool_intent("env_info", "env info", ctx)
        assert result.handled is True
        assert result.flow == "continue"


class TestGitCommitHandler:
    @patch("services.tool_dispatch._imports")
    def test_approval_required(self, mock_imports):
        al = MagicMock()
        al._has_any_grant.return_value = False
        al._write_pending.return_value = "approval-789"
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        rs.is_tool_allowed.return_value = False
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(allow_write=False)
        result = dispatch_tool_intent("git_commit", "commit changes", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "finished"


class TestUnderstandFileHandler:
    @patch("services.tool_dispatch._imports")
    def test_no_path_breaks(self, mock_imports):
        al = MagicMock()
        al._extract_path.return_value = ""
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx()
        result = dispatch_tool_intent("understand_file", "understand something", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "parse_failed"

    @patch("services.tool_dispatch._imports")
    def test_with_args_path(self, mock_imports):
        al = MagicMock()
        al._maybe_validate_tool_output.return_value = {"ok": True}
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        TOOLS = {"understand_file": {"fn": MagicMock(return_value={"ok": True})}}
        mock_imports.return_value = (al, rs, TOOLS)

        ctx = _make_ctx(decision={"args": {"path": "/test.py"}})
        result = dispatch_tool_intent("understand_file", "understand /test.py", ctx)
        assert result.handled is True
        assert result.flow == "continue"
        TOOLS["understand_file"]["fn"].assert_called_once_with(path="/test.py")


class TestRunPythonHandler:
    @patch("services.tool_dispatch._imports")
    def test_approval_when_not_allowed(self, mock_imports):
        al = MagicMock()
        al._write_pending.return_value = "approval-py"
        rs = MagicMock()
        rs.is_tool_allowed.return_value = False
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(allow_run=False)
        result = dispatch_tool_intent("run_python", "print('hello')", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "finished"

    @patch("services.tool_dispatch._imports")
    def test_lab_disabled(self, mock_imports):
        al = MagicMock()
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(
            allow_run=False,
            state={
                "original_goal": "test",
                "steps": [],
                "tool_calls": 0,
                "research_lab_root": "/lab",
            },
        )
        result = dispatch_tool_intent("run_python", "print('hello')", ctx)
        assert result.handled is True
        assert result.flow == "continue"
        assert ctx.state["steps"][-1]["result"]["reason"] == "disabled_in_research"


class TestFetchUrlHandler:
    @patch("services.tool_dispatch._imports")
    def test_no_url_breaks(self, mock_imports):
        al = MagicMock()
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx()
        result = dispatch_tool_intent("fetch_url", "fetch something without url", ctx)
        assert result.handled is True
        assert result.flow == "break"
        assert ctx.state["status"] == "parse_failed"


class TestApplyPatchHandler:
    @patch("services.tool_dispatch._imports")
    def test_lab_blocked(self, mock_imports):
        al = MagicMock()
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(state={
            "original_goal": "test",
            "steps": [],
            "tool_calls": 0,
            "research_lab_root": "/lab",
        })
        result = dispatch_tool_intent("apply_patch", "apply patch", ctx)
        assert result.handled is True
        assert result.flow == "continue"
        assert ctx.state["steps"][-1]["result"]["reason"] == "not_allowed_in_research"


class TestReplaceInFileHandler:
    @patch("services.tool_dispatch._imports")
    def test_lab_blocked(self, mock_imports):
        al = MagicMock()
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(state={
            "original_goal": "test",
            "steps": [],
            "tool_calls": 0,
            "research_lab_root": "/lab",
        })
        result = dispatch_tool_intent("replace_in_file", "replace text", ctx)
        assert result.handled is True
        assert result.flow == "continue"

    @patch("services.tool_dispatch._imports")
    def test_missing_args(self, mock_imports):
        al = MagicMock()
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        mock_imports.return_value = (al, rs, {})

        ctx = _make_ctx(decision={"args": {"path": "", "old_text": ""}})
        result = dispatch_tool_intent("replace_in_file", "replace", ctx)
        assert result.handled is True
        assert result.flow == "continue"
        assert ctx.state["steps"][-1]["result"]["ok"] is False


class TestProjectContextHandlers:
    @patch("services.tool_dispatch._imports")
    def test_get_project_context(self, mock_imports):
        al = MagicMock()
        al._maybe_validate_tool_output.return_value = {"ok": True}
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        TOOLS = {"get_project_context": {"fn": MagicMock(return_value={"ok": True})}}
        mock_imports.return_value = (al, rs, TOOLS)

        ctx = _make_ctx()
        result = dispatch_tool_intent("get_project_context", "get context", ctx)
        assert result.handled is True
        assert result.flow == "continue"

    @patch("services.tool_dispatch._imports")
    def test_update_project_context(self, mock_imports):
        al = MagicMock()
        al._maybe_validate_tool_output.return_value = {"ok": True}
        al._format_steps.return_value = "[]"
        rs = MagicMock()
        TOOLS = {"update_project_context": {"fn": MagicMock(return_value={"ok": True})}}
        mock_imports.return_value = (al, rs, TOOLS)

        ctx = _make_ctx(decision={"args": {"project_name": "test"}})
        result = dispatch_tool_intent("update_project_context", "update context", ctx)
        assert result.handled is True
        assert result.flow == "continue"
