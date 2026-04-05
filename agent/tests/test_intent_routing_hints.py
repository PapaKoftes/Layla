"""Goal-based arg fill + prompt hints for checkpoint / ingest / ES tools."""

from __future__ import annotations

from services.intent_routing_hints import fill_tool_args_from_goal, tool_routing_prompt_hints


def test_prompt_hints_restore_and_ingest():
    h = tool_routing_prompt_hints("please restore checkpoint for src/foo.py")
    assert "list_file_checkpoints" in h or "restore_file_checkpoint" in h
    h2 = tool_routing_prompt_hints("import chats from export")
    assert "ingest_chat_export" in h2.lower()


def test_fill_restore_uuid():
    uid = "a1b2c3d4-e5f6-4781-a234-567890abcdef"
    args = fill_tool_args_from_goal(
        "restore_file_checkpoint",
        f"use id {uid} please",
        "/tmp",
        {},
    )
    assert args.get("checkpoint_id") == uid


def test_fill_es_query_strips_prefix():
    args = fill_tool_args_from_goal(
        "memory_elasticsearch_search",
        "search past learnings: postgres tuning",
        "/tmp",
        {},
    )
    assert "postgres" in (args.get("query") or "").lower()


def test_fill_ingest_path():
    args = fill_tool_args_from_goal(
        "ingest_chat_export_to_knowledge",
        "ingest backups/chat_export.json please",
        "/tmp",
        {},
    )
    assert "json" in (args.get("export_path") or "")
