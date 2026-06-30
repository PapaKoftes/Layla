"""Characterization tests for the agent loop's CORE decision logic.

C5 finding: the agent loop is collection-ignored in CI, so its highest-bug-
density logic — parsing the model's tool-call/decision JSON and the completion
gate — was untested. Both modules are pure stdlib (no model, no heavy deps), so
they can and should be tested directly. These lock in the documented behavior:
brace-balanced extraction, fence stripping, trailing-comma repair, unknown-tool
nulling, and the deterministic completion gate.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from decision_schema import parse_decision  # noqa: E402
from services.infrastructure.output_quality import passes_completion_gate  # noqa: E402

TOOLS = frozenset({"read_file", "write_file", "shell", "grep_code"})


# ── parse_decision ───────────────────────────────────────────────────────────
def test_parse_valid_tool_decision():
    d = parse_decision('{"action":"tool","tool":"read_file","args":{"path":"x.py"}}', TOOLS)
    assert d and d["action"] == "tool" and d["tool"] == "read_file"
    assert d["args"] == {"path": "x.py"}


def test_parse_fenced_json():
    d = parse_decision('here:\n```json\n{"action":"reason"}\n```\nok', TOOLS)
    assert d and d["action"] == "reason"


def test_parse_repairs_trailing_comma():
    d = parse_decision('{"action":"reason","args":{"a":1},}', TOOLS)
    assert d and d["action"] == "reason"


def test_unknown_tool_is_nulled():
    d = parse_decision('{"action":"tool","tool":"definitely_not_a_tool"}', TOOLS)
    assert d is not None and d["tool"] is None  # unknown tool dropped, not executed


def test_think_and_none_actions_drop_tool():
    for act in ("think", "none"):
        d = parse_decision('{"action":"%s","tool":"read_file"}' % act, TOOLS)
        assert d and d["tool"] is None


def test_unparseable_returns_none():
    assert parse_decision("no json here at all", TOOLS) is None
    assert parse_decision("", TOOLS) is None
    assert parse_decision("{not: valid, json", TOOLS) is None


def test_prose_wrapped_object_is_extracted():
    d = parse_decision('Sure! {"action":"tool","tool":"shell","args":{"argv":["ls"]}} done', TOOLS)
    assert d and d["action"] == "tool" and d["tool"] == "shell"


def test_invalid_action_defaults_to_reason():
    d = parse_decision('{"action":"banana"}', TOOLS)
    assert d and d["action"] == "reason"


# ── completion gate ──────────────────────────────────────────────────────────
def test_gate_rejects_empty_and_short():
    ok, reasons = passes_completion_gate(goal="do x", text="")
    assert ok is False and "empty_response" in reasons
    ok2, reasons2 = passes_completion_gate(goal="do x", text="short")
    assert ok2 is False and "too_short" in reasons2


def test_gate_rejects_goal_restatement():
    goal = "refactor the authentication middleware to support tokens"
    ok, reasons = passes_completion_gate(goal=goal, text=goal + " refactor authentication middleware tokens")
    assert ok is False
    assert any(r.startswith("restates_goal") for r in reasons)


def test_gate_rejects_tool_use_without_success():
    state = {"tool_calls": 2, "steps": [{"action": "shell", "result": {"ok": False}}]}
    ok, reasons = passes_completion_gate(
        goal="list the files",
        text="I attempted to list the files but here is a long enough explanation of what happened.",
        state=state,
    )
    assert ok is False
    assert any("tool" in r for r in reasons)


def test_gate_passes_good_answer():
    ok, reasons = passes_completion_gate(
        goal="explain what a mutex is",
        text="A mutex is a synchronization primitive that enforces mutually exclusive access "
             "to a shared resource so only one thread holds it at a time; others block until release.",
    )
    assert ok is True and reasons == []


def test_gate_passes_with_successful_tool_step():
    state = {"tool_calls": 1, "steps": [{"action": "read_file", "result": {"ok": True}}]}
    ok, reasons = passes_completion_gate(
        goal="read the config",
        text="The config sets n_ctx to 4096 and enables the completion gate; here is the relevant detail.",
        state=state,
    )
    assert ok is True and reasons == []
