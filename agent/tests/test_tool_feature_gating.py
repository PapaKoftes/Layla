"""BL-205: disabled-feature tools are hidden from the model's decision set."""
from __future__ import annotations

from services.agent import llm_decision as ld


_REGISTRY = {
    "read_file": {"category": "file"},
    "analyze_image": {"category": "data", "feature": "vision"},
    "mcp_call": {"category": "system", "feature": "mcp"},
    "reason": {},
}


def test_drops_disabled_feature_tool(monkeypatch):
    monkeypatch.setattr("install.setup_profiles.enabled_feature_ids", lambda cfg=None: ["mcp"])
    kept = ld._drop_disabled_feature_tools({"read_file", "analyze_image", "mcp_call"}, _REGISTRY, {})
    assert "analyze_image" not in kept       # vision disabled → hidden
    assert "mcp_call" in kept                 # mcp enabled → kept
    assert "read_file" in kept                # no feature → always kept


def test_all_features_enabled_keeps_all(monkeypatch):
    monkeypatch.setattr("install.setup_profiles.enabled_feature_ids", lambda cfg=None: ["vision", "mcp"])
    kept = ld._drop_disabled_feature_tools({"read_file", "analyze_image", "mcp_call"}, _REGISTRY, {})
    assert kept == {"read_file", "analyze_image", "mcp_call"}


def test_fail_open_on_resolution_error(monkeypatch):
    def _boom(cfg=None):
        raise RuntimeError("no config")
    monkeypatch.setattr("install.setup_profiles.enabled_feature_ids", _boom)
    names = {"read_file", "analyze_image"}
    assert ld._drop_disabled_feature_tools(names, _REGISTRY, {}) == names   # untouched


def test_reason_never_stripped(monkeypatch):
    monkeypatch.setattr("install.setup_profiles.enabled_feature_ids", lambda cfg=None: [])
    kept = ld._drop_disabled_feature_tools({"reason", "analyze_image"}, _REGISTRY, {})
    assert "reason" in kept and "analyze_image" not in kept
