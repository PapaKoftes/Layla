"""
Provider health tracking with circuit-breaker pattern.

Each LLM provider (anthropic, ollama, groq, openai, together, etc.) gets a health
record. When a provider accumulates too many failures in a short window, the circuit
opens (provider is marked unhealthy) and stays open for a cooldown period. A recovery
probe is attempted after cooldown before fully re-enabling.

Thread-safe: uses a single lock for the health dict. Lightweight — no external deps.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger("layla")

# ── Configuration ────────────────────────────────────────────────────────────

FAILURE_THRESHOLD = 3          # failures within FAILURE_WINDOW → circuit opens
FAILURE_WINDOW_SECONDS = 60.0  # rolling window for counting failures
COOLDOWN_SECONDS = 300.0       # how long circuit stays open before recovery probe
MAX_LATENCY_SAMPLES = 50       # rolling window for latency tracking


@dataclass
class ProviderRecord:
    """Health state for one LLM provider."""
    name: str
    healthy: bool = True
    circuit_open_at: float = 0.0       # time.monotonic() when circuit opened
    failure_times: list[float] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    total_calls: int = 0
    latency_samples: list[float] = field(default_factory=list)  # seconds
    total_cost_usd: float = 0.0
    last_error: str = ""
    last_success_at: float = 0.0
    last_failure_at: float = 0.0

    def avg_latency(self) -> float:
        """Average latency in seconds (0.0 if no samples)."""
        if not self.latency_samples:
            return 0.0
        return sum(self.latency_samples) / len(self.latency_samples)

    def p95_latency(self) -> float:
        """95th percentile latency in seconds."""
        if not self.latency_samples:
            return 0.0
        sorted_samples = sorted(self.latency_samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    def error_rate(self) -> float:
        """Error rate as fraction 0.0–1.0."""
        if self.total_calls == 0:
            return 0.0
        return self.failure_count / self.total_calls

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "total_calls": self.total_calls,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "error_rate": round(self.error_rate(), 4),
            "avg_latency_ms": round(self.avg_latency() * 1000, 1),
            "p95_latency_ms": round(self.p95_latency() * 1000, 1),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "last_error": self.last_error,
            "circuit_open": not self.healthy,
        }


# ── Global health registry ──────────────────────────────────────────────────

_lock = threading.Lock()
_providers: dict[str, ProviderRecord] = {}


def _get_or_create(name: str) -> ProviderRecord:
    """Get or create a provider record (caller holds _lock)."""
    rec = _providers.get(name)
    if rec is None:
        rec = ProviderRecord(name=name)
        _providers[name] = rec
    return rec


def _prune_old_failures(rec: ProviderRecord, now: float) -> None:
    """Remove failure timestamps outside the rolling window."""
    cutoff = now - FAILURE_WINDOW_SECONDS
    rec.failure_times = [t for t in rec.failure_times if t > cutoff]


# ── Public API ───────────────────────────────────────────────────────────────


def record_success(provider: str, latency_seconds: float = 0.0, cost_usd: float = 0.0) -> None:
    """Record a successful completion call to a provider."""
    now = time.monotonic()
    with _lock:
        rec = _get_or_create(provider)
        rec.total_calls += 1
        rec.success_count += 1
        rec.last_success_at = now
        if latency_seconds > 0:
            rec.latency_samples.append(latency_seconds)
            if len(rec.latency_samples) > MAX_LATENCY_SAMPLES:
                rec.latency_samples = rec.latency_samples[-MAX_LATENCY_SAMPLES:]
        if cost_usd > 0:
            rec.total_cost_usd += cost_usd
        # If circuit was open and we got a success (recovery probe), close it
        if not rec.healthy:
            rec.healthy = True
            rec.circuit_open_at = 0.0
            rec.failure_times.clear()
            logger.info("provider_health: %s circuit CLOSED (recovered)", provider)


def record_failure(provider: str, error: str = "") -> None:
    """Record a failed completion call. May trigger circuit open."""
    now = time.monotonic()
    with _lock:
        rec = _get_or_create(provider)
        rec.total_calls += 1
        rec.failure_count += 1
        rec.last_failure_at = now
        rec.last_error = (error or "unknown")[:500]
        rec.failure_times.append(now)
        _prune_old_failures(rec, now)
        # Check circuit breaker threshold
        if rec.healthy and len(rec.failure_times) >= FAILURE_THRESHOLD:
            rec.healthy = False
            rec.circuit_open_at = now
            logger.warning(
                "provider_health: %s circuit OPEN (%d failures in %.0fs window)",
                provider, len(rec.failure_times), FAILURE_WINDOW_SECONDS,
            )


def is_healthy(provider: str) -> bool:
    """Check if a provider is healthy (circuit closed or cooldown expired)."""
    now = time.monotonic()
    with _lock:
        rec = _providers.get(provider)
        if rec is None:
            return True  # Unknown providers are assumed healthy
        if rec.healthy:
            return True
        # Check if cooldown has expired → allow a recovery probe
        if rec.circuit_open_at and (now - rec.circuit_open_at) >= COOLDOWN_SECONDS:
            # Half-open: allow one probe. Don't mark healthy yet —
            # record_success() will close the circuit if the probe succeeds.
            return True
        return False


def get_healthy_providers(candidates: list[str]) -> list[str]:
    """Filter a list of provider names to only healthy ones."""
    return [p for p in candidates if is_healthy(p)]


def get_provider_status(provider: str) -> dict:
    """Get status dict for a single provider."""
    with _lock:
        rec = _providers.get(provider)
        if rec is None:
            return {"name": provider, "healthy": True, "total_calls": 0}
        return rec.to_dict()


def get_all_status() -> list[dict]:
    """Get status dicts for all known providers."""
    with _lock:
        return [rec.to_dict() for rec in _providers.values()]


def reset_provider(provider: str) -> None:
    """Reset a provider's health state (admin use)."""
    with _lock:
        if provider in _providers:
            _providers[provider] = ProviderRecord(name=provider)


def reset_all() -> None:
    """Reset all provider health state (tests / admin)."""
    with _lock:
        _providers.clear()


def record_cost(provider: str, cost_usd: float) -> None:
    """Record cost for a provider (separate from success/failure tracking)."""
    with _lock:
        rec = _get_or_create(provider)
        rec.total_cost_usd += max(0.0, cost_usd)


def get_total_cost() -> float:
    """Total cost across all providers."""
    with _lock:
        return sum(rec.total_cost_usd for rec in _providers.values())


def get_cost_by_provider() -> dict[str, float]:
    """Cost breakdown by provider."""
    with _lock:
        return {rec.name: round(rec.total_cost_usd, 6) for rec in _providers.values()}
