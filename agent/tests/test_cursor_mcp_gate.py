"""The cursor-layla-mcp bridge exposes apply_patch (write) + run_code (exec) to any local MCP
client. This gate lets a cautious operator run a read-only bridge (LAYLA_CURSOR_MCP_WRITE=0)
while defaulting ON to preserve the Cursor workflow. Tested at the pure-logic level (the gate
module has no `mcp` dependency) plus a source-level check that server.py actually wires it."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MCP_DIR = REPO_ROOT / "cursor-layla-mcp"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import gate  # noqa: E402


def test_default_is_enabled_to_preserve_workflow():
    assert gate.write_surface_enabled({}) is True
    assert gate.write_surface_enabled({"LAYLA_CURSOR_MCP_WRITE": "1"}) is True
    assert gate.write_surface_enabled({"LAYLA_CURSOR_MCP_WRITE": "yes"}) is True


def test_explicit_disable_values_turn_it_off():
    for v in ("0", "false", "False", "OFF", "no", "disable", " disabled "):
        assert gate.write_surface_enabled({"LAYLA_CURSOR_MCP_WRITE": v}) is False, v


def test_write_tools_are_the_destructive_pair():
    assert gate.WRITE_TOOLS == frozenset({"apply_patch", "run_code"})


def test_warning_names_the_toggle_and_the_risk():
    w = gate.write_surface_warning()
    assert "LAYLA_CURSOR_MCP_WRITE=0" in w
    assert "apply_patch" in w and "run_code" in w


def test_server_wires_the_gate_in_both_handlers():
    """Guard against a silent regression that drops the gate: server.py must filter the tool
    list AND refuse the write tools / force allow flags off in the call handler."""
    src = (MCP_DIR / "server.py").read_text(encoding="utf-8")
    assert "from gate import" in src
    assert "write_surface_enabled()" in src
    assert "res.tools = [t for t in res.tools if t.name not in WRITE_TOOLS]" in src
    assert 'args["allow_write"] = False' in src and 'args["allow_run"] = False' in src
