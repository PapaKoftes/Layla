"""Memory, notes, and vector store tools."""

TOOLS = {
    "save_note": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "memory",
        "description": "Save a text note to persistent memory. Searchable by content and tags.",
    },
    "search_memories": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "memory",
        "description": "Search stored memories and learnings by keyword or semantic similarity.",
    },
    "memory_search": {
        "fn_key": "memory_search",
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "memory",
        "description": "Advanced memory search with filters for type, confidence, date range, and tags.",
    },
    "memory_get": {
        "fn_key": "memory_get",
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "memory",
        "description": "Retrieve a specific memory or learning by its ID.",
    },
    "vector_search": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "memory",
        "description": "Semantic vector search across embedded learnings. Finds conceptually similar content.",
    },
    "vector_store": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "memory",
        "description": "Store text with its embedding vector for later semantic retrieval.",
    },
    "memory_stats": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "memory",
        "description": "Show memory usage statistics: learning count, types, confidence distribution, storage size.",
    },
    "spaced_repetition_review": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "memory",
        "description": "Review a learning with a quality score (0-5) and schedule the next review via SM-2.",
    },
    "schedule_learning_review": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "memory",
        "description": "Add a learning to the spaced repetition queue for periodic review.",
    },
    "memory_elasticsearch_search": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "memory",
        "description": "Full-text search across memories using Elasticsearch-style query syntax.",
    },
    "ingest_chat_export_to_knowledge": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "memory",
        "description": "Import a chat export file (JSON/text) into the knowledge base as learnings.",
    },
    "codex_suggest_update": {
        "fn_key": "codex_suggest_update",
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "memory",
        "description": "Suggest updates to codex entities based on recent conversation context.",
    },
}
