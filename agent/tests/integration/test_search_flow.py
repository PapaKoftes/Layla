"""Integration tests: search router → backend selection → results."""
import pytest
from unittest.mock import patch, MagicMock


class TestSearchRouterIntegration:
    """Verify the full search pipeline: config → backend detection → search → failover."""

    def test_default_config_uses_sqlite(self):
        """With default config, search should use SQLite FTS (always available)."""
        from services.search_router import search, _detect_backend
        cfg = {}
        backend = _detect_backend(cfg)
        assert backend == "sqlite_fts"

    def test_search_with_empty_config(self):
        """Search should never crash, even with empty config."""
        from services.search_router import search
        result = search("test query", cfg={})
        assert isinstance(result, dict)
        assert "ok" in result
        assert "hits" in result

    @patch("services.search_router._search_meilisearch")
    @patch("services.search_router._search_sqlite_fts")
    def test_full_failover_chain(self, mock_fts, mock_ms):
        """Meilisearch fails → SQLite FTS takes over."""
        from services.search_router import search
        mock_ms.return_value = {"ok": False, "error": "connection refused", "hits": []}
        mock_fts.return_value = {"ok": True, "hits": [{"id": 1, "text": "found"}], "backend": "sqlite_fts"}
        cfg = {"meilisearch_enabled": True}
        result = search("test", cfg=cfg)
        assert result["ok"] is True
        assert result.get("failover") is True

    def test_status_reports_all_backends(self):
        """get_search_status should report on all 3 backends."""
        from services.search_router import get_search_status
        status = get_search_status(cfg={})
        assert "backends" in status
        assert "sqlite_fts" in status["backends"]
        assert "meilisearch" in status["backends"]
        assert "elasticsearch" in status["backends"]
        assert status["backends"]["sqlite_fts"]["available"] is True

    @patch("services.search_router._search_meilisearch")
    def test_index_and_search_roundtrip(self, mock_ms):
        """Index a learning, then search for it (mocked)."""
        from services.search_router import index_learning, search
        mock_ms.return_value = {"ok": True, "hits": [{"id": 42, "text": "Python is great"}]}
        cfg = {"meilisearch_enabled": True}
        # Index (should not raise)
        index_learning(cfg, rid=42, text="Python is great", tags="programming")
        # Search
        result = search("Python", cfg=cfg)
        assert result["ok"] is True


class TestSearchConfigIntegration:
    """Verify search config keys exist and integrate properly."""

    def test_config_has_search_keys(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "search_backend" in cfg
        assert "meilisearch_enabled" in cfg
        assert "meilisearch_url" in cfg

    def test_explicit_backend_override(self):
        from services.search_router import _detect_backend
        cfg = {"search_backend": "sqlite_fts", "meilisearch_enabled": True}
        assert _detect_backend(cfg) == "sqlite_fts"
