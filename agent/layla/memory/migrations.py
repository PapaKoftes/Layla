"""SQLite schema creation and migrations for Layla."""
import json
import logging
import sqlite3
import sys
import threading

from layla.memory.db_connection import _conn, _resolve_db_path
from layla.time_utils import utcnow

logger = logging.getLogger("layla")

# Migration guard: run _migrate_impl at most once per process.
_MIGRATED = False
_MIGRATION_LOCK = threading.Lock()

# ── MIGRATION VERSIONING ──
# Version 0: pre-versioning (all tables created with IF NOT EXISTS)
# Version 1: baseline — all existing tables, columns, indexes present
# Future migrations: check `if version < N` and run only new changes


def _get_schema_version(conn) -> int:
    """Get current schema version, or 0 if table doesn't exist."""
    try:
        row = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _set_schema_version(conn, version: int):
    """Update the schema version."""
    conn.execute(
        "UPDATE schema_version SET version=?, updated_at=datetime('now') WHERE id=1",
        (version,),
    )
    conn.commit()


def _effective_migrated() -> bool:
    """Prefer layla.memory.db._MIGRATED when tests patch the barrel module."""
    dbm = sys.modules.get("layla.memory.db")
    if dbm is not None and hasattr(dbm, "_MIGRATED"):
        return bool(getattr(dbm, "_MIGRATED"))
    return _MIGRATED


def migrate() -> None:
    """Create tables and run migrations. Safe to call repeatedly; runs at most once per process."""
    global _MIGRATED
    if _effective_migrated():
        return
    with _MIGRATION_LOCK:
        if _effective_migrated():
            return
        try:
            _migrate_impl()
            _MIGRATED = True
            dbm = sys.modules.get("layla.memory.db")
            if dbm is not None:
                try:
                    setattr(dbm, "_MIGRATED", True)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("DB migrate failed: %s", e)


def _migrate_impl() -> None:
    _dbp = _resolve_db_path()
    first_run = not _dbp.exists()
    with _conn() as db:
        # ── Schema version tracking (must be first) ──
        db.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)
        db.execute(
            "INSERT OR IGNORE INTO schema_version (id, version, updated_at) VALUES (1, 0, datetime('now'))"
        )
        db.commit()
        db.execute("""
            CREATE TABLE IF NOT EXISTS learnings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                content      TEXT NOT NULL,
                type         TEXT DEFAULT 'fact',
                created_at   TEXT NOT NULL,
                embedding_id TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS study_plans (
                id           TEXT PRIMARY KEY,
                topic        TEXT NOT NULL,
                status       TEXT DEFAULT 'active',
                progress     TEXT DEFAULT '[]',
                created_at   TEXT NOT NULL,
                last_studied TEXT,
                momentum_score REAL DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS wakeup_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                greeting  TEXT,
                notes     TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                tool        TEXT NOT NULL,
                args_summary TEXT,
                approved_by TEXT,
                result_ok   INTEGER
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS aspect_memories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                aspect_id  TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        # Performance indices — cover the hot query patterns
        db.execute("CREATE INDEX IF NOT EXISTS idx_learnings_type ON learnings(type)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_learnings_id_desc ON learnings(id DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit(tool)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_audit_id_desc ON audit(id DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_aspect_memories_aspect ON aspect_memories(aspect_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_study_plans_status ON study_plans(status)")
        # P1-2: cover hot retrieval path on learnings.embedding_id (column in CREATE TABLE)
        db.execute("CREATE INDEX IF NOT EXISTS idx_learnings_embedding_id ON learnings(embedding_id)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS outcome_evaluations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                evaluation_json TEXT NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_outcome_evaluations_cid_id_desc ON outcome_evaluations(conversation_id, id DESC)")

        # FTS5 virtual table for exact/keyword search over learnings content
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts
            USING fts5(content, content='learnings', content_rowid='id',
                       tokenize='porter unicode61')
        """)
        # Populate FTS from any existing data (content= tables require explicit population)
        db.execute("""
            INSERT OR IGNORE INTO learnings_fts(rowid, content)
            SELECT id, content FROM learnings
            WHERE id NOT IN (SELECT rowid FROM learnings_fts)
        """)
        # Triggers to keep FTS in sync automatically
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS learnings_fts_insert
            AFTER INSERT ON learnings BEGIN
                INSERT INTO learnings_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS learnings_fts_delete
            AFTER DELETE ON learnings BEGIN
                INSERT INTO learnings_fts(learnings_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END
        """)
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS learnings_fts_update
            AFTER UPDATE ON learnings BEGIN
                INSERT INTO learnings_fts(learnings_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
                INSERT INTO learnings_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)
        db.commit()

        db.execute("""
            CREATE TABLE IF NOT EXISTS earned_titles (
                aspect_id  TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.commit()

        db.execute("""
            CREATE TABLE IF NOT EXISTS telemetry_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                task_type TEXT,
                reasoning_mode TEXT,
                model_used TEXT,
                latency_ms REAL,
                success INTEGER,
                performance_mode TEXT
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry_events(ts)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS model_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                model_used TEXT NOT NULL,
                task_type TEXT,
                success INTEGER DEFAULT 0,
                score REAL,
                latency_ms REAL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_model_outcomes_ts ON model_outcomes(ts)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_model_outcomes_model_task ON model_outcomes(model_used, task_type)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS golden_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                task_type TEXT NOT NULL,
                goal_summary TEXT NOT NULL,
                decision_pattern TEXT NOT NULL,
                outcome_score REAL NOT NULL,
                usage_count INTEGER DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_golden_examples_ts ON golden_examples(ts)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_golden_examples_task_score ON golden_examples(task_type, outcome_score)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS route_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                conversation_id TEXT,
                goal TEXT,
                task_type TEXT,
                is_meta_self INTEGER DEFAULT 0,
                has_workspace_signals INTEGER DEFAULT 0,
                decision_action TEXT,
                decision_tool TEXT,
                preflight_ok INTEGER,
                preflight_reason TEXT,
                final_status TEXT,
                parse_failed INTEGER DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_route_telemetry_created_at ON route_telemetry(created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_route_telemetry_cid_id_desc ON route_telemetry(conversation_id, id DESC)")
        db.commit()

    # Optional: add learning_type (Phase 4). Backward compatible; existing rows default to fact.
    try:
        with _conn() as db:
            db.execute("ALTER TABLE learnings ADD COLUMN learning_type TEXT DEFAULT 'fact'")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
    try:
        with _conn() as db:
            db.execute("UPDATE learnings SET learning_type = COALESCE(type, 'fact') WHERE learning_type IS NULL OR learning_type = ''")
            db.commit()
    except Exception:
        pass

    # Optional: study_plans.momentum_score (Phase 7). Store + expose only.
    try:
        with _conn() as db:
            db.execute("ALTER TABLE study_plans ADD COLUMN momentum_score REAL DEFAULT 0")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # Memory quality: learnings confidence, source, content_hash (Section 4)
    for col, spec in [
        ("confidence", "REAL DEFAULT 0.5"),
        ("source", "TEXT DEFAULT ''"),
        ("content_hash", "TEXT DEFAULT ''"),
        ("score", "REAL DEFAULT 1.0"),
    ]:
        try:
            with _conn() as db:
                db.execute(f"ALTER TABLE learnings ADD COLUMN {col} {spec}")
                db.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    # P1-2: index content_hash (column added above; can't be in early CREATE INDEX block)
    try:
        with _conn() as db:
            db.execute("CREATE INDEX IF NOT EXISTS idx_learnings_content_hash ON learnings(content_hash)")
            db.commit()
    except Exception:
        pass
    # Spaced repetition: importance_score (0-1), next_review_at (ISO datetime), and the
    # per-item SM-2 state so review intervals actually accumulate (BL-134): ease factor,
    # last interval (days), and successful-repetition count.
    for col, spec in [
        ("importance_score", "REAL DEFAULT 0.5"),
        ("next_review_at", "TEXT"),
        ("review_ease", "REAL DEFAULT 2.5"),
        ("review_interval_days", "INTEGER DEFAULT 0"),
        ("review_reps", "INTEGER DEFAULT 0"),
    ]:
        try:
            with _conn() as db:
                db.execute(f"ALTER TABLE learnings ADD COLUMN {col} {spec}")
                db.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

    # Optional comma-separated tags (e.g. ui:remember, topic:coding)
    try:
        with _conn() as db:
            db.execute("ALTER TABLE learnings ADD COLUMN tags TEXT DEFAULT ''")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # P1-9: dual-write consistency — mark learnings whose ChromaDB write failed
    try:
        with _conn() as db:
            db.execute("ALTER TABLE learnings ADD COLUMN needs_reindex INTEGER DEFAULT 0")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # Evolution layer: study_plans optional domain_id and linked_capability_event_id
    for col, spec in [
        ("domain_id", "TEXT"),
        ("linked_capability_event_id", "INTEGER"),
    ]:
        try:
            with _conn() as db:
                db.execute(f"ALTER TABLE study_plans ADD COLUMN {col} {spec}")
                db.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

    # Evolution layer: capability tables and seed (Phase 1)
    _migrate_evolution_layer()

    # Missions table (v1.1 — long-running agent tasks)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS missions (
                    id             TEXT PRIMARY KEY,
                    goal           TEXT NOT NULL,
                    plan_json      TEXT NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'pending',
                    current_step   INTEGER NOT NULL DEFAULT 0,
                    results_json   TEXT DEFAULT '[]',
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL,
                    workspace_root TEXT DEFAULT '',
                    allow_write    INTEGER DEFAULT 0,
                    allow_run      INTEGER DEFAULT 0
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status)")
            db.commit()
    except Exception as e:
        logger.warning("missions table migration failed: %s", e)

    # Background tasks table (durable async task status across restarts)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS background_tasks (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT DEFAULT '',
                    goal            TEXT NOT NULL,
                    aspect_id       TEXT DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'queued',
                    priority        INTEGER DEFAULT 0,
                    result          TEXT DEFAULT '',
                    error           TEXT DEFAULT '',
                    created_at      TEXT NOT NULL,
                    started_at      TEXT DEFAULT '',
                    finished_at     TEXT DEFAULT '',
                    updated_at      TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_background_tasks_created ON background_tasks(created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_background_tasks_status ON background_tasks(status)")
            db.commit()
    except Exception as e:
        logger.warning("background_tasks table migration failed: %s", e)

    try:
        with _conn() as db:
            db.execute("ALTER TABLE background_tasks ADD COLUMN kind TEXT DEFAULT 'background'")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    try:
        with _conn() as db:
            db.execute("ALTER TABLE background_tasks ADD COLUMN progress_json TEXT DEFAULT '[]'")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # Repo cognition snapshots — durable multi-repo digests for system-head injection
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS repo_cognition_snapshots (
                    workspace_root     TEXT PRIMARY KEY,
                    label              TEXT DEFAULT '',
                    fingerprint        TEXT DEFAULT '',
                    pack_json          TEXT DEFAULT '{}',
                    pack_markdown      TEXT NOT NULL DEFAULT '',
                    file_manifest_json TEXT DEFAULT '[]',
                    updated_at         TEXT NOT NULL
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_repo_cognition_updated ON repo_cognition_snapshots(updated_at DESC)"
            )
            db.commit()
    except Exception as e:
        logger.warning("repo_cognition_snapshots migration failed: %s", e)

    # Conversation summary memory — prevents context overflow across sessions
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_conversation_summaries_created ON conversation_summaries(created_at DESC)")
            db.commit()
    except Exception as e:
        logger.warning("conversation_summaries table migration failed: %s", e)

    # Multi-session chat storage (conversation list + searchable messages)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id              TEXT PRIMARY KEY,
                    title           TEXT DEFAULT '',
                    aspect_id       TEXT DEFAULT '',
                    dominant_aspect TEXT DEFAULT '',
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    message_count   INTEGER DEFAULT 0
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role            TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    aspect_id       TEXT DEFAULT '',
                    created_at      TEXT NOT NULL,
                    token_count     INTEGER DEFAULT 0,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_conv_msgs_conversation_id ON conversation_messages(conversation_id, created_at)")
            db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_messages_fts
                USING fts5(content, conversation_id UNINDEXED, content='conversation_messages', content_rowid='rowid')
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS conversation_messages_fts_insert
                AFTER INSERT ON conversation_messages BEGIN
                    INSERT INTO conversation_messages_fts(rowid, content, conversation_id) VALUES (new.rowid, new.content, new.conversation_id);
                END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS conversation_messages_fts_delete
                AFTER DELETE ON conversation_messages BEGIN
                    INSERT INTO conversation_messages_fts(conversation_messages_fts, rowid, content, conversation_id)
                    VALUES ('delete', old.rowid, old.content, old.conversation_id);
                END
            """)
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS conversation_messages_fts_update
                AFTER UPDATE ON conversation_messages BEGIN
                    INSERT INTO conversation_messages_fts(conversation_messages_fts, rowid, content, conversation_id)
                    VALUES ('delete', old.rowid, old.content, old.conversation_id);
                    INSERT INTO conversation_messages_fts(rowid, content, conversation_id)
                    VALUES (new.rowid, new.content, new.conversation_id);
                END
            """)
            db.commit()
    except Exception as e:
        logger.warning("conversation tables migration failed: %s", e)

    # Operator journal (Layla v3) — lightweight durable entries (notes, recaps, threads)
    try:
        with _conn() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_journal (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at    TEXT NOT NULL,
                    entry_type    TEXT NOT NULL DEFAULT 'note',
                    content       TEXT NOT NULL,
                    tags          TEXT DEFAULT '',
                    project_id    TEXT DEFAULT '',
                    aspect_id     TEXT DEFAULT '',
                    conversation_id TEXT DEFAULT ''
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_operator_journal_created ON operator_journal(created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_operator_journal_type ON operator_journal(entry_type)")
            db.commit()
    except Exception as e:
        logger.warning("operator_journal migration failed: %s", e)

    # Self-improvement proposals (Layla v3) — operator review queue (no auto-apply)
    try:
        with _conn() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS self_improvement_proposals (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at    TEXT NOT NULL,
                    status        TEXT NOT NULL DEFAULT 'pending',
                    title         TEXT NOT NULL,
                    rationale     TEXT DEFAULT '',
                    risk_level    TEXT DEFAULT 'low',
                    domain        TEXT DEFAULT '',
                    instructions  TEXT DEFAULT ''
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_improvements_created ON self_improvement_proposals(created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_improvements_status ON self_improvement_proposals(status)")
            db.commit()
    except Exception as e:
        logger.warning("self_improvement_proposals migration failed: %s", e)

    # layla_projects — scoped presets (workspace, aspect, skills paths, preamble)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS layla_projects (
                    id               TEXT PRIMARY KEY,
                    name             TEXT NOT NULL DEFAULT '',
                    workspace_root   TEXT DEFAULT '',
                    aspect_default   TEXT DEFAULT '',
                    skill_paths_json TEXT DEFAULT '[]',
                    system_preamble  TEXT DEFAULT '',
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_layla_projects_updated ON layla_projects(updated_at DESC)")
            db.commit()
    except Exception as e:
        logger.warning("layla_projects migration failed: %s", e)

    try:
        with _conn() as db:
            db.execute("ALTER TABLE layla_projects ADD COLUMN cognition_extra_roots TEXT DEFAULT ''")
            db.commit()
    except sqlite3.OperationalError as e:
        el = str(e).lower()
        if "duplicate column" not in el and "no such table" not in el:
            raise

    try:
        with _conn() as db:
            db.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT DEFAULT ''")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            logger.debug("conversations.project_id alter: %s", e)

    # Optional: conversation tags (comma-separated, normalized)
    try:
        with _conn() as db:
            db.execute("ALTER TABLE conversations ADD COLUMN tags TEXT DEFAULT ''")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            logger.debug("conversations.tags alter: %s", e)

    # embedding_id for conversation_summaries — enables retrieval participation
    try:
        with _conn() as db:
            db.execute("ALTER TABLE conversation_summaries ADD COLUMN embedding_id TEXT DEFAULT ''")
            db.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # relationship_memory — meaningful interaction summaries for companion intelligence
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS relationship_memory (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_event   TEXT NOT NULL,
                    timestamp   TEXT NOT NULL,
                    embedding_id TEXT DEFAULT ''
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_memory_timestamp ON relationship_memory(timestamp DESC)")
            db.commit()
    except Exception as e:
        logger.warning("relationship_memory table migration failed: %s", e)

    # timeline_events — personal timeline memory (North Star companion experience)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS timeline_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type   TEXT NOT NULL,
                    content      TEXT NOT NULL,
                    timestamp    TEXT NOT NULL,
                    importance   REAL DEFAULT 0.5,
                    embedding_id TEXT DEFAULT '',
                    project_id   TEXT DEFAULT '',
                    created_at   TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_timeline_events_timestamp ON timeline_events(timestamp DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_timeline_events_importance ON timeline_events(importance DESC)")
            db.commit()
    except Exception as e:
        logger.warning("timeline_events table migration failed: %s", e)

    # user_identity — long-term companion context (verbosity, humor, formality, response length, life narrative)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS user_identity (
                    key       TEXT PRIMARY KEY,
                    snapshot  TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                )
            """)
            db.commit()
    except Exception as e:
        logger.warning("user_identity table migration failed: %s", e)

    # episodes — group timeline events, summaries, reflections into episodic memory
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id           TEXT PRIMARY KEY,
                    summary      TEXT DEFAULT '',
                    started_at   TEXT NOT NULL,
                    ended_at     TEXT,
                    created_at   TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_episodes_started ON episodes(started_at DESC)")
            db.commit()
    except Exception as e:
        logger.warning("episodes table migration failed: %s", e)

    # episode_events — links events to episodes
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS episode_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id   TEXT NOT NULL,
                    event_type   TEXT NOT NULL,
                    event_id     TEXT,
                    source_table TEXT,
                    created_at   TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_episode_events_episode ON episode_events(episode_id)")
            db.commit()
    except Exception as e:
        logger.warning("episode_events table migration failed: %s", e)

    # tool_outcomes — track tool success/failure for reliability
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS tool_outcomes (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name     TEXT NOT NULL,
                    context       TEXT DEFAULT '',
                    success       INTEGER NOT NULL,
                    latency_ms    REAL DEFAULT 0,
                    quality_score REAL DEFAULT 0.5,
                    created_at    TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_tool_outcomes_tool ON tool_outcomes(tool_name)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_tool_outcomes_created ON tool_outcomes(created_at DESC)")
            db.commit()
    except Exception as e:
        logger.warning("tool_outcomes table migration failed: %s", e)

    # goals — long-term goals
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    id           TEXT PRIMARY KEY,
                    title        TEXT NOT NULL,
                    description  TEXT DEFAULT '',
                    status       TEXT DEFAULT 'active',
                    project_id   TEXT DEFAULT '',
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status)")
            db.commit()
    except Exception as e:
        logger.warning("goals table migration failed: %s", e)

    # goal_progress — subgoals and progress tracking
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS goal_progress (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id      TEXT NOT NULL,
                    note         TEXT DEFAULT '',
                    progress_pct REAL DEFAULT 0,
                    created_at   TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_goal_progress_goal ON goal_progress(goal_id)")
            db.commit()
    except Exception as e:
        logger.warning("goal_progress table migration failed: %s", e)

    # rl_preferences — RL feedback loop preference cache (PR #1)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS rl_preferences (
                    tool_name  TEXT PRIMARY KEY,
                    score      REAL,
                    hint       TEXT,
                    updated_at TEXT
                )
            """)
            db.commit()
    except Exception as e:
        logger.warning("rl_preferences table migration failed: %s", e)

    # learnings.aspect_id — optional facet attribution (Echo / per-aspect memory)
    try:
        with _conn() as db:
            db.execute("ALTER TABLE learnings ADD COLUMN aspect_id TEXT DEFAULT ''")
            db.commit()
    except Exception:
        pass
    try:
        with _conn() as db:
            db.execute("CREATE INDEX IF NOT EXISTS idx_learnings_aspect ON learnings(aspect_id)")
            db.commit()
    except Exception:
        pass

    # DEAD TABLE — no production code uses this (removed 2026-05-17)
    # # Codex discovery tracking (videogame-style "new entry" notifications)
    # try:
    #     with _conn() as db:
    #         db.execute("""
    #             CREATE TABLE IF NOT EXISTS codex_discoveries (
    #                 entity_id     TEXT NOT NULL,
    #                 discovered_at TEXT NOT NULL,
    #                 discovery_context TEXT DEFAULT '',
    #                 notified      INTEGER DEFAULT 0,
    #                 PRIMARY KEY(entity_id)
    #             )
    #         """)
    #         db.commit()
    # except Exception:
    #     pass

    # DEAD TABLE — no production code uses this (removed 2026-05-17)
    # # Journal-entity links (connect journal entries to codex entities)
    # try:
    #     with _conn() as db:
    #         db.execute("""
    #             CREATE TABLE IF NOT EXISTS journal_entity_links (
    #                 journal_id INTEGER NOT NULL,
    #                 entity_id  TEXT NOT NULL,
    #                 PRIMARY KEY(journal_id, entity_id)
    #             )
    #         """)
    #         db.commit()
    # except Exception:
    #     pass

    # Learnings archive (faded memories -- moved here instead of hard-deleted)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS learnings_archive (
                    id            INTEGER PRIMARY KEY,
                    content       TEXT NOT NULL,
                    type          TEXT DEFAULT 'fact',
                    created_at    TEXT NOT NULL,
                    archived_at   TEXT NOT NULL,
                    archive_reason TEXT DEFAULT 'confidence_decay',
                    original_confidence REAL DEFAULT 0,
                    tags          TEXT DEFAULT '',
                    aspect_id     TEXT DEFAULT ''
                )
            """)
            db.commit()
    except Exception:
        pass

    # Task queue — cluster distributed work units (Phase 2E)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS task_queue (
                    id          TEXT PRIMARY KEY,
                    type        TEXT NOT NULL,
                    priority    INTEGER DEFAULT 1,
                    status      TEXT DEFAULT 'pending',
                    payload     TEXT DEFAULT '{}',
                    result      TEXT,
                    error       TEXT,
                    source_node TEXT,
                    assigned_to TEXT,
                    timeout_s   INTEGER DEFAULT 300,
                    created_at  TEXT NOT NULL,
                    started_at  TEXT,
                    completed_at TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_priority ON task_queue(priority, created_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_assigned ON task_queue(assigned_to)")
            db.commit()
    except Exception as e:
        logger.warning("task_queue table migration failed: %s", e)

    # Verification queue — learn-and-verify loop (Phase 5B)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS verification_queue (
                    id           TEXT PRIMARY KEY,
                    fact_content TEXT NOT NULL,
                    source       TEXT DEFAULT 'inferred',
                    confidence   REAL DEFAULT 0.5,
                    importance   REAL DEFAULT 0.5,
                    status       TEXT DEFAULT 'pending',
                    ask_count    INTEGER DEFAULT 0,
                    last_asked   TEXT,
                    user_answer  TEXT,
                    created_at   TEXT NOT NULL,
                    resolved_at  TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_verification_queue_status ON verification_queue(status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_verification_queue_importance ON verification_queue(importance DESC)")
            db.commit()
    except Exception as e:
        logger.warning("verification_queue table migration failed: %s", e)

    # ── pending_sync (node sync offline buffer) ──────────────────────────
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS pending_sync (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    type TEXT DEFAULT 'learning',
                    content_hash TEXT,
                    confidence REAL DEFAULT 0.5,
                    source TEXT DEFAULT 'local',
                    tags TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    synced INTEGER DEFAULT 0
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_pending_sync_synced ON pending_sync(synced)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_pending_sync_hash ON pending_sync(content_hash)")
            db.commit()
    except Exception as e:
        logger.warning("pending_sync table migration failed: %s", e)

    # Clean up orphaned FK references (P0-6: must run BEFORE PRAGMA foreign_keys=ON)
    _cleanup_orphaned_records()

    # Migrate learnings.json
    _migrate_learnings_json()

    # ── Set baseline version ──
    # All existing migration code above has run; stamp version 1 so future
    # migrations can gate on `if version < N`.
    try:
        with _conn() as db:
            current = _get_schema_version(db)
            if current < 1:
                _set_schema_version(db, 1)
                logger.info("Schema version set to 1 (baseline)")
    except Exception as e:
        logger.debug("schema_version update failed: %s", e)

    if first_run:
        logger.info("Initialized new Layla workspace")


# BL-028: the self-contained data-backfill migrations were split into data_migrations.py.
# Re-exported here so _migrate_impl's calls (and any migrations.X callers) keep working.
from layla.memory.data_migrations import (  # noqa: E402
    _cleanup_orphaned_records,
    _migrate_evolution_layer,
    _migrate_learnings_json,
)

__all__ = ["migrate", "_MIGRATED", "_MIGRATION_LOCK"]
