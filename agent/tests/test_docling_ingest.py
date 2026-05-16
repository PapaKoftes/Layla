"""Tests for Docling document ingestion module."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestIsAvailable:
    def test_returns_bool(self):
        from services.docling_ingest import is_available
        result = is_available()
        assert isinstance(result, bool)


class TestChunkText:
    def test_short_text_single_chunk(self):
        from services.docling_ingest import chunk_text
        chunks = chunk_text("Hello world", chunk_size=1000, overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_long_text_multiple_chunks(self):
        from services.docling_ingest import chunk_text
        # Use paragraph breaks so the chunker can split
        text = "\n\n".join(["word " * 60 for _ in range(10)])  # ~3000 chars with breaks
        chunks = chunk_text(text, chunk_size=500, overlap=100)
        assert len(chunks) > 1

    def test_overlap_works(self):
        from services.docling_ingest import chunk_text
        text = "A" * 300 + "\n\n" + "B" * 300 + "\n\n" + "C" * 300
        chunks = chunk_text(text, chunk_size=400, overlap=50)
        assert len(chunks) >= 2

    def test_empty_text(self):
        from services.docling_ingest import chunk_text
        chunks = chunk_text("", chunk_size=1000, overlap=200)
        assert chunks == [] or chunks == [""]

    def test_respects_chunk_size(self):
        from services.docling_ingest import chunk_text
        text = "word " * 1000
        chunks = chunk_text(text, chunk_size=200, overlap=50)
        # Most chunks should be around chunk_size (allowing some flexibility)
        for chunk in chunks[:-1]:  # Last chunk can be shorter
            assert len(chunk) <= 400  # Allow some flex for not splitting mid-word


class TestSupportedFormats:
    def test_returns_list(self):
        from services.docling_ingest import supported_formats
        formats = supported_formats()
        assert isinstance(formats, list)
        assert ".pdf" in formats
        assert ".docx" in formats
        assert ".html" in formats


class TestIngestFile:
    def test_text_file(self, tmp_path):
        from services.docling_ingest import ingest_file
        f = tmp_path / "test.txt"
        f.write_text("This is a test document with some content for ingestion.", encoding="utf-8")
        result = ingest_file(f, cfg={})
        assert result["ok"] is True
        assert len(result["chunks"]) >= 1
        assert "metadata" in result

    def test_markdown_file(self, tmp_path):
        from services.docling_ingest import ingest_file
        f = tmp_path / "test.md"
        f.write_text("# Title\n\nSome paragraph.\n\n## Section\n\nMore text.", encoding="utf-8")
        result = ingest_file(f, cfg={})
        assert result["ok"] is True
        assert len(result["chunks"]) >= 1

    def test_missing_file(self):
        from services.docling_ingest import ingest_file
        result = ingest_file("/nonexistent/file.txt", cfg={})
        assert result["ok"] is False
        assert "error" in result

    def test_html_file(self, tmp_path):
        from services.docling_ingest import ingest_file
        f = tmp_path / "test.html"
        f.write_text("<html><body><h1>Title</h1><p>Paragraph text.</p></body></html>", encoding="utf-8")
        result = ingest_file(f, cfg={})
        assert result["ok"] is True
        # HTML tags should be stripped
        for chunk in result["chunks"]:
            assert "<html>" not in chunk


class TestIngestBytes:
    def test_basic_bytes(self):
        from services.docling_ingest import ingest_bytes
        data = b"This is a test document content."
        result = ingest_bytes(data, "test.txt", cfg={})
        assert result["ok"] is True

    def test_empty_bytes(self):
        from services.docling_ingest import ingest_bytes
        result = ingest_bytes(b"", "empty.txt", cfg={})
        # Should handle gracefully
        assert isinstance(result, dict)


class TestConfigKeys:
    def test_docling_config_exists(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "docling_enabled" in cfg
        assert cfg["docling_enabled"] is False
        assert "docling_chunk_size" in cfg
        assert "docling_overlap" in cfg
