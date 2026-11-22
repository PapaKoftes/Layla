"""Decision shapes a real model (jinx-20b) actually produced, which used to be thrown away.

1. Fallback path: {"action":"write_file","tool":"write_file","args":{...}} — correct call, tool name in
   "action". Pydantic rejected it before normalisation, so the turn fell through to a reply that only
   described the write.
2. GBNF path: {"action":"think","thought":"<long…>  — the unbounded thought ran past the 80-token decision
   budget mid-string; truncated JSON → parse failure → step discarded.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from decision_schema import parse_decision  # noqa: E402
from services.llm.gbnf_grammar import build_decision_grammar  # noqa: E402

V = frozenset({"read_file", "write_file"})


def test_tool_name_in_action_is_a_tool_call():
    d = parse_decision('{"action":"write_file","tool":"write_file","args":{"path":"a.txt","content":"banana"}}', V)
    assert d and d["action"] == "tool" and d["tool"] == "write_file" and d["args"] == {"path": "a.txt", "content": "banana"}
    d = parse_decision('{"action":"write_file","args":{"path":"a.txt"}}', V)
    assert d["action"] == "tool" and d["tool"] == "write_file"


def test_only_offered_and_unambiguous_tools_are_coerced():
    assert parse_decision('{"action":"shell","tool":"shell"}', V)["action"] != "tool", "a tool not offered must not run"
    assert parse_decision('{"action":"write_file","tool":"read_file"}', V)["action"] != "tool", "conflicting fields"


def test_thought_is_bounded_in_the_grammar():
    g = build_decision_grammar(["read_file"])
    root = next(ln for ln in g.splitlines() if ln.startswith("root ::="))
    assert '"\\"thought\\"" ws ":" ws shortstr' in root, root
    rule = next(ln for ln in g.splitlines() if ln.startswith("shortstr ::="))
    assert "{0,160}" in rule, rule


def test_bounded_grammar_compiles():
    import pytest

    llama_cpp = pytest.importorskip("llama_cpp")
    llama_cpp.LlamaGrammar.from_string(build_decision_grammar(["read_file", "write_file"]), verbose=False)
