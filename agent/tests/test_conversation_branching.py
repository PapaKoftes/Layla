"""Conversation branching / time-travel: fork a chat (optionally at a message), list the
branch tree, and compare two branches."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from layla.memory import conversations as C


@pytest.fixture
def isolated_db(tmp_path):
    db_path = tmp_path / "test_layla.db"
    import layla.memory.db as db_mod
    import layla.memory.migrations as mig
    with patch("layla.memory.db._DB_PATH", db_path), patch("layla.memory.db_connection._DB_PATH", db_path):
        mig._MIGRATED = False
        if hasattr(db_mod, "_MIGRATED"):
            db_mod._MIGRATED = False
        mig.migrate()
        yield db_path
    # Teardown (patches restored): clear the global migration guard so a later test using a
    # different DB-isolation mechanism re-runs migrate() against its own DB.
    mig._MIGRATED = False
    if hasattr(db_mod, "_MIGRATED"):
        db_mod._MIGRATED = False


def _seed(cid: str, turns: list[tuple[str, str]]) -> list[str]:
    C.create_conversation(cid, title="Root")
    ids = []
    for role, content in turns:
        ids.append(C.append_conversation_message(cid, role, content))
    return ids


def test_full_fork_copies_all_and_links_parent(isolated_db):
    _seed("root", [("user", "hi"), ("assistant", "hello"), ("user", "bye")])
    branch = C.fork_conversation("root")
    assert branch and branch["parent_id"] == "root"
    msgs = C.get_conversation_messages(branch["id"])
    assert [m["content"] for m in msgs] == ["hi", "hello", "bye"]
    # Branch messages have NEW ids (independent), not the parent's.
    root_ids = {m["id"] for m in C.get_conversation_messages("root")}
    assert not (root_ids & {m["id"] for m in msgs})


def test_fork_at_message_truncates(isolated_db):
    mids = _seed("root", [("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2")])
    branch = C.fork_conversation("root", at_message_id=mids[1])  # up to "a1" inclusive
    contents = [m["content"] for m in C.get_conversation_messages(branch["id"])]
    assert contents == ["q1", "a1"]
    assert branch["forked_at_message_id"] == mids[1]


def test_fork_unknown_source_or_message_returns_none(isolated_db):
    assert C.fork_conversation("nope") is None
    _seed("root", [("user", "hi")])
    assert C.fork_conversation("root", at_message_id="not-a-real-id") is None


def test_list_branches_shows_children(isolated_db):
    _seed("root", [("user", "hi"), ("assistant", "hello")])
    b1 = C.fork_conversation("root", new_title="branch A")
    b2 = C.fork_conversation("root", new_title="branch B")
    tree = C.list_branches("root")
    assert tree["parent_id"] == ""
    ids = {b["id"] for b in tree["branches"]}
    assert ids == {b1["id"], b2["id"]}
    # The branch itself knows its parent.
    assert C.list_branches(b1["id"])["parent_id"] == "root"


def test_compare_finds_common_prefix_and_divergence(isolated_db):
    _seed("root", [("user", "hi"), ("assistant", "hello"), ("user", "path A?")])
    branch = C.fork_conversation("root", at_message_id=C.get_conversation_messages("root")[1]["id"])  # hi, hello
    C.append_conversation_message(branch["id"], "user", "path B?")
    cmp = C.compare_conversations("root", branch["id"])
    assert cmp["common_prefix_len"] == 2
    assert [m["content"] for m in cmp["a_divergent"]] == ["path A?"]
    assert [m["content"] for m in cmp["b_divergent"]] == ["path B?"]


def test_fork_route(isolated_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import conversations as conv_router
    _seed("root", [("user", "hi"), ("assistant", "hello")])
    app = FastAPI(); app.include_router(conv_router.router)
    tc = TestClient(app, raise_server_exceptions=False)
    r = tc.post("/conversations/root/fork", json={"title": "my branch"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["conversation"]["parent_id"] == "root"
    r2 = tc.post("/conversations/does-not-exist/fork", json={})
    assert r2.status_code == 404
