"""BL-153: MCP-only plugins — plugin-declared MCP servers merge into the active set."""
from __future__ import annotations

import pytest

from services.infrastructure import mcp_client as mc


@pytest.fixture(autouse=True)
def _clear():
    mc.clear_plugin_mcp_servers()
    yield
    mc.clear_plugin_mcp_servers()


def test_register_and_merge_into_load():
    added = mc.register_plugin_mcp_servers([
        {"name": "weather", "command": "weather-mcp", "args": ["--stdio"]},
        {"name": "bad", "args": []},   # no command → skipped
    ])
    assert added == 1
    # Plugin-declared servers require plugin code-exec consent (plugins_enabled).
    specs = mc.load_mcp_stdio_servers({"mcp_client_enabled": True, "plugins_enabled": True, "mcp_stdio_servers": []})
    names = {s.name for s in specs}
    assert "weather" in names
    weather = next(s for s in specs if s.name == "weather")
    assert weather.command == "weather-mcp" and weather.args == ("--stdio",)


def test_config_and_plugin_servers_both_present():
    mc.register_plugin_mcp_servers([{"name": "plugin_srv", "command": "psrv"}])
    cfg = {"mcp_client_enabled": True, "plugins_enabled": True, "mcp_stdio_servers": [{"name": "cfg_srv", "command": "csrv"}]}
    names = {s.name for s in mc.load_mcp_stdio_servers(cfg)}
    assert names == {"cfg_srv", "plugin_srv"}


def test_dedup_by_name():
    mc.register_plugin_mcp_servers([{"name": "dup", "command": "a"}])
    mc.register_plugin_mcp_servers([{"name": "dup", "command": "b"}])   # ignored — same name
    cfg = {"mcp_client_enabled": True, "plugins_enabled": True}
    specs = mc.load_mcp_stdio_servers(cfg)
    assert [s.name for s in specs].count("dup") == 1


def test_plugin_servers_gated_by_plugins_enabled():
    # A6c: a plugin ships a subprocess command; with plugins_enabled OFF it must be
    # ignored even when the MCP client is on, while operator-configured servers stay.
    mc.register_plugin_mcp_servers([{"name": "plugin_srv", "command": "psrv"}])
    cfg = {"mcp_client_enabled": True, "mcp_stdio_servers": [{"name": "cfg_srv", "command": "csrv"}]}
    names = {s.name for s in mc.load_mcp_stdio_servers(cfg)}
    assert names == {"cfg_srv"}          # plugin server dropped
    # Flipping plugins_enabled on lets it through.
    cfg["plugins_enabled"] = True
    names_on = {s.name for s in mc.load_mcp_stdio_servers(cfg)}
    assert names_on == {"cfg_srv", "plugin_srv"}


def test_disabled_mcp_returns_nothing():
    mc.register_plugin_mcp_servers([{"name": "x", "command": "x"}])
    assert mc.load_mcp_stdio_servers({"mcp_client_enabled": False}) == []


def test_sdk_accepts_mcp_only_manifest():
    from services.skills.plugin_sdk import validate_manifest
    r = validate_manifest({
        "name": "weather-plugin", "version": "0.1.0",
        "requires": {"layla_api": ">=1.0"},
        "mcp_servers": [{"name": "weather", "command": "weather-mcp"}],
    })
    assert r["ok"] and r["errors"] == []
    assert not any("no skills" in w for w in r["warnings"])   # mcp_servers counts as content
