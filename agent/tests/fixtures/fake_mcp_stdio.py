"""Minimal stdio MCP server for tests: initialize, notifications/initialized, tools/call."""

from __future__ import annotations

import json
import sys


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid = msg.get("id")
        method = msg.get("method", "")
        if method == "initialize":
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "0.0.1"},
                },
            }
            print(json.dumps(out), flush=True)
        elif method == "notifications/initialized":
            # JSON-RPC notification: no response
            continue
        elif method == "tools/list":
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "tools": [
                        {"name": "echo", "description": "echo", "inputSchema": {"type": "object", "properties": {}}}
                    ]
                },
            }
            print(json.dumps(out), flush=True)
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name", "")
            args = params.get("arguments") or {}
            text = f"ok:{name}:{json.dumps(args, sort_keys=True)}"
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": text}]},
            }
            print(json.dumps(out), flush=True)
        elif method == "resources/list":
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "resources": [
                        {
                            "uri": "memo://demo",
                            "name": "demo-memo",
                            "description": "fake resource for tests",
                        }
                    ]
                },
            }
            print(json.dumps(out), flush=True)
        elif method == "resources/read":
            params = msg.get("params") or {}
            uri = params.get("uri", "")
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "contents": [
                        {"uri": uri, "mimeType": "text/plain", "text": f"resource-body:{uri}"}
                    ]
                },
            }
            print(json.dumps(out), flush=True)
        else:
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {"code": -32601, "message": f"unknown method {method}"},
            }
            print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
