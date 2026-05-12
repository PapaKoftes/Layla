import json
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# Goal preservation: the prompt optimizer (in `autonomous_run`) may rewrite the
# user's goal before downstream processing. We must keep the canonical original
# text available so memory writes, reflection, and trace endpoints can refer to
# what the user actually said. These contextvars are set in `autonomous_run`
# right after capturing/optimizing the goal and read by `_autonomous_run_impl_core`.
_goal_original_var: ContextVar[str] = ContextVar("layla_goal_original", default="")
_goal_optimized_var: ContextVar[str] = ContextVar("layla_goal_optimized", default="")


def get_last_goal_original() -> str:
    """Public accessor for the most recent user-authored goal (pre-optimizer)."""
    return _goal_original_var.get()


def get_last_goal_optimized() -> str:
    """Public accessor for the optimizer's rewrite of the most recent goal."""
    return _goal_optimized_var.get()

import psutil

logger = logging.getLogger("layla")

import orchestrator  # noqa: E402
import runtime_safety  # noqa: E402
from core.executor import run_tool as _run_tool  # noqa: E402
from decision_schema import parse_decision as _parse_decision  # noqa: E402
from layla.memory.db import get_aspect_memories as _db_get_aspect_memories  # noqa: E402
from layla.memory.db import get_recent_learnings as _db_get_learnings  # noqa: E402
from layla.memory.db import migrate as _db_migrate  # noqa: E402
from layla.tools.registry import TOOLS, set_effective_sandbox  # noqa: E402
from services.agent_loop_formatting import format_tool_steps_for_prompt as _format_steps_impl
from services.agent_safety import (  # noqa: E402
    maybe_planning_strict_refusal as _maybe_planning_strict_refusal,
)
from services.agent_safety import (
    maybe_step_tool_allowlist_refusal as _maybe_step_tool_allowlist_refusal,
)
from services.context_manager import DEFAULT_BUDGETS, build_system_prompt  # noqa: E402
from services.context_window_ux import emit_context_window_ux
from services.llm_gateway import get_stop_sequences, llm_serialize_lock, run_completion  # noqa: E402
from services.outcome_writer import (  # noqa: E402
    _auto_extract_learnings,
    _extract_patch_text,
    _maybe_save_echo_memory,
    _save_outcome_memory,
)
from services.output_polish import polish_output as _polish_output  # noqa: E402
from services.resource_manager import (  # noqa: E402
    PRIORITY_AGENT,
    PRIORITY_CHAT,
    classify_load,
    schedule_slot,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = Path(__file__).resolve().parent
RESEARCH_LAB_ROOT = AGENT_DIR / ".research_lab"

_SKIP_TOOL_OUTPUT_VALIDATION = frozenset({
    "approval_required", "tool_policy_denied", "tool_loop_detected",
})

# Whole-message phatic turns ÃÃÃ¶ router + autonomous_run quick path (no LLM).
_PHATIC_QUICK_PATTERNS = (
    r"^(how are you|how are you doing)\??$",
    r"^(what'?s up|wassup)\??$",
    r"^(how'?s it going)\??$",
    r"^(you good)\??$",
)


def _log_tool_outcome(intent: str, result: object) -> None:
    """Structured INFO log for observability (tool name, ok, reason)."""
    if not isinstance(result, dict):
        logger.info("tool=%s ok=unknown outcome=non_dict", intent)
        return
    ok = result.get("ok")
    reason = result.get("reason") or result.get("error") or ""
    logger.info("tool=%s ok=%s reason=%s", intent, ok, reason or "-")


class _BackgroundProgressSteps(list):
    """Notify background_progress_callback on append (throttled) for task observability."""

    __slots__ = ("_cb", "_interval", "_last_emit", "_seq")

    def __init__(self, cb: Callable[[dict], None], interval: float = 0.35) -> None:
        super().__init__()
        self._cb = cb
        self._interval = max(0.05, float(interval))
        self._last_emit = 0.0
        self._seq = 0

    def append(self, item: object) -> None:
        super().append(item)
        try:
            now = time.monotonic()
            force = False
            if isinstance(item, dict):
                act = item.get("action")
                if act in ("client_abort", "reason", "none", "think"):
                    force = True
            if not force and now - self._last_emit < self._interval:
                return
            self._last_emit = now
            self._seq += 1
            preview = ""
            if isinstance(item, dict):
                try:
                    preview = json.dumps(item.get("result"), default=str)[:400]
                except Exception:
                    preview = str(item.get("result"))[:400]
            self._cb(
                {
                    "seq": self._seq,
                    "t": time.time(),
                    "action": item.get("action") if isinstance(item, dict) else None,
                    "preview": preview,
                    "step_index": len(self) - 1,
                }
            )
        except Exception as _exc:
            logger.debug("agent_loop:L122: %s", _exc, exc_info=False)


def _maybe_validate_tool_output(intent: str, result: object) -> object:
    if not isinstance(result, dict):
        from services.tool_output_validator import validate_tool_output

        out = validate_tool_output(intent, result)
        _log_tool_outcome(intent, out if isinstance(out, dict) else {"ok": True})
        return out
    if result.get("reason") in _SKIP_TOOL_OUTPUT_VALIDATION:
        _log_tool_outcome(intent, result)
        return result
    from services.tool_output_validator import validate_tool_output

    out = validate_tool_output(intent, result)

    # Phase 5 ÃÃÃ¶ structured validation: injection scan, size check, schema check (core/validator.py)
    try:
        from core.validator import validate as _core_validate
        vr = _core_validate(intent, out)
        if vr.get("flagged_injection"):
            # Propagate the injection flag so the planner can see it
            if isinstance(out, dict):
                out = dict(out)
                out["_injection_flagged"] = True
                out["_injection_warning"] = "Possible prompt injection in tool output"
        if vr.get("warnings"):
            logger.debug("validator: tool=%s warnings=%s", intent, vr["warnings"])
    except Exception as _ve:
        logger.debug("core.validator skipped: %s", _ve)

    _log_tool_outcome(intent, out if isinstance(out, dict) else result)
    return out


def _apply_deterministic_tool_verification(
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
    except Exception:
        return result, True, "disabled"
    try:
        from services.tool_output_validator import deterministic_verify_tool_result

        vr = deterministic_verify_tool_result(intent, result, workspace_root=workspace or "")
        ok = bool(vr.get("ok"))
        reason = str(vr.get("reason") or ("ok" if ok else "failed"))
        out = dict(result)
        out["_deterministic_verify"] = vr
        out["_deterministic_verified"] = True
        if not ok:
            # Treat as failure: prevents cascade based on a false-positive ok.
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
        except Exception:
            return result, True, "verifier_unavailable"


def _normalize_mcp_tool_args(args: dict) -> dict:
    """Map common model arg aliases onto mcp_tools_call parameters."""
    a = dict(args)
    if not (a.get("mcp_server") or "").strip() and (a.get("server") or "").strip():
        a["mcp_server"] = str(a.get("server") or "").strip()
    if not (a.get("tool_name") or "").strip() and (a.get("tool") or "").strip():
        a["tool_name"] = str(a.get("tool") or "").strip()
    return a


def _inject_workspace_args(tool_name: str, args: dict, workspace: str) -> dict:
    """Add workspace/cwd/repo to args for tools that expect them (used by batch runner)."""
    args = dict(args)
    if "cwd" not in args and tool_name in ("run_tests", "pip_install", "pip_list", "shell_session_start", "shell_session_manage"):
        args["cwd"] = workspace
    if "repo" not in args and tool_name.startswith("git_"):
        args["repo"] = workspace
    if "root" not in args and tool_name in ("search_replace", "rename_symbol", "search_codebase"):
        args["root"] = workspace
    return args


def _inject_cancel_message(conversation_history: list, tool_name: str, reason: str = "cancelled") -> None:
    """Inject a synthetic user message when a tool is cancelled/timed-out.
    Prevents the model from hallucinating tool results on the next turn (D5 pattern)."""
    try:
        msg = (
            f"[Tool execution cancelled: {tool_name} was {reason} by operator. "
            "Please continue your reasoning without that result. "
            "Do not assume the tool succeeded or guess its output.]"
        )
        conversation_history.append({"role": "user", "content": msg})
        try:
            from layla.memory.db import log_audit
            log_audit(tool_name, f"cancel:{reason}", "agent_loop", False)
        except Exception as _exc:
            logger.debug("agent_loop:L194: %s", _exc, exc_info=False)
        logger.info("cancel synthetic message injected for tool=%s reason=%s", tool_name, reason)
    except Exception as e:
        logger.debug("_inject_cancel_message failed: %s", e)


def _register_exact_tool_call(state: dict, intent: str, decision: dict | None) -> None:
    if intent in ("reason", "finish", "wakeup", "none"):
        return
    state["tool_attempted_this_turn"] = True
    try:
        tu = state.setdefault("tools_used", [])
        if intent and intent not in tu:
            tu.append(intent)
    except Exception:
        pass
    try:
        from services.tool_loop_detection import exact_call_key

        state.setdefault("_recent_exact_calls", set()).add(exact_call_key(intent, decision))
    except Exception as _exc:
        logger.debug("agent_loop:L208: %s", _exc, exc_info=False)


def _apply_lite_mode_overrides(cfg: dict) -> dict:
    """
    Apply performance_mode-based lite overrides (PR #1).
    Does NOT mutate the input dict; returns a shallow copy with adjusted keys.
    """
    import copy as _copy

    cfg = _copy.copy(cfg)
    pm = (cfg.get("performance_mode") or "auto").strip().lower()
    if pm == "low":
        cfg["max_tool_calls"] = min(int(cfg.get("max_tool_calls") or 5), 2)
        cfg["enable_cognitive_workspace"] = False
        cfg["planning_enabled"] = False
        cfg["retrieval_k"] = 3
        cfg["skip_deliberation"] = True
        cfg["skip_self_reflection"] = True
    elif pm == "mid":
        cfg["max_tool_calls"] = min(int(cfg.get("max_tool_calls") or 5), 4)
        cfg["enable_cognitive_workspace"] = False
        cfg["planning_enabled"] = cfg.get("planning_enabled", True)
    return cfg


def _get_effective_config(base_cfg: dict) -> dict:
    """Apply system_optimizer runtime overrides. Never persists to disk."""
    try:
        from services.system_optimizer import get_effective_config

        return _apply_lite_mode_overrides(get_effective_config(base_cfg))
    except Exception as e:
        logger.debug("get_effective_config failed: %s", e)
        return _apply_lite_mode_overrides(base_cfg)


def _path_under_lab(path: str | Path, lab_root: str) -> bool:
    """True if path resolves under lab_root (for research_mode write/run gating)."""
    if not lab_root or not path:
        return False
    try:
        p = Path(path).resolve()
        lab = Path(lab_root).resolve()
        p.relative_to(lab)
        return True
    except ValueError:
        return False
    except Exception:
        return False


def _research_response_asks_user(text: str) -> bool:
    """True if response looks like asking the user a question (research_mode: treat as incomplete)."""
    if not text or len(text.strip()) < 20:
        return False
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    phrases = (
        "what would you like",
        "what's the first thing",
        "would you like me to",
        "would you like to",
        "shall i ",
        "do you want me to",
        "do you want to",
        "should i ",
        "what do you want",
        "how would you like",
        "which would you",
        "let me know what",
        "tell me what",
        "ask you",
        "your preference",
    )
    return any(p in t for p in phrases)


# Placeholder for sanitized assistant turns in convo_block (never use "I replied." ÃÃÃ¶ model repeats it)
_SANITIZED_PLACEHOLDER = "[...]"

# UX interaction states (UI layer only; no change to decision logic)
UX_STATE_THINKING = "thinking"
UX_STATE_VERIFYING = "verifying"
UX_STATE_CHANGING_APPROACH = "changing_approach"
UX_STATE_REFRAMING_OBJECTIVE = "reframing_objective"


def _emit_ux(state: dict, ux_state_queue: queue.Queue | None, label: str) -> None:
    """Append UX state for this turn and optionally push to queue for live SSE."""
    state.setdefault("ux_states", []).append(label)
    if ux_state_queue is not None:
        try:
            ux_state_queue.put(label, block=False)
        except Exception as e:
            logger.debug("emit_ux put failed: %s", e)


def _emit_tool_start(ux_state_queue: queue.Queue | None, tool_name: str) -> None:
    """Emit a tool_start event so the UI can show 'Running tool_name...' during streaming."""
    logger.info("tool start: %s", tool_name)
    if ux_state_queue is not None:
        try:
            ux_state_queue.put({"_type": "tool_start", "tool": tool_name}, block=False)
        except Exception as e:
            logger.debug("emit_tool_start put failed: %s", e)


def _summarize_tool_result(result: object, max_len: int = 220) -> tuple[bool | None, str]:
    """Small, UI-safe summary for streaming tool trace."""
    ok: bool | None = None
    try:
        if isinstance(result, dict):
            if "ok" in result:
                ok = bool(result.get("ok"))
            msg = (
                result.get("message")
                or result.get("error")
                or result.get("reason")
                or result.get("status")
                or ""
            )
            s = msg if isinstance(msg, str) else str(msg)
        elif isinstance(result, str):
            s = result
        else:
            s = str(result)
    except Exception:
        s = ""
    s = (s or "").strip().replace("\n", " ")
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return ok, s


def _emit_tool_step(ux_state_queue: queue.Queue | None, tool_name: str, result: object) -> None:
    """Emit a tool_step event so the UI can show step-by-step progress during streaming."""
    if ux_state_queue is None:
        return
    ok, summary = _summarize_tool_result(result)
    try:
        ux_state_queue.put(
            {"_type": "tool_step", "phase": "end", "tool": tool_name, "ok": ok, "summary": summary},
            block=False,
        )
    except Exception as e:
        logger.debug("emit_tool_step put failed: %s", e)


def _emit_context_window_ux(
    ux_state_queue: queue.Queue | None,
    conversation_history: list | None,
    cfg: dict,
    state: dict,
) -> None:
    """Delegate to services.context_window_ux (keeps call sites stable)."""
    emit_context_window_ux(
        ux_state_queue,
        conversation_history,
        cfg,
        state,
        format_steps=_format_steps,
    )


def _approval_preview_diff(tool: str, args: dict, workspace: str) -> None:
    """Add unified diff (or patch preview) to approval args for the Web UI."""
    import difflib

    try:
        max_lines = 200
        ws = Path((workspace or "").strip()).expanduser().resolve() if (workspace or "").strip() else None
        if tool == "write_file" and args.get("path") is not None and "content" in args:
            path = Path(str(args["path"]))
            if not path.is_absolute() and ws and ws.exists():
                path = (ws / path).resolve()
            else:
                path = path.expanduser().resolve()
            if not path.exists():
                args["diff"] = "(new file)"
                return
            try:
                cur = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                cur = ""
            newc = str(args.get("content") or "")
            diff = list(
                difflib.unified_diff(
                    cur.splitlines(True),
                    newc.splitlines(True),
                    fromfile=f"a/{path.name}",
                    tofile=f"b/{path.name}",
                    lineterm="",
                )
            )
            if len(diff) > max_lines:
                diff = diff[:max_lines] + [f"\n... ({len(diff) - max_lines} more lines omitted)\n"]
            args["diff"] = "".join(diff) if diff else "(no textual change)"
        elif tool == "apply_patch":
            pt = str(args.get("patch_text") or "")
            lines = pt.splitlines()
            if len(lines) > max_lines:
                lines = lines[:max_lines] + [f"... ({len(lines)} lines truncated)"]
            args["diff"] = "\n".join(lines) if lines else "(empty patch)"
        elif tool == "write_files_batch" and isinstance(args.get("files"), list) and args["files"]:
            first = args["files"][0]
            if isinstance(first, dict) and "path" in first and "content" in first:
                sub = {"path": first["path"], "content": first["content"]}
                _approval_preview_diff("write_file", sub, workspace)
                args["diff"] = "[batch: first file]\n" + str(sub.get("diff", ""))
            else:
                args["diff"] = "(write_files_batch: no preview)"
        elif tool == "replace_in_file" and args.get("path") and "old_text" in args and "new_text" in args:
            path = Path(str(args["path"]))
            if not path.is_absolute() and ws and ws.exists():
                path = (ws / path).resolve()
            else:
                path = path.expanduser().resolve()
            if not path.exists():
                args["diff"] = "(file missing)"
                return
            try:
                cur = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                cur = ""
            ot = str(args.get("old_text") or "")
            nt = str(args.get("new_text") or "")
            if ot not in cur:
                args["diff"] = "(old_text not in file)"
                return
            try:
                cnt = int(args.get("count") or 1)
            except (TypeError, ValueError):
                cnt = 1
            newc = cur
            replaced = 0
            idx = 0
            while replaced < cnt:
                pos = newc.find(ot, idx)
                if pos < 0:
                    break
                newc = newc[:pos] + nt + newc[pos + len(ot) :]
                replaced += 1
                idx = pos + len(nt)
            diff = list(
                difflib.unified_diff(
                    cur.splitlines(True),
                    newc.splitlines(True),
                    fromfile=f"a/{path.name}",
                    tofile=f"b/{path.name}",
                    lineterm="",
                )
            )
            if len(diff) > max_lines:
                diff = diff[:max_lines] + [f"\n... ({len(diff) - max_lines} more lines omitted)\n"]
            args["diff"] = "".join(diff) if diff else "(no textual change)"
        elif tool == "search_replace":
            root = Path(str(args.get("root") or workspace or "")).expanduser().resolve()
            fg = str(args.get("file_glob") or "*")
            find = str(args.get("find") or "")
            repl = str(args.get("replace") or "")
            if root.is_dir() and find:
                for f in root.rglob(fg):
                    if not f.is_file():
                        continue
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    if find not in content:
                        continue
                    newc = content.replace(find, repl, 1)
                    diff = list(
                        difflib.unified_diff(
                            content.splitlines(True),
                            newc.splitlines(True),
                            fromfile=str(f),
                            tofile=str(f),
                            lineterm="",
                        )
                    )
                    args["diff"] = "".join(diff[:max_lines]) if diff else "(no change)"
                    return
            args["diff"] = "(search_replace: no matching file preview)"
    except Exception as e:
        args["diff"] = f"(diff preview failed: {e})"


def _is_junk_reply(content: str) -> bool:
    """True if content is junk that must never reach the user.

    Catches:
    - empty / whitespace-only
    - repeated 'assistant: I replied.' echo loops
    - raw decision-JSON blobs (model confusing tool-decision format with final reply)
    """
    if not content or not content.strip():
        return True
    import re as _re_junk
    s = content.strip().lower()
    if s == "i replied." or s == "assistant: i replied.":
        return True
    # Remove all "assistant: i replied." (with flexible spacing); if nothing left, it's junk
    remainder = _re_junk.sub(r"\s*assistant\s*:\s*i\s+replied\.\s*", " ", s, flags=_re_junk.IGNORECASE).strip()
    if len(remainder) < 15 and ("assistant" in s and "i replied" in s):
        return True
    # Decision-JSON blob: model outputted its internal decision format instead of natural language.
    # Detect: starts with '{' and contains at least two of the known decision keys.
    stripped = content.strip()
    if stripped.startswith("{"):
        _decision_keys = ("\"action\"", "\"tool\"", "\"thought\"", "\"ok\"", "\"objective_complete\"", "\"args\"")
        hits = sum(1 for k in _decision_keys if k in stripped)
        if hits >= 2:
            return True
    return False


def _quick_reply_for_trivial_turn(goal: str) -> str:
    """Return instant deterministic replies for tiny chat turns."""
    g = (goal or "").strip()
    if not g:
        return ""
    gl = g.lower()

    # Common smoke-test directives.
    if gl.startswith("reply exactly "):
        exact = g[len("reply exactly ") :].strip().strip("\"'`")
        return exact[:120]
    if gl.startswith("say exactly "):
        exact = g[len("say exactly ") :].strip().strip("\"'`")
        return exact[:120]

    if gl in {"ok", "okay", "yes", "yep", "no", "nope"}:
        return "Got it."
    for pat in _PHATIC_QUICK_PATTERNS:
        if re.match(pat, gl):
            return "I'm good. What do you need?"
    return ""


# Content signals: anything that looks like a real question or task should get full retrieval path.
_RETRIEVAL_SUBSTANTIVE_MARKERS = (
    "?",
    "who ", "what ", "why ", "how ", "when ", "where ", "which ",
    "explain", "describe", "tell me", "write ", "code", "create ", "list ",
    "summarize", "summarise", "analyze", "analyse", "compare", "contrast",
    "fix ", "debug", "error", "implement", "refactor", "test ",
    "can you", "could you", "would you", "please ", "help me",
    "define ", "meaning of", "difference between",
)

_PHATIC_RETRIEVAL_SKIP_PATTERNS = (
    r"^(hi|hey|hello|yo|sup|hiya|howdy)\b[!.ÃÃÂª\s]*$",
    r"^(thanks|thank you|thx|ty|tysm)\b[^?.]{0,48}[!.ÃÃÂª\s]*$",
    r"^(ok|okay|k|got it|yep|yeah|yes|no|nope|sure|mhm|uh huh)\b[!.ÃÃÂª\s]*$",
    r"^(bye|goodbye|see you|cya|later)\b[^?.]{0,24}[!.ÃÃÂª\s]*$",
)


def _is_lightweight_chat_turn(goal: str, reasoning_mode: str) -> bool:
    """True only for phatic / ack-only content where heavy retrieval is usually wasted.

    Not length-based: short questions like 'who are you' stay substantive (False).
    """
    if (reasoning_mode or "").strip().lower() not in {"none", "light"}:
        return False
    g = (goal or "").strip()
    if not g:
        return False
    gl = g.lower()
    if any(m in gl for m in _RETRIEVAL_SUBSTANTIVE_MARKERS):
        return False
    code_markers = (
        "def ", "class ", "import ", "traceback", "`", "```", "{", "}", "</", "/>",
        "http://", "https://",
    )
    if any(m in gl for m in code_markers):
        return False
    for pat in _PHATIC_RETRIEVAL_SKIP_PATTERNS:
        if re.match(pat, gl, re.IGNORECASE):
            return True
    return False


def truncate_at_next_user_turn(text: str) -> str:
    """Keep only the first reply; cut at the first 'User:' so we don't save/show the model continuing the dialogue."""
    if not text or not text.strip():
        return (text or "").strip()
    import re as _re
    t = text.strip()
    # If model echoed the prompt and started with "User: ...", keep only from the first aspect reply (e.g. "Eris: ...")
    if _re.match(r"^\s*User\s*:", t, _re.IGNORECASE):
        m = _re.search(r"^\s*User\s*:[^\n]*?\s+([A-Za-z]+)\s*:", t, _re.IGNORECASE)
        if m:
            t = t[m.start(1) :].strip()  # from "Eris:" (or aspect name) onward
        else:
            # no "Name:" on first line; drop the first line and keep the rest
            first_line_end = t.find("\n")
            if first_line_end != -1:
                t = t[first_line_end + 1 :].strip()
            else:
                t = ""
    # Cut at newline followed by "User:" (start of next user turn)
    m = _re.search(r"\n\s*User\s*:", t, _re.IGNORECASE)
    if m:
        return t[: m.start()].strip()
    # Cut at " User:" mid-line (e.g. "blah. User:")
    m = _re.search(r"\s+User\s*:", t, _re.IGNORECASE)
    if m:
        return t[: m.start()].strip()
    return t


def strip_junk_from_reply(text: str) -> str:
    """Remove repeated 'assistant: I replied.' and other junk from a reply before saving/displaying."""
    if not text or not text.strip():
        return (text or "").strip()
    import re as _re
    t = text.strip()
    for _ in range(50):
        prev = t
        t = _re.sub(r"^\s*assistant\s*:\s*I\s+replied\.\s*", "", t, count=1, flags=_re.IGNORECASE).strip()
        if t == prev:
            break
    # Strip [EARNED_TITLE: ...] prefix (aspect unlock notifications leaked into reply)
    t = _re.sub(r"^\s*\[EARNED_TITLE[^\]]*\]\s*", "", t, flags=_re.IGNORECASE).strip()
    # Strip "AspectName: " role prefixes at the start
    t = _re.sub(r"^(Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\s*:\s*", "", t).strip()
    # Strip completion-gate retry injection lines if they leaked into the response
    t = _re.sub(r"\[System:\s*Your last response[^\]]*\]\s*", "", t, flags=_re.IGNORECASE | _re.DOTALL).strip()
    # Truncate at prompt-echo markers (model echoed system prompt into reply)
    for _marker in (r"(?:^|\n)\s*#{1,3}\s*(TASK|CONTEXT|SCRATCHPAD|REPO)\b", r"(?:^|\n)\s*Current goal\s*:", r"(?:^|\n)\s*\[Active aspect\s*:", r"(?:^|\n)\s*Last user message\s*:", r"(?:^|\n)\s*Repo snapshot\s*:", r"(?:^|\n)\s*Repo structure\s*:", r"(?:^|\n)\s*##"):
        m = _re.search(_marker, t, _re.IGNORECASE)
        if m:
            t = t[: m.start()].strip()
    if _is_junk_reply(t):
        return ""
    return t


# Ensure DB tables exist before first request
_db_migrate()

# Last turn's reasoning mode (cross-request smoothing; single-operator local default)
_last_reasoning_mode: str = ""
_load_lock = threading.Lock()
_reason_mode_lock = threading.Lock()


def _iter_with_response_pacing(tokens, pacing_ms: int):
    """Minimum delay between successive streamed chunks (final reply path only). Caps at 10s per gap."""
    try:
        ms = int(pacing_ms or 0)
    except (TypeError, ValueError):
        ms = 0
    if ms <= 0:
        yield from tokens
        return
    delay = max(0.0, min(10.0, ms / 1000.0))
    first = True
    for t in tokens:
        if not first:
            time.sleep(delay)
        first = False
        yield t


def stream_reason(
    goal: str,
    context: str = "",
    conversation_history: list = None,
    aspect_id: str = "",
    show_thinking: bool = False,
    model_override: str | None = None,
    skip_self_reflection: bool = False,
    reasoning_mode_override: str | None = None,
    precomputed_recall: str | None = None,
    persona_focus: str = "",
    workspace_root: str = "",
    cognition_workspace_roots: list[str] | None = None,
    budget_retrieval_depth: str = "",
):
    """
    Build the same prompt as the reason path and yield token strings from streaming completion.
    Used when the client requests stream=True; no refusal/earned_title parsing.
    Sets model ContextVar for this generator (autonomous_run clears it before streaming).
    """
    from services.llm_gateway import set_model_override

    set_model_override(model_override)
    if not model_override:
        try:
            _cfg_route = runtime_safety.load_config()
            if _cfg_route.get("tool_routing_enabled", True):
                from services.model_router import classify_task_for_routing, is_routing_enabled

                if is_routing_enabled():
                    set_model_override(classify_task_for_routing(goal, context or "", _cfg_route))
        except Exception as _exc:
            logger.debug("agent_loop:L591: %s", _exc, exc_info=False)
    try:
        yield from _stream_reason_body(
            goal,
            context,
            conversation_history,
            aspect_id,
            show_thinking,
            skip_self_reflection,
            reasoning_mode_override=reasoning_mode_override,
            precomputed_recall=precomputed_recall,
            persona_focus=persona_focus,
            workspace_root=workspace_root,
            cognition_workspace_roots=cognition_workspace_roots,
        )
    finally:
        set_model_override(None)


def _stream_reason_body(
    goal: str,
    context: str = "",
    conversation_history: list = None,
    aspect_id: str = "",
    show_thinking: bool = False,
    skip_self_reflection: bool = False,
    reasoning_mode_override: str | None = None,
    precomputed_recall: str | None = None,
    persona_focus: str = "",
    workspace_root: str = "",
    cognition_workspace_roots: list[str] | None = None,
):
    """Inner generator: prompt + streaming tokens (model override set by stream_reason)."""
    active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
    # Classify reasoning need for the streaming path (same logic as the non-streaming path).
    # This gates expensive _build_system_head ops so "hi" doesn't trigger ChromaDB + graph + workspace.
    if reasoning_mode_override in {"none", "light", "deep"}:
        _stream_rmode = str(reasoning_mode_override)
    else:
        try:
            from services.reasoning_classifier import classify_reasoning_need, stabilize_reasoning_mode

            global _last_reasoning_mode
            _stream_rmode = classify_reasoning_need(goal, context or "")
            _cfg_sr = runtime_safety.load_config()
            if _stream_rmode == "deep" and (_cfg_sr.get("performance_mode") or "").strip().lower() in ("low",):
                _stream_rmode = "light"
            with _reason_mode_lock:
                _stream_rmode = stabilize_reasoning_mode(_last_reasoning_mode, _stream_rmode)
                _last_reasoning_mode = _stream_rmode
        except Exception:
            _stream_rmode = "light"
    _stream_recall = precomputed_recall or ""
    if not _stream_recall and goal and _stream_rmode != "none":
        try:
            _stream_recall = _semantic_recall(goal, k=runtime_safety.load_config().get("semantic_k", 5)).strip()
        except Exception as _exc:
            logger.warning("agent_loop:L648: %s", _exc, exc_info=True)
    head = _build_system_head(
        goal=goal,
        aspect=active_aspect,
        workspace_root=workspace_root or "",
        conversation_history=conversation_history or [],
        reasoning_mode=_stream_rmode,
        _precomputed_recall=_stream_recall,
        persona_focus_id=(persona_focus or "").strip().lower(),
        cognition_workspace_roots=cognition_workspace_roots,
    )
    convo_block = ""
    try:
        convo_turns = max(0, int(runtime_safety.load_config().get("convo_turns", 0)))
    except (TypeError, ValueError):
        convo_turns = 0
    if convo_turns > 0 and conversation_history:
        name = active_aspect.get("name", "Layla")
        turns = conversation_history[-convo_turns:]
        n_turns = len(turns)
        lines = []
        for i, t in enumerate(turns):
            role = t.get("role", "")
            # Recent turns (last 2) get more context; older turns are compressed.
            turns_from_end = n_turns - i
            max_chars = 600 if turns_from_end <= 2 else 220
            content_t = (t.get("content") or "")[:max_chars].strip()
            if role == "user":
                lines.append(f"User: {content_t}")
            else:
                if "system is under load" in content_t.lower():
                    content_t = "I couldn't reply just then."
                elif (content_t.startswith("[") and "You are" in content_t) or ("you are layla" in content_t.lower() and ("use the identity" in content_t.lower() or "rules below" in content_t.lower())):
                    content_t = _SANITIZED_PLACEHOLDER
                elif _is_junk_reply(content_t):
                    content_t = _SANITIZED_PLACEHOLDER
                lines.append(f"{name}: {content_t}")
        convo_block = "\n".join(lines)
    deliberate = show_thinking or orchestrator.should_deliberate(goal, active_aspect)
    if deliberate:
        prompt = orchestrator.build_deliberation_prompt(
            message=goal, active_aspect=active_aspect, context=_enrich_deliberation_context(context),
        )
        if head:
            prompt = head + "\n\n" + prompt
        if convo_block:
            prompt = prompt + f"\n\nRecent conversation:\n{convo_block}"
    else:
        prompt = orchestrator.build_standard_prompt(
            message=goal, aspect=active_aspect, context=context,
            head=head, convo_block=convo_block,
        )
    cfg = runtime_safety.load_config()  # noqa: F841
    temperature = cfg.get("temperature", 0.2)
    max_tok = cfg.get("completion_max_tokens", 256)
    stop = get_stop_sequences()
    gen = run_completion(prompt, max_tokens=max_tok, temperature=temperature, stream=True, stop=stop)
    try:
        _pace_ms = int(cfg.get("response_pacing_ms", 0) or 0)
    except (TypeError, ValueError):
        _pace_ms = 0
    gen = _iter_with_response_pacing(gen, _pace_ms)
    buffer = ""
    held_tokens: list[str] = []   # tokens held while we check for JSON blob start
    _json_suppressed = False
    _PROMPT_ECHO_RE = re.compile(r"(?:^|\n)\s*(##\s*(TASK|CONTEXT|SCRATCHPAD|REPO)\b|Current goal\s*:|\[Active aspect\s*:|Last user message\s*:|Repo snapshot\s*:|Repo structure\s*:)", re.IGNORECASE | re.MULTILINE)
    for token in gen:
        buffer += token
        if any(s in buffer for s in stop):
            break
        # Stop streaming if model starts echoing system prompt markers
        if _PROMPT_ECHO_RE.search(buffer):
            m = _PROMPT_ECHO_RE.search(buffer)
            clean = buffer[:m.start()].strip()
            if held_tokens:
                # Still in the initial buffer phase â yield clean text, discard junk tokens
                held_tokens.clear()
                if clean and not _is_junk_reply(clean):
                    yield clean
            buffer = clean
            break
        # Hold tokens until we know the reply isn't a raw decision-JSON blob.
        # Decision blobs start with '{' ÃÃÃ¶ we hold up to 120 chars before committing.
        if not held_tokens and not _json_suppressed:
            held_tokens.append(token)
            if len(buffer) < 120:
                continue  # keep buffering to check
            # Enough chars: decide
            if _is_junk_reply(buffer):
                _json_suppressed = True
                held_tokens.clear()
                continue
            # Not junk ÃÃÃ¶ flush held tokens
            for t in held_tokens:
                yield t
            held_tokens.clear()
        elif held_tokens:
            # Still accumulating during the check window
            held_tokens.append(token)
            if len(buffer) >= 120:
                if _is_junk_reply(buffer):
                    _json_suppressed = True
                    held_tokens.clear()
                else:
                    for t in held_tokens:
                        yield t
                    held_tokens.clear()
        elif not _json_suppressed:
            yield token
    # Flush any remaining held tokens (short replies that never hit 120 chars)
    if held_tokens and not _is_junk_reply(buffer):
        for t in held_tokens:
            yield t
    # Optional self-reflection: if enabled and score < 7, stream a rewritten response
    improved = None if skip_self_reflection else _reflect_on_response(goal, buffer, active_aspect)
    if improved:
        yield "\n\n---\n"  # visual separator for the UI
        yield improved


def _has_any_grant(tool: str, args: dict | None = None) -> bool:
    """Return True if either a session grant or a DB grant covers this call (D6)."""
    try:
        from services.session_grants import has_session_grant
        if has_session_grant(tool, args):
            return True
    except Exception as _exc:
        logger.debug("agent_loop:L763: %s", _exc, exc_info=False)
    try:
        from layla.memory.db import tool_grant_matches
        cmd = (args or {}).get("command") or (args or {}).get("path") or ""
        if tool_grant_matches(tool, cmd):
            return True
    except Exception as _exc:
        logger.debug("agent_loop:L770: %s", _exc, exc_info=False)
    return False


def _admin_pre_mutate(cfg: dict, workspace: str, tool: str, summary: str) -> None:
    """When admin_mode: git checkpoint + audit line before a mutating tool runs."""
    if not (isinstance(cfg, dict) and cfg.get("admin_mode")):
        return
    if cfg.get("admin_auto_checkpoint", True):
        try:
            from services.admin_checkpoint import git_checkpoint_layla

            git_checkpoint_layla(workspace, tool, summary)
        except Exception as _exc:
            logger.debug("agent_loop: admin checkpoint: %s", _exc, exc_info=False)
    try:
        from shared_state import get_audit

        get_audit()(tool, f"admin_auto {summary[:200]}", "admin_mode", True)
    except Exception as _exc:
        logger.debug("agent_loop: admin audit: %s", _exc, exc_info=False)


def _write_pending(tool: str, args: dict, ttl_seconds: int = 3600) -> str:
    """Write a pending approval entry and return its UUID. Exposes risk_level from registry for UI."""
    import uuid as _uuid
    from datetime import timedelta

    from layla.time_utils import utcnow
    gov_path = Path(__file__).resolve().parent / ".governance"
    gov_path.mkdir(parents=True, exist_ok=True)
    pending_file = gov_path / "pending.json"
    try:
        data = json.loads(pending_file.read_text(encoding="utf-8")) if pending_file.exists() else []
    except Exception:
        data = []
    # Prune old/non-pending approvals to keep file bounded.
    try:
        from datetime import datetime, timedelta

        keep_days = 7
        cutoff = (utcnow() - timedelta(days=keep_days)).isoformat()
        pruned = []
        for r in data if isinstance(data, list) else []:
            if not isinstance(r, dict):
                continue
            st = str(r.get("status") or "pending")
            if st != "pending":
                continue
            req = str(r.get("requested_at") or "")
            if req and req < cutoff:
                continue
            pruned.append(r)
        data = pruned[-500:]
    except Exception:
        pass
    entry_id = str(_uuid.uuid4())
    risk = (TOOLS.get(tool) or {}).get("risk_level") or "medium"
    now = utcnow()
    # TTL from config if available, else use caller-supplied default (3600s = 1h)
    try:
        _pcfg = runtime_safety.load_config()
        ttl_seconds = int(_pcfg.get("approval_ttl_seconds", ttl_seconds) or ttl_seconds)
    except Exception as _exc:
        logger.debug("agent_loop:L795: %s", _exc, exc_info=False)
    data.append({
        "id": entry_id,
        "tool": tool,
        "args": args,
        "requested_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=max(60, ttl_seconds))).isoformat(),
        "status": "pending",
        "risk_level": risk,
    })
    pending_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return entry_id


def _load_learnings(aspect_id: str = "") -> str:
    try:
        cfg = runtime_safety.load_config()
        n = cfg.get("learnings_n", 30)
        min_score = float(cfg.get("learning_min_score", 0.3) or 0.3)
        rows = _db_get_learnings(n=n, aspect_id=aspect_id or None, min_score=min_score)
        return "\n".join(r["content"] for r in rows if r.get("content"))
    except Exception as _e:
        logger.debug("load_learnings failed: %s", _e)
        return ""


def _semantic_recall(query: str, k: int = 5) -> str:
    """
    Full memory recall pipeline: BM25 + vector hybrid search + FTS5 + cross-encoder reranking.
    Falls back to pure vector search, then FTS on ChromaDB error.
    """
    try:
        from layla.memory.vector_store import search_memories_full
        cfg = runtime_safety.load_config()
        use_mmr = bool(cfg.get("retrieval_use_mmr", False))
        use_hyde = bool(cfg.get("hyde_enabled", False))
        results = search_memories_full(
            query, k=k, use_rerank=True, use_mmr=use_mmr, use_hyde=use_hyde
        )
        if not results:
            return ""
        lines = [r.get("content", "") for r in results if r.get("content")]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("ChromaDB failed, falling back to FTS: %s", e)
        try:
            from layla.memory.db import search_learnings_fts
            results = search_learnings_fts(query, n=k)
            lines = "\n".join(r.get("content", "") for r in results if r.get("content"))
            if lines.strip():
                logger.info("retrieval fallback: semantic recall using FTS (%d rows)", len(results))
            return lines
        except Exception:
            return ""


def _decompose_goal(goal: str) -> list:
    """If objective is broad, return 2-3 sub-objectives; else return []."""
    if not goal or len(goal.strip()) < 20:
        return []
    g = goal.lower().strip()
    broad_keywords = (
        "production ready", "refactor", "fix everything", "improve", "complete", "full",
        "make this repo", "get this ready", "clean up", "overhaul", "rewrite",
    )
    is_broad = len(goal) > 80 or any(kw in g for kw in broad_keywords)
    if not is_broad:
        return []
    try:
        cfg = runtime_safety.load_config()  # noqa: F841
        prompt = (
            f"Objective: {goal[:500]}\n\n"
            "Output exactly one JSON line: a JSON array of 2-3 concrete sub-objectives (short strings). "
            "Example: [\"Add tests\", \"Fix lint\", \"Update README\"]. No other text.\n"
        )
        out = run_completion(prompt, max_tokens=120, temperature=0.2, stream=False)
        if isinstance(out, dict):
            raw = (out.get("choices") or [{}])[0].get("message", {}).get("content") or (out.get("choices") or [{}])[0].get("text") or ""
        else:
            raw = ""
        for line in (raw or "").strip().splitlines():
            line = line.strip()
            if line.startswith("["):
                arr = json.loads(line)
                if isinstance(arr, list) and len(arr) >= 1:
                    subs = [str(x).strip() for x in arr[:3] if x]
                    return subs[:3]
        return []
    except Exception as e:
        logger.debug("decompose_goal failed: %s", e)
        return []


def _get_repo_structure(workspace_root: str | Path, max_entries: int = 40) -> str:
    """Top-level repo structure for workspace context. No tool call, filesystem only."""
    ws = str(workspace_root).strip() if workspace_root else ""
    if not ws:
        return ""
    try:
        root = Path(ws).resolve()
        if not root.exists() or not root.is_dir():
            return ""
        entries = []
        for p in sorted(root.iterdir())[:max_entries]:
            name = p.name
            if name.startswith(".") and name not in (".git",):
                continue
            entries.append(name + ("/" if p.is_dir() else ""))
        if not entries:
            return "(empty directory)"
        return ", ".join(entries[:max_entries])
    except Exception:
        return ""


def _enrich_deliberation_context(context: str) -> str:
    """Append project context and Echo patterns so deliberation has real workspace awareness."""
    extra = []
    try:
        from layla.memory.db import get_project_context
        pc = get_project_context()
        if pc.get("project_name") or pc.get("goals") or pc.get("lifecycle_stage"):
            proj_parts = [f"Project: {pc.get('project_name') or 'ÃÃÃ¶'}", f"Lifecycle: {pc.get('lifecycle_stage') or 'ÃÃÃ¶'}"]
            if pc.get("goals"):
                proj_parts.append(f"Goals: {(pc.get('goals') or '')[:200]}")
            extra.append("Project context: " + "; ".join(proj_parts))
    except Exception as _exc:
        logger.debug("agent_loop:L922: %s", _exc, exc_info=False)
    try:
        learnings = _db_get_learnings(n=5)
        if learnings:
            prefs = [ (ln.get("content") or "")[:80] for ln in learnings if (ln.get("content") or "").strip() ]
            if prefs:
                extra.append("Echo (patterns/preferences): " + "; ".join(prefs[:3]))
    except Exception as _exc:
        logger.debug("agent_loop:L930: %s", _exc, exc_info=False)
    if not extra:
        return context or ""
    return (context or "").strip() + "\n\n" + "\n".join(extra)


def _needs_knowledge_rag(goal: str) -> bool:
    """True if goal suggests research/search/explain or reflective/psychology-informed chat ÃÃÃ¶ use full Chroma retrieval."""
    if not (goal or "").strip():
        return False
    g = goal.lower()
    research_kw = (
        "research",
        "search",
        "explain",
        "look up",
        "what is",
        "how does",
        "find out",
        "learn about",
    )
    if any(kw in g for kw in research_kw):
        return True
    # Reflective / wellbeing phrasing ÃÃÃ¶ pulls psychology-framework knowledge when indexed (narrow list to limit noise on code chat).
    reflective_kw = (
        "reflect on",
        "self-reflect",
        "help me reflect",
        "overwhelmed",
        " i feel",
        "i'm feeling",
        "im feeling",
        "feeling stuck",
        "feeling anxious",
        "i'm anxious",
        "i am anxious",
        "pattern i",
        "noticed a pattern",
        "behavioral pattern",
        "why do i always",
        "why do i avoid",
        "i avoid",
        "keep avoiding",
        "relationship to work",
        "burnout",
        "cognitive distortion",
        "attachment style",
        "window of tolerance",
        "emotionally exhausted",
        "mental health",
        "talk to a therapist",
        "panic attack",
        "depressed about",
        "anxious about",
    )
    return any(kw in g for kw in reflective_kw)


def _needs_graph(goal: str) -> bool:
    """True if goal suggests related/context/connection ÃÃÃ¶ include graph associations."""
    if not (goal or "").strip():
        return False
    g = goal.lower()
    return any(kw in g for kw in ("related", "context", "connection", "link", "associate", "connected"))


def _aspect_dict_by_id(aspect_id: str) -> dict | None:
    """Resolve personalities/*.json entry by id (lowercase)."""
    aid = (aspect_id or "").strip().lower()
    if not aid:
        return None
    try:
        for a in orchestrator._load_aspects():
            if (a.get("id") or "").strip().lower() == aid:
                return a
    except Exception as _exc:
        logger.debug("agent_loop:L1006: %s", _exc, exc_info=False)
    return None


def _append_persona_focus_to_personality(
    personality: str,
    primary: dict | None,
    persona_focus_id: str,
    max_extra: int = 4500,
) -> str:
    """Inject a secondary aspect's prompt depth; primary aspect still owns routing/tools."""
    pid = (persona_focus_id or "").strip().lower()
    if not pid or not primary:
        return personality
    if (primary.get("id") or "").strip().lower() == pid:
        return personality
    sec = _aspect_dict_by_id(pid)
    if not sec:
        return personality
    name = sec.get("name", pid)
    role = (sec.get("role") or sec.get("voice") or "").strip()[:400]
    add = (sec.get("systemPromptAddition") or "").strip()
    if not add and not role:
        return personality
    chunk = add[:max_extra] if add else ""
    block = (
        f"\n\n---\nSecondary perspective (persona_focus={name}): blend this depth with the primary voice above; "
        f"the primary aspect still owns tools, approvals, and final voice.\n{role}\n\n{chunk}"
    )
    return personality + block


def _relationship_codex_context(cfg: dict, workspace_root: str) -> tuple[str, bool]:
    """
    Optional digest from `.layla/relationship_codex.json` for the system prompt.
    Only when inject is enabled, workspace is valid, and path is inside the sandbox.
    """
    if not bool(cfg.get("relationship_codex_inject_enabled", False)):
        return "", False
    wp = (workspace_root or "").strip()
    if not wp:
        return "", False
    try:
        wrp = Path(wp).expanduser().resolve()
    except Exception:
        return "", False
    if not wrp.is_dir():
        return "", False
    try:
        from layla.tools.registry import inside_sandbox
        from services.relationship_codex import codex_has_entities, format_codex_prompt_digest, load_codex

        if not inside_sandbox(wrp):
            return "", False
        data = load_codex(wrp)
        if not codex_has_entities(data):
            return "", False
        cap = int(cfg.get("relationship_codex_inject_max_chars", 1000) or 1000)
        digest = format_codex_prompt_digest(data, max_chars=cap)
        if not digest.strip():
            return "", False
        block = f"## Relationship codex (operator notes)\n{digest.strip()}"
        return block, True
    except Exception:
        return "", False


def _build_system_head(
    goal: str = "",
    aspect: dict | None = None,
    workspace_root: str = "",
    sub_goals: list | None = None,
    state: dict | None = None,
    conversation_history: list | None = None,
    reasoning_mode: str = "light",
    _precomputed_recall: str | None = None,
    persona_focus_id: str = "",
    cognition_workspace_roots: list[str] | None = None,
    packed_context: dict | None = None,
) -> str:
    cfg = runtime_safety.load_config()  # noqa: F841
    # Skip expensive retrieval operations for trivial/lightweight chat turns.
    # This keeps short conversational requests reactive.
    _skip_expensive = _is_lightweight_chat_turn(goal, reasoning_mode)
    identity = runtime_safety.load_identity().strip()
    knowledge = ""
    # Lazy: full Chroma knowledge RAG only when research/search/explain keywords
    if not _skip_expensive and cfg.get("use_chroma") and goal and _needs_knowledge_rag(goal):
        try:
            from layla.memory.vector_store import get_knowledge_chunks_with_sources, refresh_knowledge_if_changed
            try:
                refresh_knowledge_if_changed(REPO_ROOT / "knowledge")
            except Exception as _e:
                logger.debug("context[knowledge_refresh] failed: %s", _e)
            k = max(1, min(20, int(cfg.get("knowledge_chunks_k", 5))))
            _proj_domains: list[str] = []
            try:
                from layla.memory.db import get_project_context

                _pc = get_project_context() or {}
                _proj_domains = [str(d) for d in (_pc.get("domains") or []) if d]
            except Exception as _pde:
                logger.debug("context[project_domains_knowledge] failed: %s", _pde)
            # Use parent-doc retrieval when available for richer context
            try:
                from layla.memory.vector_store import get_knowledge_chunks_with_parent
                chunks_with_sources = get_knowledge_chunks_with_parent(
                    goal,
                    k=k,
                    aspect_id=(aspect.get("id") or "") if isinstance(aspect, dict) else "",
                    project_domains=_proj_domains or None,
                )
            except Exception:
                chunks_with_sources = get_knowledge_chunks_with_sources(
                    goal,
                    k=k,
                    aspect_id=(aspect.get("id") or "") if isinstance(aspect, dict) else "",
                    project_domains=_proj_domains or None,
                )
            if chunks_with_sources:
                knowledge = "Reference docs (relevant to this turn):\n" + "\n\n".join(c.get("text", "") for c in chunks_with_sources[:k])
                if state is not None:
                    sources = [c.get("source") or "" for c in chunks_with_sources[:k] if c.get("source")]
                    state["cited_knowledge_sources"] = list(dict.fromkeys(sources))
            else:
                if state is not None:
                    state["cited_knowledge_sources"] = []
        except Exception:
            if state is not None:
                state["cited_knowledge_sources"] = []
    if not knowledge.strip():
        # Fallback: lightweight docs when chroma disabled or non-research goal
        knowledge = runtime_safety.load_knowledge_docs(max_bytes=cfg.get("knowledge_max_bytes", 4000)).strip()
    else:
        knowledge = knowledge.strip()
    learnings = _load_learnings(aspect_id=(aspect.get("id") or "") if aspect else "").strip()

    # Build aspect identity: brief anchor line + full systemPromptAddition for voice/character depth
    if aspect:
        name = aspect.get("name", "Layla")
        title = (aspect.get("title") or "").strip()
        role = (aspect.get("role") or "").strip()[:120]
        anchor = f"{name} ({title})" if title else name
        if role:
            anchor += f" ÃÃÃ¶ {role}"
        anchor += ". Reply as her only. Do not output labels or repeat instructions."
        full_addition = (aspect.get("systemPromptAddition") or "").strip()
        if full_addition:
            personality = anchor + "\n\n" + full_addition
        else:
            personality = anchor
    else:
        raw = runtime_safety.load_personality().strip()
        personality = "Layla: default voice. Reply as her only. Do not output labels or repeat instructions." if (not raw or len(raw) > 200) else raw[:200] + ("." if len(raw) > 200 else "")

    personality = _append_persona_focus_to_personality(personality, aspect, persona_focus_id)

    if bool(cfg.get("voice_adjustment_inject_enabled", False)):
        try:
            from layla.memory.db import get_user_identity

            vadj = (get_user_identity("voice_adjustment") or "").strip()
            if vadj:
                personality += "\n\nLearned voice adjustment (operator-curated, keep tone consistent):\n" + vadj[:900]
        except Exception as _va:
            logger.debug("context[voice_adjustment] failed: %s", _va)

    # Aspect memories: recent observations for this aspect
    aspect_memories = ""
    n_mem = cfg.get("aspect_memories_n", 10)
    if aspect:
        aid = aspect.get("id", "")
        if aid:
            try:
                mems = _db_get_aspect_memories(aid, n_mem)
                if mems:
                    lines = [m.get("content", "") for m in mems if m.get("content")]
                    if lines:
                        aspect_memories = "Recent observations for this aspect:\n" + "\n".join(lines[:n_mem])
            except Exception as _e:
                logger.debug("context[aspect_memories] failed: %s", _e)

    # Semantic recall: use precomputed result if available (avoids double ChromaDB query).
    semantic = ""
    if _precomputed_recall is not None:
        semantic = _precomputed_recall
    elif not _skip_expensive and goal:
        semantic = _semantic_recall(goal, k=cfg.get("semantic_k", 5)).strip()

    # Memory graph associations: skip for trivial turns or short goals
    graph_associations = ""
    if not _skip_expensive and goal and (len(goal.split()) >= 3 or _needs_graph(goal)):
        try:
            from layla.memory.memory_graph import get_recent_nodes
            recent_nodes = get_recent_nodes(n=15)
            if recent_nodes:
                goal_words = set(w.lower() for w in goal.split() if len(w) > 3)
                relevant = [
                    n["label"] for n in recent_nodes
                    if any(w in (n.get("label") or "").lower() for w in goal_words)
                ]
                if not relevant:
                    relevant = [n["label"] for n in recent_nodes[-5:] if n.get("label")]
                if relevant:
                    graph_associations = "Knowledge graph associations: " + "; ".join(relevant[:8])
        except Exception as _e:
            logger.debug("context[graph_associations] failed: %s", _e)

    # Unified retrieval injection from packed_context (pre-assembled in autonomous_run)
    retrieved_context = ""
    _used_ids: list[str] = []
    if packed_context and (packed_context.get("retrieved_knowledge_text") or "").strip():
        retrieved_context = packed_context["retrieved_knowledge_text"].strip()
        if state is not None and packed_context.get("chunks_meta", {}).get("memory_items"):
            state["used_learning_ids"] = [
                str(x.get("id") or "") for x in packed_context["chunks_meta"]["memory_items"]
                if str(x.get("id") or "").strip()
            ]

    # Current working context: repo structure, study topics, sub-goals (unified surface)
    workspace_context_parts = []
    repo_struct = _get_repo_structure(workspace_root)
    if repo_struct:
        workspace_context_parts.append(f"Repo structure (top-level): {repo_struct}")
    # Workspace dependency context + semantic code search: only for coding/deep turns
    coding_keywords = ("code", "debug", "fix", "implement", "refactor", "function", "class", "module", "file", "grep", "read_file", "write_file")
    if not _skip_expensive and goal and workspace_root and any(kw in goal.lower() for kw in coding_keywords):
        try:
            from services.workspace_index import get_workspace_dependency_context

            dep_ctx = get_workspace_dependency_context(goal, workspace_root, max_chars=400)
            if dep_ctx:
                workspace_context_parts.append(dep_ctx)
            # Use pre-assembled code context from packed_context
            if packed_context and (packed_context.get("code_text") or "").strip():
                workspace_context_parts.append("Semantic code matches:\n" + packed_context["code_text"][:6000])
        except Exception as _e:
            logger.debug("context[workspace_index] failed: %s", _e)
    try:
        from layla.memory.db import get_active_study_plans
        plans = get_active_study_plans()
        if plans:
            topics = ", ".join((p.get("topic") or "")[:50] for p in plans[:5] if p.get("topic"))
            if topics:
                workspace_context_parts.append(f"Active study topics: {topics}")
    except Exception as _e:
        logger.debug("context[study_plans] failed: %s", _e)
    try:
        from layla.memory.db import get_project_context
        pc = get_project_context()
        if pc.get("project_name") or pc.get("goals") or pc.get("key_files"):
            proj_parts = []
            if pc.get("project_name"):
                proj_parts.append(f"Project: {pc['project_name']}")
            if pc.get("lifecycle_stage"):
                proj_parts.append(f"Lifecycle: {pc['lifecycle_stage']}")
            if pc.get("domains"):
                proj_parts.append("Domains: " + ", ".join(pc["domains"][:8]))
            if pc.get("key_files"):
                proj_parts.append("Key files: " + ", ".join(pc["key_files"][:10]))
            if pc.get("goals"):
                proj_parts.append("Goals: " + (pc["goals"][:200] or ""))
            if pc.get("progress"):
                proj_parts.append("Progress: " + (pc["progress"][:200] or ""))
            if pc.get("blockers"):
                proj_parts.append("Blockers: " + (pc["blockers"][:200] or ""))
            if pc.get("last_discussed"):
                proj_parts.append("Last discussed: " + (pc["last_discussed"][:200] or ""))
            try:
                from layla.memory.db import get_active_goals
                goals_list = get_active_goals(project_id=pc.get("project_name", ""))
                if goals_list:
                    proj_parts.append("Active goals: " + "; ".join((g.get("title") or "")[:50] for g in goals_list[:3]))
            except Exception as _e:
                logger.debug("context[active_goals] failed: %s", _e)
            if proj_parts:
                workspace_context_parts.append("Project context: " + " | ".join(proj_parts))
    except Exception as _e:
        logger.debug("context[project_context] failed: %s", _e)
    if sub_goals:
        workspace_context_parts.append("Sub-objectives for this run: " + "; ".join(sub_goals[:3]))
    if workspace_context_parts:
        workspace_context = "Current working context:\n" + "\n".join(workspace_context_parts)
    else:
        workspace_context = ""

    git_preamble = ""
    project_instructions = ""
    skills_block = ""
    wr_root = (workspace_root or cfg.get("sandbox_root") or "").strip()
    if wr_root:
        try:
            import subprocess
            from pathlib import Path

            cwd = Path(wr_root).expanduser().resolve()
            if cwd.is_dir():
                br = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=3,
                    encoding="utf-8",
                    errors="replace",
                )
                st = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=3,
                    encoding="utf-8",
                    errors="replace",
                )
                lg = subprocess.run(
                    ["git", "log", "--oneline", "-5"],
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=3,
                    encoding="utf-8",
                    errors="replace",
                )
                b, s, l = (br.stdout or "").strip(), (st.stdout or "").strip(), (lg.stdout or "").strip()
                if b or s or l:
                    git_preamble = f"Git snapshot:\nbranch: {b}\nstatus:\n{s}\nrecent:\n{l}"[:1200]
        except Exception as _exc:
            logger.debug("agent_loop:L1310: %s", _exc, exc_info=False)
        try:
            root = Path(wr_root).expanduser().resolve()
            found_pi = ""
            for parent in [root, *list(root.parents)[:3]]:
                for name in ("CLAUDE.md", "AGENTS.md"):
                    p = parent / name
                    if p.is_file():
                        found_pi = p.read_text(encoding="utf-8", errors="replace")[:4000]
                        break
                if found_pi:
                    break
            if not found_pi:
                for rel in (".layla/instructions.md", ".layla/SYSTEM.md"):
                    p = root / rel
                    if p.is_file():
                        found_pi = p.read_text(encoding="utf-8", errors="replace")[:4000]
                        break
            project_instructions = found_pi
        except Exception as _exc:
            logger.debug("agent_loop:L1330: %s", _exc, exc_info=False)
        if goal:
            try:
                from services import skills as skills_mod

                skills_block = skills_mod.skills_prompt_block(goal, wr_root, max_tokens=800)
            except Exception as _exc:
                logger.debug("agent_loop:L1337: %s", _exc, exc_info=False)

    # Build sections for centralized context management (token budgets, deduplication)
    from services.prompt_builder import build_core_sys_parts

    sys_parts = build_core_sys_parts(
        cfg=cfg,
        aspect=aspect,
        identity=identity,
        personality=personality,
        goal=goal,
        reasoning_mode=reasoning_mode,
        repo_root=REPO_ROOT,
    )
    system_instructions = "\n\n".join(sys_parts)

    # Aspect behavioral instructions: response length + refusal topics.
    # Injected here so they sit at the same authority level as identity.
    try:
        from services.aspect_behavior import build_behavior_block as _ab_block
        _behavior_block = _ab_block(aspect)
        if _behavior_block:
            system_instructions = system_instructions + "\n\n" + _behavior_block
    except Exception as _ab_e:
        logger.debug("aspect_behavior block inject failed: %s", _ab_e)

    # German language mode: inject CEFR-calibrated instructions when enabled.
    try:
        _german_enabled = False
        try:
            _gcfg = cfg if isinstance(cfg, dict) else {}
            _german_enabled = bool(_gcfg.get("german_mode_enabled", False))
        except Exception:
            pass
        if not _german_enabled:
            try:
                from layla.memory.db_connection import _conn as _gconn
                _gc = _gconn()
                _grow = _gc.execute(
                    "SELECT 1 FROM german_profile WHERE user_id='default' LIMIT 1"
                ).fetchone()
                _gc.close()
                # Only inject if user has set up a profile explicitly
                _german_enabled = False  # profile exists but mode not enabled by default
            except Exception:
                pass
        if _german_enabled:
            from services.german_mode import build_german_system_block, get_profile as _gprof
            _glevel = _gprof().get("level", "B1")
            _german_block = build_german_system_block(_glevel)
            system_instructions = system_instructions + "\n\n" + _german_block
    except Exception as _ge:
        logger.debug("german_mode inject failed: %s", _ge)

    # Memory: learnings + semantic + aspect_memories + retrieved (canonical order: context_merge_layers.MEMORY_SECTION_ORDER)
    from services.context_merge_layers import MEMORY_SECTION_ORDER

    memory_sections: dict[str, str] = {}
    # Small-model guard: skip expensive sections when context window â¤ 4096.
    # Full injection overflows the window by ~2000 tokens on small models.
    _n_ctx = int(cfg.get("n_ctx", 4096) or 4096)
    _small_model = _n_ctx <= 4096
    if git_preamble and not _small_model:
        memory_sections["git_preamble"] = git_preamble
    if project_instructions and not _small_model:
        memory_sections["project_instructions"] = "Project instructions:\n" + project_instructions
    try:
        from services.repo_cognition import format_cognition_for_prompt, merge_cognition_roots

        _cog_roots = merge_cognition_roots(workspace_root, cognition_workspace_roots)
        if _cog_roots and cfg.get("repo_cognition_inject_enabled", True) and not _small_model:
            _cog_max = int(cfg.get("repo_cognition_max_chars", 6000) or 6000)
            _cog_block = format_cognition_for_prompt(_cog_roots, max_chars=_cog_max)
            if _cog_block.strip():
                memory_sections["repo_cognition"] = (
                    "Repository cognition (deterministic snapshot from last sync ÃÃÃ¶ stated intent, norms, and doc excerpts; "
                    "verify against files when editing):\n"
                    + _cog_block
                )
    except Exception as _e:
        logger.debug("context[repo_cognition] failed: %s", _e)
    _pm_chunks: list[str] = []
    try:
        if cfg.get("project_memory_enabled", True) and (workspace_root or "").strip():
            from pathlib import Path

            from layla.tools.registry import inside_sandbox
            from services.project_memory import (
                format_aspects_hint,
                format_for_prompt,
                load_project_memory,
                memory_file_path,
            )

            wrp = Path(str(workspace_root).strip()).expanduser().resolve()
            if wrp.is_dir() and inside_sandbox(wrp) and memory_file_path(wrp).is_file():
                mem = load_project_memory(wrp)
                if mem:
                    _pm_max = int(cfg.get("project_memory_inject_max_chars", 4000) or 4000)
                    _pm_block = format_for_prompt(mem, max_chars=max(500, _pm_max))
                    if _pm_block.strip():
                        _pm_chunks.append(
                            "Project memory (local `.layla/project_memory.json` ÃÃÃ¶ structural map, plan, todos; "
                            "verify against source when editing):\n"
                            + _pm_block
                        )
                    _asp = format_aspects_hint(mem, str((aspect or {}).get("id") or ""))
                    if _asp.strip():
                        _pm_chunks.append(_asp)
    except Exception as _e:
        logger.debug("context[project_memory] failed: %s", _e)
    if _pm_chunks:
        memory_sections["project_memory"] = "\n\n".join(_pm_chunks)
    if not _small_model:
        try:
            _codex_block, _ = _relationship_codex_context(cfg, workspace_root)
            if _codex_block.strip():
                memory_sections["relationship_codex"] = _codex_block.strip()
        except Exception as _e:
            logger.debug("context[relationship_codex] failed: %s", _e)
    if skills_block and not _small_model:
        memory_sections["skills"] = "Matched skills:\n" + skills_block
    if aspect_memories:
        memory_sections["aspect_memories"] = aspect_memories
    if learnings:
        memory_sections["learnings"] = f"Things I remember:\n{learnings}"
    if semantic and semantic not in learnings:
        memory_sections["semantic_recall"] = f"Relevant memories:\n{semantic}"
    if retrieved_context:
        memory_sections["retrieved_context"] = retrieved_context
    # Working memory: cross-session project state (active project, next action, blockers, recent facts).
    try:
        from services.working_memory import format_for_prompt as _wm_format
        _wm_text = _wm_format()
        if _wm_text.strip():
            memory_sections["working_memory"] = _wm_text
    except Exception as _wm_e:
        logger.debug("context[working_memory] failed: %s", _wm_e)
    if not _small_model:
        try:
            from layla.memory.db import get_recent_conversation_summaries
            summaries = get_recent_conversation_summaries(n=3)
            if summaries:
                summary_texts = [s.get("summary", "") for s in summaries if s.get("summary")]
                if summary_texts:
                    memory_sections["conversation_summaries"] = "Prior conversation summaries:\n" + "\n\n".join(summary_texts)
        except Exception as _e:
            logger.debug("context[conversation_summaries] failed: %s", _e)
    # Relationship memory + timeline events: skip for trivial/chat turns or small models
    if not _skip_expensive and not _small_model:
        try:
            from layla.memory.db import get_recent_relationship_memories
            rel_mems = get_recent_relationship_memories(n=3)
            if rel_mems:
                rel_texts = [m.get("user_event", "") for m in rel_mems if m.get("user_event")]
                if rel_texts:
                    memory_sections["relationship_memory"] = "Recent relationship context:\n" + "\n\n".join(rel_texts)
        except Exception as _e:
            logger.debug("context[relationship_memory] failed: %s", _e)
        try:
            from layla.memory.db import get_recent_timeline_events
            timeline = get_recent_timeline_events(n=5, min_importance=0.3)
            if timeline:
                tl_texts = [f"[{e.get('event_type','')}] {e.get('content','')}" for e in timeline if e.get("content")]
                if tl_texts:
                    memory_sections["timeline_events"] = "Recent timeline:\n" + "\n\n".join(tl_texts[:5])
        except Exception as _e:
            logger.debug("context[timeline_events] failed: %s", _e)
    # Style profile + user identity ÃÃ¥Ã single precedence layer (docs/MEMORY_PRECEDENCE.md)
    _style_identity_parts: list[str] = []
    if cfg.get("enable_style_profile"):
        try:
            from services.style_profile import get_profile_summary
            profile = get_profile_summary()
            profile_parts = []
            if profile.get("response_style"):
                profile_parts.append(profile["response_style"])
            if profile.get("topics"):
                profile_parts.append(profile["topics"])
            if profile.get("collaboration"):
                profile_parts.append(profile["collaboration"])
            if profile_parts:
                _style_identity_parts.append("Conversation style (match these):\n" + "\n".join(profile_parts))
        except Exception as _e:
            logger.debug("context[style_profile] failed: %s", _e)
    try:
        from layla.memory.db import get_all_user_identity
        uid = get_all_user_identity()
        if uid:
            parts = [f"{k}: {v}" for k, v in uid.items() if v]
            if parts:
                _style_identity_parts.append("User/companion context:\n" + "\n".join(parts))
            try:
                # FRAME calibration: stat profile -> behavioral prompt modifiers.
                from services.frame_modifier import (
                    build_frame_block,
                    load_stats_from_identity,
                    write_profile_snapshot,
                )
                _frame_stats = load_stats_from_identity(uid)
                _frame_block = build_frame_block(_frame_stats)
                if _frame_block:
                    _style_identity_parts.append(_frame_block)
                # Write offline snapshot (non-blocking, best-effort).
                try:
                    write_profile_snapshot(uid)
                except Exception:
                    pass
            except Exception as _e2:
                logger.debug("context[frame_modifier] failed: %s", _e2)
            # Layla v3: surface capability levels as a short training snapshot (skip for trivial turns).
            if not _skip_expensive and cfg.get("capability_level_inject_enabled", True):
                try:
                    from layla.memory.db import get_capabilities, get_capability_domains

                    caps = get_capabilities() or []
                    domains = {d.get("id"): (d.get("name") or d.get("id")) for d in (get_capability_domains() or [])}
                    scored: list[tuple[str, float]] = []
                    for c in caps:
                        did = c.get("domain_id")
                        if did:
                            scored.append((str(did), float(c.get("level") or 0.5)))
                    if scored:
                        scored.sort(key=lambda x: -x[1])
                        top = scored[:3]
                        low = list(reversed(scored[-3:])) if len(scored) >= 3 else scored
                        top_s = ", ".join(f"{domains.get(d, d)} {lvl:.2f}" for d, lvl in top)
                        low_s = ", ".join(f"{domains.get(d, d)} {lvl:.2f}" for d, lvl in low)
                        _style_identity_parts.append(
                            "Training snapshot:\n"
                            + f"- Strong domains: {top_s}\n"
                            + f"- Focus next: {low_s}"
                        )
                except Exception as _e3:
                    logger.debug("context[capabilities] failed: %s", _e3)
    except Exception as _e:
        logger.debug("context[user_identity] failed: %s", _e)
    if _style_identity_parts:
        memory_sections["style_and_identity"] = "\n\n".join(_style_identity_parts)
    # Personal knowledge graph: skip for trivial turns or small models
    if not _skip_expensive and not _small_model:
        try:
            from services.personal_knowledge_graph import get_personal_graph_context
            pkg_ctx = get_personal_graph_context(goal or "", max_chars=400)
            if pkg_ctx:
                memory_sections["personal_knowledge_graph"] = "Personal context (relevant):\n" + pkg_ctx
        except Exception as _e:
            logger.debug("context[personal_knowledge_graph] failed: %s", _e)
    if not _skip_expensive and not _small_model:
        try:
            from services.rl_feedback import get_rl_hint_for_prompt

            rl_hint = get_rl_hint_for_prompt()
            if rl_hint:
                memory_sections["rl_feedback"] = rl_hint
        except Exception:
            pass
    # Reasoning strategies for complex goals (skip on small models)
    if goal and len(goal) > 100 and not _small_model:
        try:
            from services.reasoning_strategies import get_strategy_prompt_hint
            hint = get_strategy_prompt_hint(goal)
            if hint:
                memory_sections["reasoning_strategies"] = hint
        except Exception as _e:
            logger.debug("context[reasoning_strategies] failed: %s", _e)
    # Golden examples: inject small successful patterns for similar goals (token-bounded).
    if not _skip_expensive and not _small_model:
        try:
            if cfg.get("golden_examples_enabled", True):
                from services.golden_examples import bump_usage as _ge_bump_usage
                from services.golden_examples import format_for_prompt as _ge_format
                from services.golden_examples import retrieve_relevant_examples as _ge_retrieve

                ex = _ge_retrieve(goal or "", "agent", k=2)
                if ex:
                    memory_sections["golden_examples"] = _ge_format(ex, max_chars=1200)
                    try:
                        _ge_bump_usage([int(x.get("id")) for x in ex if x.get("id") is not None])
                    except Exception:
                        pass
        except Exception as _e:
            logger.debug("context[golden_examples] failed: %s", _e)
    try:
        from services.context_manager import deduplicate_content

        _ordered = [(memory_sections.get(k) or "").strip() for k in MEMORY_SECTION_ORDER]
        _ordered = [x for x in _ordered if x]
        memory_parts = deduplicate_content(_ordered, key_len=100)
    except Exception:
        memory_parts = [(memory_sections.get(k) or "").strip() for k in MEMORY_SECTION_ORDER if (memory_sections.get(k) or "").strip()]
    memory_block = "\n\n".join(memory_parts) if memory_parts else ""

    pinned_parts: list[str] = []
    hist = conversation_history or []
    if hist:
        for t in reversed(hist):
            if (t.get("role") or "").lower() == "user":
                u = (t.get("content") or "").strip()[:500]
                if u:
                    pinned_parts.append(f"Last user message: {u}")
                break
    if state and state.get("steps"):
        try:
            import json as _json

            last = state["steps"][-1]
            act = last.get("action") or last.get("tool") or "?"
            res = last.get("result")
            if res is not None:
                rs = res if isinstance(res, str) else _json.dumps(res, default=str)[:900]
                pinned_parts.append(f"Last tool ({act}): {rs}")
        except Exception as _exc:
            logger.debug("agent_loop:L1632: %s", _exc, exc_info=False)
    try:
        from layla.memory.db import get_recent_conversation_summaries

        sums = get_recent_conversation_summaries(n=1)
        if sums and (sums[0].get("summary") or "").strip():
            pinned_parts.append("Session summary: " + (sums[0]["summary"] or "").strip()[:400])
    except Exception as _exc:
        logger.debug("agent_loop:L1640: %s", _exc, exc_info=False)
    try:
        if packed_context:
            ft = (packed_context.get("files_text") or "").strip()
            if ft:
                pinned_parts.append("Operator file context (ranked excerpts):\n" + ft[:4000])
            ident = (packed_context.get("identity_snippet") or "").strip()
            if ident:
                pinned_parts.append("Identity hint:\n" + ident[:1200])
    except Exception as _pe:
        logger.debug("context[packed_pinned] failed: %s", _pe)
    pinned_block = "\n".join(pinned_parts) if pinned_parts else ""

    current_goal = ""
    if sub_goals:
        current_goal = "Sub-objectives: " + "; ".join(sub_goals[:3])
    elif goal:
        current_goal = "Current goal: " + (goal[:200] + "..." if len(goal) > 200 else goal)

    budgets = None
    if cfg.get("prompt_budgets"):
        budgets = dict(DEFAULT_BUDGETS)
        for k, v in (cfg.get("prompt_budgets") or {}).items():
            if k in budgets and v is not None:
                budgets[k] = max(0, int(v))

    if cfg.get("tiered_prompt_budget_enabled", True):
        try:
            from services.prompt_tier_budget import budgets_for_mode

            _rm_search = (goal or "").lower()
            _researchish = any(x in _rm_search for x in ("research", "paper", "arxiv", "study", "explain in depth"))
            tier_budgets = budgets_for_mode(reasoning_mode, research_mode=_researchish)
            if budgets is None:
                budgets = dict(DEFAULT_BUDGETS)
            budgets["memory"] = min(int(budgets.get("memory", 800)), int(tier_budgets.get("memory", 800)))
            budgets["knowledge"] = min(int(budgets.get("knowledge", 800)), int(tier_budgets.get("knowledge", 800)))
            budgets["workspace_context"] = min(int(budgets.get("workspace_context", 400)), int(tier_budgets.get("workspace", 400)))
            # Keep legacy section key in sync: build_system_prompt budgets are keyed by section name.
            budgets["agent_state"] = int(budgets["workspace_context"])
            _sys_cap = int(tier_budgets.get("identity", 200)) + int(tier_budgets.get("personality", 400)) + int(tier_budgets.get("policy", 300))
            budgets["system_instructions"] = min(int(budgets.get("system_instructions", 800)), max(400, _sys_cap * 2))
        except Exception as _tb_e:
            logger.debug("tiered prompt budget skipped: %s", _tb_e)

    # Inject hardware capability summary so Layla knows her own limits and
    # can accurately describe what she can/cannot do on this machine.
    try:
        from services.hardware_detect import get_capability_summary as _hw_cap_summary
        _hw_summary = _hw_cap_summary()
        if _hw_summary:
            system_instructions = (system_instructions or "") + "\n\n" + _hw_summary
    except Exception as _hw_e:
        logger.debug("hardware_probe capability_summary inject skipped: %s", _hw_e)

    sections = {
        "system_instructions": system_instructions,
        "pinned_context": pinned_block,
        "agent_state": workspace_context,
        "current_goal": current_goal,
        "memory": memory_block,
        "knowledge_graph": graph_associations,
        "knowledge": f"Reference docs:\n{knowledge}" if knowledge else "",
    }
    # Token-pressure: measure how much of n_ctx the conversation already uses
    _n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
    _hist_for_pressure = conversation_history or []
    try:
        from services.context_manager import token_estimate_messages
        _hist_tokens = token_estimate_messages(_hist_for_pressure)
        _hist_ratio = _hist_tokens / _n_ctx
    except Exception:
        _hist_ratio = 0.0

    if _hist_ratio > 0.4:
        # Inject compact-work directive when context is getting full
        sys_parts.append(
            "Context pressure: conversation is using more than 40% of available context. "
            "Decompose tasks into the smallest possible steps. "
            "Do one thing per response. Prefer `think` actions over long in-context reasoning. "
            "Use `read_file` only for specific sections, not full files."
        )
        system_instructions = "\n\n".join(sys_parts)
        sections["system_instructions"] = system_instructions

    if cfg.get("prompt_budget_enabled", True):
        _head_ratio = float(cfg.get("system_head_budget_ratio", 0.35) or 0.35)
        _head_ratio = max(0.15, min(0.55, _head_ratio))
        n_ctx = max(1024, int(_n_ctx * _head_ratio))
        assembled, _ctx_metrics = build_system_prompt(sections, n_ctx=n_ctx, budgets=budgets, reserve_for_response=512)
        if _ctx_metrics.get("truncated_sections") or _ctx_metrics.get("dropped_sections"):
            logger.debug(
                "context budget: truncated=%s dropped=%s total_tok=%d",
                _ctx_metrics.get("truncated_sections"),
                _ctx_metrics.get("dropped_sections"),
                _ctx_metrics.get("total_tokens", 0),
            )
        head = assembled if assembled.strip() else "You are Layla, a bounded AI companion and engineering agent."
        if cfg.get("custom_system_prefix"):
            head = head + "\n\n" + cfg["custom_system_prefix"].strip()
        return head
    # Legacy path: no budget enforcement
    parts = [system_instructions]
    if pinned_block:
        parts.append(pinned_block[:1500])
    if workspace_context:
        parts.append(workspace_context[:1200])
    if current_goal:
        parts.append(current_goal)
    if memory_block:
        parts.append(memory_block)
    if graph_associations:
        parts.append(graph_associations)
    if knowledge:
        parts.append(f"Reference docs:\n{knowledge}")
    head = "\n\n".join(parts) if parts else "You are Layla, a bounded AI companion and engineering agent."
    if cfg.get("custom_system_prefix"):
        head = head + "\n\n" + cfg["custom_system_prefix"].strip()
    return head


def _reflect_on_response(goal: str, response: str, aspect: dict | None = None) -> str | None:
    """
    Self-reflection pass: score the response 1-10. If score < 7, rewrite it.
    Returns the improved response, or None if reflection is disabled/failed/unnecessary.
    Only runs when enable_self_reflection=True in config AND response is long enough.
    Adds ~1 extra inference call; opt-in only.
    """
    cfg = runtime_safety.load_config()  # noqa: F841
    if not cfg.get("enable_self_reflection", False):
        return None
    try:
        min_len = int(cfg.get("self_reflection_min_length", 200) or 200)
    except (TypeError, ValueError):
        min_len = 200
    if len(response.strip()) < max(80, min_len):  # too short to bother reflecting
        return None
    prev_override = None
    try:
        from services.llm_gateway import get_model_override, run_completion, set_model_override
        try:
            prev_override = get_model_override()
            # Prefer the coding model for critique when the goal looks code-related.
            from services.model_router import classify_task

            if classify_task(goal or "", response or "") == "coding" and (cfg.get("coding_model") or "").strip():
                set_model_override("coding")
        except Exception:
            pass
        aspect_name = (aspect.get("name") or "Layla") if aspect else "Layla"
        critic_prompt = (
            f"You are a response quality critic for {aspect_name}.\n\n"
            f"Original question: {goal[:300]}\n\n"
            f"Response to review: {response[:800]}\n\n"
            f"Score this response 1-10 for: accuracy, completeness, and helpfulness. "
            f"Reply with only a number (1-10) on the first line, then 'GOOD' if score >= 7 "
            f"or a rewritten better response if score < 7. Do NOT repeat the original if it was good."
        )
        result = run_completion(critic_prompt, max_tokens=600, temperature=0.1)
        if not isinstance(result, dict):
            return None
        critique = ((result.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
        if not critique:
            return None
        lines = critique.split("\n", 1)
        try:
            score = int("".join(c for c in lines[0][:3] if c.isdigit()))
        except (ValueError, IndexError):
            return None
        if score >= 7:
            return None  # original was good
        # Score < 7: use the rewritten portion
        rewritten = lines[1].strip() if len(lines) > 1 else ""
        if rewritten and len(rewritten) > 40 and rewritten.upper() != "GOOD":
            import logging
            logging.getLogger("layla").info("Self-reflection improved response (score was %d/10)", score)
            return rewritten
    except Exception as _exc:
        logger.debug("agent_loop:L1782: %s", _exc, exc_info=False)
    finally:
        try:
            from services.llm_gateway import set_model_override

            set_model_override(prev_override)
        except Exception:
            pass
    return None


# Smoothed load: avoid one spike from blocking every request
_last_cpu: float = 0.0
_last_ram: float = 0.0


def system_overloaded(priority: int = PRIORITY_AGENT) -> bool:
    global _last_cpu, _last_ram
    cfg = runtime_safety.load_config()  # noqa: F841
    cpu = psutil.cpu_percent(interval=0)
    ram = psutil.virtual_memory().percent
    with _load_lock:
        # Smooth with previous sample so a single spike does not block
        smooth_cpu = (cpu + _last_cpu) / 2.0 if _last_cpu else cpu
        smooth_ram = (ram + _last_ram) / 2.0 if _last_ram else ram
        _last_cpu, _last_ram = cpu, ram
    # Chat should remain reactive even under pressure; background can be throttled.
    if priority <= PRIORITY_CHAT:
        return False
    hard_cpu = float(cfg.get("hard_cpu_percent", cfg.get("max_cpu_percent", 95)))
    hard_ram = float(cfg.get("max_ram_percent", 90))
    return smooth_cpu > hard_cpu or smooth_ram > hard_ram


# Valid tool names for LLM decision (must match TOOLS registry)
_VALID_TOOLS = frozenset(TOOLS.keys())


def _format_steps(steps: list) -> str:
    """Window tool-step formatting to avoid unbounded prompt growth."""
    try:
        cfg = runtime_safety.load_config()
        n = int(cfg.get("tool_steps_window", 25) or 25)
    except Exception:
        n = 25
    try:
        if n > 0 and isinstance(steps, list) and len(steps) > n:
            steps = steps[-n:]
    except Exception:
        pass
    return _format_steps_impl(steps)


def _summarize_steps_deterministic(steps: list, *, keep_last: int = 5, max_lines: int = 10) -> str:
    """
    Deterministic step summarization (no LLM).
    Summarizes older steps so weak models don't drown in long tool traces.
    """
    if not isinstance(steps, list) or len(steps) <= keep_last:
        return ""
    prefix = steps[: max(0, len(steps) - keep_last)]
    lines: list[str] = []
    n = 0
    for s in prefix:
        if not isinstance(s, dict):
            continue
        act = str(s.get("action") or "")
        if not act:
            continue
        r = s.get("result")
        ok = None
        extra = ""
        if isinstance(r, dict):
            ok = r.get("ok")
            p = r.get("path")
            if isinstance(p, str) and p.strip():
                extra = f" path={p.strip()}"
            rc = r.get("returncode")
            if rc is not None and act in ("shell", "run_python"):
                extra = (extra + f" rc={rc}").strip()
        elif isinstance(r, str) and act == "reason":
            ok = True
        status = "ok" if ok else "fail" if ok is False else "?"
        lines.append(f"- {act} ÃÃ¥Ã {status}{extra}")
        n += 1
        if n >= max_lines:
            break
    if not lines:
        return ""
    return "Steps completed so far (compressed):\n" + "\n".join(lines)


def _get_tools_for_goal(goal: str, *, context: str = "", workspace_root: str = "", state: dict | None = None) -> frozenset:
    """
    Return tool names for this turn. Applies OpenClaw-style tool_policy (profile,
    tools_allow/deny, groups) then intent-based subset when tool_routing_enabled.
    """
    try:
        cfg = runtime_safety.load_config()
        from services.intent_router import route_intent
        from services.tool_policy import (
            deterministic_route_tools_for_task_type,
            resolve_effective_tools_for_route,
        )

        skip_intent = not cfg.get("tool_routing_enabled", True)
        rd = None
        if state is not None and isinstance(state, dict):
            existing = state.get("route_decision")
            if isinstance(existing, dict) and (state.get("original_goal") or state.get("goal")) == goal:
                rd = existing
        if rd is None:
            rd = route_intent(goal, context=context, workspace_root=workspace_root)
            if state is not None and isinstance(state, dict):
                state["route_decision"] = rd.to_dict()
        else:
            # convert back into an object-like shape for downstream
            from services.intent_router import RouteDecision
            rd = RouteDecision(**rd)
        names = set(resolve_effective_tools_for_route(cfg, rd, goal, TOOLS, skip_intent_filter=skip_intent))
        try:
            det = deterministic_route_tools_for_task_type(cfg, rd.task_type, TOOLS)
            if det:
                names = set(names) & set(det)
        except Exception:
            pass
        # Deterministic routing: prefer a stable chain for common goal types.
        try:
            from services.toolchain_graph import deterministic_toolchain_route

            route = deterministic_toolchain_route(goal or "")
            allowed = set(route.get("allowed_tools") or [])
            if allowed:
                names = (names & allowed) | {"reason", "read_file", "list_dir", "search_memories", "save_note"}
        except Exception:
            pass
        # Visibility cap (default 15) when routing narrows by intent.
        try:
            cap = int(cfg.get("tool_visibility_cap", 15) or 15)
        except (TypeError, ValueError):
            cap = 15
        cap = max(8, min(30, cap))
        if cfg.get("tool_routing_enabled", True) and len(names) > cap:
            try:
                from layla.tools.registry import tool_recommend

                rec = tool_recommend(goal)
                top_n = max(1, cap - 5)
                top = [
                    r.get("tool")
                    for r in (rec.get("recommendations") or [])[: max(15, top_n + 6)]
                    if r.get("tool") in names
                ]
                names = set(top[:top_n]) | {"reason", "read_file", "list_dir", "search_memories", "save_note"}
            except Exception:
                top_n = max(1, cap - 5)
                names = set(list(names)[:top_n]) | {"reason", "read_file", "list_dir", "search_memories", "save_note"}
        return frozenset(names)
    except Exception:
        return _VALID_TOOLS

# ÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶Ã
# Auto file probe (planning layer only)
# ÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶Ã
MAX_SAFE_READ_BYTES = 250 * 1024  # planning signal only
LARGE_FILE_HINT_LINES = 2000      # planning signal only


def _probe_store(state: dict) -> dict:
    cm = state.setdefault("context_memory", {})
    cm.setdefault("file_probed", {})
    cm.setdefault("file_probe_hints", {})
    return cm


def _maybe_preprobe_file(state: dict, path: str) -> dict | None:
    """
    Run file_info once per path (no approval, does not count toward tool_calls).
    Records as an internal step: action=pre_read_probe.
    """
    if not path:
        return None
    cm = _probe_store(state)
    probed = cm.get("file_probed") or {}
    if path in probed:
        return probed.get(path)
    try:
        result = TOOLS["file_info"]["fn"](path=path)
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    cm["file_probed"][path] = result
    state.setdefault("steps", []).append({"action": "pre_read_probe", "path": path, "result": result})
    try:
        runtime_safety.log_execution("file_info", {"path": path, "tag": "pre_read_probe"})
    except Exception as _exc:
        logger.debug("agent_loop:L1876: %s", _exc, exc_info=False)
    return result


def _apply_probe_guidance(state: dict, intent: str, path: str, probe: dict | None) -> bool:
    """
    Soft planning gate before file operations.
    Returns True if the caller should proceed with the original tool; False to skip it for this loop.
    """
    if not isinstance(probe, dict) or not probe.get("ok"):
        return True
    is_text = probe.get("is_text")
    size = probe.get("size_bytes") or 0
    lines_sample = probe.get("line_count_sample")

    # Hard avoidance only for clearly binary files (avoid unsafe/bad UX).
    if is_text is False and intent in ("read_file", "apply_patch", "replace_in_file"):
        state.setdefault("steps", []).append({
            "action": intent,
            "result": {
                "ok": False,
                "reason": "binary_file",
                "message": "Probe indicates this file is binary; avoiding read/patch. Prefer grep_code on text sources or use a specialized extractor.",
            },
        })
        return False

    hints = []
    if isinstance(size, int) and size > MAX_SAFE_READ_BYTES:
        hints.append(f"Large file ({size} bytes): prefer grep_code first; if you must read, read narrowly and avoid dumping whole file.")
    if isinstance(lines_sample, int) and lines_sample >= LARGE_FILE_HINT_LINES:
        hints.append(f"Many lines (sample >= {lines_sample}): prefer grep-first; consider chunking strategy.")
    if hints:
        cm = _probe_store(state)
        cm["file_probe_hints"][path] = hints
    return True

# Tools that get a self-verification step (progress_made / retry_suggested)
_VERIFY_TOOLS = frozenset({
    "run_python", "apply_patch", "replace_in_file", "shell", "write_file",
    "git_status", "git_diff", "git_log", "git_branch",
})


def _verify_tool_progress(
    objective: str,
    steps_text: str,
    tool_name: str,
    result: dict,
) -> dict | None:
    """
    LLM evaluates whether the tool step moved the objective closer.
    Returns {"progress_made": bool, "retry_suggested": bool} or None.
    """
    obj_short = (objective or "")[:400]
    res_short = str(result)[:500]
    prompt = (
        f"Objective: {obj_short}\n\nLast tool: {tool_name}\nResult: {res_short}\n\n"
        "Did this step move the objective closer? Output exactly one JSON line, no other text. "
        'Format: {"progress_made": true or false, "retry_suggested": true or false}. '
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


def _observe_environment(tool_name: str, result: dict, workspace: str) -> bool:
    """
    Lightweight environment checks after a tool run. Returns True if observed state
    aligns with success (e.g. file changed, artifacts exist, command side-effects).
    """
    if not isinstance(result, dict) or not result.get("ok"):
        return False
    try:
        workspace_path = Path(workspace or ".").resolve()
        if tool_name == "run_python":
            # Tests / scripts: returncode 0; optional stdout suggests execution
            rc = result.get("returncode", -1)
            return rc == 0
        if tool_name == "apply_patch":
            # Patch applied: target path exists
            p = result.get("path") or result.get("original_path")
            if not p:
                return True
            path = Path(p)
            if not path.is_absolute():
                path = workspace_path / path
            return path.exists()
        if tool_name == "shell":
            # Command side-effect: returncode 0
            return result.get("returncode", -1) == 0
        if tool_name == "write_file":
            # File written: path exists and non-empty
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
            # Git: ok and we got output (or at least ok)
            return True
    except Exception as e:
        logger.debug("observe_environment failed: %s", e)
        return False
    return True


def _classify_failure_and_recovery(state: dict) -> None:
    """North Star â¬Âº8: delegate to failure_recovery module."""
    from services.failure_recovery import classify_failure_and_recovery
    classify_failure_and_recovery(state)


def _format_recovery_hint_for_prompt(recovery_hint: dict) -> str:
    """Stringify structured recovery hint for injection into decision prompt."""
    from services.failure_recovery import format_recovery_hint_for_prompt
    return format_recovery_hint_for_prompt(recovery_hint)


def _run_git_auto_commit(tool_name: str, result: dict, path: str, workspace: str) -> None:
    """
    After write_file or apply_patch succeeds, optionally auto-commit.
    Config: git_auto_commit. Stores last commit for /undo.
    """
    try:
        cfg = runtime_safety.load_config()
        if not cfg.get("git_auto_commit", False):
            return
        if not result.get("ok") or not workspace:
            return
        repo = str(Path(workspace).expanduser().resolve())
        # Resolve path relative to repo for git add
        p = Path(path) if path else None
        if p and not p.is_absolute():
            add_path = str(p)
        elif p:
            try:
                add_path = str(p.relative_to(repo))
            except ValueError:
                add_path = "."
        else:
            add_path = "."
        add_res = TOOLS["git_add"]["fn"](repo=repo, path=add_path)
        if not add_res.get("ok"):
            logger.debug("git_auto_commit: git_add failed: %s", add_res.get("output"))
            return
        msg = "fix: apply changes from Layla"
        commit_res = TOOLS["git_commit"]["fn"](repo=repo, message=msg, add_all=False)
        if not commit_res.get("ok"):
            logger.debug("git_auto_commit: git_commit failed: %s", commit_res.get("output"))
            return
        # Get new commit hash
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            from shared_state import set_last_layla_commit
            set_last_layla_commit(repo, r.stdout.strip())
    except Exception as e:
        logger.debug("git_auto_commit failed: %s", e)


def _run_auto_lint_test_fix(state: dict, tool_name: str, result: dict, path: str, workspace: str) -> str | None:
    """
    Post-write hook: run code_lint (and optionally run_tests) on changed path.
    If issues found, return hint string to inject into goal for retry. Cap at 3 iterations.
    """
    try:
        cfg = runtime_safety.load_config()
        if not cfg.get("auto_lint_test_fix", False):
            return None
        iters = state.get("lint_test_fix_iterations", 0)
        if iters >= 3:
            return None
        if not path or not workspace:
            return None
        state["lint_test_fix_iterations"] = iters + 1
        lint_result = TOOLS["code_lint"]["fn"](path=path, fix=False)
        if not isinstance(lint_result, dict) or not lint_result.get("ok"):
            return None
        violations = lint_result.get("violations", 0) or len(lint_result.get("details", []))
        if violations > 0 and runtime_safety.effective_auto_lint_test_fix_ruff_fix(cfg, workspace):
            try:
                TOOLS["code_lint"]["fn"](path=path, fix=True)
            except Exception as e:
                logger.debug("auto_lint ruff --fix: %s", e)
            lint_result = TOOLS["code_lint"]["fn"](path=path, fix=False)
            if not isinstance(lint_result, dict) or not lint_result.get("ok"):
                return None
            violations = lint_result.get("violations", 0) or len(lint_result.get("details", []))
        if violations > 0:
            details = lint_result.get("details", [])[:5]
            lines = [f"- {d.get('file','')}:{d.get('line','')} {d.get('code','')}: {d.get('message','')}" for d in details if isinstance(d, dict)]
            hint = f"[Lint found {violations} violation(s). Fix these and retry:\n" + "\n".join(lines) + "]"
            return hint
        if cfg.get("auto_lint_test_fix_run_tests", False):
            test_result = TOOLS["run_tests"]["fn"](cwd=workspace, pattern="", extra_args="-x -q", timeout_s=60)
            if isinstance(test_result, dict) and not test_result.get("ok") and test_result.get("failed", 0) > 0:
                out = (test_result.get("output") or "")[:500]
                return f"[Tests failed. Fix and retry:\n{out}]"
    except Exception as e:
        logger.debug("auto_lint_test_fix failed: %s", e)
    return None


def _edit_tool_lint_path(intent: str, args: dict | None, workspace: str) -> str:
    """Filesystem path hint for auto_lint_test_fix after mutating tools."""
    ws = (workspace or "").strip()
    a = args if isinstance(args, dict) else {}
    if intent in ("code_format", "notebook_edit_cell"):
        return str(a.get("path") or "").strip() or ws
    if intent == "replace_in_file":
        return str(a.get("path") or "").strip()
    if intent in ("search_replace", "rename_symbol"):
        return ws
    return ""


def _run_edit_postchecks(
    state: dict,
    intent: str,
    raw_result: object,
    *,
    workspace: str,
    cfg: dict,
    re_execute: Callable[[], object] | None = None,
) -> tuple[object, bool, str]:
    """Validate tool output, deterministic verification, optional single retry (same pattern as mutating tools)."""
    _res = _maybe_validate_tool_output(intent, raw_result)
    _res, ok, reason = _apply_deterministic_tool_verification(intent, _res, workspace=workspace, cfg=cfg)
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
            _res = _maybe_validate_tool_output(intent, raw2)
            _res, ok, reason = _apply_deterministic_tool_verification(intent, _res, workspace=workspace, cfg=cfg)
            if isinstance(_res, dict):
                _res["_deterministic_retry"] = True
                _res["_deterministic_retry_reason"] = reason
    return _res, ok, reason


def _run_verification_after_tool(state: dict, tool_name: str, result: dict, workspace: str = "") -> None:
    """If tool is verifiable and succeeded, run verification and environment observation; update state."""
    if tool_name not in _VERIFY_TOOLS or not (isinstance(result, dict) and result.get("ok")):
        return
    # Deterministic verification already ran at tool capture time; if it downgraded okÃÃ¥ÃFalse,
    # this function won't run. Keep LLM verification optional to avoid small-model noise.
    objective = state.get("objective") or state.get("original_goal") or ""
    steps_text = _format_steps(state.get("steps") or [])
    try:
        cfg_v = runtime_safety.load_config()
        llm_verify = bool(cfg_v.get("llm_tool_verification_enabled", True))
    except Exception:
        llm_verify = True
    ver = _verify_tool_progress(objective, steps_text, tool_name, result) if llm_verify else None
    if ver is not None:
        state["last_verification"] = ver
        if not ver.get("progress_made", True):
            state["consecutive_no_progress"] = state.get("consecutive_no_progress", 0) + 1
        else:
            state["consecutive_no_progress"] = 0

    # Post-verification observation: real system state
    state["environment_aligned"] = _observe_environment(tool_name, result, workspace)
    # If verification said progress but environment does not align, treat as no progress
    if ver and ver.get("progress_made") and not state.get("environment_aligned", True):
        state["consecutive_no_progress"] = state.get("consecutive_no_progress", 0) + 1
    # North Star â¬Âº8: classify failure and set recovery hint when no progress
    if state.get("consecutive_no_progress", 0) > 0:
        _classify_failure_and_recovery(state)


def _llm_decision(
    goal: str,
    state: dict,
    context: str,
    active_aspect: dict,
    show_thinking: bool,
    conversation_history: list,
) -> dict | None:
    """
    Ask the model for a structured decision: action (tool|reason), tool name, objective_complete.
    Returns parsed dict or None to fall back to classify_intent.
    """
    steps_text = _format_steps(state.get("steps") or [])
    objective = (state.get("objective") or goal).strip()
    steps_summary = str(state.get("steps_summary") or "").strip()
    if steps_summary:
        prompt_context = f"Objective: {objective[:500]}\n\n{steps_summary[:1200]}\n\n"
        if steps_text:
            prompt_context += f"Recent tool results (uncompressed tail):\n{steps_text[:900]}\n\n"
    elif steps_text:
        prompt_context = f"Objective: {objective[:500]}\n\nTool results so far:\n{steps_text[:1200]}\n\n"
    else:
        prompt_context = f"Objective: {objective[:800]}\n\n"
    sub_goals = state.get("sub_goals") or []
    if sub_goals:
        prompt_context += "Sub-objectives (guide tool choice): " + "; ".join(sub_goals[:3]) + "\n\n"

    # Cognitive workspace: chosen approach from multi-strategy deliberation
    cw = state.get("cognitive_workspace") or {}
    if cw.get("strategy_hint"):
        prompt_context += f"Chosen approach ({cw.get('chosen_name', '')}): {cw['strategy_hint']}\n\n"

    # File probe awareness (planning-only): surface hints without forcing a hard stop.
    try:
        cm = state.get("context_memory") or {}
        hints = cm.get("file_probe_hints") or {}
        if hints:
            lines = []
            for p, hs in list(hints.items())[:3]:
                if isinstance(hs, list) and hs:
                    lines.append(f"- {p}: " + " ".join(str(x)[:160] for x in hs[:2]))
            if lines:
                prompt_context += "File probe hints:\n" + "\n".join(lines) + "\n\n"
    except Exception as _exc:
        logger.debug("agent_loop:L2159: %s", _exc, exc_info=False)

    try:
        from services.intent_routing_hints import tool_routing_prompt_hints

        _route_goal = (state.get("original_goal") or goal or "").strip()
        _rh = tool_routing_prompt_hints(_route_goal)
        if _rh:
            prompt_context += _rh
    except Exception as _exc:
        logger.debug("agent_loop:L2169: %s", _exc, exc_info=False)

    aspect_block = ""
    if show_thinking:
        try:
            aspects = orchestrator._load_aspects()
            roster = getattr(orchestrator, "_DELIBERATION_ROSTER", ["morrigan", "nyx", "echo"])
            for aid in roster[:3]:
                a = next((x for x in aspects if x.get("id") == aid), None)
                if a and aid != active_aspect.get("id"):
                    name = a.get("name", aid)
                    role = (a.get("role") or a.get("voice") or "")[:60]
                    aspect_block += f"{name}: {role}\n"
            if aspect_block:
                aspect_block = "Aspects may suggest a tool; unify to one decision.\n" + aspect_block + "\n"
        except Exception as _exc:
            logger.debug("agent_loop:L2185: %s", _exc, exc_info=False)

    bias = orchestrator.get_decision_bias(active_aspect)
    bias_hint = ""
    if bias:
        try:
            bias_hint = orchestrator.decision_bias_prompt_extension(bias)  # richer, concrete nudges
        except Exception:
            bias_hint = f"Decision bias: {', '.join(bias)}. Prefer tools and approach that match.\n"

    # Layla v3: observation mode (trial phase). In nascent phase, bias toward answering/learning
    # unless the operator explicitly asked for action.
    observation_hint = ""
    try:
        cfg_obs = runtime_safety.load_config()
        if cfg_obs.get("observation_mode_enabled", True):
            from services.maturity_engine import get_state as _get_maturity_state

            ms = _get_maturity_state()
            if ms.phase == "nascent":
                _goal_l = (goal or "").lower()
                explicit_action = any(
                    kw in _goal_l
                    for kw in (
                        "write ",
                        "edit ",
                        "modify ",
                        "apply patch",
                        "replace_in_file",
                        "run ",
                        "execute ",
                        "install ",
                        "delete ",
                        "remove ",
                        "create file",
                        "add file",
                        "commit",
                        "push",
                    )
                )
                if not explicit_action:
                    observation_hint = (
                        "Observation mode (nascent): prefer action=\"reason\" (explain, ask clarifiers, learn). "
                        "Choose action=\"tool\" only if explicitly requested or necessary to answer.\n"
                    )
    except Exception as _exc:
        logger.debug("agent_loop: observation_hint failed: %s", _exc, exc_info=False)

    route_hint = ""
    try:
        rd = state.get("route_decision") if isinstance(state, dict) else None
        hints = (rd or {}).get("routing_hints") if isinstance(rd, dict) else None
        if isinstance(hints, list) and hints:
            route_hint = "Routing hints:\n- " + "\n- ".join(str(x)[:220] for x in hints[:4]) + "\n"
    except Exception as _exc:
        logger.debug("agent_loop: route_hint failed: %s", _exc, exc_info=False)

    no_progress_hint = ""
    try:
        from services.tool_loop_detection import consume_prompt_hint

        _tlh = consume_prompt_hint(state)
        if _tlh:
            no_progress_hint += f"[Loop guard] {_tlh} "
    except Exception as _exc:
        logger.debug("agent_loop:L2200: %s", _exc, exc_info=False)
    last_ver = state.get("last_verification")
    if last_ver and not last_ver.get("progress_made") and last_ver.get("retry_suggested"):
        no_progress_hint += "Last tool step did not make progress; consider a different approach or reply (reason). "
    if state.get("environment_aligned") is False:
        no_progress_hint += "Environment check did not confirm success; consider different approach or reply (reason). "
    # North Star â¬Âº8: failure awareness (structured hint stringified here)
    rh = state.get("recovery_hint")
    if rh and isinstance(rh, dict):
        no_progress_hint += _format_recovery_hint_for_prompt(rh)
    consecutive = state.get("consecutive_no_progress", 0)
    if consecutive >= 2:
        shift_count = state.get("strategy_shift_count", 0)
        if shift_count == 1:
            last_tool = state.get("last_tool_used") or "unknown"
            no_progress_hint += (
                f"Strategy shift: try a different class of action. Avoid repeating the same tool (last was {last_tool}). "
                "Prefer high-impact inspection tools: read_file, grep_code, git_diff. "
            )
        else:
            no_progress_hint += "Several steps made no progress; consider replying (reason) to explain or suggest next steps. "

    reframe_candidate = (
        consecutive >= 2
        and state.get("strategy_shift_count", 0) >= 2
        and not state.get("objective_complete")
    )
    reframe_instruction = ""
    if reframe_candidate:
        reframe_instruction = (
            "Alternatively propose a revised objective to solve the right problem: "
            'add "revised_objective": "one clear sentence" to your JSON. '
            "Prefer reframing toward higher-impact, achievable objective. "
            "If you reframe, we will continue with the new objective. "
        )

    priority_context = ""
    prev_priority = state.get("priority_level")
    prev_risk = state.get("risk_estimate")
    if prev_priority or prev_risk:
        priority_context = f"Previous step priority: {prev_priority or 'unknown'}. "
        if prev_priority == "low":
            priority_context += "Avoid low-impact retries; prefer higher-impact pivots or reply (reason). "
        else:
            priority_context += "Prefer high-impact pivots. "
        if prev_risk and "high" in str(prev_risk).lower():
            priority_context += "Risk was high; bias toward safer paths (read_file, list_dir, grep_code, git_*). "
        elif prev_priority:
            priority_context += "When risk is high prefer safer paths (read, inspect). "

    cfg_pre = runtime_safety.load_config()
    mcp_tool_hint = ""
    if cfg_pre.get("mcp_client_enabled") and cfg_pre.get("mcp_inject_tool_summary_in_decisions"):
        try:
            from services.mcp_client import get_cached_mcp_tool_summary_for_prompt

            mcp_tool_hint = get_cached_mcp_tool_summary_for_prompt(cfg_pre)
        except Exception:
            mcp_tool_hint = ""
    if mcp_tool_hint:
        prompt_context = prompt_context + mcp_tool_hint + "\n\n"

    valid_tools = _get_tools_for_goal(goal, context=context, workspace_root=state.get("workspace_root") or "", state=state)
    # Decision policy caps: enforce safety/verify gates and tool restrictions at the prompt boundary.
    try:
        if cfg_pre.get("decision_policy_enabled", True):
            from services.decision_policy import (
                apply_caps_to_valid_tools as _apply_caps_to_valid_tools,
            )
            from services.decision_policy import (
                build_policy_caps as _build_policy_caps,
            )
            _cid = (state.get("conversation_id") or "").strip() or "unknown"
            _caps = _build_policy_caps(state, cfg_pre, conversation_id=_cid)
            state["policy_caps"] = _caps.to_trace_dict()
            valid_tools = _apply_caps_to_valid_tools(valid_tools, _caps)
    except Exception as _dp_exc:
        logger.debug("decision_policy caps skipped: %s", _dp_exc)
    from services.prompt_builder import build_decision_tool_hints

    tools_list, _edit_hint_pb = build_decision_tool_hints(valid_tools, goal)
    think_trace_hint = ""
    if show_thinking:
        think_trace_hint = (
            'For action \"think\", put the plan in \"thought\" as 2-4 numbered lines (\"1.\" \"2.\" ÃÃÂª), '
            "one short sentence each ÃÃÃ¶ restate aim, outline the next move, note gaps/risks (ChatGPT-style step trace).\n"
        )
    _edit_hint = _edit_hint_pb
    tool_first_hint = ""
    if cfg_pre.get("tool_first_enforcement_enabled") and not observation_hint:
        if not state.get("tool_attempted_this_turn") and not state.get("objective_complete"):
            tool_first_hint = (
                "Tool-first policy: for substantive questions about code, files, or the workspace, prefer action=\"tool\" "
                "with a read-only inspection tool before action=\"reason\".\n"
            )
    pipeline_debug_hint = ""
    if str(state.get("pipeline_stage") or "") == "DEBUG" and cfg_pre.get("pipeline_enforcement_enabled", True):
        pipeline_debug_hint = (
            "Pipeline DEBUG: stagnation recovery ÃÃÃ¶ narrow the next tool (different path or verify with read_file/grep) "
            "before repeating writes or shell.\n"
        )
    prompt = (
        f"{aspect_block}"
        f"{bias_hint}"
        f"{observation_hint}"
        f"{route_hint}"
        f"{tool_first_hint}"
        f"{pipeline_debug_hint}"
        f"{prompt_context}"
        f"{priority_context}"
        f"{no_progress_hint}"
        f"{reframe_instruction}"
        f"{think_trace_hint}"
        f"{_edit_hint}"
        "Choose exactly one: reply (reason), internal plan (think), or run one tool. "
        f"Available actions/tools: {tools_list}. "
        "Output exactly one JSON line, no other text. "
        'Format: {"action":"tool","tool":"read_file","priority_level":"high"} or {"action":"think","thought":"..."} or {"action":"reason","objective_complete":true}. '
        'Examples: {"action":"reason","priority_level":"medium","objective_complete":true} '
        '{"action":"tool","tool":"read_file","args":{"path":"agent/main.py"},"priority_level":"high","objective_complete":false} '
        '{"action":"think","thought":"Suspect the failure is in router mounting; inspect main.py includes.","priority_level":"medium"}. '
        "Include priority_level: \"low\" or \"medium\" or \"high\" for the chosen action. "
        "Optionally impact_estimate, effort_estimate, risk_estimate (brief). "
        "Use objective_complete true only when you have enough to answer.\n"
    )
    try:
        cfg_tmp = runtime_safety.load_config()
        if cfg_tmp.get("decision_few_shot_enabled", True):
            prompt += (
                "Few-shot examples (copy the shape, adapt tool/args):\n"
                '{"action":"reason","thought":"I have enough context to answer.","priority_level":"medium","objective_complete":true}\n'
                '{"action":"tool","tool":"read_file","args":{"path":"agent/main.py"},"priority_level":"high","objective_complete":false}\n'
                '{"action":"tool","tool":"grep_code","args":{"pattern":"def _llm_decision","path":"agent"},"priority_level":"medium","objective_complete":false}\n'
                '{"action":"reason","thought":"Operator asked about Layla (capabilities/identity). Reply directly without tools.","priority_level":"medium","objective_complete":true}\n'
            )
    except Exception:
        pass
    prev_override = None
    try:
        cfg = runtime_safety.load_config()
        # Optionally route decision JSON generation to a dedicated structured-output model.
        from services.llm_gateway import get_model_override, set_model_override

        try:
            prev_override = get_model_override()
            if (cfg.get("decision_model") or "").strip():
                set_model_override("decision")
        except Exception:
            pass

        max_tok = 120 if reframe_candidate else (220 if show_thinking else 80)
        use_instructor = cfg.get("use_instructor_for_decisions", True)
        structured_on = bool(cfg.get("structured_generation_enabled", True))
        # Optional outlines + llama-cpp (wheels on 3.11ÃÃÃ´3.12); no-op if package missing
        if structured_on and not (cfg.get("llama_server_url") or "").strip():
            try:
                from services.llm_gateway import _get_llm
                from services.structured_gen import run_outlines_agent_decision

                _llm_local = _get_llm()
                if _llm_local is not None:
                    _od = run_outlines_agent_decision(
                        _llm_local,
                        prompt,
                        max_tokens=max_tok,
                        temperature=0.1,
                        valid_tools=valid_tools,
                    )
                    if _od is not None:
                        return _od
            except Exception as _exc:
                logger.debug("agent_loop: structured_gen outlines skipped: %s", _exc, exc_info=False)
        # Try instructor (grammar-constrained JSON) when local Llama available
        if use_instructor:
            for _attempt in range(2):  # 1 retry before falling back
                try:
                    import instructor

                    from decision_schema import AgentDecision
                    if not (cfg.get("llama_server_url") or "").strip():
                        from services.llm_gateway import _get_llm
                        llm = _get_llm()
                        if llm is not None:
                            create = instructor.patch(
                                create=llm.create_chat_completion_openai_v1,
                                mode=instructor.Mode.JSON_SCHEMA,
                            )
                            decision_obj = create(
                                messages=[{"role": "user", "content": prompt}],
                                max_tokens=max_tok,
                                temperature=0.1,
                                response_model=AgentDecision,
                            )
                            d = decision_obj.model_dump()
                            action = (d.get("action") or "reason").lower()
                            if action not in ("tool", "reason", "think"):
                                action = "reason"
                            tool = (d.get("tool") or "").strip() or None
                            if action in ("think",):
                                tool = None
                            if action == "tool" and tool and tool not in valid_tools:
                                tool = None
                            d["action"] = action
                            d["tool"] = tool
                            return d
                except Exception as e:
                    logger.debug("instructor decision attempt failed: %s", e)
        # Fallback: plain completion + parse
        retry_prompt_suffix = " Output only a single JSON line, no other text or commentary.\n"
        for attempt in range(2):
            out = run_completion(
                prompt + (retry_prompt_suffix if attempt > 0 else ""),
                max_tokens=max_tok,
                temperature=0.1,
                stream=False,
            )
            if isinstance(out, dict):
                text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or (out.get("choices") or [{}])[0].get("text") or ""
            else:
                text = ""
            text = (text or "").strip()
            decision = _parse_decision(text, valid_tools)
            if decision is not None:
                return decision
        return None
    except Exception as e:
        logger.debug("llm_decision parse failed: %s", e)
        return None
    finally:
        try:
            from services.llm_gateway import set_model_override

            set_model_override(prev_override)
        except Exception:
            pass


def classify_intent(goal: str) -> str:
    """Lightweight heuristic tool intent for tests and legacy call sites (no external module)."""
    g = (goal or "").strip().lower()
    if not g:
        return "reason"
    if "list checkpoints" in g:
        return "list_file_checkpoints"
    if "restore checkpoint" in g or g.startswith("revert file"):
        return "restore_file_checkpoint"
    if "import chats" in g and "backup" in g:
        return "ingest_chat_export_to_knowledge"
    if "search past learnings" in g:
        return "memory_elasticsearch_search"
    if "git status" in g:
        return "git_status"
    if "git diff" in g:
        return "git_diff"
    if "git log" in g:
        return "git_log"
    if "current branch" in g:
        return "git_branch"
    if "list dir" in g or "what files are in" in g:
        return "list_dir"
    if "grep for" in g or "search code for" in g:
        return "grep_code"
    if "create file" in g or "save file as" in g:
        return "write_file"
    if g.startswith("read file") or g.startswith("show file") or g.startswith("contents of"):
        return "read_file"
    if "explain" in g or "what do you think" in g:
        return "reason"
    return "reason"


def _extract_path(goal: str) -> str:
    """Pull a file/dir path from the goal text (very simple heuristic)."""
    words = goal.split()
    for w in words:
        if (":" in w or "/" in w or "\\" in w) and not w.startswith("http"):
            return w.strip("\"',")
    return ""


def _extract_file_and_content(goal: str):
    if "with content" in goal:
        parts = goal.split("with content", 1)
        left = parts[0]
        content = parts[1].strip()
        words = left.split()
        for w in words:
            ww = w.strip("\"',")
            if not ww or ww.lower().startswith("http"):
                continue
            # Support Windows paths (C:\...), UNC (\\server\...), and POSIX absolute paths (/tmp/x).
            if ":" in ww or "\\" in ww or ww.startswith("/"):
                return ww, content
    return None, None


def _extract_shell_argv(goal: str):
    """Very simple: find a quoted command or treat the last part as the command."""
    import shlex
    try:
        # Try to find a quoted command block
        for delim in ('"', "'"):
            if delim in goal:
                inner = goal.split(delim)[1]
                return shlex.split(inner)
    except Exception as _exc:
        logger.debug("agent_loop:L2413: %s", _exc, exc_info=False)
    # Fallback: strip common preambles
    for prefix in ("run", "execute", "install", "please run", "please execute"):
        if goal.lower().startswith(prefix):
            remainder = goal[len(prefix):].strip()
            try:
                return shlex.split(remainder)
            except Exception:
                return remainder.split()
    return goal.split()


def _autonomous_run_serialize_lock(workspace_root: str):
    """Serialize agent flights: global lock by default; optional per-workspace when configured."""
    if runtime_safety.load_config().get("llm_serialize_per_workspace"):
        from services.llm_gateway import _resolve_workspace_lock_key, get_agent_serialize_lock

        return get_agent_serialize_lock(_resolve_workspace_lock_key(workspace_root))
    return llm_serialize_lock


def autonomous_run(
    goal: str,
    context: str = "",
    workspace_root: str = "",
    allow_write: bool = False,
    allow_run: bool = False,
    conversation_history: list = None,
    aspect_id: str = "",
    show_thinking: bool = False,
    stream_final: bool = False,
    ux_state_queue: queue.Queue | None = None,
    research_mode: bool = False,
    plan_depth: int = 0,
    model_override: str | None = None,
    reasoning_effort: str | None = None,
    priority: int = PRIORITY_AGENT,
    persona_focus: str = "",
    conversation_id: str = "",
    cognition_workspace_roots: list[str] | None = None,
    client_abort_event: threading.Event | None = None,
    background_progress_callback: Callable[[dict], None] | None = None,
    active_plan_id: str = "",
    plan_approved: bool = False,
    fabrication_assist_runner_request: str = "",
    resume_execution_state: dict | None = None,
    coordinator_trace: dict | None = None,
    *,
    engineering_pipeline_mode: str = "chat",
    clarification_reply: str = "",
    skip_engineering_pipeline: bool = False,
    context_files: list[str] | None = None,
) -> dict:
    # Prompt optimizer: enhance user goal before processing (graceful; never blocks)
    # Preserve the original user-authored goal text so downstream code can refer to
    # the canonical words even when the optimizer rewrites the prompt.
    goal_original = goal
    goal_optimized: str | None = None
    try:
        from services.prompt_optimizer import optimize as _opt_goal
        _cfg_now = runtime_safety.load_config() if hasattr(runtime_safety, "load_config") else {}
        if _cfg_now.get("prompt_optimizer_enabled", True):
            _opt_result = _opt_goal(
                goal,
                context={
                    "aspect": aspect_id or "",
                    "workspace": str(workspace_root or ""),
                },
            )
            if _opt_result.get("changed") and _opt_result.get("optimized"):
                logger.debug(
                    "prompt_optimizer: [%s] goal rewritten (tier=%d)",
                    _opt_result.get("intent", "?"), _opt_result.get("tier", 0),
                )
                goal_optimized = _opt_result["optimized"]
                goal = _opt_result["optimized"]
    except Exception as _opt_e:
        logger.debug("prompt_optimizer inject failed: %s", _opt_e)

    # Phase B Fix 2: publish canonical pre/post-optimizer goal text via contextvars
    # so downstream code (state, /health/trace, memory writes) can refer to the
    # text the user actually authored. Tokens are reset in the finally below.
    _goal_orig_token = _goal_original_var.set(goal_original or "")
    _goal_opt_token = _goal_optimized_var.set(goal_optimized or "")

    # Phase 4.3: set per-task context vars for structured log isolation
    try:
        import uuid as _uuid
        from services.task_context import reset_task_context, set_task_context
        _tid = conversation_id or str(_uuid.uuid4())[:8]
        _ctx_tokens = set_task_context(
            workspace=str(workspace_root or ""),
            aspect=str(aspect_id or ""),
            task_id=_tid,
        )
    except Exception:
        _ctx_tokens = None
    try:
        with schedule_slot(priority=priority):
            with _autonomous_run_serialize_lock(workspace_root):
                return _autonomous_run_impl(
                    goal, context, workspace_root, allow_write, allow_run,
                    conversation_history, aspect_id, show_thinking, stream_final,
                    ux_state_queue, research_mode, plan_depth, model_override, reasoning_effort, priority,
                    persona_focus,
                    conversation_id,
                    cognition_workspace_roots,
                    client_abort_event,
                    background_progress_callback,
                    active_plan_id,
                    plan_approved,
                    fabrication_assist_runner_request=fabrication_assist_runner_request,
                    resume_execution_state=resume_execution_state,
                    coordinator_trace=coordinator_trace,
                    engineering_pipeline_mode=engineering_pipeline_mode,
                    clarification_reply=clarification_reply,
                    skip_engineering_pipeline=skip_engineering_pipeline,
                    context_files=context_files,
                )
    except RuntimeError as e:
        if "system_busy" in str(e):
            active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
            return {
                "status": "system_busy",
                "steps": [],
                "aspect": active_aspect.get("id", "layla"),
                "aspect_name": active_aspect.get("name", "Layla"),
                "refused": False,
                "refusal_reason": "",
                "ux_states": [],
                "memory_influenced": [],
                "reasoning_mode": "light",
            }
        raise
    finally:
        if _ctx_tokens is not None:
            try:
                reset_task_context(_ctx_tokens)
            except Exception:
                pass
        try:
            _goal_original_var.reset(_goal_orig_token)
            _goal_optimized_var.reset(_goal_opt_token)
        except Exception:
            pass


def _autonomous_run_impl(
    goal: str,
    context: str,
    workspace_root: str,
    allow_write: bool,
    allow_run: bool,
    conversation_history: list,
    aspect_id: str,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue: queue.Queue | None,
    research_mode: bool,
    plan_depth: int = 0,
    model_override: str | None = None,
    reasoning_effort: str | None = None,
    priority: int = PRIORITY_AGENT,
    persona_focus: str = "",
    conversation_id: str = "",
    cognition_workspace_roots: list[str] | None = None,
    client_abort_event: threading.Event | None = None,
    background_progress_callback: Callable[[dict], None] | None = None,
    active_plan_id: str = "",
    plan_approved: bool = False,
    fabrication_assist_runner_request: str = "",
    resume_execution_state: dict | None = None,
    coordinator_trace: dict | None = None,
    *,
    engineering_pipeline_mode: str = "chat",
    clarification_reply: str = "",
    skip_engineering_pipeline: bool = False,
    context_files: list[str] | None = None,
) -> dict:
    from services.llm_gateway import set_model_override, set_reasoning_effort
    set_model_override(model_override)
    if not model_override:
        try:
            import runtime_safety
            _cfg_route = runtime_safety.load_config()
            if _cfg_route.get("tool_routing_enabled", True):
                from services.model_router import classify_task_for_routing, is_routing_enabled
                if is_routing_enabled():
                    set_model_override(classify_task_for_routing(goal, context or "", _cfg_route))
        except Exception as _exc:
            logger.debug("agent_loop:L2536: %s", _exc, exc_info=False)
    # Phase 4.1: record CoT split decision for cost telemetry
    try:
        from services.model_router import _record_cot_phase, split_cot_models
        _cot = split_cot_models()
        if _cot.get("split_enabled"):
            _record_cot_phase("reasoning", _cot.get("reasoning_model"), estimated_tokens=800)
            _record_cot_phase("implementation", _cot.get("implementation_model"), estimated_tokens=1800)
            logger.debug(
                "cot_split: reasoning=%s impl=%s",
                _cot.get("reasoning_model"), _cot.get("implementation_model"),
            )
    except Exception:
        pass
    set_reasoning_effort(reasoning_effort)
    try:
        return _autonomous_run_impl_core(
            goal, context, workspace_root, allow_write, allow_run,
            conversation_history, aspect_id, show_thinking, stream_final,
            ux_state_queue, research_mode, plan_depth, priority,
            persona_focus,
            conversation_id,
            cognition_workspace_roots,
            client_abort_event,
            background_progress_callback,
            active_plan_id,
            plan_approved,
            fabrication_assist_runner_request=fabrication_assist_runner_request,
            resume_execution_state=resume_execution_state,
            coordinator_trace=coordinator_trace,
            engineering_pipeline_mode=engineering_pipeline_mode,
            clarification_reply=clarification_reply,
            skip_engineering_pipeline=skip_engineering_pipeline,
            context_files=context_files,
        )
    finally:
        set_model_override(None)
        set_reasoning_effort(None)


def _autonomous_run_impl_core(
    goal: str,
    context: str,
    workspace_root: str,
    allow_write: bool,
    allow_run: bool,
    conversation_history: list,
    aspect_id: str,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue: queue.Queue | None,
    research_mode: bool,
    plan_depth: int = 0,
    priority: int = PRIORITY_AGENT,
    persona_focus: str = "",
    conversation_id: str = "",
    cognition_workspace_roots: list[str] | None = None,
    client_abort_event: threading.Event | None = None,
    background_progress_callback: Callable[[dict], None] | None = None,
    active_plan_id: str = "",
    plan_approved: bool = False,
    *,
    fabrication_assist_runner_request: str = "",
    resume_execution_state: dict | None = None,
    coordinator_trace: dict | None = None,
    engineering_pipeline_mode: str = "chat",
    clarification_reply: str = "",
    skip_engineering_pipeline: bool = False,
    context_files: list[str] | None = None,
) -> dict:
    # Memory command fast-path: intercept before LLM (no inference cost, deterministic response).
    try:
        from services.memory_commands import detect_and_handle as _mem_cmd_detect
        _mem_result = _mem_cmd_detect(goal, aspect_id=aspect_id or "")
        if _mem_result.is_command:
            _active_asp = orchestrator.select_aspect(goal, force_aspect=aspect_id)
            _go_mc = _goal_original_var.get() or goal
            return {
                "goal": goal,
                "original_goal": _go_mc,
                "goal_original": _go_mc,
                "goal_optimized": _goal_optimized_var.get() or "",
                "objective": goal,
                "objective_complete": True,
                "depth": 0,
                "steps": [{"action": "memory_command", "result": _mem_result.response, "deliberated": False, "aspect": _active_asp.get("id", "layla")}],
                "status": "finished",
                "start_time": time.time(),
                "tool_calls": 0,
                "aspect": _active_asp.get("id", "layla"),
                "aspect_name": _active_asp.get("name", "Layla"),
                "refused": False,
                "refusal_reason": "",
                "last_verification": None,
                "consecutive_no_progress": 0,
                "environment_aligned": None,
                "last_tool_used": None,
                "strategy_shift_count": 0,
                "priority_level": None,
                "impact_estimate": None,
                "effort_estimate": None,
                "risk_estimate": None,
                "ux_states": [],
                "memory_influenced": [],
                "cited_knowledge_sources": [],
                "sub_goals": [],
                "reflection_pending": False,
                "reflection_asked": False,
                "reasoning_mode": "none",
                "memory_command": _mem_result.command,
                "memory_items_affected": _mem_result.items_affected,
            }
    except Exception as _mc_err:
        logger.debug("memory_commands intercept failed: %s", _mc_err)

    # Passive working memory extraction from this turn's message.
    try:
        from services.working_memory import auto_extract_from_message as _wm_extract
        _wm_extract(goal)
    except Exception as _wm_err:
        logger.debug("working_memory extract failed: %s", _wm_err)

    persona_focus_id = (persona_focus or "").strip().lower()
    _run_cid = (conversation_id or "").strip() or "default"
    base_cfg = runtime_safety.load_config()
    cfg = _get_effective_config(base_cfg)
    _prev_reasoning_mode = ""
    try:
        from services.reasoning_classifier import classify_reasoning_need, stabilize_reasoning_mode

        global _last_reasoning_mode
        with _reason_mode_lock:
            _prev_reasoning_mode = _last_reasoning_mode
        reasoning_mode = classify_reasoning_need(goal, context or "", research_mode=research_mode)
        if reasoning_mode == "deep" and (cfg.get("performance_mode") or "").strip().lower() in ("low",):
            reasoning_mode = "light"
        with _reason_mode_lock:
            reasoning_mode = stabilize_reasoning_mode(_prev_reasoning_mode, reasoning_mode)
            _last_reasoning_mode = reasoning_mode
    except Exception:
        reasoning_mode = "light"
    _run_t0 = time.time()

    def _emit_run_telemetry(st: dict, success: bool) -> None:
        try:
            _cfg_t = runtime_safety.load_config()
            if not _cfg_t.get("telemetry_enabled", True):
                return
            from services.telemetry import log_event as _tel
            from services.telemetry import log_model_outcome as _log_mo

            _lat_ms = max(0.0, (time.time() - _run_t0) * 1000.0)
            _model_used = str(_cfg_t.get("model_filename") or "")
            _tel(
                task_type="research" if research_mode else "agent",
                reasoning_mode=str(st.get("reasoning_mode") or "light"),
                model_used=_model_used,
                latency_ms=_lat_ms,
                success=success,
                performance_mode=str(_cfg_t.get("performance_mode") or "auto"),
            )
            # Record model outcome (adaptive routing); uses structured outcome score when available.
            try:
                oe = st.get("outcome_evaluation") if isinstance(st.get("outcome_evaluation"), dict) else {}
                score = oe.get("score") if isinstance(oe, dict) else None
            except Exception:
                score = None
            _log_mo(
                model_used=_model_used,
                task_type="research" if research_mode else "agent",
                success=bool(success),
                score=float(score) if score is not None else None,
                latency_ms=_lat_ms,
            )
        except Exception as _exc:
            logger.debug("agent_loop:L2623: %s", _exc, exc_info=False)
        # Close per-request trace on every exit path.
        try:
            from services.request_tracer import finish_trace as _rt_finish
            _status_str = "ok" if success else "error"
            _st_status = str((st or {}).get("status") or "")
            if _st_status in ("refused", "system_busy"):
                _status_str = _st_status
            _rt_finish(
                _req_trace,
                status=_status_str,
                tool_calls=int((st or {}).get("tool_calls") or 0),
            )
        except Exception:
            pass

    def _overloaded_now() -> bool:
        try:
            return system_overloaded(priority=priority)
        except TypeError:
            # Backward-compatible for tests/monkeypatches that stub zero-arg function.
            return system_overloaded()

    # Gate once at entry only: avoid refusing mid-run when our own LLM/embedder spiked CPU
    if _overloaded_now():
        time.sleep(2.0)
        if _overloaded_now():
            active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
            _aspect_miss = bool(active_aspect.get("_force_aspect_miss")) if isinstance(active_aspect, dict) else False
            _aspect_req = str(active_aspect.get("_force_aspect_requested") or "") if isinstance(active_aspect, dict) else ""
            _emit_run_telemetry({"reasoning_mode": reasoning_mode}, False)
            return {
                "status": "system_busy",
                "steps": [],
                "aspect": active_aspect.get("id", "layla"),
                "aspect_name": active_aspect.get("name", "Layla"),
                "aspect_miss_warning": _aspect_req if _aspect_miss else "",
                "refused": False,
                "refusal_reason": "",
                "ux_states": [],
                "memory_influenced": [],
                "reasoning_mode": reasoning_mode,
            }
    active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
    _aspect_miss = bool(active_aspect.get("_force_aspect_miss")) if isinstance(active_aspect, dict) else False
    _aspect_req = str(active_aspect.get("_force_aspect_requested") or "") if isinstance(active_aspect, dict) else ""
    # Apply aspect reasoning_depth_bias AFTER classification so aspect personality
    # can upgrade or downgrade the classifier result (e.g. Nyx always deep, Eris always light).
    try:
        from services.aspect_behavior import apply_reasoning_depth as _ab_apply_depth
        reasoning_mode = _ab_apply_depth(active_aspect, reasoning_mode)
        with _reason_mode_lock:
            _last_reasoning_mode = reasoning_mode
    except Exception as _ab_err:
        logger.debug("aspect_behavior depth apply failed: %s", _ab_err)
    # Open per-request trace (ContextVar -- safe for concurrent runs).
    _req_trace = None
    try:
        from services.request_tracer import start_trace as _rt_start
        _req_trace = _rt_start(
            goal,
            aspect_id=(active_aspect.get("id") or "") if isinstance(active_aspect, dict) else "",
            reasoning_mode=reasoning_mode,
        )
    except Exception as _rt_err:
        logger.debug("request_tracer start failed: %s", _rt_err)
    if reasoning_mode == "none" and not allow_write and not allow_run and not show_thinking:
        quick = _quick_reply_for_trivial_turn(goal)
        if quick:
            _emit_run_telemetry({"reasoning_mode": reasoning_mode}, True)
            _go_qr = _goal_original_var.get() or goal
            return {
                "goal": goal,
                "original_goal": _go_qr,
                "goal_original": _go_qr,
                "goal_optimized": _goal_optimized_var.get() or "",
                "objective": goal,
                "objective_complete": True,
                "depth": 0,
                "steps": [{"action": "reason", "result": quick, "deliberated": False, "aspect": active_aspect.get("id", "layla")}],
                "status": "finished",
                "start_time": time.time(),
                "tool_calls": 0,
                "aspect": active_aspect.get("id", "layla"),
                "aspect_name": active_aspect.get("name", "Layla"),
                "aspect_miss_warning": _aspect_req if _aspect_miss else "",
                "refused": False,
                "refusal_reason": "",
                "last_verification": None,
                "consecutive_no_progress": 0,
                "environment_aligned": None,
                "last_tool_used": None,
                "strategy_shift_count": 0,
                "priority_level": None,
                "impact_estimate": None,
                "effort_estimate": None,
                "risk_estimate": None,
                "ux_states": [],
                "memory_influenced": [],
                "cited_knowledge_sources": [],
                "sub_goals": [],
                "reflection_pending": False,
                "reflection_asked": False,
                "reasoning_mode": reasoning_mode,
            }
    # Memory attribution: compute semantic recall ONCE here; pass it to _build_system_head
    # so it is not queried twice (eliminates double ChromaDB call per non-streaming turn).
    _packed_ctx_run: dict | None = None
    _precomputed_recall = ""
    if goal and reasoning_mode != "none":
        # Phase 0.3: invalidate stale semantic index when workspace files changed (checked once per call)
        _ws_for_check = (str(workspace_root).strip() if workspace_root else "") or str(cfg.get("sandbox_root") or "")
        if _ws_for_check:
            try:
                from services.workspace_index import invalidate_if_changed
                invalidate_if_changed(_ws_for_check)
            except Exception:
                pass
        try:
            from services.context_builder import build_context

            wr = (str(workspace_root).strip() if workspace_root else "") or str(cfg.get("sandbox_root") or "")
            _packed_ctx_run = build_context(
                goal,
                {
                    "workspace_root": wr,
                    "context_files": list(context_files or []),
                    "reasoning_mode": reasoning_mode,
                    "k_memory": int(cfg.get("semantic_k", 5)),
                    "k_code": int(cfg.get("context_builder_code_k", 5)),
                },
            )
            _precomputed_recall = (_packed_ctx_run.get("memory_recall_text") or "").strip()
        except Exception as _uce:
            logger.debug("context_builder failed: %s", _uce)
            try:
                _precomputed_recall = _semantic_recall(goal, k=cfg.get("semantic_k", 5)).strip()
            except Exception:
                _precomputed_recall = ""
    memory_influenced = []
    if _load_learnings(aspect_id=active_aspect.get("id") or "").strip():
        memory_influenced.append("learnings")
    if _precomputed_recall:
        memory_influenced.append("semantic_recall")
    _ep_mode_lc = str(engineering_pipeline_mode or "chat").strip().lower()
    if (
        not skip_engineering_pipeline
        and bool(cfg.get("engineering_pipeline_enabled"))
        and _ep_mode_lc == "execute"
        and (goal or "").strip()
    ):
        try:
            import agent_loop as _al
            from services.engineering_pipeline import engineering_planning_locked, run_execute_pipeline

            if not engineering_planning_locked():

                def _agent_run_fn(step_goal: str, **kw: Any) -> dict:
                    kw2 = dict(kw)
                    kw2["engineering_pipeline_mode"] = "chat"
                    kw2["skip_engineering_pipeline"] = True
                    kw2["clarification_reply"] = ""
                    return _al.autonomous_run(step_goal, **kw2)

                return run_execute_pipeline(
                    goal=goal,
                    context=context or "",
                    workspace_root=workspace_root or "",
                    allow_write=allow_write,
                    allow_run=allow_run,
                    conversation_history=conversation_history or [],
                    aspect_id=aspect_id or "morrigan",
                    show_thinking=show_thinking,
                    stream_final=stream_final,
                    ux_state_queue=ux_state_queue,
                    research_mode=research_mode,
                    plan_depth=plan_depth,
                    persona_focus=persona_focus or "",
                    conversation_id=conversation_id or "",
                    cognition_workspace_roots=cognition_workspace_roots,
                    client_abort_event=client_abort_event,
                    background_progress_callback=background_progress_callback,
                    clarification_reply=clarification_reply or "",
                    cfg=cfg,
                    agent_run_fn=_agent_run_fn,
                    memory_influenced=list(memory_influenced),
                    active_aspect=active_aspect,
                )
        except Exception as _ep_err:
            logger.warning("engineering pipeline execute failed: %s", _ep_err)
    _prog_on = bool(cfg.get("background_progress_stream_enabled", True))
    _prog_iv = float(cfg.get("background_progress_min_interval_seconds", 0.35) or 0.35)
    if background_progress_callback is not None and _prog_on:
        _steps_list: list = _BackgroundProgressSteps(background_progress_callback, interval=_prog_iv)
    else:
        _steps_list = []
    from execution_state import create_execution_state

    state = create_execution_state(
        goal=goal,
        sub_goals=_decompose_goal(goal),
        active_aspect=active_aspect,
        memory_influenced=memory_influenced,
        reasoning_mode=reasoning_mode,
        last_reasoning_mode=_prev_reasoning_mode,
        persona_focus_id=persona_focus_id,
        conversation_id=_run_cid,
        active_plan_id=active_plan_id or "",
        plan_approved=plan_approved,
        steps_container=_steps_list,
    )
    if _packed_ctx_run:
        state["packed_context"] = _packed_ctx_run
    if context_files:
        state["context_files"] = [str(x).strip() for x in context_files if str(x).strip()]
    # Preserve canonical user-authored goal text. `goal` here may have been
    # rewritten by the prompt optimizer in `autonomous_run` (the outer wrapper).
    # `goal_original` is the user's authored input; `goal_optimized` is the
    # optimizer's rewrite (empty if no rewrite happened). Both are persisted on
    # state so memory writes and `/health/trace` can show the truth.
    _go = _goal_original_var.get() or goal
    _gopt = _goal_optimized_var.get()
    state.setdefault("original_goal", _go)
    state["goal_original"] = _go
    state["goal_optimized"] = _gopt or ""
    state["workspace_root"] = (workspace_root or "").strip()
    state["fabrication_assist_runner_request"] = (fabrication_assist_runner_request or "").strip().lower()
    try:
        from services.intent_router import route_intent

        state["route_decision"] = route_intent(goal, context=context or "", workspace_root=workspace_root or "").to_dict()
    except Exception:
        pass
    try:
        from shared_state import get_last_coordinator_trace

        _ctr = get_last_coordinator_trace(_run_cid)
        if _ctr:
            state["coordinator_trace"] = _ctr
    except Exception as _cte:
        logger.debug("coordinator_trace attach failed: %s", _cte)
    if coordinator_trace and isinstance(coordinator_trace, dict) and coordinator_trace.get("complexity_score") is not None:
        state["coordinator_trace"] = coordinator_trace
    if resume_execution_state and isinstance(resume_execution_state, dict):
        _rk = (
            "depth",
            "tool_calls",
            "consecutive_no_progress",
            "last_tool_used",
            "strategy_shift_count",
            "status",
            "pipeline_stage",
            "retries",
        )
        for k in _rk:
            if k not in resume_execution_state:
                continue
            v = resume_execution_state[k]
            if v is None:
                continue
            if k == "depth":
                try:
                    state["depth"] = int(v)
                except (TypeError, ValueError):
                    pass
            elif k == "tool_calls":
                try:
                    state["tool_calls"] = int(v)
                except (TypeError, ValueError):
                    state["tool_calls"] = v
            else:
                state[k] = v
    workspace = (str(workspace_root).strip() if workspace_root else "") or runtime_safety.load_config().get("sandbox_root", str(Path.home()))
    state["cognition_workspace_roots"] = [str(x).strip() for x in (cognition_workspace_roots or []) if str(x).strip()]
    if research_mode:
        state["research_lab_root"] = str(RESEARCH_LAB_ROOT)
        max_tool_calls = cfg.get("research_max_tool_calls", 20)
        max_runtime = cfg.get("research_max_runtime_seconds", 1800)
    else:
        max_tool_calls = cfg.get("max_tool_calls", 5)
        max_runtime = cfg.get("max_runtime_seconds", 900)
    max_tool_calls_effective = int(max_tool_calls)
    # Token-pressure cap: when conversation already occupies > 60% of n_ctx, limit tool calls
    # so the model is forced to return, chunk, and avoid context overflow.
    try:
        from services.context_manager import token_estimate_messages as _tem
        _n_ctx_here = max(2048, int(cfg.get("n_ctx", 4096)))
        _hist_ratio = _tem(conversation_history or []) / _n_ctx_here
        if _hist_ratio > 0.6 and not research_mode:
            _capped = min(int(max_tool_calls), 3)
            if _capped < max_tool_calls:
                logger.info("token_pressure_cap: hist_ratio=%.2f capping max_tool_calls %dÃÃ¥Ã%d", _hist_ratio, max_tool_calls, _capped)
                max_tool_calls = _capped
                max_tool_calls_effective = int(max_tool_calls)
    except Exception as _exc:
        logger.debug("agent_loop:L2810: %s", _exc, exc_info=False)
    # Adaptive task budget: tighten tool/plan caps from profile + config (services/task_budget.py).
    if cfg.get("task_budget_enabled", True):
        try:
            from services.task_budget import allocate_budget, profile_task

            _tb_prof = profile_task(
                goal,
                context or "",
                reasoning_mode=reasoning_mode,
                research_mode=research_mode,
                allow_write=allow_write,
                allow_run=allow_run,
            )
            _tb_env = allocate_budget(_tb_prof, cfg)
            max_tool_calls = min(int(max_tool_calls), int(_tb_env.max_tool_calls_effective))
            max_tool_calls_effective = int(max_tool_calls)
            plan_depth = min(int(plan_depth), int(_tb_env.max_plan_depth_effective))
            state["task_budget_profile"] = _tb_prof.to_trace_dict()
            state["task_budget_envelope"] = _tb_env.to_trace_dict()
        except Exception as _tb_e:
            logger.debug("task_budget failed: %s", _tb_e)
    # Short chat turns skip heavy retrieval, but local GGUF inference often needs tens of seconds.
    # Do not use a single-digit cap here ÃÃÃ¶ it caused false timeouts on "who are you" style messages.
    if not allow_write and not allow_run and _is_lightweight_chat_turn(goal, reasoning_mode):
        _light_cap = int(cfg.get("chat_light_max_runtime_seconds", 90) or 90)
        max_runtime = min(int(max_runtime), max(30, _light_cap))
    temperature = cfg.get("temperature", 0.2)

    if research_mode and workspace:
        set_effective_sandbox(workspace)

    # Phase 1 ÃÃÃ´ Observe: attach stable context snapshot to state (core/observer.py)
    try:
        from core.observer import build_snapshot as _build_snapshot
        state["_snapshot"] = _build_snapshot(
            goal=goal,
            conversation_id=state.get("conversation_id", ""),
            cfg=cfg,
            aspect_id=aspect_id,
            conversation_history=conversation_history,
            workspace_root=workspace,
            allow_write=allow_write,
            allow_run=allow_run,
        )
    except Exception as _obs_err:
        logger.debug("observer.build_snapshot failed (non-fatal): %s", _obs_err)

    # Cognitive workspace: generate approaches ÃÃ¥Ã evaluate ÃÃ¥Ã choose best (tree-of-thought)
    try:
        from services.cognitive_workspace import run_deliberation, should_use_cognitive_workspace
        # Avoid invoking LLM-only deliberation when no model/inference backend is configured
        # (common in unit tests and fresh installs).
        _llm_configured = bool((cfg.get("model_filename") or "").strip()) or bool(cfg.get("llama_server_url")) or bool(
            (cfg.get("ollama_base_url") or "").strip()
        )
        if _llm_configured and should_use_cognitive_workspace(goal, cfg, plan_depth):
            deliberation = run_deliberation(goal, context or "")
            if deliberation.get("strategy_hint"):
                state["cognitive_workspace"] = deliberation
                _emit_ux(state, ux_state_queue, UX_STATE_THINKING)
    except Exception as _e:
        logger.debug("cognitive_workspace deliberation failed: %s", _e)

    # Planning: if goal warrants it, create and execute plan first (respect max_plan_depth)
    try:
        from services.observability import log_agent_plan_completed, log_agent_plan_created, log_planner_invoked
        from services.planner import (
            create_plan,
            execute_plan_with_optional_graph,
            normalize_plan_steps_tools,
            should_plan,
            validate_plan_before_execution,
        )
        _ct_plan = state.get("coordinator_trace") or {}
        try:
            _thr = float(cfg.get("coordinator_plan_threshold", 0.45) or 0.45)
        except (TypeError, ValueError):
            _thr = 0.45
        _cs = _ct_plan.get("complexity_score")
        try:
            _cs_f = float(_cs) if _cs is not None else 0.0
        except (TypeError, ValueError):
            _cs_f = 0.0
        _force_plan = (
            _cs_f >= _thr
            and not _is_lightweight_chat_turn(goal, reasoning_mode)
        )
        # Behavior lock-in: when a goal is classified as non-trivial, enforce planÃÃ¥ÃexecuteÃÃ¥ÃvalidateÃÃ¥Ãdebug.
        _non_trivial = bool(should_plan(goal, cfg, plan_depth=plan_depth, state=state) or _force_plan)
        if reasoning_mode != "none" and _non_trivial and bool(cfg.get("planning_enabled", True)):
            _digest = ""
            if (workspace or "").strip():
                try:
                    from services.plan_workspace_store import prior_plans_digest

                    _digest = prior_plans_digest(workspace, limit=8)
                except Exception:
                    _digest = ""
            _pref_s = None
            try:
                _pref_s = (_ct_plan.get("preferred_strategy") or "").strip() or None
            except Exception:
                _pref_s = None
            _attempts = 0
            _last_plan_result: dict[str, Any] | None = None
            try:
                _max_levels = int(cfg.get("structured_retry_max_levels", 3) or 3)
            except (TypeError, ValueError):
                _max_levels = 3
            _max_levels = max(1, min(3, _max_levels))
            _structured_retry = bool(cfg.get("structured_retry_enabled", True))
            max_attempts = _max_levels if _structured_retry else 2
            while _attempts < max_attempts:
                _attempts += 1
                # Retry ladder:
                # 1) normal plan
                # 2) same plan goal + failure context (debug)
                # 3) simplified plan (max 3 steps) + optional model override
                _goal_for_plan = goal
                # Aspect behavioral bias: get per-aspect step limit.
                try:
                    from services.aspect_behavior import get_max_steps as _ab_max_steps
                    _max_steps = _ab_max_steps(active_aspect, base_limit=None)
                except Exception:
                    _max_steps = 6
                _model_override = None
                if _attempts == 2 and _last_plan_result is not None:
                    _goal_for_plan = (
                        (state.get("original_goal") or goal)
                        + "\n\n[Retry 1: Previous attempt failed. Fix ONLY the reported failure.]\n"
                        + "\n[Last plan execution summary]:\n"
                        + str(_last_plan_result.get("summary") or "")[:1200]
                    )
                if _attempts >= 3:
                    _max_steps = 3
                    _goal_for_plan = (
                        (state.get("original_goal") or goal)
                        + "\n\n[Retry 2/3: Simplify. Use at most 3 steps. Minimal viable solution only.]\n"
                        + ("\n[Last plan execution summary]:\n" + str((_last_plan_result or {}).get("summary") or "")[:1200] if _last_plan_result else "")
                    )
                    # Retry 3: model switch (prefer coding model, else fallback alias when configured).
                    if _attempts == 3:
                        try:
                            if (cfg.get("coding_model") or "").strip():
                                _model_override = "coding"
                            elif (cfg.get("models") or {}).get("fallback"):
                                _model_override = "fallback"
                        except Exception:
                            _model_override = None

                plan = create_plan(
                    _goal_for_plan,
                    cfg=cfg,
                    prior_plans_digest=_digest,
                    conversation_id=_run_cid,
                    aspect_id=aspect_id or "morrigan",
                    preferred_strategy=_pref_s,
                    max_steps=_max_steps,
                    packed_context=state.get("packed_context") if isinstance(state.get("packed_context"), dict) else None,
                )
                if not plan:
                    break
                plan, _plan_ok, _plan_reason = validate_plan_before_execution(
                    plan, cfg=cfg, workspace_root=workspace
                )
                if not _plan_ok:
                    # Force a simplified replan next attempt.
                    _last_plan_result = {"summary": f"plan_pre_validation_failed:{_plan_reason}"}
                    continue
                if bool(cfg.get("in_loop_plan_governance_enabled")) and bool(
                    cfg.get("plan_governance_require_nonempty_step_tools")
                ):
                    normalize_plan_steps_tools(plan, cfg)
                log_planner_invoked(steps=len(plan), goal_preview=goal[:60])
                log_agent_plan_created(steps=len(plan), goal_preview=goal[:60])
                plan_context = context or ""
                if state.get("cognitive_workspace", {}).get("strategy_hint"):
                    plan_context = plan_context + f"\n\n[Chosen approach: {state['cognitive_workspace']['strategy_hint']}]"
                _il_gov = bool(cfg.get("in_loop_plan_governance_enabled"))
                try:
                    _dm = int(cfg.get("in_loop_plan_default_max_retries", 1) or 1)
                except (TypeError, ValueError):
                    _dm = 1
                _dm = max(0, min(3, _dm))
                _nested_plan_approved = bool(plan_approved) or bool(allow_write) or bool(allow_run)
                _exec_common = dict(
                    context=plan_context,
                    workspace_root=workspace,
                    allow_write=allow_write,
                    allow_run=allow_run,
                    conversation_history=conversation_history or [],
                    aspect_id=aspect_id or "morrigan",
                    show_thinking=show_thinking,
                    stream_final=False,
                    ux_state_queue=ux_state_queue,
                    research_mode=research_mode,
                    conversation_id=_run_cid,
                )
                if _model_override:
                    _exec_common["model_override"] = _model_override
                if _il_gov:
                    plan_result = execute_plan_with_optional_graph(
                        plan,
                        autonomous_run,
                        goal_prefix=goal[:100],
                        plan_depth=plan_depth,
                        step_governance=True,
                        default_max_retries=_dm,
                        plan_approved=_nested_plan_approved,
                        cfg=cfg,
                        **_exec_common,
                    )
                else:
                    plan_result = execute_plan_with_optional_graph(
                        plan,
                        autonomous_run,
                        goal_prefix=goal[:100],
                        plan_depth=plan_depth,
                        cfg=cfg,
                        **_exec_common,
                    )
                _last_plan_result = plan_result if isinstance(plan_result, dict) else None
                # Mandatory validateÃÃ¥ÃdebugÃÃ¥Ãretry: if governance says steps not OK, do one debug-driven replan.
                if (
                    _il_gov
                    and bool(cfg.get("pipeline_enforcement_enabled", True))
                    and isinstance(plan_result, dict)
                    and plan_result.get("all_steps_ok") is False
                    and _attempts < max_attempts
                ):
                    try:
                        state["pipeline_stage"] = "DEBUG"
                    except Exception:
                        pass
                    goal = (state.get("original_goal") or goal)
                    continue
                log_agent_plan_completed(steps=len(plan_result.get("steps_done", [])))
                _emit_run_telemetry(state, True)
                _pc_out: dict = {
                    "status": "plan_completed",
                    "steps": plan_result.get("steps_done", []),
                    "aspect": active_aspect.get("id", "layla"),
                    "aspect_name": active_aspect.get("name", "Layla"),
                    "aspect_miss_warning": _aspect_req if _aspect_miss else "",
                    "refused": False,
                    "refusal_reason": "",
                    "ux_states": state.get("ux_states", []),
                    "memory_influenced": memory_influenced,
                    "reply": plan_result.get("summary", ""),
                    "reasoning_mode": reasoning_mode,
                    "load": classify_load(),
                }
                if _il_gov and isinstance(plan_result, dict) and "all_steps_ok" in plan_result:
                    _pc_out["all_steps_ok"] = bool(plan_result.get("all_steps_ok"))
                return _pc_out
            # If we broke out without returning, allow the loop path to handle response.
    except Exception as _exc:
        logger.warning("agent_loop:L2950: %s", _exc, exc_info=True)

    try:
        from services.agent_hooks import run_agent_hooks

        run_agent_hooks(
            "session_start",
            allow_run=allow_run,
            conversation_id=str(state.get("conversation_id") or ""),
            workspace_root=workspace,
        )
    except Exception as _exc:
        logger.debug("agent_loop:L2962: %s", _exc, exc_info=False)

    while state["depth"] < 5:
        state["tool_attempted_this_turn"] = False
        # Decision policy caps can tighten tool-call budget after repeated failures.
        try:
            if cfg.get("decision_policy_enabled", True):
                from services.decision_policy import build_policy_caps as _build_policy_caps
                from services.decision_policy import effective_max_tool_calls as _effective_max_tool_calls

                _cid = (state.get("conversation_id") or "").strip() or "unknown"
                _caps = _build_policy_caps(state, cfg, conversation_id=_cid)
                state["policy_caps"] = _caps.to_trace_dict()
                max_tool_calls_effective = _effective_max_tool_calls(int(max_tool_calls), _caps)
        except Exception:
            max_tool_calls_effective = int(max_tool_calls)
        if client_abort_event is not None and client_abort_event.is_set():
            state["status"] = "client_abort"
            _last_tool = (state.get("last_tool_used") or "agent") if isinstance(state.get("last_tool_used"), str) else "agent"
            state["steps"].append({
                "action": "client_abort",
                "result": {
                    "ok": False,
                    "reason": "client_abort",
                    "message": "Client disconnected or cancelled the request.",
                },
            })
            if conversation_history is not None:
                _inject_cancel_message(conversation_history, _last_tool, "interrupted (client disconnect)")
            state["response"] = "Request cancelled (client disconnected)."
            break

        if time.time() - state["start_time"] > max_runtime:
            state["status"] = "timeout"
            break

        if state["tool_calls"] >= max_tool_calls_effective:
            state["status"] = "tool_limit"
            break

        if state.get("consecutive_no_progress", 0) >= 2 and not state.get("objective_complete"):
            state["strategy_shift_count"] = state.get("strategy_shift_count", 0) + 1
            _emit_ux(state, ux_state_queue, UX_STATE_CHANGING_APPROACH)

        _emit_context_window_ux(ux_state_queue, conversation_history, cfg, state)
        _emit_ux(state, ux_state_queue, UX_STATE_THINKING)
        goal_for_decision = goal
        try:
            from shared_state import pop_one_agent_steer_hint

            steer = pop_one_agent_steer_hint(state.get("conversation_id") or "default")
            if steer:
                goal_for_decision = (
                    goal
                    + "\n\n[Operator steer ÃÃÃ¶ brief redirect; honor if compatible with the same task]\n"
                    + steer
                )
        except Exception as _exc:
            logger.debug("agent_loop:L3007: %s", _exc, exc_info=False)
        try:
            if cfg.get("inject_packed_context_in_decisions", True) and state.get("packed_context"):
                from services.context_builder import format_tool_context

                _gh = format_tool_context(
                    state["packed_context"],
                    max_chars=int(cfg.get("tool_loop_packed_context_chars", 1200) or 1200),
                )
                if _gh:
                    goal_for_decision = goal_for_decision + "\n\n[Retrieval context]\n" + _gh
        except Exception as _gfc:
            logger.debug("packed_context decision hint: %s", _gfc)
        # Context protection: proactive compression when history exceeds threshold (default 60% of n_ctx).
        try:
            from services.context_manager import summarize_history, token_estimate_messages

            n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
            thr = float(cfg.get("context_protection_threshold", 0.60) or 0.60)
            thr = max(0.35, min(0.85, thr))
            ch = conversation_history or []
            if ch and token_estimate_messages(ch) > int(n_ctx * thr):
                conversation_history = summarize_history(
                    list(ch),
                    n_ctx=n_ctx,
                    threshold_ratio=thr,
                    keep_recent_messages=max(6, int(cfg.get("context_sliding_keep_messages", 0) or 0)),
                )
        except Exception as _exc:
            logger.debug("context protection skipped: %s", _exc, exc_info=False)

        # Step summarization: keep older steps compressed for decision prompts.
        try:
            step_thr = int(cfg.get("step_summarization_threshold", 8) or 8)
        except (TypeError, ValueError):
            step_thr = 8
        if isinstance(state.get("steps"), list) and len(state["steps"]) > max(6, step_thr):
            state["steps_summary"] = _summarize_steps_deterministic(state["steps"], keep_last=5, max_lines=12)
        _t0 = time.perf_counter()
        decision = _llm_decision(
            goal_for_decision, state, context, active_aspect, show_thinking, conversation_history or []
        )
        if decision and isinstance(decision, dict):
            state["last_decision"] = dict(decision)
        try:
            from services.observability import log_agent_decision
            log_agent_decision(duration_ms=(time.perf_counter() - _t0) * 1000)
        except Exception as _exc:
            logger.debug("agent_loop:L3016: %s", _exc, exc_info=False)
        if decision:
            state["objective_complete"] = bool(decision.get("objective_complete", False))
            state["priority_level"] = decision.get("priority_level") or "medium"
            state["impact_estimate"] = decision.get("impact_estimate")
            state["effort_estimate"] = decision.get("effort_estimate")
            state["risk_estimate"] = decision.get("risk_estimate")
            if decision.get("action") == "think":
                thought = (decision.get("thought") or "").strip()
                state["_think_seq"] = int(state.get("_think_seq") or 0) + 1
                _tn = int(state["_think_seq"])
                if thought:
                    state["steps"].append({
                        "action": "think",
                        "result": {"ok": True, "thought": thought[:4000]},
                    })
                if show_thinking and ux_state_queue is not None:
                    try:
                        ux_state_queue.put(
                            {
                                "_type": "think",
                                "content": thought[:2000] if thought else "",
                                "step": _tn,
                            }
                        )
                    except Exception as _exc:
                        logger.debug("agent_loop:L3042: %s", _exc, exc_info=False)
                goal = (
                    state["original_goal"]
                    + "\n\n[Internal reasoning]\n"
                    + (thought or "(no thought text)")
                    + "\n\n[Tool results so far]:\n"
                    + _format_steps(state["steps"])
                )
                continue
            if decision.get("action") == "reason" or state["objective_complete"]:
                intent = "reason"
            elif decision.get("action") == "none":
                intent = "none"
            elif decision.get("action") == "tool" and decision.get("tool") and decision["tool"] in _VALID_TOOLS:
                intent = decision["tool"]
            elif decision.get("action") == "tool":
                # Model chose a tool but it was nulled by the policy filter; skip classify_intent
                # (which is policy-unaware) to avoid burning tool budget on a denied tool.
                try:
                    chosen = str(decision.get("tool") or "").strip()
                    if chosen and chosen not in _VALID_TOOLS:
                        from services.skill_discovery import record_skill_gap

                        record_skill_gap(state.get("original_goal") or goal, tool=chosen, err="unknown_tool")
                except Exception:
                    pass
                intent = "reason"
            else:
                intent = classify_intent((state.get("original_goal") or goal or "").strip())
        else:
            intent = classify_intent((state.get("original_goal") or goal or "").strip())

        consecutive = state.get("consecutive_no_progress", 0)
        objective_complete = state.get("objective_complete", False)
        revised_objective = decision.get("revised_objective") if decision else None
        if revised_objective and isinstance(revised_objective, str) and revised_objective.strip():
            _emit_ux(state, ux_state_queue, UX_STATE_REFRAMING_OBJECTIVE)
            state["reflection_pending"] = True
            state["objective"] = revised_objective.strip()
            state["original_goal"] = revised_objective.strip()
            state["consecutive_no_progress"] = 0
            state["strategy_shift_count"] = 0
            goal = state["objective"]
            continue
        if consecutive >= 2 and not objective_complete and state.get("strategy_shift_count", 0) >= 2:
            _emit_ux(state, ux_state_queue, UX_STATE_CHANGING_APPROACH)
            state["reflection_pending"] = True
            intent = "reason"

        if intent == "none":
            state["steps"].append({
                "action": "none",
                "result": {"ok": True, "message": "No action needed"},
            })
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        _ps = _maybe_planning_strict_refusal(intent, cfg, state, allow_write, allow_run)
        if _ps:
            state["tool_calls"] += 1
            state["steps"].append({"action": intent, "result": _ps})
            _log_tool_outcome(intent, _ps)
            state["last_tool_used"] = intent
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent not in ("reason", "finish", "wakeup", "none") and intent in _VALID_TOOLS:
            _alr = _maybe_step_tool_allowlist_refusal(intent, cfg)
            if _alr:
                state["tool_calls"] += 1
                state["steps"].append({"action": intent, "result": _alr})
                _log_tool_outcome(intent, _alr)
                state["last_tool_used"] = intent
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue

        # D0: Preflight ÃÃÃ¶ if the model picked an un-runnable tool (missing required args),
        # redirect to a conversational reply instead of burning tool budget or producing parse_failed.
        if intent not in ("reason", "finish", "wakeup", "none") and intent in _VALID_TOOLS:
            try:
                from services.tool_preflight import preflight_tool

                pf = preflight_tool(intent=intent, decision=decision, goal=state.get("original_goal") or goal, workspace_root=workspace or "")
                state["preflight_ok"] = bool(pf.ok)
                state["preflight_reason"] = pf.reason if not pf.ok else ""
                if not pf.ok:
                    state.setdefault("steps", []).append(
                        {
                            "action": "preflight",
                            "result": {
                                "ok": False,
                                "reason": "missing_required_args",
                                "message": pf.reason,
                                "suggested_action": pf.suggested_action,
                                "missing": pf.missing or [],
                                "tool": intent,
                            },
                        }
                    )
                    intent = "reason"
            except Exception as _pf_exc:
                logger.debug("tool_preflight skipped: %s", _pf_exc, exc_info=False)

        # ÃÃ¶ÃÃÃ¶Ã D1: Concurrent read-only tool batch ÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶Ã
        # The LLM may declare additional parallel tools in decision["batch_tools"].
        # Each entry is {"tool": name, "args": {...}} and must be concurrency_safe.
        # We execute the primary tool + all batch_tools concurrently in one step.
        _extra_batch = [
            bt for bt in (decision.get("batch_tools") or [])
            if isinstance(bt, dict)
            and bt.get("tool") in _VALID_TOOLS
            and TOOLS.get(bt["tool"], {}).get("concurrency_safe")
            and bt["tool"] != intent  # no duplicates
        ] if (
            intent not in ("reason", "finish", "wakeup", "none")
            and intent in _VALID_TOOLS
            and TOOLS.get(intent, {}).get("concurrency_safe")
            and not state.get("research_lab_root")
        ) else []

        if _extra_batch and state["tool_calls"] + 1 + len(_extra_batch) <= max_tool_calls_effective:
            _batch_tools_check = [intent] + [str(bt.get("tool") or "") for bt in _extra_batch]
            _blocked_bt = None
            for _tcheck in _batch_tools_check:
                if not _tcheck:
                    continue
                _pbx = _maybe_planning_strict_refusal(_tcheck, cfg, state, allow_write, allow_run)
                if _pbx:
                    _blocked_bt = (_tcheck, _pbx)
                    break
                _alx = _maybe_step_tool_allowlist_refusal(_tcheck, cfg)
                if _alx:
                    _blocked_bt = (_tcheck, _alx)
                    break
            if _blocked_bt:
                _tcheck, _pbx = _blocked_bt
                state["tool_calls"] += 1
                state["steps"].append({"action": _tcheck, "result": _pbx})
                _log_tool_outcome(_tcheck, _pbx)
                state["last_tool_used"] = _tcheck
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue

            import concurrent.futures as _cf
            import functools as _fn

            from services.worker_pool import tool_batch_max_workers

            _tool_timeout = float(cfg.get("tool_call_timeout_seconds", 60))
            _primary_args = _inject_workspace_args(intent, (decision.get("args") or {}) if decision else {}, workspace)
            _batch: list[tuple[str, dict]] = [(intent, _primary_args)] + [
                (bt["tool"], _inject_workspace_args(bt["tool"], bt.get("args") or {}, workspace))
                for bt in _extra_batch
            ]
            _batch_results: list[dict | None] = [None] * len(_batch)
            _hook_cid = str(state.get("conversation_id") or "")
            _pool_workers = tool_batch_max_workers(cfg, len(_batch))
            with _cf.ThreadPoolExecutor(max_workers=_pool_workers, thread_name_prefix="layla_cbatch") as _pool:
                _futs = {
                    _pool.submit(
                        _fn.partial(
                            _run_tool,
                            _bt,
                            _ba,
                            timeout_s=_tool_timeout,
                            sandbox_root=workspace,
                            allow_run=allow_run,
                            conversation_id=_hook_cid,
                        )
                    ): _idx
                    for _idx, (_bt, _ba) in enumerate(_batch)
                }
                for _fut in _cf.as_completed(_futs):
                    _bidx = _futs[_fut]
                    try:
                        _batch_results[_bidx] = _fut.result()
                    except Exception as _be:
                        _batch_results[_bidx] = {"ok": False, "error": str(_be)}
            for _bidx, (_bt, _ba) in enumerate(_batch):
                _br = _batch_results[_bidx] if _batch_results[_bidx] is not None else {"ok": False, "error": "batch slot empty"}
                runtime_safety.log_execution(_bt, _ba)
                state["tool_calls"] += 1
                _register_exact_tool_call(state, _bt, decision if _bidx == 0 else None)
                _res = _maybe_validate_tool_output(_bt, _br)
                _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                    _bt, _res, workspace=workspace, cfg=cfg
                )
                # Note: no automatic retry inside concurrent batch (would require rerunning the pool).
                if not _ok_det and isinstance(_res, dict):
                    _res["_deterministic_retry_skipped"] = True
                    _res["_deterministic_retry_reason"] = _det_reason
                state["steps"].append({"action": _bt, "result": _res})
                state["last_tool_used"] = _bt
                _emit_tool_start(ux_state_queue, _bt)
            _run_verification_after_tool(
                state,
                _batch[-1][0],
                (state["steps"][-1].get("result") if state.get("steps") else {}) if isinstance(state.get("steps"), list) else (_batch_results[-1] if _batch_results[-1] is not None else {}),
                workspace,
            )
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            logger.info("concurrent batch: ran %d tools in parallel", len(_batch))
            continue
        # ÃÃ¶ÃÃÃ¶Ã end concurrent batch ÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶ÃÃÃ¶Ã

        # Emit tool_start so streaming UI can show "Running tool_name..."
        if intent not in ("reason", "finish", "wakeup"):
            _emit_tool_start(ux_state_queue, intent)

        # OpenClaw-style tool policy: block execution outside effective tool set
        if intent not in ("reason", "finish", "wakeup") and intent in _VALID_TOOLS:
            from services.tool_policy import tool_allowed

            _vt = _get_tools_for_goal(goal, context=context or "", workspace_root=workspace or "", state=state)
            try:
                if cfg.get("decision_policy_enabled", True):
                    from services.decision_policy import apply_caps_to_valid_tools as _apply_caps_to_valid_tools
                    from services.decision_policy import build_policy_caps as _build_policy_caps

                    _cid = (state.get("conversation_id") or "").strip() or "unknown"
                    _caps = _build_policy_caps(state, cfg, conversation_id=_cid)
                    state["policy_caps"] = _caps.to_trace_dict()
                    _vt = _apply_caps_to_valid_tools(_vt, _caps)
            except Exception as _dp_exc:
                logger.debug("decision_policy caps skipped at dispatch: %s", _dp_exc)
            if not tool_allowed(intent, _vt):
                state["tool_calls"] += 1
                _tpd = {
                    "ok": False,
                    "reason": "tool_policy_denied",
                    "message": (
                        f"Tool {intent} is not allowed this turn "
                        "(tools_profile / tools_allow / tools_deny / intent filter)."
                    ),
                }
                state["steps"].append({"action": intent, "result": _tpd})
                _log_tool_outcome(intent, _tpd)
                state["last_tool_used"] = intent
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue

        if intent not in ("reason", "finish", "wakeup") and intent in _VALID_TOOLS:
            try:
                from services.tool_loop_detection import push_and_evaluate

                _loop_ev = push_and_evaluate(
                    cfg, state, intent, decision, reasoning_mode=state.get("reasoning_mode"),
                )
                if _loop_ev and _loop_ev.startswith("STOP:"):
                    state["tool_calls"] += 1
                    _tlr = {
                        "ok": False,
                        "reason": "tool_loop_detected",
                        "message": _loop_ev[5:].strip(),
                    }
                    state["steps"].append({"action": intent, "result": _tlr})
                    _log_tool_outcome(intent, _tlr)
                    state["last_tool_used"] = intent
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
                if _loop_ev and _loop_ev.startswith("WARN:"):
                    state["tool_loop_prompt_hint"] = _loop_ev[5:].strip()
            except Exception as _exc:
                logger.debug("agent_loop:L3249: %s", _exc, exc_info=False)

        if intent not in ("reason", "finish", "wakeup") and intent in _VALID_TOOLS:
            try:
                from services.tool_args import validate_tool_invocation

                _verr = validate_tool_invocation(intent, decision, goal, workspace)
                if _verr:
                    state["tool_calls"] += 1
                    state["steps"].append({"action": intent, "result": _verr})
                    _log_tool_outcome(intent, _verr)
                    state["last_tool_used"] = intent
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
            except Exception as _exc:
                logger.debug("agent_loop:L3264: %s", _exc, exc_info=False)

        if intent not in ("reason", "finish", "wakeup", "none") and intent in _VALID_TOOLS:
            try:
                from services.tool_loop_detection import exact_call_key

                _eck = exact_call_key(intent, decision)
                _seen = state.setdefault("_recent_exact_calls", set())
                if _eck in _seen:
                    state["tool_calls"] += 1
                    _tdup = {
                        "ok": False,
                        "reason": "tool_loop_detected",
                        "message": "Exact duplicate tool invocation blocked for this run.",
                    }
                    state["steps"].append({"action": intent, "result": _tdup})
                    _log_tool_outcome(intent, _tdup)
                    state["last_tool_used"] = intent
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
            except Exception as _exc:
                logger.debug("agent_loop:L3285: %s", _exc, exc_info=False)

        if intent not in ("reason", "finish", "wakeup", "none") and intent in _VALID_TOOLS:
            try:
                from services.failure_recovery import block_repeated_mutating_under_retry_constrained

                if block_repeated_mutating_under_retry_constrained(state, intent):
                    state["tool_calls"] += 1
                    _br = {
                        "ok": False,
                        "reason": "retry_constrained_block",
                        "message": (
                            "Same mutating tool blocked under retry_constrained; verify with read_file/grep before retrying."
                        ),
                    }
                    state["steps"].append({"action": intent, "result": _br})
                    _log_tool_outcome(intent, _br)
                    state["last_tool_used"] = intent
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
            except Exception as _exc:
                logger.debug("agent_loop:L3306: %s", _exc, exc_info=False)

        # ------------------------------------------------
        # WRITE FILE
        # ------------------------------------------------
        if intent == "write_file":
            path, content = _extract_file_and_content(goal)
            if not path:
                state["status"] = "parse_failed"
                break
            lab_root = state.get("research_lab_root") or ""
            if lab_root and workspace and not Path(path).is_absolute():
                path = str(Path(workspace) / path)
            if lab_root:
                if not _path_under_lab(path, lab_root):
                    state["tool_calls"] += 1
                    state["steps"].append({
                        "action": "write_file",
                        "result": {"ok": False, "reason": "research_lab_only", "message": "Writes allowed only inside .research_lab"},
                    })
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
                state["tool_calls"] += 1
                _admin_pre_mutate(cfg, workspace, "write_file", path)
                result = TOOLS["write_file"]["fn"](path=path, content=content)
                _register_exact_tool_call(state, "write_file", decision)
                runtime_safety.log_execution("write_file", {"path": path})
                _res, _ok_det, _det_reason = _run_edit_postchecks(
                    state,
                    "write_file",
                    result,
                    workspace=workspace,
                    cfg=cfg,
                    re_execute=lambda: TOOLS["write_file"]["fn"](path=path, content=content),
                )
                state["steps"].append({"action": "write_file", "result": _res})
                state["last_tool_used"] = "write_file"
                _run_verification_after_tool(state, "write_file", _res if isinstance(_res, dict) else result, workspace)
                _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
                _run_git_auto_commit("write_file", result, result.get("path") or path, workspace)
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                if reasoning_mode != "none":
                    hint = _run_auto_lint_test_fix(state, "write_file", result, result.get("path") or path, workspace)
                    if hint:
                        goal = goal + "\n\n" + hint
                continue
            _wf_grant_args = {"path": path}
            if not allow_write or (not runtime_safety.is_tool_allowed("write_file") and not _has_any_grant("write_file", _wf_grant_args)):
                wf_args = {"path": path, "content": content}
                _approval_preview_diff("write_file", wf_args, workspace)
                approval_id = _write_pending("write_file", wf_args)
                state["steps"].append({
                    "action": "write_file",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break

            target = Path(path)
            if runtime_safety.is_protected(target):
                if not runtime_safety.backup_file(target):
                    state["steps"].append({
                        "action": "write_file",
                        "result": {"ok": False, "reason": "backup_failed"},
                    })
                    state["status"] = "finished"
                    break

            state["tool_calls"] += 1
            _admin_pre_mutate(cfg, workspace, "write_file", path)
            result = TOOLS["write_file"]["fn"](path=path, content=content)
            _register_exact_tool_call(state, "write_file", decision)
            runtime_safety.log_execution("write_file", {"path": path})
            _res, _ok_det, _det_reason = _run_edit_postchecks(
                state,
                "write_file",
                result,
                workspace=workspace,
                cfg=cfg,
                re_execute=lambda: TOOLS["write_file"]["fn"](path=path, content=content),
            )
            state["steps"].append({"action": "write_file", "result": _res})
            state["last_tool_used"] = "write_file"
            _run_verification_after_tool(state, "write_file", _res if isinstance(_res, dict) else result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            _run_git_auto_commit("write_file", result, result.get("path") or path, workspace)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            if reasoning_mode != "none":
                hint = _run_auto_lint_test_fix(state, "write_file", result, result.get("path") or path, workspace)
                if hint:
                    goal = goal + "\n\n" + hint
            continue

        # ------------------------------------------------
        # WRITE FILES BATCH
        # ------------------------------------------------
        if intent == "write_files_batch":
            args = (decision.get("args") or {}) if decision else {}
            files = args.get("files") or []
            if not isinstance(files, list) or not files:
                state["steps"].append({
                    "action": "write_files_batch",
                    "result": {"ok": False, "error": "write_files_batch requires args.files: [{path, content}, ...]"},
                })
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            if not allow_write or (not runtime_safety.is_tool_allowed("write_files_batch") and not _has_any_grant("write_files_batch", {"files": [f.get("path","") for f in files][:1]})):
                wfb_args = {"files": files}
                _approval_preview_diff("write_files_batch", wfb_args, workspace)
                approval_id = _write_pending("write_files_batch", wfb_args)
                state["steps"].append({
                    "action": "write_files_batch",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            state["tool_calls"] += 1
            result = TOOLS["write_files_batch"]["fn"](files=files)
            _register_exact_tool_call(state, "write_files_batch", decision)
            runtime_safety.log_execution("write_files_batch", {"count": len(files)})
            _res = _maybe_validate_tool_output("write_files_batch", result)
            # Deterministically verify each written file exists (and is non-empty) by reusing write_file verifier.
            try:
                if isinstance(_res, dict) and _res.get("ok") and isinstance(_res.get("written"), list):
                    from services.tool_output_validator import deterministic_verify_tool_result

                    _batch_v: list[dict] = []
                    _batch_ok = True
                    for _p in [str(x) for x in (_res.get("written") or []) if str(x).strip()][:50]:
                        vr = deterministic_verify_tool_result(
                            "write_file",
                            {"ok": True, "path": _p},
                            workspace_root=workspace or "",
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
                    _run_git_auto_commit("write_files_batch", result, p, workspace)
                    break
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            if reasoning_mode != "none" and isinstance(_res, dict) and _res.get("ok"):
                wp = ""
                wlist = _res.get("written") if isinstance(_res.get("written"), list) else []
                if wlist:
                    wp = str(wlist[0] or "").strip()
                if not wp:
                    wp = workspace
                if wp:
                    lh = _run_auto_lint_test_fix(state, "write_files_batch", _res, wp, workspace)
                    if lh:
                        goal = goal + "\n\n" + lh
            continue

        # ------------------------------------------------
        # READ FILE
        # ------------------------------------------------
        if intent == "read_file":
            path = _extract_path(goal)
            if not path:
                state["status"] = "parse_failed"
                break
            probe = _maybe_preprobe_file(state, path)
            if not _apply_probe_guidance(state, "read_file", path, probe):
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            state["tool_calls"] += 1
            result = TOOLS["read_file"]["fn"](path=path)
            _register_exact_tool_call(state, "read_file", decision)
            runtime_safety.log_execution("read_file", {"path": path})
            _res = _maybe_validate_tool_output("read_file", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "read_file", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("read_file") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["read_file"] = _cnt + 1
                    result = TOOLS["read_file"]["fn"](path=path)
                    runtime_safety.log_execution("read_file", {"path": path, "_retry": True})
                    _res = _maybe_validate_tool_output("read_file", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "read_file", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "read_file", "result": _res})
            state["last_tool_used"] = "read_file"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # LIST DIR
        # ------------------------------------------------
        if intent == "list_dir":
            path = _extract_path(goal) or workspace
            state["tool_calls"] += 1
            result = TOOLS["list_dir"]["fn"](path=path)
            _register_exact_tool_call(state, "list_dir", decision)
            runtime_safety.log_execution("list_dir", {"path": path})
            _res = _maybe_validate_tool_output("list_dir", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "list_dir", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("list_dir") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["list_dir"] = _cnt + 1
                    result = TOOLS["list_dir"]["fn"](path=path)
                    runtime_safety.log_execution("list_dir", {"path": path, "_retry": True})
                    _res = _maybe_validate_tool_output("list_dir", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "list_dir", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "list_dir", "result": _res})
            state["last_tool_used"] = "list_dir"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # GIT STATUS / DIFF / LOG / BRANCH
        # ------------------------------------------------
        if intent == "git_status":
            state["tool_calls"] += 1
            result = TOOLS["git_status"]["fn"](repo=workspace)
            _register_exact_tool_call(state, "git_status", decision)
            runtime_safety.log_execution("git_status", {"repo": workspace})
            state["steps"].append({"action": "git_status", "result": _maybe_validate_tool_output("git_status", result)})
            state["last_tool_used"] = "git_status"
            _run_verification_after_tool(state, "git_status", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "git_diff":
            state["tool_calls"] += 1
            result = TOOLS["git_diff"]["fn"](repo=workspace)
            _register_exact_tool_call(state, "git_diff", decision)
            runtime_safety.log_execution("git_diff", {"repo": workspace})
            state["steps"].append({"action": "git_diff", "result": _maybe_validate_tool_output("git_diff", result)})
            state["last_tool_used"] = "git_diff"
            _run_verification_after_tool(state, "git_diff", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "git_log":
            state["tool_calls"] += 1
            result = TOOLS["git_log"]["fn"](repo=workspace, n=10)
            _register_exact_tool_call(state, "git_log", decision)
            runtime_safety.log_execution("git_log", {"repo": workspace})
            state["steps"].append({"action": "git_log", "result": _maybe_validate_tool_output("git_log", result)})
            state["last_tool_used"] = "git_log"
            _run_verification_after_tool(state, "git_log", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "git_branch":
            state["tool_calls"] += 1
            result = TOOLS["git_branch"]["fn"](repo=workspace)
            _register_exact_tool_call(state, "git_branch", decision)
            runtime_safety.log_execution("git_branch", {"repo": workspace})
            state["steps"].append({"action": "git_branch", "result": _maybe_validate_tool_output("git_branch", result)})
            state["last_tool_used"] = "git_branch"
            _run_verification_after_tool(state, "git_branch", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # GREP / GLOB
        # ------------------------------------------------
        if intent == "grep_code":
            parts = goal.split()
            pattern = parts[-1] if parts else ""
            grep_path = workspace
            maybe_path = _extract_path(goal)
            # If user supplied a concrete file path, use it; probe it once for awareness.
            if maybe_path and Path(maybe_path).suffix:
                probe = _maybe_preprobe_file(state, maybe_path)
                _apply_probe_guidance(state, "grep_code", maybe_path, probe)
                grep_path = maybe_path
            state["tool_calls"] += 1
            result = TOOLS["grep_code"]["fn"](pattern=pattern, path=grep_path)
            _register_exact_tool_call(state, "grep_code", decision)
            runtime_safety.log_execution("grep_code", {"pattern": pattern, "path": grep_path})
            _res = _maybe_validate_tool_output("grep_code", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "grep_code", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("grep_code") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["grep_code"] = _cnt + 1
                    result = TOOLS["grep_code"]["fn"](pattern=pattern, path=grep_path)
                    runtime_safety.log_execution("grep_code", {"pattern": pattern, "path": grep_path, "_retry": True})
                    _res = _maybe_validate_tool_output("grep_code", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "grep_code", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "grep_code", "result": _res})
            state["last_tool_used"] = "grep_code"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "glob_files":
            parts = goal.split()
            pattern = parts[-1] if parts else "*"
            state["tool_calls"] += 1
            result = TOOLS["glob_files"]["fn"](pattern=pattern, root=workspace)
            _register_exact_tool_call(state, "glob_files", decision)
            runtime_safety.log_execution("glob_files", {"pattern": pattern, "root": workspace})
            _res = _maybe_validate_tool_output("glob_files", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "glob_files", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("glob_files") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["glob_files"] = _cnt + 1
                    result = TOOLS["glob_files"]["fn"](pattern=pattern, root=workspace)
                    runtime_safety.log_execution("glob_files", {"pattern": pattern, "root": workspace, "_retry": True})
                    _res = _maybe_validate_tool_output("glob_files", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "glob_files", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "glob_files", "result": _res})
            state["last_tool_used"] = "glob_files"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # RUN PYTHON
        # ------------------------------------------------
        if intent == "run_python":
            lab_root = state.get("research_lab_root") or ""
            if lab_root:
                if not allow_run:
                    state["tool_calls"] += 1
                    state["steps"].append({
                        "action": "run_python",
                        "result": {"ok": False, "reason": "disabled_in_research", "message": "run_python is disabled for this research stage. Use read_file, list_dir, grep_code instead."},
                    })
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
                if not _path_under_lab(workspace, lab_root):
                    state["tool_calls"] += 1
                    state["steps"].append({
                        "action": "run_python",
                        "result": {"ok": False, "reason": "research_lab_only", "message": "run_python allowed only with cwd inside .research_lab"},
                    })
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
                code = goal
                state["tool_calls"] += 1
                _admin_pre_mutate(cfg, workspace, "run_python", (code or "")[:120])
                result = TOOLS["run_python"]["fn"](code=code, cwd=workspace)
                _register_exact_tool_call(state, "run_python", decision)
                runtime_safety.log_execution("run_python", {"cwd": workspace})
                _res = _maybe_validate_tool_output("run_python", result)
                _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                    "run_python", _res, workspace=workspace, cfg=cfg
                )
                if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                    state.setdefault("_deterministic_retry_counts", {})
                    _cnt = int(state["_deterministic_retry_counts"].get("run_python") or 0)
                    if _cnt < 1:
                        state["_deterministic_retry_counts"]["run_python"] = _cnt + 1
                        result = TOOLS["run_python"]["fn"](code=code, cwd=workspace)
                        runtime_safety.log_execution("run_python", {"cwd": workspace, "_retry": True})
                        _res = _maybe_validate_tool_output("run_python", result)
                        _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                            "run_python", _res, workspace=workspace, cfg=cfg
                        )
                        if isinstance(_res, dict):
                            _res["_deterministic_retry"] = True
                            _res["_deterministic_retry_reason"] = _det_reason
                state["steps"].append({"action": "run_python", "result": _res})
                state["last_tool_used"] = "run_python"
                _run_verification_after_tool(state, "run_python", _res if isinstance(_res, dict) else result, workspace)
                _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            if not allow_run or not runtime_safety.is_tool_allowed("run_python"):
                approval_id = _write_pending("run_python", {"code": goal, "cwd": workspace})
                state["steps"].append({
                    "action": "run_python",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            code = goal
            state["tool_calls"] += 1
            _admin_pre_mutate(cfg, workspace, "run_python", (code or "")[:120])
            result = TOOLS["run_python"]["fn"](code=code, cwd=workspace)
            _register_exact_tool_call(state, "run_python", decision)
            runtime_safety.log_execution("run_python", {"cwd": workspace})
            _res = _maybe_validate_tool_output("run_python", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "run_python", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("run_python") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["run_python"] = _cnt + 1
                    result = TOOLS["run_python"]["fn"](code=code, cwd=workspace)
                    runtime_safety.log_execution("run_python", {"cwd": workspace, "_retry": True})
                    _res = _maybe_validate_tool_output("run_python", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "run_python", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "run_python", "result": _res})
            state["last_tool_used"] = "run_python"
            _run_verification_after_tool(state, "run_python", _res if isinstance(_res, dict) else result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # APPLY PATCH
        # ------------------------------------------------
        if intent == "apply_patch":
            if state.get("research_lab_root"):
                state["tool_calls"] += 1
                state["steps"].append({
                    "action": "apply_patch",
                    "result": {"ok": False, "reason": "not_allowed_in_research", "message": "apply_patch not allowed in research missions"},
                })
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            path = _extract_path(goal)
            patch_body = _extract_patch_text(goal)
            if path:
                probe = _maybe_preprobe_file(state, path)
                if not _apply_probe_guidance(state, "apply_patch", path, probe):
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
            try:
                max_patch_lines = int(cfg.get("max_patch_lines", 0) or 0)
            except (TypeError, ValueError):
                max_patch_lines = 0
            if max_patch_lines and patch_body and patch_body.count("\n") > max_patch_lines:
                state["tool_calls"] += 1
                state["steps"].append({
                    "action": "apply_patch",
                    "result": {
                        "ok": False,
                        "error": "diff_too_large",
                        "lines": patch_body.count("\n"),
                        "max": max_patch_lines,
                    },
                })
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            if not allow_write or (not runtime_safety.is_tool_allowed("apply_patch") and not _has_any_grant("apply_patch", {"path": path or ""})):
                ap_args = {"original_path": path or "", "patch_text": patch_body}
                _approval_preview_diff("apply_patch", ap_args, workspace)
                approval_id = _write_pending("apply_patch", ap_args)
                state["steps"].append({
                    "action": "apply_patch",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            if not path:
                state["status"] = "parse_failed"
                break
            state["tool_calls"] += 1
            _admin_pre_mutate(cfg, workspace, "apply_patch", path)
            result = TOOLS["apply_patch"]["fn"](original_path=path, patch_text=patch_body)
            _register_exact_tool_call(state, "apply_patch", decision)
            runtime_safety.log_execution("apply_patch", {"path": path})
            _res = _maybe_validate_tool_output("apply_patch", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "apply_patch", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("apply_patch") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["apply_patch"] = _cnt + 1
                    result = TOOLS["apply_patch"]["fn"](original_path=path, patch_text=patch_body)
                    runtime_safety.log_execution("apply_patch", {"path": path, "_retry": True})
                    _res = _maybe_validate_tool_output("apply_patch", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "apply_patch", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "apply_patch", "result": _res})
            state["last_tool_used"] = "apply_patch"
            _run_verification_after_tool(state, "apply_patch", _res if isinstance(_res, dict) else result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            _run_git_auto_commit("apply_patch", result, path, workspace)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            if reasoning_mode != "none":
                hint = _run_auto_lint_test_fix(state, "apply_patch", result, path, workspace)
                if hint:
                    goal = goal + "\n\n" + hint
            continue

        # ------------------------------------------------
        # REPLACE IN FILE (surgical)
        # ------------------------------------------------
        if intent == "replace_in_file":
            if state.get("research_lab_root"):
                state["tool_calls"] += 1
                state["steps"].append({
                    "action": "replace_in_file",
                    "result": {"ok": False, "reason": "not_allowed_in_research"},
                })
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
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
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            if path:
                probe = _maybe_preprobe_file(state, path)
                if not _apply_probe_guidance(state, "replace_in_file", path, probe):
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
            if not allow_write or (
                not runtime_safety.is_tool_allowed("replace_in_file")
                and not _has_any_grant("replace_in_file", {"path": path})
            ):
                rif_args = {"path": path, "old_text": old_text, "new_text": new_text, "count": rcount}
                _approval_preview_diff("replace_in_file", rif_args, workspace)
                approval_id = _write_pending("replace_in_file", rif_args)
                state["steps"].append({
                    "action": "replace_in_file",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            state["tool_calls"] += 1
            _admin_pre_mutate(cfg, workspace, "replace_in_file", path)
            result = TOOLS["replace_in_file"]["fn"](
                path=path, old_text=old_text, new_text=new_text, count=rcount
            )
            _register_exact_tool_call(state, "replace_in_file", decision)
            runtime_safety.log_execution("replace_in_file", {"path": path})
            _res = _maybe_validate_tool_output("replace_in_file", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "replace_in_file", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("replace_in_file") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["replace_in_file"] = _cnt + 1
                    result = TOOLS["replace_in_file"]["fn"](path=path, old_text=old_text, new_text=new_text, count=rcount)
                    runtime_safety.log_execution("replace_in_file", {"path": path, "_retry": True})
                    _res = _maybe_validate_tool_output("replace_in_file", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "replace_in_file", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "replace_in_file", "result": _res})
            state["last_tool_used"] = "replace_in_file"
            _run_verification_after_tool(state, "replace_in_file", _res if isinstance(_res, dict) else result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            _run_git_auto_commit("replace_in_file", result, result.get("path") or path, workspace)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            if reasoning_mode != "none":
                hint = _run_auto_lint_test_fix(state, "replace_in_file", result, result.get("path") or path, workspace)
                if hint:
                    goal = goal + "\n\n" + hint
            continue

        # ------------------------------------------------
        # FETCH URL
        # ------------------------------------------------
        if intent == "fetch_url":
            words = goal.split()
            url = next((w for w in words if w.startswith("http")), "")
            if not url:
                state["status"] = "parse_failed"
                break
            state["tool_calls"] += 1
            result = TOOLS["fetch_url"]["fn"](url=url)
            _register_exact_tool_call(state, "fetch_url", decision)
            runtime_safety.log_execution("fetch_url", {"url": url})
            _res = _maybe_validate_tool_output("fetch_url", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "fetch_url", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("fetch_url") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["fetch_url"] = _cnt + 1
                    result = TOOLS["fetch_url"]["fn"](url=url)
                    runtime_safety.log_execution("fetch_url", {"url": url, "_retry": True})
                    _res = _maybe_validate_tool_output("fetch_url", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "fetch_url", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "fetch_url", "result": _res})
            state["last_tool_used"] = "fetch_url"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # SHELL
        # ------------------------------------------------
        if intent == "shell":
            if state.get("research_lab_root"):
                state["tool_calls"] += 1
                state["steps"].append({
                    "action": "shell",
                    "result": {"ok": False, "reason": "not_allowed_in_research", "message": "shell not allowed in research missions"},
                })
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            argv = _extract_shell_argv(goal)
            if not argv:
                state["status"] = "parse_failed"
                break
            if not allow_run:
                approval_id = _write_pending("shell", {"argv": argv, "cwd": workspace})
                state["steps"].append({
                    "action": "shell",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            from layla.tools.registry import shell_command_is_safe_whitelisted, shell_command_line
            _cmd_line = shell_command_line(argv)
            _grant_ok = _has_any_grant("shell", {"command": _cmd_line})
            _need_shell_approval = runtime_safety.is_tool_allowed("shell")
            if _need_shell_approval and not shell_command_is_safe_whitelisted(argv) and not _grant_ok:
                approval_id = _write_pending("shell", {"argv": argv, "cwd": workspace})
                state["steps"].append({
                    "action": "shell",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            state["tool_calls"] += 1
            _admin_pre_mutate(cfg, workspace, "shell", _cmd_line[:160])
            result = TOOLS["shell"]["fn"](argv=argv, cwd=workspace)
            _register_exact_tool_call(state, "shell", decision)
            runtime_safety.log_execution("shell", {"argv": argv, "cwd": workspace})
            _res = _maybe_validate_tool_output("shell", result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                "shell", _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get("shell") or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"]["shell"] = _cnt + 1
                    result = TOOLS["shell"]["fn"](argv=argv, cwd=workspace)
                    runtime_safety.log_execution("shell", {"argv": argv, "cwd": workspace, "_retry": True})
                    _res = _maybe_validate_tool_output("shell", result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        "shell", _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": "shell", "result": _res})
            state["last_tool_used"] = "shell"
            _run_verification_after_tool(state, "shell", _res if isinstance(_res, dict) else result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # MCP (stdio subprocess; gated like shell ÃÃÃ¶ allow_run + approvals)
        # ------------------------------------------------
        if intent == "mcp_tools_call":
            args = _normalize_mcp_tool_args((decision.get("args") or {}) if decision else {})
            if state.get("research_lab_root"):
                state["tool_calls"] += 1
                state["steps"].append({
                    "action": "mcp_tools_call",
                    "result": {"ok": False, "reason": "not_allowed_in_research", "message": "MCP tools not allowed in research missions"},
                })
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            if not allow_run:
                approval_id = _write_pending("mcp_tools_call", args)
                state["steps"].append({
                    "action": "mcp_tools_call",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            _need_mcp_approval = runtime_safety.is_tool_allowed("mcp_tools_call")
            _mcp_grant_ok = _has_any_grant("mcp_tools_call", args)
            if _need_mcp_approval and not _mcp_grant_ok:
                approval_id = _write_pending("mcp_tools_call", args)
                state["steps"].append({
                    "action": "mcp_tools_call",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            state["tool_calls"] += 1
            _mcp_args = args
            result = TOOLS["mcp_tools_call"]["fn"](
                mcp_server=str(_mcp_args.get("mcp_server") or ""),
                tool_name=str(_mcp_args.get("tool_name") or ""),
                arguments=_mcp_args.get("arguments") if isinstance(_mcp_args.get("arguments"), dict) else None,
            )
            _register_exact_tool_call(state, "mcp_tools_call", decision)
            runtime_safety.log_execution("mcp_tools_call", _mcp_args)
            _val = _maybe_validate_tool_output("mcp_tools_call", result)
            state["steps"].append({"action": "mcp_tools_call", "result": _val})
            if show_thinking:
                _emit_tool_step(ux_state_queue, "mcp_tools_call", _val)
            state["last_tool_used"] = "mcp_tools_call"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # EXTENDED TOOLS (no approval needed)
        # ------------------------------------------------
        if intent in ("json_query", "diff_files", "env_info", "regex_test",
                      "save_note", "search_memories", "git_add"):
            args = (decision.get("args") or {}) if decision else {}
            state["tool_calls"] += 1
            result = TOOLS[intent]["fn"](**args) if args else TOOLS[intent]["fn"]()
            _register_exact_tool_call(state, intent, decision)
            runtime_safety.log_execution(intent, args)
            _val = _maybe_validate_tool_output(intent, result)
            state["steps"].append({"action": intent, "result": _val})
            if show_thinking:
                _emit_tool_step(ux_state_queue, intent, _val)
            state["last_tool_used"] = intent
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "git_commit":
            args = (decision.get("args") or {}) if decision else {}
            if not allow_write or (not runtime_safety.is_tool_allowed("git_commit") and not _has_any_grant("git_commit", args)):
                approval_id = _write_pending("git_commit", args)
                state["steps"].append({"action": "git_commit", "result": {
                    "ok": False, "reason": "approval_required",
                    "approval_id": approval_id, "message": f"Run: layla approve {approval_id}",
                }})
                state["status"] = "finished"
                break
            state["tool_calls"] += 1
            result = TOOLS["git_commit"]["fn"](**args)
            _register_exact_tool_call(state, "git_commit", decision)
            runtime_safety.log_execution("git_commit", args)
            _val = _maybe_validate_tool_output("git_commit", result)
            state["steps"].append({"action": "git_commit", "result": _val})
            if show_thinking:
                _emit_tool_step(ux_state_queue, "git_commit", _val)
            state["last_tool_used"] = "git_commit"
            _run_verification_after_tool(state, "git_commit", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # PROJECT CONTEXT (agent-readable, agent-updatable)
        # ------------------------------------------------
        if intent == "get_project_context":
            state["tool_calls"] += 1
            result = TOOLS["get_project_context"]["fn"]()
            _register_exact_tool_call(state, "get_project_context", decision)
            _val = _maybe_validate_tool_output("get_project_context", result)
            state["steps"].append({"action": "get_project_context", "result": _val})
            if show_thinking:
                _emit_tool_step(ux_state_queue, "get_project_context", _val)
            state["last_tool_used"] = "get_project_context"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "update_project_context":
            args = decision.get("args") or {} if decision else {}
            state["tool_calls"] += 1
            result = TOOLS["update_project_context"]["fn"](
                project_name=args.get("project_name", ""),
                domains=args.get("domains"),
                key_files=args.get("key_files"),
                goals=args.get("goals", ""),
                lifecycle_stage=args.get("lifecycle_stage", ""),
            )
            _register_exact_tool_call(state, "update_project_context", decision)
            _val = _maybe_validate_tool_output("update_project_context", result)
            state["steps"].append({"action": "update_project_context", "result": _val})
            if show_thinking:
                _emit_tool_step(ux_state_queue, "update_project_context", _val)
            state["last_tool_used"] = "update_project_context"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # GENERIC TOOL DISPATCH (tools not hardcoded above)
        # ------------------------------------------------
        if intent in TOOLS and intent not in (
            "reason", "write_file", "read_file", "list_dir", "git_status", "git_diff", "git_log", "git_branch",
            "grep_code", "glob_files", "search_codebase", "run_python", "apply_patch", "fetch_url", "shell",
            "mcp_tools_call",
            "json_query", "diff_files", "env_info", "regex_test", "save_note", "search_memories", "git_add",
            "git_commit", "get_project_context", "update_project_context", "understand_file",
        ):
            args = (decision.get("args") or {}) if decision else {}
            if intent == "fabrication_assist_run":
                # Runner selection is never LLM-decided. It is pinned from execution state
                # (set by file-plan engine from step.inputs, and validated against config there).
                pinned = (state.get("fabrication_assist_runner_request") or "").strip().lower()
                if not isinstance(args, dict):
                    args = {}
                else:
                    args = dict(args)
                args["runner_request"] = pinned if pinned in ("stub", "subprocess") else "stub"
            if intent in (
                "restore_file_checkpoint",
                "ingest_chat_export_to_knowledge",
                "memory_elasticsearch_search",
                "list_file_checkpoints",
            ):
                try:
                    from services.intent_routing_hints import fill_tool_args_from_goal

                    _og = (state.get("original_goal") or goal or "").strip()
                    args = fill_tool_args_from_goal(intent, _og, workspace, args)
                except Exception as _exc:
                    logger.debug("agent_loop:L3889: %s", _exc, exc_info=False)
            meta = TOOLS.get(intent, {})
            needs_approval = meta.get("require_approval", False)
            allow = allow_run if intent == "fabrication_assist_run" else (allow_write or allow_run)  # generic tools need at least one
            _session_grant_ok = _has_any_grant(intent, args)
            if needs_approval and (not allow or not runtime_safety.is_tool_allowed(intent)) and not _session_grant_ok:
                ap_args = dict(args)
                _approval_preview_diff(intent, ap_args, workspace)
                approval_id = _write_pending(intent, ap_args)
                state["steps"].append({"action": intent, "result": {
                    "ok": False, "reason": "approval_required",
                    "approval_id": approval_id, "message": f"Run: layla approve {approval_id}",
                }})
                state["status"] = "finished"
                break
            # Inject workspace/cwd for tools that expect it
            if "cwd" not in args and intent in ("run_tests", "pip_install", "pip_list", "shell_session_start", "shell_session_manage"):
                args["cwd"] = workspace
            if "repo" not in args and intent.startswith("git_"):
                args["repo"] = workspace
            if ("path" not in args or not args.get("path")) and intent in ("parse_gcode", "stl_mesh_info", "tail_file"):
                path = _extract_path(goal)
                if path:
                    args["path"] = path
            if "root" not in args and intent in ("search_replace", "rename_symbol", "search_codebase"):
                args["root"] = workspace
            _tool_timeout = cfg.get("tool_call_timeout_seconds", 60)
            _tool_t0 = time.perf_counter()
            result = _run_tool(
                intent,
                args,
                timeout_s=float(_tool_timeout),
                sandbox_root=workspace,
                allow_run=allow_run,
                conversation_id=str(state.get("conversation_id") or ""),
            )
            try:
                from services.rl_feedback import record_outcome_feedback as _rl_record

                _ms = (time.perf_counter() - _tool_t0) * 1000.0
                _ok = isinstance(result, dict) and result.get("ok", True) is not False
                _rl_record(intent, success=_ok, latency_ms=_ms)
            except Exception:
                pass
            runtime_safety.log_execution(intent, args)
            state["tool_calls"] += 1
            _register_exact_tool_call(state, intent, decision)
            _res = _maybe_validate_tool_output(intent, result)
            _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                intent, _res, workspace=workspace, cfg=cfg
            )
            if not _ok_det and bool(cfg.get("deterministic_tool_verification_auto_retry", True)):
                state.setdefault("_deterministic_retry_counts", {})
                _cnt = int(state["_deterministic_retry_counts"].get(intent) or 0)
                if _cnt < 1:
                    state["_deterministic_retry_counts"][intent] = _cnt + 1
                    result = _run_tool(
                        intent,
                        args,
                        timeout_s=float(_tool_timeout),
                        sandbox_root=workspace,
                        allow_run=allow_run,
                        conversation_id=str(state.get("conversation_id") or ""),
                    )
                    runtime_safety.log_execution(intent, dict(args) | {"_retry": True})
                    _res = _maybe_validate_tool_output(intent, result)
                    _res, _ok_det, _det_reason = _apply_deterministic_tool_verification(
                        intent, _res, workspace=workspace, cfg=cfg
                    )
                    if isinstance(_res, dict):
                        _res["_deterministic_retry"] = True
                        _res["_deterministic_retry_reason"] = _det_reason
            state["steps"].append({"action": intent, "result": _res})
            state["last_tool_used"] = intent
            _run_verification_after_tool(state, intent, _res if isinstance(_res, dict) else result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            if reasoning_mode != "none":
                lp = _edit_tool_lint_path(intent, args, workspace)
                if lp and isinstance(_res, dict) and _res.get("ok"):
                    lh = _run_auto_lint_test_fix(state, intent, _res, lp, workspace)
                    if lh:
                        goal = goal + "\n\n" + lh
            continue

        # ------------------------------------------------
        # FILE INTENT (read-only)
        # ------------------------------------------------
        if intent == "understand_file":
            path = (decision.get("args") or {}).get("path") if decision else None
            if not path:
                path = _extract_path(goal)
            if not path:
                state["status"] = "parse_failed"
                break
            state["tool_calls"] += 1
            result = TOOLS["understand_file"]["fn"](path=path)
            _register_exact_tool_call(state, "understand_file", decision)
            state["steps"].append({"action": "understand_file", "result": _maybe_validate_tool_output("understand_file", result)})
            state["last_tool_used"] = "understand_file"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # REASONING
        # ------------------------------------------------
        if intent == "reason":
            if stream_final:
                state["status"] = "stream_pending"
                state["goal_for_stream"] = goal
                state["reasoning_mode_for_stream"] = state.get("reasoning_mode", "light")
                state["precomputed_recall_for_stream"] = _precomputed_recall
                state["stream_workspace_root"] = workspace
                state["cognition_workspace_roots_for_stream"] = state.get("cognition_workspace_roots") or []
                return state
            # Section 1: context compression when token count exceeds ~75% of n_ctx (before system head)
            effective_history = conversation_history or []
            if effective_history and cfg.get("context_compression", True) and reasoning_mode != "none":
                try:
                    from services.context_manager import (
                        effective_compact_threshold_ratio,
                        summarize_history,
                    )

                    n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
                    ratio = effective_compact_threshold_ratio(cfg, n_ctx)
                    keep = int(cfg.get("context_sliding_keep_messages", 0) or 0)
                    if cfg.get("context_aggressive_compress_enabled") and keep <= 0:
                        keep = 10
                    effective_history = summarize_history(
                        effective_history,
                        n_ctx=n_ctx,
                        threshold_ratio=ratio,
                        keep_recent_messages=keep,
                    )
                except Exception as _exc:
                    logger.debug("agent_loop:L3972: %s", _exc, exc_info=False)

            # LLMLingua / heuristic per-message compression for large older messages
            # (supplements summarize_history; applied to assistant turns > 800 chars)
            if effective_history and cfg.get("llmlingua_compression_enabled", False):
                try:
                    from services.prompt_compressor import compress_conversation_history
                    _keep_recent = max(4, int(cfg.get("context_sliding_keep_messages", 4) or 4))
                    effective_history = compress_conversation_history(
                        effective_history,
                        keep_recent=_keep_recent,
                        token_budget=max(800, int(n_ctx * 0.3)),
                    )
                except Exception as _cmp_e:
                    logger.debug("llmlingua history compress failed: %s", _cmp_e)
            head = _build_system_head(
                goal=goal,
                aspect=active_aspect,
                workspace_root=workspace,
                sub_goals=state.get("sub_goals"),
                state=state,
                conversation_history=effective_history,
                reasoning_mode=state.get("reasoning_mode", "light"),
                _precomputed_recall=_precomputed_recall,
                persona_focus_id=persona_focus_id,
                cognition_workspace_roots=state.get("cognition_workspace_roots"),
                packed_context=state.get("packed_context") if isinstance(state.get("packed_context"), dict) else None,
            )

            # Inject conversation history (sanitize assistant messages that are echoed instructions)
            convo_block = ""
            try:
                convo_turns = max(0, int(cfg.get("convo_turns", 0)))
            except (TypeError, ValueError):
                convo_turns = 0
            if convo_turns > 0 and effective_history:
                name = active_aspect.get("name", "Layla")
                turns = effective_history[-convo_turns:]
                n_turns = len(turns)
                lines = []
                for i, t in enumerate(turns):
                    role = t.get("role", "")
                    # Recent turns (last 2) get more context; older turns are compressed.
                    turns_from_end = n_turns - i
                    max_chars = 600 if turns_from_end <= 2 else 220
                    content_t = (t.get("content") or "")[:max_chars].strip()
                    if role == "user":
                        lines.append(f"User: {content_t}")
                    else:
                        if "system is under load" in content_t.lower():
                            content_t = "I couldn't reply just then."
                        elif (content_t.startswith("[") and "You are" in content_t) or ("you are layla" in content_t.lower() and ("use the identity" in content_t.lower() or "rules below" in content_t.lower())):
                            content_t = _SANITIZED_PLACEHOLDER
                        elif _is_junk_reply(content_t):
                            content_t = _SANITIZED_PLACEHOLDER
                        lines.append(f"{name}: {content_t}")
                convo_block = "\n".join(lines)

            # Deliberation or standard prompt
            deliberate = show_thinking or orchestrator.should_deliberate(goal, active_aspect)
            if deliberate:
                prompt = orchestrator.build_deliberation_prompt(
                    message=goal,
                    active_aspect=active_aspect,
                    context=_enrich_deliberation_context(context),
                )
                if head:
                    prompt = head + "\n\n" + prompt
                if convo_block:
                    prompt = prompt + f"\n\nRecent conversation:\n{convo_block}"
            else:
                prompt = orchestrator.build_standard_prompt(
                    message=goal,
                    aspect=active_aspect,
                    context=context,
                    head=head,
                    convo_block=convo_block,
                )

            max_tok = cfg.get("completion_max_tokens", 256)
            out = run_completion(prompt, max_tokens=max_tok, temperature=temperature, stream=False)
            if isinstance(out, str):
                out = {"choices": [{"text": out}]}
            if isinstance(out, dict):
                text = (out.get("choices") or [{}])[0].get("text") or (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            else:
                text = ""
            text = (text or "").strip()
            text = truncate_at_next_user_turn(text)

            # Strip when model echoes the system head (e.g. "You are Layla. Use the identity..." or "nyou are Layla...")
            # Normalize leading junk (e.g. "n") so we detect the echo
            if text and text[0].lower() == "n" and len(text) > 4 and text[1:].strip().lower().startswith("you are layla"):
                text = text[1:].strip()
            paragraphs = text.split("\n\n")
            while paragraphs and paragraphs[0].strip():
                first = paragraphs[0].strip().lower()
                if first.startswith("you are layla") and ("use the identity" in first or "rules below" in first):
                    paragraphs.pop(0)
                else:
                    break
            text = "\n\n".join(paragraphs).strip()

            # Strip all echoed "[NAME] (You are...)" blocks (no "). " required; repeat until clean)
            import re as _re_echo
            # Match "[NAME] (You are ..." until "). " or next echo or "assistant:" or "\n\n" or end
            _echo_pat = _re_echo.compile(
                r"\s*\[[\w\s]+\]\s*\(You are[\s\S]*?(?=\)\.\s|\s*\[[\w\s]+\]\s*\(You are|\s*assistant\s*:|\n\n|\Z)",
                _re_echo.IGNORECASE | _re_echo.DOTALL,
            )
            for _ in range(20):
                prev = text
                text = _echo_pat.sub("", text, count=1).strip()
                if text == prev:
                    break
            # Strip leading "assistant: " if present
            if _re_echo.match(r"^\s*assistant\s*:\s*", text, _re_echo.IGNORECASE):
                text = _re_echo.sub(r"^\s*assistant\s*:\s*", "", text, count=1, flags=_re_echo.IGNORECASE).strip()
            # Strip repeated "assistant: I replied." so it never gets saved or shown
            for _ in range(50):
                prev = text
                text = _re_echo.sub(r"^\s*assistant\s*:\s*I\s+replied\.\s*", "", text, count=1, flags=_re_echo.IGNORECASE).strip()
                if text == prev:
                    break
            if _is_junk_reply(text):
                text = ""
            # Strip line-by-line any remaining instruction-like lines at start
            lines = text.split("\n")
            while lines:
                first = lines[0].strip()
                if _re_echo.match(r"^\[[\w\s]+\]\s*\(?", first) or first.startswith("[ACTIVE ASPECT:"):
                    lines.pop(0)
                    continue
                if first.startswith("You are ") and ("aspect" in first.lower() or " the " in first[:80]):
                    lines.pop(0)
                    continue
                if first.lower() in ("assistant:", "assistant", "i replied."):
                    lines.pop(0)
                    continue
                if _is_junk_reply(first):
                    lines.pop(0)
                    continue
                break
            text = "\n".join(lines).strip()
            if not text or text.lower().strip() == "assistant:" or _is_junk_reply(text):
                text = ""

            # Refusal: if aspect can refuse and output starts with [REFUSED: ...], do not run tools
            refused = False
            refusal_reason = ""
            if active_aspect.get("can_refuse") or active_aspect.get("will_refuse"):
                import re as _re
                m = _re.match(r"^\s*\[REFUSED:\s*(.+?)\]\s*", text, _re.DOTALL | _re.IGNORECASE)
                if m:
                    refusal_reason = m.group(1).strip()
                    text = _re.sub(r"^\s*\[REFUSED:\s*.+?\]\s*", "", text, flags=_re.DOTALL | _re.IGNORECASE).strip()
                    refused = True
            state["refused"] = refused
            state["refusal_reason"] = refusal_reason

            # Reflection: once per run, after pivot/reframe, ask alignment (guidance only)
            if state.get("reflection_pending") and not state.get("reflection_asked") and text:
                text = text.rstrip() + "\n\nDoes this direction align with your goals?"
                state["reflection_asked"] = True

            # Earned title: if output ends with [EARNED_TITLE: ...], parse and save
            import re as _re_et
            et_match = _re_et.search(r"\[EARNED_TITLE:\s*(.+?)\]\s*$", text, _re_et.IGNORECASE)
            if et_match:
                from layla.memory.db import save_earned_title
                try:
                    save_earned_title(active_aspect.get("id", ""), et_match.group(1).strip())
                except Exception as _exc:
                    logger.debug("agent_loop:L4130: %s", _exc, exc_info=False)
                text = _re_et.sub(r"\s*\[EARNED_TITLE:\s*.+?\]\s*$", "", text, flags=_re_et.IGNORECASE).strip()

            # Research mission: treat question-to-user as incomplete; continue until full output
            if state.get("research_lab_root") and not refused and state.get("status") != "timeout":
                if _research_response_asks_user(text):
                    goal = (
                        state["original_goal"]
                        + "\n\n[Tool results so far]:\n"
                        + _format_steps(state["steps"])
                        + "\n\n[System: Your last response asked the user a question. In this mission you must not ask questions. Produce the full structured output now: System Understanding, Weakness Map, Upgrade Opportunities, Lens Case Study, Suggested Roadmap.]"
                    )
                    continue

            text = _polish_output(text, cfg)
            # Layla v3: optional inline initiative suggestion (no extra LLM call).
            try:
                cfg_inline = runtime_safety.load_config()
                if cfg_inline.get("inline_initiative_enabled", False):
                    from services.maturity_engine import get_state as _get_maturity_state

                    ms = _get_maturity_state()
                    if ms.phase in ("adept", "veteran", "transcendent"):
                        from services.initiative_inline import maybe_append_inline_suggestion

                        text = maybe_append_inline_suggestion(text, state=state, cfg=cfg_inline)
            except Exception as _exc:
                logger.debug("agent_loop:inline_initiative failed: %s", _exc, exc_info=False)

            # Strict completion gate: retry instead of returning low-quality output.
            try:
                cfg_gate = runtime_safety.load_config()
                if bool(cfg_gate.get("completion_gate_enabled", False)):
                    from services.output_quality import passes_completion_gate

                    ok_gate, reasons = passes_completion_gate(goal=state.get("original_goal") or goal, text=text, state=state, cfg=cfg_gate)
                    state["completion_gate_passed"] = bool(ok_gate)
                    state["completion_gate_reasons"] = reasons[:6]
                    try:
                        max_r = int(cfg_gate.get("completion_gate_max_retries", 1) or 1)
                    except (TypeError, ValueError):
                        max_r = 1
                    max_r = max(0, min(2, max_r))
                    cur_r = int(state.get("completion_gate_retries") or 0)
                    if not ok_gate and cur_r < max_r and state.get("status") != "timeout":
                        state["completion_gate_retries"] = cur_r + 1
                        state.setdefault("steps", []).append(
                            {
                                "action": "completion_gate",
                                "result": {
                                    "ok": False,
                                    "reason": "completion_gate_failed",
                                    "reasons": reasons[:6],
                                    "retry": True,
                                },
                            }
                        )
                        # Re-enter the loop with a strict instruction.
                        goal = (
                            (state.get("original_goal") or goal)
                            + "\n\n[System: Your last response failed the completion gate for these reasons: "
                            + ", ".join(reasons[:4])
                            + ". Produce a correct, complete response now. Do not restate the goal.]\n"
                        )
                        continue
                    if not ok_gate and cur_r >= max_r:
                        # Hard stop: return structured failure instead of garbage.
                        text = (
                            "I couldn't meet the completion quality gate within the retry budget.\n\n"
                            "Structured failure:\n"
                            f"- reasons: {', '.join(reasons[:6]) or 'unknown'}\n"
                            "- suggested_next: simplify the request, reduce scope, or provide a specific file/path/expected output.\n"
                        )
            except Exception as _exc:
                logger.debug("completion gate failed open: %s", _exc, exc_info=False)
            state["steps"].append({
                "action": "reason",
                "result": text,
                "deliberated": deliberate,
                "aspect": active_aspect.get("id"),
            })
            state["status"] = "finished"

            # Save Echo aspect memory after any reply ÃÃÃ¶ Echo always tracks
            if text and not refused:
                try:
                    _maybe_save_echo_memory(
                        aspect_id=active_aspect.get("id", ""),
                        user_msg=state["original_goal"],
                        reply=text,
                        conversation_history=conversation_history or [],
                    )
                except Exception as _exc:
                    logger.debug("agent_loop:L4163: %s", _exc, exc_info=False)
            break

        # D5: After any step, if the last tool result is approval_required or timed_out,
        # inject a synthetic cancel message so the model doesn't hallucinate the result.
        _last_step = state["steps"][-1] if state.get("steps") else None
        if _last_step:
            _last_res = _last_step.get("result", {})
            _last_reason = _last_res.get("reason") if isinstance(_last_res, dict) else ""
            _last_tool_name = _last_step.get("action", "tool")
            if _last_reason == "approval_required" and conversation_history is not None:
                _inject_cancel_message(conversation_history, _last_tool_name, "pending operator approval")
            elif isinstance(_last_res, dict) and _last_res.get("timed_out") and conversation_history is not None:
                _inject_cancel_message(conversation_history, _last_tool_name, "timed out")

        state["depth"] += 1

        # Resource-aware chunking: after each tool call, yield if system is under pressure.
        # high load ÃÃ¥Ã sleep briefly and continue; critical (2 consecutive) ÃÃ¥Ã checkpoint and pause.
        if state["tool_calls"] > 0 and state["tool_calls"] % 2 == 0:
            try:
                _load = classify_load()
                _load_level = _load.get("level", "ok")
                if _load_level in ("high", "critical"):
                    _consecutive_high = state.get("_consecutive_high_load", 0) + 1
                    state["_consecutive_high_load"] = _consecutive_high
                    sleep_s = 5.0 if _load_level == "critical" else 2.0
                    logger.info("resource_chunking: load=%s consecutive=%d sleeping=%.0fs", _load_level, _consecutive_high, sleep_s)
                    time.sleep(sleep_s)
                    if _load_level == "critical" and _consecutive_high >= 2:
                        # Checkpoint and pause ÃÃÃ¶ let the UI offer a Resume button
                        state["checkpoint"] = {
                            "steps": list(state.get("steps", [])),
                            "goal": goal,
                            "original_goal": state.get("original_goal", goal),
                            "tool_calls": state["tool_calls"],
                            "depth": state["depth"],
                        }
                        state["status"] = "paused_high_load"
                        break
                else:
                    state["_consecutive_high_load"] = 0
            except Exception as _re:
                logger.debug("resource_chunking check failed: %s", _re)

    # Fallback: when a tool handler couldn't extract required arguments (e.g. file
    # path from a conversational message), fall back to a proper LLM response instead
    # of returning the opaque "I couldn't understand the request" error.
    if state.get("status") == "parse_failed":
        logger.info("parse_failed fallback: generating conversational response for %r", (state.get("original_goal") or "")[:120])
        try:
            _fb_head = _build_system_head(
                goal=state.get("original_goal") or goal,
                aspect=active_aspect,
                workspace_root=workspace,
                sub_goals=state.get("sub_goals"),
                state=state,
                conversation_history=conversation_history or [],
                reasoning_mode=state.get("reasoning_mode", "light"),
                _precomputed_recall=_precomputed_recall,
                persona_focus_id=persona_focus_id,
                cognition_workspace_roots=state.get("cognition_workspace_roots"),
                packed_context=state.get("packed_context") if isinstance(state.get("packed_context"), dict) else None,
            )
            _fb_prompt = orchestrator.build_standard_prompt(
                message=state.get("original_goal") or goal,
                aspect=active_aspect,
                context=context,
                head=_fb_head,
                convo_block="",
            )
            if stream_final:
                state["status"] = "stream_pending"
                state["goal_for_stream"] = state.get("original_goal") or goal
                state["reasoning_mode_for_stream"] = state.get("reasoning_mode", "light")
                state["precomputed_recall_for_stream"] = _precomputed_recall
                state["stream_workspace_root"] = workspace
                state["cognition_workspace_roots_for_stream"] = state.get("cognition_workspace_roots") or []
            else:
                max_tok = cfg.get("completion_max_tokens", 256)
                _fb_out = run_completion(_fb_prompt, max_tokens=max_tok, temperature=temperature, stream=False)
                _fb_text = ""
                if isinstance(_fb_out, str):
                    _fb_text = _fb_out
                elif isinstance(_fb_out, dict):
                    _fb_text = (_fb_out.get("choices") or [{}])[0].get("text") or (_fb_out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                _fb_text = (_fb_text or "").strip()
                _fb_text = truncate_at_next_user_turn(_fb_text)
                _fb_text = _polish_output(_fb_text, cfg)
                if _fb_text and not _is_junk_reply(_fb_text):
                    state["steps"].append({
                        "action": "reason",
                        "result": _fb_text,
                        "deliberated": False,
                        "aspect": active_aspect.get("id"),
                    })
                    state["status"] = "finished"
        except Exception as _fb_exc:
            logger.warning("parse_failed fallback LLM call failed: %s", _fb_exc)

    # D5: runtime timeout also warrants a cancel message
    if state.get("status") == "timeout" and conversation_history is not None:
        _inject_cancel_message(conversation_history, "agent", "hit runtime limit")

    if state.get("status") == "finished":
        try:
            if runtime_safety.load_config().get("pipeline_enforcement_enabled", True):
                state["pipeline_stage"] = "REFLECT"
        except Exception:
            state["pipeline_stage"] = "REFLECT"
        try:
            from services.outcome_evaluation import evaluate_outcome_structured
            from shared_state import set_last_outcome_evaluation

            ev_struct = evaluate_outcome_structured(state)
            state["outcome_evaluation"] = ev_struct
            cid_fin = (state.get("conversation_id") or "").strip()
            if cid_fin:
                set_last_outcome_evaluation(cid_fin, ev_struct)
            # Mandatory outcome recording for feedback loop: persist strategy patterns
            try:
                from layla.memory import strategy_stats as _strategy_stats

                _g = (state.get("original_goal") or state.get("goal") or "").strip()
                _task_type = (_g.replace("\n", " ")[:120] if _g else "general") or "general"
                _strat = str(active_aspect.get("id") or "morrigan")[:120]
                _strategy_stats.record_strategy_stat(_task_type, _strat, success=bool(ev_struct.get("success")))
                state["strategy_stats_recorded"] = True
            except Exception as _ss_exc:
                logger.warning("strategy_stats record failed (outcome feedback at risk): %s", _ss_exc)
        except Exception as _ev_exc:
            logger.warning("outcome evaluation failed (feedback loop at risk): %s", _ev_exc)
        _save_outcome_memory(state)
        try:
            from layla.memory.distill import run_distill_after_outcome
            run_distill_after_outcome(n=50)
        except Exception as e:
            logger.debug("distill after outcome failed: %s", e)
        # Auto-learning: extract and persist 1-2 insights from every substantive exchange
        final_text = ""
        for s in reversed(state.get("steps", [])):
            if s.get("action") == "reason":
                r = s.get("result", "")
                final_text = r if isinstance(r, str) else ""
                break
        if final_text and not state.get("refused") and len(final_text.strip()) >= 80:
            import threading as _t
            _t.Thread(
                target=_auto_extract_learnings,
                args=(state.get("original_goal", ""), final_text, active_aspect.get("id", "")),
                daemon=True,
                name="auto-learn",
            ).start()
    if research_mode:
        set_effective_sandbox(None)

    # Persist routing telemetry (local-only) for debugging misroutes and regressions.
    try:
        rd = state.get("route_decision") if isinstance(state.get("route_decision"), dict) else {}
        from layla.memory.routing_telemetry import log_route_telemetry

        log_route_telemetry(
            conversation_id=str(state.get("conversation_id") or "") or None,
            goal=str(state.get("original_goal") or state.get("goal") or ""),
            task_type=str(rd.get("task_type") or ""),
            is_meta_self=bool(rd.get("is_meta_self")),
            has_workspace_signals=bool(rd.get("has_workspace_signals")),
            decision_action=str((state.get("last_decision") or {}).get("action") or ""),
            decision_tool=str((state.get("last_decision") or {}).get("tool") or ""),
            preflight_ok=state.get("preflight_ok") if "preflight_ok" in state else None,
            preflight_reason=str(state.get("preflight_reason") or "") or None,
            final_status=str(state.get("status") or "") or None,
            parse_failed=bool(state.get("status") == "parse_failed"),
        )
    except Exception:
        pass

    _emit_run_telemetry(state, state.get("status") in ("finished", "plan_completed"))

    # Response envelope (stable keys for UI/API consumers).
    try:
        if state.get("status") in ("finished", "plan_completed"):
            state["steps_taken"] = list(state.get("steps") or [])
            if "completion_gate_passed" not in state:
                state["completion_gate_passed"] = True
            if "retry_count" not in state:
                state["retry_count"] = int(state.get("completion_gate_retries") or 0)
    except Exception:
        pass

    return state
