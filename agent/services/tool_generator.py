"""
Experimental: generated tools under ``.layla/generated_tools/`` (governance-heavy).

Disabled unless ``dynamic_tool_generation_enabled`` is true in config.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def is_enabled(cfg: dict) -> bool:
    return bool(cfg.get("dynamic_tool_generation_enabled"))


def propose_stub(description: str) -> dict[str, Any]:
    """Placeholder — returns a template only; execution requires future sandbox compile."""
    return {"ok": False, "error": "dynamic_tool_generation_not_implemented", "description": (description or "")[:200]}
