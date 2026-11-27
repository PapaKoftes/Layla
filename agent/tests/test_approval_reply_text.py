"""A turn that ends on a queued approval must SAY so. Live it replied "Ready. What do you need?" (the generic
empty-reply standby) while a write_file approval sat in the queue unmentioned."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent.turn import answer_of  # noqa: E402


def test_approval_turn_names_tool_and_target():
    result = {"response": "", "steps": [{
        "action": "write_file", "args": {"path": "notes.txt"},
        "result": {"ok": False, "reason": "approval_required", "approval_id": "abc"},
    }]}
    text = answer_of(result)
    assert "approval" in text.lower() and "write_file" in text and "notes.txt" in text, text


def test_prose_answer_still_wins_and_dicts_never_leak():
    assert answer_of({"response": "Done.", "steps": [{"result": {"reason": "approval_required"}}]}) == "Done."
    assert answer_of({"response": "", "steps": [{"result": {"ok": False, "error": "x"}}]}) == ""


def test_generic_approval_step_records_the_target_not_the_content():
    import ast

    src = (AGENT_DIR / "services" / "tools" / "tool_dispatch_base.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_approval_break")
    body = ast.unparse(fn)
    assert "'args'" in body and "'path'" in body and "'content'" not in body
