"""
Tool verification and environment observation for the agent loop.

Extracted from agent_loop.py — Phase 2 decomposition.
Handles post-tool validation, deterministic verification, LLM progress checks,
and real-world environment observation.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# Tools that trigger post-execution verification
VERIFY_TOOLS = frozenset({
    "run_python", "apply_patch", "replace_in_file", "shell", "write_file",
    "git_status", "git_diff", "git_log", "git_branch",
})

# Tool output reasons that skip validation
SKIP_TOOL_OUTPUT_VALIDATION = frozenset({
    "approval_required", "tool_policy_denied", "tool_loop_detected",
})


def log_tool_outcome(intent: str, result: object) -> None:
    """Structured INFO log for observability (tool name, ok, reason)."""
    if not isinstance(result, dict):
        logger.info("tool=%s ok=unknown outcome=non_dict", intent)
        return
    ok = result.get("ok")
    reason = result.get("reason") or result.get("error") or ""
    logger.info("tool=%s ok=%s reason=%s", intent, ok, reason or "-")


def maybe_validate_tool_output(intent: str, result: object) -> object:
    """Validate tool output through the tool_output_validator service."""
    if not isinstance(result, dict):
        from services.tools.tool_output_validator import validate_tool_output
        out = validate_tool_output(intent, result)
        log_tool_outcome(intent, out if isinstance(out, dict) else {"ok": True})
        return out
    if result.get("reason") in SKIP_TOOL_OUTPUT_VALIDATION:
        log_tool_outcome(intent, result)
        return result
    from services.tools.tool_output_validator import validate_tool_output
    out = validate_tool_output(intent, result)

    try:
        from core.validator import validate as _core_validate
        vr = _core_validate(intent, out)
        if vr.get("flagged_injection"):
            if isinstance(out, dict):
                out = dict(out)
                out["_injection_flagged"] = True
                out["_injection_warning"] = "Possible prompt injection in tool output"
        if vr.get("warnings"):
            logger.warning("validator: tool=%s warnings=%s", intent, vr["warnings"])
    except Exception as _ve:
        logger.warning("core.validator skipped: %s", _ve)

    log_tool_outcome(intent, out if isinstance(out, dict) else result)
    return out


def apply_deterministic_tool_verification(
    intent: str,
    result: object,
    *,
    workspace: str,
    cfg: dict,
) -> tuple[object, bool, str]:
    """
    Deterministic post-tool semantic verification.
    Returns (possibly-updated-result, verified_ok, reason).

    When enabled, this can downgrade a tool success to a failure if verification fails.
    """
    if not isinstance(result, dict):
        return result, True, "non_dict_result"
    if not result.get("ok"):
        return result, False, "tool_reported_failure"
    try:
        if not bool(cfg.get("deterministic_tool_verification_enabled", True)):
            return result, True, "disabled"
    except Exception as e:
        logger.warning("deterministic_tool_verification config check failed: %s", e, exc_info=True)
        return result, True, "disabled"
    try:
        from services.tools.tool_output_validator import deterministic_verify_tool_result

        vr = deterministic_verify_tool_result(intent, result, workspace_root=workspace or "")
        ok = bool(vr.get("ok"))
        reason = str(vr.get("reason") or ("ok" if ok else "failed"))
        out = dict(result)
        out["_deterministic_verify"] = vr
        out["_deterministic_verified"] = True
        if not ok:
            out["ok"] = False
            out["error"] = out.get("error") or "deterministic_verification_failed"
            out["reason"] = out.get("reason") or reason
        return out, ok, reason
    except Exception as _exc:
        try:
            out = dict(result)
            out["_deterministic_verified"] = False
            out["_deterministic_verify_error"] = str(_exc)[:240]
            return out, True, "verifier_unavailable"
        except Exception as e2:
            logger.warning("deterministic_verify fallback dict copy failed: %s", e2)
            return result, True, "verifier_unavailable"


def verify_tool_progress(
    objective: str,
    steps_text: str,
    tool_name: str,
    result: dict,
) -> dict | None:
    """
    LLM evaluates whether the tool step moved the objective closer.
    Returns {"progress_made": bool, "retry_suggested": bool} or None.
    """
    from services.llm.llm_gateway import run_completion

    obj_short = (objective or "")[:400]
    res_short = str(result)[:500]
    prompt = (
        f"Objective: {obj_short}\n\nLast tool: {tool_name}\nResult: {res_short}\n\n"
        "Did this step move the objective closer? Output exactly one JSON line, no other text. "
        '{"progress_made": true or false, "retry_suggested": true or false}. '
        "retry_suggested true only if a different approach might help.\n"
    )
    try:
        out = run_completion(prompt, max_tokens=60, temperature=0.1, stream=False)
        if isinstance(out, dict):
            text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or (out.get("choices") or [{}])[0].get("text") or ""
        else:
            text = ""
        for line in (text or "").strip().splitlines():
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                if isinstance(data, dict):
                    return {
                        "progress_made": bool(data.get("progress_made", True)),
                        "retry_suggested": bool(data.get("retry_suggested", False)),
                    }
        return None
    except Exception as e:
        logger.debug("verify_tool_progress parse failed: %s", e)
        return None


def observe_environment(tool_name: str, result: dict, workspace: str) -> bool:
    """
    Lightweight environment checks after a tool run. Returns True if observed state
    aligns with success (e.g. file changed, artifacts exist, command side-effects).
    """
    if not isinstance(result, dict) or not result.get("ok"):
        return False
    try:
        workspace_path = Path(workspace or ".").resolve()
        if tool_name == "run_python":
            return result.get("returncode", -1) == 0
        if tool_name == "apply_patch":
            p = result.get("path") or result.get("original_path")
            if not p:
                return True
            path = Path(p)
            if not path.is_absolute():
                path = workspace_path / path
            return path.exists()
        if tool_name == "shell":
            return result.get("returncode", -1) == 0
        if tool_name == "write_file":
            p = result.get("path")
            if not p:
                return True
            path = Path(p)
            if not path.is_absolute():
                path = workspace_path / path
            return path.exists() and path.stat().st_size >= 0
        if tool_name == "replace_in_file":
            p = result.get("path")
            if not p:
                return True
            path = Path(p)
            if not path.is_absolute():
                path = workspace_path / path
            return path.exists()
        if tool_name in ("git_status", "git_diff", "git_log", "git_branch"):
            return True
    except Exception as e:
        logger.debug("observe_environment failed: %s", e)
        return False
    return True


def run_verification_after_tool(
    state: dict,
    tool_name: str,
    result: dict,
    workspace: str = "",
    *,
    format_steps_fn=None,
) -> None:
    """If tool is verifiable and succeeded, run verification and environment observation; update state."""
    import runtime_safety

    if tool_name not in VERIFY_TOOLS or not (isinstance(result, dict) and result.get("ok")):
        return
    objective = state.get("objective") or state.get("original_goal") or ""
    steps_text = format_steps_fn(state.get("steps") or []) if format_steps_fn else ""
    try:
        cfg_v = runtime_safety.load_config()
        llm_verify = bool(cfg_v.get("llm_tool_verification_enabled", True))
    except Exception as e:
        logger.warning("llm_tool_verification config load failed: %s", e, exc_info=True)
        llm_verify = True
    ver = verify_tool_progress(objective, steps_text, tool_name, result) if llm_verify else None
    if ver is not None:
        state["last_verification"] = ver
        if not ver.get("progress_made", True):
            state["consecutive_no_progress"] = state.get("consecutive_no_progress", 0) + 1
        else:
            state["consecutive_no_progress"] = 0
    state["environment_aligned"] = observe_environment(tool_name, result, workspace)
    if ver and ver.get("progress_made") and not state.get("environment_aligned", True):
        state["consecutive_no_progress"] = state.get("consecutive_no_progress", 0) + 1
    if state.get("consecutive_no_progress", 0) > 0:
        from services.infrastructure.failure_recovery import classify_failure_and_recovery
        classify_failure_and_recovery(state)


def run_edit_postchecks(
    state: dict,
    intent: str,
    raw_result: object,
    *,
    workspace: str,
    cfg: dict,
    re_execute=None,
) -> tuple[object, bool, str]:
    """Validate tool output, deterministic verification, optional single retry."""
    _res = maybe_validate_tool_output(intent, raw_result)
    _res, ok, reason = apply_deterministic_tool_verification(intent, _res, workspace=workspace, cfg=cfg)
    if (
        not ok
        and bool(cfg.get("deterministic_tool_verification_auto_retry", True))
        and re_execute is not None
    ):
        state.setdefault("_deterministic_retry_counts", {})
        cnt = int(state["_deterministic_retry_counts"].get(intent) or 0)
        if cnt < 1:
            state["_deterministic_retry_counts"][intent] = cnt + 1
            raw2 = re_execute()
            _res = maybe_validate_tool_output(intent, raw2)
            _res, ok, reason = apply_deterministic_tool_verification(intent, _res, workspace=workspace, cfg=cfg)
            if isinstance(_res, dict):
                _res["_deterministic_retry"] = True
                _res["_deterministic_retry_reason"] = reason
    return _res, ok, reason
