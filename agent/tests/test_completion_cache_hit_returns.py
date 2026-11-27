"""A completion-cache hit returns the cached completion (it used to raise on every hit).

The hit path reset the routing-prompt ContextVar token and the function's `finally` reset it again:
RuntimeError("<Token ...> has already been used once"), which the `finally` did not catch. Live log: every
turn, "project_discovery completion failed: <Token used var=<ContextVar name='routing_prompt' ...>> has
already been used once". No test had ever exercised a hit.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

HIT = {"choices": [{"message": {"content": "cached answer"}}]}


def test_cache_hit_returns_the_cached_completion_and_clears_routing_prompt(monkeypatch):
    import runtime_safety
    import services.llm.inference_router as ir
    import services.retrieval.completion_cache as cc
    from services.llm import llm_gateway as gw

    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: {"completion_cache_enabled": True})
    lookups = []

    def _hit(*a, **k):
        lookups.append(a)
        return HIT

    monkeypatch.setattr(cc, "get_cached", _hit)

    def _no_inference(*a, **k):
        raise AssertionError("a cache hit must not run inference")

    monkeypatch.setattr(ir, "run_completion", _no_inference)

    for _ in range(2):  # repeated hits, as project_discovery does every turn
        assert gw.run_completion("same prompt", max_tokens=32, temperature=0.0) is HIT
    assert len(lookups) == 2, "PROBE BROKEN: the cache was not consulted, so no hit path ran"
    assert gw._routing_prompt_var.get(None) is None
