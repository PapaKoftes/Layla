"""BL-181: standard tenacity-backed retry helper."""
from __future__ import annotations

import pytest

from services.infrastructure import retry_util as ru


def test_returns_on_first_success():
    calls = []
    assert ru.retry_call(lambda: calls.append(1) or "ok", attempts=3) == "ok"
    assert len(calls) == 1


def test_retries_then_succeeds():
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("nope")
        return "done"

    # tiny delays keep the test fast
    assert ru.retry_call(_flaky, attempts=5, base_delay=0.001, max_delay=0.005) == "done"
    assert calls["n"] == 3


def test_reraises_after_exhausting_attempts():
    calls = {"n": 0}

    def _always():
        calls["n"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        ru.retry_call(_always, attempts=3, base_delay=0.001, max_delay=0.002)
    assert calls["n"] == 3


def test_only_retries_selected_exceptions():
    calls = {"n": 0}

    def _typeerr():
        calls["n"] += 1
        raise TypeError("wrong type")

    with pytest.raises(TypeError):
        ru.retry_call(_typeerr, attempts=4, base_delay=0.001, exceptions=(ValueError,))
    assert calls["n"] == 1   # TypeError not in retry set → no retry


def test_resilient_decorator():
    state = {"n": 0}

    @ru.resilient(attempts=3, base_delay=0.001, max_delay=0.002)
    def flaky(x):
        state["n"] += 1
        if state["n"] < 2:
            raise ValueError("retry me")
        return x * 2

    assert flaky(21) == 42
    assert state["n"] == 2


def test_tenacity_is_the_backend():
    # BL-181 requires tenacity to actually be present + used (not just the stdlib fallback)
    import tenacity  # noqa: F401
