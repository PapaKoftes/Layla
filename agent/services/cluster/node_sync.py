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
from typing import Any

logger = logging.getLogger("layla")

# ── Retry / reconnect constants ────────────────────────────────────────
SYNC_MAX_RETRIES = 3
SYNC_BACKOFF_BASE = 2          # seconds; delays will be 2, 4, 8
PEER_MAX_CONSECUTIVE_FAILS = 5  # skip peer after this many consecutive failures
DEAD_LETTER_THRESHOLD = 10      # mark learning as dead-letter after N failed pushes


# ── Syncable sources ─────────────────────────────────────────────────────
#
# The set of knowledge we replicate between paired nodes.  Each "kind" maps to
# a DB table (resolved off LAYLA_DATA_DIR via layla.memory.db_connection._conn)
# plus the metadata columns to carry over the wire.  Every kind dedups on a
# content hash so a two-way sync can never loop or double-import.
#
#   learning   → learnings        (already synced; has a content_hash column)
#   memory     → aspect_memories  (per-aspect memories; deduped on content)
#   knowledge  → knowledge_entries (the wiki/KB store; created on demand)
#
# NOTE: table names come from this fixed registry, never from request data, so
# the f-string queries below are not an injection surface.
_SYNC_SOURCES: dict[str, dict[str, Any]] = {
    "learning": {
        "table": "learnings",
        "carry": ("type", "confidence", "source", "tags", "aspect_id"),
        "has_hash": True,
        "dedup": "hash",
    },
    "memory": {
        "table": "aspect_memories",
        "carry": ("aspect_id",),
        "has_hash": False,
        "dedup": "content",
    },
    "knowledge": {
        "table": "knowledge_entries",
        "carry": ("title", "tags", "source"),
        "has_hash": True,
        "dedup": "hash",
    },
}
SYNC_KINDS: tuple[str, ...] = tuple(_SYNC_SOURCES.keys())


def _content_hash(content: str) -> str:
    """Stable 32-char content hash — the dedup key shared by every kind."""
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _migrate_db() -> None:
    """Ensure the core schema exists before we read/write it.

    A freshly-paired node legitimately starts with an empty (unmigrated) DB, so
    node-sync must not assume the tables already exist.  ``migrate()`` is cheap
    and idempotent (guarded + CREATE TABLE IF NOT EXISTS)."""
    try:
        from layla.memory.migrations import migrate
        migrate()
    except Exception as e:
        logger.debug("migrate() during sync failed: %s", e)


def _row_get(row: Any, key: str, default: Any = "") -> Any:
    """Read a column from a sqlite3.Row (by name) or a plain dict."""
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return default


def _ensure_knowledge_table(db: Any) -> None:
    """Create the durable knowledge/wiki entries table if absent (idempotent).

    Kept inline (like ``pending_sync``) so node-sync owns its own storage and
    does not require a schema migration in a file it doesn't own.  This is the
    canonical DB home for wiki entries that replicate between nodes.
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_entries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            content      TEXT NOT NULL,
            title        TEXT DEFAULT '',
            tags         TEXT DEFAULT '',
            source       TEXT DEFAULT '',
            content_hash TEXT,
            created_at   TEXT NOT NULL
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_entries_hash ON knowledge_entries(content_hash)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_entries_created ON knowledge_entries(created_at)")


def add_knowledge_entry(content: str, *, title: str = "", tags: str = "", source: str = "local") -> bool:
    """Store a wiki/KB entry in the node-syncable ``knowledge_entries`` table.

    Deduped by content hash so re-adding the same entry is a no-op.  Returns
    True if a new row was written.
    """
    content = (content or "").strip()
    if not content:
        return False
    try:
        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow
        ch = _content_hash(content)
        with _conn() as db:
            _ensure_knowledge_table(db)
            if db.execute("SELECT 1 FROM knowledge_entries WHERE content_hash = ? LIMIT 1", (ch,)).fetchone():
                return False
            db.execute(
                "INSERT INTO knowledge_entries (content, title, tags, source, content_hash, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (content, title, tags, source, ch, utcnow().isoformat()),
            )
            db.commit()
        return True
    except Exception as e:
        logger.debug("add_knowledge_entry failed: %s", e)
        return False


# ── Pairing gate ─────────────────────────────────────────────────────────
#
# The whole subsystem is a no-op until a pair exists.  We NEVER push to, or
# accept a sync from, a peer we are not mutually paired + authenticated with.

def _load_cluster_cfg() -> dict[str, Any]:
    try:
        from services.cluster.cluster_network import load_cluster_config
        return load_cluster_config() or {}
    except Exception:
        return {}


def is_authorized_peer(peer_id: str, cfg: dict[str, Any] | None = None) -> bool:
    """A peer may be synced with ONLY when we hold a shared cluster secret AND
    the peer is a persisted, paired peer.  Refuses every unpaired/unauthenticated
    node — the core safety invariant."""
    cfg = cfg if cfg is not None else _load_cluster_cfg()
    if not cfg.get("cluster_secret_hash"):
        return False
    return bool(peer_id) and peer_id in (cfg.get("peers") or {})


def sync_paired() -> bool:
    """True only once a pair exists: clustering persisted on, a shared secret
    held, and at least one paired peer recorded.  Until then, sync is a complete
    no-op (no work, no network) — the common single-device case."""
    cfg = _load_cluster_cfg()
    return bool(cfg.get("cluster_enabled") and cfg.get("cluster_secret_hash") and (cfg.get("peers")))


# ── Sync state tracking ─────────────────────────────────────────────────

_SYNC_STATE_KEY = "cluster_sync_state"


def _watermark_key(peer_id: str, slot: str = "learning") -> str:
    """Per-(peer, slot) watermark key.  ``slot`` is a kind, optionally suffixed
    with a direction (e.g. ``learning:push`` / ``memory:pull``) so push and pull
    advance independently and re-sync stays incremental."""
    return f"{_SYNC_STATE_KEY}_{peer_id}_{slot}"


def _get_last_sync_time(peer_id: str, slot: str = "learning") -> str:
    """Get the last sync watermark for a peer + slot."""
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            row = db.execute(
                "SELECT snapshot FROM user_identity WHERE key = ?",
                (_watermark_key(peer_id, slot),),
            ).fetchone()
            if row:
                return row["snapshot"] if isinstance(row, dict) else row[0]
    except Exception:
        pass
    return "2000-01-01T00:00:00Z"


def _set_last_sync_time(peer_id: str, timestamp: str, slot: str = "learning") -> None:
    """Update the last sync watermark for a peer + slot."""
    try:
        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow
        with _conn() as db:
            db.execute(
                """INSERT OR REPLACE INTO user_identity (key, snapshot, updated_at)
                   VALUES (?, ?, ?)""",
                (_watermark_key(peer_id, slot), timestamp, utcnow().isoformat()),
            )
            db.commit()
    except Exception as e:
        logger.debug("Failed to save sync timestamp: %s", e)


def _max_created(records: list[dict[str, Any]]) -> str:
    """Highest created_at across records (ISO timestamps sort lexicographically)."""
    best = ""
    for r in records:
        c = r.get("created_at") or ""
        if c > best:
            best = c
    return best


def _advance_watermark(peer_id: str, slot: str, records: list[dict[str, Any]]) -> None:
    """Advance a per-slot watermark to the newest record seen, monotonically."""
    hi = _max_created(records)
    if not hi:
        return
    if hi > _get_last_sync_time(peer_id, slot):
        _set_last_sync_time(peer_id, hi, slot)


# ── Generic multi-kind export/import ─────────────────────────────────────

def export_since(kind: str, since: str, limit: int = 500) -> list[dict[str, Any]]:
    """Export records of ``kind`` created since ``since`` (incremental).

    Returns wire records: ``{kind, content, content_hash, created_at, <carry>}``.
    Used to send our knowledge to a peer.
    """
    src = _SYNC_SOURCES.get(kind)
    if not src:
        return []
    cols = ["content", "created_at", *src["carry"]]
    if src["has_hash"]:
        cols.append("content_hash")
    _migrate_db()
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            if kind == "knowledge":
                _ensure_knowledge_table(db)
            rows = db.execute(
                f"SELECT {', '.join(cols)} FROM {src['table']} "
                "WHERE created_at > ? ORDER BY created_at ASC LIMIT ?",
                (since, limit),
            ).fetchall()
    except Exception as e:
        logger.warning("export_since(%s) failed: %s", kind, e)
        return []

    result: list[dict[str, Any]] = []
    for row in rows:
        content = _row_get(row, "content")
        if not content:
            continue
        ch = _row_get(row, "content_hash") if src["has_hash"] else ""
        if not ch:
            ch = _content_hash(content)
        rec: dict[str, Any] = {
            "kind": kind,
            "content": content,
            "content_hash": ch,
            "created_at": _row_get(row, "created_at"),
        }
        for c in src["carry"]:
            rec[c] = _row_get(row, c)
        result.append(rec)
    return result


def import_records(kind: str, records: list[dict[str, Any]], source_label: str = "cluster_sync") -> dict[str, int]:
    """Import records of ``kind`` from a remote node, deduping by content hash.

    Never double-imports: a record whose content hash (learnings/knowledge) or
    exact content (memories) already exists is skipped.  Returns imported/skipped.
    """
    src = _SYNC_SOURCES.get(kind)
    if not src or not records:
        return {"imported": 0, "skipped": 0}

    imported = 0
    skipped = 0
    _migrate_db()
    try:
        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow

        with _conn() as db:
            if kind == "knowledge":
                _ensure_knowledge_table(db)
            for rec in records:
                content = (rec.get("content") or "").strip()
                if not content:
                    skipped += 1
                    continue
                content_hash = rec.get("content_hash") or _content_hash(content)
                created = rec.get("created_at") or utcnow().isoformat()

                if _record_exists(db, kind, content_hash, content):
                    skipped += 1
                    continue

                _insert_record(db, kind, rec, content, content_hash, created, source_label)
                imported += 1
            db.commit()
    except Exception as e:
        logger.warning("import_records(%s) failed: %s", kind, e)

    if imported:
        logger.info("Imported %d %s from %s (skipped %d duplicates)", imported, kind, source_label, skipped)
    return {"imported": imported, "skipped": skipped}


def _record_exists(db: Any, kind: str, content_hash: str, content: str) -> bool:
    """Dedup probe: content-hash for hashed kinds, exact content for memories."""
    src = _SYNC_SOURCES[kind]
    if src["dedup"] == "content":
        row = db.execute(
            f"SELECT 1 FROM {src['table']} WHERE content = ? LIMIT 1", (content,)
        ).fetchone()
    else:
        row = db.execute(
            f"SELECT 1 FROM {src['table']} WHERE content_hash = ? LIMIT 1", (content_hash,)
        ).fetchone()
    return row is not None


def _insert_record(db: Any, kind: str, rec: dict[str, Any], content: str,
                   content_hash: str, created: str, source_label: str) -> None:
    """Insert one record into its kind's table."""
    if kind == "memory":
        db.execute(
            "INSERT INTO aspect_memories (aspect_id, content, created_at) VALUES (?,?,?)",
            (rec.get("aspect_id", "") or "", content, created),
        )
    elif kind == "knowledge":
        db.execute(
            "INSERT INTO knowledge_entries (content, title, tags, source, content_hash, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (content, rec.get("title", "") or "", rec.get("tags", "") or "",
             source_label, content_hash, created),
        )
    else:  # learning
        db.execute(
            "INSERT INTO learnings (content, type, created_at, confidence, source, content_hash, tags, aspect_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (content, rec.get("type", "fact") or "fact", created,
             rec.get("confidence", 0.5), source_label, content_hash,
             rec.get("tags", "") or "", rec.get("aspect_id", "") or ""),
        )


# ── Pending sync buffer (DRONE offline mode) ─────────────────────────────

def buffer_for_sync(content: str, learning_type: str = "fact", **kwargs) -> None:
    """Buffer a learning for later sync when we regain connectivity.

    Used by DRONE-GO when it's offline — queues learnings in a local
    pending_sync table to push to QUEEN on reconnect.
    """
    try:
        import uuid

        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow

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
            "refused": [],
            "errors": [],
        }

        # Hard gate: until a pair exists, sync is a complete no-op — no config
        # read beyond this cheap check, no network, no peers touched.  This keeps
        # the single-device case free of any sync behaviour.
        if not sync_paired():
            summary["note"] = "not_paired"
            return summary

        cluster_cfg = _load_cluster_cfg()

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

                # ── Safety: never sync to an unpaired/unauthenticated peer ──
                if not is_authorized_peer(pid, cluster_cfg):
                    logger.warning("Refusing sync with unauthorized peer %s", pid[:8])
                    summary["refused"].append(pid[:8])
                    continue

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

    # Kinds carried over the generic multi-kind transport (everything but the
    # learning kind, which keeps flowing through the canonical net.sync_push /
    # net.sync_pull path so that public transport contract stays authoritative).
    _EXTRA_KINDS: tuple[str, ...] = tuple(k for k in SYNC_KINDS if k != "learning")

    def _sync_with_peer(self, net, peer) -> dict[str, int]:
        """Sync with a single AUTHORIZED peer: push our new records for every
        syncable kind, pull theirs.  Push and pull each carry a per-(peer, kind)
        watermark that advances to the newest record seen, so re-sync stays
        incremental instead of resending everything.

        Learnings ride the canonical ``net.sync_push`` / ``net.sync_pull``
        transport; the newer kinds (memories, wiki) ride the generic multi-kind
        endpoint via ``net._post``.  Both channels apply the cluster-secret auth.

        Each HTTP call is wrapped in an exponential backoff retry loop:
        up to 3 attempts with delays of 2s, 4s, 8s between retries.
        """
        result = {"pushed": 0, "pulled": 0}
        pid = peer.instance_id

        # ── PUSH learnings (+ buffered offline items) via the canonical transport ──
        learn_out = export_since("learning", _get_last_sync_time(pid, "learning:push"))
        pending = get_pending_sync()
        if learn_out or pending:
            if self._retry_sync_push(net, peer, learn_out + pending):
                result["pushed"] += len(learn_out) + len(pending)
                _advance_watermark(pid, "learning:push", learn_out)
                if pending:
                    mark_synced([p["id"] for p in pending if "id" in p])
            elif pending:
                # Push failed after all retries — increment fail counts + dead-letter.
                ids = [p["id"] for p in pending if "id" in p]
                increment_fail_counts(ids)
                dead = get_dead_letter_candidates()
                if dead:
                    mark_dead_letters(dead)

        # ── PUSH memories + wiki via the multi-kind transport ──
        extra: dict[str, list[dict]] = {}
        for kind in self._EXTRA_KINDS:
            recs = export_since(kind, _get_last_sync_time(pid, f"{kind}:push"))
            if recs:
                extra[kind] = recs
        if extra and self._retry_push_records(net, peer, extra):
            for kind, recs in extra.items():
                result["pushed"] += len(recs)
                _advance_watermark(pid, f"{kind}:push", recs)

        # ── PULL learnings via the canonical transport ──
        their_learnings = self._retry_sync_pull(net, peer, _get_last_sync_time(pid, "learning:pull"))
        if their_learnings:
            counts = import_records("learning", their_learnings, source_label=f"sync:{pid[:8]}")
            result["pulled"] += counts.get("imported", 0)
            _advance_watermark(pid, "learning:pull", their_learnings)

        # ── PULL memories + wiki via the multi-kind transport ──
        since_map = {kind: _get_last_sync_time(pid, f"{kind}:pull") for kind in self._EXTRA_KINDS}
        incoming = self._retry_pull_records(net, peer, since_map)
        for kind in self._EXTRA_KINDS:
            recs = incoming.get(kind) or []
            if not recs:
                continue
            counts = import_records(kind, recs, source_label=f"sync:{pid[:8]}")
            result["pulled"] += counts.get("imported", 0)
            _advance_watermark(pid, f"{kind}:pull", recs)

        return result

    @staticmethod
    def _retry_sync_push(net, peer, learnings: list[dict]) -> bool:
        """Push learnings via the canonical transport with backoff (3 attempts, 2/4/8s)."""
        if not learnings:
            return True
        for attempt in range(SYNC_MAX_RETRIES):
            try:
                if net.sync_push(peer, learnings):
                    return True
            except Exception as e:
                logger.debug("sync_push to %s attempt %d/%d failed: %s",
                             peer.instance_id[:8], attempt + 1, SYNC_MAX_RETRIES, e)
            if attempt < SYNC_MAX_RETRIES - 1:
                time.sleep(SYNC_BACKOFF_BASE * (2 ** attempt))
        logger.warning("sync_push to %s failed after %d attempts", peer.instance_id[:8], SYNC_MAX_RETRIES)
        return False

    @staticmethod
    def _retry_sync_pull(net, peer, since: str) -> list[dict]:
        """Pull learnings via the canonical transport with backoff (3 attempts, 2/4/8s).

        ``net.sync_pull`` returns a list (``[]`` for both no-new-data and a
        swallowed error), so an empty result is not retried — that would only add
        backoff sleeps to the common no-op pull."""
        for attempt in range(SYNC_MAX_RETRIES):
            try:
                result = net.sync_pull(peer, since)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("sync_pull from %s attempt %d/%d failed: %s",
                             peer.instance_id[:8], attempt + 1, SYNC_MAX_RETRIES, e)
            if attempt < SYNC_MAX_RETRIES - 1:
                time.sleep(SYNC_BACKOFF_BASE * (2 ** attempt))
        return []

    @staticmethod
    def _retry_push_records(net, peer, records: dict[str, list[dict]]) -> bool:
        """Push the multi-kind ``records`` map over the authenticated channel
        (net._post applies the cluster-secret header).  Backoff 3×, 2/4/8s."""
        payload: dict[str, Any] = {"records": records}
        for attempt in range(SYNC_MAX_RETRIES):
            try:
                resp = net._post(peer.address, "/cluster/sync/push", payload)
                if resp and resp.get("ok"):
                    return True
            except Exception as e:
                logger.debug("records push to %s attempt %d/%d failed: %s",
                             peer.instance_id[:8], attempt + 1, SYNC_MAX_RETRIES, e)
            if attempt < SYNC_MAX_RETRIES - 1:
                time.sleep(SYNC_BACKOFF_BASE * (2 ** attempt))
        logger.warning("records push to %s failed after %d attempts", peer.instance_id[:8], SYNC_MAX_RETRIES)
        return False

    @staticmethod
    def _retry_pull_records(net, peer, since_map: dict[str, str]) -> dict[str, list[dict]]:
        """Pull the multi-kind ``records`` map (memories, wiki) with backoff."""
        if not since_map:
            return {}
        legacy_since = min(since_map.values())
        payload = {"since": legacy_since, "since_map": since_map, "kinds": list(since_map.keys())}
        for attempt in range(SYNC_MAX_RETRIES):
            try:
                resp = net._post(peer.address, "/cluster/sync/pull", payload)
                if resp is not None:
                    records = resp.get("records")
                    return records if isinstance(records, dict) else {}
            except Exception as e:
                logger.debug("records pull from %s attempt %d/%d failed: %s",
                             peer.instance_id[:8], attempt + 1, SYNC_MAX_RETRIES, e)
            if attempt < SYNC_MAX_RETRIES - 1:
                time.sleep(SYNC_BACKOFF_BASE * (2 ** attempt))
        logger.warning("records pull from %s failed after %d attempts", peer.instance_id[:8], SYNC_MAX_RETRIES)
        return {}

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
