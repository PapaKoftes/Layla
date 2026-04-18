"""
Contract tests: tool domain manifests are non-empty, uniquely keyed, and carry baseline metadata.
Full real execution of every tool is not attempted here (see integration_smoke markers).
"""

from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.tools import registry  # noqa: E402
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

_DOMAIN_MANIFESTS: list[tuple[str, dict]] = [
    ("file", FILE_TOOLS),
    ("git", GIT_TOOLS),
    ("web", WEB_TOOLS),
    ("memory", MEMORY_TOOLS),
    ("code", CODE_TOOLS),
    ("data", DATA_TOOLS),
    ("system", SYSTEM_TOOLS),
    ("automation", AUTOMATION_TOOLS),
    ("analysis", ANALYSIS_TOOLS),
    ("general", GENERAL_TOOLS),
    ("geometry", GEOMETRY_TOOLS),
]


def test_domain_tool_names_unique_and_match_registry_count():
    seen: set[str] = set()
    for domain_name, tools in _DOMAIN_MANIFESTS:
        assert len(tools) >= 1, f"domain {domain_name} has no tools"
        for tool_name in tools:
            assert isinstance(tool_name, str) and tool_name.strip()
            assert tool_name not in seen, f"duplicate tool name {tool_name!r} in domain {domain_name}"
            seen.add(tool_name)
    assert len(seen) == len(registry.TOOLS), (
        f"domain merge count {len(seen)} != registry.TOOLS {len(registry.TOOLS)}"
    )


def test_each_domain_entry_has_risk_metadata():
    for domain_name, tools in _DOMAIN_MANIFESTS:
        for tool_name, meta in tools.items():
            assert isinstance(meta, dict) and meta, f"{domain_name}.{tool_name}: empty meta"
            assert "risk_level" in meta, f"{domain_name}.{tool_name}: missing risk_level"
            assert "dangerous" in meta, f"{domain_name}.{tool_name}: missing dangerous"
            assert "require_approval" in meta, f"{domain_name}.{tool_name}: missing require_approval"
