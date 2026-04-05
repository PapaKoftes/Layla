"""Hard step.tools allowlist + thread-local context for file-plan execution."""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_allowlist_empty_context_never_blocks():
    import agent_loop as al
    from services.tool_allowlist_context import clear_plan_step_tool_allowlist

    clear_plan_step_tool_allowlist()
    r = al._maybe_step_tool_allowlist_refusal("write_file", {})
    assert r is None


def test_allowlist_blocks_disallowed_tool():
    import agent_loop as al
    from services.tool_allowlist_context import clear_plan_step_tool_allowlist, set_plan_step_tool_allowlist

    clear_plan_step_tool_allowlist()
    set_plan_step_tool_allowlist(frozenset({"read_file", "list_dir"}))
    r = al._maybe_step_tool_allowlist_refusal("write_file", {})
    assert r is not None
    assert r.get("reason") == "step_tool_allowlist"
    clear_plan_step_tool_allowlist()


def test_allowlist_allows_listed_tool():
    import agent_loop as al
    from services.tool_allowlist_context import clear_plan_step_tool_allowlist, set_plan_step_tool_allowlist

    set_plan_step_tool_allowlist(frozenset({"read_file"}))
    r = al._maybe_step_tool_allowlist_refusal("read_file", {})
    assert r is None
    clear_plan_step_tool_allowlist()


def test_call_autonomous_sets_and_clears_allowlist():
    from services import engine_plans as ep
    from services.tool_allowlist_context import get_plan_step_tool_allowlist

    calls: list[str] = []

    def fake_autonomous_run(**_kw: object) -> dict:
        al = get_plan_step_tool_allowlist()
        calls.append("run:" + (",".join(sorted(al)) if al else ""))
        return {"ok": True, "response": "x"}

    payload = {
        "workspace_root": "",
        "allow_write": False,
        "allow_run": False,
        "_plan_step_tool_allowlist": ["read_file", "list_dir"],
    }
    import agent_loop as al_mod

    orig = al_mod.autonomous_run
    al_mod.autonomous_run = fake_autonomous_run
    try:
        ep._call_autonomous("goal", payload)
    finally:
        al_mod.autonomous_run = orig

    assert get_plan_step_tool_allowlist() is None
    assert any(c == "run:list_dir,read_file" for c in calls)
