"""Auto file-probe helpers (planning layer only).

Extracted from agent_loop.py -- provides pre-read probing so the planner
can make soft decisions (skip binary files, hint about large files) before
the execution layer actually touches a file.
"""
from __future__ import annotations

import logging
from typing import Any

import runtime_safety
from constants import LARGE_FILE_HINT_LINES, MAX_SAFE_READ_BYTES
from layla.tools.registry import TOOLS

logger = logging.getLogger("layla")

__all__ = [
    "probe_store",
    "maybe_preprobe_file",
    "apply_probe_guidance",
]


# -- helpers -----------------------------------------------------------------

def probe_store(state: dict) -> dict:
    cm = state.setdefault("context_memory", {})
    cm.setdefault("file_probed", {})
    cm.setdefault("file_probe_hints", {})
    return cm


def maybe_preprobe_file(state: dict, path: str) -> dict | None:
    """
    Run file_info once per path (no approval, does not count toward tool_calls).
    Records as an internal step: action=pre_read_probe.
    """
    if not path:
        return None
    cm = probe_store(state)
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
        logger.debug("probe_helpers: %s", _exc, exc_info=False)
    return result


def apply_probe_guidance(state: dict, intent: str, path: str, probe: dict | None) -> bool:
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
        cm = probe_store(state)
        cm["file_probe_hints"][path] = hints
    return True
