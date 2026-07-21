"""postchecks._run_git_auto_commit auto-commits after a mutating tool ONLY when git_auto_commit is enabled
(default off). A regression that ignored the gate would fire surprise commits on every write. Locks the gate."""
import sys
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
from services.agent import postchecks  # noqa: E402


def test_no_autocommit_when_gate_disabled():
    called = {"git": 0}
    fake_tools = {"git_add": {"fn": lambda **k: called.__setitem__("git", called["git"] + 1) or {"ok": True}},
                  "git_commit": {"fn": lambda **k: called.__setitem__("git", called["git"] + 1) or {"ok": True}}}
    with patch("runtime_safety.load_config", return_value={"git_auto_commit": False}), \
         patch.dict("layla.tools.registry.TOOLS", fake_tools, clear=False):
        postchecks._run_git_auto_commit("write_file", {"ok": True}, "f.txt", "/tmp/ws")
    assert called["git"] == 0, "no git commands may run when git_auto_commit is off (the default)"


def test_no_autocommit_when_tool_failed():
    called = {"git": 0}
    fake_tools = {"git_add": {"fn": lambda **k: called.__setitem__("git", called["git"] + 1) or {"ok": True}}}
    with patch("runtime_safety.load_config", return_value={"git_auto_commit": True}), \
         patch.dict("layla.tools.registry.TOOLS", fake_tools, clear=False):
        postchecks._run_git_auto_commit("write_file", {"ok": False}, "f.txt", "/tmp/ws")
    assert called["git"] == 0, "a failed tool must not trigger an auto-commit"
