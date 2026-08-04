"""Discord inbound is untrusted input and must never write files or run code. Unlike Slack/Telegram
(which route through TransportAdapter that FORCES allow_write=allow_run=False, test-locked), the
Discord bot funnels every inbound path through a single helper `_call_layla`. This test locks that
helper to forced-False so a one-line regression (adding allow_write=True) is caught.

Source-level, not runtime: `discord_bot/bot.py` imports the `discord` library, which is not installed
in the test venv — importing the module would ImportError. The invariant is a code-shape guarantee, so
a static assertion over the source is the right, dependency-free check."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOT = REPO_ROOT / "discord_bot" / "bot.py"


def test_call_layla_forces_read_only():
    src = BOT.read_text(encoding="utf-8")
    # The single choke point passes both flags explicitly False.
    assert "allow_write=False" in src, "_call_layla must force allow_write=False"
    assert "allow_run=False" in src, "_call_layla must force allow_run=False"


def test_no_inbound_path_enables_write_or_run():
    src = BOT.read_text(encoding="utf-8")
    # No Discord code path may ever request write/run (the regression this guards against).
    assert not re.search(r"allow_write\s*=\s*True", src), "Discord must never set allow_write=True"
    assert not re.search(r"allow_run\s*=\s*True", src), "Discord must never set allow_run=True"


def test_all_inbound_replies_go_through_the_choke_point():
    """Every inbound reply must call the forced-read-only helper `_call_layla`, not call_layla_async
    directly (which would let a caller pass its own allow flags). Only the helper definition itself may
    reference call_layla_async."""
    src = BOT.read_text(encoding="utf-8")
    # Exactly one call_layla_async reference outside the import line: inside _call_layla.
    non_import = [ln for ln in src.splitlines()
                  if "call_layla_async" in ln and not ln.strip().startswith("from ")]
    assert len(non_import) == 1, f"call_layla_async should be reached only via _call_layla; found {non_import}"
