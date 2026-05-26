"""Unified tracing exports — OpenTelemetry spans + Langfuse budget spans.

No hard dependency on either SDK; each function is a no-op when disabled or
when the respective package is not installed.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("layla")


# ---------------------------------------------------------------------------
# OpenTelemetry
# ---------------------------------------------------------------------------

@contextmanager
def maybe_span(cfg: dict[str, Any], name: str, **attrs: Any) -> Iterator[None]:
    if not bool((cfg or {}).get("opentelemetry_enabled", False)):
        yield
        return
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("layla")
        with tracer.start_as_current_span(name, attributes={k: str(v) for k, v in attrs.items() if v is not None}):
            yield
    except Exception as e:
        logger.debug("otel span skipped: %s", e)
        yield


# ---------------------------------------------------------------------------
# Langfuse
# ---------------------------------------------------------------------------

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
