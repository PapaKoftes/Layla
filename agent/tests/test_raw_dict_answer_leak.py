"""Regression: a run that only made (failed) tool calls must not leak a raw tool dict.

The golden eval surfaced answers like `{"ok": false, "error": "Path not found"}` for
trivial questions ("capital of France"). looks_like_raw_tool_dict detects that leak and
synthesize_direct_answer answers the question from the model instead.
"""
from __future__ import annotations

from services.agent import response_builder as rb


def test_looks_like_raw_tool_dict_detects_error_dicts():
    assert rb.looks_like_raw_tool_dict('{"ok": false, "error": "Path not found"}')
    assert rb.looks_like_raw_tool_dict('{"ok": false, "reason": "tool_policy_denied"}')
    assert rb.looks_like_raw_tool_dict('{"ok": true, "memories": [], "_empty_output": true}')
    assert rb.looks_like_raw_tool_dict('{"ok": false, "output": "", "error": "tool_returned_no_ok"}')


def test_looks_like_raw_tool_dict_ignores_real_answers():
    assert not rb.looks_like_raw_tool_dict("The capital of France is Paris.")
    assert not rb.looks_like_raw_tool_dict("")
    assert not rb.looks_like_raw_tool_dict("Here's a dict: {not json at all")
    assert not rb.looks_like_raw_tool_dict('{"title": "a normal json object without error keys"}')


def test_synthesize_direct_answer_uses_model(monkeypatch):
    def _fake_completion(prompt, **kw):
        assert "capital of France" in prompt
        return {"choices": [{"message": {"content": "The capital of France is Paris."}}]}

    monkeypatch.setattr("services.llm.llm_gateway.run_completion", _fake_completion, raising=False)
    out = rb.synthesize_direct_answer("What is the capital of France?")
    assert "Paris" in out


def test_synthesize_empty_goal():
    assert rb.synthesize_direct_answer("") == ""


def test_synthesize_never_returns_a_dict_leak(monkeypatch):
    # even if the model somehow returns a dict-shaped string, don't pass it through
    monkeypatch.setattr(
        "services.llm.llm_gateway.run_completion",
        lambda prompt, **kw: {"choices": [{"message": {"content": '{"ok": false, "error": "x"}'}}]},
        raising=False,
    )
    assert rb.synthesize_direct_answer("hi") == ""


def test_synthesize_model_unavailable(monkeypatch):
    def _boom(prompt, **kw):
        raise RuntimeError("no model")
    monkeypatch.setattr("services.llm.llm_gateway.run_completion", _boom, raising=False)
    assert rb.synthesize_direct_answer("anything") == ""


def test_reexported_from_agent_loop():
    import agent_loop
    assert agent_loop._looks_like_raw_tool_dict('{"ok": false, "error": "x"}')
    assert callable(agent_loop._synthesize_direct_answer)
