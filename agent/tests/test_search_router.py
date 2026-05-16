"""Tests for unified search router."""
from unittest.mock import MagicMock, patch

import pytest


class TestDetectBackend:
    def test_auto_default_sqlite(self):
        from services.search_router import _detect_backend
        cfg = {}
        assert _detect_backend(cfg) == "sqlite_fts"

    def test_auto_prefers_meilisearch(self):
        from services.search_router import _detect_backend
        cfg = {"meilisearch_enabled": True}
        assert _detect_backend(cfg) == "meilisearch"

    def test_auto_elasticsearch_when_no_meili(self):
        from services.search_router import _detect_backend
        cfg = {"elasticsearch_enabled": True}
        assert _detect_backend(cfg) == "elasticsearch"

    def test_explicit_backend(self):
        from services.search_router import _detect_backend
        cfg = {"search_backend": "sqlite_fts", "meilisearch_enabled": True}
        assert _detect_backend(cfg) == "sqlite_fts"

    def test_explicit_elasticsearch(self):
        from services.search_router import _detect_backend
        cfg = {"search_backend": "elasticsearch"}
        assert _detect_backend(cfg) == "elasticsearch"


class TestSearchFallback:
    @patch("services.search_router._search_meilisearch")
    def test_meilisearch_success(self, mock_ms):
        from services.search_router import search
        mock_ms.return_value = {"ok": True, "hits": [{"id": 1, "text": "found"}]}
        cfg = {"meilisearch_enabled": True}
        result = search("test", cfg=cfg)
        assert result["ok"] is True
        assert len(result["hits"]) == 1
        assert result["backend"] == "meilisearch"

    @patch("services.search_router._search_sqlite_fts")
    @patch("services.search_router._search_meilisearch")
    def test_failover_to_sqlite(self, mock_ms, mock_fts):
        from services.search_router import search
        mock_ms.return_value = {"ok": False, "error": "connection refused", "hits": []}
        mock_fts.return_value = {"ok": True, "hits": [{"id": 2, "text": "fallback"}]}
        cfg = {"meilisearch_enabled": True}
        result = search("test", cfg=cfg)
        assert result["ok"] is True
        assert result.get("failover") is True

    @patch("services.search_router._search_sqlite_fts")
    def test_sqlite_fts_direct(self, mock_fts):
        from services.search_router import search
        mock_fts.return_value = {"ok": True, "hits": [], "backend": "sqlite_fts"}
        result = search("test", cfg={}, backend_override="sqlite_fts")
        assert result["ok"] is True


class TestSearchStatus:
    def test_returns_all_backends(self):
        from services.search_router import get_search_status
        cfg = {}
        status = get_search_status(cfg)
        assert "active_backend" in status
        assert "backends" in status
        assert "sqlite_fts" in status["backends"]
        assert status["backends"]["sqlite_fts"]["available"] is True

    def test_meilisearch_disabled(self):
        from services.search_router import get_search_status
        cfg = {"meilisearch_enabled": False}
        status = get_search_status(cfg)
        assert status["backends"]["meilisearch"]["enabled"] is False


class TestIndexLearning:
    @patch("services.search_router.logger")
    def test_no_op_when_disabled(self, mock_logger):
        from services.search_router import index_learning
        # Should not raise
        index_learning({}, rid=1, text="test")

    @patch("services.meilisearch_bridge.index_learning")
    def test_fans_out_to_meilisearch(self, mock_ms_index):
        from services.search_router import index_learning
        cfg = {"meilisearch_enabled": True}
        index_learning(cfg, rid=1, text="test text", tags="tag1")
        mock_ms_index.assert_called_once()


class TestMeilisearchBridge:
    def test_disabled_returns_error(self):
        from services.meilisearch_bridge import search_learnings
        result = search_learnings({}, "test")
        assert result["ok"] is False
        assert "disabled" in result["error"]

    def test_index_when_disabled_noop(self):
        from services.meilisearch_bridge import index_learning
        # Should not raise
        index_learning({}, rid=1, text="test")


class TestConfigKeys:
    def test_meilisearch_config_exists(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "meilisearch_enabled" in cfg
        assert cfg["meilisearch_enabled"] is False
        assert "meilisearch_url" in cfg
        assert "meilisearch_index" in cfg
        assert "search_backend" in cfg
        assert cfg["search_backend"] == "auto"
