"""Tests for unified web crawler module."""
from unittest.mock import MagicMock, patch

import pytest


class TestCrawlBasic:
    @patch("services.web_crawler._BACKENDS")
    def test_basic_fallback(self, mock_backends):
        from services.web_crawler import crawl_url
        def mock_fn(url, cfg):
            return {"ok": True, "content": "Hello world", "title": "Test", "url": url, "backend": "basic"}
        mock_backends.__getitem__ = lambda self, k: mock_fn
        mock_backends.get = lambda k, d=None: mock_fn
        # Use auto which falls to basic
        result = crawl_url("http://example.com", cfg={}, backend="basic")
        assert result["ok"] is True

    def test_empty_url(self):
        from services.web_crawler import crawl_url
        result = crawl_url("", cfg={})
        assert result["ok"] is False


class TestCrawlFirecrawl:
    def test_firecrawl_import_guard(self):
        """Firecrawl backend handles ImportError gracefully."""
        from services.web_crawler import _crawl_firecrawl
        # firecrawl SDK not installed in test env, should return ok=False
        result = _crawl_firecrawl("http://example.com", {"firecrawl_api_key": "test"})
        assert result["ok"] is False


class TestCrawlCrawl4ai:
    def test_crawl4ai_import_guard(self):
        """crawl4ai backend handles ImportError gracefully."""
        from services.web_crawler import _crawl_crawl4ai
        result = _crawl_crawl4ai("http://example.com", {})
        assert result["ok"] is False


class TestCrawlUrls:
    @patch("services.web_crawler.crawl_url")
    def test_multiple_urls(self, mock_crawl):
        from services.web_crawler import crawl_urls
        mock_crawl.return_value = {"ok": True, "content": "text", "title": "T", "url": "http://a.com"}
        results = crawl_urls(["http://a.com", "http://b.com"], cfg={})
        assert len(results) == 2

    def test_empty_list(self):
        from services.web_crawler import crawl_urls
        results = crawl_urls([], cfg={})
        assert results == []


class TestCrawlerStatus:
    def test_returns_dict(self):
        from services.web_crawler import get_crawler_status
        status = get_crawler_status(cfg={})
        assert isinstance(status, dict)
        assert "basic" in status
        assert status["basic"] is True  # always available

    def test_firecrawl_without_key(self):
        from services.web_crawler import get_crawler_status
        status = get_crawler_status(cfg={})
        assert "firecrawl" in status

    def test_active_backend_present(self):
        from services.web_crawler import get_crawler_status
        status = get_crawler_status(cfg={})
        assert "active" in status


class TestAutoDetect:
    def test_auto_falls_to_basic(self):
        """With no firecrawl key and crawl4ai disabled, auto resolves to basic."""
        import services.web_crawler as wc
        from services.web_crawler import _resolve_backend
        backend = _resolve_backend(cfg={})
        assert backend == "basic"


class TestContentTruncation:
    def test_long_content_truncated(self):
        """Content longer than 50k chars is truncated by _truncate."""
        from services.web_crawler import _truncate
        long_text = "x" * 100000
        truncated = _truncate(long_text)
        assert len(truncated) <= 50020  # 50k + truncation marker
        assert truncated.endswith("[...truncated]")


class TestConfigKeys:
    def test_crawler_config_exists(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "crawler_backend" in cfg
        assert cfg["crawler_backend"] == "auto"
        assert "firecrawl_api_key" in cfg
        assert "crawl4ai_enabled" in cfg
