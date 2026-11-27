"""Agent bookkeeping (reflection_engine learnings) must never be recalled into prompts as operator memory,
while self_improvement can still mine it. Live, a reply was literally the stored reflection text."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

REFLECTION = "Reflection (List the files): Worked: list_dir succeeded | Failed: None | Improve: N/A | outcome_score=0.85"
FACT = "The operator keeps the zephyr deploy runbook in docs/zephyr.md."


def test_recall_excludes_reflections_but_mining_sees_them(isolated_db):
    from layla.memory import learnings as L
    from services.memory.memory_router import save_learning

    save_learning(content=REFLECTION, kind="strategy", source="reflection_engine")
    save_learning(content=FACT, kind="fact")

    recent = [r["content"] for r in L.get_recent_learnings(n=50)]
    assert FACT in recent, f"PROBE BROKEN: the ordinary learning was not saved/recalled: {recent}"
    assert REFLECTION not in recent

    fts = [r["content"] for r in L.search_learnings_fts("list_dir succeeded zephyr", n=20)]
    assert FACT in fts, f"PROBE BROKEN: FTS did not match the ordinary learning: {fts}"
    assert REFLECTION not in fts

    with L._conn() as db:
        mined = [r[0] for r in db.execute("SELECT content FROM learnings WHERE source='reflection_engine'").fetchall()]
    assert any("outcome_score" in L._dec(c) for c in mined), "self_improvement's mining query must still see it"
