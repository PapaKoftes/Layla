"""Tests for scripts/check_dead_symbols.py — the static symbol-liveness gate.

Proves three things:
  1. The gate exits 0 on the current tree (the committed whitelist covers the
     existing baseline).
  2. The gate has TEETH: a throwaway module with an exported symbol that nobody
     calls is flagged — while a framework entry point (a @router.* handler) is
     correctly ignored.
  3. The whitelist is load-bearing, not vacuous: removing it from the scan
     resurfaces findings, so the green result in (1) is real suppression rather
     than an empty scan.

Skips cleanly if `vulture` is not installed, mirroring the gate's own graceful
degradation (so a dev without the [dev] extra is never hard-blocked).
"""
import os
import sys

import pytest

# Import the gate module from agent/scripts/ (not on the package path). Note this
# is agent/scripts (2 levels up: tests -> agent), distinct from the repo-root
# scripts/ dir that holds check_copyleft.py.
_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import check_dead_symbols as cds  # noqa: E402

# The whole module is meaningless without vulture; skip rather than fail.
pytestmark = pytest.mark.skipif(
    cds._load_vulture() is None,
    reason="vulture not installed (pip install vulture, or the [dev] extra)",
)


def test_gate_is_green_on_current_tree():
    """The committed whitelist must keep the current tree clean."""
    assert cds.check() == 0


def test_gate_has_teeth(tmp_path):
    """A NEW orphan export is caught; a framework route handler is not."""
    module = tmp_path / "throwaway_orphan_mod.py"
    module.write_text(
        "def totally_orphaned_widget():\n"
        "    return 1\n"
        "\n"
        "class OrphanedGizmo:\n"
        "    pass\n"
        "\n"
        "@router.get('/never')\n"
        "def a_route_handler():\n"
        "    return {}\n",
        encoding="utf-8",
    )

    vulture_mod = cds._load_vulture()
    # exclude=[] so nothing about the tmp path can be accidentally filtered out.
    found = {it.name for it in cds.find_dead_symbols(vulture_mod, [tmp_path], exclude=[])}

    # The orphaned exported function and class are flagged.
    assert "totally_orphaned_widget" in found
    assert "OrphanedGizmo" in found
    # The @router.* handler is a framework entry point and must be ignored,
    # even though it too has no static caller.
    assert "a_route_handler" not in found
    # tmp_path is removed automatically by pytest — the throwaway module is gone.


def test_whitelist_is_load_bearing():
    """Green must come from real suppression, not an empty scan.

    Scanning the tree WITHOUT consulting the committed whitelist must resurface
    findings; scanning WITH it must be clean.
    """
    vulture_mod = cds._load_vulture()

    without_whitelist = cds.find_dead_symbols(
        vulture_mod, [cds.AGENT_DIR], exclude=cds.EXCLUDE + [cds._WHITELIST_GLOB]
    )
    with_whitelist = cds.find_dead_symbols(vulture_mod, [cds.AGENT_DIR])

    assert len(without_whitelist) > 0, "expected a non-empty baseline before whitelisting"
    assert len(with_whitelist) == 0, "whitelist should suppress the entire current baseline"


def test_only_gated_symbol_types_are_reported():
    """The gate scopes to defined-symbol liveness, not imports/vars/unreachable."""
    assert cds.GATED_TYPES == frozenset({"function", "class", "method", "property"})
    for item in cds.find_dead_symbols(cds._load_vulture(), [cds.AGENT_DIR],
                                      exclude=cds.EXCLUDE + [cds._WHITELIST_GLOB]):
        assert item.typ in cds.GATED_TYPES


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
