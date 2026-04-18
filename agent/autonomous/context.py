from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _safe_json(obj: Any, max_chars: int) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > max_chars:
        return s[:max_chars] + "..."
    return s


def compress_output(text: str, *, max_chars: int = 3200) -> str:
    """Trim long raw text before it hits planner context."""
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 3] + "..."


def normalize_path_for_tracking(raw: object) -> str:
    """Stable absolute path string for dedupe/analytics (empty if invalid)."""
    return _normalize_path_key(raw)


def _normalize_path_key(raw: object) -> str:
    if raw is None:
        return ""
    p = str(raw).strip()
    if not p:
        return ""
    try:
        return str(Path(p).expanduser().resolve())
    except Exception:
        return p


@dataclass
class ContextState:
    goal: str
    known_facts: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    progress: list[str] = field(default_factory=list)
    last_result_summary: str = ""
    # Per-run cache: (tool, args_json) -> result dict
    tool_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Normalized absolute path -> last read_file result (dedupe same path, different arg spelling)
    path_reads: dict[str, dict[str, Any]] = field(default_factory=dict)
    rolling_progress_cap: int = 24

    def cache_key(self, tool: str, args: dict[str, Any]) -> str:
        return f"{tool}:{_safe_json(args, 1000)}"

    def maybe_get_cached(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        return self.tool_cache.get(self.cache_key(tool, args))

    def set_cached(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        self.tool_cache[self.cache_key(tool, args)] = result

    def cache_tool_result(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        """Alias for set_cached (explicit API for investigation engine)."""
        self.set_cached(tool, args, result)

    def get_cached_result(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        """Alias for maybe_get_cached."""
        return self.maybe_get_cached(tool, args)

    def dedupe_file_reads(self, path_arg: object) -> dict[str, Any] | None:
        """If path was already read this run, return stored result (skip second disk read)."""
        key = _normalize_path_key(path_arg)
        if not key:
            return None
        prev = self.path_reads.get(key)
        if prev is None:
            return None
        out = dict(prev)
        out["_deduped_read"] = True
        out["_dedupe_path"] = key
        return out

    def record_read_file_result(self, args: dict[str, Any], result: dict[str, Any]) -> None:
        if not isinstance(args, dict) or not isinstance(result, dict):
            return
        key = _normalize_path_key(args.get("path"))
        if key and result.get("ok") is not False:
            self.path_reads[key] = result

    def record_progress(self, line: str) -> None:
        t = (line or "").strip()
        if not t:
            return
        self.progress.append(t[:500])
        cap = max(12, self.rolling_progress_cap)
        if len(self.progress) > cap:
            self.progress = self.progress[-cap:]

    def summarize_for_planner(self) -> dict[str, Any]:
        rp = self.rolling_progress_cap
        files_read = sorted(self.path_reads.keys())[:40]
        return {
            "goal": self.goal[:1500],
            "known_facts": self.known_facts[-20:],
            "open_questions": self.open_questions[-20:],
            "progress": self.progress[-rp:],
            "last_result_summary": compress_output(self.last_result_summary, max_chars=1200),
            "files_read_this_run": files_read,
        }


def compress_tool_result(tool: str, result: dict[str, Any], *, max_chars: int = 2400) -> str:
    """Produce a small planner-facing summary (not the full raw)."""
    if not isinstance(result, dict):
        return compress_output(str(result), max_chars=max_chars)
    if result.get("ok") is False:
        err = str(result.get("error") or result.get("reason") or "")[:600]
        return f"{tool}: ok=false {err}".strip()
    if result.get("_deduped_read"):
        return f"{tool}: deduped_hit {result.get('_dedupe_path', '')}"[:max_chars]
    for key in ("summary", "message", "path"):
        if result.get(key):
            return compress_output(f"{tool}: {str(result.get(key))}", max_chars=max_chars).strip()
    blob = _safe_json(result, max_chars)
    return compress_output(f"{tool}: {blob}", max_chars=max_chars + 80).strip()

