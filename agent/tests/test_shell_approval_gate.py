"""Approval-gate TEETH for the shell dispatch path (services/tools/tool_dispatch._handle_shell).

The shell approval gate is the ACTUAL security boundary for a prompt-injected/misaligned
local model: it decides whether an un-approved shell command runs. This test file must fail
if that gate is removed.

Why it was rewritten (BL-344): the previous version NEVER invoked ``_handle_shell``. It
asserted predicate building-blocks and a source substring (``"not ctx.allow_run"``) that
three OTHER gates (run_python x2, mcp_tools_call) also satisfy — so it PASSED with the entire
shell approval block deleted. That was verified by deletion: with lines 582-604 of
tool_dispatch.py removed, all four old tests still passed. A guard that survives the removal
of the thing it guards is no guard.

This rewrite DRIVES the real dispatch path. The leaf shell tool is replaced by a spy that
records + raises the instant control reaches it, so:
  * a refusal is proven by the spy NEVER running (execution not reached), and
  * a positive control proves the harness CAN reach execution (so the refusals aren't
    vacuously true because the tool is simply unreachable).
Deleting the gate lets the spy run -> the refusal tests fail. Proven by deletion in the
slice that authored this file (both single-gate deletions and full-block deletion).
"""
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import runtime_safety as rs  # noqa: E402
from layla.tools.registry import TOOLS, shell_command_is_safe_whitelisted  # noqa: E402
from services.tools.tool_dispatch import _handle_shell  # noqa: E402
from services.tools.tool_dispatch_base import DispatchContext  # noqa: E402


class _ShellExecuted(Exception):
    """Raised by the spy the instant control reaches the shell tool fn."""


def _make_ctx(goal: str, *, allow_run: bool, workspace) -> DispatchContext:
    return DispatchContext(
        state={"steps": [], "status": "", "tool_calls": 0,
               "original_goal": goal, "conversation_id": ""},
        cfg={},                 # no tool_approval_bypass, no admin_mode
        workspace=str(workspace),
        decision={"args": {}},
        allow_write=True,       # irrelevant: shell keys on allow_run, never allow_write
        allow_run=allow_run,
        reasoning_mode="none",
        ux_state_queue=None,
        show_thinking=False,
    )


@pytest.fixture
def gate_harness(monkeypatch):
    """Isolate the gate. The leaf shell tool becomes a spy that records the call and raises
    the instant it runs; ``_write_pending`` is stubbed so the approval path never writes to
    agent/.governance (operator state); ``_has_any_grant`` is forced False so no DB grant can
    mask a bypass. The spy STANDS IN for the shell runner, so neither the shell_runner
    blocklist nor a real subprocess can hide a gate bypass — only the gate decides whether
    the spy runs. Yields ``(executed, pending)`` recorders."""
    import agent_loop as al

    executed: list[dict] = []
    pending: list[tuple] = []

    def spy(**kwargs):
        executed.append(kwargs)
        raise _ShellExecuted()

    def fake_write_pending(tool, args, ttl_seconds=3600):
        pending.append((tool, args))
        return "test-pending-id"

    orig_fn = TOOLS["shell"]["fn"]
    TOOLS["shell"]["fn"] = spy
    monkeypatch.setattr(al, "_write_pending", fake_write_pending)
    monkeypatch.setattr(al, "_has_any_grant", lambda *a, **k: False)
    try:
        yield executed, pending
    finally:
        TOOLS["shell"]["fn"] = orig_fn


# --- preconditions the gate relies on -----------------------------------------------------

def test_precondition_shell_not_preapproved_and_rm_not_whitelisted():
    # If shell were pre-approved or rm were whitelisted, the refusal tests would be testing
    # nothing. Assert the premises explicitly.
    assert rs.is_tool_allowed("shell") is False
    assert shell_command_is_safe_whitelisted(["rm", "-rf", "/x"]) is False
    assert shell_command_is_safe_whitelisted(["git", "status"]) is True


# --- ANTI-VACUOUS positive control: execution IS reachable in this harness ------------------

def test_positive_control_execution_is_reachable(gate_harness, tmp_path):
    # When approval is satisfied (allow_run + a whitelisted read-only command), the dispatch
    # path DOES reach the shell tool. This is the guard against a false-green: it proves the
    # refusal tests below fail-closed on a real seam, not because the tool is unreachable.
    executed, _ = gate_harness
    ctx = _make_ctx('run "git status"', allow_run=True, workspace=tmp_path)
    with pytest.raises(_ShellExecuted):
        _handle_shell("shell", ctx.state["original_goal"], ctx)
    assert executed and executed[0]["argv"] == ["git", "status"]


# --- gate 2 (whitelist/grant): un-approved DESTRUCTIVE command is refused -------------------

def test_gate_refuses_unapproved_destructive_command(gate_harness, tmp_path):
    # allow_run=True, but shell is not tool-allowed, the command is not whitelisted, and there
    # is no grant -> the whitelist/grant gate must refuse. `rm -rf` must never reach the tool.
    executed, pending = gate_harness
    ctx = _make_ctx('run "rm -rf /workspace/important"', allow_run=True, workspace=tmp_path)
    res = _handle_shell("shell", ctx.state["original_goal"], ctx)
    assert executed == [], "shell tool EXECUTED an un-approved destructive command — gate bypassed"
    assert res.flow == "break"
    assert ctx.state["steps"][-1]["result"].get("reason") == "approval_required"
    assert pending and pending[-1][0] == "shell"


# --- gate 1 (master run switch): nothing runs without run permission ------------------------

def test_gate_refuses_when_run_not_permitted(gate_harness, tmp_path):
    # allow_run=False (the master switch for running shell at all). Even a whitelisted,
    # read-only command must be gated. This isolates the first gate: with allow_run=False and
    # a *whitelisted* command, the second (whitelist) gate would NOT fire, so only the first
    # gate stands between the model and execution.
    executed, pending = gate_harness
    ctx = _make_ctx('run "git status"', allow_run=False, workspace=tmp_path)
    res = _handle_shell("shell", ctx.state["original_goal"], ctx)
    assert executed == [], "shell RAN with allow_run=False — master run gate bypassed"
    assert res.flow == "break"
    assert ctx.state["steps"][-1]["result"].get("reason") == "approval_required"
    assert pending and pending[-1][0] == "shell"
