#!/usr/bin/env python3
"""Run Layla as an MCP server (inbound) — Plan item 14.

Exposes a CURATED, READ-ONLY subset of Layla's registry tools plus her memory
recall over the Model Context Protocol, so other agents / MCP-aware tools can
call her. Every call runs fail-closed (no writes, no code execution).

    python -m clients.layla_mcp_server            # serve over stdio (default)

Gating (by design):
  * Requires the optional MCP SDK:  pip install 'mcp>=1.0,<2.0'
  * Requires mcp_server_enabled: true in runtime_config.json (OFF by default —
    an inbound server is a real exposure and must be switched on deliberately).

Point an MCP client at this process. Example client config entry:
    {"command": "python", "args": ["-m", "clients.layla_mcp_server"]}
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run standalone: make the agent/ package root importable (mirrors tests' bootstrap).
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="layla-mcp-server",
        description="Expose Layla's safe tools + memory recall as an MCP server.",
    )
    ap.add_argument(
        "--transport", choices=["stdio"], default="stdio",
        help="transport to serve on (stdio only for the standalone entry)",
    )
    args = ap.parse_args(argv)

    try:
        from services.infrastructure.mcp_server import build_layla_mcp_server, exposed_tool_names, run_stdio
    except Exception as e:  # pragma: no cover - import guard
        print(f"[layla-mcp-server] cannot import server module: {e}", file=sys.stderr)
        return 1

    try:
        server = build_layla_mcp_server()
    except RuntimeError as e:
        # Fail-closed: SDK missing or mcp_server_enabled off. Tell the operator how to proceed.
        print(f"[layla-mcp-server] not starting: {e}", file=sys.stderr)
        return 2

    names = exposed_tool_names()
    print(
        f"[layla-mcp-server] serving {len(names)} read-only tool(s) over {args.transport}: "
        f"{', '.join(names) if names else '(none)'}",
        file=sys.stderr,
    )
    if args.transport == "stdio":
        run_stdio(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
