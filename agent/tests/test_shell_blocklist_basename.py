"""Shell blocklist matches on command BASENAME equality, not endswith — so path-prefixed
dangerous commands are blocked while legitimate names that merely end with a blocked token
(charm, add, disc) are allowed."""
from __future__ import annotations

from services.sandbox.shell_runner import _cmd_blocked


def test_dangerous_commands_blocked_bare_and_path():
    assert _cmd_blocked(["rm", "-rf", "/"]) is not None
    assert _cmd_blocked(["/usr/bin/rm", "x"]) is not None
    assert _cmd_blocked(["shutdown"]) is not None
    assert _cmd_blocked(["dd", "if=/dev/zero"]) is not None


def test_names_ending_with_blocked_token_not_over_blocked():
    # Old endswith logic wrongly blocked these ("charm" ends with "rm", "add" with "dd", ...).
    for argv in (["charm"], ["add"], ["disc"], ["warm"]):
        msg = _cmd_blocked(argv)
        # Either allowed outright, or only rejected by the (separate) allowlist — never by the blocklist.
        assert msg is None or "allowlist" in msg
