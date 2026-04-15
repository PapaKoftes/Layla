"""Remote client rate limit (sliding window)."""
from services.remote_rate_limit import check_rate_limit


def test_rate_limit_allows_under_cap():
    ok, _ = check_rate_limit("test-ip-a", 100)
    assert ok is True
    ok2, _ = check_rate_limit("test-ip-a", 100)
    assert ok2 is True


def test_rate_limit_blocks_over_cap():
    key = "test-ip-burst"
    cap = 5
    for _ in range(cap):
        ok, _ = check_rate_limit(key, cap)
        assert ok is True
    ok, reason = check_rate_limit(key, cap)
    assert ok is False
    assert reason == "rate_limited"


def test_rate_limit_zero_disabled():
    ok, reason = check_rate_limit("any", 0)
    assert ok is True
    assert reason == ""
