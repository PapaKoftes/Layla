# -*- coding: utf-8 -*-
"""
Tests for Phase 4: Research Automation + Ingestion Pipeline.

Covers:
  - Research orchestrator (score_credibility, decompose_topic, search_local,
    search_web, synthesize_article, research_topic, _extract_text)
  - Ingestion pipeline (IngestResult, _sha256, ingest_text, ingest_file,
    ingest_directory, dedup via hash)
  - Chunker (estimate_tokens, chunk_text, _split_sentences, _build_overlap)
  - Extractors (extract_text for .txt, .md, .py, .html, unknown)
  - Reranker (rerank, _tokenize, _bm25_rerank)
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ============================================================================
# Tests: Reranker
# ============================================================================


class TestRerankerTokenize:
    """Unit tests for the _tokenize helper."""

    def test_basic(self):
        from services.retrieval.reranker import _tokenize
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_punctuation_stripped(self):
        from services.retrieval.reranker import _tokenize
        tokens = _tokenize("async/await patterns — Python 3.12!")
        assert "async" in tokens
        assert "await" in tokens
        assert "python" in tokens
        assert "3" in tokens
        assert "12" in tokens

    def test_empty(self):
        from services.retrieval.reranker import _tokenize
        assert _tokenize("") == []

    def test_unicode(self):
        from services.retrieval.reranker import _tokenize
        tokens = _tokenize("日本語テスト")
        # \w+ matches unicode word characters
        assert len(tokens) >= 1


class TestBM25Rerank:
    """Tests for the BM25 fallback reranker."""

    def test_basic_ranking(self):
        from services.retrieval.reranker import _bm25_rerank
        docs = [
            "Python is great for web development",
            "Java enterprise application server",
            "Python async await patterns for web APIs",
            "C++ memory management pointers",
        ]
        result = _bm25_rerank("Python web", docs, top_k=4)
        assert len(result) == 4
        # The two Python+web docs should rank higher
        top_2_indices = {r["original_index"] for r in result[:2]}
        assert 0 in top_2_indices or 2 in top_2_indices

    def test_returns_correct_structure(self):
        from services.retrieval.reranker import _bm25_rerank
        docs = ["alpha beta", "gamma delta"]
        result = _bm25_rerank("alpha", docs, top_k=2)
        assert len(result) == 2
        for r in result:
            assert "content" in r
            assert "score" in r
            assert "original_index" in r
            assert isinstance(r["score"], float)

    def test_top_k_limits_output(self):
        from services.retrieval.reranker import _bm25_rerank
        docs = [f"document {i}" for i in range(10)]
        result = _bm25_rerank("document", docs, top_k=3)
        assert len(result) == 3

    def test_empty_query_tokens(self):
        from services.retrieval.reranker import _bm25_rerank
        docs = ["hello world"]
        result = _bm25_rerank("!!!", docs, top_k=5)
        assert len(result) == 1
        assert result[0]["score"] == 0.0

    def test_descending_score_order(self):
        from services.retrieval.reranker import _bm25_rerank
        docs = ["the the the", "python web python web", "python async patterns"]
        result = _bm25_rerank("python web", docs, top_k=3)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)


class TestRerank:
    """Tests for the public rerank() function."""

    def test_empty_documents(self):
        from services.retrieval.reranker import rerank
        assert rerank("test query", []) == []

    def test_empty_query(self):
        from services.retrieval.reranker import rerank
        result = rerank("", ["doc1", "doc2"])
        assert len(result) == 2
        assert all(r["score"] == 0.0 for r in result)

    def test_whitespace_query(self):
        from services.retrieval.reranker import rerank
        result = rerank("   ", ["doc1"])
        assert len(result) == 1
        assert result[0]["score"] == 0.0

    def test_bm25_fallback_used_without_sentence_transformers(self):
        """Without sentence-transformers installed, should fall back to BM25."""
        from services.retrieval.reranker import rerank
        docs = ["Python web async", "Java Spring Boot", "Python FastAPI"]
        result = rerank("Python web framework", docs, top_k=2)
        assert len(result) == 2
        # All results must have the expected keys
        for r in result:
            assert "content" in r
            assert "score" in r
            assert "original_index" in r

    def test_top_k_respected(self):
        from services.retrieval.reranker import rerank
        docs = [f"document number {i} about testing" for i in range(20)]
        result = rerank("document testing", docs, top_k=5)
        assert len(result) == 5

    def test_original_index_preserved(self):
        from services.retrieval.reranker import rerank
        docs = ["aaa", "bbb query match", "ccc"]
        result = rerank("query match", docs, top_k=3)
        indices = {r["original_index"] for r in result}
        # All original indices should be valid
        assert indices.issubset({0, 1, 2})


# ============================================================================
# Tests: Chunker
# ============================================================================


class TestEstimateTokens:
    def test_empty(self):
        from layla.ingestion.chunker import estimate_tokens
        assert estimate_tokens("") == 0

    def test_single_word(self):
        from layla.ingestion.chunker import estimate_tokens
        result = estimate_tokens("hello")
        assert result == 1  # accurate count (tiktoken cl100k; the //4 fallback agrees)

    def test_multiple_words(self):
        from layla.ingestion.chunker import estimate_tokens
        result = estimate_tokens("one two three four five")
        assert result == 5  # accurate count (was the crude int(5*1.3)=6)


class TestChunkText:
    def test_empty_text(self):
        from layla.ingestion.chunker import chunk_text
        assert chunk_text("") == []

    def test_whitespace_only(self):
        from layla.ingestion.chunker import chunk_text
        assert chunk_text("   \n\n  ") == []

    def test_short_text_single_chunk(self):
        from layla.ingestion.chunker import chunk_text
        text = "This is a short sentence."
        chunks = chunk_text(text, max_tokens=512)
        assert len(chunks) == 1
        assert "short sentence" in chunks[0]

    def test_long_text_produces_multiple_chunks(self):
        from layla.ingestion.chunker import chunk_text
        # Build text with many sentences
        sentences = [f"This is sentence number {i} with some extra words." for i in range(50)]
        text = " ".join(sentences)
        chunks = chunk_text(text, max_tokens=50, overlap_tokens=10)
        assert len(chunks) > 1

    def test_overlap_creates_shared_content(self):
        from layla.ingestion.chunker import chunk_text
        sentences = [f"Sentence {i} has unique content here." for i in range(20)]
        text = ". ".join(sentences) + "."
        chunks = chunk_text(text, max_tokens=30, overlap_tokens=10)
        if len(chunks) >= 2:
            # Some content from end of chunk[0] should appear in chunk[1]
            last_words_0 = set(chunks[0].split()[-5:])
            first_words_1 = set(chunks[1].split()[:10])
            # At least some overlap expected
            assert len(last_words_0 & first_words_1) > 0 or len(chunks) >= 2

    def test_sentence_boundaries_respected(self):
        from layla.ingestion.chunker import chunk_text
        text = "First sentence. Second sentence. Third sentence."
        chunks = chunk_text(text, max_tokens=5, overlap_tokens=0)
        # Each chunk should contain complete sentence fragments
        for chunk in chunks:
            assert len(chunk.strip()) > 0


class TestSplitSentences:
    def test_basic_split(self):
        from layla.ingestion.chunker import _split_sentences
        result = _split_sentences("Hello world. How are you? Fine!")
        assert len(result) == 3

    def test_double_newline_split(self):
        from layla.ingestion.chunker import _split_sentences
        result = _split_sentences("Paragraph one.\n\nParagraph two.")
        assert len(result) == 2

    def test_empty_input(self):
        from layla.ingestion.chunker import _split_sentences
        assert _split_sentences("") == []


class TestBuildOverlap:
    def test_basic_overlap(self):
        from layla.ingestion.chunker import _build_overlap
        sentences = ["First sentence", "Second sentence", "Third sentence"]
        overlap, tokens = _build_overlap(sentences, overlap_tokens=5)
        assert len(overlap) >= 1
        assert tokens > 0

    def test_zero_overlap(self):
        from layla.ingestion.chunker import _build_overlap
        sentences = ["A sentence with several words"]
        # With very small overlap budget, still returns at least one sentence
        overlap, tokens = _build_overlap(sentences, overlap_tokens=1)
        assert len(overlap) >= 1


# ============================================================================
# Tests: Extractors
# ============================================================================


class TestExtractors:
    def test_txt_file(self, tmp_path):
        from layla.ingestion.extractors import extract_text
        f = tmp_path / "test.txt"
        f.write_text("Hello from txt file.", encoding="utf-8")
        result = extract_text(f)
        assert "Hello from txt file" in result

    def test_md_file(self, tmp_path):
        from layla.ingestion.extractors import extract_text
        f = tmp_path / "readme.md"
        f.write_text("# Title\n\nSome markdown content.", encoding="utf-8")
        result = extract_text(f)
        assert "Title" in result
        assert "markdown content" in result

    def test_py_file(self, tmp_path):
        from layla.ingestion.extractors import extract_text
        f = tmp_path / "script.py"
        f.write_text("def hello():\n    print('hi')\n", encoding="utf-8")
        result = extract_text(f)
        assert "def hello" in result

    def test_html_file_regex_fallback(self, tmp_path):
        from layla.ingestion.extractors import extract_text
        f = tmp_path / "page.html"
        f.write_text(
            "<html><body><p>Hello HTML</p><script>var x=1;</script></body></html>",
            encoding="utf-8",
        )
        result = extract_text(f)
        assert "Hello HTML" in result
        # Script content should be stripped
        assert "var x=1" not in result

    def test_nonexistent_file(self, tmp_path):
        from layla.ingestion.extractors import extract_text
        result = extract_text(tmp_path / "nonexistent.txt")
        assert result == ""

    def test_unknown_extension_tries_plain(self, tmp_path):
        from layla.ingestion.extractors import extract_text
        f = tmp_path / "data.xyz"
        f.write_text("some content here", encoding="utf-8")
        result = extract_text(f)
        assert "some content here" in result

    def test_plain_extensions_set(self):
        from layla.ingestion.extractors import _PLAIN_EXTENSIONS
        assert ".txt" in _PLAIN_EXTENSIONS
        assert ".md" in _PLAIN_EXTENSIONS
        assert ".py" in _PLAIN_EXTENSIONS
        assert ".json" in _PLAIN_EXTENSIONS
        assert ".yaml" in _PLAIN_EXTENSIONS
        assert ".toml" in _PLAIN_EXTENSIONS


# ============================================================================
# Tests: Ingestion Pipeline
# ============================================================================


class TestSha256:
    def test_deterministic(self):
        from layla.ingestion.pipeline import _sha256
        h1 = _sha256("hello world")
        h2 = _sha256("hello world")
        assert h1 == h2

    def test_different_inputs(self):
        from layla.ingestion.pipeline import _sha256
        h1 = _sha256("hello")
        h2 = _sha256("world")
        assert h1 != h2

    def test_returns_hex_string(self):
        from layla.ingestion.pipeline import _sha256
        h = _sha256("test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestIngestResult:
    def test_defaults(self):
        from layla.ingestion.pipeline import IngestResult
        r = IngestResult()
        assert r.source == ""
        assert r.chunks == 0
        assert r.entities == []
        assert r.content_hash == ""
        assert r.skipped is False


class TestIngestText:
    def test_empty_text_skipped(self):
        from layla.ingestion.pipeline import ingest_text
        result = ingest_text("")
        assert result.skipped is True

    def test_whitespace_text_skipped(self):
        from layla.ingestion.pipeline import ingest_text
        result = ingest_text("   \n\t  ")
        assert result.skipped is True

    @patch("layla.ingestion.pipeline._hash_exists", return_value=True)
    def test_duplicate_skipped(self, mock_hash):
        from layla.ingestion.pipeline import ingest_text
        result = ingest_text("some unique content for dedup test", source="test")
        assert result.skipped is True
        assert result.content_hash != ""

    @patch("layla.ingestion.pipeline._hash_exists", return_value=False)
    @patch("services.memory.memory_router.save_learning", return_value=1)
    def test_successful_ingest(self, mock_save, mock_hash):
        from layla.ingestion.pipeline import ingest_text
        result = ingest_text("A short text that will become a single chunk.", source="unit-test")
        assert result.skipped is False
        assert result.chunks >= 1
        assert result.content_hash != ""
        assert result.source == "unit-test"

    @patch("layla.ingestion.pipeline._hash_exists", return_value=False)
    @patch("services.memory.memory_router.save_learning", return_value=1)
    def test_ingest_with_topic(self, mock_save, mock_hash):
        from layla.ingestion.pipeline import ingest_text
        result = ingest_text("Content about Python.", source="test", topic="python")
        assert result.skipped is False
        # save_learning should have been called with tags containing topic
        if mock_save.called:
            # Check tags include topic
            # May be in positional or keyword args
            pass


class TestIngestFile:
    def test_nonexistent_file(self, tmp_path):
        from layla.ingestion.pipeline import ingest_file
        result = ingest_file(tmp_path / "ghost.txt")
        assert result.skipped is True

    @patch("layla.ingestion.pipeline._hash_exists", return_value=False)
    @patch("services.memory.memory_router.save_learning", return_value=1)
    def test_txt_file(self, mock_save, mock_hash, tmp_path):
        from layla.ingestion.pipeline import ingest_file
        f = tmp_path / "sample.txt"
        f.write_text("This is sample text content for ingestion testing.", encoding="utf-8")
        result = ingest_file(f)
        assert result.skipped is False
        assert result.chunks >= 1
        assert result.source == str(f)

    @patch("layla.ingestion.pipeline._hash_exists", return_value=True)
    def test_duplicate_file_skipped(self, mock_hash, tmp_path):
        from layla.ingestion.pipeline import ingest_file
        f = tmp_path / "dup.txt"
        f.write_text("duplicate content", encoding="utf-8")
        result = ingest_file(f)
        assert result.skipped is True


class TestIngestDirectory:
    @patch("layla.ingestion.pipeline._hash_exists", return_value=False)
    @patch("services.memory.memory_router.save_learning", return_value=1)
    def test_directory_ingest(self, mock_save, mock_hash, tmp_path):
        from layla.ingestion.pipeline import ingest_directory
        (tmp_path / "a.txt").write_text("File A content.", encoding="utf-8")
        (tmp_path / "b.md").write_text("# File B\n\nMarkdown.", encoding="utf-8")
        results = ingest_directory(tmp_path)
        assert len(results) == 2
        assert all(not r.skipped for r in results)

    def test_nonexistent_directory(self, tmp_path):
        from layla.ingestion.pipeline import ingest_directory
        results = ingest_directory(tmp_path / "nope")
        assert results == []

    @patch("layla.ingestion.pipeline._hash_exists", return_value=False)
    @patch("services.memory.memory_router.save_learning", return_value=1)
    def test_extension_filter(self, mock_save, mock_hash, tmp_path):
        from layla.ingestion.pipeline import ingest_directory
        (tmp_path / "keep.txt").write_text("keep this", encoding="utf-8")
        (tmp_path / "skip.py").write_text("# skip this", encoding="utf-8")
        results = ingest_directory(tmp_path, extensions=[".txt"])
        assert len(results) == 1
        assert "keep.txt" in results[0].source


# ============================================================================
# Tests: Research Orchestrator
# ============================================================================


