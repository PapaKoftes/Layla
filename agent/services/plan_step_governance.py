"""Step outcome validation, low-confidence heuristics, and pre-approval plan checks."""

from __future__ import annotations

import json
from typing import Any

from services.plan_schema import Plan
from services.plan_step_result_models import coerce_tool_result

_PLAN_GOVERNANCE_MUTATING_TYPES = frozenset({"edit", "test", "build", "refactor", "cad"})


def _plan_governance_require_nonempty_tools() -> bool:
    try:
        import runtime_safety

        c = runtime_safety.load_config()
        return bool(c.get("plan_governance_hard_mode")) or bool(c.get("plan_governance_require_nonempty_step_tools"))
    except Exception:
        return False


def _plan_governance_reject_auto_filled() -> bool:
    try:
        import runtime_safety

        c = runtime_safety.load_config()
        return bool(c.get("plan_governance_hard_mode")) or bool(c.get("plan_governance_reject_auto_filled_tools"))
    except Exception:
        return False


def _plan_governance_strict_tool_evidence() -> bool:
    """Require structured tool results to look like real writes / test runs (not only ok:true)."""
    try:
        import runtime_safety

        c = runtime_safety.load_config()
        return bool(c.get("plan_governance_hard_mode")) or bool(c.get("plan_governance_strict_tool_evidence"))
    except Exception:
        return False


def _step_marks_tools_auto_filled(step: Any) -> bool:
    return bool(getattr(step, "tools_auto_filled", False) or getattr(step, "_tools_auto_filled", False))


_EDIT_WRITE_ACTIONS = frozenset({"apply_patch", "write_file", "write_files_batch"})


def _substantive_write_tool_result(result: dict[str, Any], action: str) -> bool:
    """True when the tool dict looks like a real write/patch (paths, batch count), not a bare ok:true."""
    coerced = coerce_tool_result(action, result)
    if coerced is not None:
        result = coerced
    if result.get("ok") is not True:
        return False
    if action == "write_file":
        return bool(str(result.get("path") or "").strip())
    if action == "apply_patch":
        return bool(str(result.get("path") or "").strip())
    if action == "write_files_batch":
        written = result.get("written")
        if isinstance(written, list) and len(written) > 0:
            return True
        try:
            return int(result.get("count") or 0) > 0
        except (TypeError, ValueError):
            return False
    return False


def _substantive_run_tests_result(result: dict[str, Any]) -> bool:
    """True when run_tests output indicates pytest/unittest actually ran with success evidence."""
    coerced = coerce_tool_result("run_tests", result)
    if coerced is not None:
        result = coerced
    if result.get("ok") is not True:
        return False
    rc = result.get("returncode")
    if rc is not None and int(rc) != 0:
        return False
    try:
        passed = int(result.get("passed") or 0)
        failed = int(result.get("failed") or 0)
    except (TypeError, ValueError):
        passed, failed = 0, 0
    if passed > 0 or failed > 0:
        return True
    out = str(result.get("output") or result.get("stdout") or "")[:12000]
    ol = out.lower()
    if "pytest" in ol or "unittest" in ol or "tox" in ol or "nose" in ol:
        return True
    if "skipped" in ol and len(out.strip()) > 60:
        return True
    if "no tests ran" in ol or "collected 0 items" in ol:
        return True
    return len(out.strip()) > 200


def _substantive_shell_test_result(result: dict[str, Any]) -> bool:
    if result.get("ok") is not True:
        return False
    rc = result.get("returncode")
    if rc is not None and int(rc) != 0:
        return False
    blob = json.dumps(result, default=str).lower()
    if not any(x in blob for x in ("pytest", "unittest", "tox", "nose")):
        return False
    out = str(result.get("stdout") or result.get("stderr") or result.get("output") or "")[:8000]
    return len(out.strip()) >= 40


def _edit_has_successful_write_trace(steps_list: list[Any]) -> bool:
    strict = _plan_governance_strict_tool_evidence()
    for e in steps_list:
        if not isinstance(e, dict):
            continue
        act = str(e.get("action") or "").strip()
        if act not in _EDIT_WRITE_ACTIONS:
            continue
        r = e.get("result")
        if not isinstance(r, dict) or r.get("ok") is not True:
            continue
        if strict:
            if _substantive_write_tool_result(r, act):
                return True
        else:
            return True
    return False


def _test_has_successful_run_trace(steps_list: list[Any]) -> bool:
    strict = _plan_governance_strict_tool_evidence()
    for e in steps_list:
        if not isinstance(e, dict):
            continue
        r = e.get("result")
        if not isinstance(r, dict) or r.get("ok") is not True:
            continue
        act = str(e.get("action") or "").strip()
        if act == "run_tests":
            if strict:
                if _substantive_run_tests_result(r):
                    return True
            else:
                return True
        if act in ("shell", "run_python"):
            blob = json.dumps(r, default=str).lower()
            if not any(x in blob for x in ("pytest", "unittest", "tox", "nose")):
                continue
            if strict:
                if _substantive_shell_test_result(r):
                    return True
            else:
                return True
    return False


_FATAL_RESPONSE_PHRASES = (
    "traceback (most recent call last)",
    "traceback (most recent",
    "unhandled exception",
    "segmentation fault",
    "internal server error",
    "fatal:",
    "errno ",
    "stack overflow",
    "out of memory",
)


def _fatal_error_signal_in_response(resp_text: str) -> bool:
    low = (resp_text or "").lower()
    return any(p in low for p in _FATAL_RESPONSE_PHRASES)


def _required_tool_names(step: Any) -> list[str]:
    raw = getattr(step, "tools", None) or []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(t).strip() for t in raw if str(t).strip()]


def _listed_tools_were_invoked(required: list[str], steps_list: list[Any]) -> bool:
    if not required:
        return True
    if not steps_list:
        return False
    invoked: set[str] = set()
    for e in steps_list:
        if not isinstance(e, dict):
            continue
        act = str(e.get("action") or "").strip()
        if act:
            invoked.add(act)
    for r in required:
        if r in invoked:
            return True
        for inv in invoked:
            if inv == r or (inv and r in inv) or (r and inv in r):
                return True
    return False


def low_confidence_response(resp: dict[str, Any]) -> bool:
    """Heuristic: empty/short reply, refusal, or explicit uncertainty."""
    if resp.get("refused"):
        return True
    if resp.get("ok") is False:
        return True
    txt = (resp.get("response") or "").strip()
    if not txt or len(txt) < 20:
        return True
    low = txt.lower()
    hedges = (
        "i'm not sure",
        "i am not sure",
        "cannot determine",
        "unable to complete",
        "unable to",
        "i don't know",
        "i do not know",
        "unclear if",
        "unclear whether",
        "as an ai language model",
        "i cannot verify",
        "can't verify",
        "cannot verify",
        "no evidence",
        "insufficient information",
    )
    return any(h in low for h in hedges)


def _final_reply_text(resp: dict[str, Any]) -> str:
    r = str(resp.get("response") or "").strip()
    if r:
        return r
    st = resp.get("state") if isinstance(resp.get("state"), dict) else {}
    steps = st.get("steps") or []
    if not isinstance(steps, list):
        return ""
    for s in reversed(steps):
        if isinstance(s, dict) and str(s.get("action") or "") == "reason":
            t = s.get("result")
            if isinstance(t, str) and t.strip():
                return t.strip()
    return ""


def _check_success_criteria(criteria: str, text: str) -> tuple[bool, str]:
    """Cheap deterministic checks for optional plan step success_criteria."""
    crit_raw = (criteria or "").strip()
    if not crit_raw:
        return True, ""
    blob = text.lower()
    c = crit_raw.lower()
    if c in ("nonempty", "nonempty_reply", "nonempty_response"):
        if len(text.strip()) >= 20:
            return True, ""
        return False, "success_criteria:nonempty_failed"
    if c.startswith("substring:"):
        sub = crit_raw.split(":", 1)[1].strip()
        if sub and sub.lower() in blob:
            return True, ""
        return False, f"success_criteria:substring_missing:{sub[:60]}"
    if crit_raw.lower() in blob or crit_raw in text:
        return True, ""
    return False, "success_criteria:text_match_failed"


def validate_step_outcome(step: Any, resp: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, reason). Requires tool traces to be successful; type-specific checks."""
    if resp.get("refused"):
        return False, "refused"
    if resp.get("ok") is False:
        return False, "response_ok_false"
    if _plan_governance_reject_auto_filled() and _step_marks_tools_auto_filled(step):
        return False, "signal:step_tools_were_auto_filled"

    st = resp.get("state") if isinstance(resp.get("state"), dict) else {}
    raw_steps = st.get("steps") or []
    steps_list: list[Any] = raw_steps if isinstance(raw_steps, list) else []

    for entry in steps_list:
        if not isinstance(entry, dict):
            continue
        r = entry.get("result")
        if isinstance(r, dict) and r.get("ok") is False:
            reason = str(r.get("reason") or r.get("error") or "tool_error")
            return False, f"tool:{entry.get('action')}:{reason}"

    resp_body = str(resp.get("response") or "")
    if _fatal_error_signal_in_response(resp_body):
        return False, "signal:fatal_error_phrase_in_response"

    sc = (getattr(step, "success_criteria", None) or "").strip()
    if sc:
        combined = resp_body or _final_reply_text(resp)
        if _fatal_error_signal_in_response(combined):
            return False, "success_criteria:blocked_by_fatal_phrase"
        sok, sreason = _check_success_criteria(sc, combined)
        if not sok:
            return False, sreason

    req_tools = _required_tool_names(step)
    if req_tools:
        if not steps_list:
            return False, "signal:tools_required_but_no_tool_steps"
        if not _listed_tools_were_invoked(req_tools, steps_list):
            return False, "signal:required_tool_not_invoked"

    blob = json.dumps(steps_list, default=str) + "\n" + resp_body
    bl = blob.lower()
    stype = (getattr(step, "type", None) or "analysis").strip().lower()
    if stype in ("", "task"):
        stype = "analysis"

    strict_ev = _plan_governance_strict_tool_evidence()
    if strict_ev and stype in ("edit", "test") and not steps_list:
        return False, "strict:requires_tool_traces"

    if stype == "edit":
        if steps_list:
            if not _edit_has_successful_write_trace(steps_list):
                return False, "edit_step_validation:no_successful_write_tool_trace"
            return True, ""
        if not any(
            k in bl
            for k in (
                "patch",
                "apply_patch",
                "write_file",
                "diff",
                "unified diff",
                "changed",
                "file changed",
                "updated file",
            )
        ):
            return False, "edit_step_validation:no_patch_or_write_signal"

    if stype == "test":
        if steps_list:
            if not _test_has_successful_run_trace(steps_list):
                return False, "test_step_validation:no_successful_test_tool_trace"
            return True, ""
        ok_signals = (
            "passed",
            "exit code 0",
            "exit code: 0",
            '"ok": true',
            "'ok': true",
            "tests passed",
            "all tests passed",
            "0 failed",
            "0 errors",
        )
        if "run_tests" in bl or "pytest" in bl:
            if any(sig in bl for sig in ok_signals):
                return True, ""
            if any(
                x in bl
                for x in (
                    "failed",
                    "error",
                    "exit code 1",
                    "exit code: 1",
                    '"ok": false',
                    "traceback",
                )
            ):
                return False, "test_step_validation:negative_test_outcome"
            return True, ""
        if any(sig in bl for sig in ok_signals):
            return True, ""
        return False, "test_step_validation:no_test_signal"

    return True, ""


def validate_file_plan_before_approval(plan: Plan) -> list[str]:
    """Block approve when dependencies or tools are invalid; keep plans inspectable."""
    errs: list[str] = []
    if not plan.steps:
        errs.append("no_steps")
        return errs

    id_set = {s.id for s in plan.steps if getattr(s, "id", None)}
    for s in plan.steps:
        sid = getattr(s, "id", "") or "?"
        title = (getattr(s, "title", None) or "").strip()
        desc = (getattr(s, "description", None) or "").strip()
        if not title and not desc:
            errs.append(f"step_empty:{sid}")
        for dep in getattr(s, "depends_on", None) or []:
            if dep not in id_set:
                errs.append(f"unknown_dependency:{sid}->{dep}")
        try:
            from layla.tools.registry import TOOLS

            for tn in getattr(s, "tools", None) or []:
                t = str(tn).strip()
                if t and t not in TOOLS:
                    errs.append(f"unknown_tool:{sid}:{t}")
        except Exception:
            pass
        if _plan_governance_require_nonempty_tools():
            st = str(getattr(s, "type", "") or "").strip().lower()
            if st in _PLAN_GOVERNANCE_MUTATING_TYPES:
                tl = list(getattr(s, "tools", None) or [])
                if not [x for x in tl if str(x).strip()]:
                    errs.append(f"step_missing_tools:{sid}:{st}")
        if len(desc) > 12000:
            errs.append(f"step_description_too_long:{sid}")
    return errs


def validate_sqlite_plan_before_approval(plan_dict: dict[str, Any]) -> list[str]:
    """Same checks for `layla_plans` rows (steps are dicts)."""
    errs: list[str] = []
    steps = plan_dict.get("steps") or []
    if not isinstance(steps, list) or not steps:
        errs.append("no_steps")
        return errs

    ids: set[str] = set()
    for s in steps:
        if isinstance(s, dict) and s.get("id") is not None:
            ids.add(str(s["id"]))

    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            errs.append(f"step_{i}_not_object")
            continue
        desc = (s.get("description") or s.get("task") or "").strip()
        if not desc:
            errs.append(f"step_{i}_empty_description")
        for dep in s.get("depends_on") or []:
            if str(dep) not in ids:
                errs.append(f"step_{i}_unknown_dependency:{dep}")
        tools = s.get("tools") or []
        if isinstance(tools, list):
            try:
                from layla.tools.registry import TOOLS

                for tn in tools:
                    t = str(tn).strip()
                    if t and t not in TOOLS:
                        errs.append(f"step_{i}_unknown_tool:{t}")
            except Exception:
                pass
        if _plan_governance_require_nonempty_tools():
            st = str(s.get("type") or s.get("role") or "").strip().lower()
            if st in _PLAN_GOVERNANCE_MUTATING_TYPES:
                tls = s.get("tools") if isinstance(s.get("tools"), list) else []
                if not [x for x in tls if str(x).strip()]:
                    errs.append(f"step_{i}_missing_tools:{st}")
    return errs


def suggest_sqlite_plan_improvements(steps: list[Any]) -> list[str]:
    """Non-blocking hints after PATCH; does not reject plans."""
    out: list[str] = []
    if not isinstance(steps, list):
        return out
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        st = str(s.get("type") or s.get("role") or "").lower()
        tools = s.get("tools") if isinstance(s.get("tools"), list) else []
        desc = (s.get("description") or s.get("task") or "").strip()
        if st in ("edit", "refactor", "build") and len(tools) == 0:
            out.append(f"step_{i}: consider listing tools (e.g. read_file, apply_patch) for governance validation")
        if st == "test" and len(tools) == 0:
            out.append(f"step_{i}: consider tools: [run_tests] for clearer validation")
        if len(desc) < 12:
            out.append(f"step_{i}: description is very short; expand for reliable execution")
    return out[:24]
