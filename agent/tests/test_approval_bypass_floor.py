"""safe_mode is a HARD FLOOR over tool_approval_bypass for destructive tools (audit HIGH/MED).

Before: tool_approval_bypass was a one-click UI 'yes to everything' switch, and safe_mode — advertised
as 'require approval for writes/exec' — was never read on the dispatch path (decorative). Now a single
casual toggle of the bypass cannot hand the model unsupervised destructive power: while safe_mode is on
(the default), the bypass still does not skip approval for write/exec/dangerous tools."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.tools.tool_dispatch_base import DispatchContext, _is_approval_bypassed  # noqa: E402


def _ctx(cfg: dict) -> DispatchContext:
    return DispatchContext(
        state={}, cfg=cfg, workspace="/tmp/ws", decision=None,
        allow_write=True, allow_run=True, reasoning_mode="direct",
        ux_state_queue=None, show_thinking=False,
    )


def test_bypass_off_never_bypasses():
    assert _is_approval_bypassed(_ctx({"tool_approval_bypass": False}), "write_file") is False


def test_safe_mode_floor_blocks_bypass_for_destructive_tools():
    # bypass ON + safe_mode ON (default) → destructive tools STILL require approval.
    for tool in ("write_file", "shell", "run_python", "apply_patch", "git_push"):
        assert _is_approval_bypassed(_ctx({"tool_approval_bypass": True, "safe_mode": True}), tool) is False, tool
    # safe_mode defaults True even when unset.
    assert _is_approval_bypassed(_ctx({"tool_approval_bypass": True}), "write_file") is False


def test_bypass_still_applies_to_nondestructive_tools_under_safe_mode():
    # Reads/search are not in DANGEROUS_TOOLS → bypass still works with safe_mode on.
    assert _is_approval_bypassed(_ctx({"tool_approval_bypass": True, "safe_mode": True}), "read_file") is True


def test_full_autoapprove_requires_disabling_safe_mode_too():
    # Deliberate two-step: bypass ON + safe_mode OFF → destructive tools auto-approve.
    assert _is_approval_bypassed(_ctx({"tool_approval_bypass": True, "safe_mode": False}), "write_file") is True


def test_bypass_ignored_while_remote_exposed():
    ctx = _ctx({"tool_approval_bypass": True, "safe_mode": False, "remote_enabled": True})
    assert _is_approval_bypassed(ctx, "read_file") is False


def test_bypass_keys_are_remote_protected():
    from routers.settings import _REMOTE_PROTECTED_KEYS as P
    for k in ("tool_approval_bypass", "admin_mode", "admin_blocklist_override"):
        assert k in P, f"{k} (an approval-bypassing control) must be remote-protected"
