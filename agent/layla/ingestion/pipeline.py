"""
pipeline.py -- Main ingestion pipeline for Layla.

Routes: raw text / file / URL / directory -> extract -> chunk -> embed -> save.

All memory writes go through services.memory_router.save_learning.
Entity extraction via layla.codex.enricher.extract_entities.
Codex linking via layla.codex.linker.auto_link_learning.
Deduplication via SHA256 content hash.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla.ingestion")


# ── Result type ──────────────────────────────────────────────────────────────

@dataclass
class IngestResult:
    source: str = ""              # file path or URL
    chunks: int = 0               # number of chunks created
    entities: list[str] = field(default_factory=list)  # extracted entity names
    content_hash: str = ""        # SHA256 of raw content (dedup key)
    skipped: bool = False         # True if already ingested (duplicate)


# ── Dedup helpers ────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    """Return hex SHA256 of *text*."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _hash_exists(content_hash: str) -> bool:
    """Check if a learning with this content_hash already exists."""
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate
        migrate()
        with _conn() as db:
            row = db.execute(
                "SELECT 1 FROM learnings WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
            return row is not None
    except Exception as exc:
        logger.debug("_hash_exists check failed (proceeding): %s", exc)
        return False


# ── Core ingest logic ────────────────────────────────────────────────────────

def _ingest_raw(text: str, source: str, topic: str) -> IngestResult:
    """Shared logic: chunk text, extract entities, save each chunk."""
    content_hash = _sha256(text)

    # Dedup: skip if content already ingested
    if _hash_exists(content_hash):
        logger.info("Skipping duplicate content from %s (hash=%s)", source, content_hash[:12])
        return IngestResult(
            source=source,
            chunks=0,
            content_hash=content_hash,
            skipped=True,
        )

    # Chunk
    try:
        from layla.ingestion.chunker import chunk_text
        chunks = chunk_text(text)
    except Exception as exc:
        logger.warning("Chunking failed for %s: %s", source, exc)
        chunks = [text]  # fallback: entire text as single chunk

    # Extract entities (from full text, not per-chunk)
    entity_names: list[str] = []
    try:
        from layla.codex.enricher import extract_entities
        raw_entities = extract_entities(text[:10_000])
        entity_names = [e.get("name", "") for e in raw_entities if e.get("name")]
    except Exception as exc:
        logger.debug("Entity extraction failed for %s: %s", source, exc)

    # Build tags from topic + entities
    tags_parts = []
    if topic:
        tags_parts.append(topic)
    if entity_names:
        tags_parts.extend(entity_names[:5])
    tags_str = ", ".join(tags_parts)[:500]

    # Save each chunk as a learning
    saved_count = 0
    last_learning_id: int | None = None
    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            from services.memory_router import save_learning
            learning_id = save_learning(
                content=chunk,
                kind="fact",
                source=source,
                tags=tags_str,
            )
            if isinstance(learning_id, int) and learning_id > 0:
                saved_count += 1
                last_learning_id = learning_id
        except Exception as exc:
            logger.warning("save_learning failed for chunk from %s: %s", source, exc)

    # Auto-link last chunk to codex (representative linking)
    if last_learning_id is not None:
        try:
            from layla.codex.linker import auto_link_learning
            auto_link_learning(text[:2000], last_learning_id)
        except Exception as exc:
            logger.debug("auto_link_learning failed for %s: %s", source, exc)

    return IngestResult(
        source=source,
        chunks=saved_count,
        entities=entity_names,
        content_hash=content_hash,
        skipped=False,
    )


# ── Public API ───────────────────────────────────────────────────────────────

def ingest_text(
    text: str,
    source: str = "manual",
    *,
    topic: str = "",
) -> IngestResult:
    """Ingest raw text -> chunk -> embed -> save as learnings."""
    if not text or not text.strip():
        return IngestResult(source=source, skipped=True)
    return _ingest_raw(text, source=source, topic=topic)


def ingest_file(path: Path, *, topic: str = "") -> IngestResult:
    """Ingest a file -> extract text -> chunk -> embed -> save."""
    path = Path(path)
    source = str(path)

    if not path.is_file():
        logger.warning("ingest_file: not a file: %s", path)
        return IngestResult(source=source, skipped=True)

    try:
        from layla.ingestion.extractors import extract_text
        text = extract_text(path)
    except Exception as exc:
        logger.warning("Text extraction failed for %s: %s", path, exc)
        return IngestResult(source=source, skipped=True)

    if not text or not text.strip():
        logger.info("No text extracted from %s", path)
        return IngestResult(source=source, skipped=True)

    return _ingest_raw(text, source=source, topic=topic)


def ingest_url(url: str, *, topic: str = "") -> IngestResult:
    """Fetch URL -> extract text -> chunk -> embed -> save."""
    source = url
    text = ""

    # Try TOOLS["fetch_url"] from the tool registry
    try:
        from layla.tools.registry_body import TOOLS
        result = TOOLS["fetch_url"]["fn"](url=url)
        if isinstance(result, dict) and result.get("ok"):
            text = result.get("text", "")
    except Exception as exc:
        logger.debug("TOOLS fetch_url failed for %s: %s", url, exc)

    # Fallback: trafilatura
    if not text:
        try:
            import trafilatura
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(downloaded) or ""
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("trafilatura fetch failed for %s: %s", url, exc)

    # Fallback: urllib
    if not text:
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            # Strip HTML tags
            import re
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text).strip()
        except Exception as exc:
            logger.warning("All URL fetch methods failed for %s: %s", url, exc)
            return IngestResult(source=source, skipped=True)

    if not text or not text.strip():
        return IngestResult(source=source, skipped=True)

    return _ingest_raw(text, source=source, topic=topic)


def ingest_directory(
    dir_path: Path,
    *,
    topic: str = "",
    extensions: list[str] | None = None,
) -> list[IngestResult]:
    """Ingest all files in a directory recursively."""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        logger.warning("ingest_directory: not a directory: %s", dir_path)
        return []

    results: list[IngestResult] = []
    for file_path in sorted(dir_path.rglob("*")):
        if not file_path.is_file():
            continue
        if extensions and file_path.suffix.lower() not in extensions:
            continue
        try:
            result = ingest_file(file_path, topic=topic)
            results.append(result)
        except Exception as exc:
            logger.warning("ingest_directory: failed on %s: %s", file_path, exc)
            results.append(IngestResult(source=str(file_path), skipped=True))

    return results
