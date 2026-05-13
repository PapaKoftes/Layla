"""Tests for multi-agent delegation module."""
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


class TestIsDecomposable:
    def test_simple_task(self):
        from services.multi_agent import is_decomposable
        assert is_decomposable("What is Python?") is False

    def test_compound_task(self):
        from services.multi_agent import is_decomposable
        # Needs both halves >15 chars for "and" heuristic
        assert is_decomposable("Research Python frameworks and refactor the entire database module") is True

    def test_numbered_tasks(self):
        from services.multi_agent import is_decomposable
        assert is_decomposable("1. Fix the bug 2. Write tests 3. Update docs") is True

    def test_also_keyword(self):
        from services.multi_agent import is_decomposable
        assert is_decomposable("Fix the auth bug, also update the README") is True

    def test_empty_string(self):
        from services.multi_agent import is_decomposable
        assert is_decomposable("") is False

    def test_single_action(self):
        from services.multi_agent import is_decomposable
        assert is_decomposable("Fix the login page CSS") is False


class TestDecomposeTask:
    def test_simple_returns_single(self):
        from services.multi_agent import decompose_task
        subtasks = decompose_task("Fix the bug")
        assert len(subtasks) == 1
        assert subtasks[0]["description"] == "Fix the bug"

    def test_and_splits(self):
        from services.multi_agent import decompose_task
        subtasks = decompose_task("Research Python and refactor the database")
        assert len(subtasks) >= 2

    def test_subtask_has_id(self):
        from services.multi_agent import decompose_task
        subtasks = decompose_task("Do A and do B")
        for st in subtasks:
            assert "id" in st
            assert "description" in st
            assert "priority" in st

    def test_numbered_list(self):
        from services.multi_agent import decompose_task
        # Numbered with newlines or clear separation
        subtasks = decompose_task("1. Fix the bug\n2. Write the tests\n3. Deploy to production")
        assert len(subtasks) >= 2

    def test_empty_task(self):
        from services.multi_agent import decompose_task
        subtasks = decompose_task("")
        assert len(subtasks) <= 1


class TestAggregateResults:
    def test_all_success(self):
        from services.multi_agent import aggregate_results
        results = [
            {"id": "1", "description": "Task A", "result": "Done A", "ok": True, "duration_ms": 100},
            {"id": "2", "description": "Task B", "result": "Done B", "ok": True, "duration_ms": 200},
        ]
        agg = aggregate_results(results)
        assert agg["ok"] is True
        assert "summary" in agg
        assert len(agg["subtask_results"]) == 2
        assert agg["total_duration_ms"] > 0

    def test_partial_failure(self):
        from services.multi_agent import aggregate_results
        results = [
            {"id": "1", "description": "Task A", "result": "Done", "ok": True, "duration_ms": 100},
            {"id": "2", "description": "Task B", "result": "", "ok": False, "duration_ms": 50},
        ]
        agg = aggregate_results(results)
        # Partial success should still be ok=True (partial) or ok=False depending on impl
        assert "summary" in agg
        assert len(agg["subtask_results"]) == 2

    def test_empty_results(self):
        from services.multi_agent import aggregate_results
        agg = aggregate_results([])
        assert isinstance(agg, dict)
        assert "summary" in agg


class TestDispatchSubtasks:
    @pytest.mark.asyncio
    async def test_single_subtask(self):
        from services.multi_agent import dispatch_subtasks
        subtasks = [{"id": "1", "description": "Test task", "priority": 1, "depends_on": []}]
        results = await dispatch_subtasks(subtasks, cfg={})
        assert len(results) == 1
        assert results[0]["id"] == "1"
        assert "ok" in results[0]
        assert "duration_ms" in results[0]

    @pytest.mark.asyncio
    async def test_parallel_subtasks(self):
        from services.multi_agent import dispatch_subtasks
        subtasks = [
            {"id": "1", "description": "Task A", "priority": 1, "depends_on": []},
            {"id": "2", "description": "Task B", "priority": 1, "depends_on": []},
        ]
        results = await dispatch_subtasks(subtasks, cfg={})
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_empty_subtasks(self):
        from services.multi_agent import dispatch_subtasks
        results = await dispatch_subtasks([], cfg={})
        assert results == []


class TestRunMultiAgent:
    @pytest.mark.asyncio
    async def test_simple_task(self):
        from services.multi_agent import run_multi_agent
        result = await run_multi_agent("Fix the bug", cfg={})
        assert isinstance(result, dict)
        assert "ok" in result
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_compound_task(self):
        from services.multi_agent import run_multi_agent
        result = await run_multi_agent("Research Python and write tests", cfg={})
        assert isinstance(result, dict)
        assert "subtask_results" in result
        assert len(result["subtask_results"]) >= 2


class TestDelegationStatus:
    def test_returns_dict(self):
        from services.multi_agent import get_delegation_status
        status = get_delegation_status()
        assert "active_tasks" in status
        assert "completed" in status
        assert "max_parallel" in status
