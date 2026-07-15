"""summarize_tool_result builds the per-tool status frame streamed to the chat UI (success/fail badge +
truncated summary). It was UNTESTED — the same UI-data-binding category that already bit us. Locks it."""
import sys
from pathlib import Path
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
from services.agent.ux_emitter import summarize_tool_result  # noqa: E402


def test_failure_dict_yields_false_and_message():
    ok, s = summarize_tool_result({"ok": False, "error": "boom happened"})
    assert ok is False and "boom happened" in s


def test_success_dict_yields_true_and_message():
    ok, s = summarize_tool_result({"ok": True, "message": "wrote 3 files"})
    assert ok is True and "wrote 3 files" in s


def test_non_dict_yields_none_ok():
    ok, s = summarize_tool_result("plain string result")
    assert ok is None and "plain string result" in s


def test_long_result_is_truncated():
    ok, s = summarize_tool_result({"ok": True, "message": "x" * 500}, max_len=50)
    assert len(s) <= 50 and s.endswith("...")


def test_newlines_flattened_and_never_raises():
    ok, s = summarize_tool_result({"ok": True, "message": "line1\nline2\nline3"})
    assert "\n" not in s
    # a weird object must not raise
    assert summarize_tool_result(object())[1] is not None
