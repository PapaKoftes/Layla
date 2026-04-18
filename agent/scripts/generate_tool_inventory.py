#!/usr/bin/env python3
"""
Emit a Markdown table of tools from domain manifests (for release / audit).

Usage (from repo root):
  python agent/scripts/generate_tool_inventory.py > tool-inventory.md
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.tools.domains import (  # noqa: E402
    ANALYSIS_TOOLS,
    AUTOMATION_TOOLS,
    CODE_TOOLS,
    DATA_TOOLS,
    FILE_TOOLS,
    GENERAL_TOOLS,
    GEOMETRY_TOOLS,
    GIT_TOOLS,
    MEMORY_TOOLS,
    SYSTEM_TOOLS,
    WEB_TOOLS,
)

_ROWS: list[tuple[str, str, str, str]] = []


def _emit(domain: str, tools: dict) -> None:
    for name, meta in sorted(tools.items()):
        risk = str(meta.get("risk_level", ""))
        appr = "yes" if meta.get("require_approval") else "no"
        dang = "yes" if meta.get("dangerous") else "no"
        _ROWS.append((domain, name, risk, f"approval={appr}, dangerous={dang}"))


def main() -> None:
    _emit("file", FILE_TOOLS)
    _emit("git", GIT_TOOLS)
    _emit("web", WEB_TOOLS)
    _emit("memory", MEMORY_TOOLS)
    _emit("code", CODE_TOOLS)
    _emit("data", DATA_TOOLS)
    _emit("system", SYSTEM_TOOLS)
    _emit("automation", AUTOMATION_TOOLS)
    _emit("analysis", ANALYSIS_TOOLS)
    _emit("general", GENERAL_TOOLS)
    _emit("geometry", GEOMETRY_TOOLS)

    lines = [
        "| Domain | Tool | Risk | Flags |",
        "|--------|------|------|-------|",
    ]
    for domain, name, risk, flags in _ROWS:
        lines.append(f"| {domain} | `{name}` | {risk} | {flags} |")
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
