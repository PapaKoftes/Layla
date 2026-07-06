"""Knowledge Watcher — monitors folders for new/changed files and auto-ingests.

Uses ``watchdog`` to watch configured directories for file changes,
then queues them for ingestion via the existing pipeline.  Only runs
in BREATHE or SPRINT mode (respects the resource governor).

Phase 5A of the distributed infrastructure plan.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional, Set

logger = logging.getLogger("layla")

# ── Supported file types ────────────────────────────────────────────────

SUPPORTED_EXTENSIONS: Set[str] = {
    ".pdf", ".docx", ".txt", ".md",
    ".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h",
    ".json", ".yaml", ".yml",
    ".csv", ".xlsx",
    ".html", ".htm",
    ".ipynb",
}

# Files to always skip
SKIP_PATTERNS = {
    "__pycache__", ".git", ".venv", "node_modules",
    ".pyc", ".pyo", ".so", ".dll", ".exe",
    "desktop.ini", "thumbs.db", ".ds_store",
}


def _should_process(path: Path) -> bool:
    """Check if a file should be processed."""
    if not path.is_file():
        return False
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    # Skip hidden files and known junk
    for part in path.parts:
        if part.lower() in SKIP_PATTERNS:
            return False
        if part.startswith(".") and part != ".":
            return False
    # Skip very large files (>50MB)
    try:
        if path.stat().st_size > 50 * 1024 * 1024:
            return False
    except OSError:
        return False
    return True


# ── File hash tracking ──────────────────────────────────────────────────

def _file_hash(path: Path) -> str:
    """Compute a quick hash of file contents for change detection."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""


class _FileTracker:
    """Tracks processed files to avoid re-ingesting unchanged content."""

    def __init__(self):
        self._hashes: dict[str, str] = {}  # path → hash
        self._lock = threading.Lock()

    def has_changed(self, path: Path) -> bool:
        """Check if a file is new or has been modified."""
        current_hash = _file_hash(path)
        if not current_hash:
            return False
        with self._lock:
            prev = self._hashes.get(str(path))
            if prev == current_hash:
                return False
            self._hashes[str(path)] = current_hash
            return True

    def mark_processed(self, path: Path) -> None:
        """Update the stored hash for a file."""
        h = _file_hash(path)
        if h:
            with self._lock:
                self._hashes[str(path)] = h


# ── KnowledgeWatcher ────────────────────────────────────────────────────

class KnowledgeWatcher:
    """Watches configured directories for new/modified files and ingests them.

    Integrates with:
    - ``services.resource_governor`` — only ingests in BREATHE/SPRINT
    - ``layla.ingestion.pipeline`` — existing document processing
    - ``services.work_unit`` — queues ingestion tasks for distributed processing
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._watch_dirs: list[Path] = []
        self._exclude_dirs: list[Path] = []
        self._observer = None
        self._tracker = _FileTracker()
        self._running = False
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._poll_interval = max(30, self._cfg.get("knowledge_poll_interval", 60))

        # Stats
        self._files_ingested = 0
        self._files_skipped = 0

        self._load_config()

    def _load_config(self) -> None:
        """Load watch/exclude directories from user identity or config."""
        # From config
        watch = self._cfg.get("knowledge_watch_dirs", [])
        exclude = self._cfg.get("knowledge_exclude_dirs", [])

        # From user identity (set during onboarding)
        try:
            from layla.memory.db_connection import _conn
            with _conn() as db:
                row = db.execute(
                    "SELECT snapshot FROM user_identity WHERE key = 'watch_folders'"
                ).fetchone()
                if row:
                    val = row["snapshot"] if isinstance(row, dict) else row[0]
                    if val:
                        import json
                        try:
                            dirs = json.loads(val)
                            if isinstance(dirs, list):
                                watch.extend(dirs)
                        except Exception:
                            if isinstance(val, str) and val.strip():
                                watch.append(val)

                row = db.execute(
                    "SELECT snapshot FROM user_identity WHERE key = 'exclude_folders'"
                ).fetchone()
                if row:
                    val = row["snapshot"] if isinstance(row, dict) else row[0]
                    if val:
                        import json
                        try:
                            dirs = json.loads(val)
                            if isinstance(dirs, list):
                                exclude.extend(dirs)
                        except Exception:
                            pass
        except Exception:
            pass

        self._watch_dirs = [Path(d) for d in watch if d]
        self._exclude_dirs = [Path(d) for d in exclude if d]

    # ── Watcher lifecycle ────────────────────────────────────────────

    def start(self) -> bool:
        """Start watching configured directories.

        Uses watchdog if available, falls back to polling.
        """
        if self._running:
            return True

        if not self._watch_dirs:
            logger.debug("Knowledge watcher: no directories configured")
            return False

        # Try watchdog first
        try:
            from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
            from watchdog.observers import Observer

            class _Handler(FileSystemEventHandler):
                def __init__(self, watcher: KnowledgeWatcher):
                    self._watcher = watcher

                def on_created(self, event):
                    if not event.is_directory:
                        self._watcher._on_file_change(Path(event.src_path), kind="file_created")

                def on_modified(self, event):
                    if not event.is_directory:
                        self._watcher._on_file_change(Path(event.src_path), kind="file_modified")

            observer = Observer()
            handler = _Handler(self)
            for watch_dir in self._watch_dirs:
                if watch_dir.is_dir():
                    observer.schedule(handler, str(watch_dir), recursive=True)
                    logger.info("Knowledge watcher: watching %s", watch_dir)

            observer.start()
            self._observer = observer
            self._running = True
            logger.info("Knowledge watcher started (watchdog mode, %d dirs)", len(self._watch_dirs))
            return True

        except ImportError:
            logger.info("watchdog not installed, using polling mode")

        # Fallback: polling mode
        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="knowledge-poll",
            daemon=True,
        )
        self._poll_thread.start()
        self._running = True
        logger.info("Knowledge watcher started (poll mode, %ds interval, %d dirs)",
                     self._poll_interval, len(self._watch_dirs))
        return True

    def stop(self) -> None:
        """Stop the watcher."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
            self._poll_thread = None
        logger.info("Knowledge watcher stopped (ingested=%d, skipped=%d)",
                     self._files_ingested, self._files_skipped)

    # ── File processing ──────────────────────────────────────────────

    def _on_file_change(self, path: Path, kind: str = "file_modified") -> None:
        """Called when a file is created or modified."""
        if not _should_process(path):
            return

        # Check excludes
        for exc in self._exclude_dirs:
            try:
                path.relative_to(exc)
                return  # File is in excluded directory
            except ValueError:
                pass

        # Check governor
        if not self._should_ingest():
            return

        # Check if actually changed
        if not self._tracker.has_changed(path):
            self._files_skipped += 1
            return

        self._ingest_file(path)

        # BL-233: let user-defined automation rules react to the change (best-effort).
        try:
            from services.automation.rules_engine import dispatch_event
            dispatch_event("file_modified", {"path": str(path)})
        except Exception as e:  # noqa: BLE001
            logger.debug("automation dispatch on file change failed: %s", e)

    def _should_ingest(self) -> bool:
        """Check if the resource governor allows ingestion."""
        try:
            from services.infrastructure.resource_governor import get_mode
            mode = get_mode().value
            return mode in ("breathe", "sprint")
        except Exception:
            return True  # No governor → always ingest

    def _ingest_file(self, path: Path) -> None:
        """Ingest a single file."""
        try:
            # Try ingestion pipeline first
            try:
                from layla.ingestion.pipeline import process_file
                process_file(str(path))
                self._tracker.mark_processed(path)
                self._files_ingested += 1
                logger.info("Knowledge watcher: ingested %s", path.name)
                # Maturity: award XP for file ingestion
                try:
                    from services.personality.maturity_engine import award_xp
                    award_xp(8, reason=f"file_ingested:{path.name}"[:80])
                except Exception:
                    pass
                return
            except ImportError:
                pass

            # Fallback: read and store as a learning
            content = path.read_text(encoding="utf-8", errors="replace")
            if len(content) > 10000:
                content = content[:10000] + "\n\n[... truncated]"

            from layla.memory.db_connection import _conn
            from layla.time_utils import utcnow
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

            with _conn() as db:
                existing = db.execute(
                    "SELECT id FROM learnings WHERE content_hash = ?",
                    (content_hash,),
                ).fetchone()
                if not existing:
                    db.execute(
                        """INSERT INTO learnings
                           (content, type, created_at, source, content_hash, confidence)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            f"[{path.name}]\n{content}",
                            "document",
                            utcnow().isoformat(),
                            f"file:{path.name}",
                            content_hash,
                            0.7,
                        ),
                    )
                    db.commit()
                    self._files_ingested += 1
                    logger.info("Knowledge watcher: stored %s as learning", path.name)
                    # Maturity: award XP for fallback file storage
                    try:
                        from services.personality.maturity_engine import award_xp
                        award_xp(5, reason=f"file_stored:{path.name}"[:80])
                    except Exception:
                        pass
                else:
                    self._files_skipped += 1

            self._tracker.mark_processed(path)

        except Exception as e:
            logger.debug("Knowledge watcher: failed to ingest %s: %s", path.name, e)

    # ── Polling fallback ─────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Periodically scan watch directories for changes."""
        while not self._stop_event.is_set():
            for watch_dir in self._watch_dirs:
                if not watch_dir.is_dir():
                    continue
                try:
                    for path in watch_dir.rglob("*"):
                        if self._stop_event.is_set():
                            return
                        self._on_file_change(path)
                except Exception as e:
                    logger.debug("Poll scan error for %s: %s", watch_dir, e)

            self._stop_event.wait(self._poll_interval)

    # ── Manual scan ──────────────────────────────────────────────────

    def scan_now(self) -> dict[str, int]:
        """Run an immediate scan of all watch directories."""
        before = self._files_ingested
        for watch_dir in self._watch_dirs:
            if not watch_dir.is_dir():
                continue
            for path in watch_dir.rglob("*"):
                self._on_file_change(path)
        return {
            "files_ingested": self._files_ingested - before,
            "total_ingested": self._files_ingested,
        }

    # ── Config management ────────────────────────────────────────────

    def add_watch_dir(self, directory: str) -> bool:
        """Add a directory to watch."""
        path = Path(directory)
        if not path.is_dir():
            return False
        if path not in self._watch_dirs:
            self._watch_dirs.append(path)
        return True

    def remove_watch_dir(self, directory: str) -> bool:
        """Remove a directory from the watch list."""
        path = Path(directory)
        if path in self._watch_dirs:
            self._watch_dirs.remove(path)
            return True
        return False

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "watch_dirs": [str(d) for d in self._watch_dirs],
            "exclude_dirs": [str(d) for d in self._exclude_dirs],
            "files_ingested": self._files_ingested,
            "files_skipped": self._files_skipped,
            "mode": "watchdog" if self._observer else "polling",
        }


# ── Module-level singleton ───────────────────────────────────────────────

_watcher: KnowledgeWatcher | None = None


def get_knowledge_watcher(cfg: dict | None = None) -> KnowledgeWatcher:
    """Get or create the singleton KnowledgeWatcher."""
    global _watcher
    if _watcher is None:
        _watcher = KnowledgeWatcher(cfg)
    return _watcher


def start_knowledge_watcher(cfg: dict | None = None) -> bool:
    """Start the knowledge watcher."""
    return get_knowledge_watcher(cfg).start()


def stop_knowledge_watcher() -> None:
    """Stop the knowledge watcher."""
    if _watcher is not None:
        _watcher.stop()
