"""
Document ingestion via Docling -- lightweight, layout-aware document extraction.

Supports: PDF, DOCX, PPTX, HTML, Markdown, AsciiDoc
Alternative to Unstructured.io (lighter footprint).

Config keys:
  docling_enabled: bool (default False)
  docling_chunk_size: int (default 1000 chars)
  docling_overlap: int (default 200 chars)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_SUPPORTED_FORMATS = [
    ".pdf", ".docx", ".pptx", ".html", ".htm",
    ".md", ".markdown", ".adoc", ".asciidoc",
]

_BASIC_FORMATS = [".txt", ".md", ".markdown", ".html", ".htm", ".csv"]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Check whether the ``docling`` library is importable."""
    try:
        import docling  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Supported formats
# ---------------------------------------------------------------------------

def supported_formats() -> list[str]:
    """Return the list of file extensions supported by this module."""
    return list(_SUPPORTED_FORMATS)


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, *, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split *text* into chunks on paragraph boundaries.

    Each chunk targets *chunk_size* characters.  An *overlap* of characters
    from the end of the previous chunk is prepended to the next one so that
    context is preserved across chunk boundaries.

    Returns a list of non-empty strings.
    """
    if not text or not text.strip():
        return []

    chunk_size = max(chunk_size, 1)
    overlap = max(0, min(overlap, chunk_size - 1))

    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) > chunk_size and current:
            # Flush current chunk
            chunks.append(current)
            # Build overlap prefix from the tail of the flushed chunk
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{para}".strip() if tail else para
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


# ---------------------------------------------------------------------------
# Internal: Docling-based extraction
# ---------------------------------------------------------------------------

def _extract_via_docling(path: Path) -> dict[str, Any]:
    """Use docling's ``DocumentConverter`` to extract structured text.

    Returns ``{"text": str, "metadata": dict}`` on success or raises.
    """
    from docling.document_converter import DocumentConverter  # type: ignore[import-untyped]

    converter = DocumentConverter()
    result = converter.convert(str(path))

    doc = result.document
    full_text: str = doc.export_to_text() if hasattr(doc, "export_to_text") else str(doc)

    metadata: dict[str, Any] = {
        "title": getattr(doc, "title", None) or path.stem,
        "file_type": path.suffix.lower(),
    }

    # PDF-specific: page count
    if hasattr(doc, "pages"):
        try:
            metadata["num_pages"] = len(doc.pages)
        except Exception:
            pass

    return {"text": full_text, "metadata": metadata}


# ---------------------------------------------------------------------------
# Internal: basic fallback extraction (no docling)
# ---------------------------------------------------------------------------

def _ingest_basic(path: Path) -> dict[str, Any]:
    """Fallback reader for plain text, Markdown, HTML, and CSV files.

    Strips HTML tags when the file is ``.html`` / ``.htm``.
    Returns ``{"ok": bool, "chunks": list[str], "metadata": dict, ...}``.
    """
    suffix = path.suffix.lower()
    if suffix not in _BASIC_FORMATS:
        return {
            "ok": False,
            "chunks": [],
            "metadata": {},
            "error": f"Unsupported format for basic fallback: {suffix}",
        }

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {
            "ok": False,
            "chunks": [],
            "metadata": {},
            "error": f"Failed to read file: {exc}",
        }

    if suffix in (".html", ".htm"):
        raw = _HTML_TAG_RE.sub("", raw)

    chunks = chunk_text(raw)
    metadata: dict[str, Any] = {
        "title": path.stem,
        "file_type": suffix,
        "num_chunks": len(chunks),
    }
    return {"ok": True, "chunks": chunks, "metadata": metadata}


# ---------------------------------------------------------------------------
# Public: ingest from file path
# ---------------------------------------------------------------------------

def ingest_file(path: str | Path, *, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ingest a document file and return chunked text.

    Parameters
    ----------
    path:
        Filesystem path to the document.
    cfg:
        Optional configuration dict.  Recognised keys:
        ``docling_enabled`` (bool), ``docling_chunk_size`` (int),
        ``docling_overlap`` (int).

    Returns
    -------
    dict with keys:
        ``ok`` (bool), ``chunks`` (list[str]), ``metadata`` (dict),
        and optionally ``error`` (str).
    """
    cfg = cfg or {}
    enabled = cfg.get("docling_enabled", False)
    try:
        chunk_sz = int(cfg.get("docling_chunk_size", 1000))
    except (ValueError, TypeError):
        chunk_sz = 1000
    try:
        overlap = int(cfg.get("docling_overlap", 200))
    except (ValueError, TypeError):
        overlap = 200

    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return {
            "ok": False,
            "chunks": [],
            "metadata": {},
            "error": f"File not found: {p}",
        }

    suffix = p.suffix.lower()
    if suffix not in _SUPPORTED_FORMATS and suffix not in _BASIC_FORMATS:
        return {
            "ok": False,
            "chunks": [],
            "metadata": {},
            "error": f"Unsupported file type: {suffix}",
        }

    # Attempt docling extraction first (if enabled and available)
    if enabled and is_available() and suffix in _SUPPORTED_FORMATS:
        try:
            extracted = _extract_via_docling(p)
            text = extracted["text"]
            metadata = extracted["metadata"]
            chunks = chunk_text(text, chunk_size=chunk_sz, overlap=overlap)
            metadata["num_chunks"] = len(chunks)
            logger.debug("docling ingested %s -> %d chunks", p.name, len(chunks))
            return {"ok": True, "chunks": chunks, "metadata": metadata}
        except Exception as exc:
            logger.warning("docling extraction failed for %s, falling back: %s", p.name, exc)

    # Fallback to basic text extraction
    if suffix in _BASIC_FORMATS:
        result = _ingest_basic(p)
        # Re-chunk with caller's settings when basic fallback produced text
        if result["ok"] and result["chunks"]:
            full_text = "\n\n".join(result["chunks"])
            result["chunks"] = chunk_text(full_text, chunk_size=chunk_sz, overlap=overlap)
            result["metadata"]["num_chunks"] = len(result["chunks"])
        return result

    return {
        "ok": False,
        "chunks": [],
        "metadata": {},
        "error": (
            f"Cannot ingest {suffix} without docling. "
            "Install docling or set docling_enabled=True in config."
        ),
    }


# ---------------------------------------------------------------------------
# Public: ingest from bytes
# ---------------------------------------------------------------------------

def ingest_bytes(
    data: bytes,
    filename: str,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest a document from raw bytes (e.g. an uploaded file).

    Writes *data* to a temporary file, delegates to :func:`ingest_file`,
    then cleans up.

    Parameters
    ----------
    data:
        Raw file bytes.
    filename:
        Original filename (used for extension detection and metadata).
    cfg:
        Optional configuration dict (same keys as :func:`ingest_file`).

    Returns
    -------
    Same structure as :func:`ingest_file`.
    """
    import tempfile

    if not data:
        return {
            "ok": False,
            "chunks": [],
            "metadata": {},
            "error": "Empty data",
        }

    suffix = Path(filename).suffix or ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False, prefix="docling_"
        ) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
    except Exception as exc:
        return {
            "ok": False,
            "chunks": [],
            "metadata": {},
            "error": f"Failed to write temp file: {exc}",
        }

    try:
        result = ingest_file(tmp_path, cfg=cfg)
        # Override title with original filename
        if result.get("metadata"):
            result["metadata"]["title"] = Path(filename).stem
        return result
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
