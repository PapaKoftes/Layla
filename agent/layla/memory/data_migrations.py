"""Data-backfill migrations extracted from migrations.py (BL-028 file split).

Self-contained one-time data migrations — FK orphan cleanup, legacy learnings.json import,
and the evolution-layer backfill — each opening its own connection. Split out of the schema-DDL
sequence in migrations.py to keep that file focused; called from _migrate_impl.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time

from layla.memory.db_connection import _conn, _resolve_db_path
from layla.time_utils import utcnow

logger = logging.getLogger("layla")


def _cleanup_orphaned_records() -> None:
    """Remove rows whose foreign-key parents no longer exist.

    This runs once per process (called inside ``_migrate_impl``) so we clean up
    any historical orphans *before* PRAGMA foreign_keys=ON is enforced on every
    connection.  Each statement is wrapped individually so a missing table (e.g.
    on a fresh DB where goals haven't been created yet) never blocks the rest.
    """
    cleanup_statements = [
        (
            "conversation_messages",
            "DELETE FROM conversation_messages WHERE conversation_id NOT IN (SELECT id FROM conversations)",
        ),
        (
            "relationships (from_entity)",
            "DELETE FROM relationships WHERE from_entity NOT IN (SELECT id FROM entities)",
        ),
        (
            "relationships (to_entity)",
            "DELETE FROM relationships WHERE to_entity NOT IN (SELECT id FROM entities)",
        ),
        (
            "goal_progress",
            "DELETE FROM goal_progress WHERE goal_id NOT IN (SELECT id FROM goals)",
        ),
        (
            "episode_events",
            "DELETE FROM episode_events WHERE episode_id NOT IN (SELECT id FROM episodes)",
        ),
    ]
    try:
        with _conn() as db:
            for label, sql in cleanup_statements:
                try:
                    cursor = db.execute(sql)
                    if cursor.rowcount > 0:
                        logger.info(
                            "FK orphan cleanup: removed %d orphaned rows from %s",
                            cursor.rowcount,
                            label,
                        )
                except Exception:
                    # Table may not exist yet on a brand-new DB — that's fine.
                    pass
            db.commit()
    except Exception as exc:
        logger.warning("FK orphan cleanup failed: %s", exc)


def _migrate_learnings_json() -> None:
    learnings_json = _resolve_db_path().parent / "learnings.json"
    if learnings_json.exists():
        try:
            data = json.loads(learnings_json.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                with _conn() as db:
                    existing = {r[0] for r in db.execute("SELECT content FROM learnings")}
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        c = item.get("content", "")
                        if c and c not in existing:
                            db.execute(
                                "INSERT INTO learnings (content, type, created_at) VALUES (?,?,?)",
                                (c, item.get("type", "fact"), item.get("created_at", utcnow().isoformat())),
                            )
                    db.commit()
                # Rename old file so we don't migrate twice
                learnings_json.rename(learnings_json.with_suffix(".json.migrated"))
        except Exception:
            pass


def _migrate_evolution_layer() -> None:
    """Create evolution layer tables and seed capability_domains, dependencies, capabilities."""
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS capability_domains (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS capabilities (
                domain_id              TEXT PRIMARY KEY REFERENCES capability_domains(id),
                level                  REAL NOT NULL DEFAULT 0.5,
                confidence             REAL NOT NULL DEFAULT 0.5,
                trend                  TEXT NOT NULL DEFAULT 'stable',
                last_practiced_at      TEXT,
                decay_risk             REAL NOT NULL DEFAULT 0.5,
                reinforcement_priority REAL NOT NULL DEFAULT 0.5,
                practice_count         INTEGER NOT NULL DEFAULT 0,
                updated_at             TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS capability_events (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                domain_id             TEXT NOT NULL,
                event_type            TEXT NOT NULL,
                mission_id            TEXT,
                delta_level           REAL DEFAULT 0,
                delta_confidence      REAL DEFAULT 0,
                notes                 TEXT,
                usefulness_score      REAL DEFAULT 0.5,
                learning_quality_score REAL DEFAULT 0.5,
                created_at            TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS capability_dependencies (
                source_domain_id TEXT NOT NULL,
                target_domain_id TEXT NOT NULL,
                weight          REAL NOT NULL DEFAULT 0.2,
                PRIMARY KEY (source_domain_id, target_domain_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS style_profile (
                key                 TEXT PRIMARY KEY,
                profile_snapshot   TEXT,
                last_reinforced_at TEXT,
                drift_score        REAL DEFAULT 0,
                updated_at         TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS mission_chains (
                id                TEXT PRIMARY KEY,
                parent_mission_id TEXT,
                mission_type      TEXT NOT NULL,
                goal_summary      TEXT,
                outcome_summary   TEXT,
                status            TEXT NOT NULL DEFAULT 'pending',
                capability_domains TEXT,
                created_at        TEXT NOT NULL,
                completed_at      TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                domain_id  TEXT,
                plan_id    TEXT,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS project_context (
                id               INTEGER PRIMARY KEY CHECK (id = 1),
                project_name     TEXT DEFAULT '',
                domains         TEXT DEFAULT '[]',
                key_files       TEXT DEFAULT '[]',
                goals           TEXT DEFAULT '',
                lifecycle_stage TEXT DEFAULT '',
                updated_at      TEXT NOT NULL
            )
        """)
        db.execute("INSERT OR IGNORE INTO project_context (id, updated_at) VALUES (1, ?)", (now,))
        db.commit()

    # Seed capability_domains (idempotent: insert only if empty)
    seed_domains = [
        ("coding", "Coding", "Implementing and refactoring code"),
        ("system_design", "System Design", "Architecture and design decisions"),
        ("communication", "Communication", "Explaining and writing clearly"),
        ("research", "Research", "Deep research and synthesis"),
        ("planning", "Planning", "Task breakdown and roadmaps"),
        ("writing", "Writing", "Structured writing and documentation"),
        ("repo_understanding", "Repo Understanding", "Understanding codebases"),
        ("problem_solving", "Problem Solving", "Debugging and analysis"),
        ("strategic_thinking", "Strategic Thinking", "Tradeoffs and strategy"),
        ("self_maintenance", "Self-Maintenance", "Improving own systems"),
    ]
    with _conn() as db:
        for domain_id, name, description in seed_domains:
            db.execute(
                "INSERT OR IGNORE INTO capability_domains (id, name, description, created_at) VALUES (?,?,?,?)",
                (domain_id, name, description, now),
            )
        # Seed capability_dependencies
        deps = [
            ("planning", "coding", 0.3),
            ("research", "writing", 0.2),
            ("system_design", "coding", 0.2),
            ("problem_solving", "strategic_thinking", 0.2),
            ("repo_understanding", "coding", 0.25),
            ("communication", "writing", 0.2),
        ]
        for src, tgt, w in deps:
            db.execute(
                "INSERT OR IGNORE INTO capability_dependencies (source_domain_id, target_domain_id, weight) VALUES (?,?,?)",
                (src, tgt, w),
            )
        # Fabrication domains and dependencies (Part 1 + Part 6)
        fabrication_domains = [
            ("cad_modeling", "CAD Modeling", "Fabrication-friendly geometry and structure"),
            ("cam_strategy", "CAM Strategy", "Toolpath and machining strategy"),
            ("parametric_design", "Parametric Design", "Reusable definitions and constraints"),
            ("cnc_machining", "CNC Machining", "Material-specific feeds, speeds, toolpaths"),
            ("tooling", "Tooling", "Tool selection for geometry and material"),
            ("feeds_and_speeds", "Feeds and Speeds", "Cutting parameters by material and tool"),
            ("woodworking", "Woodworking", "Wood connection strength, use cases, techniques"),
            ("wood_assembly", "Wood assembly", "Connection types and applications in wood"),
            ("structural_building", "Structural Building", "Load-bearing and assembly"),
            ("furniture_design", "Furniture Design", "Form, function, and build sequence"),
            ("digital_fabrication", "Digital Fabrication", "From design to physical output"),
            ("python_fabrication_tools", "Python Fabrication Tools", "ezdxf, OpenCV, programmatic DXF"),
            ("fabrication_logic", "Fabrication Logic", "Logic and workflow from design to physical output"),
        ]
        for domain_id, name, description in fabrication_domains:
            db.execute(
                "INSERT OR IGNORE INTO capability_domains (id, name, description, created_at) VALUES (?,?,?,?)",
                (domain_id, name, description, now),
            )
        fabrication_deps = [
            ("cad_modeling", "cam_strategy", 0.25),
            ("cam_strategy", "cnc_machining", 0.3),
            ("cnc_machining", "tooling", 0.25),
            ("tooling", "feeds_and_speeds", 0.25),
            ("parametric_design", "cad_modeling", 0.2),
            ("python_fabrication_tools", "digital_fabrication", 0.2),
        ]
        for src, tgt, w in fabrication_deps:
            db.execute(
                "INSERT OR IGNORE INTO capability_dependencies (source_domain_id, target_domain_id, weight) VALUES (?,?,?)",
                (src, tgt, w),
            )
        db.commit()

    # Optional: add lifecycle_stage to project_context (existing DBs)
    try:
        with _conn() as db:
            db.execute("ALTER TABLE project_context ADD COLUMN lifecycle_stage TEXT DEFAULT ''")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # Optional: add progress, blockers, last_discussed to project_context (companion experience)
    for col in ("progress", "blockers", "last_discussed"):
        try:
            with _conn() as db:
                db.execute(f"ALTER TABLE project_context ADD COLUMN {col} TEXT DEFAULT ''")
                db.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

    # Optional: add usefulness_score and learning_quality_score to capability_events (existing DBs)
    for col, default in (("usefulness_score", "0.5"), ("learning_quality_score", "0.5")):
        try:
            with _conn() as db:
                db.execute(f"ALTER TABLE capability_events ADD COLUMN {col} REAL DEFAULT {default}")
                db.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

    # Capability implementations (technical backends: vector_search, embedding, etc.)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS capability_implementations (
                    capability_name   TEXT NOT NULL,
                    implementation_id TEXT NOT NULL,
                    package_name      TEXT NOT NULL,
                    status            TEXT NOT NULL DEFAULT 'candidate',
                    latency_ms        REAL,
                    throughput_per_sec REAL,
                    memory_mb         REAL,
                    benchmark_results  TEXT,
                    last_benchmarked_at TEXT,
                    sandbox_valid     INTEGER DEFAULT 0,
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL,
                    PRIMARY KEY (capability_name, implementation_id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_cap_impl_status ON capability_implementations(status)")
            db.commit()
    except Exception as e:
        logger.warning("capability_implementations table migration failed: %s", e)

    # Backfill capabilities: one row per domain with defaults
    with _conn() as db:
        rows = db.execute("SELECT id FROM capability_domains").fetchall()
        for row in rows:
            domain_id = row["id"]
            db.execute(
                """INSERT OR IGNORE INTO capabilities
                   (domain_id, level, confidence, trend, decay_risk, reinforcement_priority, practice_count, updated_at)
                   VALUES (?, 0.5, 0.5, 'stable', 0.5, 0.5, 0, ?)""",
                (domain_id, now),
            )
        db.commit()

    # Seed light style profile (direction only; identity stabilizes over time)
    with _conn() as db:
        n = db.execute("SELECT COUNT(*) FROM style_profile").fetchone()[0]
        if n == 0:
            defaults = [
                ("writing", "Clear, direct. Prefer active voice. No fluff. Stay on point."),
                ("coding", "Readable names, small steps. Prefer standard library. One concern per change."),
                ("reasoning", "State assumptions. One conclusion per thread. Acknowledge uncertainty when it exists."),
                ("structuring", "Lead with the point. Group by idea. Short paragraphs and lists when they help."),
            ]
            for key, snapshot in defaults:
                db.execute(
                    """INSERT INTO style_profile (key, profile_snapshot, last_reinforced_at, drift_score, updated_at)
                       VALUES (?,?,?,0,?)""",
                    (key, snapshot, now, now),
                )
            db.commit()

    # Session prompt log + tool permission grants (operator/session scoped)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS session_prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL,
                    aspect TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_session_prompts_id_desc ON session_prompts(id DESC)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS tool_permission_grants (
                    id TEXT PRIMARY KEY,
                    tool TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    scope TEXT DEFAULT 'session',
                    created_at TEXT,
                    expires_at TEXT
                )
            """)
            db.commit()
    except Exception as e:
        logger.warning("session_prompts / tool_permission_grants migration failed: %s", e)

    # layla_plans (planning-first) — standalone migration for DBs created before this block ran
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS layla_plans (
                    id               TEXT PRIMARY KEY,
                    workspace_root   TEXT NOT NULL DEFAULT '',
                    goal             TEXT NOT NULL DEFAULT '',
                    context          TEXT NOT NULL DEFAULT '',
                    steps_json       TEXT NOT NULL DEFAULT '[]',
                    status           TEXT NOT NULL DEFAULT 'draft',
                    conversation_id  TEXT NOT NULL DEFAULT '',
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_layla_plans_ws ON layla_plans(workspace_root)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_layla_plans_status ON layla_plans(status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_layla_plans_updated ON layla_plans(updated_at DESC)")
            db.commit()
    except Exception as e:
        logger.warning("layla_plans migration failed: %s", e)

    # tasks — coordinator / execution persistence (architecture overhaul)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    plan_json TEXT DEFAULT '{}',
                    results_json TEXT DEFAULT '[]',
                    execution_state_json TEXT DEFAULT '{}',
                    conversation_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_conv ON tasks(conversation_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC)")
            db.commit()
    except Exception as e:
        logger.warning("tasks table migration failed: %s", e)

    # strategy_stats — task_type + strategy success/fail tallies (outcome loop)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS strategy_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    last_updated_at TEXT NOT NULL,
                    UNIQUE(task_type, strategy)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_strategy_stats_task ON strategy_stats(task_type)")
            db.commit()
    except Exception as e:
        logger.warning("strategy_stats migration failed: %s", e)

    # tool_calls — structured tracing for every tool execution (Phase 0.2)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      TEXT NOT NULL DEFAULT '',
                    tool_name   TEXT NOT NULL,
                    args_hash   TEXT DEFAULT '',
                    result_ok   INTEGER DEFAULT 0,
                    error_code  TEXT DEFAULT '',
                    duration_ms INTEGER DEFAULT 0,
                    created_at  TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id ON tool_calls(run_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_created ON tool_calls(created_at DESC)")
            db.commit()
    except Exception as e:
        logger.warning("tool_calls table migration failed: %s", e)

    # Add cost_usd + provider columns to tool_calls (Phase 3 — LLM cost tracking)
    try:
        with _conn() as db:
            cols = {row[1] for row in db.execute("PRAGMA table_info(tool_calls)").fetchall()}
            if "cost_usd" not in cols:
                db.execute("ALTER TABLE tool_calls ADD COLUMN cost_usd REAL DEFAULT 0.0")
            if "provider" not in cols:
                db.execute("ALTER TABLE tool_calls ADD COLUMN provider TEXT DEFAULT ''")
            if "model_used" not in cols:
                db.execute("ALTER TABLE tool_calls ADD COLUMN model_used TEXT DEFAULT ''")
            db.commit()
    except Exception as e:
        logger.debug("tool_calls cost columns migration: %s", e)

    # ── Phase A: Canonical entity/relationship tables ──────────────────────
    # These are the single source of truth for all entities stored anywhere.
    # Every service that discovers people, concepts, technologies, or code
    # symbols MUST write here via services/memory_router.py.
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id              TEXT PRIMARY KEY,
                    type            TEXT NOT NULL,
                    canonical_name  TEXT NOT NULL,
                    aliases         TEXT DEFAULT '[]',
                    description     TEXT DEFAULT '',
                    tags            TEXT DEFAULT '[]',
                    confidence      REAL DEFAULT 0.5,
                    source          TEXT DEFAULT '',
                    evidence        TEXT DEFAULT '',
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    last_seen_at    TEXT DEFAULT '',
                    attributes      TEXT DEFAULT '{}'
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_type ON entities(canonical_name, type)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    id              TEXT PRIMARY KEY,
                    from_entity     TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    to_entity       TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    type            TEXT NOT NULL,
                    weight          REAL DEFAULT 0.5,
                    evidence        TEXT DEFAULT '',
                    source          TEXT DEFAULT '',
                    bidirectional   INTEGER DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_rel_from ON relationships(from_entity)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_rel_to ON relationships(to_entity)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(type)")
            db.commit()
    except Exception as e:
        logger.warning("entities/relationships migration failed: %s", e)

    # Privacy level column on entities (TIER 6: Privacy Separation)
    try:
        with _conn() as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(entities)").fetchall()}
            if "privacy_level" not in cols:
                db.execute("ALTER TABLE entities ADD COLUMN privacy_level TEXT DEFAULT 'public'")
                db.execute("CREATE INDEX IF NOT EXISTS idx_entities_privacy ON entities(privacy_level)")
                db.commit()
    except Exception:
        pass

    # Privacy level column on learnings (allows marking learnings as personal/sensitive)
    try:
        with _conn() as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(learnings)").fetchall()}
            if "privacy_level" not in cols:
                db.execute("ALTER TABLE learnings ADD COLUMN privacy_level TEXT DEFAULT 'public'")
                db.commit()
    except Exception:
        pass
