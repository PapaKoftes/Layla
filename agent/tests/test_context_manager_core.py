"""Tests for services.context_manager — token estimation, compaction, dedup, and prompt assembly."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.context_manager import (
    DEFAULT_BUDGETS,
    build_system_prompt,
    deduplicate_content,
    effective_compact_threshold_ratio,
    maybe_auto_compact,
    summarize_history,
    token_estimate,
    token_estimate_messages,
    truncate_to_tokens,
)


# ===========================================================================
# token_estimate
# ===========================================================================


class TestTokenEstimate:
    """Tests for the token_estimate helper."""

    def test_positive_for_nonempty_text(self):
        result = token_estimate("Hello, world!")
        assert isinstance(result, int)
        assert result > 0

    def test_zero_for_empty_string(self):
        assert token_estimate("") == 0

    def test_longer_text_higher_count(self):
        short = token_estimate("hi")
        long = token_estimate("This is a significantly longer piece of text with many words.")
        assert long > short


# ===========================================================================
# token_estimate_messages
# ===========================================================================


class TestTokenEstimateMessages:
    """Tests for token_estimate_messages."""

    def test_sums_across_messages(self):
        msgs = [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi, how can I help you?"},
        ]
        total = token_estimate_messages(msgs)
        assert isinstance(total, int)
        assert total > 0

    def test_empty_messages_returns_zero(self):
        assert token_estimate_messages([]) == 0

    def test_single_message(self):
        msgs = [{"role": "user", "content": "Test message"}]
        total = token_estimate_messages(msgs)
        single_content = token_estimate("Test message")
        # Should be content tokens + overhead (~4 per message)
        assert total >= single_content

    def test_handles_missing_content(self):
        msgs = [{"role": "user"}]  # no "content" key
        total = token_estimate_messages(msgs)
        # Should not raise; empty content → overhead only
        assert isinstance(total, int)


# ===========================================================================
# effective_compact_threshold_ratio
# ===========================================================================


class TestEffectiveCompactThresholdRatio:
    """Tests for effective_compact_threshold_ratio."""

    def test_returns_base_ratio_no_aggressive(self):
        cfg = {"context_auto_compact_ratio": 0.75}
        result = effective_compact_threshold_ratio(cfg, n_ctx=16384)
        assert result == 0.75

    def test_default_ratio_when_key_missing(self):
        result = effective_compact_threshold_ratio({}, n_ctx=16384)
        assert result == 0.75

    def test_none_config_returns_default(self):
        result = effective_compact_threshold_ratio(None, n_ctx=16384)
        assert result == 0.75

    def test_aggressive_small_context(self):
        cfg = {
            "context_auto_compact_ratio": 0.75,
            "context_aggressive_compress_enabled": True,
        }
        result = effective_compact_threshold_ratio(cfg, n_ctx=4096)
        assert result == 0.52

    def test_aggressive_medium_context(self):
        cfg = {
            "context_auto_compact_ratio": 0.75,
            "context_aggressive_compress_enabled": True,
        }
        result = effective_compact_threshold_ratio(cfg, n_ctx=16384)
        assert result == 0.62

    def test_aggressive_does_not_raise_base(self):
        """Aggressive mode caps at min(base, threshold), never raises it."""
        cfg = {
            "context_auto_compact_ratio": 0.50,
            "context_aggressive_compress_enabled": True,
        }
        result = effective_compact_threshold_ratio(cfg, n_ctx=4096)
        assert result == 0.50  # min(0.50, 0.52) = 0.50


# ===========================================================================
# summarize_history
# ===========================================================================


class TestSummarizeHistory:
    """Tests for summarize_history."""

    def test_under_threshold_returns_unchanged(self):
        msgs = [
            {"role": "user", "content": "Short question"},
            {"role": "assistant", "content": "Short answer"},
        ]
        result = summarize_history(msgs, n_ctx=100000, threshold_ratio=0.75)
        assert result == msgs

    def test_over_threshold_compresses(self, mock_llm):
        """When over threshold, should call LLM and compress."""
        mock_llm.return_value = {
            "choices": [{"message": {"content": "- Key fact 1\n- Decision made\n- Result obtained"}}]
        }
        # Create messages large enough to exceed the threshold
        big_content = "x " * 2000
        msgs = [
            {"role": "user", "content": big_content},
            {"role": "assistant", "content": big_content},
            {"role": "user", "content": big_content},
            {"role": "assistant", "content": big_content},
            {"role": "user", "content": "Latest question"},
        ]
        # Use a tight context to force compression
        with patch("services.context_manager.token_estimate_messages") as mock_est:
            # First call: total (over threshold); subsequent calls measure output
            mock_est.side_effect = [5000, 100]
            with patch("services.context_manager._compress_to_summary") as mock_compress:
                mock_compress.return_value = "[Earlier conversation summary]\n- Bullet 1"
                result = summarize_history(msgs, n_ctx=4096, threshold_ratio=0.5)

        # The result should be shorter (summary + tail)
        assert len(result) < len(msgs)
        assert result[0]["role"] == "system"
        assert "summary" in result[0]["content"].lower()

    def test_keep_recent_messages(self):
        """With keep_recent_messages > 0, only prefix is compressed."""
        msgs = [
            {"role": "user", "content": "Old message " * 200},
            {"role": "assistant", "content": "Old reply " * 200},
            {"role": "user", "content": "Recent question"},
            {"role": "assistant", "content": "Recent answer"},
        ]
        with patch("services.context_manager.token_estimate_messages", return_value=8000):
            with patch("services.context_manager._compress_to_summary") as mock_compress:
                mock_compress.return_value = "[Earlier conversation (truncated)]\nOld stuff"
                result = summarize_history(
                    msgs, n_ctx=4096, threshold_ratio=0.5, keep_recent_messages=2,
                )

        # Last 2 messages should be preserved verbatim
        assert result[-1]["content"] == "Recent answer"
        assert result[-2]["content"] == "Recent question"


# ===========================================================================
# maybe_auto_compact
# ===========================================================================


class TestMaybeAutoCompact:
    """Tests for maybe_auto_compact."""

    def test_delegates_to_summarize_history(self):
        msgs = [{"role": "user", "content": "Hello"}]
        with patch("services.context_manager.summarize_history", return_value=msgs) as mock_sh:
            result = maybe_auto_compact(msgs, n_ctx=16384, cfg={})
        mock_sh.assert_called_once()
        assert result == msgs

    def test_aggressive_sets_keep_10(self):
        msgs = [{"role": "user", "content": "Hello"}]
        cfg = {"context_aggressive_compress_enabled": True}
        with patch("services.context_manager.summarize_history", return_value=msgs) as mock_sh:
            maybe_auto_compact(msgs, n_ctx=16384, cfg=cfg)
        _, kwargs = mock_sh.call_args
        assert kwargs["keep_recent_messages"] == 10

    def test_explicit_keep_overrides_aggressive_default(self):
        msgs = [{"role": "user", "content": "Hello"}]
        cfg = {
            "context_aggressive_compress_enabled": True,
            "context_sliding_keep_messages": 5,
        }
        with patch("services.context_manager.summarize_history", return_value=msgs) as mock_sh:
            maybe_auto_compact(msgs, n_ctx=16384, cfg=cfg)
        _, kwargs = mock_sh.call_args
        assert kwargs["keep_recent_messages"] == 5


# ===========================================================================
# truncate_to_tokens
# ===========================================================================


class TestTruncateToTokens:
    """Tests for truncate_to_tokens."""

    def test_returns_original_when_under_budget(self):
        text = "Short text"
        result = truncate_to_tokens(text, max_tokens=1000)
        assert result == text

    def test_truncates_long_text(self):
        text = "word " * 5000
        result = truncate_to_tokens(text, max_tokens=50)
        assert len(result) < len(text)
        assert result.endswith("...")

    def test_empty_text_returns_empty(self):
        assert truncate_to_tokens("", max_tokens=100) == ""

    def test_zero_budget_returns_empty(self):
        assert truncate_to_tokens("Some text", max_tokens=0) == ""

    def test_negative_budget_returns_empty(self):
        assert truncate_to_tokens("Some text", max_tokens=-5) == ""

    def test_custom_suffix(self):
        text = "word " * 5000
        result = truncate_to_tokens(text, max_tokens=50, suffix="[CUT]")
        assert result.endswith("[CUT]")


# ===========================================================================
# deduplicate_content
# ===========================================================================


class TestDeduplicateContent:
    """Tests for deduplicate_content."""

    def test_removes_exact_duplicates(self):
        items = ["Alpha bravo charlie", "Alpha bravo charlie", "Delta echo"]
        result = deduplicate_content(items, key_len=80)
        assert result == ["Alpha bravo charlie", "Delta echo"]

    def test_preserves_order_first_wins(self):
        items = ["First item", "Second item", "First item"]
        result = deduplicate_content(items, key_len=80)
        assert result == ["First item", "Second item"]

    def test_empty_items_filtered(self):
        items = ["", "   ", None, "Real content"]  # type: ignore[list-item]
        result = deduplicate_content(items, key_len=80)
        assert result == ["Real content"]

    def test_no_items(self):
        assert deduplicate_content([], key_len=80) == []

    def test_short_key_len_groups_by_prefix(self):
        items = [
            "Common prefix followed by A",
            "Common prefix followed by B",
            "Different start",
        ]
        result = deduplicate_content(items, key_len=14)
        # "Common prefix " is 14 chars → both map to same fingerprint; first wins
        assert len(result) == 2
        assert result[0] == "Common prefix followed by A"
        assert result[1] == "Different start"

    def test_all_unique(self):
        items = ["Alpha", "Bravo", "Charlie"]
        result = deduplicate_content(items, key_len=80)
        assert result == items


# ===========================================================================
# build_system_prompt
# ===========================================================================


class TestBuildSystemPrompt:
    """Tests for build_system_prompt."""

    def _patch_externals(self):
        """Return a stack of patches for external dependencies."""
        return [
            patch("services.context_manager.get_last_prompt_metrics", return_value=({}, 4096)),
            patch("services.context_manager.record_prompt_metrics"),
        ]

    def test_assembles_sections_in_order(self):
        sections = {
            "system_instructions": "You are Layla.",
            "current_goal": "Help the user.",
            "current_task": "Answer the question.",
        }
        # Use a large context to avoid truncation
        prompt, metrics = build_system_prompt(
            sections, n_ctx=100000, budgets=DEFAULT_BUDGETS.copy(),
        )
        assert "You are Layla" in prompt
        assert "Help the user" in prompt
        assert "Answer the question" in prompt
        # system_instructions should come before current_task
        assert prompt.index("You are Layla") < prompt.index("Answer the question")

    def test_respects_token_budgets(self):
        big_text = "filler " * 5000
        sections = {
            "system_instructions": big_text,
            "memory": "Important memory",
        }
        budgets = {"system_instructions": 50, "memory": 200}
        prompt, metrics = build_system_prompt(
            sections, n_ctx=100000, budgets=budgets,
        )
        # The system_instructions section should have been truncated
        assert len(prompt) < len(big_text)
        assert "truncated_sections" in metrics

    def test_returns_metrics_dict(self):
        sections = {"system_instructions": "Identity text."}
        _, metrics = build_system_prompt(
            sections, n_ctx=100000, budgets=DEFAULT_BUDGETS.copy(),
        )
        assert isinstance(metrics, dict)
        assert "section_tokens" in metrics
        assert "total_tokens" in metrics
        assert "truncated_sections" in metrics
        assert "dropped_sections" in metrics
        assert "dedup_removed" in metrics

    def test_empty_sections(self):
        prompt, metrics = build_system_prompt(
            {}, n_ctx=100000, budgets=DEFAULT_BUDGETS.copy(),
        )
        assert prompt == ""
        assert metrics["total_tokens"] == 0

    def test_drops_sections_when_budget_exhausted(self):
        sections = {
            "system_instructions": "Important identity " * 200,
            "current_goal": "Goal text",
            "memory": "Memory data " * 200,
            "current_task": "Do this thing",
        }
        # Very small total budget so later sections get dropped
        budgets = {
            "system_instructions": 30,
            "current_goal": 10,
            "memory": 10,
            "current_task": 10,
        }
        prompt, metrics = build_system_prompt(
            sections, n_ctx=120, budgets=budgets, reserve_for_response=50,
        )
        # Some sections should be either truncated or dropped
        has_pressure = (
            len(metrics["truncated_sections"]) > 0
            or len(metrics["dropped_sections"]) > 0
        )
        assert has_pressure

    def test_deduplicates_memory_sections(self):
        """When memory and knowledge_graph have identical content, dedup should remove one."""
        sections = {
            "system_instructions": "Identity.",
            "memory": "The user likes Python.",
            "knowledge_graph": "The user likes Python.",
        }
        budgets = {"system_instructions": 200, "memory": 200, "knowledge_graph": 200}
        # Disable structure labels so headers don't make otherwise-identical
        # content appear unique to the deduplication fingerprinting.
        with patch("runtime_safety.load_config", return_value={"prompt_structure_labels": False}):
            _, metrics = build_system_prompt(
                sections, n_ctx=100000, budgets=budgets,
            )
        assert metrics["dedup_removed"] >= 1

    def test_section_tokens_recorded(self):
        sections = {
            "system_instructions": "Be helpful.",
            "current_task": "Solve the puzzle.",
        }
        _, metrics = build_system_prompt(
            sections, n_ctx=100000, budgets=DEFAULT_BUDGETS.copy(),
        )
        assert "system_instructions" in metrics["section_tokens"]
        assert metrics["section_tokens"]["system_instructions"] > 0
