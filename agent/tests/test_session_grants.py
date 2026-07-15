"""SAFETY: session-grant resolution decides whether a destructive tool skips the approval floor. It had
ZERO test coverage (every dispatch test mocked _has_any_grant), so a regression that widened a grant would
ship green. This locks the three scopes: `tool` (any args), `exact` (args must match), `command` (glob)."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.safety import session_grants as sg  # noqa: E402


def teardown_function(_):
    sg.clear_session_grants()


def test_tool_scope_matches_any_args():
    sg.clear_session_grants()
    sg.add_session_grant("write_file", scope="tool")
    assert sg.has_session_grant("write_file", {"path": "a"}) is True
    assert sg.has_session_grant("write_file", {"path": "totally-different"}) is True
    # but NOT a different tool
    assert sg.has_session_grant("shell", {"command": "ls"}) is False


def test_exact_scope_requires_arg_match():
    sg.clear_session_grants()
    sg.add_session_grant("write_file", scope="exact", args={"path": "/safe/a.txt"})
    assert sg.has_session_grant("write_file", {"path": "/safe/a.txt"}) is True
    # a DIFFERENT path must NOT be auto-approved
    assert sg.has_session_grant("write_file", {"path": "/etc/passwd"}) is False


def test_command_scope_glob_does_not_overmatch():
    sg.clear_session_grants()
    # granting `git status` must NOT auto-approve `git push` (the dangerous one)
    sg.add_session_grant("shell", scope="command", args={"command": "git status"})
    assert sg.has_session_grant("shell", {"command": "git status"}) is True
    assert sg.has_session_grant("shell", {"command": "git push"}) is False
    assert sg.has_session_grant("shell", {"command": "rm -rf /"}) is False


def test_command_scope_glob_matches_intended_pattern():
    sg.clear_session_grants()
    sg.add_session_grant("shell", scope="command", args={"command": "npm test*"})
    assert sg.has_session_grant("shell", {"command": "npm test"}) is True
    assert sg.has_session_grant("shell", {"command": "npm test -- --watch"}) is True
    assert sg.has_session_grant("shell", {"command": "npm publish"}) is False


def test_clear_revokes_all_grants():
    sg.clear_session_grants()
    sg.add_session_grant("write_file", scope="tool")
    assert sg.has_session_grant("write_file", {}) is True
    sg.clear_session_grants()
    assert sg.has_session_grant("write_file", {}) is False


def test_no_grant_means_no_bypass():
    sg.clear_session_grants()
    assert sg.has_session_grant("shell", {"command": "ls"}) is False
    assert sg.has_session_grant("write_file", {"path": "x"}) is False
