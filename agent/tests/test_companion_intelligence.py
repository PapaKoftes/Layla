"""Tests for companion intelligence subsystem."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_relationship_memory_add_and_get():
    from layla.memory.db import add_relationship_memory, get_recent_relationship_memories, migrate
    migrate()
    add_relationship_memory("User asked about Python debugging. Resolved with breakpoint().")
    mems = get_recent_relationship_memories(n=3)
    assert len(mems) >= 1
    assert "user_event" in mems[0]
    assert "timestamp" in mems[0]
    assert "Python" in mems[0].get("user_event", "") or "debugging" in mems[0].get("user_event", "")


def test_style_profile_update_and_summary():
    from services.style_profile import get_profile_summary, update_profile_from_interactions
    update_profile_from_interactions([
        {"role": "user", "content": "Thanks! Can you fix this bug? The error says NoneType."},
        {"role": "user", "content": "Please explain how async works in Python."},
    ])
    profile = get_profile_summary()
    assert "response_style" in profile
    assert "topics" in profile


def test_style_profile_collaboration_hints_non_clinical():
    from layla.memory.db import get_style_profile, migrate
    from services.style_profile import get_profile_summary, update_profile_from_interactions

    migrate()
    update_profile_from_interactions([
        {"role": "user", "content": "be blunt — no sugarcoat. Tell me straight what's wrong with this design."},
        {"role": "user", "content": "i'm struggling a bit; please be gentle with the review."},
    ])
    profile = get_profile_summary()
    assert "collaboration" in profile
    row = get_style_profile("collaboration")
    assert row and "non-clinical" in (row.get("profile_snapshot") or "").lower()
    assert "dsm" in (row.get("profile_snapshot") or "").lower()


def test_conversation_summaries_still_work():
    from layla.memory.db import get_recent_conversation_summaries, migrate
    migrate()
    summaries = get_recent_conversation_summaries(n=5)
    assert isinstance(summaries, list)


def test_stt_detect_voice_mode():
    from services.stt import detect_voice_mode
    assert detect_voice_mode(b"") is False
    assert detect_voice_mode(b"x" * 100) is False
    # Short WAV-like bytes: RIFF header + minimal data
    wav = b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    assert detect_voice_mode(wav) is False


def test_tts_get_voice_options():
    from services.tts import get_voice_options
    opts = get_voice_options()
    assert isinstance(opts, list)
    assert len(opts) >= 5
    assert any(v["id"] == "af_heart" for v in opts)


# ── Longitudinal state tests ──────────────────────────────────────────────────
# Each test uses a throwaway DB in tmp_path so it never touches production layla.db.

def _reset_db(monkeypatch, tmp_path):
    """Point db module at a fresh temp file and reset the migration guard."""
    import layla.memory.db as db_mod
    import layla.memory.learnings as learnings_mod
    test_db = tmp_path / f"test_layla_{Path(tmp_path).name}.db"
    monkeypatch.setattr(db_mod, "_DB_PATH", test_db)
    monkeypatch.setattr(db_mod, "_MIGRATED", False)
    # Clear the in-process rate-limiter deque so prior test calls don't trigger
    # the 20-per-60s cap and cause save_learning to return -1.
    learnings_mod._recent_learning_ts.clear()
    db_mod.migrate()
    return test_db


def test_relationship_memory_survives_simulated_restart(monkeypatch, tmp_path):
    """relationship_memory rows must be readable after the migration guard is reset (simulates restart)."""
    import layla.memory.db as db_mod
    _reset_db(monkeypatch, tmp_path)
    db_mod.add_relationship_memory("User shared they work on CNC fabrication projects.")
    # Simulate restart: reset migration guard so the next call re-opens the same file.
    monkeypatch.setattr(db_mod, "_MIGRATED", False)
    db_mod.migrate()
    mems = db_mod.get_recent_relationship_memories(n=10)
    contents = [m.get("user_event", "") for m in mems]
    assert any("CNC" in c for c in contents), f"Expected CNC in memories, got: {contents}"


def test_learnings_from_30_days_ago_still_appear(monkeypatch, tmp_path):
    """Learnings must not be filtered by age; a 31-day-old learning must still surface."""
    import layla.memory.db as db_mod
    _reset_db(monkeypatch, tmp_path)
    # Write a learning, then manually backdate it.
    db_mod.save_learning(
        content="Old fact: prefer ezdxf over dxfgrabber for DXF parsing in Python projects.",
        kind="fact",
        source="test",
    )
    with db_mod._conn() as conn:
        conn.execute("UPDATE learnings SET created_at = datetime('now', '-31 days')")
    rows = db_mod.get_recent_learnings(n=50)
    contents = [r.get("content", "") for r in rows]
    assert any("ezdxf" in c for c in contents), (
        f"31-day-old learning silently filtered. Got: {[c[:60] for c in contents]}"
    )


def test_study_plan_progress_advances_correctly(monkeypatch, tmp_path):
    """update_study_progress must increment the notes list and set last_studied."""
    import layla.memory.db as db_mod
    _reset_db(monkeypatch, tmp_path)
    db_mod.save_study_plan("plan-async-01", "Python async/await", status="active")
    db_mod.update_study_progress("plan-async-01", "Learned event loop basics.")
    db_mod.update_study_progress("plan-async-01", "Covered asyncio.gather and Task.")
    plan = db_mod.get_plan_by_topic("Python async/await")
    assert plan is not None, "Plan not found after save"
    assert plan.get("last_studied") is not None, "last_studied not set after update"
    progress_raw = plan.get("progress") or "[]"
    import json
    notes = json.loads(progress_raw) if isinstance(progress_raw, str) else progress_raw
    assert len(notes) >= 2, f"Expected >=2 progress notes, got: {notes}"


def test_reflection_engine_produces_retrievable_learnings(monkeypatch, tmp_path):
    """run_reflection must persist at least one learning that get_recent_learnings can retrieve."""
    import layla.memory.db as db_mod
    import services.llm_gateway as llm_gateway
    from services.reflection_engine import run_reflection

    _reset_db(monkeypatch, tmp_path)
    # Never call the real LLM in unit tests (would require a model + can hang).

    def _fake_completion(*_args, **_kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            "What worked: write_file and run_python\n"
                            "What failed: nothing\n"
                            "What could improve: add more assertions\n"
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(llm_gateway, "run_completion", _fake_completion)
    state = {
        "status": "finished",
        "objective": "Write hello.py and verify it runs",
        "steps": [
            {"action": "write_file", "result": {"ok": True}},
            {"action": "run_python", "result": {"ok": True, "output": "Hello\n"}},
        ],
    }
    result = run_reflection(state)
    # run_reflection returns None only for non-finished or no-tool states
    assert result is not None, "run_reflection returned None for a finished state with tool steps"
    rows = db_mod.get_recent_learnings(n=20)
    contents = " ".join(r.get("content", "") for r in rows)
    assert "Reflection" in contents or "Worked" in contents or "write_file" in contents, (
        f"Reflection not found in learnings. Contents: {contents[:300]}"
    )


def test_personal_knowledge_graph_invalidation_on_write(monkeypatch, tmp_path):
    """After save_learning, _pkg_built must be False so the next query rebuilds the graph."""
    import layla.memory.db as db_mod
    import services.personal_knowledge_graph as pkg_mod
    _reset_db(monkeypatch, tmp_path)
    # Force an initial build.
    pkg_mod.get_personal_graph_context("test query")
    assert pkg_mod._pkg_built is True, "Graph should be built after first query"
    # A new learning write should invalidate the cache.
    db_mod.save_learning(content="New insight: use heapq for priority queues", kind="fact", source="test")
    assert pkg_mod._pkg_built is False, (
        "save_learning must call invalidate_personal_graph(); _pkg_built is still True"
    )
