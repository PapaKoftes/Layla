"""BL-108: KV-cache prompt-prefix reuse — LlamaRAMCache attach, flag-gated."""
from __future__ import annotations

import sys
import types

import pytest

from services.llm import llm_gateway as gw


class _FakeInst:
    def __init__(self):
        self.cache = None

    def set_cache(self, c):
        self.cache = c


def _install_fake_llama(monkeypatch):
    mod = types.ModuleType("llama_cpp")

    class LlamaRAMCache:
        def __init__(self, capacity_bytes=0):
            self.capacity_bytes = capacity_bytes

    mod.LlamaRAMCache = LlamaRAMCache
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)
    return LlamaRAMCache


def test_apply_prompt_cache_attaches(monkeypatch):
    LlamaRAMCache = _install_fake_llama(monkeypatch)
    inst = _FakeInst()
    assert gw._apply_prompt_cache(inst, 256) is True
    assert isinstance(inst.cache, LlamaRAMCache)
    assert inst.cache.capacity_bytes == 256 * 1024 * 1024


def test_apply_prompt_cache_no_set_cache(monkeypatch):
    _install_fake_llama(monkeypatch)

    class NoCache:
        pass

    assert gw._apply_prompt_cache(NoCache(), 128) is False


def test_apply_prompt_cache_positional_fallback(monkeypatch):
    # some llama-cpp builds take a positional capacity, not the keyword
    mod = types.ModuleType("llama_cpp")

    class LlamaRAMCache:
        def __init__(self, capacity):  # positional-only
            self.capacity = capacity

    mod.LlamaRAMCache = LlamaRAMCache
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)
    inst = _FakeInst()
    assert gw._apply_prompt_cache(inst, 64) is True
    assert inst.cache.capacity == 64 * 1024 * 1024


def test_apply_prompt_cache_unavailable(monkeypatch):
    mod = types.ModuleType("llama_cpp")  # no LlamaRAMCache attribute
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)
    monkeypatch.setitem(sys.modules, "llama_cpp.llama_cache", types.ModuleType("llama_cpp.llama_cache"))
    assert gw._apply_prompt_cache(_FakeInst(), 128) is False
