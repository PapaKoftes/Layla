"""Shared foundation for tool_dispatch (BL-029 split).

The DispatchContext/DispatchResult data structures, the shared handler helpers, and the
hardcoded-intents set. Imported by tool_dispatch.py (handlers + router) — this module imports
nothing back from it, so there is no cycle.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla.tool_dispatch")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DispatchContext:
    """All state and config needed by tool dispatch handlers."""
    state: dict
    cfg: dict
    workspace: str
    decision: dict | None
    allow_write: bool
    allow_run: bool
    reasoning_mode: str
    ux_state_queue: Any          # queue.Queue | None
    show_thinking: bool


@dataclass
class DispatchResult:
    """Outcome of dispatching a tool intent.

    *handled*  – ``True`` if the intent was recognised and processed.
    *flow*     – ``"continue"`` → next loop iteration; ``"break"`` → exit loop.
    *goal*     – Updated goal string for the next iteration.
    """
    handled: bool = False
    flow: str = "continue"
    goal: str = ""


# ---------------------------------------------------------------------------
# Lazy imports  (avoids circular import with agent_loop)
# ---------------------------------------------------------------------------

_cached_imports = None


def _compact_args(args: Any, *, max_str: int = 500) -> dict:
    """A shallow, size-capped snapshot of tool args for step recording / macros.

    Truncates long string values so replaying/recording a run as a macro (BL-231)
    stays cheap; non-dict inputs collapse to ``{}``.
    """
    if not isinstance(args, dict):
        return {}
    out: dict = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > max_str:
            out[k] = v[:max_str] + f"…(+{len(v) - max_str} chars)"
        else:
            out[k] = v
    return out


def _imports():
    """Return ``(agent_loop, runtime_safety, TOOLS)`` with lazy loading. Cached after first call."""
    global _cached_imports
    if _cached_imports is not None:
        return _cached_imports
    import agent_loop as al  # noqa: E402 — safe; fully loaded by call-time
    import runtime_safety as rs  # noqa: E402
    from layla.tools.registry import TOOLS  # noqa: E402
    _cached_imports = (al, rs, TOOLS)
    return _cached_imports


def _rebuild_goal(state: dict) -> str:
    al, _, _ = _imports()
    return state["original_goal"] + "\n\n[Tool results so far]:\n" + al._format_steps(state["steps"])


# ---------------------------------------------------------------------------
# Permission bypass
# ---------------------------------------------------------------------------

_bypass_warned = set()  # tracks tools we've already warned about


def _is_approval_bypassed(ctx: DispatchContext, tool_name: str) -> bool:
    """Check if tool approval should be bypassed.

    When ``tool_approval_bypass`` is ``True`` in config, all approval checks
    are skipped.  A warning is logged once per tool name per process lifetime
    so the user knows which tools are running unsupervised.

    Returns True if the caller should *skip* the approval check.
    """
    if not ctx.cfg.get("tool_approval_bypass", False):
        return False
    # A2b: never honor the approval bypass while the server is remotely exposed. Otherwise an
    # authenticated remote caller's writes/exec would run unsupervised (the remote allow_write
    # strip is overridden by this flag). Unsupervised local exec OR remote exposure — not both.
    if ctx.cfg.get("remote_enabled", False):
        if "__remote_bypass_blocked" not in _bypass_warned:
            _bypass_warned.add("__remote_bypass_blocked")
            logger.warning(
                "tool_approval_bypass IGNORED because remote_enabled is on — approvals stay "
                "enforced while the server is network-exposed (safety)."
            )
        return False
    if tool_name not in _bypass_warned:
        _bypass_warned.add(tool_name)
        logger.warning(
            "⚠ tool_approval_bypass active — '%s' executing WITHOUT approval. "
            "Disable 'tool_approval_bypass' in runtime_config.json to restore safety checks.",
            tool_name,
        )
        try:
            from services.observability.security_audit import log_policy_bypass_attempt
            log_policy_bypass_attempt(
                "tool_approval_bypass",
                detail=f"tool={tool_name}",
                blocked=False,
            )
        except Exception:
            pass
    return True


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _deterministic_verify_retry(intent, state, cfg, workspace, _res, execute_fn, log_args):
    """Apply deterministic verification + optional auto-retry.  Returns ``(_res, ok, reason)``."""
    al, rs, _ = _imports()
    _res, _ok, _reason = al._apply_deterministic_tool_verification(
        intent, _res, workspace=workspace, cfg=cfg,
    )
    if not _ok and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
        state.setdefault("_deterministic_retry_counts", {})
        _cnt = int(state["_deterministic_retry_counts"].get(intent) or 0)
        if _cnt < 1:
            state["_deterministic_retry_counts"][intent] = _cnt + 1
            result2 = execute_fn()
            rs.log_execution(intent, dict(log_args) | {"_retry": True})
            _res = al._maybe_validate_tool_output(intent, result2)
            _res, _ok, _reason = al._apply_deterministic_tool_verification(
                intent, _res, workspace=workspace, cfg=cfg,
            )
            if isinstance(_res, dict):
                _res["_deterministic_retry"] = True
                _res["_deterministic_retry_reason"] = _reason
    return _res, _ok, _reason


def _approval_break(intent, args, ctx) -> DispatchResult:
    """Return a DispatchResult that requests approval and breaks the loop."""
    al, _, _ = _imports()
    al._approval_preview_diff(intent, args, ctx.workspace)
    approval_id = al._write_pending(intent, args)
    ctx.state["steps"].append({
        "action": intent,
        "result": {
            "ok": False,
            "reason": "approval_required",
            "approval_id": approval_id,
            "message": f"Run: layla approve {approval_id}",
        },
    })
    ctx.state["status"] = "finished"
    return DispatchResult(handled=True, flow="break", goal=_rebuild_goal(ctx.state))


def _lab_blocked(intent, state) -> DispatchResult:
    """Block a tool in research-lab mode and continue."""
    # Rejected — no tool ran; accrue to blocked_calls, not the real tool budget.
    state["blocked_calls"] = state.get("blocked_calls", 0) + 1
    state["steps"].append({
        "action": intent,
        "result": {"ok": False, "reason": "not_allowed_in_research",
                   "message": f"{intent} not allowed in research missions"},
    })
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


def _base_tool_handler(ctx: DispatchContext, tool_name: str, tool_fn, args: dict, **opts):
    """Shared boilerplate for tool execution.

    Consolidates the repeated execute-validate-verify-record pattern found
    across most read/read-write tool handlers.

    Parameters
    ----------
    ctx : DispatchContext
        The tool execution context.
    tool_name : str
        Name of the tool being executed.
    tool_fn : callable
        The actual tool implementation to call.
    args : dict
        Arguments to pass to *tool_fn*.
    opts : dict
        Optional overrides:
        - needs_approval: bool (default False)
            If True, check approval/grant before execution.
        - needs_sandbox: bool (default True)
            If True, honour lab-root sandbox restrictions.
        - auto_commit: bool (default False)
            If True, run git auto-commit after successful execution.
        - auto_lint: bool (default False)
            If True, run auto lint/test/fix after execution (when reasoning_mode != "none").
        - verify: bool (default True)
            If True, run _run_verification_after_tool + UX emit.
        - log_args: dict | None
            Override dict passed to rs.log_execution (defaults to *args*).
        - commit_path: str | None
            File path for git auto-commit (required when auto_commit=True).
        - lint_path: str | None
            File path for lint step (defaults to commit_path).

    Returns
    -------
    DispatchResult
    """
    al, rs, TOOLS = _imports()
    state = ctx.state
    cfg = ctx.cfg
    workspace = ctx.workspace
    decision = ctx.decision

    needs_approval = opts.get("needs_approval", False)
    needs_sandbox = opts.get("needs_sandbox", True)
    auto_commit = opts.get("auto_commit", False)
    auto_lint = opts.get("auto_lint", False)
    verify = opts.get("verify", True)
    log_args = opts.get("log_args", args)
    commit_path = opts.get("commit_path")
    lint_path = opts.get("lint_path") or commit_path

    # --- sandbox / lab-root check -----------------------------------------
    if needs_sandbox and state.get("research_lab_root"):
        return _lab_blocked(tool_name, state)

    # --- approval check ---------------------------------------------------
    if needs_approval and not _is_approval_bypassed(ctx, tool_name):
        if not ctx.allow_write or (
            not rs.is_tool_allowed(tool_name)
            and not al._has_any_grant(tool_name, args)
        ):
            return _approval_break(tool_name, dict(args), ctx)

    # --- execute ----------------------------------------------------------
    state["tool_calls"] += 1
    result = tool_fn(**args)
    al._register_exact_tool_call(state, tool_name, decision)
    rs.log_execution(tool_name, log_args)

    # --- validate output + deterministic verify / retry -------------------
    _res = al._maybe_validate_tool_output(tool_name, result)
    _res, _, _ = _deterministic_verify_retry(
        tool_name, state, cfg, workspace, _res,
        lambda: tool_fn(**args),
        log_args,
    )

    # --- record step ------------------------------------------------------
    # `args` is a compact snapshot (long values truncated) so a run can be
    # replayed/recorded as a macro (BL-231); the step formatter ignores it.
    state["steps"].append({"action": tool_name, "result": _res, "args": _compact_args(log_args)})
    state["last_tool_used"] = tool_name

    # --- optional verification --------------------------------------------
    if verify:
        al._run_verification_after_tool(
            state, tool_name, _res if isinstance(_res, dict) else result, workspace,
        )
        al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)

    # --- optional git auto-commit -----------------------------------------
    if auto_commit and commit_path:
        al._run_git_auto_commit(tool_name, result, commit_path, workspace)

    # --- optional lint / test / fix ---------------------------------------
    new_goal = _rebuild_goal(state)
    if auto_lint and lint_path and ctx.reasoning_mode != "none":
        hint = al._run_auto_lint_test_fix(state, tool_name, result, lint_path, workspace)
        if hint:
            new_goal += "\n\n" + hint

    return DispatchResult(handled=True, flow="continue", goal=new_goal)


# ---------------------------------------------------------------------------
# Intents with dedicated handlers (used by generic dispatch as exclusion set)
# ---------------------------------------------------------------------------

_HARDCODED_INTENTS = frozenset({
    "reason", "write_file", "read_file", "list_dir", "git_status", "git_diff",
    "git_log", "git_branch", "grep_code", "glob_files", "search_codebase",
    "run_python", "apply_patch", "fetch_url", "shell", "mcp_tools_call",
    "json_query", "diff_files", "env_info", "regex_test", "save_note",
    "search_memories", "git_add", "git_commit", "get_project_context",
    "update_project_context", "understand_file", "write_files_batch",
    "replace_in_file",
})
