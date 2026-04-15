"""Optional OpenTelemetry spans — no-op unless opentelemetry_enabled and SDK present."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("layla")


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
