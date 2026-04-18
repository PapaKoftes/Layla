"""
Tests for services/rl_feedback.py — RL preference learning feedback loop.
Uses in-memory SQLite via monkeypatching to avoid touching the real DB.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure agent/ is on sys.path
_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))


# ---------------------------------------------------------------------------
# Helpers: build mock reliability / capability event data
# ---------------------------------------------------------------------------

def _make_reliability(tools: dict) -> dict:
    """
    Build a get_tool_reliability() return value.
    tools = {name: {"success_rate": float, "avg_latency": float, "count": int}}
    """
    result = {}
    for name, stats in tools.items():
        result[name] = {
            "success_rate": stats.get("success_rate", 0.5),
            "avg_latency": stats.get("avg_latency", 100.0),
            "avg_quality": stats.get("avg_quality", 0.5),
            "count": stats.get("count", 0),
        }
    return result


# ---------------------------------------------------------------------------
# compute_tool_preferences tests
# ---------------------------------------------------------------------------

def _mock_db_module(reliability_data: dict, capability_rows: list | None = None):
    """Return a mock layla.memory.db module with get_tool_reliability and _conn patched."""
    mock_db = MagicMock()
    mock_db.get_tool_reliability.return_value = reliability_data
    mock_db.migrate.return_value = None

    rows = capability_rows or []
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_ctx.execute.return_value = mock_cursor
    mock_db._conn.return_value = mock_ctx

    return mock_db


class TestComputeToolPreferences:
    def test_basic_preference_score(self):
        """Verify the preference formula: 0.6*sr + 0.2*latency_factor + 0.2*usefulness."""
        from services.rl_feedback import compute_tool_preferences

        reliability = _make_reliability({
            "search_codebase": {"success_rate": 1.0, "avg_latency": 0.0, "count": 10},
        })
        mock_db = _mock_db_module(reliability)

        with patch.dict("sys.modules", {"layla.memory.db": mock_db}):
            prefs = compute_tool_preferences()

        assert "search_codebase" in prefs
        p = prefs["search_codebase"]
        # score = 1.0*0.6 + 1.0*0.2 + 0.5*0.2 = 0.9
        assert abs(p.score - 0.9) < 0.01
        assert p.success_rate == 1.0
        assert p.sample_count == 10

    def test_high_latency_penalised(self):
        """High latency (>=5000ms) should reduce latency_factor to 0."""
        from services.rl_feedback import compute_tool_preferences

        reliability = _make_reliability({
            "slow_tool": {"success_rate": 1.0, "avg_latency": 5000.0, "count": 5},
        })
        mock_db = _mock_db_module(reliability)

        with patch.dict("sys.modules", {"layla.memory.db": mock_db}):
            prefs = compute_tool_preferences()

        p = prefs["slow_tool"]
        # score = 1.0*0.6 + 0.0*0.2 + 0.5*0.2 = 0.7
        assert abs(p.score - 0.7) < 0.01

    def test_failed_tool_low_score(self):
        """Tool with 0% success rate and high latency should have very low score."""
        from services.rl_feedback import compute_tool_preferences

        reliability = _make_reliability({
            "broken_tool": {"success_rate": 0.0, "avg_latency": 5000.0, "count": 8},
        })
        mock_db = _mock_db_module(reliability)

        with patch.dict("sys.modules", {"layla.memory.db": mock_db}):
            prefs = compute_tool_preferences()

        p = prefs["broken_tool"]
        # score = 0.0*0.6 + 0.0*0.2 + 0.5*0.2 = 0.1
        assert abs(p.score - 0.1) < 0.01

    def test_empty_reliability_returns_empty(self):
        """No data → empty dict."""
        from services.rl_feedback import compute_tool_preferences

        mock_db = _mock_db_module({})

        with patch.dict("sys.modules", {"layla.memory.db": mock_db}):
            prefs = compute_tool_preferences()

        assert prefs == {}

    def test_db_failure_graceful(self):
        """If get_tool_reliability raises, return empty dict."""
        from services.rl_feedback import compute_tool_preferences

        mock_db = MagicMock()
        mock_db.get_tool_reliability.side_effect = RuntimeError("db down")
        mock_db.migrate.return_value = None
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value = mock_cursor
        mock_db._conn.return_value = mock_ctx

        with patch.dict("sys.modules", {"layla.memory.db": mock_db}):
            prefs = compute_tool_preferences()

        assert isinstance(prefs, dict)


# ---------------------------------------------------------------------------
# update_tool_preference_hints tests
# ---------------------------------------------------------------------------

class TestUpdateToolPreferenceHints:
    def _make_pref(self, score, success_rate, sample_count, usefulness=0.5):
        from services.rl_feedback import ToolPreference
        return ToolPreference(
            score=score,
            success_rate=success_rate,
            avg_latency_ms=100.0,
            usefulness=usefulness,
            sample_count=sample_count,
        )

    def test_preferred_hint(self):
        from services.rl_feedback import update_tool_preference_hints
        prefs = {"good_tool": self._make_pref(score=0.85, success_rate=0.9, sample_count=10)}
        hints = update_tool_preference_hints(prefs)
        assert hints["good_tool"] == "preferred"

    def test_avoid_hint(self):
        from services.rl_feedback import update_tool_preference_hints
        prefs = {"bad_tool": self._make_pref(score=0.2, success_rate=0.8, sample_count=6)}
        hints = update_tool_preference_hints(prefs)
        assert hints["bad_tool"] == "avoid"

    def test_unreliable_hint(self):
        from services.rl_feedback import update_tool_preference_hints
        prefs = {"flaky_tool": self._make_pref(score=0.5, success_rate=0.3, sample_count=4)}
        hints = update_tool_preference_hints(prefs)
        assert hints["flaky_tool"] == "unreliable"

    def test_no_hint_insufficient_samples(self):
        """With < 5 samples, preferred/avoid hints should not fire."""
        from services.rl_feedback import update_tool_preference_hints
        prefs = {
            "new_tool_good": self._make_pref(score=0.9, success_rate=0.95, sample_count=2),
            "new_tool_bad": self._make_pref(score=0.1, success_rate=0.1, sample_count=2),
        }
        hints = update_tool_preference_hints(prefs)
        assert hints["new_tool_good"] == ""
        assert hints["new_tool_bad"] == ""

    def test_unreliable_requires_3_samples(self):
        from services.rl_feedback import update_tool_preference_hints
        prefs = {"maybe_flaky": self._make_pref(score=0.5, success_rate=0.3, sample_count=2)}
        hints = update_tool_preference_hints(prefs)
        # sample_count < 3, so should not be unreliable
        assert hints["maybe_flaky"] == ""

    def test_empty_prefs_returns_empty(self):
        from services.rl_feedback import update_tool_preference_hints
        assert update_tool_preference_hints({}) == {}

    def test_preferred_takes_precedence_over_unreliable(self):
        """score > 0.8 and sr >= 0.5: should be preferred not unreliable."""
        from services.rl_feedback import update_tool_preference_hints
        prefs = {"combo": self._make_pref(score=0.85, success_rate=0.6, sample_count=8)}
        hints = update_tool_preference_hints(prefs)
        assert hints["combo"] == "preferred"


# ---------------------------------------------------------------------------
# get_rl_hint_for_prompt tests
# ---------------------------------------------------------------------------

class TestGetRlHintForPrompt:
    def _make_pref(self, score, success_rate, sample_count):
        from services.rl_feedback import ToolPreference
        return ToolPreference(
            score=score, success_rate=success_rate,
            avg_latency_ms=100.0, usefulness=0.5, sample_count=sample_count,
        )

    def test_returns_formatted_string(self):
        from services.rl_feedback import get_rl_hint_for_prompt

        prefs = {
            "good_tool": self._make_pref(0.9, 0.95, 10),
            "bad_tool": self._make_pref(0.2, 0.8, 6),
            "flaky": self._make_pref(0.5, 0.3, 4),
        }

        with (
            patch("services.rl_feedback.compute_tool_preferences", return_value=prefs),
        ):
            hint = get_rl_hint_for_prompt()

        assert "## Tool Performance Hints" in hint
        assert "good_tool" in hint
        assert "bad_tool" in hint
        assert "flaky" in hint

    def test_returns_empty_if_no_data(self):
        from services.rl_feedback import get_rl_hint_for_prompt

        with patch("services.rl_feedback.compute_tool_preferences", return_value={}):
            hint = get_rl_hint_for_prompt()

        assert hint == ""

    def test_returns_empty_if_all_hints_empty(self):
        """All tools have too few samples → no hints → empty string."""
        from services.rl_feedback import get_rl_hint_for_prompt

        prefs = {"new_tool": self._make_pref(0.7, 0.7, 1)}
        with patch("services.rl_feedback.compute_tool_preferences", return_value=prefs):
            hint = get_rl_hint_for_prompt()

        assert hint == ""

    def test_graceful_on_exception(self):
        from services.rl_feedback import get_rl_hint_for_prompt

        with patch("services.rl_feedback.compute_tool_preferences", side_effect=RuntimeError("fail")):
            hint = get_rl_hint_for_prompt()

        assert hint == ""

    def test_prefer_and_avoid_sections_present(self):
        from services.rl_feedback import get_rl_hint_for_prompt

        prefs = {
            "alpha": self._make_pref(0.95, 0.95, 10),
            "beta": self._make_pref(0.25, 0.8, 5),
        }
        with patch("services.rl_feedback.compute_tool_preferences", return_value=prefs):
            hint = get_rl_hint_for_prompt()

        assert "Prefer:" in hint
        assert "Avoid:" in hint
        assert "alpha" in hint
        assert "beta" in hint
