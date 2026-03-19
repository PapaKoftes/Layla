"""Memory, notes, and vector store tools."""

TOOLS = {
    "save_note": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "search_memories": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "memory_search": {"fn_key": "memory_search", "dangerous": False, "require_approval": False, "risk_level": "low"},
    "memory_get": {"fn_key": "memory_get", "dangerous": False, "require_approval": False, "risk_level": "low"},
    "vector_search": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "vector_store": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "memory_stats": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "spaced_repetition_review": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "schedule_learning_review": {"dangerous": False, "require_approval": False, "risk_level": "low"},
}
