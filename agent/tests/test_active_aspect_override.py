"""
Per-aspect model override wiring (P4/P5): the active-aspect ContextVar makes an
aspect's configured model win in the gateway's live model resolution.

The model-swap itself needs two models resident (a bigger box); these tests verify the
*resolution* — that _effective_model_filename honours aspect_model_overrides when an
active aspect is set, and is a no-op otherwise.
"""
from __future__ import annotations

from services.llm import llm_gateway
from services.llm.model_router import reset_router_config_cache

_CFG = {
    "model_filename": "default.gguf",
    "aspect_model_overrides": {"nyx": {"preferred_model": "nyx-deep.gguf"}},
}


def _use_cfg(monkeypatch):
    monkeypatch.setattr("runtime_safety.load_config", lambda: dict(_CFG))
    reset_router_config_cache()


def test_active_aspect_override_wins(monkeypatch):
    _use_cfg(monkeypatch)
    tok = llm_gateway.set_active_aspect("nyx")
    try:
        assert llm_gateway._effective_model_filename(dict(_CFG)) == "nyx-deep.gguf"
    finally:
        llm_gateway.reset_active_aspect(tok)
        reset_router_config_cache()


def test_no_active_aspect_falls_through(monkeypatch):
    _use_cfg(monkeypatch)
    # no aspect set -> normal routing -> the default model
    assert llm_gateway._effective_model_filename(dict(_CFG)) == "default.gguf"
    reset_router_config_cache()


def test_active_aspect_without_override_falls_through(monkeypatch):
    _use_cfg(monkeypatch)
    tok = llm_gateway.set_active_aspect("morrigan")  # no override configured for morrigan
    try:
        assert llm_gateway._effective_model_filename(dict(_CFG)) == "default.gguf"
    finally:
        llm_gateway.reset_active_aspect(tok)
        reset_router_config_cache()


def test_set_reset_are_leak_safe(monkeypatch):
    _use_cfg(monkeypatch)
    assert llm_gateway.get_active_aspect() is None
    tok = llm_gateway.set_active_aspect("nyx")
    assert llm_gateway.get_active_aspect() == "nyx"
    llm_gateway.reset_active_aspect(tok)
    assert llm_gateway.get_active_aspect() is None
    # blank id normalises to None (no spurious override lookups)
    tok2 = llm_gateway.set_active_aspect("   ")
    assert llm_gateway.get_active_aspect() is None
    llm_gateway.reset_active_aspect(tok2)
