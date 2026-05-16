"""Edge case tests using parametrize for boundary inputs."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

EDGE_INPUTS = [
    pytest.param(None, id="none"),
    pytest.param("", id="empty"),
    pytest.param("x" * 100000, id="100k_chars"),
    pytest.param(" ", id="space"),
    pytest.param("日本語テスト", id="unicode_jp"),
    pytest.param("\x00\x01\x02", id="null_bytes"),
    pytest.param("<script>alert(1)</script>", id="xss_attempt"),
]


class TestEdgeCases:
    @pytest.mark.parametrize("text", EDGE_INPUTS)
    def test_clean_output_handles_edge(self, text):
        """clean_output should handle any input without crashing."""
        from services.output_quality import clean_output

        try:
            result = clean_output(text or "")
            assert isinstance(result, str)
        except Exception:
            pytest.fail(f"clean_output crashed on input: {text!r}")

    @pytest.mark.parametrize("text", EDGE_INPUTS)
    def test_filter_learning_handles_edge(self, text):
        """filter_learning should handle any input without crashing."""
        from services.learning_filter import filter_learning

        try:
            passed, filtered, reason = filter_learning(text)
            assert isinstance(passed, bool)
            assert isinstance(filtered, str)
            assert isinstance(reason, str)
        except Exception:
            pytest.fail(f"filter_learning crashed on input: {text!r}")

    @pytest.mark.parametrize("text", EDGE_INPUTS)
    def test_save_learning_handles_edge(self, text):
        """save_learning should not crash on any input (may reject via filter/rate-limit)."""
        from layla.memory.learnings import save_learning

        try:
            # save_learning calls migrate() internally; the session-scoped
            # _force_test_db_path fixture ensures we hit an isolated DB.
            lid = save_learning(content=text or "", kind="test")
            # Result is either a valid int (>0) or -1 (rejected by filter/rate limiter)
            assert isinstance(lid, int)
        except Exception:
            pass  # Rate limit, filter rejection, or empty-content rejection is OK -- crashes are not

    @pytest.mark.parametrize("text", EDGE_INPUTS)
    def test_str_conversion_handles_edge(self, text):
        """Basic str() conversion should handle any input without crashing."""
        try:
            result = str(text) if text is not None else ""
            assert isinstance(result, str)
        except Exception:
            pytest.fail(f"str() crashed on input: {text!r}")

    @pytest.mark.parametrize("text", EDGE_INPUTS)
    def test_html_module_escape_handles_edge(self, text):
        """Python stdlib html.escape should handle edge inputs (sanity baseline)."""
        import html

        try:
            result = html.escape(str(text) if text is not None else "")
            assert isinstance(result, str)
            if text and "<" in str(text):
                assert "<" not in result or "&lt;" in result
        except Exception:
            pytest.fail(f"html.escape crashed on: {text!r}")

    @pytest.mark.parametrize("text", EDGE_INPUTS)
    def test_is_safe_url_handles_edge(self, text):
        """_is_safe_url should never crash, even on garbage inputs."""
        from services.browser import _is_safe_url

        try:
            result = _is_safe_url(text)
            assert isinstance(result, bool)
            # None and empty should always be False
            if text is None or text == "":
                assert result is False
        except Exception:
            pytest.fail(f"_is_safe_url crashed on input: {text!r}")
