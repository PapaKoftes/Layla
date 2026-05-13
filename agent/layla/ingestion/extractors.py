"""
extractors.py -- Text extraction from various file types.

Supports: .txt, .md, .py, .json, .csv, .html, .pdf, .docx.
All optional dependencies are lazy-imported and gracefully skipped.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("layla.ingestion")

# Extensions that can be read as plain text
_PLAIN_EXTENSIONS = frozenset({".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".rst", ".sh", ".bat", ".ps1"})


def extract_text(file_path: Path) -> str:
    """Extract text from a file. Supports .txt, .md, .py, .json, .html, .pdf, .docx."""
    file_path = Path(file_path)
    if not file_path.is_file():
        logger.warning("extract_text: file not found: %s", file_path)
        return ""

    suffix = file_path.suffix.lower()

    # Plain text files
    if suffix in _PLAIN_EXTENSIONS:
        return _read_plain(file_path)

    # HTML
    if suffix in (".html", ".htm"):
        return _read_html(file_path)

    # PDF
    if suffix == ".pdf":
        return _read_pdf(file_path)

    # DOCX
    if suffix == ".docx":
        return _read_docx(file_path)

    # Unknown -- try plain text, return empty on binary
    return _read_plain(file_path)


def _read_plain(file_path: Path) -> str:
    """Read file as UTF-8 text; return empty string on binary/decode errors."""
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("_read_plain failed for %s: %s", file_path, exc)
        return ""


def _read_html(file_path: Path) -> str:
    """Extract text from HTML. Uses trafilatura if available, else regex strip."""
    raw = _read_plain(file_path)
    if not raw:
        return ""

    # Try trafilatura first
    try:
        import trafilatura
        extracted = trafilatura.extract(raw)
        if extracted:
            return extracted
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("trafilatura extraction failed: %s", exc)

    # Regex fallback: strip tags
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _read_pdf(file_path: Path) -> str:
    """Extract text from PDF using pypdf. Returns empty if unavailable."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()
    except ImportError:
        logger.debug("pypdf not installed; skipping PDF extraction for %s", file_path)
        return ""
    except Exception as exc:
        logger.debug("PDF extraction failed for %s: %s", file_path, exc)
        return ""


def _read_docx(file_path: Path) -> str:
    """Extract text from DOCX using python-docx. Returns empty if unavailable."""
    try:
        from docx import Document
        doc = Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs).strip()
    except ImportError:
        logger.debug("python-docx not installed; skipping DOCX extraction for %s", file_path)
        return ""
    except Exception as exc:
        logger.debug("DOCX extraction failed for %s: %s", file_path, exc)
        return ""
