"""Tool dispatch handlers extracted from agent_loop._autonomous_run_impl_core.

This module contains the if-elif tool routing logic that dispatches tool intents
to their respective handlers.  Each handler mirrors the original inline code but
returns a :class:`DispatchResult` to control the outer loop's flow.

Dependencies on ``agent_loop`` helper functions are accessed via **lazy import**
to avoid circular import at module-load time.
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
    state["tool_calls"] += 1
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
    if needs_approval:
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
    state["steps"].append({"action": tool_name, "result": _res})
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


# ===================================================================
# WRITE FILE
# ===================================================================

def _handle_write_file(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, cfg, workspace, decision = ctx.state, ctx.cfg, ctx.workspace, ctx.decision

    path, content = al._extract_file_and_content(goal)
    if not path:
        state["status"] = "parse_failed"
        return DispatchResult(handled=True, flow="break", goal=goal)

    lab_root = state.get("research_lab_root") or ""
    if lab_root and workspace and not Path(path).is_absolute():
        path = str(Path(workspace) / path)

    # --- lab-root path ---------------------------------------------------
    if lab_root:
        if not al._path_under_lab(path, lab_root):
            state["tool_calls"] += 1
            state["steps"].append({
                "action": "write_file",
                "result": {"ok": False, "reason": "research_lab_only",
                           "message": "Writes allowed only inside .research_lab"},
            })
            return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

        state["tool_calls"] += 1
        al._admin_pre_mutate(cfg, workspace, "write_file", path)
        result = TOOLS["write_file"]["fn"](path=path, content=content)
        al._register_exact_tool_call(state, "write_file", decision)
        rs.log_execution("write_file", {"path": path})
        _res, _, _ = al._run_edit_postchecks(
            state, "write_file", result, workspace=workspace, cfg=cfg,
            re_execute=lambda: TOOLS["write_file"]["fn"](path=path, content=content),
        )
        state["steps"].append({"action": "write_file", "result": _res})
        state["last_tool_used"] = "write_file"
        al._run_verification_after_tool(state, "write_file", _res if isinstance(_res, dict) else result, workspace)
        al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
        al._run_git_auto_commit("write_file", result, result.get("path") or path, workspace)
        new_goal = _rebuild_goal(state)
        if ctx.reasoning_mode != "none":
            hint = al._run_auto_lint_test_fix(state, "write_file", result, result.get("path") or path, workspace)
            if hint:
                new_goal += "\n\n" + hint
        return DispatchResult(handled=True, flow="continue", goal=new_goal)

    # --- normal path: approval check -------------------------------------
    _wf_grant_args = {"path": path}
    if not ctx.allow_write or (not rs.is_tool_allowed("write_file") and not al._has_any_grant("write_file", _wf_grant_args)):
        return _approval_break("write_file", {"path": path, "content": content}, ctx)

    target = Path(path)
    if rs.is_protected(target):
        if not rs.backup_file(target):
            state["steps"].append({"action": "write_file", "result": {"ok": False, "reason": "backup_failed"}})
            state["status"] = "finished"
            return DispatchResult(handled=True, flow="break", goal=goal)

    state["tool_calls"] += 1
    al._admin_pre_mutate(cfg, workspace, "write_file", path)
    result = TOOLS["write_file"]["fn"](path=path, content=content)
    al._register_exact_tool_call(state, "write_file", decision)
    rs.log_execution("write_file", {"path": path})
    _res, _, _ = al._run_edit_postchecks(
        state, "write_file", result, workspace=workspace, cfg=cfg,
        re_execute=lambda: TOOLS["write_file"]["fn"](path=path, content=content),
    )
    state["steps"].append({"action": "write_file", "result": _res})
    state["last_tool_used"] = "write_file"
    al._run_verification_after_tool(state, "write_file", _res if isinstance(_res, dict) else result, workspace)
    al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
    al._run_git_auto_commit("write_file", result, result.get("path") or path, workspace)
    new_goal = _rebuild_goal(state)
    if ctx.reasoning_mode != "none":
        hint = al._run_auto_lint_test_fix(state, "write_file", result, result.get("path") or path, workspace)
        if hint:
            new_goal += "\n\n" + hint
    return DispatchResult(handled=True, flow="continue", goal=new_goal)


# ===================================================================
# WRITE FILES BATCH
# ===================================================================

def _handle_write_files_batch(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, _, workspace, decision = ctx.state, ctx.cfg, ctx.workspace, ctx.decision

    args = (decision.get("args") or {}) if decision else {}
    files = args.get("files") or []
    if not isinstance(files, list) or not files:
        state["steps"].append({
            "action": "write_files_batch",
            "result": {"ok": False, "error": "write_files_batch requires args.files: [{path, content}, ...]"},
        })
        return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

    if not ctx.allow_write or (
        not rs.is_tool_allowed("write_files_batch")
        and not al._has_any_grant("write_files_batch", {"files": [f.get("path", "") for f in files][:1]})
    ):
        return _approval_break("write_files_batch", {"files": files}, ctx)

    state["tool_calls"] += 1
    result = TOOLS["write_files_batch"]["fn"](files=files)
    al._register_exact_tool_call(state, "write_files_batch", decision)
    rs.log_execution("write_files_batch", {"count": len(files)})
    _res = al._maybe_validate_tool_output("write_files_batch", result)

    # Deterministic batch verification
    try:
        if isinstance(_res, dict) and _res.get("ok") and isinstance(_res.get("written"), list):
            from services.tool_output_validator import deterministic_verify_tool_result
            _batch_v: list[dict] = []
            _batch_ok = True
            for _p in [str(x) for x in (_res.get("written") or []) if str(x).strip()][:50]:
                vr = deterministic_verify_tool_result(
                    "write_file", {"ok": True, "path": _p}, workspace_root=workspace or "",
                )
                _batch_v.append({"path": _p, **(vr if isinstance(vr, dict) else {"ok": False, "reason": "bad_verifier_return"})})
                if not bool(vr.get("ok")):
                    _batch_ok = False
            _res["_deterministic_verify_batch"] = _batch_v
            if not _batch_ok:
                _res["ok"] = False
                _res["error"] = _res.get("error") or "deterministic_batch_verification_failed"
                _res["reason"] = _res.get("reason") or "deterministic_batch_verification_failed"
    except Exception as _exc:
        if isinstance(_res, dict):
            _res["_deterministic_verify_batch_error"] = str(_exc)[:240]

    state["steps"].append({"action": "write_files_batch", "result": _res})
    state["last_tool_used"] = "write_files_batch"
    if result.get("ok") and result.get("written"):
        for p in result.get("written", [])[:1]:
            al._run_git_auto_commit("write_files_batch", result, p, workspace)
            break

    new_goal = _rebuild_goal(state)
    if ctx.reasoning_mode != "none" and isinstance(_res, dict) and _res.get("ok"):
        wp = ""
        wlist = _res.get("written") if isinstance(_res.get("written"), list) else []
        if wlist:
            wp = str(wlist[0] or "").strip()
        if not wp:
            wp = workspace
        if wp:
            lh = al._run_auto_lint_test_fix(state, "write_files_batch", _res, wp, workspace)
            if lh:
                new_goal += "\n\n" + lh
    return DispatchResult(handled=True, flow="continue", goal=new_goal)


# ===================================================================
# READ FILE
# ===================================================================

def _handle_read_file(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, _, TOOLS = _imports()
    state = ctx.state

    path = al._extract_path(goal)
    if not path:
        state["status"] = "parse_failed"
        return DispatchResult(handled=True, flow="break", goal=goal)

    probe = al._maybe_preprobe_file(state, path)
    if not al._apply_probe_guidance(state, "read_file", path, probe):
        return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

    return _base_tool_handler(
        ctx, "read_file", TOOLS["read_file"]["fn"],
        args={"path": path},
        log_args={"path": path},
        verify=False,
    )


# ===================================================================
# LIST DIR
# ===================================================================

def _handle_list_dir(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, _, TOOLS = _imports()

    path = al._extract_path(goal) or ctx.workspace
    return _base_tool_handler(
        ctx, "list_dir", TOOLS["list_dir"]["fn"],
        args={"path": path},
        log_args={"path": path},
        verify=False,
    )


# ===================================================================
# GIT STATUS / DIFF / LOG / BRANCH  (simple read-only tools)
# ===================================================================

def _handle_simple_git(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, workspace, decision = ctx.state, ctx.workspace, ctx.decision

    state["tool_calls"] += 1
    git_args = {"repo": workspace}
    if intent == "git_log":
        git_args["n"] = 10
    result = TOOLS[intent]["fn"](**git_args)
    al._register_exact_tool_call(state, intent, decision)
    rs.log_execution(intent, {"repo": workspace})
    state["steps"].append({"action": intent, "result": al._maybe_validate_tool_output(intent, result)})
    state["last_tool_used"] = intent
    al._run_verification_after_tool(state, intent, result, workspace)
    al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


# ===================================================================
# GREP CODE
# ===================================================================

def _handle_grep_code(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, _, TOOLS = _imports()

    parts = goal.split()
    pattern = parts[-1] if parts else ""
    grep_path = ctx.workspace
    maybe_path = al._extract_path(goal)
    if maybe_path and Path(maybe_path).suffix:
        probe = al._maybe_preprobe_file(ctx.state, maybe_path)
        al._apply_probe_guidance(ctx.state, "grep_code", maybe_path, probe)
        grep_path = maybe_path

    return _base_tool_handler(
        ctx, "grep_code", TOOLS["grep_code"]["fn"],
        args={"pattern": pattern, "path": grep_path},
        log_args={"pattern": pattern, "path": grep_path},
        verify=False,
    )


# ===================================================================
# GLOB FILES
# ===================================================================

def _handle_glob_files(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    _, _, TOOLS = _imports()

    parts = goal.split()
    pattern = parts[-1] if parts else "*"
    return _base_tool_handler(
        ctx, "glob_files", TOOLS["glob_files"]["fn"],
        args={"pattern": pattern, "root": ctx.workspace},
        log_args={"pattern": pattern, "root": ctx.workspace},
        verify=False,
    )


# ===================================================================
# RUN PYTHON
# ===================================================================

def _handle_run_python(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, cfg, workspace, decision = ctx.state, ctx.cfg, ctx.workspace, ctx.decision

    lab_root = state.get("research_lab_root") or ""

    if lab_root:
        if not ctx.allow_run:
            state["tool_calls"] += 1
            state["steps"].append({
                "action": "run_python",
                "result": {"ok": False, "reason": "disabled_in_research",
                           "message": "run_python is disabled for this research stage. Use read_file, list_dir, grep_code instead."},
            })
            return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

        if not al._path_under_lab(workspace, lab_root):
            state["tool_calls"] += 1
            state["steps"].append({
                "action": "run_python",
                "result": {"ok": False, "reason": "research_lab_only",
                           "message": "run_python allowed only with cwd inside .research_lab"},
            })
            return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

        # Lab execution
        code = goal
        state["tool_calls"] += 1
        al._admin_pre_mutate(cfg, workspace, "run_python", (code or "")[:120])
        result = TOOLS["run_python"]["fn"](code=code, cwd=workspace)
        al._register_exact_tool_call(state, "run_python", decision)
        rs.log_execution("run_python", {"cwd": workspace})
        _res = al._maybe_validate_tool_output("run_python", result)
        _res, _, _ = _deterministic_verify_retry(
            "run_python", state, cfg, workspace, _res,
            lambda: TOOLS["run_python"]["fn"](code=code, cwd=workspace),
            {"cwd": workspace},
        )
        state["steps"].append({"action": "run_python", "result": _res})
        state["last_tool_used"] = "run_python"
        al._run_verification_after_tool(state, "run_python", _res if isinstance(_res, dict) else result, workspace)
        al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
        return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

    # Non-lab: approval check
    if not ctx.allow_run or not rs.is_tool_allowed("run_python"):
        approval_id = al._write_pending("run_python", {"code": goal, "cwd": workspace})
        state["steps"].append({
            "action": "run_python",
            "result": {"ok": False, "reason": "approval_required",
                       "approval_id": approval_id, "message": f"Run: layla approve {approval_id}"},
        })
        state["status"] = "finished"
        return DispatchResult(handled=True, flow="break", goal=goal)

    code = goal
    state["tool_calls"] += 1
    al._admin_pre_mutate(cfg, workspace, "run_python", (code or "")[:120])
    result = TOOLS["run_python"]["fn"](code=code, cwd=workspace)
    al._register_exact_tool_call(state, "run_python", decision)
    rs.log_execution("run_python", {"cwd": workspace})
    _res = al._maybe_validate_tool_output("run_python", result)
    _res, _, _ = _deterministic_verify_retry(
        "run_python", state, cfg, workspace, _res,
        lambda: TOOLS["run_python"]["fn"](code=code, cwd=workspace),
        {"cwd": workspace},
    )
    state["steps"].append({"action": "run_python", "result": _res})
    state["last_tool_used"] = "run_python"
    al._run_verification_after_tool(state, "run_python", _res if isinstance(_res, dict) else result, workspace)
    al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


# ===================================================================
# APPLY PATCH
# ===================================================================

def _handle_apply_patch(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    from services.outcome_writer import _extract_patch_text
    state, cfg, workspace, decision = ctx.state, ctx.cfg, ctx.workspace, ctx.decision

    if state.get("research_lab_root"):
        return _lab_blocked("apply_patch", state)

    path = al._extract_path(goal)
    patch_body = _extract_patch_text(goal)

    if path:
        probe = al._maybe_preprobe_file(state, path)
        if not al._apply_probe_guidance(state, "apply_patch", path, probe):
            return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

    try:
        max_patch_lines = int(cfg.get("max_patch_lines", 0) or 0)
    except (TypeError, ValueError):
        max_patch_lines = 0
    if max_patch_lines and patch_body and patch_body.count("\n") > max_patch_lines:
        state["tool_calls"] += 1
        state["steps"].append({
            "action": "apply_patch",
            "result": {"ok": False, "error": "diff_too_large",
                       "lines": patch_body.count("\n"), "max": max_patch_lines},
        })
        return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

    if not ctx.allow_write or (not rs.is_tool_allowed("apply_patch") and not al._has_any_grant("apply_patch", {"path": path or ""})):
        return _approval_break("apply_patch", {"original_path": path or "", "patch_text": patch_body}, ctx)

    if not path:
        state["status"] = "parse_failed"
        return DispatchResult(handled=True, flow="break", goal=goal)

    state["tool_calls"] += 1
    al._admin_pre_mutate(cfg, workspace, "apply_patch", path)
    result = TOOLS["apply_patch"]["fn"](original_path=path, patch_text=patch_body)
    al._register_exact_tool_call(state, "apply_patch", decision)
    rs.log_execution("apply_patch", {"path": path})
    _res = al._maybe_validate_tool_output("apply_patch", result)
    _res, _, _ = _deterministic_verify_retry(
        "apply_patch", state, cfg, workspace, _res,
        lambda: TOOLS["apply_patch"]["fn"](original_path=path, patch_text=patch_body),
        {"path": path},
    )
    state["steps"].append({"action": "apply_patch", "result": _res})
    state["last_tool_used"] = "apply_patch"
    al._run_verification_after_tool(state, "apply_patch", _res if isinstance(_res, dict) else result, workspace)
    al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
    al._run_git_auto_commit("apply_patch", result, path, workspace)
    new_goal = _rebuild_goal(state)
    if ctx.reasoning_mode != "none":
        hint = al._run_auto_lint_test_fix(state, "apply_patch", result, path, workspace)
        if hint:
            new_goal += "\n\n" + hint
    return DispatchResult(handled=True, flow="continue", goal=new_goal)


# ===================================================================
# REPLACE IN FILE
# ===================================================================

def _handle_replace_in_file(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, cfg, workspace, decision = ctx.state, ctx.cfg, ctx.workspace, ctx.decision

    if state.get("research_lab_root"):
        state["tool_calls"] += 1
        state["steps"].append({
            "action": "replace_in_file",
            "result": {"ok": False, "reason": "not_allowed_in_research"},
        })
        return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

    args = (decision.get("args") or {}) if decision else {}
    path = str(args.get("path") or "").strip()
    old_text = str(args.get("old_text") or "")
    new_text = str(args.get("new_text") if args.get("new_text") is not None else "")
    try:
        rcount = int(args.get("count") or 1)
    except (TypeError, ValueError):
        rcount = 1

    if not path or not old_text:
        state["tool_calls"] += 1
        state["steps"].append({
            "action": "replace_in_file",
            "result": {"ok": False, "error": "replace_in_file requires path and old_text in args"},
        })
        return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

    if path:
        probe = al._maybe_preprobe_file(state, path)
        if not al._apply_probe_guidance(state, "replace_in_file", path, probe):
            return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))

    if not ctx.allow_write or (
        not rs.is_tool_allowed("replace_in_file")
        and not al._has_any_grant("replace_in_file", {"path": path})
    ):
        return _approval_break("replace_in_file", {"path": path, "old_text": old_text, "new_text": new_text, "count": rcount}, ctx)

    state["tool_calls"] += 1
    al._admin_pre_mutate(cfg, workspace, "replace_in_file", path)
    result = TOOLS["replace_in_file"]["fn"](path=path, old_text=old_text, new_text=new_text, count=rcount)
    al._register_exact_tool_call(state, "replace_in_file", decision)
    rs.log_execution("replace_in_file", {"path": path})
    _res = al._maybe_validate_tool_output("replace_in_file", result)
    _res, _, _ = _deterministic_verify_retry(
        "replace_in_file", state, cfg, workspace, _res,
        lambda: TOOLS["replace_in_file"]["fn"](path=path, old_text=old_text, new_text=new_text, count=rcount),
        {"path": path},
    )
    state["steps"].append({"action": "replace_in_file", "result": _res})
    state["last_tool_used"] = "replace_in_file"
    al._run_verification_after_tool(state, "replace_in_file", _res if isinstance(_res, dict) else result, workspace)
    al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
    al._run_git_auto_commit("replace_in_file", result, result.get("path") or path, workspace)
    new_goal = _rebuild_goal(state)
    if ctx.reasoning_mode != "none":
        hint = al._run_auto_lint_test_fix(state, "replace_in_file", result, result.get("path") or path, workspace)
        if hint:
            new_goal += "\n\n" + hint
    return DispatchResult(handled=True, flow="continue", goal=new_goal)


# ===================================================================
# FETCH URL
# ===================================================================

def _handle_fetch_url(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, _, TOOLS = _imports()

    words = goal.split()
    url = next((w for w in words if w.startswith("http")), "")
    if not url:
        ctx.state["status"] = "parse_failed"
        return DispatchResult(handled=True, flow="break", goal=goal)

    return _base_tool_handler(
        ctx, "fetch_url", TOOLS["fetch_url"]["fn"],
        args={"url": url},
        log_args={"url": url},
        verify=False,
    )


# ===================================================================
# SHELL
# ===================================================================

def _handle_shell(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, cfg, workspace, decision = ctx.state, ctx.cfg, ctx.workspace, ctx.decision

    if state.get("research_lab_root"):
        return _lab_blocked("shell", state)

    argv = al._extract_shell_argv(goal)
    if not argv:
        state["status"] = "parse_failed"
        return DispatchResult(handled=True, flow="break", goal=goal)

    if not ctx.allow_run:
        approval_id = al._write_pending("shell", {"argv": argv, "cwd": workspace})
        state["steps"].append({
            "action": "shell",
            "result": {"ok": False, "reason": "approval_required",
                       "approval_id": approval_id, "message": f"Run: layla approve {approval_id}"},
        })
        state["status"] = "finished"
        return DispatchResult(handled=True, flow="break", goal=goal)

    from layla.tools.registry import shell_command_is_safe_whitelisted, shell_command_line
    _cmd_line = shell_command_line(argv)
    _grant_ok = al._has_any_grant("shell", {"command": _cmd_line})
    _need_shell_approval = rs.is_tool_allowed("shell")
    if _need_shell_approval and not shell_command_is_safe_whitelisted(argv) and not _grant_ok:
        approval_id = al._write_pending("shell", {"argv": argv, "cwd": workspace})
        state["steps"].append({
            "action": "shell",
            "result": {"ok": False, "reason": "approval_required",
                       "approval_id": approval_id, "message": f"Run: layla approve {approval_id}"},
        })
        state["status"] = "finished"
        return DispatchResult(handled=True, flow="break", goal=goal)

    state["tool_calls"] += 1
    al._admin_pre_mutate(cfg, workspace, "shell", _cmd_line[:160])
    result = TOOLS["shell"]["fn"](argv=argv, cwd=workspace)
    al._register_exact_tool_call(state, "shell", decision)
    rs.log_execution("shell", {"argv": argv, "cwd": workspace})
    _res = al._maybe_validate_tool_output("shell", result)
    _res, _, _ = _deterministic_verify_retry(
        "shell", state, cfg, workspace, _res,
        lambda: TOOLS["shell"]["fn"](argv=argv, cwd=workspace),
        {"argv": argv, "cwd": workspace},
    )
    state["steps"].append({"action": "shell", "result": _res})
    state["last_tool_used"] = "shell"
    al._run_verification_after_tool(state, "shell", _res if isinstance(_res, dict) else result, workspace)
    al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


# ===================================================================
# MCP TOOLS CALL
# ===================================================================

def _handle_mcp_tools_call(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, _, _, decision = ctx.state, ctx.cfg, ctx.workspace, ctx.decision

    args = al._normalize_mcp_tool_args((decision.get("args") or {}) if decision else {})

    if state.get("research_lab_root"):
        return _lab_blocked("mcp_tools_call", state)

    if not ctx.allow_run:
        approval_id = al._write_pending("mcp_tools_call", args)
        state["steps"].append({
            "action": "mcp_tools_call",
            "result": {"ok": False, "reason": "approval_required",
                       "approval_id": approval_id, "message": f"Run: layla approve {approval_id}"},
        })
        state["status"] = "finished"
        return DispatchResult(handled=True, flow="break", goal=goal)

    _need_mcp_approval = rs.is_tool_allowed("mcp_tools_call")
    _mcp_grant_ok = al._has_any_grant("mcp_tools_call", args)
    if _need_mcp_approval and not _mcp_grant_ok:
        approval_id = al._write_pending("mcp_tools_call", args)
        state["steps"].append({
            "action": "mcp_tools_call",
            "result": {"ok": False, "reason": "approval_required",
                       "approval_id": approval_id, "message": f"Run: layla approve {approval_id}"},
        })
        state["status"] = "finished"
        return DispatchResult(handled=True, flow="break", goal=goal)

    state["tool_calls"] += 1
    result = TOOLS["mcp_tools_call"]["fn"](
        mcp_server=str(args.get("mcp_server") or ""),
        tool_name=str(args.get("tool_name") or ""),
        arguments=args.get("arguments") if isinstance(args.get("arguments"), dict) else None,
    )
    al._register_exact_tool_call(state, "mcp_tools_call", decision)
    rs.log_execution("mcp_tools_call", args)
    _val = al._maybe_validate_tool_output("mcp_tools_call", result)
    state["steps"].append({"action": "mcp_tools_call", "result": _val})
    if ctx.show_thinking:
        al._emit_tool_step(ctx.ux_state_queue, "mcp_tools_call", _val)
    state["last_tool_used"] = "mcp_tools_call"
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


# ===================================================================
# EXTENDED TOOLS (no approval: json_query, diff_files, etc.)
# ===================================================================

_EXTENDED_TOOLS = frozenset({
    "json_query", "diff_files", "env_info", "regex_test",
    "save_note", "search_memories", "git_add",
})


def _handle_extended_tools(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, decision = ctx.state, ctx.decision

    args = (decision.get("args") or {}) if decision else {}
    state["tool_calls"] += 1
    result = TOOLS[intent]["fn"](**args) if args else TOOLS[intent]["fn"]()
    al._register_exact_tool_call(state, intent, decision)
    rs.log_execution(intent, args)
    _val = al._maybe_validate_tool_output(intent, result)
    state["steps"].append({"action": intent, "result": _val})
    if ctx.show_thinking:
        al._emit_tool_step(ctx.ux_state_queue, intent, _val)
    state["last_tool_used"] = intent
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


# ===================================================================
# GIT COMMIT (approval-gated)
# ===================================================================

def _handle_git_commit(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, workspace, decision = ctx.state, ctx.workspace, ctx.decision

    args = (decision.get("args") or {}) if decision else {}
    if not ctx.allow_write or (not rs.is_tool_allowed("git_commit") and not al._has_any_grant("git_commit", args)):
        return _approval_break("git_commit", args, ctx)

    state["tool_calls"] += 1
    result = TOOLS["git_commit"]["fn"](**args)
    al._register_exact_tool_call(state, "git_commit", decision)
    rs.log_execution("git_commit", args)
    _val = al._maybe_validate_tool_output("git_commit", result)
    state["steps"].append({"action": "git_commit", "result": _val})
    if ctx.show_thinking:
        al._emit_tool_step(ctx.ux_state_queue, "git_commit", _val)
    state["last_tool_used"] = "git_commit"
    al._run_verification_after_tool(state, "git_commit", result, workspace)
    al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


# ===================================================================
# PROJECT CONTEXT
# ===================================================================

def _handle_get_project_context(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, _, TOOLS = _imports()
    state, decision = ctx.state, ctx.decision

    state["tool_calls"] += 1
    result = TOOLS["get_project_context"]["fn"]()
    al._register_exact_tool_call(state, "get_project_context", decision)
    _val = al._maybe_validate_tool_output("get_project_context", result)
    state["steps"].append({"action": "get_project_context", "result": _val})
    if ctx.show_thinking:
        al._emit_tool_step(ctx.ux_state_queue, "get_project_context", _val)
    state["last_tool_used"] = "get_project_context"
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


def _handle_update_project_context(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, _, TOOLS = _imports()
    state, decision = ctx.state, ctx.decision

    args = (decision.get("args") or {}) if decision else {}
    state["tool_calls"] += 1
    result = TOOLS["update_project_context"]["fn"](
        project_name=args.get("project_name", ""),
        domains=args.get("domains"),
        key_files=args.get("key_files"),
        goals=args.get("goals", ""),
        lifecycle_stage=args.get("lifecycle_stage", ""),
    )
    al._register_exact_tool_call(state, "update_project_context", decision)
    _val = al._maybe_validate_tool_output("update_project_context", result)
    state["steps"].append({"action": "update_project_context", "result": _val})
    if ctx.show_thinking:
        al._emit_tool_step(ctx.ux_state_queue, "update_project_context", _val)
    state["last_tool_used"] = "update_project_context"
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


# ===================================================================
# UNDERSTAND FILE (read-only)
# ===================================================================

def _handle_understand_file(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, _, TOOLS = _imports()
    state, decision = ctx.state, ctx.decision

    path = (decision.get("args") or {}).get("path") if decision else None
    if not path:
        path = al._extract_path(goal)
    if not path:
        state["status"] = "parse_failed"
        return DispatchResult(handled=True, flow="break", goal=goal)

    state["tool_calls"] += 1
    result = TOOLS["understand_file"]["fn"](path=path)
    al._register_exact_tool_call(state, "understand_file", decision)
    state["steps"].append({"action": "understand_file", "result": al._maybe_validate_tool_output("understand_file", result)})
    state["last_tool_used"] = "understand_file"
    return DispatchResult(handled=True, flow="continue", goal=_rebuild_goal(state))


# ===================================================================
# GENERIC TOOL DISPATCH (tools not hardcoded above)
# ===================================================================

def _handle_generic(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    al, rs, TOOLS = _imports()
    state, cfg, workspace, decision = ctx.state, ctx.cfg, ctx.workspace, ctx.decision

    args = (decision.get("args") or {}) if decision else {}

    # fabrication_assist_run: pin runner selection
    if intent == "fabrication_assist_run":
        pinned = (state.get("fabrication_assist_runner_request") or "").strip().lower()
        if not isinstance(args, dict):
            args = {}
        else:
            args = dict(args)
        args["runner_request"] = pinned if pinned in ("stub", "subprocess") else "stub"

    # Intent routing hints
    if intent in ("restore_file_checkpoint", "ingest_chat_export_to_knowledge",
                  "memory_elasticsearch_search", "list_file_checkpoints"):
        try:
            from services.intent_routing_hints import fill_tool_args_from_goal
            _og = (state.get("original_goal") or goal or "").strip()
            args = fill_tool_args_from_goal(intent, _og, workspace, args)
        except Exception as _exc:
            logger.debug("tool_dispatch:fill_tool_args: %s", _exc, exc_info=False)

    meta = TOOLS.get(intent, {})
    needs_approval = meta.get("require_approval", False)
    allow = ctx.allow_run if intent == "fabrication_assist_run" else (ctx.allow_write or ctx.allow_run)
    _session_grant_ok = al._has_any_grant(intent, args)

    if needs_approval and (not allow or not rs.is_tool_allowed(intent)) and not _session_grant_ok:
        return _approval_break(intent, dict(args), ctx)

    # Inject workspace/cwd for tools that expect it
    if "cwd" not in args and intent in ("run_tests", "pip_install", "pip_list", "shell_session_start", "shell_session_manage"):
        args["cwd"] = workspace
    if "repo" not in args and intent.startswith("git_"):
        args["repo"] = workspace
    if ("path" not in args or not args.get("path")) and intent in ("parse_gcode", "stl_mesh_info", "tail_file"):
        path = al._extract_path(goal)
        if path:
            args["path"] = path
    if "root" not in args and intent in ("search_replace", "rename_symbol", "search_codebase"):
        args["root"] = workspace

    _tool_timeout = cfg.get("tool_call_timeout_seconds", 60)
    from core.executor import run_tool as _run_tool_fn
    _tool_t0 = time.perf_counter()
    result = _run_tool_fn(
        intent, args,
        timeout_s=float(_tool_timeout),
        sandbox_root=workspace,
        allow_run=ctx.allow_run,
        conversation_id=str(state.get("conversation_id") or ""),
    )

    try:
        from services.rl_feedback import record_outcome_feedback as _rl_record
        _ms = (time.perf_counter() - _tool_t0) * 1000.0
        _ok = isinstance(result, dict) and result.get("ok", True) is not False
        _rl_record(intent, success=_ok, latency_ms=_ms)
    except Exception:
        pass

    rs.log_execution(intent, args)
    state["tool_calls"] += 1
    al._register_exact_tool_call(state, intent, decision)
    _res = al._maybe_validate_tool_output(intent, result)
    _res, _, _ = _deterministic_verify_retry(
        intent, state, cfg, workspace, _res,
        lambda: _run_tool_fn(
            intent, args,
            timeout_s=float(_tool_timeout),
            sandbox_root=workspace,
            allow_run=ctx.allow_run,
            conversation_id=str(state.get("conversation_id") or ""),
        ),
        args,
    )
    state["steps"].append({"action": intent, "result": _res})
    state["last_tool_used"] = intent
    al._run_verification_after_tool(state, intent, _res if isinstance(_res, dict) else result, workspace)
    al._emit_ux(state, ctx.ux_state_queue, al.UX_STATE_VERIFYING)

    new_goal = _rebuild_goal(state)
    if ctx.reasoning_mode != "none":
        lp = al._edit_tool_lint_path(intent, args, workspace)
        if lp and isinstance(_res, dict) and _res.get("ok"):
            lh = al._run_auto_lint_test_fix(state, intent, _res, lp, workspace)
            if lh:
                new_goal += "\n\n" + lh
    return DispatchResult(handled=True, flow="continue", goal=new_goal)


# ===================================================================
# MAIN DISPATCH ENTRY POINT
# ===================================================================

# Map of intent → handler for intents with dedicated handlers
_HANDLER_MAP: dict[str, Any] = {
    "write_file": _handle_write_file,
    "write_files_batch": _handle_write_files_batch,
    "read_file": _handle_read_file,
    "list_dir": _handle_list_dir,
    "git_status": _handle_simple_git,
    "git_diff": _handle_simple_git,
    "git_log": _handle_simple_git,
    "git_branch": _handle_simple_git,
    "grep_code": _handle_grep_code,
    "glob_files": _handle_glob_files,
    "run_python": _handle_run_python,
    "apply_patch": _handle_apply_patch,
    "replace_in_file": _handle_replace_in_file,
    "fetch_url": _handle_fetch_url,
    "shell": _handle_shell,
    "mcp_tools_call": _handle_mcp_tools_call,
    "git_commit": _handle_git_commit,
    "get_project_context": _handle_get_project_context,
    "update_project_context": _handle_update_project_context,
    "understand_file": _handle_understand_file,
}


def dispatch_tool_intent(intent: str, goal: str, ctx: DispatchContext) -> DispatchResult:
    """Route a tool *intent* to its handler and return the outcome.

    Returns ``DispatchResult(handled=False)`` if the intent is not a tool
    (e.g. ``"reason"``, ``"finish"``).
    """
    handler = _HANDLER_MAP.get(intent)
    if handler is not None:
        return handler(intent, goal, ctx)

    # Extended tools group (no approval needed)
    if intent in _EXTENDED_TOOLS:
        return _handle_extended_tools(intent, goal, ctx)

    # Generic dispatch for any tool in TOOLS not handled above
    _, _, TOOLS = _imports()
    if intent in TOOLS and intent not in _HARDCODED_INTENTS:
        return _handle_generic(intent, goal, ctx)

    return DispatchResult(handled=False)
