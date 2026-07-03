"""
Tests for native GBNF constrained decoding — services/llm/gbnf_grammar.py.

The grammar *builder* is pure and tested without a model. The strongest checks
compile the generated GBNF with the real ``llama_cpp.LlamaGrammar`` parser (present
in the test venv) to prove it is well-formed — the model-in-the-loop reliability gain
is a separate, app-running verification.
"""
from __future__ import annotations

import pytest

from services.llm.gbnf_grammar import (
    build_decision_grammar,
    escape_gbnf_literal,
    gbnf_decoding_available,
    run_gbnf_agent_decision,
)

SAMPLE_TOOLS = ["read_file", "grep_code", "write_file", "run_shell"]


def _tool_rule_line(grammar: str) -> str:
    return grammar.split("tool ::=")[1].splitlines()[0]


class TestBuildDecisionGrammar:
    def test_has_all_named_rules(self):
        g = build_decision_grammar(SAMPLE_TOOLS)
        assert g.strip()
        rule_names = {ln.split("::=")[0].strip() for ln in g.splitlines() if "::=" in ln}
        for name in ("root", "action", "tool", "priority", "object", "string", "ws", "value", "boolean"):
            assert name in rule_names, f"missing rule {name!r}"

    def test_contains_each_tool_as_json_terminal(self):
        g = build_decision_grammar(SAMPLE_TOOLS)
        for t in SAMPLE_TOOLS:
            assert f'\\"{t}\\"' in g, f"tool {t!r} not pinned in grammar"

    def test_tool_rule_allows_null(self):
        assert "null" in _tool_rule_line(build_decision_grammar(SAMPLE_TOOLS))

    def test_action_enum_pinned(self):
        g = build_decision_grammar(SAMPLE_TOOLS)
        for a in ("tool", "reason", "think", "none"):
            assert f'\\"{a}\\"' in g

    def test_priority_enum_pinned(self):
        g = build_decision_grammar(SAMPLE_TOOLS)
        for p in ("low", "medium", "high"):
            assert f'\\"{p}\\"' in g

    def test_empty_tools_falls_back_to_free_string(self):
        assert "string" in _tool_rule_line(build_decision_grammar([]))

    def test_none_tools_is_safe(self):
        # None must not raise; behaves like empty.
        assert "string" in _tool_rule_line(build_decision_grammar(None))

    def test_dedup_and_strip(self):
        g = build_decision_grammar(["read_file", " read_file ", "grep_code", "", None])
        assert _tool_rule_line(g).count('\\"read_file\\"') == 1


class TestEscape:
    def test_escapes_quote(self):
        assert escape_gbnf_literal('a"b') == 'a\\"b'

    def test_escapes_backslash(self):
        assert escape_gbnf_literal("a\\b") == "a\\\\b"

    def test_special_char_tool_builds(self):
        # Must not raise even with quote/backslash in a tool name.
        g = build_decision_grammar(['weird"tool', "back\\slash", "normal"])
        assert "root ::=" in g


@pytest.mark.skipif(not gbnf_decoding_available(), reason="llama_cpp not installed")
class TestGrammarCompiles:
    """The real proof: llama.cpp's grammar parser accepts the generated GBNF."""

    def _compile(self, grammar: str):
        from llama_cpp import LlamaGrammar

        return LlamaGrammar.from_string(grammar, verbose=False)

    def test_compiles_with_tools(self):
        assert self._compile(build_decision_grammar(SAMPLE_TOOLS)) is not None

    def test_compiles_empty_tools(self):
        assert self._compile(build_decision_grammar([])) is not None

    def test_compiles_with_special_chars(self):
        # Quote and backslash in tool names must not produce malformed GBNF.
        assert self._compile(build_decision_grammar(['a"b', "c\\d", "normal_tool"])) is not None

    def test_compiles_single_tool(self):
        assert self._compile(build_decision_grammar(["only_one"])) is not None


class TestRunGbnfAgentDecision:
    def test_returns_none_when_completion_raises(self):
        class BadLLM:
            def create_completion(self, *a, **k):
                raise RuntimeError("boom")

        out = run_gbnf_agent_decision(
            BadLLM(), "p", max_tokens=64, temperature=0.1, valid_tools=frozenset(SAMPLE_TOOLS)
        )
        assert out is None

    def test_returns_none_on_empty_text(self):
        class EmptyLLM:
            def create_completion(self, *a, **k):
                return {"choices": [{"text": "   "}]}

        out = run_gbnf_agent_decision(
            EmptyLLM(), "p", max_tokens=64, temperature=0.1, valid_tools=frozenset(SAMPLE_TOOLS)
        )
        assert out is None

    @pytest.mark.skipif(not gbnf_decoding_available(), reason="llama_cpp not installed")
    def test_parses_constrained_completion(self):
        # Grammar compiles for real; the completion text is stubbed (no model needed).
        seen = {}

        class FakeLLM:
            def create_completion(self, prompt, **k):
                seen["grammar_passed"] = k.get("grammar") is not None
                return {
                    "choices": [
                        {"text": '{"action":"tool","tool":"read_file","priority_level":"high","objective_complete":false}'}
                    ]
                }

        out = run_gbnf_agent_decision(
            FakeLLM(), "p", max_tokens=64, temperature=0.1, valid_tools=frozenset(SAMPLE_TOOLS)
        )
        assert seen.get("grammar_passed") is True, "grammar must be passed to create_completion"
        assert out is not None
        assert out["action"] == "tool"
        assert out["tool"] == "read_file"
        assert out["priority_level"] == "high"

    @pytest.mark.skipif(not gbnf_decoding_available(), reason="llama_cpp not installed")
    def test_hallucinated_tool_normalized_out(self):
        # Even if a stub emits a tool not in the valid set, parse_decision drops it.
        class FakeLLM:
            def create_completion(self, prompt, **k):
                return {"choices": [{"text": '{"action":"tool","tool":"not_a_real_tool"}'}]}

        out = run_gbnf_agent_decision(
            FakeLLM(), "p", max_tokens=64, temperature=0.1, valid_tools=frozenset(SAMPLE_TOOLS)
        )
        assert out is not None
        assert out["tool"] is None
