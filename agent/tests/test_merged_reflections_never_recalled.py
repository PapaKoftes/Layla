"""Merged reflections can't pass as facts.

Before recall excluded reflection_engine rows, memory distillation merged reflections into ordinary rows
(source '', type 'fact'); those leaked into prompts ("Personal context: Learning: Reflection ([Active
workspace: ...]"). A one-time migration re-tags them, and distillation never merges them again.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

REFL = "Reflection (What is the secret token?): Worked: Task completed | Failed: None"


def test_legacy_merged_reflection_is_retagged_and_not_recalled(isolated_db):
    from layla.memory.data_migrations import _retag_legacy_internal_learnings
    from layla.memory.db import _conn, get_recent_learnings
    from layla.memory.learnings import save_learning

    save_learning(REFL + " [merged from 2 similar]", kind="fact")          # legacy: no source
    save_learning("The operator prefers dark mode in every editor and terminal they use.", kind="fact")
    with _conn() as db:
        db.execute("UPDATE learnings SET source = '' WHERE source IS NULL")
        db.commit()
    assert any(r["content"].startswith("Reflection (") for r in get_recent_learnings(n=20)), \
        "PROBE BROKEN: the legacy row was not recalled before the migration"

    assert _retag_legacy_internal_learnings() == 1
    assert _retag_legacy_internal_learnings() == 0  # idempotent
    contents = [r["content"] for r in get_recent_learnings(n=20)]
    assert any("dark mode" in c for c in contents), contents
    assert not any(c.startswith("Reflection (") for c in contents), contents


def test_distillation_never_merges_reflections():
    from layla.memory.distill import memory_distill

    rows = [{"id": 1, "content": REFL, "created_at": "2026-01-01"},
            {"id": 2, "content": REFL.replace("secret token", "secret code"), "created_at": "2026-01-02"}]
    assert memory_distill(rows) == {"merged_groups": 0, "removed": 0, "added": 0}
