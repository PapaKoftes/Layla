"""S4 tool-layer defense-in-depth: a destructive tool reaching the generic executor.run_tool must
fail-closed if the active turn didn't grant the matching permission, WITHOUT breaking internal/confined
callers that run outside a turn context."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.tools import tool_permissions as tp  # noqa: E402


def teardown_function(_):
    tp.clear_tool_permissions()


def test_permissive_when_no_turn_context():
    tp.clear_tool_permissions()
    for t in ("write_file", "shell", "read_file", "git_commit"):
        ok, _ = tp.check_tool_permission(t)
        assert ok, f"{t} should be permissive with no active turn context"


def test_write_tool_refused_without_allow_write():
    tp.set_tool_permissions(allow_write=False, allow_run=True)
    ok, reason = tp.check_tool_permission("write_file")
    assert not ok and "allow_write" in reason
    # a read tool is never gated
    assert tp.check_tool_permission("read_file")[0]


def test_exec_tool_refused_without_allow_run():
    tp.set_tool_permissions(allow_write=True, allow_run=False)
    ok, reason = tp.check_tool_permission("shell")
    assert not ok and "allow_run" in reason
    # write tool allowed since allow_write is on
    assert tp.check_tool_permission("write_file")[0]


def test_granted_permissions_allow_destructive_tools():
    tp.set_tool_permissions(allow_write=True, allow_run=True)
    for t in ("write_file", "search_replace", "shell", "run_python", "git_commit"):
        assert tp.check_tool_permission(t)[0], t


def test_executor_fails_closed_on_denied_destructive_tool():
    # Register a fake write tool; with allow_write off, run_tool must refuse before executing it.
    from unittest.mock import patch

    import core.executor as ex
    import layla.tools.registry as reg
    called = {"n": 0}

    def _fake_write(**kw):
        called["n"] += 1
        return {"ok": True}

    tp.set_tool_permissions(allow_write=False, allow_run=False)
    try:
        with patch.dict(reg.TOOLS, {"write_file": {"fn": _fake_write}}, clear=False):
            res = ex.run_tool("write_file", {"path": "x", "content": "y"})
    finally:
        tp.clear_tool_permissions()
    assert res["ok"] is False and "Blocked" in res["error"]
    assert called["n"] == 0, "the destructive tool must NOT have executed"


def test_executor_allows_when_granted():
    from unittest.mock import patch

    import core.executor as ex
    import layla.tools.registry as reg
    called = {"n": 0}

    def _fake_write(**kw):
        called["n"] += 1
        return {"ok": True, "result": "done"}

    tp.set_tool_permissions(allow_write=True, allow_run=True)
    try:
        with patch.dict(reg.TOOLS, {"write_file": {"fn": _fake_write}}, clear=False):
            res = ex.run_tool("write_file", {"path": "x", "content": "y"})
    finally:
        tp.clear_tool_permissions()
    assert called["n"] == 1 and res.get("ok") is True
