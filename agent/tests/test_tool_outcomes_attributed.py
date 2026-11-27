"""The agent's own tool calls are recorded as agent usage, and learning reads only recent uses.

Live DB: 114 of 114 tool_outcomes rows had context=''. The "agent_loop" marker was set only in
core.executor.run_tool, which only the MCP server calls; the agent dispatches through
tool_dispatch.dispatch_tool_intent. get_tool_reliability(attributed_only=True) — what tool-reliability
policy and planner preferences read — was therefore always empty.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_agent_dispatch_records_attributed_outcome(isolated_db, tmp_path):
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    from layla.memory.db import _conn
    from services.tools.tool_dispatch import DispatchContext, dispatch_tool_intent

    decision = {"action": "tool", "tool": "list_dir", "args": {"path": str(tmp_path)}}
    state = {"steps": [], "tool_calls": 0, "workspace_root": str(tmp_path), "original_goal": "list",
             "last_decision": decision}
    ctx = DispatchContext(state=state, cfg={"sandbox_root": str(tmp_path)}, workspace=str(tmp_path), decision=decision,
                          allow_write=False, allow_run=False, reasoning_mode="none", ux_state_queue=None,
                          show_thinking=False)
    dispatch_tool_intent("list_dir", "list", ctx)

    with _conn() as db:
        rows = db.execute("SELECT tool_name, context FROM tool_outcomes").fetchall()
    assert rows, "PROBE BROKEN: dispatch recorded no tool outcome at all"
    assert ("list_dir", "agent_loop") in [(r[0], r[1]) for r in rows], rows


def test_reliability_learning_reads_only_recent_attributed_uses(isolated_db):
    from layla.memory.db import _conn
    from layla.memory.user_profile import get_tool_reliability

    with _conn() as db:
        for i in range(20):  # 20 old failures (e.g. a since-fixed bug) ...
            db.execute("INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at)"
                       " VALUES ('list_dir','agent_loop',0,1,0,?)", (f"2026-01-01T00:00:{i:02d}",))
        for i in range(10):  # ... then 10 recent successes
            db.execute("INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at)"
                       " VALUES ('list_dir','agent_loop',1,1,1,?)", (f"2026-06-01T00:00:{i:02d}",))
        db.execute("INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at)"
                   " VALUES ('list_dir','',0,1,0,'2026-07-01T00:00:00')")  # unattributed: never learned from
        db.commit()

    allt = get_tool_reliability(attributed_only=True, n=100)["list_dir"]
    assert allt["count"] == 30 and abs(allt["success_rate"] - 10 / 30) < 1e-9, allt
    recent = get_tool_reliability(attributed_only=True, n=10)["list_dir"]
    assert recent["count"] == 10 and recent["success_rate"] == 1.0, recent
    one = get_tool_reliability("list_dir", attributed_only=True, n=10)["list_dir"]
    assert one["success_rate"] == 1.0, one
