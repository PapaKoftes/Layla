"""Two safety gaps: silent screen/clipboard capture, and a stale duplicate of the shell blocklist.

1. CAPTURE. `clipboard_write` required approval while `clipboard_read` did not, and
   `screenshot_desktop` was ungated entirely. That is backwards. Writing text the user already chose
   is harmless next to reading whatever they last copied — routinely a password or token — or
   capturing the whole screen including other applications. Both flow into model context and from
   there into memory rows and logs, in a product whose premise is local-first privacy.

2. SHELL. `layla/tools/impl/system.py` fell back to executing commands behind a second, weaker
   blocklist when the sandboxed runner raised. That copy was broken in BOTH directions — measured,
   not theorised: `cmd.exe`, `powershell.exe`, `reg.exe`, `taskkill.exe` and any absolute path
   sailed through (because `"cmd.exe".endswith("cmd")` is False against a blocklist of bare names),
   while innocent `mydd` / `myreg` / `addsc` / `procdd` were blocked. 5 bypasses, 4 false blocks.

   The fix is NOT a better duplicate. services/sandbox/shell_runner.py already normalises correctly
   (strip quotes, strip directory, casefold, loop-peel exec suffixes and trailing dots/spaces,
   basename EQUALITY not endswith). Two implementations of one security rule drift apart, and the
   weaker one silently wins whenever the stronger is unavailable. So the fallback now fails closed.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import runtime_safety
from services.sandbox.shell_runner import _normalize_cmd_name


class TestCaptureToolsRequireApproval:
    @pytest.mark.parametrize("tool", ["clipboard_read", "screenshot_desktop"])
    def test_capture_tools_are_gated(self, tool):
        assert tool in runtime_safety.DANGEROUS_TOOLS, (
            f"{tool} harvests private data straight into model context, memory and logs; "
            "it must require explicit approval"
        )

    def test_read_is_gated_at_least_as_strictly_as_write(self):
        """The original asymmetry, pinned so it cannot come back."""
        assert "clipboard_write" in runtime_safety.DANGEROUS_TOOLS
        assert "clipboard_read" in runtime_safety.DANGEROUS_TOOLS, (
            "clipboard_read was ungated while clipboard_write was gated — reading what the user "
            "last copied is the more sensitive of the two"
        )

    def test_gating_is_not_vacuous(self):
        """Guard the premise: DANGEROUS_TOOLS must actually withhold permission by default."""
        with patch.object(runtime_safety, "load_config", return_value={}), \
             patch.object(runtime_safety.Path, "read_text", side_effect=OSError("no approvals file")):
            assert runtime_safety.is_tool_allowed("clipboard_read") is False
            # And a genuinely safe tool must stay allowed, so the check is discriminating.
            assert runtime_safety.is_tool_allowed("read_file") is True


class TestShellFallbackFailsClosed:
    def test_the_correct_normaliser_handles_what_the_stale_copy_missed(self):
        """Pins the real rule, so a future 'simplification' cannot regress to endswith matching."""
        for raw, expected in [
            ("cmd.exe", "cmd"),
            (r"C:\Windows\System32\cmd.exe", "cmd"),
            ("PowerShell.EXE", "powershell"),
            ("/usr/bin/rm", "rm"),
            ("rm.exe.", "rm"),          # Windows drops trailing dots when resolving
            ("rm.exe.exe", "rm"),       # stacked suffixes
            ('"C:/Program Files/x/reg.exe"', "reg"),
        ]:
            assert _normalize_cmd_name(raw) == expected, f"{raw!r} must normalise to {expected!r}"

    def test_innocent_names_embedding_a_blocked_token_survive(self):
        """The false-block half of the old bug: endswith caught these, equality must not."""
        for raw in ("mydd", "myreg", "addsc", "procdd", "charm", "disc"):
            assert _normalize_cmd_name(raw) == raw
            assert raw not in ("rm", "del", "dd", "reg", "sc"), "sanity: these are not blocked names"

    def test_shell_refuses_to_run_when_the_sandboxed_runner_fails(self):
        """No weaker second path. If the sandboxed runner cannot execute, nothing executes."""
        from layla.tools.impl import system as sys_tools

        with patch("services.sandbox.shell_runner.run_shell_argv", side_effect=RuntimeError("boom")), \
             patch("subprocess.run") as sp:
            out = sys_tools.shell(argv=["echo", "hi"], cwd=".")

        assert out["ok"] is False
        assert "refused" in out["error"].lower() or "unavailable" in out["error"].lower()
        sp.assert_not_called(), "a command was executed outside the sandboxed runner"

    def test_failing_closed_applies_to_would_be_blocked_commands_too(self):
        from layla.tools.impl import system as sys_tools

        with patch("services.sandbox.shell_runner.run_shell_argv", side_effect=RuntimeError("boom")), \
             patch("subprocess.run") as sp:
            out = sys_tools.shell(argv=[r"C:\Windows\System32\cmd.exe", "/c", "dir"], cwd=".")

        assert out["ok"] is False
        sp.assert_not_called(), (
            "cmd.exe executed via the fallback — this is the exact bypass the change removes"
        )
