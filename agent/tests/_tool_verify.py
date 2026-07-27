"""
Tool-offerability pinning primitives for the driven tool-verification harness.

PLAN ITEM 26. Background: a per-tool verification run can fail for the wrong
reason. The router narrows the tools it offers the model in two stages, both of
which can silently drop the tool under test:

  1. Intent filter -- ``resolve_effective_tools_for_route`` computes
     ``effective &= intent_names``. Even a tool explicitly listed in
     ``cfg['tools_allow']`` is intersected back OUT if it does not belong to the
     goal's intent categories (e.g. a web tool on a coding goal).
  2. Visibility cap -- ``services.agent.llm_decision.get_tools_for_goal`` trims
     the survivors to ``tool_visibility_cap`` (~15) via ``tool_recommend``.

Both stages are gated on ``tool_routing_enabled`` (default True). So a naive
"just add the tool to tools_allow" pin is not enough -- if routing stays on, the
intent filter can still amputate the target. This is the "verify the probe
before the result" trap: the run reports "model cannot use tool X" when in fact
X was never presented.

These helpers are the config-side primitives item 25's driven harness uses per
case:

* ``pin_tools_config`` builds a config that GUARANTEES the target is presented.
* ``offered_set`` reports what the production resolver actually offers under a
  config, so the harness can RECORD the offered set alongside each driven result
  (proving the target was presented, not assumed).

This module lives under ``tests/`` on purpose: it is a test-only harness helper,
so the dead-symbols gate excludes it and no production module gains a test-only
caller. It only READS production mechanisms
(``resolve_effective_tools_for_route``); it never reinvents them.
"""
from __future__ import annotations

from typing import Any


def _tools_registry() -> dict[str, Any]:
    """The live tool registry the resolver narrows from (~200 tools)."""
    from layla.tools.registry import TOOLS

    return TOOLS


def _route_for_goal(goal: str) -> Any:
    """
    Build the RouteDecision the production resolver's intent filter consumes.

    This mirrors ``services.tools.intent_router.route_intent`` exactly where it
    matters: that function ends by setting ``intent_categories = detect_intent(goal)``
    (overwriting its earlier broad default), and the resolver reads ONLY
    ``route.intent_categories``. We build it directly from ``detect_intent`` so the
    offered set is deterministic and free of ``route_intent``'s optional
    ``classify_task`` model call. Falls back to ``None`` on any import error --
    the resolver then routes through ``get_tool_names_for_goal(goal)`` instead,
    which is the same intent source.
    """
    try:
        from services.tools.intent_detection import detect_intent
        from services.tools.intent_router import RouteDecision

        return RouteDecision(
            task_type="default",
            is_meta_self=False,
            has_workspace_signals=False,
            has_path_like=False,
            has_url_like=False,
            intent_categories=list(detect_intent(goal or "")),
            routing_hints=[],
        )
    except Exception:
        return None


def pin_tools_config(target: str, decoys: list[str] | None = None) -> dict[str, Any]:
    """
    Return a config that GUARANTEES ``target`` is in the offered set.

    Strategy (uses the REAL mechanism -- see ``resolve_effective_tools_for_route``):

    * ``tools_profile="minimal"`` -- the base set is just the four safety tools
      (read_file, list_dir, search_memories, save_note), so the 3B is not drowned
      by ~200 tools.
    * ``tools_allow=[target, *decoys]`` -- unioned into the effective set by the
      resolver, so the target (and a few decoys, to keep it a real choice rather
      than a forced single option) are definitely present.
    * ``tool_routing_enabled=False`` -- the LOAD-BEARING part. It makes the
      resolver skip the intent filter (``skip_intent_filter=True``), so the union
      above is not intersected back out; and it makes
      ``get_tools_for_goal`` skip the ~15-tool visibility cap entirely (that block
      is gated on ``tool_routing_enabled`` and only fires when the set exceeds the
      cap -- the pinned set is tiny, so it would not fire anyway).

    Without ``tool_routing_enabled=False`` a tools_allow-only pin silently fails:
    a web ``target`` on a coding goal is added by tools_allow and then removed by
    ``effective &= intent_names``. See ``test_tool_offerability_pinning``.
    """
    allow: list[str] = []
    seen: set[str] = set()
    for name in [target, *(decoys or [])]:
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        allow.append(name)
    return {
        "tool_routing_enabled": False,
        "tools_profile": "minimal",
        "tools_allow": allow,
    }


def offered_set(cfg: dict[str, Any], goal: str = "") -> set[str]:
    """
    The tools actually offered under ``cfg`` for ``goal``, via the production
    resolver (``resolve_effective_tools_for_route``).

    ``skip_intent_filter`` is derived from ``cfg`` the same way production does
    (``services.agent.llm_decision.get_tools_for_goal``:
    ``skip = not cfg.get("tool_routing_enabled", True)``), so a pinned config
    (routing off) yields the un-narrowed union and a default config (routing on)
    yields the intent-narrowed set the model would really see at the resolver
    boundary.

    Note: this reports the RESOLVER's offer -- the layer where profile /
    tools_allow / tools_deny / intent-filter act. The downstream visibility cap
    and dependency/feature gates live in ``get_tools_for_goal``; a pinned config
    disables the cap and keeps the set tiny, and the dep gate is intentionally
    not applied here so a dep-gated tool (e.g. ``ddg_search``) is still shown as
    offered by the offerability layer.
    """
    from services.tools.tool_policy import resolve_effective_tools_for_route

    skip = not bool(cfg.get("tool_routing_enabled", True))
    route = _route_for_goal(goal)
    names = resolve_effective_tools_for_route(
        cfg,
        route if route is not None else {},
        goal,
        _tools_registry(),
        skip_intent_filter=skip,
    )
    return set(names)
