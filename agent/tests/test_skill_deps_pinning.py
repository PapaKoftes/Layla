"""A6b: skill-pack supply-chain — dependency pinning enforcement.

Covers _unpinned_dependencies (the pure classifier used by install_from_git to
reject floating deps when skill_deps_require_pinned is on).
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.skills.skill_packs import _unpinned_dependencies  # noqa: E402


def test_exact_pins_are_accepted():
    assert _unpinned_dependencies(["requests==2.31.0", "numpy==1.26.4"]) == []


def test_floating_and_bare_specs_are_flagged():
    bad = _unpinned_dependencies(["requests", "numpy>=1.20", "flask~=2.0", "pandas"])
    assert set(bad) == {"requests", "numpy>=1.20", "flask~=2.0", "pandas"}


def test_direct_url_reference_counts_as_pinned():
    # A direct reference to an immutable artifact (PEP 508 `name @ url`) is pinned.
    assert _unpinned_dependencies(["mypkg @ https://example.com/mypkg-1.0.whl"]) == []


def test_empty_and_blank_specs_ignored():
    assert _unpinned_dependencies(["", "   ", "requests==2.31.0"]) == []


def test_mixed_returns_only_the_unpinned():
    assert _unpinned_dependencies(["requests==2.31.0", "numpy>=1.20"]) == ["numpy>=1.20"]
