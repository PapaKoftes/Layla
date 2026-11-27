"""POST /learn/correct replaces a stored fact.

It had no test, and its UPDATE set an `updated_at` column the learnings table does not have, so every
correction failed with a 500; it also wrote the correction plaintext over possibly-encrypted content and left
the old vector searchable.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_correcting_a_fact_replaces_it(isolated_db):
    from fastapi.testclient import TestClient

    import main
    from layla.memory.db import get_recent_learnings
    from services.memory.memory_router import save_learning

    assert save_learning("The project deadline for the launch is Friday the 4th.", kind="fact") > 0
    with TestClient(main.app) as c:
        r = c.post("/learn/correct", json={"query": "project deadline",
                                           "correction": "The project deadline for the launch is Monday the 7th."})
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True, r.json()
    assert r.json().get("learning_id"), r.json()
    cs = [x["content"] for x in get_recent_learnings(n=20)]
    assert any("Monday the 7th" in c for c in cs), cs
    assert not any("Friday the 4th" in c for c in cs), cs
