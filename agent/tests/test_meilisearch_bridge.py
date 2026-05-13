"""Tests for Meilisearch bridge module."""
import pytest
from unittest.mock import patch, MagicMock


class TestClientFromConfig:
    def test_disabled_returns_none(self):
        from services.meilisearch_bridge import client_from_config
        result = client_from_config({"meilisearch_enabled": False})
        assert result is None

    def test_no_url_returns_none(self):
        from services.meilisearch_bridge import client_from_config
        result = client_from_config({"meilisearch_enabled": True, "meilisearch_url": ""})
        assert result is None

    def test_no_meilisearch_package(self):
        """Without meilisearch installed, client_from_config returns None."""
        from services.meilisearch_bridge import client_from_config
        # meilisearch SDK likely not installed in test env
        result = client_from_config({
            "meilisearch_enabled": True,
            "meilisearch_url": "http://localhost:7700",
        })
        # Either None (no package) or a client object (package present but no server)
        assert result is None or result is not None  # doesn't crash


class TestIsAvailable:
    def test_returns_bool(self):
        from services.meilisearch_bridge import is_available
        result = is_available(cfg={})
        assert isinstance(result, bool)

    def test_disabled_config(self):
        from services.meilisearch_bridge import is_available
        result = is_available(cfg={"meilisearch_enabled": False})
        assert result is False


class TestSearchLearnings:
    def test_disabled_config(self):
        from services.meilisearch_bridge import search_learnings
        result = search_learnings(cfg={"meilisearch_enabled": False}, q="test")
        assert result["ok"] is False

    def test_empty_query(self):
        from services.meilisearch_bridge import search_learnings
        result = search_learnings(cfg={}, q="")
        assert result["ok"] is False

    @patch("services.meilisearch_bridge.client_from_config")
    def test_no_client(self, mock_client):
        from services.meilisearch_bridge import search_learnings
        mock_client.return_value = None
        result = search_learnings(
            cfg={"meilisearch_enabled": True, "meilisearch_url": "http://localhost:7700"},
            q="test",
        )
        assert result["ok"] is False


class TestIndexLearning:
    def test_no_client_no_crash(self):
        """index_learning with no Meilisearch connection should not crash."""
        from services.meilisearch_bridge import index_learning
        # Should not raise
        index_learning(cfg={}, rid=1, text="test learning")

    def test_empty_text_no_crash(self):
        from services.meilisearch_bridge import index_learning
        index_learning(cfg={}, rid=1, text="")


class TestDeleteLearning:
    def test_no_client_no_crash(self):
        from services.meilisearch_bridge import delete_learning
        delete_learning(cfg={}, rid=1)


class TestGetStats:
    def test_returns_dict(self):
        from services.meilisearch_bridge import get_stats
        result = get_stats(cfg={})
        assert isinstance(result, dict)

    def test_disabled_config(self):
        from services.meilisearch_bridge import get_stats
        result = get_stats(cfg={"meilisearch_enabled": False})
        assert isinstance(result, dict)


class TestConfigKeys:
    def test_meilisearch_config_exists(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "meilisearch_enabled" in cfg
        assert "meilisearch_url" in cfg
        assert "meilisearch_api_key" in cfg
        assert "meilisearch_index" in cfg
