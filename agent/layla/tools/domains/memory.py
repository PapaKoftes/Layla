"""Memory, notes, and vector store tools."""

TOOLS = {
    "save_note": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "search_memories": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "memory_search": {"fn_key": "memory_search", "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "memory_get": {"fn_key": "memory_get", "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "vector_search": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "vector_store": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "memory_stats": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "spaced_repetition_review": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "schedule_learning_review": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "memory_elasticsearch_search": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "ingest_chat_export_to_knowledge": {"dangerous": True, "require_approval": True, "risk_level": "medium"},
    "codex_suggest_update": {
        "fn_key": "codex_suggest_update",
        "dangerous": False,
        "require_approval": False,
        "risk_level": "low",
        "concurrency_safe": True,
    },
}
