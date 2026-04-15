from __future__ import annotations


def test_conversation_tags_set_and_suggest(tmp_path, monkeypatch):
    # Use a temp DB
    monkeypatch.setenv("LAYLA_DB_PATH", str(tmp_path / "layla.db"))

    from layla.memory.db import create_conversation, get_conversation, set_conversation_tags, suggest_conversation_tags

    c = create_conversation("conv1", title="Hello", aspect_id="morrigan")
    assert c["id"] == "conv1"

    assert set_conversation_tags("conv1", "alpha, Beta ,alpha,ui/v3") is True
    row = get_conversation("conv1")
    assert row is not None
    assert row.get("tags") == "alpha,beta,ui/v3"

    tags = suggest_conversation_tags(prefix="a", limit=10)
    assert "alpha" in tags


def test_conversation_list_and_search_tag_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYLA_DB_PATH", str(tmp_path / "layla.db"))

    from layla.memory.db import (
        create_conversation,
        list_conversations_filtered,
        search_conversations_filtered,
        set_conversation_tags,
    )

    create_conversation("a", title="Alpha chat", aspect_id="morrigan")
    create_conversation("b", title="Beta chat", aspect_id="nyx")
    set_conversation_tags("a", "work,alpha")
    set_conversation_tags("b", "work,beta")

    only_alpha = list_conversations_filtered(limit=50, tag="alpha")
    ids = [c["id"] for c in only_alpha]
    assert "a" in ids
    assert "b" not in ids

    s = search_conversations_filtered("chat", limit=50, tag="beta")
    ids2 = [c["id"] for c in s]
    assert "b" in ids2
    assert "a" not in ids2

