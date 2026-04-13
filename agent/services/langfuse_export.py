"""
Optional Langfuse export — no hard dependency on langfuse (pip install langfuse to enable).
Controlled by runtime_config: langfuse_enabled + keys.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def maybe_emit_run_budget_span(cfg: dict[str, Any], summary: dict[str, Any]) -> None:
    """Best-effort span for run_budget_summary; no-op if disabled or import fails."""
    if not isinstance(cfg, dict) or not cfg.get("langfuse_enabled"):
        return
    pk = (cfg.get("langfuse_public_key") or "").strip()
    sk = (cfg.get("langfuse_secret_key") or "").strip()
    if not pk or not sk:
        return
    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]
    except Exception:
        logger.debug("langfuse not installed; skipping run budget export")
        return
    try:
        host = (cfg.get("langfuse_host") or "https://cloud.langfuse.com").strip()
        lf = Langfuse(public_key=pk, secret_key=sk, host=host)
        if hasattr(lf, "start_as_current_observation"):
            with lf.start_as_current_observation(as_type="span", name="layla_run_budget") as obs:  # type: ignore[misc]
                obs.update(metadata=summary)
        else:
            logger.debug("langfuse SDK present but start_as_current_observation missing; skip span")
    except Exception as e:
        logger.debug("langfuse export failed: %s", e)
