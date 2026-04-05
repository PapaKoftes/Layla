"""
agent/core/validator.py — Phase 5: Validate

Runs after every tool execution. Always runs — cannot be skipped.

Checks:
  1. schema_valid   — result is a dict with at least an 'ok' key
  2. not_empty      — result has some content
  3. size_ok        — result fits within token budget
  4. no_injection   — no prompt injection patterns in string values
  5. consistent     — result appears related to the original goal (heuristic)

Returns ValidationResult. Never raises. A failed check does NOT abort the loop;
it annotates the result with warnings and flags it for the planner.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("layla")

# Patterns that suggest a tool output is trying to inject instructions into the model
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\n\nHuman:", re.IGNORECASE),
    re.compile(r"\n\nAssistant:", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"<\|im_start\|>"),
    re.compile(r"<\|im_end\|>"),
    re.compile(r"</s>"),
    re.compile(r"<\|endoftext\|>"),
    re.compile(r"\n\n###\s*(Human|User|Assistant|System)\s*:", re.IGNORECASE),
    re.compile(r"ignore (previous|all|above) instructions", re.IGNORECASE),
    re.compile(r"disregard (previous|all|above) instructions", re.IGNORECASE),
]

_MAX_RESULT_TOKENS = 4096  # approximate token ceiling for a single tool result


def validate(
    tool_name: str,
    result: Any,
    goal: str = "",
) -> dict[str, Any]:
    """
    Validate a tool result and return a ValidationResult.

      {
        passed:  bool,
        checks:  {schema_valid, not_empty, size_ok, no_injection, consistent},
        warnings: [str],
        flagged_injection: bool,
        annotated_result: <original result, possibly prefixed with warning>
      }
    """
    checks: dict[str, bool] = {
        "schema_valid": False,
        "not_empty": False,
        "size_ok": True,
        "no_injection": True,
        "consistent": True,
    }
    warnings: list[str] = []
    flagged_injection = False

    # 1. Schema check
    if isinstance(result, dict) and "ok" in result:
        checks["schema_valid"] = True
    else:
        warnings.append(f"schema_invalid: result for {tool_name!r} is not a dict with 'ok' key")

    # 2. Not empty
    if result is not None and result != {} and result != "":
        checks["not_empty"] = True
    else:
        warnings.append(f"empty_result: {tool_name!r} returned no content")

    # 3. Size check (approximate)
    result_str = _to_str(result)
    approx_tokens = max(1, len(result_str) // 4)
    if approx_tokens > _MAX_RESULT_TOKENS:
        checks["size_ok"] = False
        warnings.append(
            f"oversized_result: {tool_name!r} returned ~{approx_tokens} tokens (limit {_MAX_RESULT_TOKENS})"
        )

    # 4. Injection scan
    injection_hits = _scan_injection(result_str)
    if injection_hits:
        checks["no_injection"] = False
        flagged_injection = True
        warnings.append(
            f"possible_injection: {tool_name!r} output matched patterns: {injection_hits}"
        )
        logger.warning(
            "validator: tool=%s possible prompt injection detected patterns=%s",
            tool_name,
            injection_hits,
        )

    # 5. Consistency (goal keyword overlap — heuristic only)
    if goal and result_str:
        goal_words = set(re.findall(r"\b\w{4,}\b", goal.lower()))
        result_words = set(re.findall(r"\b\w{4,}\b", result_str.lower()))
        if goal_words and len(goal_words & result_words) == 0:
            checks["consistent"] = False
            # Only a warning — many valid results won't share keywords with the goal
            warnings.append(f"low_consistency: {tool_name!r} result shares no keywords with goal")

    passed = checks["schema_valid"] and checks["not_empty"] and checks["no_injection"]

    # Annotate result if injection detected
    annotated_result = result
    if flagged_injection and isinstance(result, dict):
        annotated_result = dict(result)
        annotated_result["_injection_flagged"] = True
        annotated_result["_injection_warning"] = "Possible prompt injection detected in tool output"

    if warnings:
        logger.debug("validator: tool=%s warnings=%s", tool_name, warnings)

    return {
        "passed": passed,
        "checks": checks,
        "warnings": warnings,
        "flagged_injection": flagged_injection,
        "annotated_result": annotated_result,
    }


def _to_str(result: Any) -> str:
    """Flatten result to a string for pattern scanning."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        parts = []
        for v in result.values():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, (list, dict)):
                parts.append(str(v))
        return "\n".join(parts)
    return str(result) if result is not None else ""


def _scan_injection(text: str) -> list[str]:
    """Return list of pattern names that matched."""
    if not text:
        return []
    hits = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            hits.append(pattern.pattern[:30])
    return hits
