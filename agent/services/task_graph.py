"""
Task graph engine. Missions run as dependency graphs.
TaskNode, TaskGraph, GraphExecutor allow parallel execution where dependencies permit.
Agent roles: planner, researcher, executor, critic, memory_curator — run concurrently when ready.
"""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("layla")

AGENT_ROLES = ("planner", "researcher", "executor", "critic", "memory_curator")


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    """A single task in the graph. role: planner, researcher, executor, critic, memory_curator."""

    id: str
    task: str
    tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    role: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "tools": self.tools,
            "dependencies": self.dependencies,
            "role": self.role,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }


class TaskGraph:
    """Dependency graph of tasks. Topological order for execution."""

    def __init__(self) -> None:
        self.nodes: dict[str, TaskNode] = {}
        self._sorted: list[str] | None = None

    def add_node(
        self,
        task: str,
        tools: list[str] | None = None,
        dependencies: list[str] | None = None,
        role: str = "",
        node_id: str | None = None,
    ) -> str:
        nid = node_id or str(uuid.uuid4())[:8]
        self.nodes[nid] = TaskNode(
            id=nid,
            task=task,
            tools=tools or [],
            dependencies=dependencies or [],
            role=role or "",
        )
        self._sorted = None
        return nid

    def add_node_obj(self, node: TaskNode) -> str:
        self.nodes[node.id] = node
        self._sorted = None
        return node.id

    def get_ready(self) -> list[str]:
        """Return node ids whose dependencies are all completed."""
        ready = []
        for nid, node in self.nodes.items():
            if node.status != TaskStatus.PENDING:
                continue
            deps_ok = all(
                self.nodes.get(d).status == TaskStatus.COMPLETED
                for d in node.dependencies
                if d in self.nodes
            )
            if deps_ok:
                ready.append(nid)
        return ready

    def topological_order(self) -> list[str]:
        """Return node ids in topological order (dependencies before dependents)."""
        if self._sorted is not None:
            return self._sorted
        in_degree: dict[str, int] = {
            nid: len([d for d in node.dependencies if d in self.nodes])
            for nid, node in self.nodes.items()
        }
        queue = [nid for nid, d in in_degree.items() if d == 0]
        result: list[str] = []
        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for other_id, node in self.nodes.items():
                if nid in node.dependencies:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)
        self._sorted = result
        return result

    def to_dict(self) -> dict:
        return {"nodes": list(self.nodes.values()), "order": self.topological_order()}


class GraphExecutor:
    """Execute a TaskGraph. Supports sequential or parallel-ready execution."""

    def __init__(self, graph: TaskGraph, executor_fn: Callable[[str, str, list[str]], dict] | None = None) -> None:
        self.graph = graph
        self.executor_fn = executor_fn

    def run_step(self, node_id: str) -> dict | None:
        """Execute a single node. Returns result dict or None on failure."""
        node = self.graph.nodes.get(node_id)
        if not node or node.status != TaskStatus.PENDING:
            return None
        node.status = TaskStatus.RUNNING
        try:
            if self.executor_fn:
                result = self.executor_fn(node_id, node.task, node.tools)
            else:
                result = {"status": "no_executor", "task": node.task}
            node.status = TaskStatus.COMPLETED
            node.result = result
            return result
        except Exception as e:
            logger.exception("task_graph step %s failed", node_id)
            node.status = TaskStatus.FAILED
            node.error = str(e)
            return None

    def run_sequential(self) -> list[dict]:
        """Execute all nodes in topological order. Returns list of results."""
        order = self.graph.topological_order()
        results = []
        for nid in order:
            r = self.run_step(nid)
            if r is not None:
                results.append(r)
            else:
                node = self.graph.nodes.get(nid)
                if node and node.status == TaskStatus.FAILED:
                    results.append({"node_id": nid, "status": "failed", "error": node.error})
        return results

    def run_until_complete(self, max_steps: int = 100) -> list[dict]:
        """Execute all ready nodes repeatedly until none ready or max_steps."""
        results: list[dict] = []
        for _ in range(max_steps):
            ready = self.graph.get_ready()
            if not ready:
                break
            for nid in ready:
                r = self.run_step(nid)
                if r is not None:
                    results.append(r)
        return results

    def run_parallel_ready(self, max_workers: int = 4) -> list[dict]:
        """Execute all currently ready nodes in parallel. Returns merged results."""
        ready = self.graph.get_ready()
        if not ready:
            return []
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(max_workers, len(ready))) as ex:
            futures = {ex.submit(self.run_step, nid): nid for nid in ready}
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                    if r is not None:
                        results.append(r)
                except Exception as e:
                    nid = futures[fut]
                    node = self.graph.nodes.get(nid)
                    if node:
                        node.status = TaskStatus.FAILED
                        node.error = str(e)
                    results.append({"node_id": nid, "status": "failed", "error": str(e)})
        return results

    def run_until_complete_parallel(self, max_steps: int = 100, max_workers: int = 4) -> list[dict]:
        """Execute waves of ready nodes in parallel until complete. Merge outputs per wave."""
        results: list[dict] = []
        for _ in range(max_steps):
            wave = self.run_parallel_ready(max_workers=max_workers)
            if not wave:
                break
            results.extend(wave)
        return results
