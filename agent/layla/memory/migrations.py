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
    # Spaced repetition: importance_score (0-1), next_review_at (ISO datetime)
    for col, spec in [
        ("importance_score", "REAL DEFAULT 0.5"),
        ("next_review_at", "TEXT"),
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

    # Codex discovery tracking (videogame-style "new entry" notifications)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS codex_discoveries (
                    entity_id     TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    discovery_context TEXT DEFAULT '',
                    notified      INTEGER DEFAULT 0,
                    PRIMARY KEY(entity_id)
                )
            """)
            db.commit()
    except Exception:
        pass

    # Journal-entity links (connect journal entries to codex entities)
    try:
        with _conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS journal_entity_links (
                    journal_id INTEGER NOT NULL,
                    entity_id  TEXT NOT NULL,
                    PRIMARY KEY(journal_id, entity_id)
                )
            """)
            db.commit()
    except Exception:
        pass

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

    # Migrate learnings.json
    _migrate_learnings_json()

    if first_run:
        logger.info("Initialized new Layla workspace")


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


__all__ = ["migrate", "_MIGRATED", "_MIGRATION_LOCK"]
