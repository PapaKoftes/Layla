"""Tests for the bounded model cache (F9: unbounded _llm_by_path -> OOM SPOF).

Multi-model routing (coding/reasoning/chat/dual-model/fallback-chain) loaded a
new multi-GB GGUF per distinct path with no eviction, so a 2nd/3rd routed model
OOMed the single server process. _evict_models_if_needed bounds it: evict the
oldest NON-primary model(s) to stay within max_resident_models; never evict the
primary (_llm). Pure logic — uses fakes, no real model.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import services.llm.llm_gateway as g # noqa: E402


class _Fake:
    def __init__(self, name):
        self.name = name
        self.closed = False
    def close(self):
        self.closed = True


def _reset():
    g._llm_by_path.clear()
    g._llm = None


def test_evicts_oldest_non_primary_and_frees_it():
    _reset()
    prim, cod = _Fake("default"), _Fake("coding")
    g._llm_by_path["/m/default.gguf"] = prim
    g._llm_by_path["/m/coding.gguf"] = cod
    g._llm = prim
    evicted = g._evict_models_if_needed(2)  # making room for a 3rd
    assert evicted == ["/m/coding.gguf"]
    assert cod.closed is True                      # freed
    assert "/m/default.gguf" in g._llm_by_path     # primary retained
    assert prim.closed is False
    _reset()


def test_never_evicts_the_lone_primary():
    _reset()
    prim = _Fake("default")
    g._llm_by_path["/m/default.gguf"] = prim
    g._llm = prim
    assert g._evict_models_if_needed(1) == []      # only primary -> keep it
    assert "/m/default.gguf" in g._llm_by_path and prim.closed is False
    _reset()


def test_bound_holds_across_repeated_inserts():
    _reset()
    prim = _Fake("default")
    g._llm_by_path["/m/default.gguf"] = prim
    g._llm = prim
    # Simulate loading several routed models with cap=2: evict-then-insert each.
    for name in ("coding", "reasoning", "chat"):
        g._evict_models_if_needed(2)
        g._llm_by_path[f"/m/{name}.gguf"] = _Fake(name)
        assert len(g._llm_by_path) <= 2            # never grows past the cap
    assert "/m/default.gguf" in g._llm_by_path     # primary survived all rounds
    _reset()


def test_bad_cap_falls_back_to_default():
    _reset()
    prim = _Fake("default")
    g._llm_by_path["/m/default.gguf"] = prim
    g._llm = prim
    # invalid cap must not crash; treated as the default bound
    assert g._evict_models_if_needed("not-a-number") == []
    _reset()
