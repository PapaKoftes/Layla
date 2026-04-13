"""Capabilities Db — Layla SQLite."""
import json
import logging
import sqlite3

from layla.time_utils import utcnow

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate

logger = logging.getLogger("layla")


# ── evolution layer: capabilities ──────────────────────────────────────────

def get_capability_domains() -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT * FROM capability_domains ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_capabilities() -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT * FROM capabilities ORDER BY domain_id").fetchall()
    return [dict(r) for r in rows]


def get_capability(domain_id: str) -> dict | None:
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM capabilities WHERE domain_id=?", (domain_id,)).fetchone()
    return dict(row) if row else None


def insert_capability_event(
    domain_id: str,
    event_type: str,
    mission_id: str | None = None,
    delta_level: float = 0.0,
    delta_confidence: float = 0.0,
    notes: str | None = None,
    usefulness_score: float = 0.5,
    learning_quality_score: float = 0.5,
) -> int:
    migrate()
    now = utcnow().isoformat()
    usefulness_score = max(0.0, min(1.0, usefulness_score))
    learning_quality_score = max(0.0, min(1.0, learning_quality_score))
    with _conn() as db:
        try:
            cur = db.execute(
                """INSERT INTO capability_events (domain_id, event_type, mission_id, delta_level, delta_confidence, notes, usefulness_score, learning_quality_score, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (domain_id, event_type, mission_id or "", delta_level, delta_confidence, notes or "", usefulness_score, learning_quality_score, now),
            )
        except sqlite3.OperationalError:
            cur = db.execute(
                """INSERT INTO capability_events (domain_id, event_type, mission_id, delta_level, delta_confidence, notes, usefulness_score, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (domain_id, event_type, mission_id or "", delta_level, delta_confidence, notes or "", usefulness_score, now),
            )
        db.commit()
        return cur.lastrowid


def update_capability(
    domain_id: str,
    level: float,
    confidence: float,
    trend: str,
    last_practiced_at: str | None,
    decay_risk: float,
    reinforcement_priority: float,
    practice_count: int,
) -> None:
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """UPDATE capabilities SET level=?, confidence=?, trend=?, last_practiced_at=?, decay_risk=?,
               reinforcement_priority=?, practice_count=?, updated_at=? WHERE domain_id=?""",
            (level, confidence, trend, last_practiced_at, decay_risk, reinforcement_priority, practice_count, now, domain_id),
        )
        db.commit()


def get_recent_capability_events(domain_id: str, n: int = 10) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM capability_events WHERE domain_id=? ORDER BY id DESC LIMIT ?",
            (domain_id, n),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_scheduler_history(n: int = 10) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM scheduler_history ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def append_scheduler_history(domain_id: str | None, plan_id: str | None) -> None:
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "INSERT INTO scheduler_history (domain_id, plan_id, created_at) VALUES (?,?,?)",
            (domain_id or "", plan_id or "", now),
        )
        db.commit()


def get_capability_dependencies() -> list[dict]:
    """Returns list of {source_domain_id, target_domain_id, weight}."""
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT source_domain_id, target_domain_id, weight FROM capability_dependencies").fetchall()
    return [dict(r) for r in rows]


# ── capability implementations (technical backends) ──────────────────────────

def get_capability_implementation(capability_name: str, implementation_id: str) -> dict | None:
    """Get a capability implementation record by name and impl id."""
    migrate()
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM capability_implementations WHERE capability_name=? AND implementation_id=?",
            (capability_name, implementation_id),
        ).fetchone()
    return dict(row) if row else None


def upsert_capability_implementation(
    capability_name: str,
    implementation_id: str,
    package_name: str,
    status: str = "candidate",
    latency_ms: float | None = None,
    throughput_per_sec: float | None = None,
    memory_mb: float | None = None,
    benchmark_results: str | None = None,
    sandbox_valid: bool = False,
) -> None:
    """Insert or update a capability implementation record."""
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """INSERT INTO capability_implementations
               (capability_name, implementation_id, package_name, status, latency_ms, throughput_per_sec,
                memory_mb, benchmark_results, last_benchmarked_at, sandbox_valid, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(capability_name, implementation_id) DO UPDATE SET
                 package_name=excluded.package_name, status=excluded.status,
                 latency_ms=CASE WHEN excluded.latency_ms IS NOT NULL THEN excluded.latency_ms ELSE capability_implementations.latency_ms END,
                 throughput_per_sec=CASE WHEN excluded.throughput_per_sec IS NOT NULL THEN excluded.throughput_per_sec ELSE capability_implementations.throughput_per_sec END,
                 memory_mb=CASE WHEN excluded.memory_mb IS NOT NULL THEN excluded.memory_mb ELSE capability_implementations.memory_mb END,
                 benchmark_results=CASE WHEN excluded.benchmark_results IS NOT NULL THEN excluded.benchmark_results ELSE capability_implementations.benchmark_results END,
                 last_benchmarked_at=CASE WHEN excluded.last_benchmarked_at IS NOT NULL THEN excluded.last_benchmarked_at ELSE capability_implementations.last_benchmarked_at END,
                 sandbox_valid=excluded.sandbox_valid,
                 updated_at=excluded.updated_at""",
            (
                capability_name, implementation_id, package_name, status,
                latency_ms, throughput_per_sec, memory_mb, benchmark_results,
                now if (latency_ms is not None or throughput_per_sec is not None) else None,
                1 if sandbox_valid else 0,
                now, now,
            ),
        )
        db.commit()


def get_best_capability_implementation(capability_name: str) -> dict | None:
    """Return the best benchmarked implementation for a capability (lowest latency, valid sandbox)."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            """SELECT * FROM capability_implementations
               WHERE capability_name=? AND status IN ('active','benchmarked') AND sandbox_valid=1
               ORDER BY latency_ms IS NULL, latency_ms ASC
               LIMIT 1""",
            (capability_name,),
        ).fetchall()
    return dict(rows[0]) if rows else None


def list_capability_implementations(capability_name: str | None = None) -> list[dict]:
    """List all capability implementation records, optionally filtered by capability."""
    migrate()
    with _conn() as db:
        if capability_name:
            rows = db.execute(
                "SELECT * FROM capability_implementations WHERE capability_name=? ORDER BY capability_name, implementation_id",
                (capability_name,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM capability_implementations ORDER BY capability_name, implementation_id"
            ).fetchall()
    return [dict(r) for r in rows]


# ── style profile (evolution layer) ────────────────────────────────────────

def get_style_profile(key: str) -> dict | None:
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM style_profile WHERE key=?", (key,)).fetchone()
    return dict(row) if row else None


def set_style_profile(key: str, profile_snapshot: str, drift_score: float = 0.0) -> None:
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """INSERT INTO style_profile (key, profile_snapshot, last_reinforced_at, drift_score, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET profile_snapshot=excluded.profile_snapshot,
                 last_reinforced_at=excluded.last_reinforced_at, drift_score=excluded.drift_score, updated_at=excluded.updated_at""",
            (key, profile_snapshot, now, drift_score, now),
        )
        db.commit()


