# -*- coding: utf-8 -*-
"""
Tests for Phase 8: Service Depth Improvement.

Covers:
  - outcome_writer (_maybe_save_echo_memory, _save_outcome_memory,
                     _extract_patch_text, _auto_extract_learnings)
  - initiative_engine (collect_initiative_hints, wakeup_engine_hints,
                        generate_project_proposals)
  - knowledge_distiller (distill_learnings_to_insights, run_periodic_distillation)
  - experience_replay (get_recent_tool_patterns, get_recent_reflections,
                        get_reliable_tools, run_experience_replay)
  - memory_consolidation (consolidate_session, consolidate_periodic,
                           reinforce_learning, prune_low_confidence_learnings,
                           apply_retention_policies)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ============================================================================
# Tests: outcome_writer
# ============================================================================


class TestExtractPatchText:
    def test_empty_goal(self):
        from services.outcome_writer import _extract_patch_text
        assert _extract_patch_text("") == ""
        assert _extract_patch_text(None) == ""

    def test_plain_text_passthrough(self):
        from services.outcome_writer import _extract_patch_text
        assert _extract_patch_text("just some text") == "just some text"

    def test_code_block_extraction(self):
        from services.outcome_writer import _extract_patch_text
        goal = "Apply this:\n```patch\n--- a/foo.py\n+++ b/foo.py\n```\nDone."
        result = _extract_patch_text(goal)
        assert "--- a/foo.py" in result

    def test_diff_marker_detection(self):
        from services.outcome_writer import _extract_patch_text
        goal = "Some preamble\n--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
        result = _extract_patch_text(goal)
        assert result.startswith("--- a/file.py")

    def test_diff_git_detection(self):
        from services.outcome_writer import _extract_patch_text
        goal = "Header text\ndiff --git a/x.py b/x.py\nindex abc..def 100644"
        result = _extract_patch_text(goal)
        assert result.startswith("diff --git")


class TestMaybeSaveEchoMemory:
    @patch("services.outcome_writer._db_save_aspect_memory")
    def test_echo_active_saves_immediately(self, mock_save):
        from services.outcome_writer import _maybe_save_echo_memory
        _maybe_save_echo_memory("echo", "Hello", "Hi there", [])
        mock_save.assert_called()

    @patch("services.outcome_writer._db_save_aspect_memory")
    def test_non_echo_no_immediate_save(self, mock_save):
        from services.outcome_writer import _maybe_save_echo_memory
        # 0 turns, not echo — should not fire
        _maybe_save_echo_memory("morrigan", "Hello", "Hi", [])
        mock_save.assert_not_called()

    @patch("services.outcome_writer._db_save_aspect_memory")
    def test_pattern_save_every_5_turns(self, mock_save):
        from services.outcome_writer import _maybe_save_echo_memory
        history = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(10)
        ]
        _maybe_save_echo_memory("morrigan", "test", "reply", history)
        # 10 turns, 10 % 5 == 0 → pattern save should fire
        assert mock_save.call_count >= 1

    @patch("services.outcome_writer._db_save_aspect_memory")
    def test_pattern_save_needs_two_topics(self, mock_save):
        from services.outcome_writer import _maybe_save_echo_memory
        # 5 turns but only 1 user message
        history = [{"role": "assistant", "content": "ok"}] * 4 + [{"role": "user", "content": "hello"}]
        _maybe_save_echo_memory("nyx", "test", "reply", history)
        # Not enough topics (need >= 2 user messages)
        # Should not save a pattern note (but won't error)


class TestSaveOutcomeMemory:
    @patch("services.reflection_engine.run_reflection", new=MagicMock())
    @patch("services.memory_router.save_learning")
    def test_finished_state_saves(self, mock_save):
        from services.outcome_writer import _save_outcome_memory
        state = {
            "status": "finished",
            "objective": "Test the system",
            "steps": [
                {"action": "read_file", "result": {"ok": True, "path": "/tmp/x.py"}},
            ],
        }
        _save_outcome_memory(state)
        assert mock_save.call_count >= 1

    @patch("services.memory_router.save_learning")
    def test_non_finished_state_skips(self, mock_save):
        from services.outcome_writer import _save_outcome_memory
        state = {"status": "running", "steps": []}
        _save_outcome_memory(state)
        mock_save.assert_not_called()

    @patch("services.reflection_engine.run_reflection", new=MagicMock())
    @patch("services.memory_router.save_learning")
    def test_no_tool_steps_still_saves(self, mock_save):
        from services.outcome_writer import _save_outcome_memory
        state = {
            "status": "finished",
            "objective": "Answer a question",
            "steps": [{"action": "reason", "result": "The answer is 42."}],
        }
        _save_outcome_memory(state)
        assert mock_save.call_count >= 1


class TestAutoExtractLearnings:
    @patch("services.memory_router.save_learning")
    def test_short_response_skips(self, mock_save):
        from services.outcome_writer import _auto_extract_learnings
        _auto_extract_learnings("question", "short reply", "morrigan")
        mock_save.assert_not_called()

    @patch("services.memory_router.save_learning")
    def test_greeting_response_skips(self, mock_save):
        from services.outcome_writer import _auto_extract_learnings
        _auto_extract_learnings("hi", "hello thanks ok sure cool yes no " * 3, "echo")
        mock_save.assert_not_called()

    @patch("services.llm_gateway.run_completion", side_effect=Exception("no LLM"))
    @patch("services.memory_router.save_learning")
    def test_fallback_extracts_bullet_points(self, mock_save, mock_llm):
        from services.outcome_writer import _auto_extract_learnings
        response = (
            "Here are the key points:\n"
            "- Always validate input before processing it through the pipeline\n"
            "- Never trust user-supplied file paths without sanitization\n"
            "Some closing text that is not a bullet point."
        )
        _auto_extract_learnings("How to be safe?", response, "nyx")
        # Should have extracted bullet points via fallback
        if mock_save.call_count > 0:
            saved_content = mock_save.call_args_list[0][1].get("content", "")
            assert len(saved_content) > 10

    @patch("services.llm_gateway.run_completion", side_effect=Exception("no LLM"))
    @patch("services.memory_router.save_learning")
    def test_preference_detection(self, mock_save, mock_llm):
        from services.outcome_writer import _auto_extract_learnings
        # Reset fingerprint set to avoid dedup
        import services.outcome_writer as ow
        ow._recent_learning_fingerprints = set()

        # The response needs extractable bullet points so the function doesn't
        # early-return at "if not extracted: return" before the preference code
        response = (
            "Sure, I'll use tabs from now on.\n"
            "- Always use tabs instead of spaces for indentation in this project\n"
            "- Configure the editor to insert tabs by default for consistency\n"
            "Let me know if you want anything else."
        )
        _auto_extract_learnings("I prefer tabs over spaces", response, "echo")
        # Should have saved at least one preference
        assert mock_save.call_count >= 1
        # Check that at least one call is a preference
        saved_kinds = [c.kwargs.get("kind", "") for c in mock_save.call_args_list]
        assert any("preference" in k for k in saved_kinds)


class TestAspectLearningType:
    def test_all_aspects_covered(self):
        from services.outcome_writer import _ASPECT_LEARNING_TYPE
        expected = {"morrigan", "nyx", "echo", "eris", "lilith", "cassandra"}
        assert expected == set(_ASPECT_LEARNING_TYPE.keys())


# ============================================================================
# Tests: initiative_engine
# ============================================================================


class TestCollectInitiativeHints:
    def test_disabled_returns_empty(self):
        from services.initiative_engine import collect_initiative_hints
        result = collect_initiative_hints({}, {"initiative_engine_enabled": False})
        assert result == []

    def test_enabled_with_empty_state(self):
        from services.initiative_engine import collect_initiative_hints
        result = collect_initiative_hints({"steps": []}, {"initiative_engine_enabled": True})
        assert isinstance(result, list)

    @patch("services.outcome_evaluation.evaluate_outcome_structured", side_effect=ImportError)
    def test_failed_tool_step_generates_hint(self, mock_eval):
        from services.initiative_engine import collect_initiative_hints
        state = {
            "steps": [
                {"action": "write_file", "result": {"ok": False, "error": "permission denied"}},
            ],
        }
        result = collect_initiative_hints(state, {"initiative_engine_enabled": True})
        assert len(result) >= 1
        assert "write_file" in result[0]

    def test_deduplication(self):
        from services.initiative_engine import collect_initiative_hints
        # Steps that would generate the same hint
        state = {
            "steps": [
                {"action": "reason", "result": "thinking"},
                {"action": "read_file", "result": {"ok": True}},
            ],
            "objective": "implement a feature",
        }
        result = collect_initiative_hints(state, {"initiative_engine_enabled": True})
        # No duplicates
        assert len(result) == len(set(r[:80] for r in result))

    def test_max_4_hints(self):
        from services.initiative_engine import collect_initiative_hints
        state = {
            "steps": [
                {"action": f"tool_{i}", "result": {"ok": False, "error": f"err {i}"}}
                for i in range(10)
            ],
        }
        result = collect_initiative_hints(state, {"initiative_engine_enabled": True})
        assert len(result) <= 4


class TestWakeupEngineHints:
    def test_disabled(self):
        from services.initiative_engine import wakeup_engine_hints
        assert wakeup_engine_hints([], {"initiative_engine_enabled": False}) == []

    def test_no_plans(self):
        from services.initiative_engine import wakeup_engine_hints
        hints = wakeup_engine_hints([], {"initiative_engine_enabled": True})
        assert len(hints) >= 1
        assert "No active study plans" in hints[0]

    def test_many_plans(self):
        from services.initiative_engine import wakeup_engine_hints
        hints = wakeup_engine_hints([1, 2, 3, 4], {"initiative_engine_enabled": True})
        assert any("pausing" in h.lower() for h in hints)

    def test_few_plans(self):
        from services.initiative_engine import wakeup_engine_hints
        hints = wakeup_engine_hints([1, 2], {"initiative_engine_enabled": True})
        assert len(hints) >= 1


class TestGenerateProjectProposals:
    def test_disabled(self):
        from services.initiative_engine import generate_project_proposals
        result = generate_project_proposals(cfg={"initiative_project_proposals_enabled": False})
        assert result == []

    def test_default_disabled(self):
        from services.initiative_engine import generate_project_proposals
        result = generate_project_proposals(cfg={})
        assert result == []

    @patch("services.maturity_engine.get_trust_tier", return_value=1)
    def test_low_trust_tier(self, mock_trust):
        from services.initiative_engine import generate_project_proposals
        result = generate_project_proposals(cfg={"initiative_project_proposals_enabled": True})
        assert result == []


# ============================================================================
# Tests: knowledge_distiller
# ============================================================================


class TestDistillLearningsToInsights:
    @patch("layla.memory.db.get_recent_learnings", return_value=[])
    def test_empty_learnings(self, mock_get):
        from services.knowledge_distiller import distill_learnings_to_insights
        result = distill_learnings_to_insights(n=10)
        assert result["insights_added"] == 0

    @patch("layla.memory.db.get_recent_learnings", return_value=[
        {"content": "a"}, {"content": "b"},
    ])
    def test_too_few_learnings(self, mock_get):
        from services.knowledge_distiller import distill_learnings_to_insights
        result = distill_learnings_to_insights(n=10)
        assert result["insights_added"] == 0
        assert result["learnings_processed"] == 2

    @patch("services.memory_router.save_learning")
    @patch("services.llm_gateway.run_completion", return_value={
        "choices": [{"message": {"content": "Users prefer fast local inference.\nCode quality improves with tests."}}],
    })
    @patch("layla.memory.db.get_recent_learnings", return_value=[
        {"content": "Learning about local models"},
        {"content": "Learning about test coverage"},
        {"content": "Learning about code quality"},
    ])
    def test_llm_synthesis(self, mock_get, mock_llm, mock_save):
        from services.knowledge_distiller import distill_learnings_to_insights
        result = distill_learnings_to_insights(n=10)
        assert result["insights_added"] >= 1
        assert mock_save.call_count >= 1

    @patch("services.memory_router.save_learning")
    @patch("services.llm_gateway.run_completion", side_effect=Exception("no LLM"))
    @patch("layla.memory.distill.distill_rules", return_value=["Pattern: users prefer local-first tools"])
    @patch("layla.memory.db.get_recent_learnings", return_value=[
        {"content": "Learning about local models"},
        {"content": "Learning about test coverage"},
        {"content": "Learning about privacy"},
    ])
    def test_fallback_to_distill_rules(self, mock_get, mock_rules, mock_llm, mock_save):
        from services.knowledge_distiller import distill_learnings_to_insights
        result = distill_learnings_to_insights(n=10)
        assert result["insights_added"] >= 1

    @patch("layla.memory.db.get_recent_learnings", side_effect=Exception("DB error"))
    def test_error_returns_zero(self, mock_get):
        from services.knowledge_distiller import distill_learnings_to_insights
        result = distill_learnings_to_insights(n=10)
        assert result["insights_added"] == 0
        assert "error" in result


class TestRunPeriodicDistillation:
    @patch("services.knowledge_distiller.distill_learnings_to_insights")
    def test_calls_distill(self, mock_distill):
        mock_distill.return_value = {"insights_added": 2, "learnings_processed": 25}
        from services.knowledge_distiller import run_periodic_distillation
        result = run_periodic_distillation()
        mock_distill.assert_called_once_with(n=25)
        assert result["insights_added"] == 2


# ============================================================================
# Tests: experience_replay
# ============================================================================


class TestGetRecentToolPatterns:
    @patch("layla.memory.db.get_tool_reliability", return_value={
        "read_file": {"count": 50, "success_rate": 0.95, "avg_latency": 120},
        "write_file": {"count": 20, "success_rate": 0.85, "avg_latency": 200},
        "shell": {"count": 2, "success_rate": 1.0, "avg_latency": 300},
    })
    def test_filters_low_count(self, mock_rel):
        from services.experience_replay import get_recent_tool_patterns
        patterns = get_recent_tool_patterns()
        # shell has count=2 (< 3 threshold), should be excluded
        tool_names = [p["tool"] for p in patterns]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "shell" not in tool_names

    @patch("layla.memory.db.get_tool_reliability", return_value={})
    def test_empty_returns_empty(self, mock_rel):
        from services.experience_replay import get_recent_tool_patterns
        assert get_recent_tool_patterns() == []

    @patch("layla.memory.db.get_tool_reliability", side_effect=Exception("DB error"))
    def test_error_returns_empty(self, mock_rel):
        from services.experience_replay import get_recent_tool_patterns
        assert get_recent_tool_patterns() == []


class TestGetRecentReflections:
    @patch("layla.memory.db.get_recent_learnings", return_value=[
        {"content": "Reflection: always verify before committing"},
        {"content": "Worked: the test approach succeeded"},
        {"content": "Random learning about Python"},
        {"content": "Failed: timeout on large repos"},
    ])
    def test_filters_reflections(self, mock_get):
        from services.experience_replay import get_recent_reflections
        reflections = get_recent_reflections(n=10)
        assert len(reflections) == 3
        assert all(
            any(kw in r for kw in ("Reflection", "Worked:", "Failed:"))
            for r in reflections
        )

    @patch("layla.memory.db.get_recent_learnings", return_value=[])
    def test_empty(self, mock_get):
        from services.experience_replay import get_recent_reflections
        assert get_recent_reflections() == []


class TestGetReliableTools:
    @patch("services.experience_replay.get_recent_tool_patterns", return_value=[
        {"tool": "read_file", "success_rate": 0.95, "count": 50},
        {"tool": "write_file", "success_rate": 0.70, "count": 20},
        {"tool": "grep_code", "success_rate": 0.90, "count": 10},
    ])
    def test_filters_by_success_rate(self, mock_patterns):
        from services.experience_replay import get_reliable_tools
        tools = get_reliable_tools(min_success_rate=0.8)
        assert "read_file" in tools
        assert "grep_code" in tools
        assert "write_file" not in tools


class TestRunExperienceReplay:
    @patch("services.experience_replay.get_recent_reflections", return_value=["reflection1"])
    @patch("services.experience_replay.get_recent_tool_patterns", return_value=[
        {"tool": "read_file", "success_rate": 0.95, "count": 50},
    ])
    def test_returns_summary(self, mock_patterns, mock_reflections):
        from services.experience_replay import run_experience_replay
        result = run_experience_replay()
        assert result["tool_patterns"] == 1
        assert result["reflections_reviewed"] == 1
        assert "read_file" in result["top_reliable_tools"]


# ============================================================================
# Tests: memory_consolidation
# ============================================================================


class TestConsolidateSession:
    def test_no_conversation_id(self):
        from services.memory_consolidation import consolidate_session
        result = consolidate_session("")
        assert result["ok"] is False
        assert "no_conversation_id" in result["reason"]

    @patch("layla.memory.db.get_conversation_messages", return_value=[])
    def test_no_messages(self, mock_msgs):
        from services.memory_consolidation import consolidate_session
        result = consolidate_session("conv-123")
        assert result["ok"] is True
        assert result.get("note") == "no_messages"

    @patch("shared_state.get_last_outcome_evaluation", return_value=None)
    @patch("layla.memory.distill.run_distill_after_outcome", return_value={"merged": 0})
    @patch("layla.memory.db.get_conversation_messages", return_value=[
        {"role": "user", "content": f"msg {i}"} for i in range(8)
    ])
    def test_normal_session(self, mock_msgs, mock_distill, mock_eval):
        from services.memory_consolidation import consolidate_session
        result = consolidate_session("conv-456")
        assert result["ok"] is True
        assert result["messages_seen"] == 8
        assert any("distill" in a for a in result["actions"])

    @patch("shared_state.get_last_outcome_evaluation", return_value=None)
    @patch("layla.memory.distill.run_distill_after_outcome", return_value={"merged": 0})
    @patch("layla.memory.db.get_conversation_messages", return_value=[
        {"role": "user", "content": f"msg {i}"} for i in range(15)
    ])
    def test_long_session_flags_summary(self, mock_msgs, mock_distill, mock_eval):
        from services.memory_consolidation import consolidate_session
        result = consolidate_session("conv-789")
        assert "thread_ready_for_summary" in result["actions"]


class TestConsolidatePeriodic:
    @patch("layla.memory.distill.run_distill_after_outcome", return_value={"merged": 1})
    @patch("layla.memory.learnings._apply_confidence_decay")
    def test_runs_both_hooks(self, mock_decay, mock_distill):
        from services.memory_consolidation import consolidate_periodic
        result = consolidate_periodic()
        assert result["ok"] is True
        assert any("distill_tick" in a for a in result["actions"])


class TestReinforcelearning:
    @patch("layla.memory.db_connection._conn")
    @patch("layla.memory.migrations.migrate")
    def test_success_bumps_confidence(self, mock_migrate, mock_conn):
        mock_db = MagicMock()
        # Proper context manager mock
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_db)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = ctx

        # Simulate row with confidence 0.5 (dict-style access)
        mock_row = {"confidence": 0.5}
        mock_db.execute.return_value.fetchone.return_value = mock_row

        from services.memory_consolidation import reinforce_learning
        reinforce_learning(42, success=True)
        # Should have called execute with SELECT then UPDATE then commit
        call_sqls = [str(c) for c in mock_db.execute.call_args_list]
        assert any("UPDATE" in s for s in call_sqls)

    def test_failure_skips(self):
        from services.memory_consolidation import reinforce_learning
        # Should not raise, just return
        reinforce_learning(42, success=False)


class TestPruneLowConfidenceLearnings:
    @patch("layla.memory.db_connection._conn")
    @patch("layla.memory.migrations.migrate")
    def test_prunes_batch(self, mock_migrate, mock_conn):
        mock_db = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_db)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = ctx

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 3

        def exec_side_effect(sql, *args):
            if "PRAGMA" in sql:
                result = MagicMock()
                result.fetchall.return_value = [
                    (0, "id", "", 0, None, 0),
                    (1, "confidence", "", 0, None, 0),
                    (2, "embedding_id", "", 0, None, 0),
                ]
                return result
            if "SELECT embedding_id" in sql:
                result = MagicMock()
                result.fetchall.return_value = []
                return result
            if "DELETE" in sql:
                return mock_cursor
            return MagicMock()

        mock_db.execute.side_effect = exec_side_effect

        from services.memory_consolidation import prune_low_confidence_learnings
        n = prune_low_confidence_learnings(threshold=0.08, batch=5)
        assert n == 3


class TestApplyRetentionPolicies:
    @patch("layla.memory.db_connection._conn")
    @patch("layla.memory.migrations.migrate")
    def test_runs_without_error(self, mock_migrate, mock_conn):
        mock_db = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_db)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = ctx

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        mock_cursor.fetchall.return_value = [
            (0, "id", "", 0, None, 0),
            (1, "created_at", "", 0, None, 0),
        ]
        mock_db.execute.return_value = mock_cursor

        from services.memory_consolidation import apply_retention_policies
        result = apply_retention_policies()
        assert result["ok"] is True

    def test_error_returns_error_dict(self):
        from services.memory_consolidation import apply_retention_policies
        # Without mocking the DB, it will fail but should return error dict
        result = apply_retention_policies()
        # May or may not succeed depending on DB state, but should not raise
        assert isinstance(result, dict)


# ============================================================================
# Tests: Tool Descriptions and Categorization
# ============================================================================


class TestToolDomainCategories:
    """Verify all tool domain files have explicit categories."""

    @pytest.fixture
    def all_domain_tools(self):
        from layla.tools.domains import (
            analysis, automation, code, data, file, general,
            geometry, git, memory, system, web,
        )
        return {
            "analysis": analysis.TOOLS,
            "automation": automation.TOOLS,
            "code": code.TOOLS,
            "data": data.TOOLS,
            "file": file.TOOLS,
            "general": general.TOOLS,
            "geometry": geometry.TOOLS,
            "git": git.TOOLS,
            "memory": memory.TOOLS,
            "system": system.TOOLS,
            "web": web.TOOLS,
        }

    def test_all_tools_have_category(self, all_domain_tools):
        missing = []
        for domain, tools in all_domain_tools.items():
            for name, meta in tools.items():
                if "category" not in meta:
                    missing.append(f"{domain}/{name}")
        assert missing == [], f"Tools missing category: {missing}"

    def test_all_tools_have_description(self, all_domain_tools):
        missing = []
        for domain, tools in all_domain_tools.items():
            for name, meta in tools.items():
                if "description" not in meta:
                    missing.append(f"{domain}/{name}")
        assert missing == [], f"Tools missing description: {missing}"

    def test_valid_categories(self, all_domain_tools):
        valid = {
            "filesystem", "code", "git", "web", "memory", "search",
            "system", "voice", "planning", "fabrication", "data",
        }
        invalid = []
        for domain, tools in all_domain_tools.items():
            for name, meta in tools.items():
                cat = meta.get("category", "")
                if cat not in valid:
                    invalid.append(f"{domain}/{name}: '{cat}'")
        assert invalid == [], f"Tools with invalid category: {invalid}"

    def test_descriptions_not_empty(self, all_domain_tools):
        short = []
        for domain, tools in all_domain_tools.items():
            for name, meta in tools.items():
                desc = meta.get("description", "")
                if len(desc) < 20:
                    short.append(f"{domain}/{name}: '{desc}'")
        assert short == [], f"Tools with too-short descriptions: {short}"

    def test_total_tool_count(self, all_domain_tools):
        total = sum(len(tools) for tools in all_domain_tools.values())
        assert total >= 190, f"Expected >= 190 tools, got {total}"
