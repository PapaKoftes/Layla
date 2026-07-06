"""Standard retry helper (BL-181) — one tenacity-backed retry for flaky I/O.

`diskcache` (retrieval cache) and `apscheduler` (scheduler registry) are already adopted;
tenacity was a declared-but-unused dependency. This gives the codebase one place to get
resilient retries with exponential backoff + jitter, so ad-hoc `for attempt in range(...)`
loops can standardise on it. Degrades gracefully: if tenacity is somehow absent, a tiny
stdlib fallback preserves the same call contract.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger("layla")


def retry_call(
    fn: Callable[[], Any],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    label: str = "",
) -> Any:
    """Call `fn()` with exponential-backoff retries. Re-raises the last error after `attempts`."""
    attempts = max(1, int(attempts))
    try:
        from tenacity import (
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential_jitter,
        )

        @retry(
            reraise=True,
            stop=stop_after_attempt(attempts),
            wait=wait_exponential_jitter(initial=base_delay, max=max_delay),
            retry=retry_if_exception_type(exceptions),
        )
        def _run():
            return fn()

        return _run()
    except ImportError:
        # stdlib fallback with the same semantics
        last: BaseException | None = None
        for i in range(attempts):
            try:
                return fn()
            except exceptions as e:  # type: ignore[misc]
                last = e
                if i < attempts - 1:
                    delay = min(max_delay, base_delay * (2 ** i))
                    logger.debug("retry_call%s: attempt %d failed (%s); backing off %.2fs",
                                 f" [{label}]" if label else "", i + 1, e, delay)
                    time.sleep(delay)
        assert last is not None
        raise last


def resilient(**opts):
    """Decorator form of `retry_call` — wrap a flaky function with standard retries."""
    def _wrap(fn: Callable) -> Callable:
        def _inner(*a, **kw):
            return retry_call(lambda: fn(*a, **kw), label=fn.__name__, **opts)
        _inner.__name__ = getattr(fn, "__name__", "resilient")
        _inner.__doc__ = fn.__doc__
        return _inner
    return _wrap
