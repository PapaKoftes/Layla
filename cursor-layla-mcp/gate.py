"""Opt-out gate for the Cursor <-> Layla MCP bridge's write/exec surface.

This bridge exposes ``apply_patch`` (allow_write) and ``run_code`` (allow_run) to any local
MCP client that spawns it — a full write+exec surface on LOCALHOST TRUST. The gate defaults
**ON** so the existing Cursor workflow keeps working, but can be turned off to run a read-only
bridge:

    LAYLA_CURSOR_MCP_WRITE=0   # hide apply_patch/run_code, force allow_write/allow_run False

Kept in a dependency-free module (no ``mcp`` import) so the gate logic is unit-testable in the
main test venv, which does not install the MCP SDK.
"""
from __future__ import annotations

import os

# Tools that make Layla write files or execute code through the bridge.
WRITE_TOOLS = frozenset({"apply_patch", "run_code"})

_DISABLED_VALUES = frozenset({"0", "false", "off", "no", "disable", "disabled"})


def write_surface_enabled(env: dict | None = None) -> bool:
    """True unless ``LAYLA_CURSOR_MCP_WRITE`` is explicitly set to a disable value.

    Default (unset) is ON to preserve the operator's Cursor workflow; the gate exists so a
    cautious operator can run a read-only bridge without editing code."""
    src = env if env is not None else os.environ
    return str(src.get("LAYLA_CURSOR_MCP_WRITE", "1")).strip().lower() not in _DISABLED_VALUES


def write_surface_warning() -> str:
    """One-line startup warning printed to stderr when the write/exec surface is live."""
    return (
        "[cursor-layla-mcp] WRITE+EXEC surface ENABLED: apply_patch (write) and run_code (exec) "
        "are exposed to any local MCP client that spawns this server — LOCALHOST TRUST ONLY. "
        "Set LAYLA_CURSOR_MCP_WRITE=0 for a read-only bridge."
    )
