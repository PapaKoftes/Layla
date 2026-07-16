"""delete_conversation must clear the parent link on any child fork so it doesn't dangle at a now-missing
parent (the only real residual the final audit sweep found — a graceful fork-tree cosmetic nit)."""
import sys, uuid
from pathlib import Path
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_deleting_parent_clears_child_parent_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYLA_DB_PATH", str(tmp_path / "layla.db"))
    from layla.memory.db import create_conversation, delete_conversation, get_conversation
    from layla.memory.db_connection import _conn
    parent = "p-" + uuid.uuid4().hex[:8]
    child = "c-" + uuid.uuid4().hex[:8]
    create_conversation(parent, title="parent")
    create_conversation(child, title="child")
    with _conn() as db:
        db.execute("UPDATE conversations SET parent_id=? WHERE id=?", (parent, child)); db.commit()
    assert (get_conversation(child) or {}).get("parent_id") == parent
    # delete the parent — the child's parent_id must be cleared, and the child must still exist
    assert delete_conversation(parent) is True
    ch = get_conversation(child)
    assert ch is not None, "child conversation must survive parent deletion"
    assert (ch.get("parent_id") or "") == "", "child parent_id must be cleared, not left dangling"
