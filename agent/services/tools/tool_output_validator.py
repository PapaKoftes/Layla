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

        # Default: no deterministic verifier for this tool.
        return {"ok": True, "reason": "no_verifier", "details": {}}
    except Exception as ex:
        return {"ok": False, "reason": "verifier_exception", "details": {"error": str(ex)[:240]}}
