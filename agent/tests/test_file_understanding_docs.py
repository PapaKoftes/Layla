"""Activation: analyze_file() now runs the real text extractor for docs (was intent-only)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.file_understanding import analyze_file  # noqa: E402


def test_analyze_html_is_real_extract(tmp_path):
    h = tmp_path / "doc.html"
    h.write_text(
        "<html><body><h1>Spec</h1><p>Hello world this is the document body text.</p></body></html>",
        encoding="utf-8")
    r = analyze_file(str(h))
    assert r.get("word_count", 0) >= 5          # proves real extraction, not intent-only
    assert "document body" in r.get("preview", "").lower()


def test_analyze_docx_is_real_extract(tmp_path):
    docx = pytest.importorskip("docx")
    p = tmp_path / "m.docx"
    d = docx.Document()
    d.add_paragraph("alpha beta gamma delta epsilon zeta")
    d.save(str(p))
    r = analyze_file(str(p))
    assert r.get("word_count", 0) >= 5
    assert "alpha" in r.get("preview", "").lower()
