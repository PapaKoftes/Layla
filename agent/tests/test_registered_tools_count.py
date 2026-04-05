"""
Authoritative count of entries in layla.tools.registry.TOOLS.

When you add or remove a tool in domain manifests, update EXPECTED_TOOL_COUNT.
"""

from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.tools import registry  # noqa: E402

# Bump when domain TOOLS dicts change (see layla/tools/domains/*.py).
EXPECTED_TOOL_COUNT = 186


def test_tools_dict_count_matches_manifest():
    assert len(registry.TOOLS) == EXPECTED_TOOL_COUNT, (
        f"TOOLS count {len(registry.TOOLS)} != {EXPECTED_TOOL_COUNT} — update EXPECTED_TOOL_COUNT "
        "and AGENTS.md / docs that cite the tool total."
    )
