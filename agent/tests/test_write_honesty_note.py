"""A create-file turn that wrote nothing must say so. Live: a code block plus "File created." with no write."""
import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent.turn import UNWRITTEN_NOTE, with_write_honesty  # noqa: E402

ASK = "Create a file named notes.txt containing exactly the word banana."


def test_no_write_gets_the_note():
    out = with_write_honesty("```python\nopen('notes.txt','w')\n```\n\nFile created.", ASK, [{"action": "reason"}])
    assert out.endswith(UNWRITTEN_NOTE)


def test_real_or_pending_write_gets_no_note():
    done = [{"action": "write_file", "result": {"ok": True, "path": "notes.txt"}}]
    pend = [{"action": "write_file", "result": {"ok": False, "reason": "approval_required"}}]
    assert UNWRITTEN_NOTE not in with_write_honesty("Done.", ASK, done)
    assert UNWRITTEN_NOTE not in with_write_honesty("Waiting.", ASK, pend)


def test_unrelated_turns_are_untouched():
    for msg in ("How do I create a file in Python?", "Hey there", "What is in notes.txt?"):
        assert with_write_honesty("Answer.", msg, []) == "Answer."


def test_both_router_reply_paths_apply_it():
    src = (AGENT_DIR / "routers" / "agent.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "with_write_honesty"]
    assert len(calls) >= 2, "streamed and non-streamed agent replies must both apply the write-honesty note"
