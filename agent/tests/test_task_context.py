"""Phase 4.3 — task_context isolation tests."""
import logging
import threading

import pytest

from services.task_context import (
    TaskContextFilter,
    get_aspect,
    get_task_id,
    get_workspace,
    install_filter,
    reset_task_context,
    set_task_context,
)


def test_set_and_get_context():
    tokens = set_task_context(workspace="/proj/foo", aspect="nyx", task_id="t1")
    assert get_workspace() == "/proj/foo"
    assert get_aspect() == "nyx"
    assert get_task_id() == "t1"
    reset_task_context(tokens)
    assert get_workspace() == ""
    assert get_aspect() == ""


def test_reset_restores_previous():
    outer = set_task_context(workspace="/outer", aspect="morrigan")
    inner = set_task_context(workspace="/inner", aspect="eris")
    assert get_workspace() == "/inner"
    reset_task_context(inner)
    assert get_workspace() == "/outer"
    assert get_aspect() == "morrigan"
    reset_task_context(outer)


def test_context_filter_injects_task_ctx():
    tokens = set_task_context(workspace="/w", aspect="echo", task_id="abc")
    f = TaskContextFilter()
    record = logging.LogRecord("layla", logging.DEBUG, "", 0, "msg", (), None)
    f.filter(record)
    assert "workspace=/w" in record.task_ctx
    assert "aspect=echo" in record.task_ctx
    assert "task=abc" in record.task_ctx
    reset_task_context(tokens)


def test_context_filter_empty_when_no_context():
    tokens = set_task_context("", "", "")
    f = TaskContextFilter()
    record = logging.LogRecord("layla", logging.DEBUG, "", 0, "msg", (), None)
    f.filter(record)
    assert record.task_ctx == ""
    reset_task_context(tokens)


def test_install_filter_idempotent():
    log = logging.getLogger("layla.test_ctx")
    install_filter("layla.test_ctx")
    install_filter("layla.test_ctx")
    tcf_count = sum(1 for f in log.filters if isinstance(f, TaskContextFilter))
    assert tcf_count == 1


def test_thread_isolation():
    """Each thread has its own context var values."""
    results: dict[str, str] = {}

    def worker(name: str, ws: str):
        tokens = set_task_context(workspace=ws)
        import time; time.sleep(0.02)
        results[name] = get_workspace()
        reset_task_context(tokens)

    t1 = threading.Thread(target=worker, args=("a", "/ws-a"))
    t2 = threading.Thread(target=worker, args=("b", "/ws-b"))
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert results["a"] == "/ws-a"
    assert results["b"] == "/ws-b"
