"""Tests for provider health tracking and circuit-breaker logic."""
import time

import pytest


class TestRecordSuccess:
    def test_records_success(self):
        from services.provider_health import get_provider_status, record_success, reset_all
        reset_all()
        record_success("anthropic", latency_seconds=0.5, cost_usd=0.001)
        status = get_provider_status("anthropic")
        assert status["healthy"] is True
        assert status["total_calls"] == 1
        assert status["success_count"] == 1
        assert status["failure_count"] == 0

    def test_tracks_latency(self):
        from services.provider_health import get_provider_status, record_success, reset_all
        reset_all()
        record_success("groq", latency_seconds=0.1)
        record_success("groq", latency_seconds=0.3)
        status = get_provider_status("groq")
        assert status["avg_latency_ms"] == pytest.approx(200.0, abs=1)

    def test_tracks_cost(self):
        from services.provider_health import get_provider_status, record_success, reset_all
        reset_all()
        record_success("openai", cost_usd=0.005)
        record_success("openai", cost_usd=0.003)
        status = get_provider_status("openai")
        assert status["total_cost_usd"] == pytest.approx(0.008, abs=0.0001)


class TestRecordFailure:
    def test_records_failure(self):
        from services.provider_health import get_provider_status, record_failure, reset_all
        reset_all()
        record_failure("anthropic", error="rate_limited")
        status = get_provider_status("anthropic")
        assert status["failure_count"] == 1
        assert status["last_error"] == "rate_limited"
        assert status["healthy"] is True  # 1 failure = still healthy

    def test_truncates_long_errors(self):
        from services.provider_health import get_provider_status, record_failure, reset_all
        reset_all()
        record_failure("test", error="x" * 1000)
        status = get_provider_status("test")
        assert len(status["last_error"]) <= 500


class TestCircuitBreaker:
    def test_opens_after_threshold(self):
        from services.provider_health import (
            FAILURE_THRESHOLD,
            is_healthy,
            record_failure,
            reset_all,
        )
        reset_all()
        for _ in range(FAILURE_THRESHOLD):
            record_failure("bad_provider", error="timeout")
        assert is_healthy("bad_provider") is False

    def test_stays_healthy_under_threshold(self):
        from services.provider_health import (
            FAILURE_THRESHOLD,
            is_healthy,
            record_failure,
            reset_all,
        )
        reset_all()
        for _ in range(FAILURE_THRESHOLD - 1):
            record_failure("flaky_provider", error="timeout")
        assert is_healthy("flaky_provider") is True

    def test_unknown_provider_is_healthy(self):
        from services.provider_health import is_healthy, reset_all
        reset_all()
        assert is_healthy("never_seen_provider") is True

    def test_success_closes_circuit(self):
        from services.provider_health import (
            FAILURE_THRESHOLD,
            is_healthy,
            record_failure,
            record_success,
            reset_all,
        )
        reset_all()
        for _ in range(FAILURE_THRESHOLD):
            record_failure("recovering", error="fail")
        assert is_healthy("recovering") is False
        # Simulate recovery probe succeeding
        record_success("recovering", latency_seconds=0.1)
        assert is_healthy("recovering") is True


class TestHealthFiltering:
    def test_get_healthy_providers(self):
        from services.provider_health import (
            FAILURE_THRESHOLD,
            get_healthy_providers,
            record_failure,
            reset_all,
        )
        reset_all()
        for _ in range(FAILURE_THRESHOLD):
            record_failure("dead_one", error="fail")
        candidates = ["dead_one", "alive_one", "alive_two"]
        healthy = get_healthy_providers(candidates)
        assert "dead_one" not in healthy
        assert "alive_one" in healthy
        assert "alive_two" in healthy

    def test_empty_candidates(self):
        from services.provider_health import get_healthy_providers, reset_all
        reset_all()
        assert get_healthy_providers([]) == []


class TestStatusReporting:
    def test_get_all_status(self):
        from services.provider_health import (
            get_all_status,
            record_failure,
            record_success,
            reset_all,
        )
        reset_all()
        record_success("prov_a", latency_seconds=0.2, cost_usd=0.01)
        record_failure("prov_b", error="timeout")
        all_status = get_all_status()
        assert len(all_status) == 2
        names = {s["name"] for s in all_status}
        assert "prov_a" in names
        assert "prov_b" in names

    def test_error_rate_calculation(self):
        from services.provider_health import (
            get_provider_status,
            record_failure,
            record_success,
            reset_all,
        )
        reset_all()
        record_success("mixed")
        record_success("mixed")
        record_failure("mixed")
        status = get_provider_status("mixed")
        assert status["error_rate"] == pytest.approx(1 / 3, abs=0.01)

    def test_reset_provider(self):
        from services.provider_health import (
            get_provider_status,
            record_success,
            reset_all,
            reset_provider,
        )
        reset_all()
        record_success("resettable", latency_seconds=0.1, cost_usd=0.5)
        reset_provider("resettable")
        status = get_provider_status("resettable")
        assert status["total_calls"] == 0
        assert status["total_cost_usd"] == 0.0


class TestCostTracking:
    def test_record_cost_separate(self):
        from services.provider_health import get_cost_by_provider, record_cost, reset_all
        reset_all()
        record_cost("anthropic", 0.01)
        record_cost("anthropic", 0.02)
        record_cost("groq", 0.005)
        costs = get_cost_by_provider()
        assert costs["anthropic"] == pytest.approx(0.03, abs=0.001)
        assert costs["groq"] == pytest.approx(0.005, abs=0.001)

    def test_get_total_cost(self):
        from services.provider_health import get_total_cost, record_cost, reset_all
        reset_all()
        record_cost("a", 0.1)
        record_cost("b", 0.2)
        assert get_total_cost() == pytest.approx(0.3, abs=0.01)

    def test_negative_cost_ignored(self):
        from services.provider_health import get_cost_by_provider, record_cost, reset_all
        reset_all()
        record_cost("test", -5.0)
        costs = get_cost_by_provider()
        assert costs.get("test", 0.0) == 0.0
