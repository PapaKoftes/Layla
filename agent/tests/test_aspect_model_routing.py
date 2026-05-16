# -*- coding: utf-8 -*-
"""
test_aspect_model_routing.py -- Unit tests for aspect-keyed model routing.

Tests aspect override returns preferred model, fallback to standard routing,
temperature_boost application, and tool preferences per aspect.

Run:
    cd agent/ && python -m pytest tests/test_aspect_model_routing.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.aspect_behavior import (
    ASPECT_TOOL_PREFERENCES,
    get_tool_preferences,
)
from services.model_router import (
    _resolve_aspect_model,
    get_aspect_routing_params,
    get_model_for_task,
    reset_router_config_cache,
    route_model,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg_with_aspect_overrides(overrides: dict, **extra) -> dict:
    """Build a minimal config dict with aspect_model_overrides."""
    cfg = {
        "model_filename": "default.gguf",
        "coding_model": "coding.gguf",
        "reasoning_model": "reasoning.gguf",
        "chat_model": "chat.gguf",
        "models": {},
        "aspect_model_overrides": overrides,
    }
    cfg.update(extra)
    return cfg


# ---------------------------------------------------------------------------
# route_model with aspect_id
# ---------------------------------------------------------------------------

class TestRouteModelAspectOverride:
    """route_model() respects aspect_model_overrides when aspect_id is given."""

    def test_aspect_override_returns_preferred_model(self, monkeypatch):
        """When an aspect has a preferred_model configured, route_model returns it."""
        reset_router_config_cache()
        cfg = _cfg_with_aspect_overrides({
            "nyx": {"preferred_model": "nyx-deep.gguf"},
        })
        monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
        reset_router_config_cache()

        result = route_model("coding", aspect_id="nyx")
        assert result == "nyx-deep.gguf"

    def test_aspect_override_takes_priority_over_task_type(self, monkeypatch):
        """Aspect preferred_model wins even for coding/reasoning tasks."""
        reset_router_config_cache()
        cfg = _cfg_with_aspect_overrides({
            "cassandra": {"preferred_model": "cassandra-analytical.gguf"},
        })
        monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
        reset_router_config_cache()

        for task_type in ("coding", "reasoning", "chat", "default"):
            result = route_model(task_type, aspect_id="cassandra")
            assert result == "cassandra-analytical.gguf", (
                f"Expected cassandra override for task_type={task_type}"
            )

    def test_no_aspect_id_falls_back_to_standard(self, monkeypatch):
        """When aspect_id is None, standard task-type routing applies."""
        reset_router_config_cache()
        cfg = _cfg_with_aspect_overrides({
            "nyx": {"preferred_model": "nyx-deep.gguf"},
        })
        monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
        reset_router_config_cache()

        result = route_model("coding", aspect_id=None)
        assert result == "coding.gguf"

    def test_unknown_aspect_falls_back_to_standard(self, monkeypatch):
        """An aspect_id not in the overrides dict falls through to standard routing."""
        reset_router_config_cache()
        cfg = _cfg_with_aspect_overrides({
            "nyx": {"preferred_model": "nyx-deep.gguf"},
        })
        monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
        reset_router_config_cache()

        result = route_model("chat", aspect_id="unknown_aspect")
        assert result == "chat.gguf"

    def test_empty_preferred_model_falls_through(self, monkeypatch):
        """When preferred_model is empty string, fallback to standard routing."""
        reset_router_config_cache()
        cfg = _cfg_with_aspect_overrides({
            "echo": {"preferred_model": "", "temperature_boost": 0.1},
        })
        monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
        reset_router_config_cache()

        result = route_model("reasoning", aspect_id="echo")
        assert result == "reasoning.gguf"

    def test_no_overrides_config_key_falls_through(self, monkeypatch):
        """When aspect_model_overrides is not in config at all, standard routing works."""
        reset_router_config_cache()
        cfg = {
            "model_filename": "default.gguf",
            "coding_model": "coding.gguf",
            "reasoning_model": None,
            "chat_model": None,
            "models": {},
        }
        monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
        reset_router_config_cache()

        result = route_model("coding", aspect_id="nyx")
        assert result == "coding.gguf"


# ---------------------------------------------------------------------------
# _resolve_aspect_model internal
# ---------------------------------------------------------------------------

class TestResolveAspectModel:
    """Low-level resolution of aspect model overrides."""

    def test_none_aspect_returns_none(self, monkeypatch):
        model, cfg = _resolve_aspect_model(None)
        assert model is None
        assert cfg == {}

    def test_empty_string_aspect_returns_none(self, monkeypatch):
        model, cfg = _resolve_aspect_model("")
        assert model is None
        assert cfg == {}

    def test_valid_aspect_returns_model_and_config(self, monkeypatch):
        overrides = {
            "eris": {"preferred_model": "eris-creative.gguf", "temperature_boost": 0.2},
        }
        monkeypatch.setattr("runtime_safety.load_config", lambda: {
            "aspect_model_overrides": overrides,
        })

        model, aspect_cfg = _resolve_aspect_model("eris")
        assert model == "eris-creative.gguf"
        assert aspect_cfg["temperature_boost"] == 0.2

    def test_alias_resolution(self, monkeypatch):
        """If preferred_model is a known alias, it gets resolved."""
        overrides = {
            "nyx": {"preferred_model": "magicoder"},
        }
        monkeypatch.setattr("runtime_safety.load_config", lambda: {
            "aspect_model_overrides": overrides,
        })

        model, _ = _resolve_aspect_model("nyx")
        # "magicoder" alias should resolve to the full GGUF name
        assert model == "Magicoder-S-DS-6.7B-Instruct.Q4_K_M.gguf"


# ---------------------------------------------------------------------------
# get_aspect_routing_params
# ---------------------------------------------------------------------------

class TestGetAspectRoutingParams:
    """get_aspect_routing_params() extracts temperature_boost and reasoning_mode."""

    def test_temperature_boost_returned(self, monkeypatch):
        overrides = {
            "eris": {"preferred_model": "eris.gguf", "temperature_boost": 0.3},
        }
        monkeypatch.setattr("runtime_safety.load_config", lambda: {
            "aspect_model_overrides": overrides,
        })

        params = get_aspect_routing_params("eris")
        assert params["temperature_boost"] == 0.3
        assert params["preferred_model"] == "eris.gguf"

    def test_reasoning_mode_override(self, monkeypatch):
        overrides = {
            "cassandra": {
                "preferred_model": "cassandra.gguf",
                "reasoning_mode": "deep",
                "temperature_boost": 0.0,
            },
        }
        monkeypatch.setattr("runtime_safety.load_config", lambda: {
            "aspect_model_overrides": overrides,
        })

        params = get_aspect_routing_params("cassandra")
        assert params["reasoning_mode"] == "deep"

    def test_no_aspect_returns_defaults(self, monkeypatch):
        monkeypatch.setattr("runtime_safety.load_config", lambda: {
            "aspect_model_overrides": {},
        })

        params = get_aspect_routing_params(None)
        assert params["preferred_model"] is None
        assert params["temperature_boost"] == 0.0
        assert params["reasoning_mode"] is None

    def test_missing_fields_return_defaults(self, monkeypatch):
        overrides = {
            "echo": {},  # no preferred_model, no temperature_boost
        }
        monkeypatch.setattr("runtime_safety.load_config", lambda: {
            "aspect_model_overrides": overrides,
        })

        params = get_aspect_routing_params("echo")
        assert params["preferred_model"] is None
        assert params["temperature_boost"] == 0.0
        assert params["reasoning_mode"] is None


# ---------------------------------------------------------------------------
# get_model_for_task with aspect_id
# ---------------------------------------------------------------------------

class TestGetModelForTaskAspect:
    """get_model_for_task() forwards aspect_id to route_model."""

    def test_aspect_override_for_coding_task(self, monkeypatch):
        reset_router_config_cache()
        cfg = _cfg_with_aspect_overrides({
            "morrigan": {"preferred_model": "morrigan-planner.gguf"},
        })
        monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
        reset_router_config_cache()

        result = get_model_for_task("implement the feature", aspect_id="morrigan")
        assert result == "morrigan-planner.gguf"

    def test_no_aspect_id_standard_routing(self, monkeypatch):
        reset_router_config_cache()
        cfg = _cfg_with_aspect_overrides({})
        monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
        reset_router_config_cache()

        result = get_model_for_task("implement the feature")
        assert result == "coding.gguf"


# ---------------------------------------------------------------------------
# Tool preferences
# ---------------------------------------------------------------------------

class TestToolPreferences:
    """ASPECT_TOOL_PREFERENCES and get_tool_preferences()."""

    def test_cassandra_boosts_analysis_tools(self):
        prefs = get_tool_preferences("cassandra")
        assert "read_file" in prefs["boost"]
        assert "grep_code" in prefs["boost"]
        assert "run_python" in prefs["boost"]

    def test_cassandra_suppresses_fetch(self):
        prefs = get_tool_preferences("cassandra")
        assert "fetch_url" in prefs["suppress"]

    def test_echo_boosts_memory_tools(self):
        prefs = get_tool_preferences("echo")
        assert "search_memories" in prefs["boost"]
        assert "save_learning" in prefs["boost"]

    def test_echo_suppresses_shell(self):
        prefs = get_tool_preferences("echo")
        assert "run_shell" in prefs["suppress"]

    def test_nyx_boosts_code_tools(self):
        prefs = get_tool_preferences("nyx")
        assert "grep_code" in prefs["boost"]
        assert "git_log" in prefs["boost"]
        assert prefs["suppress"] == []

    def test_eris_boosts_web_tools(self):
        prefs = get_tool_preferences("eris")
        assert "web_search" in prefs["boost"]
        assert "fetch_url" in prefs["boost"]

    def test_morrigan_boosts_planning_tools(self):
        prefs = get_tool_preferences("morrigan")
        assert "create_plan" in prefs["boost"]
        assert "execute_plan" in prefs["boost"]

    def test_lilith_suppresses_dangerous_tools(self):
        prefs = get_tool_preferences("lilith")
        assert "run_shell" in prefs["suppress"]
        assert "run_python" in prefs["suppress"]
        assert "write_file" in prefs["suppress"]
        assert "search_memories" in prefs["boost"]

    def test_unknown_aspect_returns_empty(self):
        prefs = get_tool_preferences("nonexistent")
        assert prefs == {"boost": [], "suppress": []}

    def test_all_known_aspects_present(self):
        expected_aspects = {"cassandra", "echo", "nyx", "eris", "morrigan", "lilith"}
        assert set(ASPECT_TOOL_PREFERENCES.keys()) == expected_aspects

    def test_all_entries_have_boost_and_suppress(self):
        for aspect_id, prefs in ASPECT_TOOL_PREFERENCES.items():
            assert "boost" in prefs, f"{aspect_id} missing 'boost'"
            assert "suppress" in prefs, f"{aspect_id} missing 'suppress'"
            assert isinstance(prefs["boost"], list), f"{aspect_id} boost not a list"
            assert isinstance(prefs["suppress"], list), f"{aspect_id} suppress not a list"
