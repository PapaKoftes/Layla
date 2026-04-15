"""
OpenClaw-style tool governance: profile, allow/deny lists, group:* expansion.
Combines with intent-based filtering from intent_detection.
"""
from __future__ import annotations

import fnmatch
import logging
from typing import Any

from services.intent_detection import _get_tool_category, get_tool_names_for_goal

logger = logging.getLogger("layla")

# OpenClaw-aligned group names -> Layla tool categories (expanded via registry)
_GROUP_TO_CATEGORIES: dict[str, tuple[str, ...]] = {
    "group:fs": ("filesystem",),
    "group:code": ("code",),
    "group:web": ("web",),
    "group:memory": ("memory",),
    "group:system": ("system",),
    "group:automation": ("automation",),
    "group:data": ("data",),
    "group:analysis": ("analysis",),
    # OpenClaw "runtime" ~= shell + run_python
    "group:runtime": (),
    "group:sessions": (),  # no Layla equivalent; empty
    "group:openclaw": (),  # placeholder; treated as all built-ins when combined with profile
}

_RUNTIME_TOOL_NAMES = frozenset({"shell", "run_python", "shell_session_start", "shell_session_manage"})


_DEFAULT_DETERMINISTIC_TOOL_ROUTES: dict[str, tuple[str, ...]] = {
    # Keep these small and stable; they are a confusion-reduction layer for weak models.
    "coding": (
        "read_file",
        "write_file",
        "replace_in_file",
        "apply_patch",
        "grep_code",
        "list_dir",
        "glob_files",
        "shell",
        "git_status",
        "git_diff",
    ),
    "research": (
        "read_file",
        "grep_code",
        "list_dir",
        "glob_files",
        "search_memories",
        "fetch_url",
    ),
    "planning": (
        "read_file",
        "list_dir",
        "grep_code",
        "glob_files",
        "search_memories",
    ),
    "file_ops": (
        "read_file",
        "write_file",
        "replace_in_file",
        "list_dir",
        "glob_files",
        "shell",
        "apply_patch",
    ),
}


def deterministic_route_tools(
    cfg: dict[str, Any],
    goal: str,
    tools_dict: dict[str, Any],
) -> frozenset[str] | None:
    """
    Deterministic tool routing by task type.
    Returns a tool allow-set or None if disabled / unknown.
    """
    if not bool(cfg.get("deterministic_tool_routes_enabled", False)):
        return None
    try:
        from services.model_router import classify_task

        tt = str(classify_task(goal or "", "") or "").strip().lower()
    except Exception:
        tt = ""

    raw_routes = cfg.get("deterministic_tool_routes")
    routes: dict[str, Any] = raw_routes if isinstance(raw_routes, dict) else {}
    default = dict(_DEFAULT_DETERMINISTIC_TOOL_ROUTES)
    # Allow config override per route key.
    for k, v in list(routes.items()):
        if not isinstance(k, str):
            continue
        if isinstance(v, (list, tuple)):
            default[k.strip().lower()] = tuple(str(x) for x in v if str(x).strip())

    route = default.get(tt)
    if not route:
        return None
    allowed = {t for t in route if t in tools_dict}
    # Always include minimal safety net; agent_loop also enforces this.
    for t in ("reason", "read_file", "list_dir"):
        if t in tools_dict or t == "reason":
            allowed.add(t)
    return frozenset(allowed)


def _tools_for_categories(tools_dict: dict[str, Any], categories: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    if not categories:
        return out
    cat_set = set(categories)
    for name in tools_dict:
        cat = _get_tool_category(name, tools_dict.get(name))
        if cat in cat_set:
            out.add(name)
    return out


def _expand_group_token(
    token: str,
    tools_dict: dict[str, Any],
    merged_groups: dict[str, frozenset[str]],
) -> set[str]:
    t = token.strip()
    if not t:
        return set()
    key = t.lower()
    if key in merged_groups:
        return set(merged_groups[key])
    if key == "group:runtime":
        return {n for n in _RUNTIME_TOOL_NAMES if n in tools_dict}
    if key in _GROUP_TO_CATEGORIES:
        cats = _GROUP_TO_CATEGORIES[key]
        if not cats:
            return set()
        return _tools_for_categories(tools_dict, cats)
    return set()


def _build_default_merged_groups(all_names: set[str], tools_dict: dict[str, Any]) -> dict[str, frozenset[str]]:
    """All group:* keys -> frozenset of tool names."""
    merged: dict[str, frozenset[str]] = {}
    for gname, cats in _GROUP_TO_CATEGORIES.items():
        if gname == "group:runtime":
            merged[gname] = frozenset(n for n in _RUNTIME_TOOL_NAMES if n in tools_dict)
        elif cats:
            merged[gname] = frozenset(_tools_for_categories(tools_dict, cats))
        else:
            merged[gname] = frozenset()
    # group:openclaw = union of common built-ins (everything except exotic plugins — use all registered)
    merged["group:openclaw"] = frozenset(all_names)
    return merged


def _expand_allow_deny_tokens(
    tokens: list[str] | None,
    all_names: set[str],
    tools_dict: dict[str, Any],
    merged_groups: dict[str, frozenset[str]],
    *,
    for_deny: bool = False,
) -> set[str]:
    out: set[str] = set()
    if not tokens:
        return out
    for raw in tokens:
        if not isinstance(raw, str):
            continue
        t = raw.strip()
        if not t:
            continue
        low = t.lower()
        if low == "*":
            if for_deny:
                return set(all_names)  # caller will clear or remove all
            out |= all_names
            continue
        if low.startswith("group:"):
            out |= _expand_group_token(low, tools_dict, merged_groups)
        elif t in tools_dict:
            out.add(t)
        else:
            # glob on tool names
            for name in all_names:
                if fnmatch.fnmatch(name, t):
                    out.add(name)
    return out


def _profile_base_set(
    profile: str,
    all_names: set[str],
    tools_dict: dict[str, Any],
    merged_groups: dict[str, frozenset[str]],
) -> set[str]:
    p = (profile or "full").strip().lower()
    if p in ("", "full", "all"):
        return set(all_names)
    if p == "minimal":
        keep = {"read_file", "list_dir", "search_memories", "save_note"}
        return {n for n in keep if n in all_names}
    if p == "coding":
        s: set[str] = set()
        for g in ("group:fs", "group:code", "group:memory", "group:runtime", "group:analysis"):
            s |= _expand_group_token(g, tools_dict, merged_groups)
        for extra in ("apply_patch", "git_status", "git_diff", "git_log", "fetch_url"):
            if extra in all_names:
                s.add(extra)
        return s
    if p == "messaging":
        s = _expand_group_token("group:memory", tools_dict, merged_groups)
        s |= _expand_group_token("group:web", tools_dict, merged_groups)
        for extra in ("read_file", "list_dir", "fetch_url"):
            if extra in all_names:
                s.add(extra)
        return s
    logger.warning("Unknown tools_profile %r; using full", profile)
    return set(all_names)


def _apply_custom_groups(cfg: dict[str, Any], merged: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    custom = cfg.get("tool_groups")
    if not isinstance(custom, dict):
        return merged
    out = dict(merged)
    for k, v in custom.items():
        if not isinstance(k, str) or not k.startswith("group:"):
            continue
        if isinstance(v, (list, tuple, set)):
            names = frozenset(str(x) for x in v if isinstance(x, str))
            out[k.lower()] = names
    return out


def resolve_effective_tools(
    cfg: dict[str, Any],
    goal: str,
    tools_dict: dict[str, Any],
    *,
    skip_intent_filter: bool = False,
) -> frozenset[str]:
    """
    Resolve tool names allowed for this turn.
    Order: profile base -> union tools_allow -> subtract tools_deny -> intersect intent (unless skipped).
    Always preserves virtual 'reason' for prompts if present in intent set.
    """
    all_names = set(tools_dict.keys())
    merged = _build_default_merged_groups(all_names, tools_dict)
    merged = _apply_custom_groups(cfg, merged)

    profile = cfg.get("tools_profile") or "full"
    effective = _profile_base_set(profile, all_names, tools_dict, merged)

    allow = cfg.get("tools_allow")
    if isinstance(allow, list) and allow:
        effective |= _expand_allow_deny_tokens(allow, all_names, tools_dict, merged, for_deny=False)

    _deny_all = False
    deny = cfg.get("tools_deny")
    if isinstance(deny, list) and deny:
        if any(isinstance(d, str) and d.strip() == "*" for d in deny):
            effective.clear()
            _deny_all = True
        else:
            to_remove = _expand_allow_deny_tokens(deny, all_names, tools_dict, merged, for_deny=True)
            effective -= to_remove

    # Optional per-provider narrowing (remote models)
    tools_by_provider = cfg.get("tools_by_provider")
    if isinstance(tools_by_provider, dict) and tools_by_provider:
        model_hint = str(cfg.get("chat_model") or cfg.get("remote_model_name") or "").lower()
        be = str(cfg.get("inference_backend") or "").lower()
        for prov_key, pol in tools_by_provider.items():
            if not isinstance(prov_key, str) or not isinstance(pol, dict):
                continue
            pk = prov_key.lower()
            matched = pk in model_hint or (model_hint and model_hint in pk) or pk == be or pk in be
            if not matched:
                continue
            p_allow = pol.get("tools_allow")
            p_deny = pol.get("tools_deny")
            if isinstance(p_allow, list) and p_allow:
                allowed = _expand_allow_deny_tokens(p_allow, all_names, tools_dict, merged, for_deny=False)
                effective &= allowed | {"reason"}
            if isinstance(p_deny, list) and p_deny:
                if any(isinstance(d, str) and d.strip() == "*" for d in p_deny):
                    effective.clear()
                    _deny_all = True
                else:
                    rem = _expand_allow_deny_tokens(p_deny, all_names, tools_dict, merged, for_deny=True)
                    effective -= rem
            break

    if skip_intent_filter:
        intent_names = set(all_names) | {"reason"}
    else:
        intent_names = set(get_tool_names_for_goal(goal, tools_dict))

    effective &= intent_names

    SAFETY = frozenset({"read_file", "list_dir", "search_memories", "save_note"})
    if effective and not (effective & SAFETY.intersection(all_names)):
        effective |= {n for n in SAFETY if n in all_names}

    if not effective and not _deny_all:
        effective = {n for n in intent_names if n in all_names or n == "reason"}

    if "reason" in intent_names:
        effective.add("reason")

    logger.debug(
        "tool_policy: profile=%s allow=%s deny=%s -> %d tools",
        profile,
        bool(cfg.get("tools_allow")),
        bool(cfg.get("tools_deny")),
        len(effective),
    )
    return frozenset(effective)


def tool_allowed(intent: str, valid_tools: frozenset[str]) -> bool:
    """True if tool name may execute this turn (reason is not a registry tool)."""
    if intent == "reason" or intent in ("finish", "wakeup"):
        return True
    return intent in valid_tools
