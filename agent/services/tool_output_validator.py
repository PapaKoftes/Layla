"""
Normalize and annotate tool return dicts (safety / hygiene for agent loop).
"""
from __future__ import annotations

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
