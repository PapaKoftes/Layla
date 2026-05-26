"""Tests for services.agent_safety — planning strict mode and per-step tool allowlist gates."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.agent_safety import (
    maybe_planning_strict_refusal,
    maybe_step_tool_allowlist_refusal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(strict: bool = False) -> dict:
    return {"planning_strict_mode": strict}


def _state(plan_approved: bool = False) -> dict:
    return {"plan_approved": plan_approved}


# ===========================================================================
# maybe_planning_strict_refusal
# ===========================================================================


class TestPlanningStrictRefusal:
    """Tests for the planning_strict_mode gate."""

    # -- Feature disabled → always None -------

    def test_disabled_returns_none(self):
        result = maybe_planning_strict_refusal(
            "shell", _cfg(strict=False), _state(), allow_write=True, allow_run=True,
        )
        assert result is None

    # -- Feature enabled + plan approved → None --

    def test_plan_approved_returns_none(self):
        result = maybe_planning_strict_refusal(
            "shell", _cfg(strict=True), _state(plan_approved=True),
            allow_write=True, allow_run=True,
        )
        assert result is None

    # -- No write/run perms → None (nothing dangerous possible) --

    def test_no_write_no_run_returns_none(self):
        result = maybe_planning_strict_refusal(
            "shell", _cfg(strict=True), _state(),
            allow_write=False, allow_run=False,
        )
        assert result is None

    # -- Benign intents always pass --

    @pytest.mark.parametrize("intent", ["reason", "finish", "wakeup", "none"])
    def test_benign_intents_return_none(self, intent: str):
        result = maybe_planning_strict_refusal(
            intent, _cfg(strict=True), _state(),
            allow_write=True, allow_run=True,
        )
        assert result is None

    # -- Run-category tools blocked when allow_run --

    @pytest.mark.parametrize("intent", [
        "shell", "run_python", "mcp_tools_call", "run_tests",
        "pip_install", "shell_session_start", "shell_session_manage",
        "git_add", "git_commit",
    ])
    def test_run_tools_blocked_with_allow_run(self, intent: str):
        result = maybe_planning_strict_refusal(
            intent, _cfg(strict=True), _state(),
            allow_write=False, allow_run=True,
        )
        assert result is not None
        assert result["ok"] is False
        assert result["reason"] == "planning_strict_mode"
        assert "message" in result

    # -- Run tool also blocked when allow_write --

    def test_shell_blocked_with_allow_write(self):
        result = maybe_planning_strict_refusal(
            "shell", _cfg(strict=True), _state(),
            allow_write=True, allow_run=False,
        )
        assert result is not None
        assert result["reason"] == "planning_strict_mode"

    # -- Dangerous tools (from TOOLS registry) blocked --

    def test_dangerous_tool_blocked(self):
        """A tool flagged dangerous=True in the registry should be refused."""
        fake_tools = {"delete_everything": {"dangerous": True}}
        with patch("services.agent_safety.TOOLS", fake_tools):
            result = maybe_planning_strict_refusal(
                "delete_everything", _cfg(strict=True), _state(),
                allow_write=True, allow_run=False,
            )
        assert result is not None
        assert result["reason"] == "planning_strict_mode"

    # -- Exception tools (scan_repo, update_project_memory) pass --

    @pytest.mark.parametrize("intent", ["scan_repo", "update_project_memory"])
    def test_exception_dangerous_tools_pass(self, intent: str):
        fake_tools = {intent: {"dangerous": True}}
        with patch("services.agent_safety.TOOLS", fake_tools):
            result = maybe_planning_strict_refusal(
                intent, _cfg(strict=True), _state(),
                allow_write=True, allow_run=True,
            )
        assert result is None

    # -- Non-dangerous, non-run tool passes --

    def test_non_dangerous_non_run_tool_passes(self):
        fake_tools = {"read_file": {"dangerous": False}}
        with patch("services.agent_safety.TOOLS", fake_tools):
            result = maybe_planning_strict_refusal(
                "read_file", _cfg(strict=True), _state(),
                allow_write=True, allow_run=True,
            )
        assert result is None

    # -- Unknown tool (not in TOOLS, not in run list) passes --

    def test_unknown_tool_passes(self):
        with patch("services.agent_safety.TOOLS", {}):
            result = maybe_planning_strict_refusal(
                "unknown_safe_tool", _cfg(strict=True), _state(),
                allow_write=True, allow_run=True,
            )
        assert result is None


# ===========================================================================
# maybe_step_tool_allowlist_refusal
# ===========================================================================


class TestStepToolAllowlistRefusal:
    """Tests for the per-step tool allowlist gate."""

    # -- Always-allowed intents bypass the allowlist --

    @pytest.mark.parametrize("intent", ["reason", "finish", "wakeup", "none", "think"])
    def test_always_allowed_intents(self, intent: str):
        result = maybe_step_tool_allowlist_refusal(intent, {})
        assert result is None

    # -- Empty allowlist → None (no restriction) --

    def test_empty_allowlist_returns_none(self):
        with patch(
            "services.tool_allowlist_context.get_plan_step_tool_allowlist",
            return_value=None,
        ):
            result = maybe_step_tool_allowlist_refusal("shell", {})
        assert result is None

    def test_empty_frozenset_allowlist_returns_none(self):
        with patch(
            "services.tool_allowlist_context.get_plan_step_tool_allowlist",
            return_value=frozenset(),
        ):
            result = maybe_step_tool_allowlist_refusal("shell", {})
        assert result is None

    # -- Intent in allowlist → None --

    def test_intent_in_allowlist_returns_none(self):
        with patch(
            "services.tool_allowlist_context.get_plan_step_tool_allowlist",
            return_value=frozenset({"shell", "read_file"}),
        ):
            result = maybe_step_tool_allowlist_refusal("shell", {})
        assert result is None

    # -- Intent NOT in allowlist → refusal dict --

    def test_intent_not_in_allowlist_returns_refusal(self):
        with patch(
            "services.tool_allowlist_context.get_plan_step_tool_allowlist",
            return_value=frozenset({"read_file", "write_file"}),
        ):
            result = maybe_step_tool_allowlist_refusal("shell", {})
        assert result is not None
        assert result["ok"] is False
        assert result["reason"] == "step_tool_allowlist"
        assert "shell" in result["message"]
        assert "read_file" in result["message"]

    # -- Refusal message lists all allowed tools --

    def test_refusal_lists_allowed_tools(self):
        allowed = frozenset({"alpha", "bravo", "charlie"})
        with patch(
            "services.tool_allowlist_context.get_plan_step_tool_allowlist",
            return_value=allowed,
        ):
            result = maybe_step_tool_allowlist_refusal("delta", {})
        assert result is not None
        for name in allowed:
            assert name in result["message"]

    # -- Import failure of allowlist module → None (fail-open) --

    def test_import_failure_returns_none(self):
        """When tool_allowlist_context cannot be imported, the gate fails open."""
        import builtins
        import sys

        _real_import = builtins.__import__

        def _blocking_import(name, *args, **kwargs):
            if "tool_allowlist_context" in name:
                raise ImportError("simulated missing module")
            return _real_import(name, *args, **kwargs)

        # Remove cached module so the lazy import inside the function re-triggers
        saved = sys.modules.pop("services.tool_allowlist_context", None)
        try:
            with patch.object(builtins, "__import__", side_effect=_blocking_import):
                result = maybe_step_tool_allowlist_refusal("shell", {})
            assert result is None
        finally:
            if saved is not None:
                sys.modules["services.tool_allowlist_context"] = saved
