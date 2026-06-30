"""Tests for the heterogeneous-council per-aspect model routing.

Verifies (a) the config -> per-aspect model resolution and (b) that the model
override is applied for an aspect's call and restored afterward, so a pooled,
reused worker thread cannot leak one aspect's model into the next call.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.planning import debate_engine as de  # noqa: E402
from services.llm import llm_gateway as gw  # noqa: E402


def test_aspect_model_override_resolution():
    cfg = {"council_aspect_models": {"morrigan": "coding", "nyx": "reasoning"}}
    assert de._aspect_model_override("morrigan", cfg) == "coding"
    assert de._aspect_model_override("MORRIGAN", cfg) == "coding"  # lookup is case-insensitive
    assert de._aspect_model_override("nyx", cfg) == "reasoning"
    assert de._aspect_model_override("echo", cfg) is None  # unmapped -> default


def test_aspect_model_override_empty_or_invalid():
    assert de._aspect_model_override("morrigan", {}) is None
    assert de._aspect_model_override("morrigan", {"council_aspect_models": None}) is None
    assert de._aspect_model_override("morrigan", {"council_aspect_models": []}) is None
    assert de._aspect_model_override("morrigan", {"council_aspect_models": {"morrigan": ""}}) is None


def test_override_applied_then_restored(monkeypatch):
    seen = {}

    def fake_run_completion(prompt, **params):
        seen["override_during_call"] = gw.get_model_override()
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(gw, "run_completion", fake_run_completion)

    gw.set_model_override(None)
    cfg = {"council_aspect_models": {"morrigan": "coding"}}
    de._run_aspect_completion("morrigan", cfg, "hi", {"max_tokens": 10})
    assert seen["override_during_call"] == "coding"          # applied during the call
    assert gw.get_model_override() is None                    # restored afterward


def test_no_override_leak_across_aspects(monkeypatch):
    """Simulate two sequential calls on the same thread: the second aspect has no
    override and must NOT inherit the first aspect's model."""
    seen = []

    def fake_run_completion(prompt, **params):
        seen.append(gw.get_model_override())
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(gw, "run_completion", fake_run_completion)
    gw.set_model_override(None)
    cfg = {"council_aspect_models": {"morrigan": "coding"}}  # nyx unmapped

    de._run_aspect_completion("morrigan", cfg, "a", {"max_tokens": 10})
    de._run_aspect_completion("nyx", cfg, "b", {"max_tokens": 10})
    assert seen == ["coding", None]                           # nyx did NOT inherit "coding"
    assert gw.get_model_override() is None
