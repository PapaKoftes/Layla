# -*- coding: utf-8 -*-
"""
O-7 regression: budget CJK/non-Latin text with the exact model tokenizer, not tiktoken.

tiktoken's cl100k_base over-counts non-Latin scripts (up to +100% for Chinese), so budgeting with
it silently over-truncates a CJK user's context against the shipped 11-language UI. When a model is
resident, count_tokens must use its exact tokenizer for non-ASCII text; ASCII stays on tiktoken
(0% divergence, cheaper hot path); with no model resident it falls back to tiktoken cleanly.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.llm import token_count as tc  # noqa: E402


class _FakeModel:
    """Stand-in for a resident Llama: 1 token per Unicode codepoint (deliberately != tiktoken)."""

    def __init__(self):
        self.calls = []

    def tokenize(self, b, add_bos=False, special=False):
        self.calls.append(b)
        return list(range(len(b.decode("utf-8", "ignore"))))


def test_no_resident_model_falls_back_and_never_crashes(monkeypatch):
    monkeypatch.setattr(tc, "_resident_model_token_count", lambda _t: None)
    # Non-ASCII still counts (via tiktoken or the char heuristic) and is positive.
    assert tc.count_tokens("你好世界，这是一个测试。") > 0
    assert tc.count_tokens("hello world") > 0


def test_non_ascii_uses_resident_model_tokenizer(monkeypatch):
    fake = _FakeModel()
    monkeypatch.setattr("services.llm.llm_gateway.get_resident_model", lambda: fake, raising=False)
    text = "你好世界"  # 4 codepoints
    assert tc.count_tokens(text) == 4  # exact model path, not tiktoken's count
    assert fake.calls, "resident model tokenizer must be used for non-ASCII text"


def test_ascii_does_not_touch_the_model_tokenizer(monkeypatch):
    fake = _FakeModel()
    monkeypatch.setattr("services.llm.llm_gateway.get_resident_model", lambda: fake, raising=False)
    n = tc.count_tokens("hello world, this is plain ASCII code()")
    assert n > 0
    assert fake.calls == [], "ASCII must stay on tiktoken; the model tokenizer must not be called"


def test_resident_token_count_swallows_tokenizer_errors(monkeypatch):
    class _Boom:
        def tokenize(self, *a, **k):
            raise RuntimeError("native boom")

    monkeypatch.setattr("services.llm.llm_gateway.get_resident_model", lambda: _Boom(), raising=False)
    # A tokenizer error must degrade to the fallback, never propagate.
    assert tc._resident_model_token_count("你好") is None
    assert tc.count_tokens("你好") > 0
