"""Item 11: journal entries could not be deleted (no delete at DB/engine/router/UI). Verify the new
delete path works end-to-end at the engine level (which routes to the DB)."""
import sys
from pathlib import Path
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_journal_add_then_delete(isolated_db):
    from services.infrastructure.journal_engine import add_entry, list_entries, delete_entry
    r = add_entry("note", "a disposable test entry")
    assert r.get("ok") and r["entry"].get("id")
    eid = r["entry"]["id"]
    assert any(e.get("id") == eid for e in list_entries()["entries"]), "entry should be listed"
    d = delete_entry(eid)
    assert d.get("ok") and d.get("deleted") == 1, f"delete should remove 1 row: {d}"
    assert not any(e.get("id") == eid for e in list_entries()["entries"]), "entry should be gone"
    # deleting a non-existent id is a clean no-op (0 deleted), not an error
    d2 = delete_entry(999999)
    assert d2.get("ok") and d2.get("deleted") == 0


def test_journal_router_wires_delete():
    src = (AGENT_DIR / "routers" / "journal.py").read_text(encoding="utf-8")
    assert '@router.delete("/journal/{entry_id}")' in src
