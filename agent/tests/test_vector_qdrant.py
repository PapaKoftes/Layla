"""Tests for Qdrant vector store adapter."""
from unittest.mock import MagicMock, patch

import pytest


class TestIsAvailable:
    def test_not_available_no_client(self):
        """Without qdrant_client installed, is_available returns False."""
        from layla.memory.vector_qdrant import is_available
        assert is_available(cfg={}) is False

    def test_returns_bool(self):
        from layla.memory.vector_qdrant import is_available
        result = is_available(cfg={})
        assert isinstance(result, bool)


class TestGetClient:
    def test_no_qdrant_returns_none(self):
        """Without qdrant_client installed, get_client returns None."""
        from layla.memory.vector_qdrant import get_client
        client = get_client(cfg={})
        # qdrant_client not installed in test env -> should be None
        assert client is None


class TestEnsureCollection:
    @patch("layla.memory.vector_qdrant.get_client")
    def test_no_client_returns_false(self, mock_gc):
        from layla.memory.vector_qdrant import ensure_collection
        mock_gc.return_value = None
        result = ensure_collection(cfg={})
        assert result is False

    def test_no_qdrant_returns_false(self):
        """Without qdrant_client installed, ensure_collection returns False."""
        from layla.memory.vector_qdrant import ensure_collection
        result = ensure_collection(cfg={"qdrant_collection": "test-coll"})
        assert result is False


class TestAddMemories:
    def test_empty_memories(self):
        from layla.memory.vector_qdrant import add_memories
        result = add_memories(cfg={}, memories=[])
        assert result["ok"] is True
        assert result["count"] == 0

    def test_no_qdrant_installed(self):
        """Without qdrant_client, add_memories with data returns error."""
        from layla.memory.vector_qdrant import add_memories
        memories = [
            {"id": "1", "text": "test memory", "embedding": [0.1] * 384, "metadata": {"tag": "test"}},
        ]
        result = add_memories(cfg={}, memories=memories)
        assert result["ok"] is False
        assert result["count"] == 0


class TestSearchMemories:
    @patch("layla.memory.vector_qdrant.get_client")
    def test_no_client(self, mock_gc):
        from layla.memory.vector_qdrant import search_memories
        mock_gc.return_value = None
        result = search_memories(cfg={}, embedding=[0.1] * 384)
        assert result == []

    @patch("layla.memory.vector_qdrant.get_client")
    @patch("layla.memory.vector_qdrant.ensure_collection", return_value=True)
    def test_search_returns_list(self, mock_ensure, mock_gc):
        from layla.memory.vector_qdrant import search_memories
        mock_client = MagicMock()
        mock_hit = MagicMock()
        mock_hit.id = "1"
        mock_hit.score = 0.95
        mock_hit.payload = {"text": "test memory", "metadata": {"tag": "test"}}
        mock_client.search.return_value = [mock_hit]
        mock_gc.return_value = mock_client
        result = search_memories(cfg={"qdrant_collection": "test"}, embedding=[0.1] * 384)
        assert len(result) == 1
        assert result[0]["id"] == "1"
        assert result[0]["score"] == 0.95


class TestDeleteMemories:
    @patch("layla.memory.vector_qdrant.get_client")
    def test_no_client(self, mock_gc):
        from layla.memory.vector_qdrant import delete_memories
        mock_gc.return_value = None
        result = delete_memories(cfg={}, ids=["1"])
        assert result["ok"] is False

    def test_no_qdrant_installed(self):
        """Without qdrant_client, delete returns error."""
        from layla.memory.vector_qdrant import delete_memories
        result = delete_memories(cfg={}, ids=["1", "2"])
        assert result["ok"] is False


class TestGetStats:
    @patch("layla.memory.vector_qdrant.get_client")
    def test_no_client(self, mock_gc):
        from layla.memory.vector_qdrant import get_stats
        mock_gc.return_value = None
        stats = get_stats(cfg={})
        assert stats["available"] is False

    @patch("layla.memory.vector_qdrant.get_client")
    def test_with_stats(self, mock_gc):
        from layla.memory.vector_qdrant import get_stats
        mock_client = MagicMock()
        mock_info = MagicMock()
        mock_info.vectors_count = 100
        mock_info.points_count = 100
        mock_client.get_collection.return_value = mock_info
        mock_gc.return_value = mock_client
        stats = get_stats(cfg={"qdrant_collection": "test"})
        assert stats["available"] is True
        assert stats["vectors_count"] == 100


class TestConfigKeys:
    def test_qdrant_config_exists(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "vector_backend" in cfg
        assert cfg["vector_backend"] == "chroma"
        assert "qdrant_url" in cfg
        assert "qdrant_collection" in cfg
