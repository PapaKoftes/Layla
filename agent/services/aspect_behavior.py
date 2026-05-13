# -*- coding: utf-8 -*-
"""
aspect_behavior.py -- Aspect behavioral separation layer.

Translates the `behavior` block in each personality JSON into concrete
runtime decisions: reasoning depth, response length, step limits, and
per-aspect prompt instructions that make aspects genuinely different at
execution time -- not just in voice.

Why separate from orchestrator.py:
  - orchestrator handles selection and deliberation routing
  - this module handles per-turn execution parameters
  - keeps both files focused and independently testable

Behavior fields (in personality JSON under key "behavior"):
    reasoning_depth_bias   -- "deep" | "light" | "auto"
        Forces or biases reasoning classification. "auto" defers to the
        classifier. "deep" upgrades "light" to "deep". "light" downgrades
        "deep" to "light" unless the goal explicitly asks for deep analysis.

    response_length_bias   -- "concise" | "medium" | "thorough"
        Injects a length instruction into the system prompt. Does not
        set max_tokens; it tells the model via language.

    max_steps_bias         -- int (default 6)
        Suggested upper bound on autonomous tool-use steps. agent_loop
        uses this as the plan_depth cap when not overridden by the caller.

    refusal_topics         -- list[str]
        Topics this aspect will actively push back on. Injected as an
        explicit instruction line. Lilith: ["harm", "manipulation"].

Public API:
    apply_reasoning_depth(aspect, current_mode)  -> str  (new mode)
    get_max_steps(aspect, base_limit)            -> int
    build_behavior_block(aspect)                 -> str  (for prompt injection)
    get_refusal_topics(aspect)                   -> list[str]
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Defaults when no behavior block present
# ---------------------------------------------------------------------------

_DEFAULT_DEPTH   = "auto"
_DEFAULT_LENGTH  = "medium"
_DEFAULT_STEPS   = 6

# Minimum steps allowed even for concise aspects (single-shot still needs at
# least 1 reasoning step).
_MIN_STEPS = 2
_MAX_STEPS = 20  # absolute ceiling regardless of aspect

# ---------------------------------------------------------------------------
# Response length -> prompt instruction
# ---------------------------------------------------------------------------

_LENGTH_INSTRUCTIONS: dict[str, str] = {
    "concise": (
        "Response length: concise. Lead with the answer. "
        "One short code block or paragraph maximum. No padding."
    ),
    "medium": (
        "Response length: balanced. Cover what is needed; "
        "trim what isn't. No forced brevity, no waffle."
    ),
    "thorough": (
        "Response length: thorough. Explain reasoning, trade-offs, "
        "and edge cases. Use structure (headers/bullets) when it aids clarity."
    ),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_behavior(aspect: dict) -> dict:
    b = (aspect or {}).get("behavior")
    return b if isinstance(b, dict) else {}


def _depth_bias(aspect: dict) -> str:
    return str(_get_behavior(aspect).get("reasoning_depth_bias") or _DEFAULT_DEPTH).strip().lower()


def _length_bias(aspect: dict) -> str:
    v = str(_get_behavior(aspect).get("response_length_bias") or _DEFAULT_LENGTH).strip().lower()
    return v if v in _LENGTH_INSTRUCTIONS else _DEFAULT_LENGTH


def _steps_bias(aspect: dict) -> int:
    try:
        v = int(_get_behavior(aspect).get("max_steps_bias") or _DEFAULT_STEPS)
        return max(_MIN_STEPS, min(_MAX_STEPS, v))
    except (TypeError, ValueError):
        return _DEFAULT_STEPS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_reasoning_depth(aspect: dict, current_mode: str) -> str:
    """
    Apply aspect reasoning_depth_bias to an already-classified mode.

    Rules:
      "deep"  -> always return "deep" (never downgrade to none/light)
      "light" -> return "light" unless current_mode is already "none"
                 (trivial turns stay trivial regardless of aspect)
      "auto"  -> return current_mode unchanged

    Args:
        aspect:       aspect dict (may be empty / None)
        current_mode: output from reasoning_classifier ("none"|"light"|"deep")

    Returns:
        adjusted mode string
    """
    if not aspect:
        return current_mode

    bias = _depth_bias(aspect)
    mode = (current_mode or "light").strip().lower()

    if bias == "deep":
        # Upgrade light -> deep; keep deep; keep none (trivial stays trivial)
        if mode == "none":
            return "none"
        return "deep"

    if bias == "light":
        # Downgrade deep -> light; keep light/none
        if mode == "deep":
            return "light"
        return mode

    # "auto" -- pass through
    return mode


def get_max_steps(aspect: dict, base_limit: int | None = None) -> int:
    """
    Return the effective max autonomous steps for this aspect.

    If base_limit is provided and lower than the aspect bias, the lower
    value wins (caller can always set a tighter cap).

    Args:
        aspect:     aspect dict
        base_limit: caller-supplied limit (None = use aspect bias only)

    Returns:
        int step limit
    """
    bias = _steps_bias(aspect)
    if base_limit is not None:
        try:
            caller_limit = max(_MIN_STEPS, min(_MAX_STEPS, int(base_limit)))
            return min(bias, caller_limit)
        except (TypeError, ValueError):
            pass
    return bias


def get_refusal_topics(aspect: dict) -> list[str]:
    """Return list of refusal topic strings for this aspect (may be empty)."""
    raw = _get_behavior(aspect).get("refusal_topics")
    if isinstance(raw, list):
        return [str(t).strip().lower() for t in raw if t]
    return []


def build_behavior_block(aspect: dict) -> str:
    """
    Build the behavioral instruction block to inject into the system prompt.
    Returns empty string for fully neutral aspects (all defaults).

    Includes:
      - Response length instruction
      - Refusal topic warning (if any)
    Does NOT include reasoning depth (that controls the reasoning classifier,
    not the model's self-reported tone).
    """
    if not aspect:
        return ""

    parts: list[str] = []

    # Response length
    length = _length_bias(aspect)
    if length != _DEFAULT_LENGTH:  # only inject non-default lengths
        instruction = _LENGTH_INSTRUCTIONS.get(length, "")
        if instruction:
            parts.append(instruction)

    # Refusal topics
    topics = get_refusal_topics(aspect)
    if topics:
        topic_str = ", ".join(topics)
        parts.append(
            f"Refusal topics for this aspect: [{topic_str}]. "
            "If the request directly involves these, refuse clearly and briefly."
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Aspect tool preferences
# ---------------------------------------------------------------------------

ASPECT_TOOL_PREFERENCES: dict[str, dict[str, list[str]]] = {
    "cassandra": {
        "boost": ["read_file", "grep_code", "run_python", "git_diff", "understand_file"],
        "suppress": ["fetch_url"],
    },
    "echo": {
        "boost": ["search_memories", "save_learning"],
        "suppress": ["run_shell"],
    },
    "nyx": {
        "boost": ["grep_code", "read_file", "understand_file", "git_log"],
        "suppress": [],
    },
    "eris": {
        "boost": ["web_search", "fetch_url", "brainstorm"],
        "suppress": [],
    },
    "morrigan": {
        "boost": ["create_plan", "execute_plan", "list_dir"],
        "suppress": [],
    },
    "lilith": {
        "boost": ["search_memories"],
        "suppress": ["run_shell", "run_python", "write_file"],
    },
}


def get_tool_preferences(aspect_id: str) -> dict:
    """Return tool preference weights for an aspect.

    Returns a dict with ``boost`` (list of tool names the aspect favours)
    and ``suppress`` (list of tool names the aspect avoids).
    """
    return ASPECT_TOOL_PREFERENCES.get(aspect_id, {"boost": [], "suppress": []})


def get_behavior_summary(aspect: dict) -> dict:
    """
    Return a structured summary of the active behavioral parameters.
    Useful for observability/logging.
    """
    return {
        "aspect_id":            (aspect or {}).get("id", "unknown"),
        "reasoning_depth_bias": _depth_bias(aspect),
        "response_length_bias": _length_bias(aspect),
        "max_steps_bias":       _steps_bias(aspect),
        "refusal_topics":       get_refusal_topics(aspect),
    }
