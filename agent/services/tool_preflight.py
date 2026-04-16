"""
Deterministic tool-argument preflight.

Goal: prevent wasted tool steps when the model chose a tool that cannot run because
required args are missing (e.g., read_file without a path).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

_URL_RE = re.compile(r"https?://", re.I)
_PATHLIKE_RE = re.compile(r"([A-Za-z]:\\|/|\\\\)")


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    reason: str = ""
    suggested_action: str = "reason"  # "reason" | "think"
    missing: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_path_like(text: str) -> str:
    if not text:
        return ""
    for tok in text.split():
        t = tok.strip("\"'`,.;()[]{}")
        if not t:
            continue
        if _PATHLIKE_RE.search(t) and not t.lower().startswith("http"):
            return t
        if any(t.lower().endswith(ext) for ext in (".py", ".ts", ".tsx", ".js", ".json", ".toml", ".yml", ".yaml", ".md", ".txt")):
            return t
    return ""


def _extract_url_like(text: str) -> str:
    if not text:
        return ""
    for tok in text.split():
        t = tok.strip("\"'`,.;()[]{}")
        if not t:
            continue
        if _URL_RE.search(t):
            return t
    return ""


def preflight_tool(
    intent: str,
    decision: dict | None,
    goal: str,
    workspace_root: str = "",
) -> PreflightResult:
    """
    Return PreflightResult(ok=False) when required args are clearly missing.

    This is intentionally conservative: it only blocks when execution is impossible
    (no path/url/argv present), not when args are merely suboptimal.
    """
    name = (intent or "").strip()
    if not name or name in ("reason", "finish", "wakeup", "none"):
        return PreflightResult(ok=True)

    args = (decision or {}).get("args") if isinstance(decision, dict) else None
    args = args if isinstance(args, dict) else {}

    text = (goal or "").strip()

    if name in ("read_file", "understand_file"):
        path = str(args.get("path") or "").strip() or _extract_path_like(text)
        if not path:
            return PreflightResult(
                ok=False,
                reason=f"{name} requires a file path, but none was provided.",
                suggested_action="reason",
                missing=["path"],
            )
        return PreflightResult(ok=True)

    if name == "fetch_url":
        url = str(args.get("url") or "").strip() or _extract_url_like(text)
        if not url:
            return PreflightResult(
                ok=False,
                reason="fetch_url requires a URL, but none was provided.",
                suggested_action="reason",
                missing=["url"],
            )
        return PreflightResult(ok=True)

    if name == "shell":
        argv = args.get("argv")
        if isinstance(argv, list) and argv:
            return PreflightResult(ok=True)
        # Heuristic: if the user didn't include any obvious command text, block.
        # (We intentionally do not attempt complex parsing here.)
        if len(text.split()) < 2:
            return PreflightResult(
                ok=False,
                reason="shell requires argv/command text, but none was provided.",
                suggested_action="reason",
                missing=["argv"],
            )
        return PreflightResult(ok=True)

    if name == "write_file":
        path = str(args.get("path") or "").strip() or _extract_path_like(text)
        if not path:
            return PreflightResult(
                ok=False,
                reason="write_file requires a path, but none was provided.",
                suggested_action="reason",
                missing=["path"],
            )
        return PreflightResult(ok=True)

    if name == "apply_patch":
        path = str(args.get("path") or args.get("original_path") or "").strip() or _extract_path_like(text)
        patch_text = args.get("patch_text")
        if not path:
            return PreflightResult(
                ok=False,
                reason="apply_patch requires a path, but none was provided.",
                suggested_action="reason",
                missing=["path"],
            )
        if not isinstance(patch_text, str) or not patch_text.strip():
            return PreflightResult(
                ok=False,
                reason="apply_patch requires patch_text, but none was provided.",
                suggested_action="think",
                missing=["patch_text"],
            )
        return PreflightResult(ok=True)

    # Default: allow (unknown tools are handled elsewhere).
    _ = workspace_root  # reserved for future per-workspace rules
    return PreflightResult(ok=True)

