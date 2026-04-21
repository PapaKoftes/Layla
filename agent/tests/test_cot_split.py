"""Phase 4.1 — dual-model CoT split tests."""
import pytest

from services.model_router import (
    _record_cot_phase,
    clear_cot_stats,
    get_cot_stats,
    split_cot_models,
)


@pytest.fixture(autouse=True)
def _clean_stats():
    clear_cot_stats()
    yield
    clear_cot_stats()


def test_split_cot_models_returns_dict():
    result = split_cot_models()
    assert "reasoning_model" in result
    assert "implementation_model" in result
    assert "split_enabled" in result


def test_split_cot_models_split_enabled_only_when_distinct():
    result = split_cot_models()
    r = result["reasoning_model"]
    i = result["implementation_model"]
    expected_split = bool(r and i and r != i)
    assert result["split_enabled"] == expected_split


def test_record_cot_phase_accumulates():
    _record_cot_phase("reasoning", "fast-model", 500)
    _record_cot_phase("reasoning", "fast-model", 300)
    stats = get_cot_stats()
    entry = next((s for s in stats if s["phase"] == "reasoning"), None)
    assert entry is not None
    assert entry["calls"] == 2
    assert entry["estimated_tokens"] == 800


def test_record_cot_phase_separate_keys():
    _record_cot_phase("reasoning", "fast", 100)
    _record_cot_phase("implementation", "slow", 200)
    stats = get_cot_stats()
    phases = {s["phase"] for s in stats}
    assert "reasoning" in phases
    assert "implementation" in phases


def test_clear_cot_stats():
    _record_cot_phase("reasoning", "m", 100)
    clear_cot_stats()
    assert get_cot_stats() == []


def test_get_cot_stats_returns_list():
    assert isinstance(get_cot_stats(), list)
