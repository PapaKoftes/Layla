"""One hallucinated argument name destroyed the entire agent run. For 16 days. Every time.

The dispatch site was:

    result = TOOLS[intent]["fn"](**args) if args else TOOLS[intent]["fn"]()

`args` comes from the MODEL. A 3B invents plausible-but-wrong parameter names constantly, and each
one raised TypeError out of the tool call:

    search_memories() got an unexpected keyword argument 'max_results'    (the real parameter is `n`)

Because `state["steps"].append(...)` runs AFTER the call, the exception meant the step was never
recorded. Measured on the live DB: 104 completed runs across 16 days, ZERO with any tool step — not
because tools were never chosen, but because choosing one with a single wrong argument name killed
the turn before it could be logged. Upstream the exception surfaced as an ordinary reply, so the
symptom read as "the model prefers to reason" rather than "the dispatcher crashes".

Proved by running the real loop on a novel goal, before and after:

    before:  steps == ['reason']                              (TypeError, run destroyed)
    after:   steps == ['think', 'search_memories', 'reason']  (tool executed, run continued)

Model output is untrusted input. These tests pin that it is bound to the real signature.
"""
from __future__ import annotations

import pytest

from services.tools.tool_dispatch import invoke_tool


def _search(query: str, n: int = 8) -> dict:
    """Mirrors the real search_memories signature that triggered the bug."""
    return {"ok": True, "query": query, "n": n}


def _reader(path: str) -> dict:
    return {"ok": True, "path": path}


def _kwargs_tool(**kw) -> dict:
    return {"ok": True, "got": sorted(kw)}


class TestAHallucinatedArgumentDoesNotKillTheRun:
    def test_the_exact_bug(self):
        """`max_results` instead of `n` — the argument that cost 104 runs."""
        out = invoke_tool("search_memories", _search, {"query": "hello", "max_results": 1})
        assert out["ok"] is True, "a near-miss argument name must not destroy the call"
        assert out["query"] == "hello", "the VALID argument must still be passed through"
        assert out["n"] == 8, "the tool's own default must apply for the dropped one"

    def test_the_drop_is_reported_not_hidden(self):
        out = invoke_tool("search_memories", _search, {"query": "x", "max_results": 1, "limit": 2})
        assert out.get("ignored_args") == ["limit", "max_results"], (
            "silently ignoring model arguments teaches it nothing; the result must say what was dropped"
        )

    def test_a_valid_call_is_untouched(self):
        out = invoke_tool("search_memories", _search, {"query": "x", "n": 3})
        assert out == {"ok": True, "query": "x", "n": 3}
        assert "ignored_args" not in out

    def test_no_args_still_works(self):
        assert invoke_tool("read_file", lambda: {"ok": True}, {})["ok"] is True


class TestMissingRequiredArgsTeachRatherThanCrash:
    def test_a_missing_required_arg_returns_a_usable_error(self):
        out = invoke_tool("read_file", _reader, {"filename": "README.md"})
        assert out["ok"] is False
        assert "path" in out["error"], "the error must name the argument that was missing"
        assert out["accepted_args"] == ["path"], (
            "the model needs the ACCEPTED parameter names to retry correctly — an error that only "
            "says 'failed' produces another wrong guess"
        )
        assert out["ignored_args"] == ["filename"]

    def test_it_does_not_raise(self):
        """The whole point: dispatch must survive any argument the model invents."""
        for bad in ({"nonsense": 1}, {"path": "x", "extra": 2, "more": 3}, {}):
            out = invoke_tool("read_file", _reader, bad)
            assert isinstance(out, dict), f"invoke_tool raised or returned non-dict for {bad!r}"


class TestPassthroughCases:
    def test_a_kwargs_tool_receives_everything(self):
        """A tool that declares **kwargs genuinely accepts unknown names — do not filter it."""
        out = invoke_tool("flexible", _kwargs_tool, {"anything": 1, "at_all": 2})
        assert out["got"] == ["anything", "at_all"]

    def test_an_uninspectable_callable_is_called_directly(self):
        out = invoke_tool("builtin_like", dict, {"a": 1})
        assert out == {"a": 1}

    def test_a_typeerror_from_inside_the_tool_is_reported_not_raised(self):
        def _boom(path: str) -> dict:
            raise TypeError("something deep exploded")

        out = invoke_tool("boom", _boom, {"path": "x"})
        assert out["ok"] is False and "rejected its arguments" in out["error"]


def test_every_dispatch_site_is_guarded():
    """The bug was one unguarded splat. An AST sweep keeps a new one from reappearing."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "services" / "tools" / "tool_dispatch.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # TOOLS[...]["fn"](**anything)
        fn = node.func
        if not (isinstance(fn, ast.Subscript) and isinstance(fn.slice, ast.Constant) and fn.slice.value == "fn"):
            continue
        if any(isinstance(k, ast.keyword) and k.arg is None for k in node.keywords):
            offenders.append(node.lineno)
    assert not offenders, (
        f"unguarded TOOLS[...]['fn'](**args) splat at line(s) {offenders} — model-supplied arguments "
        "must go through invoke_tool(), or one wrong parameter name destroys the whole run again"
    )
