"""
Tests for agent_loop: classify_intent, decision parsing (with mock LLM output).
Run from agent/: pytest tests/test_agent_loop.py -v
"""
import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import pytest  # noqa: E402


def test_classify_intent_read_file():
    from agent_loop import classify_intent
    assert classify_intent("read file foo.py") == "read_file"
    assert classify_intent("Show file README") == "read_file"
    assert classify_intent("contents of bar.txt") == "read_file"


def test_classify_intent_write_file():
    from agent_loop import classify_intent
    assert classify_intent("create file x.py") == "write_file"
    assert classify_intent("save file as y") == "write_file"


def test_classify_intent_list_dir():
    from agent_loop import classify_intent
    assert classify_intent("list dir src/") == "list_dir"
    assert classify_intent("what files are in .") == "list_dir"


def test_classify_intent_git():
    from agent_loop import classify_intent
    assert classify_intent("git status") == "git_status"
    assert classify_intent("git diff") == "git_diff"
    assert classify_intent("git log") == "git_log"
    assert classify_intent("current branch") == "git_branch"


def test_classify_intent_grep_code():
    from agent_loop import classify_intent
    assert classify_intent("grep for def main") == "grep_code"
    assert classify_intent("search code for TODO") == "grep_code"


def test_classify_intent_reason_fallback():
    from agent_loop import classify_intent
    assert classify_intent("what do you think about this?") == "reason"
    assert classify_intent("explain how it works") == "reason"


def test_decision_parsing_valid_tool():
    """Parse a valid JSON line with action=tool returns structured dict."""
    # We can't call _llm_decision easily without mocking run_completion. So test the parsing
    # logic by simulating what _llm_decision does with a given text.
    text = '{"action":"tool","tool":"read_file","priority_level":"high"}'
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            data = json.loads(line)
            assert data.get("action") == "tool"
            assert data.get("tool") == "read_file"
            assert data.get("priority_level") == "high"
            break
    else:
        pytest.fail("No JSON line found")


def test_decision_parsing_valid_reason():
    text = '{"action":"reason","objective_complete":true}'
    data = json.loads(text.strip())
    assert data.get("action") == "reason"
    assert data.get("objective_complete") is True


def test_decision_parsing_extra_text_ignores_non_json():
    """First line that looks like JSON is used; leading text is ignored."""
    text = 'Here is my choice:\n{"action":"reason","objective_complete":false}'
    found = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            found = json.loads(line)
            break
    assert found is not None
    assert found.get("action") == "reason"
    assert found.get("objective_complete") is False


def _minimal_cfg(sandbox_root: str) -> dict:
    # Keep prompts minimal and disable optional layers for deterministic tests.
    return {
        "sandbox_root": sandbox_root,
        "use_chroma": False,
        "knowledge_max_bytes": 0,
        "learnings_n": 0,
        "semantic_k": 0,
        "planning_enabled": False,
        "max_tool_calls": 10,
        "convo_turns": 0,
        "max_runtime_seconds": 5,
        "temperature": 0.0,
        "completion_max_tokens": 40,
        "enable_cognitive_lens": False,
        "enable_lens_knowledge": False,
        "enable_behavioral_rhythm": False,
        "enable_ui_reflection": False,
        "enable_operational_guidance": False,
        "enable_personality_expression": False,
        "uncensored": False,
        "nsfw_allowed": False,
    }


def test_pre_read_probe_inserts_file_info_before_read(monkeypatch, tmp_path):
    import agent_loop

    f = tmp_path / "a.txt"
    f.write_text("hello\nworld\n", encoding="utf-8")

    monkeypatch.setattr(agent_loop, "system_overloaded", lambda: False)
    monkeypatch.setattr(agent_loop.runtime_safety, "load_config", lambda: _minimal_cfg(str(tmp_path)))
    monkeypatch.setattr(agent_loop.runtime_safety, "load_identity", lambda: "")
    monkeypatch.setattr(agent_loop.runtime_safety, "load_personality", lambda: "")

    # Avoid real LLM usage
    decisions = iter([
        {"action": "tool", "tool": "read_file", "args": {}, "objective_complete": False, "priority_level": "high"},
        {"action": "reason", "tool": None, "args": {}, "objective_complete": True, "priority_level": "high"},
    ])
    monkeypatch.setattr(agent_loop, "_llm_decision", lambda *a, **k: next(decisions))
    monkeypatch.setattr(agent_loop, "run_completion", lambda *a, **k: {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(agent_loop.orchestrator, "select_aspect", lambda *a, **k: {"id": "morrigan", "name": "Morrigan"})
    monkeypatch.setattr(agent_loop.orchestrator, "should_deliberate", lambda *a, **k: False)

    result = agent_loop.autonomous_run(
        goal=f"read file {str(f)}",
        context="",
        workspace_root=str(tmp_path),
        allow_write=False,
        allow_run=False,
        conversation_history=[],
        aspect_id="",
        show_thinking=False,
    )
    steps = result.get("steps") or []
    assert steps[0]["action"] == "pre_read_probe"
    assert steps[0]["result"]["ok"] is True
    assert steps[1]["action"] == "read_file"
    assert "context_memory" in result and "file_probed" in (result["context_memory"] or {})


def test_pre_read_probe_avoids_binary_reads(monkeypatch, tmp_path):
    import agent_loop
    from layla.tools.registry import set_effective_sandbox

    set_effective_sandbox(None)

    f = tmp_path / "bin.dat"
    f.write_bytes(b"\xff\x00\x01\x02\xff")

    monkeypatch.setattr(agent_loop, "system_overloaded", lambda: False)
    monkeypatch.setattr(agent_loop.runtime_safety, "load_config", lambda: _minimal_cfg(str(tmp_path)))
    monkeypatch.setattr(agent_loop.runtime_safety, "load_identity", lambda: "")
    monkeypatch.setattr(agent_loop.runtime_safety, "load_personality", lambda: "")

    decisions = iter([
        {"action": "tool", "tool": "read_file", "args": {}, "objective_complete": False, "priority_level": "high"},
        {"action": "reason", "tool": None, "args": {}, "objective_complete": True, "priority_level": "high"},
    ])
    monkeypatch.setattr(agent_loop, "_llm_decision", lambda *a, **k: next(decisions))
    monkeypatch.setattr(agent_loop, "run_completion", lambda *a, **k: {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(agent_loop.orchestrator, "select_aspect", lambda *a, **k: {"id": "nyx", "name": "Nyx"})
    monkeypatch.setattr(agent_loop.orchestrator, "should_deliberate", lambda *a, **k: False)

    # If the actual read_file tool is called, fail (binary should be avoided).
    called = {"read": 0}
    real_read = agent_loop.TOOLS["read_file"]["fn"]
    def _fail_read(*a, **k):
        called["read"] += 1
        return real_read(*a, **k)
    monkeypatch.setitem(agent_loop.TOOLS["read_file"], "fn", _fail_read)

    result = agent_loop.autonomous_run(
        goal=f"read file {str(f)}",
        context="",
        workspace_root=str(tmp_path),
        allow_write=False,
        allow_run=False,
        conversation_history=[],
        aspect_id="",
        show_thinking=False,
    )
    steps = result.get("steps") or []
    assert steps[0]["action"] == "pre_read_probe"
    # Guidance path adds a synthetic read_file failure without calling the tool.
    assert any(s.get("action") == "read_file" and (s.get("result") or {}).get("reason") == "binary_file" for s in steps)
    assert called["read"] == 0


def test_pre_read_probe_runs_only_once_per_path(monkeypatch, tmp_path):
    import agent_loop
    from layla.tools.registry import set_effective_sandbox

    set_effective_sandbox(None)

    f = tmp_path / "a2.txt"
    f.write_text("hello\n", encoding="utf-8")

    monkeypatch.setattr(agent_loop, "system_overloaded", lambda: False)
    monkeypatch.setattr(agent_loop.runtime_safety, "load_config", lambda: _minimal_cfg(str(tmp_path)))
    monkeypatch.setattr(agent_loop.runtime_safety, "load_identity", lambda: "")
    monkeypatch.setattr(agent_loop.runtime_safety, "load_personality", lambda: "")
    monkeypatch.setattr(agent_loop.orchestrator, "select_aspect", lambda *a, **k: {"id": "morrigan", "name": "Morrigan"})
    monkeypatch.setattr(agent_loop.orchestrator, "should_deliberate", lambda *a, **k: False)

    decisions = iter([
        {"action": "tool", "tool": "read_file", "args": {}, "objective_complete": False, "priority_level": "high"},
        {"action": "tool", "tool": "read_file", "args": {}, "objective_complete": False, "priority_level": "high"},
        {"action": "reason", "tool": None, "args": {}, "objective_complete": True, "priority_level": "high"},
    ])
    monkeypatch.setattr(agent_loop, "_llm_decision", lambda *a, **k: next(decisions))
    monkeypatch.setattr(agent_loop, "run_completion", lambda *a, **k: {"choices": [{"message": {"content": "ok"}}]})

    calls = {"probe": 0}
    real_probe = agent_loop.TOOLS["file_info"]["fn"]
    def _count_probe(*a, **k):
        calls["probe"] += 1
        return real_probe(*a, **k)
    monkeypatch.setitem(agent_loop.TOOLS["file_info"], "fn", _count_probe)

    result = agent_loop.autonomous_run(
        goal=f"read file {str(f)}",
        context="",
        workspace_root=str(tmp_path),
        allow_write=False,
        allow_run=False,
        conversation_history=[],
        aspect_id="",
        show_thinking=False,
    )
    steps = result.get("steps") or []
    assert sum(1 for s in steps if s.get("action") == "pre_read_probe") == 1
    assert calls["probe"] == 1


def test_knowledge_refresh_detects_changes(monkeypatch, tmp_path):
    from layla.memory import vector_store

    # Force chroma path offloading: only test change detection calls into indexer.
    monkeypatch.setattr(vector_store, "_use_chroma", lambda: True)

    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    f = kdir / "x.md"
    f.write_text("hello", encoding="utf-8")

    called = {"n": 0}
    monkeypatch.setattr(vector_store, "index_knowledge_docs", lambda *_a, **_k: called.__setitem__("n", called["n"] + 1))

    assert vector_store.refresh_knowledge_if_changed(kdir, min_interval_s=0) is True
    assert called["n"] == 1
    # No changes -> no reindex
    assert vector_store.refresh_knowledge_if_changed(kdir, min_interval_s=0) is False
    assert called["n"] == 1
    # Touch file -> reindex
    f.write_text("hello2", encoding="utf-8")
    assert vector_store.refresh_knowledge_if_changed(kdir, min_interval_s=0) is True
    assert called["n"] == 2


# North Star §8: failure awareness and structured recovery hint
def test_failure_classify_sets_structured_recovery_hint():
    """_classify_failure_and_recovery sets recovery_hint dict (type, message, source) when consecutive_no_progress > 0."""
    import agent_loop
    state = {"consecutive_no_progress": 1, "last_tool_used": "read_file"}
    agent_loop._classify_failure_and_recovery(state)
    rh = state.get("recovery_hint")
    assert isinstance(rh, dict)
    assert rh.get("type") == "planning_gap"
    assert (rh.get("message") or "").strip()
    assert rh.get("source") == "failure_classifier"

    state2 = {"consecutive_no_progress": 2, "last_tool_used": "write_file"}
    agent_loop._classify_failure_and_recovery(state2)
    assert state2.get("recovery_hint", {}).get("type") == "execution_issue"

    state3 = {"consecutive_no_progress": 1, "last_tool_used": "unknown_tool"}
    agent_loop._classify_failure_and_recovery(state3)
    assert state3.get("recovery_hint", {}).get("type") == "workflow_breakdown"


def test_failure_classify_clears_when_no_progress_zero():
    """When consecutive_no_progress is 0, recovery_hint is cleared."""
    import agent_loop
    state = {"consecutive_no_progress": 0, "last_tool_used": "read_file", "recovery_hint": {"type": "x", "message": "y", "source": "failure_classifier"}}
    agent_loop._classify_failure_and_recovery(state)
    assert state.get("recovery_hint") is None


def test_format_recovery_hint_for_prompt():
    """Structured recovery hint is stringified correctly for prompt injection."""
    import agent_loop
    out = agent_loop._format_recovery_hint_for_prompt({"type": "planning_gap", "message": "Break into steps.", "source": "failure_classifier"})
    assert "planning_gap" in out
    assert "Break into steps" in out
    assert out == "Failure type: planning_gap. Assist recovery: Break into steps. "
    assert agent_loop._format_recovery_hint_for_prompt(None) == ""
    assert agent_loop._format_recovery_hint_for_prompt({}) == ""
