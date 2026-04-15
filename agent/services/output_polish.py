"""Lightweight final response cleanup for UX consistency."""
from __future__ import annotations

import re

_CODE_FENCE = re.compile(r"```")
_JSON_START = re.compile(r"^\s*[\[{]")
_TOOLISH = re.compile(r'^\s*\{\s*"(ok|error|result|tool|approval_id)"\s*:')


def _looks_like_code_or_structured(text: str) -> bool:
    """True if text contains a fenced code block, JSON/array, or tool-style JSON."""
    if not text:
        return False
    if _CODE_FENCE.search(text):
        return True
    if _JSON_START.match(text):
        return True
    if _TOOLISH.match(text):
        return True
    return False


def polish_output(text: str, cfg: dict | None = None) -> str:
    """Strip edges and collapse blank lines — skips code/JSON to preserve structure."""
    if not text:
        return ""
    if _looks_like_code_or_structured(text):
        return text.strip()
    t = text.strip()
    if not t:
        return ""
    t = re.sub(r"\n{3,}", "\n\n", t)
    try:
        if cfg and bool(cfg.get("output_quality_gate_enabled", False)):
            from services.output_quality import clean_output

            return clean_output(t, cfg=cfg)
    except Exception:
        pass
    return t.strip()
