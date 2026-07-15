"""WATERTIGHT contract for the chat-rail UI (conversations.js). This feature has regressed repeatedly
because nothing locked the exact API response SHAPES the UI reads — a backend edit that renamed a field
or changed a response wrapper broke save/load/title silently. These tests fail loudly if any field the
UI depends on disappears.

The UI contract, from agent/ui/components/conversations.js:
  • list  : GET /conversations               → { ok: true, conversations: [ {id, title, updated_at,
             created_at, aspect_id, project_id, tags}, ... ] }        (renders the rail; title falls back
             to 'New chat', so title MUST be a string key that exists)
  • load  : GET /conversations/{id}/messages → { ok: true, messages: [ {role, content, aspect_id}, ... ] }
             (requires d.ok === true AND Array.isArray(d.messages))
  • create: POST /conversations              → { ok: true, conversation: { id, ... } }
             (requires d.ok AND d.conversation, reads d.conversation.id)
  • rename: POST /conversations/{id}/rename  → { ok: true }  and the new title shows in the list
"""
import json
import sys
import uuid
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _body(resp) -> dict:
    """Parse a starlette JSONResponse body to a dict (what the browser's fetch().json() sees)."""
    return json.loads(bytes(resp.body).decode("utf-8"))


def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("LAYLA_DB_PATH", str(tmp_path / "layla.db"))


def test_create_endpoint_contract(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path)
    from routers.conversations import create_conversation_api
    d = _body(create_conversation_api({"aspect_id": "morrigan"}))
    assert d.get("ok") is True, d
    assert isinstance(d.get("conversation"), dict), "UI reads d.conversation"
    assert d["conversation"].get("id"), "UI reads d.conversation.id"


def test_list_endpoint_contract(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path)
    from layla.memory.db import append_conversation_message, create_conversation
    from routers.conversations import list_conversations_api

    cid = "c-" + uuid.uuid4().hex[:8]
    create_conversation(cid, title="Reverse a string", aspect_id="morrigan")
    append_conversation_message(cid, "user", "hi", aspect_id="morrigan")

    d = _body(list_conversations_api())
    assert d.get("ok") is True
    assert isinstance(d.get("conversations"), list), "UI does `Array.isArray(d.conversations)`"
    row = next((c for c in d["conversations"] if c.get("id") == cid), None)
    assert row is not None, "created conversation must appear in the list"
    # Every field the rail render reads MUST exist:
    for field in ("id", "title", "created_at", "updated_at", "aspect_id"):
        assert field in row, f"rail render reads s.{field}; missing → silent UI break"
    assert row["title"] == "Reverse a string"


def test_messages_endpoint_contract(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path)
    from layla.memory.db import append_conversation_message, create_conversation
    from routers.conversations import get_conversation_messages_api

    cid = "c-" + uuid.uuid4().hex[:8]
    create_conversation(cid, aspect_id="morrigan")
    append_conversation_message(cid, "user", "Write a reverse function", aspect_id="morrigan")
    append_conversation_message(cid, "assistant", "def rev(s): return s[::-1]", aspect_id="morrigan")

    d = _body(get_conversation_messages_api(cid))
    assert d.get("ok") is True, "UI requires d.ok === true or it silently returns (blank chat)"
    assert isinstance(d.get("messages"), list), "UI does `Array.isArray(d.messages)`"
    assert len(d["messages"]) == 2
    for m in d["messages"]:
        for field in ("role", "content", "aspect_id"):
            assert field in m, f"load reads m.{field}; missing → wrong/blank bubble"
    assert d["messages"][0]["role"] == "user"
    assert d["messages"][1]["role"] == "assistant"
    assert "rev" in d["messages"][1]["content"]


def test_rename_reflects_in_list(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path)
    from layla.memory.db import create_conversation
    from routers.conversations import list_conversations_api, rename_conversation_api

    cid = "c-" + uuid.uuid4().hex[:8]
    create_conversation(cid, title="old", aspect_id="morrigan")
    d = _body(rename_conversation_api(cid, {"title": "My renamed chat"}))
    assert d.get("ok") is True
    row = next(c for c in _body(list_conversations_api())["conversations"] if c["id"] == cid)
    assert row["title"] == "My renamed chat"


def test_full_roundtrip_save_list_title_load(tmp_path, monkeypatch):
    """The exact flow the user cares about: a chat is saved, appears in the rail WITH a title, and its
    messages load back — all through the real endpoints."""
    _isolated(monkeypatch, tmp_path)
    from layla.memory.db import append_conversation_message
    from routers.conversations import (
        create_conversation_api,
        get_conversation_messages_api,
        list_conversations_api,
    )

    # 1) create (New chat)
    cid = _body(create_conversation_api({"aspect_id": "nyx"}))["conversation"]["id"]
    # 2) a turn is persisted (what routers/agent.py does after a reply)
    append_conversation_message(cid, "user", "How do I read a file in Python?", aspect_id="nyx")
    append_conversation_message(cid, "assistant", "Use open(path).read().", aspect_id="nyx")
    # give it a title (auto-name is what the agent path applies)
    from layla.memory.conversations import _auto_name_conversation
    from layla.memory.db import rename_conversation
    title = _auto_name_conversation("How do I read a file in Python?")
    assert title and title.strip(), "auto-name must produce a non-empty instant title"
    rename_conversation(cid, title)
    # 3) rail shows it with the title
    row = next(c for c in _body(list_conversations_api())["conversations"] if c["id"] == cid)
    assert row["title"].strip(), "conversation must have a non-empty title in the rail"
    # 4) load restores both messages in order
    msgs = _body(get_conversation_messages_api(cid))["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert "file" in msgs[0]["content"].lower()


def test_error_responses_still_carry_ok_false(tmp_path, monkeypatch):
    # The UI branches on d.ok; an error must be {ok:false} (not a bare 500 body) so the UI degrades
    # gracefully instead of throwing.
    _isolated(monkeypatch, tmp_path)
    from routers.conversations import rename_conversation_api
    d = _body(rename_conversation_api("nonexistent-" + uuid.uuid4().hex, {"title": "x"}))
    assert d.get("ok") is False
