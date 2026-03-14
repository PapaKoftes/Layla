"""Tests for task_graph (parallel agent roles)."""

from services.task_graph import (
    AGENT_ROLES,
    GraphExecutor,
    TaskGraph,
    TaskNode,
)


def test_agent_roles_constant():
    assert "planner" in AGENT_ROLES
    assert "researcher" in AGENT_ROLES
    assert "executor" in AGENT_ROLES
    assert "critic" in AGENT_ROLES
    assert "memory_curator" in AGENT_ROLES


def test_task_node_has_role():
    node = TaskNode(id="a", task="test", role="researcher")
    assert node.role == "researcher"


def test_add_node_with_role():
    g = TaskGraph()
    nid = g.add_node("research X", role="researcher")
    assert g.nodes[nid].role == "researcher"


def test_run_parallel_ready_empty():
    g = TaskGraph()
    g.add_node("a", dependencies=[])
    ex = GraphExecutor(g, executor_fn=lambda i, t, tools: {"status": "ok"})
    # a is ready
    results = ex.run_parallel_ready()
    assert len(results) == 1
    assert results[0].get("status") == "ok"


def test_run_parallel_ready_two_independent():
    g = TaskGraph()
    g.add_node("task a", role="researcher")
    g.add_node("task b", role="executor")
    ex = GraphExecutor(g, executor_fn=lambda i, t, tools: {"node": i, "status": "ok"})
    results = ex.run_parallel_ready()
    assert len(results) == 2
    assert all(r.get("status") == "ok" for r in results)
