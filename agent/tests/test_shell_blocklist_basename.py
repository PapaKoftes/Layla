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


# --- BL-296: extension normalization + extended blocklist ---------------------------------

def _blocked_by_blocklist(argv):
    """True iff argv is rejected by the BLOCKLIST specifically (not the allowlist)."""
    msg = _cmd_blocked(argv)
    return msg is not None and "blocked" in msg.lower()


def test_exe_suffix_and_case_do_not_bypass_blocklist():
    # The exact escape the fix was built to catch: powershell -> blocked, but powershell.exe /
    # PowerShell.EXE / cmd.exe / rm.exe walked straight past a blocklist written in bare names.
    for argv in (
        ["powershell.exe"],
        ["PowerShell.EXE"],
        ["cmd.exe"],
        ["CMD.EXE"],
        ["rm.exe"],
        ["Rm.Exe", "-rf", "."],
    ):
        assert _blocked_by_blocklist(argv), f"{argv} must be blocked (extension/case bypass)"


def test_full_path_exe_is_blocked():
    # Directory prefix + .exe must still normalize to the bare name.
    assert _blocked_by_blocklist([r"C:\Windows\System32\rm.exe", "-rf"])
    assert _blocked_by_blocklist(["/usr/bin/powershell.exe"])
    assert _blocked_by_blocklist([r".\cmd.exe"])


def test_interpreters_and_lolbins_blocked():
    # Interpreters (they run arbitrary sub-commands, nullifying an argv blocklist) and the
    # download/remote-exec LOLBins the threat frame names. Bare + .exe forms.
    for name in ("pwsh", "bash", "wmic", "wget", "certutil", "bitsadmin", "mshta", "rundll32"):
        assert _blocked_by_blocklist([name]), f"{name} must be blocked"
        assert _blocked_by_blocklist([name + ".exe"]), f"{name}.exe must be blocked"


def test_legitimate_commands_not_blocked_by_blocklist():
    # No false positives: normal dev commands and the historical near-miss names.
    for argv in (
        ["git", "status"],
        ["python.exe", "-c", "print(1)"],
        ["ls"],
        ["charm"],
        ["node", "app.js"],
    ):
        assert not _blocked_by_blocklist(argv), f"{argv} must NOT be blocklisted"


def test_curl_intentionally_not_blocklisted():
    # Documented decision (BL-296): curl.exe ships with Windows and is commonly legitimate;
    # network egress is url_guard's job, not this blocklist. If this ever changes, it must be
    # a conscious edit — this asserts the current, intentional state.
    assert not _blocked_by_blocklist(["curl.exe", "https://example.com"])


def test_trailing_dots_and_spaces_do_not_bypass_the_blocklist():
    """Windows resolves an executable name by stripping trailing dots and spaces, so `rm.exe.`,
    `rm.exe ` and `rm.exe...` all launch `rm.exe`. Found by adversarial verification AFTER the first
    normalization landed: the initial fix stripped one suffix but not trailing dots, so `rm.exe.` slipped
    the blocklist. This pins every trailing/stacked variant."""
    from services.sandbox.shell_runner import _cmd_blocked

    for cmd in (
        "rm.exe.", "rm.exe ", "rm.exe...", "rm.exe. ",
        "powershell.exe.", "POWERSHELL.EXE. ", "cmd.exe. ",
        "rm.exe.exe", '"rm.exe."', r"C:\Windows\System32\rm.exe.",  # raw: a plain string makes \r a CR
    ):
        assert _cmd_blocked([cmd]) is not None, f"trailing/stacked bypass slipped the blocklist: {cmd!r}"

    # And the false-positive floor must hold: legitimate names that merely embed or trail a blocked token
    # (or share a Windows-shipped exe) stay allowed.
    for ok in ("git", "python", "ls", "charm", "disc", "add", "discard", "curl.exe", "git.exe", "powerpoint"):
        assert _cmd_blocked([ok]) is None, f"legitimate command false-blocked: {ok!r}"
