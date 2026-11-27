"""Replies that open with an echoed decision line keep their real answer; an empty reply after a successful
listing shows the listing. Live (jinx-20b): 3 of 4 "List the files" replies were discarded whole."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

RAW = ('{"action":"tool","tool":"list_dir","args":{"path":"C:\\\\ws"}}\n\n'
       "The workspace contains: listprobe_0.md, probe_token.txt.")


def test_echoed_decision_line_is_dropped_and_answer_kept():
    import agent_loop as al
    from services.agent.response_builder import strip_junk_from_reply

    for fn in (al._clean_response_text, strip_junk_from_reply):
        out = fn(RAW)
        assert out.startswith("The workspace contains") and "listprobe_0.md" in out, (fn.__name__, out)


def test_a_reply_that_is_only_a_decision_is_still_junk():
    import agent_loop as al

    assert al._clean_response_text('{"action":"tool","tool":"list_dir","args":{"path":"/"}}') == ""


def test_prose_starting_with_a_brace_is_untouched():
    from services.agent.response_builder import _strip_leading_decision_echo

    s = '{"name": "x"} is a JSON object with one key.'
    assert _strip_leading_decision_echo(s) == s


def test_empty_reply_falls_back_to_the_listing():
    from services.agent.turn import tool_result_fallback

    steps = [{"action": "list_dir", "result": {"ok": True, "entries": [
        {"name": "a.md", "type": "file"}, {"name": "sub", "type": "dir"}]}}]
    out = tool_result_fallback(steps)
    assert "- a.md" in out and "- sub/" in out
    assert tool_result_fallback([{"action": "list_dir", "result": {"ok": False, "error": "x"}}]) == ""
    assert tool_result_fallback([{"action": "read_file", "result": {"ok": True, "content": "x"}}]) == ""
