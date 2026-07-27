"""
PLAN ITEM 26 -- tool-offerability pinning.

Proves the config-side primitives in ``tests/_tool_verify.py`` remove the
visibility/intent narrowing confound so a driven per-tool verification run
actually PRESENTS the target tool to the model.

The four target tools span domains on purpose (a file tool, a git tool, a data
tool, and a dependency-gated web tool) so the pin is exercised against tools
that a coding-goal's intent filter would otherwise route away.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

import pytest

from tests._tool_verify import offered_set, pin_tools_config

# One tool per domain. A coding goal's intent categories are {code, filesystem,
# memory}, so the data tool and the web tool are OUTSIDE it -- the exact tools a
# router would drop if we did not pin.
_FILE_TOOL = "write_file"        # filesystem
_GIT_TOOL = "git_log"            # code
_DATA_TOOL = "read_csv"          # data (outside a coding goal's intent set)
_WEB_TOOL_DEPGATED = "ddg_search"  # web, requires duckduckgo_search

_SPREAD = (_FILE_TOOL, _GIT_TOOL, _DATA_TOOL, _WEB_TOOL_DEPGATED)

# A goal whose intent filter narrows hard, so the confound is real, not incidental.
_CODING_GOAL = "fix the bug in this code"


@pytest.mark.parametrize("target", _SPREAD)
def test_pin_guarantees_target_offered(target: str) -> None:
    """pin_tools_config(target) yields a config whose offered_set CONTAINS target,
    for a spread of tools across domains -- even on a coding goal that would
    otherwise route the data/web tools away."""
    cfg = pin_tools_config(target)
    offered = offered_set(cfg, _CODING_GOAL)
    assert target in offered, f"{target} was pinned but not offered: {sorted(offered)}"
    # The pin keeps the set small (minimal profile + allowlist), well under the
    # ~15 visibility cap -- that is what removes the cap confound.
    assert len(offered) <= 15, f"pinned set unexpectedly large ({len(offered)}): {sorted(offered)}"


def test_pin_target_offered_regardless_of_goal() -> None:
    """The pin holds across unrelated goals -- the target does not depend on the
    goal's intent categories once routing is disabled."""
    cfg = pin_tools_config(_WEB_TOOL_DEPGATED)
    for goal in ("", _CODING_GOAL, "plot a chart of the csv data", "who are you?"):
        assert _WEB_TOOL_DEPGATED in offered_set(cfg, goal), f"pin failed for goal={goal!r}"


def test_unpinned_default_can_drop_low_priority_tool() -> None:
    """An un-pinned default config DROPS a low-priority (out-of-intent) tool --
    this is the confound the pin removes. The same tool, pinned, is offered."""
    default_cfg: dict = {}  # routing on by default; full profile
    default_offered = offered_set(default_cfg, _CODING_GOAL)

    # The data tool and the web tool are outside a coding goal's intent set, so the
    # resolver's intent filter drops them under the default config.
    assert _DATA_TOOL not in default_offered
    assert _WEB_TOOL_DEPGATED not in default_offered

    # Pinning restores each -- proving the confound is removable, not intrinsic.
    assert _DATA_TOOL in offered_set(pin_tools_config(_DATA_TOOL), _CODING_GOAL)
    assert _WEB_TOOL_DEPGATED in offered_set(pin_tools_config(_WEB_TOOL_DEPGATED), _CODING_GOAL)


def test_tools_allow_alone_is_insufficient_without_disabling_routing() -> None:
    """The trap this pin exists to avoid: adding the target to tools_allow while
    routing stays ON still drops it, because ``effective &= intent_names``
    intersects it back out. This is why pin_tools_config sets
    tool_routing_enabled=False -- and why offered_set records the truth."""
    naive_cfg = {
        "tool_routing_enabled": True,  # routing ON -> intent filter still runs
        "tools_profile": "minimal",
        "tools_allow": [_WEB_TOOL_DEPGATED],
    }
    naive_offered = offered_set(naive_cfg, _CODING_GOAL)
    assert _WEB_TOOL_DEPGATED not in naive_offered, (
        "tools_allow alone should NOT guarantee offerability with routing on"
    )

    # The real pin (routing disabled) fixes exactly this.
    assert _WEB_TOOL_DEPGATED in offered_set(pin_tools_config(_WEB_TOOL_DEPGATED), _CODING_GOAL)


def test_decoys_are_also_offered() -> None:
    """Decoys are presented alongside the target, so the driven case is a real
    choice among tools rather than a single forced option."""
    decoys = [_GIT_TOOL, _DATA_TOOL]
    cfg = pin_tools_config(_WEB_TOOL_DEPGATED, decoys)
    offered = offered_set(cfg, _CODING_GOAL)
    assert _WEB_TOOL_DEPGATED in offered
    for d in decoys:
        assert d in offered, f"decoy {d} not offered: {sorted(offered)}"


def test_pin_config_shape_uses_real_mechanism() -> None:
    """The pin is a plain config fragment driving the production resolver knobs:
    routing off + minimal profile + a tools_allow union that includes the target."""
    cfg = pin_tools_config(_FILE_TOOL, [_GIT_TOOL, _GIT_TOOL, "  "])  # dupes/blank ignored
    assert cfg["tool_routing_enabled"] is False
    assert cfg["tools_profile"] == "minimal"
    assert cfg["tools_allow"] == [_FILE_TOOL, _GIT_TOOL]  # deduped, ordered, target first
