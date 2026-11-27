"""A newer "<subject> is <value>" fact replaces older values of the same subject.

Live: four contradictory "favorite color code" values accumulated (learned, merged by distillation, kept in
the graph) and the model blended them: "teal-c2ad. Earlier, it was teal-7c2c; now it's teal-ae0a".
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _contents():
    from layla.memory.db import get_recent_learnings

    return [r["content"] for r in get_recent_learnings(n=50)]


def test_a_new_value_replaces_the_old_one(isolated_db, monkeypatch, tmp_path):
    from layla.memory import memory_graph as mg
    from services.memory.memory_router import save_learning

    monkeypatch.setattr(mg, "GRAPH_PATH", tmp_path / "kg.graphml")
    old = "The operator's favorite color code is teal-7c2c."
    new = "The operator's favorite color code is teal-ae0a."
    assert save_learning(old, kind="fact") > 0
    mg.add_node(old[:80])
    assert any("teal-7c2c" in c for c in _contents()), "PROBE BROKEN: the old fact was not stored"

    assert save_learning(new, kind="fact") > 0
    cs = _contents()
    assert any("teal-ae0a" in c for c in cs), cs
    assert not any("teal-7c2c" in c for c in cs), cs
    assert not any("teal-7c2c" in (n.get("label") or "") for n in mg.get_recent_nodes(n=50))


def test_unrelated_and_short_subject_facts_coexist(isolated_db):
    from services.memory.memory_router import save_learning

    for c in ("The user is a backend developer at a startup.", "The user is from Berlin and likes cycling.",
              "I like Python for scripting and quick tools.", "I like Rust for systems programming work.",
              "The operator's favorite editor theme is dark."):
        save_learning(c, kind="fact")
    save_learning("The operator's favorite color code is teal-1.", kind="fact")
    cs = " | ".join(_contents())
    for frag in ("backend developer", "from Berlin", "Python for scripting", "Rust for systems", "editor theme is dark"):
        assert frag in cs, (frag, cs)


def test_subject_value_parsing():
    from layla.memory.learnings import fact_subject_value

    assert fact_subject_value("The operator's favorite color code is teal-ae0a.") == \
        ("the operator's favorite color code", "teal-ae0a")
    assert fact_subject_value("The user is a developer.") is None          # 2-word subject
    assert fact_subject_value("I like Python.") is None                     # no is/are
    assert fact_subject_value("The deploy targets are staging and prod. More text.") == \
        ("the deploy targets", "staging and prod")
