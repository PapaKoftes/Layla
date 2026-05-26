"""Tests for services.work_unit — WorkUnit dataclass and TaskQueue."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.work_unit import (
    WorkUnit,
    TaskType,
    TaskStatus,
    TaskPriority,
)


class TestWorkUnit:
    def test_defaults(self):
        wu = WorkUnit()
        assert wu.type == TaskType.INFERENCE
        assert wu.priority == TaskPriority.NORMAL
        assert wu.status == TaskStatus.PENDING
        assert wu.payload == {}
        assert wu.id  # auto-generated

    def test_custom_create(self):
        wu = WorkUnit(
            id="task-001",
            type=TaskType.EMBEDDING,
            priority=TaskPriority.LOW,
            payload={"texts": ["hello"]},
            timeout_seconds=120,
        )
        assert wu.id == "task-001"
        assert wu.type == TaskType.EMBEDDING
        assert wu.priority == 2

    def test_to_dict(self):
        wu = WorkUnit(id="test", type=TaskType.STUDY, status=TaskStatus.RUNNING)
        d = wu.to_dict()
        assert d["type"] == "study"
        assert d["status"] == "running"
        assert d["id"] == "test"

    def test_from_dict(self):
        d = {
            "id": "abc",
            "type": "backup",
            "status": "done",
            "priority": 0,
            "payload": '{"db": "main"}',
            "timeout_seconds": 600,
        }
        wu = WorkUnit.from_dict(d)
        assert wu.id == "abc"
        assert wu.type == TaskType.BACKUP
        assert wu.status == TaskStatus.DONE
        assert wu.priority == 0
        assert wu.payload == {"db": "main"}

    def test_from_dict_already_parsed(self):
        d = {
            "id": "xyz",
            "type": "embedding",
            "status": "pending",
            "payload": {"texts": ["a", "b"]},
        }
        wu = WorkUnit.from_dict(d)
        assert wu.payload == {"texts": ["a", "b"]}

    def test_roundtrip(self):
        original = WorkUnit(
            id="rt-test",
            type=TaskType.INGESTION,
            priority=TaskPriority.CRITICAL,
            payload={"file": "test.pdf"},
            timeout_seconds=200,
            source_node="queen-001",
        )
        d = original.to_dict()
        restored = WorkUnit.from_dict(d)
        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.priority == original.priority
        assert restored.payload == original.payload
        assert restored.source_node == original.source_node

    def test_mark_running(self):
        wu = WorkUnit()
        wu.mark_running("node-1")
        assert wu.status == TaskStatus.RUNNING
        assert wu.assigned_to == "node-1"
        assert wu.started_at is not None

    def test_mark_done(self):
        wu = WorkUnit()
        wu.mark_done({"output": "success"})
        assert wu.status == TaskStatus.DONE
        assert wu.result == {"output": "success"}
        assert wu.completed_at is not None

    def test_mark_failed(self):
        wu = WorkUnit()
        wu.mark_failed("timeout exceeded")
        assert wu.status == TaskStatus.FAILED
        assert wu.error == "timeout exceeded"
        assert wu.completed_at is not None

    def test_mark_cancelled(self):
        wu = WorkUnit()
        wu.mark_cancelled()
        assert wu.status == TaskStatus.CANCELLED
        assert wu.completed_at is not None


class TestTaskType:
    def test_all_types(self):
        expected = {"inference", "embedding", "ingestion", "study", "backup", "consolidation", "wiki_build"}
        actual = {t.value for t in TaskType}
        assert actual == expected

    def test_from_string(self):
        assert TaskType("embedding") == TaskType.EMBEDDING
        assert TaskType("wiki_build") == TaskType.WIKI_BUILD


class TestTaskStatus:
    def test_all_statuses(self):
        expected = {"pending", "running", "done", "failed", "cancelled"}
        actual = {s.value for s in TaskStatus}
        assert actual == expected


class TestTaskPriority:
    def test_ordering(self):
        assert TaskPriority.CRITICAL < TaskPriority.NORMAL < TaskPriority.LOW
        assert TaskPriority.CRITICAL == 0
        assert TaskPriority.NORMAL == 1
        assert TaskPriority.LOW == 2
