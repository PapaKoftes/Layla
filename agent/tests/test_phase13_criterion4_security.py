"""Phase 13 criterion 4: "the three HIGH security items fixed OR CLAIMS DELETED".

The criterion was prose in a planning document, which means nothing enforces it. This turns all
three into assertions so the criterion is machine-checked and cannot silently regress.

The three items, as originally reported:

  1. `powershell` blocked / `powershell.exe` ALLOWED (and `pwsh`/`bash` not on the list at all).
  2. 3/3 Python-sandbox network-jail bypasses (`import _socket`, `importlib.reload(socket)`, raw
     `_socket`), including a real HTTP 200.
  3. `check_output` runs AFTER the token loop, so streaming — the default — is unguarded.

Item 2 is resolved by the SECOND half of the criterion, and deliberately so. Python cannot be
sandboxed in-process on Windows without a real OS boundary (cf. RestrictedPython "not a sandbox";
smolagents "must not be used as a security boundary"). The honest resolution is not to pretend
otherwise but to ensure nothing CLAIMS otherwise — so the test asserts the disclaimer exists and
that no false isolation claim has crept back in.
"""
from __future__ import annotations

from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent


class TestItem1ShellBlocklistHasNoWindowsBypass:
    """The reported bypass was Windows-shaped: a blocklist of bare names vs `.exe` invocations."""

    @pytest.mark.parametrize("raw,expected", [
        ("powershell", "powershell"),
        ("powershell.exe", "powershell"),
        ("PowerShell.EXE", "powershell"),
        (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", "powershell"),
        ("cmd.exe", "cmd"),
        ("/usr/bin/rm", "rm"),
        ("rm.exe.", "rm"),          # Windows strips trailing dots when resolving
        ("rm.exe.exe", "rm"),       # stacked suffixes
    ])
    def test_invocation_forms_normalise_to_the_bare_name(self, raw, expected):
        from services.sandbox.shell_runner import _normalize_cmd_name
        assert _normalize_cmd_name(raw) == expected

    @pytest.mark.parametrize("shell", ["powershell", "cmd", "pwsh", "bash", "sh"])
    def test_every_interpreter_is_actually_on_a_blocklist(self, shell):
        """The report noted pwsh/bash were not listed AT ALL — normalising them buys nothing."""
        from services.sandbox.shell_runner import _DEFAULT_BLOCKLIST
        assert shell in _DEFAULT_BLOCKLIST, (
            f"{shell!r} is not blocked; normalisation only helps for names that are on the list"
        )

    def test_no_weaker_duplicate_blocklist_survives(self):
        """The bypass lived in a SECOND copy of the rule. Two copies drift; the weaker one wins.

        Checked by AST, NOT by scanning text. The first version of this test did scan text and
        failed on its own evidence — the comment in system.py *documenting* the removed bug contains
        the very string it searched for. That is the third time this session a probe matched prose
        instead of code (`git grep` on untracked files, `startswith("#")` missing docstrings). If a
        check is about what the code DOES, read the code, not the file.
        """
        import ast

        src = (AGENT_DIR / "layla" / "tools" / "impl" / "system.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        refs = [n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Name) and n.id == "_SHELL_BLOCKLIST"]
        assert not refs, (
            f"system.py references _SHELL_BLOCKLIST again at line(s) {refs} — a second copy of the "
            "shell rule is exactly the defect that let cmd.exe through, because the weaker copy "
            "silently wins whenever the stronger path is unavailable. shell_runner._cmd_blocked is "
            "the single owner."
        )


class TestItem2NetworkClaimsAreHonest:
    """Not fixable in-process; the criterion's "or claims deleted" branch is the real resolution."""

    def test_the_speedbump_documents_that_it_is_not_a_boundary(self):
        src = (AGENT_DIR / "services" / "sandbox" / "python_runner.py").read_text(encoding="utf-8")
        low = src.lower()
        assert "not a security boundary" in low or "not a boundary" in low
        assert "bypassable" in low, "the known bypasses must stay documented, not quietly dropped"

    def test_the_identity_doc_denies_network_isolation(self):
        """This is what Layla answers 'what can you do?' from. It must not overclaim."""
        cap = REPO_ROOT / ".identity" / "capabilities.md"
        assert cap.exists(), "capabilities.md is the anti-fabrication source; it must ship"
        text = cap.read_text(encoding="utf-8").lower()
        assert "does not" in text and "network" in text, (
            "capabilities.md must state plainly that the Python sandbox does not block the network"
        )

    def test_no_false_isolation_claim_has_crept_back(self):
        """A claim is a liability even when the code is honest — scan the shipped surfaces."""
        offenders = []
        patterns = ("network-isolated", "network isolated", "sandboxed network", "network jail")
        for path in list(REPO_ROOT.glob("*.md")) + list((REPO_ROOT / ".identity").glob("*.md")):
            try:
                low = path.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            for pat in patterns:
                idx = low.find(pat)
                if idx == -1:
                    continue
                window = low[max(0, idx - 200):idx + 200]
                # A disclaimer that NAMES the thing in order to deny it is fine.
                if any(d in window for d in ("not ", "does not", "never", "cannot", "no ")):
                    continue
                offenders.append(f"{path.name}: {pat!r}")
        assert not offenders, f"unqualified network-isolation claims: {offenders}"


class TestItem3StreamingIsGuarded:
    """The done-frame check ran after the tokens were already on the wire."""

    def test_the_guard_suppresses_the_delta_and_everything_after(self):
        from services.agent.response_builder import StreamOutputGuard

        class _Res:
            blocked = True

        g = StreamOutputGuard({})
        assert g.feed("a benign opening ") == "a benign opening "
        import services.safety.content_guard as cg
        orig = cg.check_output
        cg.check_output = lambda text, cfg: _Res()
        try:
            assert g.feed("x" * 400) == "", "the matching delta must be cut"
            assert g.blocked is True
        finally:
            cg.check_output = orig
        assert g.feed("harmless continuation") == "", (
            "once blocked, EVERY later delta must stay suppressed — otherwise the harmful "
            "continuation streams anyway"
        )

    def test_the_guard_is_pure_passthrough_on_benign_content(self):
        from services.agent.response_builder import StreamOutputGuard
        g = StreamOutputGuard({})
        out = "".join(g.feed(p) for p in ["Hello ", "there, ", "here is your answer."])
        assert out == "Hello there, here is your answer."
        assert g.blocked is False

    def test_the_guard_fails_open_rather_than_dropping_the_reply(self):
        """Availability: a throwing scanner must not silently blank the default UI path."""
        from services.agent.response_builder import StreamOutputGuard
        import services.safety.content_guard as cg
        orig = cg.check_output
        cg.check_output = lambda text, cfg: (_ for _ in ()).throw(RuntimeError("scanner down"))
        try:
            g = StreamOutputGuard({})
            assert g.feed("a" * 400) == "a" * 400
            assert g.blocked is False
        finally:
            cg.check_output = orig

    @pytest.mark.parametrize("router,needle", [
        ("routers/agent.py", "StreamOutputGuard"),
        ("routers/openai_compat.py", "StreamOutputGuard"),
    ])
    def test_the_guard_is_wired_into_every_streaming_path(self, router, needle):
        """A correct component nobody calls is this codebase's signature defect."""
        src = (AGENT_DIR / router).read_text(encoding="utf-8")
        assert needle in src, (
            f"{router} streams tokens without the output guard — the done-frame check runs only "
            "after the payload is already on the wire, and a raw /v1 client never sees a retraction"
        )
