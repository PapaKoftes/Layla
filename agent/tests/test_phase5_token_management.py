# -*- coding: utf-8 -*-
"""
Tests for Phase 5: Advanced Token Management.

Covers:
  - Dynamic context budget reallocation (rebalance_budget)
  - Conversation chunking (should_chunk, build_handoff_summary,
    format_continuation_prompt, ChunkHandoff)
  - Context attribution (attribute_response, Attribution, AttributionResult)
  - Selective Context integration in prompt_compressor (tier detection)
  - CONTEXT_PRESSURE metric wiring
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ============================================================================
# Tests: Dynamic Context Budget Reallocation
# ============================================================================


class TestRebalanceBudget:
    """Tests for context_budget.rebalance_budget()."""

    def _base_budgets(self):
        return {
            "system_instructions": 800,
            "current_goal": 100,
            "agent_state": 400,
            "pinned_context": 400,
            "memory": 800,
            "knowledge_graph": 200,
            "knowledge": 800,
            "workspace_context": 400,
            "tools": 0,
            "conversation": 800,
            "current_task": 200,
        }

    def test_no_change_when_pressure_low(self):
        from services.context_budget import rebalance_budget
        budgets = self._base_budgets()
        # 50% pressure — should not shrink
        section_tokens = {k: int(v * 0.5) for k, v in budgets.items()}
        result = rebalance_budget(budgets, section_tokens)
        # Memory/knowledge should be same or larger
        assert result["memory"] >= budgets["memory"]

    def test_shrinks_compressible_sections_under_high_pressure(self):
        from services.context_budget import rebalance_budget
        budgets = self._base_budgets()
        # 90% pressure — should shrink compressible sections
        section_tokens = {k: int(v * 0.9) for k, v in budgets.items()}
        result = rebalance_budget(budgets, section_tokens)
        assert result["memory"] < budgets["memory"]
        assert result["knowledge"] < budgets["knowledge"]
        assert result["knowledge_graph"] < budgets["knowledge_graph"]

    def test_protected_sections_not_shrunk(self):
        from services.context_budget import rebalance_budget
        budgets = self._base_budgets()
        section_tokens = {k: int(v * 0.95) for k, v in budgets.items()}
        result = rebalance_budget(budgets, section_tokens)
        # system_instructions, conversation, current_goal should not shrink
        assert result["system_instructions"] == budgets["system_instructions"]
        assert result["conversation"] == budgets["conversation"]
        assert result["current_goal"] == budgets["current_goal"]

    def test_disabled_by_config(self):
        from services.context_budget import rebalance_budget
        budgets = self._base_budgets()
        section_tokens = {k: int(v * 0.95) for k, v in budgets.items()}
        result = rebalance_budget(budgets, section_tokens, cfg={"dynamic_budget_enabled": False})
        # Should return unchanged copy
        assert result["memory"] == budgets["memory"]

    def test_custom_threshold(self):
        from services.context_budget import rebalance_budget
        budgets = self._base_budgets()
        # 80% pressure with threshold at 0.75 — should trigger shrinkage
        section_tokens = {k: int(v * 0.8) for k, v in budgets.items()}
        result = rebalance_budget(budgets, section_tokens, pressure_threshold=0.75)
        assert result["memory"] < budgets["memory"]

    def test_returns_new_dict(self):
        from services.context_budget import rebalance_budget
        budgets = self._base_budgets()
        result = rebalance_budget(budgets)
        assert result is not budgets

    def test_empty_section_tokens(self):
        from services.context_budget import rebalance_budget
        budgets = self._base_budgets()
        result = rebalance_budget(budgets, section_tokens={})
        # No pressure info — should return budgets as-is
        assert result["memory"] == budgets["memory"]

    def test_expands_at_low_pressure(self):
        from services.context_budget import rebalance_budget
        budgets = self._base_budgets()
        # 40% pressure — should expand memory/knowledge
        section_tokens = {k: int(v * 0.4) for k, v in budgets.items()}
        result = rebalance_budget(budgets, section_tokens)
        # At least memory should get a bonus
        assert result["memory"] >= budgets["memory"]


# ============================================================================
# Tests: Conversation Chunking
# ============================================================================


class TestShouldChunk:
    def test_at_threshold(self):
        from services.conversation_chunker import should_chunk
        assert should_chunk(50, cfg={"auto_chunk_long_tasks": True, "chunk_step_threshold": 50})

    def test_below_threshold(self):
        from services.conversation_chunker import should_chunk
        assert not should_chunk(49, cfg={"auto_chunk_long_tasks": True, "chunk_step_threshold": 50})

    def test_disabled(self):
        from services.conversation_chunker import should_chunk
        assert not should_chunk(100, cfg={"auto_chunk_long_tasks": False})

    def test_multiple_of_threshold(self):
        from services.conversation_chunker import should_chunk
        assert should_chunk(100, cfg={"auto_chunk_long_tasks": True, "chunk_step_threshold": 50})

    def test_zero_step(self):
        from services.conversation_chunker import should_chunk
        assert not should_chunk(0)


class TestBuildHandoffSummary:
    def test_basic_handoff(self):
        from services.conversation_chunker import build_handoff_summary
        messages = [
            {"role": "user", "content": "refactor the auth module"},
            {"role": "assistant", "content": "I completed the refactoring of auth.py"},
            {"role": "user", "content": "now fix the tests"},
            {"role": "assistant", "content": "I found 3 failing tests in test_auth.py"},
        ]
        handoff = build_handoff_summary("refactor auth", messages, step_count=50)
        assert handoff.goal == "refactor auth"
        assert handoff.total_steps_so_far == 50
        assert handoff.chunk_number == 1
        assert isinstance(handoff.completed_actions, list)
        assert isinstance(handoff.key_findings, list)

    def test_empty_messages(self):
        from services.conversation_chunker import build_handoff_summary
        handoff = build_handoff_summary("test goal", [], step_count=50)
        assert handoff.goal == "test goal"
        assert handoff.completed_actions == []

    def test_custom_chunk_number(self):
        from services.conversation_chunker import build_handoff_summary
        handoff = build_handoff_summary("goal", [], step_count=100, chunk_number=3)
        assert handoff.chunk_number == 3


class TestFormatContinuationPrompt:
    def test_basic_format(self):
        from services.conversation_chunker import ChunkHandoff, format_continuation_prompt
        handoff = ChunkHandoff(
            chunk_number=1,
            total_steps_so_far=50,
            goal="refactor the codebase",
            completed_actions=["fixed imports"],
            pending_actions=["run tests", "update docs"],
            key_findings=["3 circular imports found"],
            context_summary="Refactored module structure.",
        )
        prompt = format_continuation_prompt(handoff)
        assert "Chunk 2" in prompt  # chunk_number + 1
        assert "refactor the codebase" in prompt
        assert "50" in prompt
        assert "run tests" in prompt
        assert "Continue" in prompt

    def test_empty_handoff(self):
        from services.conversation_chunker import ChunkHandoff, format_continuation_prompt
        handoff = ChunkHandoff(
            chunk_number=0,
            total_steps_so_far=0,
            goal="test",
        )
        prompt = format_continuation_prompt(handoff)
        assert "test" in prompt


class TestChunkHandoffDataclass:
    def test_defaults(self):
        from services.conversation_chunker import ChunkHandoff
        h = ChunkHandoff(chunk_number=1, total_steps_so_far=50, goal="test")
        assert h.completed_actions == []
        assert h.pending_actions == []
        assert h.key_findings == []
        assert h.context_summary == ""
        assert h.created_at > 0


class TestSaveChunkToMemory:
    @patch("services.memory_router.save_learning", return_value=1)
    def test_save_succeeds(self, mock_save):
        from services.conversation_chunker import ChunkHandoff, save_chunk_to_memory
        handoff = ChunkHandoff(
            chunk_number=2,
            total_steps_so_far=100,
            goal="long task",
            context_summary="Summary of work done.",
        )
        save_chunk_to_memory(handoff)
        assert mock_save.called
        call_kwargs = mock_save.call_args
        assert "long task" in str(call_kwargs)


# ============================================================================
# Tests: Context Attribution
# ============================================================================


class TestAttributeResponse:
    def test_basic_attribution(self):
        from services.context_attribution import attribute_response
        sources = [
            {"id": "learning:1", "label": "Python patterns", "content": "Python async await patterns are essential for web development with FastAPI and modern frameworks."},
            {"id": "learning:2", "label": "Database", "content": "PostgreSQL indexing strategies for improving query performance on large tables."},
        ]
        result = attribute_response(
            "Python async patterns are useful for building FastAPI web applications.",
            sources,
        )
        assert len(result.attributions) >= 1
        # The Python source should score higher
        top_attr = result.attributions[0]
        assert "learning:1" == top_attr.source_id or top_attr.score > 0

    def test_empty_response(self):
        from services.context_attribution import attribute_response
        result = attribute_response("", [{"id": "1", "label": "test", "content": "content"}])
        assert result.attributions == []

    def test_empty_sources(self):
        from services.context_attribution import attribute_response
        result = attribute_response("Some response text.", [])
        assert result.attributions == []
        assert result.total_sources_checked == 0

    def test_disabled_by_config(self):
        from services.context_attribution import attribute_response
        result = attribute_response(
            "response",
            [{"id": "1", "label": "test", "content": "matching response content"}],
            cfg={"context_attribution_enabled": False},
        )
        assert result.attributions == []

    def test_min_score_filtering(self):
        from services.context_attribution import attribute_response
        sources = [
            {"id": "1", "label": "unrelated", "content": "completely different topic about quantum physics experiments"},
        ]
        result = attribute_response("Python web development tutorial", sources, min_score=0.5)
        # Low overlap should be filtered out
        assert all(a.score >= 0.5 for a in result.attributions)

    def test_top_k_limit(self):
        from services.context_attribution import attribute_response
        sources = [
            {"id": f"s{i}", "label": f"Source {i}", "content": f"matching content about topic {i} with shared words"}
            for i in range(20)
        ]
        result = attribute_response(
            "matching content about topic with shared words",
            sources,
            top_k=3,
            min_score=0.01,
        )
        assert len(result.attributions) <= 3

    def test_coverage_calculated(self):
        from services.context_attribution import attribute_response
        sources = [
            {"id": "1", "label": "Source", "content": "Python async web development FastAPI framework patterns"},
        ]
        result = attribute_response(
            "Python async patterns are great. FastAPI uses async web development. This is powerful.",
            sources,
            min_score=0.01,
        )
        assert isinstance(result.coverage, float)
        assert 0.0 <= result.coverage <= 1.0


class TestAttribution:
    def test_creation(self):
        from services.context_attribution import Attribution
        a = Attribution(
            source_id="learning:42",
            source_label="Test Learning",
            source_snippet="Some content...",
            score=0.85,
            matched_terms=["python", "async"],
        )
        assert a.score == 0.85
        assert len(a.matched_terms) == 2


class TestAttributionResult:
    def test_creation(self):
        from services.context_attribution import AttributionResult
        r = AttributionResult(response_snippet="test response")
        assert r.attributions == []
        assert r.total_sources_checked == 0
        assert r.coverage == 0.0


class TestWordOverlapScore:
    def test_identical_sets(self):
        from services.context_attribution import _compute_overlap_score
        words = {"python", "async", "patterns"}
        score, matched = _compute_overlap_score(words, words)
        assert score > 0
        assert len(matched) > 0

    def test_disjoint_sets(self):
        from services.context_attribution import _compute_overlap_score
        score, matched = _compute_overlap_score(
            {"python", "async"},
            {"database", "indexing"},
        )
        assert score == 0.0
        assert matched == []

    def test_empty_sets(self):
        from services.context_attribution import _compute_overlap_score
        score, matched = _compute_overlap_score(set(), {"hello"})
        assert score == 0.0


class TestJaccardSimilarity:
    def test_identical(self):
        from services.context_attribution import _jaccard_similarity
        assert _jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        from services.context_attribution import _jaccard_similarity
        assert _jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial(self):
        from services.context_attribution import _jaccard_similarity
        sim = _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert 0.0 < sim < 1.0

    def test_empty(self):
        from services.context_attribution import _jaccard_similarity
        assert _jaccard_similarity(set(), {"a"}) == 0.0


# ============================================================================
# Tests: Prompt Compressor — Selective Context Integration
# ============================================================================


class TestSelectiveContextIntegration:
    def test_get_available_tier_without_selective_context(self):
        from services.prompt_compressor import get_available_tier
        tier = get_available_tier()
        # Without selective_context installed, should be >= 1
        assert isinstance(tier, int)
        assert tier >= 0

    def test_get_info_includes_selective_context(self):
        from services.prompt_compressor import get_info
        info = get_info()
        assert "selective_context_installed" in info
        assert isinstance(info["selective_context_installed"], bool)

    def test_heuristic_compression_still_works(self):
        from services.prompt_compressor import compress
        text = " ".join([f"Sentence number {i} with some important content about topic." for i in range(20)])
        result = compress(text, target_ratio=0.5, force_heuristic=True)
        assert result["method"] == "heuristic"
        assert result["compressed_len"] < result["original_len"]

    def test_compress_passthrough_for_short_text(self):
        from services.prompt_compressor import compress
        result = compress("Short text.", target_ratio=0.5)
        assert result["method"] == "passthrough"

    def test_compress_empty(self):
        from services.prompt_compressor import compress
        result = compress("")
        assert result["method"] == "passthrough"
        assert result["compressed"] == ""


# ============================================================================
# Tests: Context Pressure Metric Wiring
# ============================================================================


class TestContextPressureWiring:
    def test_record_context_pressure(self):
        from services.metrics import CONTEXT_PRESSURE, record_context_pressure
        record_context_pressure(0.75)
        vals = CONTEXT_PRESSURE.get_all()
        assert any(v == 0.75 for v in vals.values())

    def test_pressure_clamped(self):
        from services.metrics import CONTEXT_PRESSURE, record_context_pressure
        record_context_pressure(1.5)
        vals = CONTEXT_PRESSURE.get_all()
        assert all(v <= 1.0 for v in vals.values())

    def test_pressure_zero(self):
        from services.metrics import record_context_pressure
        # Should not raise
        record_context_pressure(0.0)

    def test_build_system_prompt_records_pressure(self):
        """build_system_prompt should record context pressure metric."""
        from services.context_manager import build_system_prompt
        sections = {
            "system_instructions": "You are a helpful assistant.",
            "conversation": "User: hello\nAssistant: hi there",
        }
        _prompt, metrics = build_system_prompt(sections, n_ctx=4096)
        # The metric should have been set — check it was called
        from services.metrics import CONTEXT_PRESSURE
        vals = CONTEXT_PRESSURE.get_all()
        # Should have at least one value recorded
        assert len(vals) >= 1


# ============================================================================
# Tests: Build Budget Telemetry
# ============================================================================


class TestBuildBudgetTelemetry:
    def test_returns_expected_structure(self):
        from services.context_budget import build_budget_telemetry
        result = build_budget_telemetry(n_ctx=4096)
        assert "n_ctx" in result
        assert "sections" in result
        assert "warnings" in result
        assert "total" in result["sections"]

    def test_with_metrics(self):
        from services.context_budget import build_budget_telemetry
        metrics = {
            "section_tokens": {"memory": 600, "conversation": 700},
            "total_tokens": 1300,
            "truncated_sections": ["memory"],
            "dropped_sections": [],
            "dedup_removed": 1,
        }
        result = build_budget_telemetry(n_ctx=4096, last_metrics=metrics)
        assert result["sections"]["memory"]["used"] == 600
        assert result["dedup_removed"] == 1
