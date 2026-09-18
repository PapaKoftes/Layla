"""Docs must not lie about the tool count.

A done-audit found five different tool-count claims across the docs (README 200, AGENTS 202,
tools-reference 195/207, product-plan 204, ...) while the authoritative count — EXPECTED_TOOL_COUNT
and the live registry — is a single number. Docs drift because nothing gated them: the tests-count
freshness test guarded only its own number. This gate pins every human-facing "N registered tools"
and "tool count: N" claim to EXPECTED_TOOL_COUNT so the next tool add/remove can't silently re-scatter
them.

Scope: the LIVE docs a reader/agent is pointed at. `docs/archive/` is deliberately excluded — those
are historical snapshots and their old counts are correct as-of-then.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from tests.test_registered_tools_count import EXPECTED_TOOL_COUNT  # noqa: E402

# "<N> registered tools" and "tool count: <N>" (bold markdown and spaces tolerated up to the digits).
_CLAIM_RES = (
    re.compile(r"(\d+)\s+registered tools", re.IGNORECASE),
    re.compile(r"tool count:[^\d\n]{0,8}(\d+)", re.IGNORECASE),
)

# Live docs a reader/agent is actually pointed at. Explicit roots; archive is skipped below.
_DOC_ROOTS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "knowledge",
    REPO_ROOT / "docs",
]


def _live_markdown_files() -> list[Path]:
    files: list[Path] = []
    for root in _DOC_ROOTS:
        if root.is_file() and root.suffix == ".md":
            files.append(root)
        elif root.is_dir():
            for p in root.rglob("*.md"):
                if "archive" in p.parts:  # historical snapshots keep their as-of-then counts
                    continue
                files.append(p)
    return files


def test_doc_registered_tool_counts_match_the_registry():
    offenders: list[str] = []
    for path in _live_markdown_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for rgx in _CLAIM_RES:
            for m in rgx.finditer(text):
                claimed = int(m.group(1))
                if claimed != EXPECTED_TOOL_COUNT:
                    line = text.count("\n", 0, m.start()) + 1
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    offenders.append(f"  {rel}:{line} claims {claimed}, expected {EXPECTED_TOOL_COUNT} — {m.group(0)!r}")
    assert not offenders, (
        f"Doc tool-count claims disagree with EXPECTED_TOOL_COUNT={EXPECTED_TOOL_COUNT} "
        "(update the doc, or EXPECTED_TOOL_COUNT if the registry really changed):\n" + "\n".join(offenders)
    )
