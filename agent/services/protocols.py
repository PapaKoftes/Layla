"""Protocol interfaces for backend abstraction (P5-1/P5-2).

These protocols define the structural contracts that memory and search backends
must satisfy.  They are *runtime-checkable*, so you can use ``isinstance(obj,
MemoryBackend)`` to verify duck-type compatibility without requiring explicit
subclassing.

The method signatures are derived from the actual public API of
``services.memory_router`` (MemoryBackend) and
``layla.memory.vector_store`` (SearchBackend) so that existing
implementations already satisfy the protocols structurally.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Shared result type (mirrors memory_router.MemoryResult)
# ---------------------------------------------------------------------------

@dataclass
class MemoryResult:
    """Canonical result from any memory store."""

    id: str
    content: str
    type: str           # entity type, "learning", "conversation", "article", etc.
    score: float        # relevance 0.0-1.0
    source: str         # originating store name
    metadata: dict      # original record data


# ---------------------------------------------------------------------------
# P5-1  MemoryBackend protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class MemoryBackend(Protocol):
    """Interface for memory storage backends.

    Methods mirror the public write/read surface of ``memory_router``:
    * ``save_learning``   -- persist a learning entry
    * ``get_learnings``   -- retrieve recent learnings
    * ``delete_learning`` -- remove a learning by id
    * ``query``           -- route a query to the appropriate store(s)
    * ``upsert_entity``   -- create or merge an entity record
    * ``get_entity``      -- fetch a single entity by id
    """

    def save_learning(self, content: str, kind: str = "general", **kwargs: Any) -> Any:
        """Persist a new learning entry.  Returns an id or status value."""
        ...

    def get_learnings(self, limit: int = 50, kind: str = "") -> list[dict]:
        """Return the most recent learnings, optionally filtered by kind."""
        ...

    def delete_learning(self, learning_id: int) -> bool:
        """Remove a learning by its numeric id.  Returns True on success."""
        ...

    def query(
        self,
        text: str,
        *,
        query_type: str = "auto",
        limit: int = 10,
        min_confidence: float = 0.3,
        max_privacy: str | None = None,
    ) -> list[MemoryResult]:
        """Route a memory query and return ranked results."""
        ...

    def upsert_entity(self, entity: Any) -> bool:
        """Write or merge an entity record.  Returns True if stored."""
        ...

    def get_entity(self, entity_id: str) -> dict | None:
        """Retrieve a single entity by id, or None."""
        ...


# ---------------------------------------------------------------------------
# P5-2  SearchBackend protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class SearchBackend(Protocol):
    """Interface for search / retrieval backends.

    Methods mirror ``layla.memory.vector_store`` public surface:
    * ``search``          -- semantic / hybrid search
    * ``index_document``  -- add or update a document in the index
    * ``delete_document`` -- remove a document by id
    """

    def search(self, query: str, k: int = 5, **kwargs: Any) -> list[dict]:
        """Run a search query and return up to *k* result dicts."""
        ...

    def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> bool:
        """Index (or re-index) a document.  Returns True on success."""
        ...

    def delete_document(self, doc_id: str) -> bool:
        """Remove a document from the index.  Returns True on success."""
        ...
