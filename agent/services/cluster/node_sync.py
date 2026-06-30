"""Node Sync — incremental knowledge replication between cluster nodes.

Syncs learnings, memories, and wiki entries between QUEEN and DRONE nodes
using timestamp-based incremental replication with content_hash dedup.

Phase 3C of the distributed infrastructure plan.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("layla")

# ── Retry / reconnect constants ────────────────────────────────────────
SYNC_MAX_RETRIES = 3
SYNC_BACKOFF_BASE = 2          # seconds; delays will be 2, 4, 8
PEER_MAX_CONSECUTIVE_FAILS = 5  # skip peer after this many consecutive failures
DEAD_LETTER_THRESHOLD = 10      # mark learning as dead-letter after N failed pushes


# ── Sync state tracking ─────────────────────────────────────────────────

_SYNC_STATE_KEY = "cluster_sync_state"


def _get_last_sync_time(peer_id: str) -> str:
    """Get the last sync timestamp for a peer."""
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            row = db.execute(
                "SELECT snapshot FROM user_identity WHERE key = ?",
                (f"{_SYNC_STATE_KEY}_{peer_id}",),
            ).fetchone()
            if row:
                return row["snapshot"] if isinstance(row, dict) else row[0]
    except Exception:
        pass
    return "2000-01-01T00:00:00Z"


def _set_last_sync_time(peer_id: str, timestamp: str) -> None:
    """Update the last sync timestamp for a peer."""
    try:
        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow
        with _conn() as db:
            db.execute(
                """INSERT OR REPLACE INTO user_identity (key, snapshot, updated_at)
                   VALUES (?, ?, ?)""",
                (f"{_SYNC_STATE_KEY}_{peer_id}", timestamp, utcnow().isoformat()),
            )
            db.commit()
    except Exception as e:
        logger.debug("Failed to save sync timestamp: %s", e)


# ── Learnings export/import ──────────────────────────────────────────────

def get_learnings_since(since: str, limit: int = 500) -> list[dict[str, Any]]:
    """Get learnings created since a given timestamp.

    Used to send our learnings to a peer.
    """
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            rows = db.execute(
                """SELECT id, content, type, created_at, confidence, source, content_hash, tags, aspect_id
                   FROM learnings
                   WHERE created_at > ?
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (since, limit),
            ).fetchall()

        result = []
        for row in rows:
            def _g(key, default=""):
                if isinstance(row, dict):
                    return row.get(key, default)
                try:
                    return row[key]
                except (IndexError, KeyError):
                    return default

            entry = {
                "content": _g("content"),
                "type": _g("type", "fact"),
                "created_at": _g("created_at"),
                "confidence": _g("confidence", 0.5),
                "source": _g("source", ""),
                "content_hash": _g("content_hash", ""),
                "tags": _g("tags", ""),
                "aspect_id": _g("aspect_id", ""),
            }
            # Ensure content_hash is populated
            if not entry["content_hash"] and entry["content"]:
                entry["content_hash"] = hashlib.sha256(entry["content"].encode()).hexdigest()[:32]
            result.append(entry)
        return result

    except Exception as e:
        logger.warning("get_learnings_since failed: %s", e)
        return []


def import_learnings(learnings: list[dict[str, Any]], source_label: str = "cluster_sync") -> dict[str, int]:
    """Import learnings from a remote node, deduplicating by content_hash.

    Returns counts of imported vs skipped.
    """
    imported = 0
    skipped = 0

    try:
        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow

        with _conn() as db:
            for entry in learnings:
                content = entry.get("content", "")
                if not content:
                    skipped += 1
                    continue

                # Compute content hash
                content_hash = entry.get("content_hash", "")
                if not content_hash:
                    content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

                # Check for duplicates
                existing = db.execute(
                    "SELECT id FROM learnings WHERE content_hash = ?",
                    (content_hash,),
                ).fetchone()
                if existing:
                    skipped += 1
                    continue

                # Insert
                db.execute(
                    """INSERT INTO learnings
                       (content, type, created_at, confidence, source, content_hash, tags, aspect_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        content,
                        entry.get("type", "fact"),
                        entry.get("created_at", utcnow().isoformat()),
                        entry.get("confidence", 0.5),
                        source_label,
                        content_hash,
                        entry.get("tags", ""),
                        entry.get("aspect_id", ""),
                    ),
                )
                imported += 1
            db.commit()

    except Exception as e:
        logger.warning("import_learnings failed: %s", e)

    if imported:
        logger.info("Imported %d learnings from %s (skipped %d duplicates)", imported, source_label, skipped)

    return {"imported": imported, "skipped": skipped}


# ── Pending sync buffer (DRONE offline mode) ─────────────────────────────

def buffer_for_sync(content: str, learning_type: str = "fact", **kwargs) -> None:
    """Buffer a learning for later sync when we regain connectivity.

    Used by DRONE-GO when it's offline — queues learnings in a local
    pending_sync table to push to QUEEN on reconnect.
    """
    try:
        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow
        import uuid

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        with _conn() as db:
            # Ensure pending_sync table exists
            db.execute("""
                CREATE TABLE IF NOT EXISTS pending_sync (
                    id          TEXT PRIMARY KEY,
                    content     TEXT NOT NULL,
                    type        TEXT DEFAULT 'fact',
                    content_hash TEXT,
                    confidence  REAL DEFAULT 0.5,
                    source      TEXT DEFAULT '',
                    tags        TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    synced      INTEGER DEFAULT 0
                )
            """)
            db.execute(
                """INSERT OR IGNORE INTO pending_sync
                   (id, content, type, content_hash, confidence, source, tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex[:16],
                    content,
                    learning_type,
                    content_hash,
                    kwargs.get("confidence", 0.5),
                    kwargs.get("source", ""),
                    kwargs.get("tags", ""),
                    utcnow().isoformat(),
                ),
            )
            db.commit()
    except Exception as e:
        logger.debug("buffer_for_sync failed: %s", e)


def get_pending_sync(limit: int = 100) -> list[dict[str, Any]]:
    """Get learnings that haven't been synced yet."""
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            rows = db.execute(
                """SELECT * FROM pending_sync
                   WHERE synced = 0
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        result = []
        for row in rows:
            if isinstance(row, dict):
                result.append(row)
            else:
                result.append({
                    "id": row[0],
                    "content": row[1],
                    "type": row[2],
                    "content_hash": row[3],
                    "confidence": row[4],
                    "source": row[5],
                    "tags": row[6],
                    "created_at": row[7],
                })
        return result
    except Exception:
        return []


def mark_synced(ids: list[str]) -> None:
    """Mark pending sync items as synced."""
    if not ids:
        return
    try:
        from layla.memory.db_connection import _conn
        placeholders = ",".join("?" for _ in ids)
        with _conn() as db:
            db.execute(
                f"UPDATE pending_sync SET synced = 1 WHERE id IN ({placeholders})",
                ids,
            )
            db.commit()
    except Exception as e:
        logger.debug("mark_synced failed: %s", e)


def _ensure_dead_letter_column() -> None:
    """Add dead_letter column to pending_sync if it does not exist (idempotent)."""
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            db.execute(
                "ALTER TABLE pending_sync ADD COLUMN dead_letter INTEGER DEFAULT 0"
            )
            db.commit()
    except Exception:
        # Column already exists or table missing — both are fine
        pass


def _ensure_fail_count_column() -> None:
    """Add fail_count column to pending_sync if it does not exist (idempotent)."""
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            db.execute(
                "ALTER TABLE pending_sync ADD COLUMN fail_count INTEGER DEFAULT 0"
            )
            db.commit()
    except Exception:
        pass


def mark_dead_letters(ids: list[str]) -> None:
    """Mark pending sync items as dead-letter (permanently failed)."""
    if not ids:
        return
    _ensure_dead_letter_column()
    try:
        from layla.memory.db_connection import _conn
        placeholders = ",".join("?" for _ in ids)
        with _conn() as db:
            db.execute(
                f"UPDATE pending_sync SET dead_letter = 1 WHERE id IN ({placeholders})",
                ids,
            )
            db.commit()
        logger.warning(
            "Marked %d pending_sync items as dead-letter after %d+ failed attempts",
            len(ids), DEAD_LETTER_THRESHOLD,
        )
    except Exception as e:
        logger.debug("mark_dead_letters failed: %s", e)


def increment_fail_counts(ids: list[str]) -> None:
    """Increment the fail_count for pending sync items after a failed push."""
    if not ids:
        return
    _ensure_fail_count_column()
    try:
        from layla.memory.db_connection import _conn
        placeholders = ",".join("?" for _ in ids)
        with _conn() as db:
            db.execute(
                f"UPDATE pending_sync SET fail_count = COALESCE(fail_count, 0) + 1 WHERE id IN ({placeholders})",
                ids,
            )
            db.commit()
    except Exception as e:
        logger.debug("increment_fail_counts failed: %s", e)


def get_dead_letter_candidates() -> list[str]:
    """Return IDs of pending_sync items whose fail_count >= DEAD_LETTER_THRESHOLD."""
    _ensure_fail_count_column()
    _ensure_dead_letter_column()
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            rows = db.execute(
                "SELECT id FROM pending_sync WHERE synced = 0 AND COALESCE(dead_letter, 0) = 0 AND COALESCE(fail_count, 0) >= ?",
                (DEAD_LETTER_THRESHOLD,),
            ).fetchall()
        return [r[0] if not isinstance(r, dict) else r["id"] for r in rows]
    except Exception:
        return []


def flush_pending_for_peer(peer_id: str) -> int:
    """Flush all un-synced pending items to a specific peer.

    Queries pending_sync WHERE synced=0 (and not dead-lettered),
    pushes them via the cluster network sync_push mechanism,
    and marks them synced=1 on success.

    Returns count of flushed items.
    """
    pending = get_pending_sync()
    if not pending:
        return 0

    # Filter out dead-lettered items
    _ensure_dead_letter_column()
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            rows = db.execute(
                "SELECT id FROM pending_sync WHERE synced = 0 AND COALESCE(dead_letter, 0) = 0"
            ).fetchall()
        live_ids = {r[0] if not isinstance(r, dict) else r["id"] for r in rows}
        pending = [p for p in pending if p.get("id") in live_ids]
    except Exception:
        pass

    if not pending:
        return 0

    try:
        from services.cluster.cluster_network import get_cluster_network
        net = get_cluster_network()
        peer = net.get_peer(peer_id)
        if not peer:
            return 0

        ok = net.sync_push(peer, pending)
        if ok:
            ids = [p["id"] for p in pending if "id" in p]
            mark_synced(ids)
            logger.info(
                "Flushed %d buffered learnings to peer %s",
                len(ids), peer_id[:8],
            )
            return len(ids)
        else:
            # Push failed — increment fail counts
            ids = [p["id"] for p in pending if "id" in p]
            increment_fail_counts(ids)
            # Check for dead-letter candidates
            dead = get_dead_letter_candidates()
            if dead:
                mark_dead_letters(dead)
            return 0
    except Exception as e:
        logger.debug("flush_pending_for_peer(%s) failed: %s", peer_id[:8], e)
        return 0


# ── Full sync orchestrator ───────────────────────────────────────────────

class NodeSync:
    """Orchestrates bidirectional sync between this node and all peers.

    Called periodically (every ``cluster_sync_interval`` seconds)
    by the scheduler.

    Tracks per-peer consecutive failure counts and supports:
    - Exponential backoff on individual peer sync attempts
    - Automatic skip of peers with 5+ consecutive failures
    - Reconnection detection (peer transitions OFFLINE -> ONLINE)
    - Pending buffer flush on reconnect
    - Dead-letter handling for items failing 10+ times
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._sync_interval = max(60, self._cfg.get("cluster_sync_interval", 300))
        self._sync_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Track consecutive sync failures per peer
        self._peer_retry_counts: dict[str, int] = {}
        # Track last-known status per peer for reconnection detection
        self._peer_last_status: dict[str, str] = {}

    def sync_once(self) -> dict[str, Any]:
        """Run a single sync cycle with all online peers.

        Includes reconnection detection: if a peer was previously OFFLINE
        but is now ONLINE (heartbeat recovered), flush pending buffers
        immediately.  Peers with 5+ consecutive failures are skipped
        until heartbeat marks them ONLINE again.

        Returns a summary of what was synced.
        """
        summary: dict[str, Any] = {
            "peers_synced": 0,
            "total_pushed": 0,
            "total_pulled": 0,
            "reconnected": [],
            "skipped": [],
            "errors": [],
        }

        try:
            from services.cluster.cluster_network import get_cluster_network
            net = get_cluster_network()
            if not net.enabled:
                summary["note"] = "cluster_disabled"
                return summary

            online_peers = net.get_online_peers()
            if not online_peers:
                summary["note"] = "no_peers_online"
                return summary

            for peer in online_peers:
                pid = peer.instance_id
                prev_status = self._peer_last_status.get(pid, "unknown")
                current_status = peer.status.value if hasattr(peer.status, "value") else str(peer.status)

                # ── Reconnection detection ────────────────────────────
                if prev_status == "offline" and current_status in ("online", "degraded"):
                    # Peer reconnected — flush pending buffer
                    flushed = flush_pending_for_peer(pid)
                    logger.info(
                        "Peer %s (%s) reconnected, flushing %d buffered learnings",
                        pid[:8], peer.name, flushed,
                    )
                    summary["reconnected"].append(pid[:8])
                    # Reset failure counter on reconnection
                    self._peer_retry_counts[pid] = 0

                # Update last-known status
                self._peer_last_status[pid] = current_status

                # ── Skip peers with too many consecutive failures ─────
                if self._peer_retry_counts.get(pid, 0) >= PEER_MAX_CONSECUTIVE_FAILS:
                    logger.debug(
                        "Skipping peer %s: %d consecutive sync failures",
                        pid[:8], self._peer_retry_counts[pid],
                    )
                    summary["skipped"].append(pid[:8])
                    continue

                # ── Normal sync ───────────────────────────────────────
                try:
                    result = self._sync_with_peer(net, peer)
                    summary["peers_synced"] += 1
                    summary["total_pushed"] += result.get("pushed", 0)
                    summary["total_pulled"] += result.get("pulled", 0)
                    # Success — reset failure counter
                    self._peer_retry_counts[pid] = 0
                except Exception as e:
                    self._peer_retry_counts[pid] = self._peer_retry_counts.get(pid, 0) + 1
                    summary["errors"].append(f"{pid[:8]}: {e}")

        except Exception as e:
            summary["errors"].append(str(e))

        if summary["total_pushed"] or summary["total_pulled"]:
            logger.info(
                "Sync cycle: %d peers, pushed=%d, pulled=%d",
                summary["peers_synced"],
                summary["total_pushed"],
                summary["total_pulled"],
            )

        return summary

    def _sync_with_peer(self, net, peer) -> dict[str, int]:
        """Sync with a single peer: push our new learnings, pull theirs.

        Each HTTP call is wrapped in an exponential backoff retry loop:
        up to 3 attempts with delays of 2s, 4s, 8s between retries.
        """
        result = {"pushed": 0, "pulled": 0}

        # Get last sync time for this peer
        last_sync = _get_last_sync_time(peer.instance_id)

        # Push: send our learnings since last sync (with retry)
        our_learnings = get_learnings_since(last_sync)
        if our_learnings:
            ok = self._retry_sync_push(net, peer, our_learnings)
            if ok:
                result["pushed"] = len(our_learnings)

        # Also push any buffered offline items (with retry + dead-letter handling)
        pending = get_pending_sync()
        if pending:
            ok = self._retry_sync_push(net, peer, pending)
            if ok:
                ids = [p["id"] for p in pending if "id" in p]
                mark_synced(ids)
                result["pushed"] += len(pending)
            else:
                # Push failed after all retries — increment fail counts
                ids = [p["id"] for p in pending if "id" in p]
                increment_fail_counts(ids)
                # Check for dead-letter candidates
                dead = get_dead_letter_candidates()
                if dead:
                    mark_dead_letters(dead)

        # Pull: get their learnings since last sync (with retry)
        their_learnings = self._retry_sync_pull(net, peer, last_sync)
        if their_learnings:
            counts = import_learnings(their_learnings, source_label=f"sync:{peer.instance_id[:8]}")
            result["pulled"] = counts.get("imported", 0)

        # Update sync timestamp
        now = datetime.now(timezone.utc).isoformat()
        _set_last_sync_time(peer.instance_id, now)

        return result

    @staticmethod
    def _retry_sync_push(net, peer, learnings: list[dict]) -> bool:
        """Push learnings with exponential backoff retry (3 attempts, 2/4/8s delays)."""
        for attempt in range(SYNC_MAX_RETRIES):
            try:
                ok = net.sync_push(peer, learnings)
                if ok:
                    return True
            except Exception as e:
                logger.debug(
                    "sync_push to %s attempt %d/%d failed: %s",
                    peer.instance_id[:8], attempt + 1, SYNC_MAX_RETRIES, e,
                )
            if attempt < SYNC_MAX_RETRIES - 1:
                delay = SYNC_BACKOFF_BASE * (2 ** attempt)
                logger.info(
                    "Retrying sync_push to %s in %ds (attempt %d/%d)",
                    peer.instance_id[:8], delay, attempt + 2, SYNC_MAX_RETRIES,
                )
                time.sleep(delay)
        logger.warning(
            "sync_push to %s failed after %d attempts",
            peer.instance_id[:8], SYNC_MAX_RETRIES,
        )
        return False

    @staticmethod
    def _retry_sync_pull(net, peer, since: str) -> list[dict]:
        """Pull learnings with exponential backoff retry (3 attempts, 2/4/8s delays)."""
        for attempt in range(SYNC_MAX_RETRIES):
            try:
                result = net.sync_pull(peer, since)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(
                    "sync_pull from %s attempt %d/%d failed: %s",
                    peer.instance_id[:8], attempt + 1, SYNC_MAX_RETRIES, e,
                )
            if attempt < SYNC_MAX_RETRIES - 1:
                delay = SYNC_BACKOFF_BASE * (2 ** attempt)
                logger.info(
                    "Retrying sync_pull from %s in %ds (attempt %d/%d)",
                    peer.instance_id[:8], delay, attempt + 2, SYNC_MAX_RETRIES,
                )
                time.sleep(delay)
        logger.warning(
            "sync_pull from %s failed after %d attempts",
            peer.instance_id[:8], SYNC_MAX_RETRIES,
        )
        return []

    # ── Background sync loop ─────────────────────────────────────────

    def start(self) -> None:
        """Start periodic background sync."""
        if self._sync_thread and self._sync_thread.is_alive():
            return
        self._stop_event.clear()
        self._sync_thread = threading.Thread(
            target=self._sync_loop,
            name="node-sync",
            daemon=True,
        )
        self._sync_thread.start()
        logger.info("Node sync started (every %ds)", self._sync_interval)

    def stop(self) -> None:
        """Stop the background sync loop."""
        self._stop_event.set()
        if self._sync_thread:
            self._sync_thread.join(timeout=10)
            self._sync_thread = None

    def _sync_loop(self) -> None:
        """Periodically sync with all peers.

        Before each sync cycle, updates ``_peer_last_status`` for ALL
        known peers (including offline ones) so that ``sync_once`` can
        detect OFFLINE -> ONLINE transitions and flush pending buffers.
        """
        while not self._stop_event.is_set():
            try:
                # Only sync if governor allows background work
                try:
                    from services.infrastructure.resource_governor import should_run_background
                    if not should_run_background(priority=2):
                        self._stop_event.wait(self._sync_interval)
                        continue
                except Exception:
                    pass

                # Snapshot ALL peer statuses (including offline) before sync
                try:
                    from services.cluster.cluster_network import get_cluster_network
                    net = get_cluster_network()
                    if net.enabled:
                        with net._peers_lock:
                            for pid, peer in net.peers.items():
                                status_val = peer.status.value if hasattr(peer.status, "value") else str(peer.status)
                                # Only set to offline if we haven't seen it yet
                                if pid not in self._peer_last_status:
                                    self._peer_last_status[pid] = status_val
                except Exception:
                    pass

                self.sync_once()
            except Exception as e:
                logger.debug("Sync loop error: %s", e)
            self._stop_event.wait(self._sync_interval)


# ── Module-level singleton ───────────────────────────────────────────────

_sync: NodeSync | None = None


def get_node_sync(cfg: dict | None = None) -> NodeSync:
    """Get or create the singleton NodeSync."""
    global _sync
    if _sync is None:
        _sync = NodeSync(cfg)
    return _sync


def sync_now() -> dict[str, Any]:
    """Run an immediate sync cycle."""
    return get_node_sync().sync_once()
