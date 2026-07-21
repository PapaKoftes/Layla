"""The planner learned "avoid read_file" from a self-test sweep, because outcomes had no provenance.

`tool_outcomes` is written by a wrapper installed over EVERY entry in TOOLS (layla/tools/registry.py),
so it fires for any invoker: the agent loop, direct TOOLS[...] calls, approvals, the ingestion
pipeline, skill packs, and capability self-test sweeps. It recorded none of them — all 306 rows on
the operator's box carried context='' — so those populations were indistinguishable.

That is not idle bookkeeping. rl_feedback.compute_tool_preferences turns get_tool_reliability() into
the planner's prefer/avoid hints, so whatever this counts becomes what the agent believes about its
own tools. One minute of that table (2026-07-16T16:29) held 132 rows in which ~150 DISTINCT tools each
ran exactly once — a registry enumeration, not a conversation — and every disk-touching tool in it
failed because sandbox_root pointed at an empty folder. The lesson learned was "avoid read_file,
file_info, list_dir": an artifact of a sweep against an empty directory, not experience.

Corroborating the split: core/executor._trace_tool_call is ungated and wrote only 13 `tool_calls`
rows against those 306 `tool_outcomes`, so roughly 293 executions never went through the agent loop
at all.
"""
from __future__ import annotations

import pytest

from layla.memory import user_profile
from services.observability._legacy_observability import (
    TOOL_SOURCE_AGENT,
    current_tool_source,
    log_tool_result,
    tool_invocation_source,
)


class TestInvocationSourceMarker:
    def test_unmarked_threads_report_no_source(self):
        assert current_tool_source() == "", "attribution must never be assumed"

    def test_marker_sets_and_restores(self):
        with tool_invocation_source(TOOL_SOURCE_AGENT):
            assert current_tool_source() == TOOL_SOURCE_AGENT
        assert current_tool_source() == "", "the marker must not leak past its block"

    def test_marker_restores_on_exception(self):
        with pytest.raises(ValueError):
            with tool_invocation_source(TOOL_SOURCE_AGENT):
                raise ValueError("boom")
        assert current_tool_source() == "", "a failing tool must not poison later attribution"

    def test_run_tool_marks_the_thread(self):
        """The agent-loop entry point is what distinguishes real usage from a registry sweep."""
        from core import executor

        seen = {}

        def _fake_inner(*a, **k):
            seen["source"] = current_tool_source()
            return {"ok": True}

        orig = executor._run_tool_inner
        executor._run_tool_inner = _fake_inner
        try:
            executor.run_tool("list_tools", {}, timeout_s=5)
        finally:
            executor._run_tool_inner = orig

        assert seen.get("source") == TOOL_SOURCE_AGENT, (
            "run_tool must stamp provenance, or agent-loop rows stay indistinguishable from sweeps"
        )


class TestReliabilityExcludesUnattributedRows:
    def test_log_tool_result_stamps_the_active_source(self, monkeypatch):
        rows: list[dict] = []
        monkeypatch.setattr(
            "layla.memory.db.record_tool_outcome",
            lambda tool, ok, context="", latency_ms=0, quality_score=0.5: rows.append(
                {"tool": tool, "ok": ok, "context": context}
            ),
        )
        with tool_invocation_source(TOOL_SOURCE_AGENT):
            log_tool_result("read_file", ok=True, duration_ms=5)
        log_tool_result("read_file", ok=False, duration_ms=5)  # sweep: no marker

        assert rows[0]["context"] == TOOL_SOURCE_AGENT
        assert rows[1]["context"] == "", "an unmarked invoker must NOT be attributed to the agent loop"

    def test_reliability_ignores_unattributed_rows_by_default(self, tmp_path, monkeypatch):
        """The whole point: a sweep must not become a lesson."""
        import sqlite3

        db_file = tmp_path / "probe.db"
        con = sqlite3.connect(db_file)
        con.execute(
            "CREATE TABLE tool_outcomes (id INTEGER PRIMARY KEY, tool_name TEXT, context TEXT, "
            "success INTEGER, latency_ms REAL, quality_score REAL, created_at TEXT)"
        )
        # A sweep against an empty sandbox: read_file failed 13/13, unattributed.
        for _ in range(13):
            con.execute("INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at) "
                        "VALUES ('read_file','',0,5,0.0,'2026-07-16T16:29:00')")
        # Real agent-loop usage: read_file succeeded twice.
        for _ in range(2):
            con.execute("INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at) "
                        "VALUES ('read_file','agent_loop',1,5,1.0,'2026-07-20T10:00:00')")
        con.commit()

        class _Ctx:
            def __enter__(self):
                con.row_factory = sqlite3.Row
                return con

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(user_profile, "_conn", lambda: _Ctx())
        monkeypatch.setattr(user_profile, "migrate", lambda: None)

        attributed = user_profile.get_tool_reliability(attributed_only=True)
        assert attributed["read_file"]["count"] == 2, "sweep rows must not be counted"
        assert attributed["read_file"]["success_rate"] == 1.0, (
            "with the sweep excluded, read_file's real success rate is 100% — the planner was "
            "avoiding it on the strength of 13 failures it never actually experienced"
        )

        raw = user_profile.get_tool_reliability()  # default: diagnostics see everything
        assert raw["read_file"]["count"] == 15, "diagnostics must still be able to see everything"
        assert raw["read_file"]["success_rate"] < 0.2, "and the raw view is what misled the planner"
        con.close()


def test_every_learning_consumer_opts_into_attribution():
    """Attribution is opt-IN, so a new learning call site can silently reintroduce the bug.

    Flipping the default instead would have changed all six call sites at once — including
    tool_health_snapshot, a diagnostic that legitimately wants the raw totals. Opt-in keeps the
    diagnostic honest, but only a test can keep the learners honest, so this is that test.
    """
    import ast
    from pathlib import Path

    LEARNERS = {
        "services/infrastructure/rl_feedback.py",
        "services/infrastructure/experience_replay.py",
        "services/planning/planner.py",
        "services/safety/decision_policy.py",
    }
    agent_dir = Path(__file__).resolve().parent.parent
    offenders = []
    for rel in sorted(LEARNERS):
        path = agent_dir / rel
        assert path.exists(), f"{rel} moved — update this list rather than deleting the check"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if fn != "get_tool_reliability":
                continue
            if not any(k.arg == "attributed_only" for k in node.keywords):
                offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "these learning call sites read tool reliability without attributed_only=True, so a "
        "capability self-test sweep can teach the planner again: " + ", ".join(offenders)
    )
