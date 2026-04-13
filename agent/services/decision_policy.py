"""
Decision control plane: merge subsystem signals into PolicyCaps and apply to effective tool sets.
Prompts render context; caps enforce allow/deny at dispatch boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Tools that count as "verify / inspect" before mutating under policy.
_READ_VERIFY_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "list_dir",
    "grep_code",
    "file_info",
    "git_status",
    "git_diff",
    "git_log",
    "glob_files",
    "python_ast",
    "understand_file",
})

# Typical mutating / high-impact tools (subset of registry names).
_MUTATING_TOOLS: frozenset[str] = frozenset({
    "write_file",
    "apply_patch",
    "shell",
    "run_python",
    "git_commit",
    "git_push",
    "pip_install",
    "search_replace",
    "rename_symbol",
    "generate_gcode",
    "geometry_execute_program",
    "docker_run",
    "mcp_tools_call",
})


@dataclass
class PolicyCaps:
    forbidden_tools: frozenset[str] = field(default_factory=frozenset)
    allowed_only: frozenset[str] | None = None  # if set, intersect with base allowlist
    require_verify_before_mutate: bool = False
    max_tool_calls_delta: int = 0  # subtract from remaining budget (negative tightens)
    sources: list[str] = field(default_factory=list)

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "forbidden_tools": sorted(self.forbidden_tools),
            "allowed_only": sorted(self.allowed_only) if self.allowed_only is not None else None,
            "require_verify_before_mutate": self.require_verify_before_mutate,
            "max_tool_calls_delta": self.max_tool_calls_delta,
            "sources": list(self.sources),
        }


def merge_policy_caps(base: PolicyCaps, extra: PolicyCaps) -> PolicyCaps:
    out = PolicyCaps(
        forbidden_tools=base.forbidden_tools | extra.forbidden_tools,
        allowed_only=base.allowed_only,
        require_verify_before_mutate=base.require_verify_before_mutate or extra.require_verify_before_mutate,
        max_tool_calls_delta=base.max_tool_calls_delta + extra.max_tool_calls_delta,
        sources=list(dict.fromkeys(base.sources + extra.sources)),
    )
    if extra.allowed_only is not None:
        if out.allowed_only is None:
            out.allowed_only = extra.allowed_only
        else:
            out.allowed_only = out.allowed_only & extra.allowed_only
    return out


def _recent_verify_in_steps(steps: list[dict], lookback: int = 4) -> bool:
    for s in reversed(steps[-lookback:]):
        act = str(s.get("action") or "")
        if act in _READ_VERIFY_TOOLS:
            r = s.get("result")
            if isinstance(r, dict) and r.get("ok", True):
                return True
    return False


def caps_from_outcome_evaluation(ev: dict | None) -> PolicyCaps:
    if not isinstance(ev, dict):
        return PolicyCaps()
    score = ev.get("score")
    try:
        sc = float(score)
    except (TypeError, ValueError):
        return PolicyCaps()
    caps = PolicyCaps(sources=["outcome_evaluation"])
    if sc < 0.45:
        caps.require_verify_before_mutate = True
        caps.max_tool_calls_delta = -2
        caps.forbidden_tools |= _MUTATING_TOOLS
    elif sc < 0.62:
        caps.require_verify_before_mutate = True
        caps.max_tool_calls_delta = -1
    if not ev.get("success", True):
        caps.require_verify_before_mutate = True
    return caps


def caps_from_cognitive_workspace(cw: dict | None) -> PolicyCaps:
    if not isinstance(cw, dict):
        return PolicyCaps()
    hint = (cw.get("strategy_hint") or "").lower()
    name = (cw.get("chosen_name") or "").lower()
    caps = PolicyCaps(sources=["cognitive_workspace"])
    if any(x in hint for x in ("read first", "inspect", "map", "understand before", "verify")):
        caps.require_verify_before_mutate = True
    if "lilith" in name or "safe" in hint:
        caps.require_verify_before_mutate = True
    return caps


def caps_from_running_outcome(state: dict) -> PolicyCaps:
    """Heuristic on in-flight steps (tool failures this run)."""
    try:
        from services.outcome_evaluation import evaluate_outcome

        ev = evaluate_outcome(state)
    except Exception:
        return PolicyCaps()
    if int(ev.get("tool_fail") or 0) >= 3:
        return PolicyCaps(
            require_verify_before_mutate=True,
            forbidden_tools=_MUTATING_TOOLS,
            sources=["running_outcome_evaluation"],
        )
    if int(ev.get("tool_fail") or 0) >= 1:
        return PolicyCaps(require_verify_before_mutate=True, sources=["running_outcome_evaluation"])
    return PolicyCaps()


def caps_from_personal_knowledge_graph(state: dict, cfg: dict) -> PolicyCaps:
    """PKG is usually text-only; optional hard flag from state."""
    if not cfg.get("pkg_policy_strict_enabled"):
        return PolicyCaps()
    pkg = state.get("pkg_policy") if isinstance(state.get("pkg_policy"), dict) else None
    if not pkg:
        return PolicyCaps()
    ft = pkg.get("forbidden_tools")
    if isinstance(ft, list) and ft:
        return PolicyCaps(forbidden_tools=frozenset(str(x) for x in ft if x), sources=["pkg_policy"])
    return PolicyCaps()


def caps_from_tool_reliability(cfg: dict) -> PolicyCaps:
    if not cfg.get("tool_replay_policy_enabled"):
        return PolicyCaps()
    try:
        from layla.memory.db import get_tool_reliability

        stats = get_tool_reliability()
        bad = [
            n
            for n, s in stats.items()
            if s.get("count", 0) >= 8 and float(s.get("success_rate", 1.0) or 0.0) < 0.35
        ]
        if bad:
            return PolicyCaps(forbidden_tools=frozenset(bad[:8]), sources=["tool_reliability"])
    except Exception:
        pass
    return PolicyCaps()


def caps_from_reflection_state(state: dict) -> PolicyCaps:
    ref = state.get("reflection_caps")
    if not isinstance(ref, dict):
        return PolicyCaps()
    ft = ref.get("forbidden_tools")
    if isinstance(ft, list) and ft:
        return PolicyCaps(forbidden_tools=frozenset(str(x) for x in ft), sources=["reflection_engine"])
    return PolicyCaps()


def build_policy_caps(
    state: dict,
    cfg: dict,
    *,
    conversation_id: str,
) -> PolicyCaps:
    if not cfg.get("decision_policy_enabled", True):
        return PolicyCaps(sources=["disabled"])

    caps = PolicyCaps()
    try:
        from shared_state import get_last_outcome_evaluation

        prev = get_last_outcome_evaluation(conversation_id)
        caps = merge_policy_caps(caps, caps_from_outcome_evaluation(prev))
    except Exception:
        pass

    caps = merge_policy_caps(caps, caps_from_cognitive_workspace(state.get("cognitive_workspace")))
    caps = merge_policy_caps(caps, caps_from_running_outcome(state))
    caps = merge_policy_caps(caps, caps_from_personal_knowledge_graph(state, cfg))
    caps = merge_policy_caps(caps, caps_from_tool_reliability(cfg))
    caps = merge_policy_caps(caps, caps_from_reflection_state(state))

    steps = state.get("steps") or []
    if (
        caps.require_verify_before_mutate
        and len(steps) >= 1
        and not _recent_verify_in_steps(steps)
    ):
        caps = merge_policy_caps(
            caps,
            PolicyCaps(forbidden_tools=_MUTATING_TOOLS, sources=["verify_gate_mid_run"]),
        )

    try:
        from services.toolchain_awareness import policy_hint_from_toolchain

        th = policy_hint_from_toolchain(state.get("original_goal") or state.get("goal") or "")
        if th.forbidden_tools:
            caps = merge_policy_caps(caps, th)
    except Exception:
        pass

    return caps


def apply_caps_to_valid_tools(base: frozenset[str], caps: PolicyCaps) -> frozenset[str]:
    """Intersect registry-allowed tools with policy caps. Always keep non-tool decision paths."""
    meta = frozenset({"reason", "think", "none"})
    tools = set(base) | meta
    tools -= caps.forbidden_tools
    if caps.allowed_only is not None and caps.allowed_only:
        tools &= caps.allowed_only | meta
    return frozenset(t for t in tools if t)


def effective_max_tool_calls(cfg_max: int, caps: PolicyCaps) -> int:
    v = int(cfg_max) + int(caps.max_tool_calls_delta)
    return max(1, v)


def filter_batch_tools(batch: list[dict], valid: frozenset[str]) -> list[dict]:
    out: list[dict] = []
    for bt in batch:
        if not isinstance(bt, dict):
            continue
        name = (bt.get("tool") or "").strip()
        if name and name in valid:
            out.append(bt)
    return out
