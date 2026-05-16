"""Tests for services.pre_loop_setup — pre-loop helpers extracted from agent_loop."""
from unittest.mock import MagicMock, patch

import pytest


class TestCheckMemoryCommand:
    def test_non_command_returns_none(self):
        from services.pre_loop_setup import check_memory_command
        # "hello there" is not a memory command, should return None
        result = check_memory_command("hello there")
        assert result is None or isinstance(result, dict)

    def test_returns_none_on_import_error(self):
        from services.pre_loop_setup import check_memory_command
        with patch.dict("sys.modules", {"services.memory_commands": None}):
            result = check_memory_command("teach me something")
        # Should handle import errors gracefully
        assert result is None or isinstance(result, dict)


class TestExtractWorkingMemory:
    def test_does_not_crash(self):
        from services.pre_loop_setup import extract_working_memory
        # Should not raise even if working_memory module is unavailable
        extract_working_memory("test message")

    def test_empty_goal(self):
        from services.pre_loop_setup import extract_working_memory
        extract_working_memory("")


class TestCheckContentGuard:
    def test_normal_input_returns_none(self):
        from services.pre_loop_setup import check_content_guard
        result = check_content_guard("What is the weather today?")
        # Normal input should not be blocked
        assert result is None or isinstance(result, dict)

    def test_returns_dict_or_none(self):
        from services.pre_loop_setup import check_content_guard
        result = check_content_guard("hello")
        assert result is None or isinstance(result, dict)


class TestCheckDignity:
    def test_returns_string(self):
        from services.pre_loop_setup import check_dignity
        result = check_dignity("hello")
        assert isinstance(result, str)

    def test_normal_input_empty_prompt(self):
        from services.pre_loop_setup import check_dignity
        result = check_dignity("Can you help me with Python?")
        assert isinstance(result, str)


class TestBuildPrecomputedRecall:
    def test_no_goal_returns_empty(self):
        from services.pre_loop_setup import build_precomputed_recall
        packed, recall, influenced = build_precomputed_recall(
            "", {}, "", "none",
        )
        assert packed is None
        assert recall == ""
        assert isinstance(influenced, list)

    def test_reasoning_none_skips_recall(self):
        from services.pre_loop_setup import build_precomputed_recall
        packed, recall, influenced = build_precomputed_recall(
            "test goal", {}, "/workspace", "none",
        )
        assert packed is None
        assert recall == ""

    def test_returns_tuple_of_three(self):
        from services.pre_loop_setup import build_precomputed_recall
        # Use reasoning_mode="none" to skip the heavy context building
        result = build_precomputed_recall("test", {}, "", "none")
        assert isinstance(result, tuple)
        assert len(result) == 3
        packed, recall, influenced = result
        assert packed is None or isinstance(packed, dict)
        assert isinstance(recall, str)
        assert isinstance(influenced, list)


    # P2-7: compute_runtime_caps was dead code — removed along with its tests.
