"""
Normalize and annotate tool return dicts (safety / hygiene for agent loop).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Keys that indicate a non-empty successful payload (exclude bool `ok` itself).
_PAYLOAD_KEYS = (
    "content",
    "stdout",
    "stderr",
    "output",
    "matches",
    "written",
    "path",
    "reply",
    "results",
    "entries",
    "summary",
    "text",
    "data",
    "lines",
    "returncode",
    "count",
    "files_copied",
    "bytes",
)


def _has_meaningful_payload(result: dict[str, Any]) -> bool:
    for k in _PAYLOAD_KEYS:
        if k not in result:
            continue
        v = result[k]
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, (list, dict, set, tuple)) and len(v) > 0:
            return True
        if isinstance(v, bool) and k == "ok":
            continue
        if isinstance(v, (int, float)) and k == "returncode":
            return True
        if isinstance(v, (int, float)) and v != 0:
            return True
    return False


def validate_tool_output(tool_name: str, result: Any) -> dict[str, Any]:
    """
    Ensure tool results are dict-shaped; add error when ok is false but no error;
    flag suspicious ok-with-empty payloads.
    """
    _ = tool_name
    if not isinstance(result, dict):
        return {"ok": False, "error": "tool_output_invalid", "message": "non-dict result"}
    out = dict(result)
    if not out.get("ok") and not out.get("error") and not out.get("reason"):
        out["error"] = "tool_returned_no_ok"
    if out.get("ok") and not _has_meaningful_payload(out) and not out.get("_empty_output"):
        out["_empty_output"] = True
    return out


_STDERR_FATAL_PATTERNS = (
    re.compile(r"\bTraceback\b", re.IGNORECASE),
    re.compile(r"\bException\b", re.IGNORECASE),
    re.compile(r"\bError\b", re.IGNORECASE),
    re.compile(r"\bFAILED\b", re.IGNORECASE),
)


def deterministic_verify_tool_result(
    tool_name: str,
    result: Any,
    *,
    workspace_root: str = "",
) -> dict[str, Any]:
    """
    Deterministic semantic verification for common tools.

    Returns a dict:
      {ok: bool, reason: str, details: {...}}

    Never raises; failures are returned as ok=False.
    """
    if not isinstance(result, dict):
        return {"ok": False, "reason": "non_dict_result", "details": {"type": type(result).__name__}}
    if not result.get("ok"):
        # Tool already reported failure; do not overwrite.
        return {"ok": False, "reason": "tool_reported_failure", "details": {"error": result.get("error") or result.get("reason")}}

    ws = Path(workspace_root).resolve() if workspace_root else None

    def _resolve_path(p: str) -> Path | None:
        if not p:
            return None
        try:
            pp = Path(p)
            if not pp.is_absolute() and ws is not None:
                pp = ws / pp
            return pp.resolve()
        except Exception:
            return None

    tn = (tool_name or "").strip()
    try:
        if tn in ("write_file", "replace_in_file"):
            p = str(result.get("path") or "")
            rp = _resolve_path(p)
            if rp is None:
                return {"ok": False, "reason": "missing_path", "details": {}}
            if not rp.exists():
                return {"ok": False, "reason": "file_missing_after_write", "details": {"path": str(rp)}}
            try:
                if rp.stat().st_size <= 0:
                    return {"ok": False, "reason": "file_empty_after_write", "details": {"path": str(rp)}}
            except Exception:
                # If stat fails but file exists, treat as ok.
                pass
            return {"ok": True, "reason": "ok", "details": {"path": str(rp)}}

        if tn == "apply_patch":
            p = str(result.get("path") or result.get("original_path") or "")
            rp = _resolve_path(p)
            if rp is None:
                # Some patch tools may not return a path; accept ok.
                return {"ok": True, "reason": "ok_no_path", "details": {}}
            if not rp.exists():
                return {"ok": False, "reason": "file_missing_after_patch", "details": {"path": str(rp)}}
            return {"ok": True, "reason": "ok", "details": {"path": str(rp)}}

        if tn in ("run_python", "shell"):
            rc = result.get("returncode", None)
            try:
                rc_i = int(rc) if rc is not None else None
            except Exception:
                rc_i = None
            if rc_i is None:
                return {"ok": False, "reason": "missing_returncode", "details": {}}
            if rc_i != 0:
                return {"ok": False, "reason": "nonzero_returncode", "details": {"returncode": rc_i}}
            stderr = str(result.get("stderr") or "")
            if stderr:
                for rx in _STDERR_FATAL_PATTERNS:
                    if rx.search(stderr):
                        return {"ok": False, "reason": "fatal_stderr_pattern", "details": {"pattern": rx.pattern}}
            return {"ok": True, "reason": "ok", "details": {"returncode": rc_i}}

        if tn in ("read_file", "list_dir", "grep_code", "glob_files", "fetch_url"):
            if result.get("_empty_output"):
                return {"ok": False, "reason": "empty_output", "details": {}}
            return {"ok": True, "reason": "ok", "details": {}}

        if tn == "search_replace":
            if result.get("dry_run"):
                return {"ok": True, "reason": "dry_run", "details": {}}
            find = str(result.get("find") or "")
            use_regex = bool(result.get("use_regex"))
            matches = result.get("matches") or []
            if use_regex or not find.strip():
                return {"ok": True, "reason": "regex_or_empty_find", "details": {}}
            failed: list[dict] = []
            for m in matches if isinstance(matches, list) else []:
                if not isinstance(m, dict):
                    continue
                p = str(m.get("path") or "").strip()
                if not p:
                    continue
                rp = _resolve_path(p)
                if rp is None or not rp.exists():
                    failed.append({"path": p, "reason": "missing"})
                    continue
                try:
                    txt = rp.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    failed.append({"path": str(rp), "reason": "read_failed"})
                    continue
                if find in txt:
                    failed.append({"path": str(rp), "reason": "find_still_present"})
            if failed:
                return {"ok": False, "reason": "search_replace_incomplete", "details": {"failed": failed[:8]}}
            return {"ok": True, "reason": "ok", "details": {}}

        if tn == "rename_symbol":
            if not result.get("applied"):
                return {"ok": True, "reason": "rename_dry_run", "details": {}}
            old = str(result.get("old_name") or "")
            if not old.strip():
                return {"ok": True, "reason": "no_old_name", "details": {}}
            rx_old = re.compile(r"\b" + re.escape(old) + r"\b")
            changes = result.get("changes") or []
            failed = []
            for ch in changes if isinstance(changes, list) else []:
                if not isinstance(ch, dict):
                    continue
                p = str(ch.get("path") or "").strip()
                if not p:
                    continue
                rp = _resolve_path(p)
                if rp is None or not rp.exists():
                    failed.append({"path": p, "reason": "missing"})
                    continue
                try:
                    txt = rp.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    failed.append({"path": str(rp), "reason": "read_failed"})
                    continue
                if rx_old.search(txt):
                    failed.append({"path": str(rp), "reason": "old_symbol_still_present"})
            if failed:
                return {"ok": False, "reason": "rename_symbol_incomplete", "details": {"failed": failed[:8]}}
            return {"ok": True, "reason": "ok", "details": {}}

        # --- Extended effect verifiers (Plan item 27, risk-prioritized) -------
        # The block above is the original 12. The registry below extends
        # deterministic artifact verification to the wider EFFECTFUL set
        # (writers / exec / network / dangerous tools first). Each helper runs
        # ONLY on the tool's post-execution result dict; it never re-runs the
        # tool. A helper bug degrades to "unverified" (ok=True) so a verifier
        # can never crash a turn or falsely fail a genuinely-successful tool.
        _verifier = _EFFECT_VERIFIERS.get(tn)
        if _verifier is not None:
            try:
                _verdict = _verifier(result, _resolve_path)
            except Exception as _vex:
                return {
                    "ok": True,
                    "reason": "verifier_soft_error",
                    "details": {"tool": tn, "error": str(_vex)[:200]},
                }
            if isinstance(_verdict, dict) and "ok" in _verdict:
                _verdict.setdefault("reason", "ok" if _verdict.get("ok") else "failed")
                _verdict.setdefault("details", {})
                return _verdict
            return {"ok": True, "reason": "no_verifier", "details": {}}

        # Default: no deterministic verifier for this tool.
        return {"ok": True, "reason": "no_verifier", "details": {}}
    except Exception as ex:
        return {"ok": False, "reason": "verifier_exception", "details": {"error": str(ex)[:240]}}


# ---------------------------------------------------------------------------
# Extended per-tool effect verifiers (Plan item 27)
#
# deterministic_verify_tool_result confirms the CONCRETE artifact of a
# *successful* tool result — model-free, and WITHOUT re-running the tool. The
# original 12 verifiers live inline in the function above; the helpers below
# extend that coverage to the wider effectful set, prioritized by RISK
# (dangerous / require_approval / write / exec / network tools first).
#
# Contract for every helper:
#   * input is the tool's RESULT dict, already known to carry ok=True.
#   * return {"ok": bool, "reason": str, "details": dict}.
#   * return ok=False ONLY on a POSITIVE tamper/empty signal — the promised
#     artifact key is absent, or the file / rows / commit / http-status it
#     names is provably missing, empty, or wrong. Uncertain filesystem state
#     degrades to a soft pass: a verifier must never turn a genuinely
#     successful tool into a failure.
#   * never raise; deterministic_verify_tool_result also wraps each call and
#     degrades a raised error to "unverified" (ok=True) so a verifier bug can
#     never crash a turn.
#
# Pure-informational / idempotent tools stay no_verifier on purpose, because
# "did it happen" is meaningless for them: uuid_generate, random_string,
# password_generate, timestamp_convert, string_transform, base64_tool,
# json_schema, jwt_decode, math_eval, count_tokens, and the read-only search /
# analysis tools whose success is already the payload the caller reads.

_GIT_COMMIT_SIGNATURE = re.compile(r"\[[^\]\n]*\b[0-9a-f]{7,40}\b[^\]\n]*\]")

_HASH_HEX_LENGTHS = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}


def _artifact_file_verdict(resolve_path, path_value, *, require_nonempty=True, allow_dir=False):
    """Shared check: the result names an output path that must now exist.

    A missing/blank path string is a tamper signal (ok=False). A path that
    resolves but does not exist is a missing artifact (ok=False). An
    unexpected stat error degrades to a soft pass (ok=True) rather than
    failing a tool that really did succeed.
    """
    p = str(path_value or "").strip()
    if not p:
        return {"ok": False, "reason": "missing_artifact_path", "details": {}}
    rp = resolve_path(p)
    if rp is None:
        return {"ok": False, "reason": "missing_artifact_path", "details": {"path": p}}
    try:
        if not rp.exists():
            return {"ok": False, "reason": "artifact_missing", "details": {"path": str(rp)}}
        if rp.is_dir():
            if not allow_dir:
                return {"ok": False, "reason": "artifact_not_a_file", "details": {"path": str(rp)}}
            return {"ok": True, "reason": "ok", "details": {"path": str(rp)}}
        if require_nonempty and rp.stat().st_size <= 0:
            return {"ok": False, "reason": "artifact_empty", "details": {"path": str(rp)}}
    except Exception as ex:
        return {"ok": True, "reason": "unverified_stat_error", "details": {"error": str(ex)[:160]}}
    return {"ok": True, "reason": "ok", "details": {"path": str(rp)}}


# --- file / artifact writers -----------------------------------------------

def _v_write_files_batch(result, resolve_path):
    written = result.get("written")
    if not isinstance(written, list) or not written:
        return {"ok": False, "reason": "no_files_written", "details": {}}
    count = result.get("count")
    if isinstance(count, int) and count != len(written):
        return {"ok": False, "reason": "count_mismatch",
                "details": {"count": count, "written": len(written)}}
    missing = []
    for p in written:
        v = _artifact_file_verdict(resolve_path, p, require_nonempty=False)
        if not v["ok"] and v["reason"] in ("artifact_missing", "missing_artifact_path"):
            missing.append(str(p))
    if missing:
        return {"ok": False, "reason": "written_file_missing", "details": {"missing": missing[:8]}}
    return {"ok": True, "reason": "ok", "details": {"count": len(written)}}


def _v_write_csv(result, resolve_path):
    # An empty CSV (header only, or zero rows) is legitimate — require existence
    # but not non-emptiness; the concrete artifact is (file present + row count).
    v = _artifact_file_verdict(resolve_path, result.get("path"), require_nonempty=False)
    if not v["ok"]:
        return v
    if not isinstance(result.get("rows"), int):
        return {"ok": False, "reason": "missing_row_count", "details": {}}
    return {"ok": True, "reason": "ok", "details": {"rows": result.get("rows")}}


def _v_create_svg(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("path"))


def _v_create_mermaid(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("path"))


def _v_create_archive(result, resolve_path):
    v = _artifact_file_verdict(resolve_path, result.get("output"))
    if not v["ok"]:
        return v
    try:
        import zipfile
        rp = resolve_path(str(result.get("output")))
        if rp is not None and zipfile.is_zipfile(str(rp)):
            with zipfile.ZipFile(str(rp)) as z:
                names = z.namelist()
            files_in = result.get("files")
            if isinstance(files_in, int) and files_in > 0 and not names:
                return {"ok": False, "reason": "archive_has_no_members",
                        "details": {"output": str(rp)}}
            return {"ok": True, "reason": "ok",
                    "details": {"output": str(rp), "members": len(names)}}
    except Exception as ex:
        return {"ok": True, "reason": "unverified_archive_read", "details": {"error": str(ex)[:160]}}
    return v


def _v_extract_archive(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("dest"),
                                  require_nonempty=False, allow_dir=True)


def _v_merge_pdf(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("output"))


def _v_db_backup(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("backup"))


def _v_generate_gcode(result, resolve_path):
    v = _artifact_file_verdict(resolve_path, result.get("output_path"))
    if not v["ok"]:
        return v
    if not isinstance(result.get("moves"), int):
        return {"ok": False, "reason": "missing_move_count", "details": {}}
    return {"ok": True, "reason": "ok", "details": {"moves": result.get("moves")}}


def _v_code_format(result, resolve_path):
    # path may be a file OR a directory (formatting a tree).
    return _artifact_file_verdict(resolve_path, result.get("path"),
                                  require_nonempty=False, allow_dir=True)


def _v_calendar_add_event(result, resolve_path):
    v = _artifact_file_verdict(resolve_path, result.get("path"))
    if not v["ok"]:
        return v
    if not str(result.get("summary") or "").strip():
        return {"ok": False, "reason": "missing_summary", "details": {}}
    return v


def _v_notebook_edit_cell(result, resolve_path):
    if not result.get("written"):
        return {"ok": False, "reason": "not_written", "details": {}}
    if not isinstance(result.get("cell_index"), int):
        return {"ok": False, "reason": "missing_cell_index", "details": {}}
    return _artifact_file_verdict(resolve_path, result.get("path"))


def _v_update_project_memory(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("path"))


def _v_image_resize(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("output"))


def _v_screenshot_desktop(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("path"))


def _v_tts_speak(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("output_path"))


def _v_generate_qr(result, resolve_path):
    if result.get("output"):
        return _artifact_file_verdict(resolve_path, result.get("output"))
    b64 = result.get("base64")
    if isinstance(b64, str) and b64.strip():
        return {"ok": True, "reason": "ok", "details": {"base64_len": len(b64)}}
    return {"ok": False, "reason": "no_qr_artifact", "details": {}}


def _v_extract_frames(result, resolve_path):
    n = result.get("frames_extracted")
    if not isinstance(n, int) or n <= 0:
        return {"ok": False, "reason": "no_frames_extracted", "details": {}}
    paths = result.get("frame_paths")
    if not isinstance(paths, list) or not paths:
        return {"ok": False, "reason": "no_frame_paths", "details": {}}
    return _artifact_file_verdict(resolve_path, paths[0])


# --- structured-data producers ---------------------------------------------

def _v_json_query(result, resolve_path):
    # A queried JSON value may legitimately be None / 0 / False, so assert KEY
    # PRESENCE, never truthiness.
    if "result" in result or "result_str" in result or "data" in result:
        return {"ok": True, "reason": "ok", "details": {}}
    return {"ok": False, "reason": "no_query_value", "details": {}}


def _v_sql_query(result, resolve_path):
    cols = result.get("columns")
    if not isinstance(cols, list):
        return {"ok": False, "reason": "missing_columns", "details": {}}
    rows = result.get("rows")
    if not isinstance(rows, list):
        return {"ok": False, "reason": "missing_rows", "details": {}}
    rc = result.get("row_count")
    if isinstance(rc, int) and rc != len(rows):
        return {"ok": False, "reason": "row_count_mismatch",
                "details": {"row_count": rc, "rows": len(rows)}}
    return {"ok": True, "reason": "ok", "details": {"columns": len(cols), "rows": len(rows)}}


def _v_read_csv(result, resolve_path):
    cols = result.get("columns")
    if not isinstance(cols, list):
        return {"ok": False, "reason": "missing_columns", "details": {}}
    if "sample" not in result and "rows" not in result:
        return {"ok": False, "reason": "missing_data", "details": {}}
    return {"ok": True, "reason": "ok", "details": {"columns": len(cols)}}


def _v_schema_introspect(result, resolve_path):
    tables = result.get("tables")
    if not isinstance(tables, dict):
        return {"ok": False, "reason": "missing_tables", "details": {}}
    return {"ok": True, "reason": "ok", "details": {"tables": len(tables)}}


def _v_dataset_summary(result, resolve_path):
    shape = result.get("shape")
    if not isinstance(shape, dict) or "rows" not in shape or "columns" not in shape:
        return {"ok": False, "reason": "missing_shape", "details": {}}
    return {"ok": True, "reason": "ok", "details": {"shape": shape}}


def _v_hash_file(result, resolve_path):
    h = result.get("hash")
    if not isinstance(h, str) or not h.strip():
        return {"ok": False, "reason": "missing_hash", "details": {}}
    hs = h.strip().lower()
    if any(c not in "0123456789abcdef" for c in hs):
        return {"ok": False, "reason": "hash_not_hex", "details": {}}
    algo = str(result.get("algorithm") or "").lower().replace("-", "")
    exp = _HASH_HEX_LENGTHS.get(algo)
    if exp is not None and len(hs) != exp:
        return {"ok": False, "reason": "hash_length_mismatch",
                "details": {"algorithm": algo, "len": len(hs), "expected": exp}}
    return {"ok": True, "reason": "ok", "details": {"algorithm": algo, "len": len(hs)}}


# --- git / exec / network effects ------------------------------------------

def _v_git_commit(result, resolve_path):
    out = str(result.get("output") or "")
    if not out.strip():
        return {"ok": False, "reason": "empty_commit_output", "details": {}}
    low = out.lower()
    if _GIT_COMMIT_SIGNATURE.search(out) or any(
        w in low for w in ("file changed", "files changed", "insertion", "deletion")
    ):
        return {"ok": True, "reason": "ok", "details": {}}
    return {"ok": False, "reason": "no_commit_recorded", "details": {"output": out[:200]}}


def _v_git_worktree_add(result, resolve_path):
    return _artifact_file_verdict(resolve_path, result.get("path"),
                                  require_nonempty=False, allow_dir=True)


def _v_run_tests(result, resolve_path):
    rc = result.get("returncode")
    if not isinstance(rc, int):
        return {"ok": False, "reason": "missing_returncode", "details": {}}
    if rc != 0:
        return {"ok": False, "reason": "tests_nonzero_returncode", "details": {"returncode": rc}}
    failed = result.get("failed")
    if isinstance(failed, int) and failed > 0:
        return {"ok": False, "reason": "tests_failed", "details": {"failed": failed}}
    return {"ok": True, "reason": "ok", "details": {"passed": result.get("passed")}}


def _v_run_skill_pack(result, resolve_path):
    if result.get("timed_out"):
        return {"ok": False, "reason": "skill_pack_timed_out", "details": {}}
    ec = result.get("exit_code")
    if not isinstance(ec, int):
        return {"ok": False, "reason": "missing_exit_code", "details": {}}
    if ec != 0:
        return {"ok": False, "reason": "skill_pack_nonzero_exit", "details": {"exit_code": ec}}
    return {"ok": True, "reason": "ok", "details": {"exit_code": ec}}


def _v_mcp_tools_call(result, resolve_path):
    if "mcp" not in result or result.get("mcp") is None:
        return {"ok": False, "reason": "missing_mcp_payload", "details": {}}
    return {"ok": True, "reason": "ok", "details": {}}


def _v_send_webhook(result, resolve_path):
    # send_webhook / discord_send return ok=True even for a 4xx/5xx response;
    # the true delivery artifact is a 2xx HTTP status.
    status = result.get("status")
    if not isinstance(status, int):
        return {"ok": False, "reason": "missing_http_status", "details": {}}
    if not (200 <= status < 300):
        return {"ok": False, "reason": "http_status_not_2xx", "details": {"status": status}}
    return {"ok": True, "reason": "ok", "details": {"status": status}}


def _v_github_pr(result, resolve_path):
    if not isinstance(result.get("number"), int):
        return {"ok": False, "reason": "missing_pr_number", "details": {}}
    if not str(result.get("url") or "").strip():
        return {"ok": False, "reason": "missing_pr_url", "details": {}}
    return {"ok": True, "reason": "ok", "details": {"number": result.get("number")}}


def _v_send_email(result, resolve_path):
    if not str(result.get("to") or "").strip():
        return {"ok": False, "reason": "missing_recipient", "details": {}}
    return {"ok": True, "reason": "ok", "details": {}}


def _v_fabrication_assist_run(result, resolve_path):
    sp = str(result.get("session_path") or "").strip()
    if not sp:
        return {"ok": False, "reason": "missing_session_path", "details": {}}
    v = _artifact_file_verdict(resolve_path, sp)
    # A runner that legitimately did not persist a session file must not fail
    # an otherwise-successful run.
    if not v["ok"] and v["reason"] in ("artifact_missing", "artifact_not_a_file"):
        return {"ok": True, "reason": "unverified_session_file", "details": {"session_path": sp}}
    return v


# --- memory persistence -----------------------------------------------------

def _v_save_note(result, resolve_path):
    if not str(result.get("saved") or "").strip():
        return {"ok": False, "reason": "nothing_saved", "details": {}}
    return {"ok": True, "reason": "ok", "details": {}}


def _v_vector_store(result, resolve_path):
    if not str(result.get("stored") or "").strip():
        return {"ok": False, "reason": "nothing_stored", "details": {}}
    return {"ok": True, "reason": "ok", "details": {}}


# Registry consumed by deterministic_verify_tool_result. Ordered by risk tier
# (dangerous / write / exec / network first, then structured readers).
_EFFECT_VERIFIERS = {
    # dangerous / high-risk writers & exec
    "write_files_batch": _v_write_files_batch,
    "run_skill_pack": _v_run_skill_pack,
    "mcp_tools_call": _v_mcp_tools_call,
    "run_tests": _v_run_tests,
    "git_worktree_add": _v_git_worktree_add,
    # write / require_approval effects
    "write_csv": _v_write_csv,
    "create_svg": _v_create_svg,
    "create_mermaid": _v_create_mermaid,
    "create_archive": _v_create_archive,
    "extract_archive": _v_extract_archive,
    "merge_pdf": _v_merge_pdf,
    "db_backup": _v_db_backup,
    "generate_gcode": _v_generate_gcode,
    "code_format": _v_code_format,
    "calendar_add_event": _v_calendar_add_event,
    "notebook_edit_cell": _v_notebook_edit_cell,
    "update_project_memory": _v_update_project_memory,
    "git_commit": _v_git_commit,
    "generate_qr": _v_generate_qr,
    "image_resize": _v_image_resize,
    "screenshot_desktop": _v_screenshot_desktop,
    "tts_speak": _v_tts_speak,
    "extract_frames": _v_extract_frames,
    "fabrication_assist_run": _v_fabrication_assist_run,
    # outbound / network effects (model-supplied destination)
    "send_webhook": _v_send_webhook,
    "discord_send": _v_send_webhook,
    "github_pr": _v_github_pr,
    "send_email": _v_send_email,
    # memory persistence
    "save_note": _v_save_note,
    "vector_store": _v_vector_store,
    # structured-data producers (artifact = the parsed payload)
    "json_query": _v_json_query,
    "sql_query": _v_sql_query,
    "read_csv": _v_read_csv,
    "schema_introspect": _v_schema_introspect,
    "dataset_summary": _v_dataset_summary,
    "hash_file": _v_hash_file,
}
