"""
SQLite persistent memory for Layla.

Tables:
  learnings        — replaces learnings.json for structured persistence
  study_plans      — topics Layla is studying
  wakeup_log       — session greeting history
  audit            — tool execution audit trail
  aspect_memories  — per-aspect long-term observations
"""
import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from layla.time_utils import utcnow

logger = logging.getLogger("layla")

_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "layla.db"

# Migration guard: run _migrate_impl at most once per process.
_MIGRATED = False
import threading as _threading  # noqa: E402

_MIGRATION_LOCK = _threading.Lock()


def _conn() -> sqlite3.Connection:
    """
    Return an optimized SQLite connection.
    - WAL mode: readers don't block writers, writers don't block readers.
    - SYNCHRONOUS=NORMAL: safe + fast (still durable on power failure with WAL).
    - CACHE_SIZE=-32000: 32 MB page cache per connection.
    - TEMP_STORE=MEMORY: temp tables in RAM.
    - MMAP_SIZE=256MB: memory-mapped I/O for read-heavy paths.
    """
    c = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-32000")   # 32 MB
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA mmap_size=268435456") # 256 MB
    c.execute("PRAGMA busy_timeout=5000")   # 5 s wait on SQLITE_BUSY
    return c


def migrate() -> None:
    """Create tables and run migrations. Safe to call repeatedly; runs at most once per process."""
    global _MIGRATED
    if _MIGRATED:
        return
    with _MIGRATION_LOCK:
        if _MIGRATED:
            return
        try:
            _migrate_impl()
            _MIGRATED = True
        except Exception as e:
            logger.warning("DB migrate failed: %s", e)


def _migrate_impl() -> None:
    first_run = not _DB_PATH.exists()
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

    # Migrate learnings.json
    _migrate_learnings_json()

    if first_run:
        logger.info("Initialized new Layla workspace")


def _migrate_learnings_json() -> None:
    learnings_json = Path(__file__).resolve().parent.parent.parent.parent / "learnings.json"
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
            ("woodworking", "Woodworking", "Joint strength, use cases, techniques"),
            ("joinery", "Joinery", "Joint types and applications"),
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


# ── learnings ──────────────────────────────────────────────────────────────

def save_learning(
    content: str,
    kind: str = "fact",
    embedding_id: str = "",
    confidence: float = 0.5,
    source: str = "",
    score: float = 1.0,
) -> int:
    """Save a learning. Uses content_hash for dedup. confidence: 0.9 study, 0.7 LLM, 0.4 heuristic.
    Hook: learning quality filter rejects short/uncertain entries; long content summarized before storing."""
    migrate()
    try:
        from services.learning_filter import filter_learning
        pass_filter, filtered, reason = filter_learning(content)
        if not pass_filter:
            try:
                from services.observability import log_learning_skipped
                log_learning_skipped(reason=reason or "filter_rejected")
            except Exception:
                pass
            return -1
        content = filtered or content
    except Exception:
        pass
    try:
        from layla.memory.distill import passes_learning_quality_gate

        ok_q, qscore = passes_learning_quality_gate(content)
        if not ok_q:
            try:
                from services.observability import log_learning_skipped

                log_learning_skipped(reason=f"quality_gate:{qscore:.2f}")
            except Exception:
                pass
            return -1
    except Exception:
        pass
    learning_type = kind if kind in ("fact", "preference", "strategy", "identity") else "fact"
    content_hash = hashlib.sha1(content.encode("utf-8", errors="replace")).hexdigest()
    score = max(0.0, min(1.0, float(score)))
    with _conn() as db:
        try:
            has_hash = any(r[1] == "content_hash" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_hash = False
        if has_hash:
            row = db.execute("SELECT id FROM learnings WHERE content_hash=? AND content_hash!=''", (content_hash,)).fetchone()
            if row:
                return row[0]
        try:
            cur = db.execute(
                """INSERT INTO learnings (content, type, created_at, embedding_id, learning_type, confidence, source, content_hash, score)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (content, learning_type, utcnow().isoformat(), embedding_id, learning_type, confidence, source, content_hash, score),
            )
        except sqlite3.OperationalError:
            cur = db.execute(
                "INSERT INTO learnings (content, type, created_at, embedding_id, learning_type) VALUES (?,?,?,?,?)",
                (content, learning_type, utcnow().isoformat(), embedding_id, learning_type),
            )
        db.commit()
        rid = cur.lastrowid
        try:
            from services.observability import log_learning_saved
            log_learning_saved(content_preview=content[:80], source=source or "db")
        except Exception:
            pass
        # Section 5: graph expansion in background (daemon thread, non-blocking)
        if rid and content:
            try:
                import threading
                def _expand():
                    try:
                        from services.graph_learning import expand_graph_from_learning
                        expand_graph_from_learning(content)
                    except Exception:
                        pass
                t = threading.Thread(target=_expand, daemon=True, name="graph-expand")
                t.start()
            except Exception:
                pass
        return rid


_ASPECT_LEARNING_PREFERENCE = {"echo": "preference", "morrigan": "strategy", "nyx": "fact"}


def count_learnings() -> int:
    """Return total number of stored learnings quickly."""
    migrate()
    with _conn() as db:
        row = db.execute("SELECT COUNT(*) AS c FROM learnings").fetchone()
        return int(row["c"]) if row and row["c"] is not None else 0


def get_recent_learnings(n: int = 30, aspect_id: str | None = None, min_score: float | None = None) -> list[dict]:
    """Recent learnings. If aspect_id given, prefer learning_type: Echo->preference, Morrigan->strategy, Nyx->fact."""
    migrate()
    with _conn() as db:
        try:
            has_lt = any(r[1] == "learning_type" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
            has_conf = any(r[1] == "confidence" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_lt = False
            has_conf = False
        sel = "id, content, type, created_at, embedding_id"
        if has_conf:
            sel += ", confidence"
        has_score = any(r[1] == "score" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        if has_score:
            sel += ", score"
        score_filter = ""
        args: list = []
        if has_score and min_score is not None:
            score_filter = " WHERE COALESCE(score, 1.0) >= ?"
            args.append(float(min_score))
        if not has_lt or not aspect_id:
            rows = db.execute(f"SELECT {sel} FROM learnings{score_filter} ORDER BY id DESC LIMIT ?", tuple(args + [n])).fetchall()
        else:
            pref = _ASPECT_LEARNING_PREFERENCE.get(aspect_id.lower(), "fact")
            sel_lt = sel + ", learning_type" if has_lt else sel
            rows = db.execute(
                f"""SELECT {sel_lt} FROM learnings
                   {score_filter}
                   ORDER BY CASE WHEN learning_type = ? THEN 0 ELSE 1 END, id DESC LIMIT ?""",
                tuple(args + [pref, n]),
            ).fetchall()
        result = [dict(r) for r in reversed(rows)]
        for r in result:
            if "learning_type" not in r and "type" in r:
                r["learning_type"] = r["type"]
            if has_conf:
                r["adjusted_confidence"] = _apply_confidence_decay(r.get("confidence"), r.get("created_at", ""))
        return result


def _apply_confidence_decay(confidence: float, created_at: str) -> float:
    """Age-based decay: adjusted = confidence * exp(-age_days/180)."""
    import math
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        from datetime import timezone
        dt_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        age_days = (utcnow() - dt_utc).total_seconds() / 86400.0
    except Exception:
        age_days = 0.0
    conf = float(confidence) if confidence is not None else 0.5
    return conf * math.exp(-age_days / 180.0)


def search_learnings_fts(query: str, n: int = 20) -> list[dict]:
    """
    FTS5 full-text search over learnings using Porter stemmer + unicode tokenization.
    Falls back to LIKE search if FTS5 table is missing.
    Returns list of matching learning dicts ordered by relevance (BM25 rank).
    Applies age-based confidence decay for retrieval scoring.
    """
    migrate()
    with _conn() as db:
        try:
            has_conf = any(r[1] == "confidence" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
            sel = "l.id, l.content, l.type, l.created_at"
            if has_conf:
                sel += ", l.confidence"
            rows = db.execute(
                f"""SELECT {sel}
                   FROM learnings l
                   JOIN learnings_fts f ON l.id = f.rowid
                   WHERE learnings_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, n),
            ).fetchall()
            result = [dict(r) for r in rows]
            for r in result:
                conf = r.get("confidence")
                created = r.get("created_at", "")
                r["adjusted_confidence"] = _apply_confidence_decay(conf, created)
            return result
        except Exception:
            # Fallback: simple LIKE search
            try:
                has_conf = any(r[1] == "confidence" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
                sel = "id, content, type, created_at"
                if has_conf:
                    sel += ", confidence"
                rows = db.execute(
                    f"SELECT {sel} FROM learnings WHERE content LIKE ? LIMIT ?",
                    (f"%{query}%", n),
                ).fetchall()
                result = [dict(r) for r in rows]
                for r in result:
                    r["adjusted_confidence"] = _apply_confidence_decay(r.get("confidence"), r.get("created_at", ""))
                return result
            except Exception:
                return []


def get_learnings_by_embedding_ids(embedding_ids: list[str]) -> dict[str, dict]:
    """Look up confidence and created_at for learnings by embedding_id. Used for retrieval scoring."""
    if not embedding_ids:
        return {}
    migrate()
    result = {}
    with _conn() as db:
        try:
            has_conf = any(r[1] == "confidence" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_conf = False
        sel = "embedding_id, created_at"
        if has_conf:
            sel += ", confidence"
        placeholders = ",".join("?" * len(embedding_ids))
        rows = db.execute(
            f"SELECT {sel} FROM learnings WHERE embedding_id IN ({placeholders}) AND embedding_id != ''",
            tuple(embedding_ids),
        ).fetchall()
        for r in rows:
            rid = r["embedding_id"]
            conf = r.get("confidence")
            created = r.get("created_at", "")
            result[rid] = {
                "confidence": float(conf) if conf is not None else 0.5,
                "created_at": created,
                "adjusted_confidence": _apply_confidence_decay(conf, created),
            }
    return result


def delete_learnings_by_id(ids: list) -> None:
    """Remove learnings by id list. Used by memory distillation."""
    if not ids:
        return
    migrate()
    placeholders = ",".join("?" * len(ids))
    with _conn() as db:
        db.execute(f"DELETE FROM learnings WHERE id IN ({placeholders})", tuple(ids))
        db.commit()


def get_learnings_due_for_review(limit: int = 10) -> list[dict]:
    """
    Return learnings due for spaced repetition review.
    next_review_at <= now or NULL; ordered by importance_score then created_at.
    """
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        try:
            has_col = any(r[1] == "next_review_at" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_col = False
        if not has_col:
            return []
        rows = db.execute(
            """SELECT id, content, type, created_at, importance_score, next_review_at
               FROM learnings
               WHERE next_review_at IS NULL OR next_review_at <= ?
               ORDER BY COALESCE(importance_score, 0.5) DESC, created_at ASC
               LIMIT ?""",
            (now, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def schedule_next_review(learning_id: int, interval_hours: float = 24.0) -> None:
    """Schedule next review for a learning. Uses simple interval (FSRS-style would need more params)."""
    migrate()
    from datetime import datetime, timedelta
    try:
        next_at = (datetime.utcnow() + timedelta(hours=interval_hours)).isoformat() + "Z"
        with _conn() as db:
            db.execute("UPDATE learnings SET next_review_at = ? WHERE id = ?", (next_at, learning_id))
            db.commit()
    except Exception as e:
        logger.warning("schedule_next_review failed: %s", e)


def set_learning_importance(learning_id: int, score: float) -> None:
    """Set importance_score (0-1) for a learning. Higher = more likely to persist."""
    migrate()
    score = max(0.0, min(1.0, score))
    try:
        with _conn() as db:
            has_col = any(r[1] == "importance_score" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
            if has_col:
                db.execute("UPDATE learnings SET importance_score = ? WHERE id = ?", (score, learning_id))
                db.commit()
    except Exception as e:
        logger.warning("set_learning_importance failed: %s", e)


# ── study plans ────────────────────────────────────────────────────────────

def save_study_plan(plan_id: str, topic: str, status: str = "active", domain_id: str | None = None) -> None:
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        try:
            db.execute(
                """INSERT INTO study_plans (id, topic, status, progress, created_at, domain_id)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status, domain_id=COALESCE(excluded.domain_id, study_plans.domain_id)""",
                (plan_id, topic, status, "[]", now, domain_id),
            )
        except sqlite3.OperationalError:
            db.execute(
                """INSERT INTO study_plans (id, topic, status, progress, created_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status""",
                (plan_id, topic, status, "[]", now),
            )
        db.commit()


def get_active_study_plans() -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM study_plans WHERE status='active'"
        ).fetchall()
    return [dict(r) for r in rows]


def get_plan_by_topic(topic: str) -> dict | None:
    """Return the active study plan with this topic (case-insensitive), or None."""
    if not (topic or "").strip():
        return None
    topic_clean = topic.strip().lower()
    for p in get_active_study_plans():
        if (p.get("topic") or "").strip().lower() == topic_clean:
            return p
    return None


def update_study_progress(plan_id: str, note: str) -> None:
    migrate()
    with _conn() as db:
        row = db.execute("SELECT progress FROM study_plans WHERE id=?", (plan_id,)).fetchone()
        if row:
            progress = json.loads(row["progress"] or "[]")
            progress.append({"note": note, "at": utcnow().isoformat()})
            db.execute(
                "UPDATE study_plans SET progress=?, last_studied=? WHERE id=?",
                (json.dumps(progress), utcnow().isoformat(), plan_id),
            )
            db.commit()


# ── wakeup log ─────────────────────────────────────────────────────────────

def log_wakeup(greeting: str, notes: str = "") -> None:
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO wakeup_log (timestamp, greeting, notes) VALUES (?,?,?)",
            (utcnow().isoformat(), greeting, notes),
        )
        db.commit()


def get_last_wakeup() -> dict | None:
    migrate()
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM wakeup_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ── audit ─────────────────────────────────────────────────────────────────

def log_audit(tool: str, args_summary: str, approved_by: str, result_ok: bool) -> None:
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO audit (timestamp, tool, args_summary, approved_by, result_ok) VALUES (?,?,?,?,?)",
            (utcnow().isoformat(), tool, args_summary[:200], approved_by, int(result_ok)),
        )
        db.commit()


def get_recent_audit(n: int = 10) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── conversation summaries (context overflow prevention) ────────────────────

def add_conversation_summary(summary: str) -> None:
    """Persist a conversation summary for long-term context retention. Stores embedding for retrieval."""
    if not (summary or "").strip():
        return
    migrate()
    summary_text = summary.strip()[:8000]
    embedding_id = ""
    try:
        from layla.memory.vector_store import add_vector, embed
        vec = embed(summary_text)
        embedding_id = add_vector(vec, {"content": summary_text, "type": "conversation_summary"})
    except Exception:
        pass
    with _conn() as db:
        db.execute(
            "INSERT INTO conversation_summaries (summary, created_at, embedding_id) VALUES (?,?,?)",
            (summary_text, utcnow().isoformat(), embedding_id),
        )
        db.commit()


def get_recent_conversation_summaries(n: int = 5) -> list[dict]:
    """Return the n most recent conversation summaries (newest first)."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT id, summary, created_at, embedding_id FROM conversation_summaries ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── relationship memory (companion intelligence) ────────────────────────────

def add_relationship_memory(user_event: str, embedding_id: str = "") -> None:
    """Store a meaningful interaction summary for companion context. Optionally embeds for retrieval."""
    if not (user_event or "").strip():
        return
    migrate()
    event_text = (user_event or "").strip()[:4000]
    eid = (embedding_id or "").strip()
    if not eid:
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(event_text)
            eid = add_vector(vec, {"content": event_text, "type": "relationship_memory"})
        except Exception:
            pass
    with _conn() as db:
        db.execute(
            "INSERT INTO relationship_memory (user_event, timestamp, embedding_id) VALUES (?,?,?)",
            (event_text, utcnow().isoformat(), eid),
        )
        db.commit()


def get_recent_relationship_memories(n: int = 5) -> list[dict]:
    """Return the n most recent relationship memories (newest first)."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT id, user_event, timestamp, embedding_id FROM relationship_memory ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── timeline events (personal timeline memory) ────────────────────────────────

TIMELINE_EVENT_TYPES = ("life_event", "project_milestone", "goal", "blocker", "conversation_summary")


def add_timeline_event(
    content: str,
    event_type: str = "life_event",
    importance: float = 0.5,
    project_id: str = "",
    embedding_id: str = "",
) -> int:
    """Store a timeline event for personal memory. event_type: life_event|project_milestone|goal|blocker|conversation_summary."""
    if not (content or "").strip():
        return -1
    migrate()
    event_type = event_type if event_type in TIMELINE_EVENT_TYPES else "life_event"
    content_text = (content or "").strip()[:4000]
    imp = max(0.0, min(1.0, float(importance)))
    eid = (embedding_id or "").strip()
    if not eid:
        try:
            from layla.memory.vector_store import add_vector, embed
            vec = embed(content_text)
            eid = add_vector(vec, {"content": content_text, "type": "timeline_event", "event_type": event_type})
        except Exception:
            pass
    now = utcnow().isoformat()
    with _conn() as db:
        cur = db.execute(
            """INSERT INTO timeline_events (event_type, content, timestamp, importance, embedding_id, project_id, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (event_type, content_text, now, imp, eid, (project_id or "").strip(), now),
        )
        db.commit()
        return cur.lastrowid or -1


def get_recent_timeline_events(n: int = 10, min_importance: float = 0.0) -> list[dict]:
    """Return the n most recent timeline events (newest first), optionally filtered by importance."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            """SELECT id, event_type, content, timestamp, importance, project_id FROM timeline_events
               WHERE importance >= ? ORDER BY timestamp DESC LIMIT ?""",
            (min_importance, n),
        ).fetchall()
    return [dict(r) for r in rows]


# ── user identity (long-term companion context) ───────────────────────────────

USER_IDENTITY_KEYS = ("verbosity", "humor_tolerance", "formality", "response_length", "life_narrative_summary")


def get_user_identity(key: str) -> dict | None:
    """Return user identity snapshot for a key. Keys: verbosity, humor_tolerance, formality, response_length, life_narrative_summary."""
    if not (key or "").strip():
        return None
    migrate()
    with _conn() as db:
        row = db.execute("SELECT key, snapshot, updated_at FROM user_identity WHERE key=?", (key.strip(),)).fetchone()
    return dict(row) if row else None


def get_all_user_identity() -> dict[str, str]:
    """Return all user identity key-value pairs for companion context."""
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT key, snapshot FROM user_identity").fetchall()
    return {r["key"]: (r["snapshot"] or "").strip() for r in rows if r.get("key")}


def set_user_identity(key: str, snapshot: str) -> None:
    """Set user identity snapshot. Keys: verbosity, humor_tolerance, formality, response_length, life_narrative_summary."""
    if not (key or "").strip():
        return
    migrate()
    now = utcnow().isoformat()
    key = key.strip()
    snapshot = (snapshot or "").strip()[:4000]
    with _conn() as db:
        db.execute(
            """INSERT INTO user_identity (key, snapshot, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET snapshot=excluded.snapshot, updated_at=excluded.updated_at""",
            (key, snapshot, now),
        )
        db.commit()


# ── episodes (episodic memory) ──────────────────────────────────────────────

def create_episode(summary: str = "") -> str:
    """Create a new episode. Returns episode_id."""
    import uuid
    migrate()
    now = utcnow().isoformat()
    eid = str(uuid.uuid4())[:16]
    with _conn() as db:
        db.execute(
            "INSERT INTO episodes (id, summary, started_at, ended_at, created_at) VALUES (?,?,?,?,?)",
            (eid, (summary or "")[:500], now, None, now),
        )
        db.commit()
    return eid


def add_episode_event(episode_id: str, event_type: str, event_id: str = "", source_table: str = "") -> None:
    """Link an event to an episode."""
    if not episode_id:
        return
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "INSERT INTO episode_events (episode_id, event_type, event_id, source_table, created_at) VALUES (?,?,?,?,?)",
            (episode_id, event_type or "unknown", (event_id or "")[:64], (source_table or "")[:32], now),
        )
        db.commit()


def get_recent_episodes(n: int = 5) -> list[dict]:
    """Return the n most recent episodes."""
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT id, summary, started_at, ended_at FROM episodes ORDER BY started_at DESC LIMIT ?", (n,)).fetchall()
    return [dict(r) for r in rows]


# ── tool outcomes (tool reliability learning) ─────────────────────────────────

def record_tool_outcome(tool_name: str, success: bool, context: str = "", latency_ms: float = 0, quality_score: float = 0.5) -> None:
    """Record a tool outcome for reliability learning."""
    if not (tool_name or "").strip():
        return
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at) VALUES (?,?,?,?,?,?)""",
            (tool_name.strip(), (context or "")[:500], 1 if success else 0, max(0, float(latency_ms)), max(0, min(1, float(quality_score))), now),
        )
        db.commit()


def get_tool_reliability(tool_name: str | None = None, n: int = 100) -> dict[str, dict]:
    """Return reliability stats per tool: {tool_name: {success_rate, avg_latency, avg_quality, count}}."""
    migrate()
    with _conn() as db:
        if tool_name:
            rows = db.execute(
                """SELECT tool_name, AVG(success) as success_rate, AVG(latency_ms) as avg_latency, AVG(quality_score) as avg_quality, COUNT(*) as count
                   FROM tool_outcomes WHERE tool_name=? GROUP BY tool_name""",
                (tool_name,),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT tool_name, AVG(success) as success_rate, AVG(latency_ms) as avg_latency, AVG(quality_score) as avg_quality, COUNT(*) as count
                   FROM tool_outcomes GROUP BY tool_name""",
                (),
            ).fetchall()
    result = {}
    for r in rows:
        name = r["tool_name"]
        result[name] = {
            "success_rate": float(r["success_rate"] or 0),
            "avg_latency": float(r["avg_latency"] or 0),
            "avg_quality": float(r["avg_quality"] or 0.5),
            "count": int(r["count"] or 0),
        }
    return result


# ── goals (goal engine) ─────────────────────────────────────────────────────

def add_goal(title: str, description: str = "", project_id: str = "") -> str:
    """Add a long-term goal. Returns goal_id."""
    import uuid
    migrate()
    now = utcnow().isoformat()
    gid = str(uuid.uuid4())[:16]
    with _conn() as db:
        db.execute(
            "INSERT INTO goals (id, title, description, status, project_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (gid, (title or "")[:200], (description or "")[:1000], "active", (project_id or "").strip(), now, now),
        )
        db.commit()
    return gid


def add_goal_progress(goal_id: str, note: str = "", progress_pct: float = 0) -> None:
    """Record progress on a goal."""
    if not goal_id:
        return
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "INSERT INTO goal_progress (goal_id, note, progress_pct, created_at) VALUES (?,?,?,?)",
            (goal_id, (note or "")[:500], max(0, min(100, float(progress_pct))), now),
        )
        db.execute("UPDATE goals SET updated_at=? WHERE id=?", (now, goal_id))
        db.commit()


def get_active_goals(project_id: str = "") -> list[dict]:
    """Return active goals, optionally filtered by project."""
    migrate()
    with _conn() as db:
        if project_id:
            rows = db.execute("SELECT * FROM goals WHERE status='active' AND (project_id=? OR project_id='') ORDER BY updated_at DESC", (project_id,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM goals WHERE status='active' ORDER BY updated_at DESC LIMIT 20").fetchall()
    return [dict(r) for r in rows]


# ── aspect memories ────────────────────────────────────────────────────────

def save_aspect_memory(aspect_id: str, content: str) -> None:
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO aspect_memories (aspect_id, content, created_at) VALUES (?,?,?)",
            (aspect_id, content, utcnow().isoformat()),
        )
        db.commit()


def get_aspect_memories(aspect_id: str, n: int = 10) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM aspect_memories WHERE aspect_id=? ORDER BY id DESC LIMIT ?",
            (aspect_id, n),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── earned titles ──────────────────────────────────────────────────────────

def save_earned_title(aspect_id: str, title: str) -> None:
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO earned_titles (aspect_id, title, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(aspect_id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at",
            (aspect_id, title, utcnow().isoformat()),
        )
        db.commit()


def get_earned_title(aspect_id: str) -> str | None:
    migrate()
    with _conn() as db:
        row = db.execute("SELECT title FROM earned_titles WHERE aspect_id=?", (aspect_id,)).fetchone()
    return row["title"] if row else None


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


# ── mission chains (evolution layer) ───────────────────────────────────────

def create_mission_chain(
    chain_id: str,
    mission_type: str,
    goal_summary: str,
    parent_mission_id: str | None = None,
    capability_domains: list[str] | None = None,
) -> None:
    migrate()
    now = utcnow().isoformat()
    domains_json = json.dumps(capability_domains or []) if capability_domains else "[]"
    with _conn() as db:
        db.execute(
            """INSERT INTO mission_chains (id, parent_mission_id, mission_type, goal_summary, status, capability_domains, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (chain_id, parent_mission_id or "", mission_type, goal_summary, "pending", domains_json, now),
        )
        db.commit()


def get_pending_mission_chains() -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute("SELECT * FROM mission_chains WHERE status='pending' ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def complete_mission_chain(chain_id: str, outcome_summary: str) -> None:
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "UPDATE mission_chains SET status='completed', outcome_summary=?, completed_at=? WHERE id=?",
            (outcome_summary, now, chain_id),
        )
        db.commit()


# ── missions (v1.1 — long-running agent tasks) ────────────────────────────────

def save_mission(mission: dict) -> None:
    """Persist a mission to the missions table."""
    migrate()
    now = utcnow().isoformat()
    mission_id = mission.get("id", "")
    goal = mission.get("goal", "")
    plan = mission.get("plan") or []
    status = mission.get("status", "pending")
    current_step = int(mission.get("current_step", 0))
    results = mission.get("results") or []
    workspace_root = mission.get("workspace_root", "")
    allow_write = 1 if mission.get("allow_write") else 0
    allow_run = 1 if mission.get("allow_run") else 0
    plan_json = json.dumps(plan)
    results_json = json.dumps(results)
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO missions
               (id, goal, plan_json, status, current_step, results_json, created_at, updated_at,
                workspace_root, allow_write, allow_run)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mission_id,
                goal,
                plan_json,
                status,
                current_step,
                results_json,
                mission.get("created_at", now),
                mission.get("updated_at", now),
                workspace_root,
                allow_write,
                allow_run,
            ),
        )
        db.commit()


def get_mission(mission_id: str) -> dict | None:
    """Fetch a mission by id."""
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
    if not row:
        return None
    try:
        plan = json.loads(row["plan_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        plan = []
    try:
        results = json.loads(row["results_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        results = []
    return {
        "id": row["id"],
        "goal": row["goal"],
        "plan": plan,
        "status": row["status"],
        "current_step": int(row["current_step"] or 0),
        "results": results,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "workspace_root": row["workspace_root"] or "",
        "allow_write": bool(row["allow_write"]),
        "allow_run": bool(row["allow_run"]),
    }


def update_mission_status(mission_id: str, status: str) -> None:
    """Update mission status."""
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            "UPDATE missions SET status=?, updated_at=? WHERE id=?",
            (status, now, mission_id),
        )
        db.commit()


def update_mission_progress(
    mission_id: str,
    status: str | None = None,
    current_step: int | None = None,
    results: list | None = None,
) -> None:
    """Update mission progress: status, current_step, results."""
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        if status is not None:
            db.execute("UPDATE missions SET status=?, updated_at=? WHERE id=?", (status, now, mission_id))
        if current_step is not None:
            db.execute("UPDATE missions SET current_step=?, updated_at=? WHERE id=?", (current_step, now, mission_id))
        if results is not None:
            results_json = json.dumps(results)
            db.execute("UPDATE missions SET results_json=?, updated_at=? WHERE id=?", (results_json, now, mission_id))
        db.commit()


def get_active_missions(limit: int = 5) -> list[dict]:
    """Fetch missions with status running or pending, for mission_worker."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT id FROM missions WHERE status IN ('running','pending') ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for row in rows:
        m = get_mission(row["id"])
        if m:
            out.append(m)
    return out


def get_missions(limit: int = 50, status_filter: str | None = None) -> list[dict]:
    """Fetch missions for listing; optionally filter by status."""
    migrate()
    with _conn() as db:
        if status_filter:
            rows = db.execute(
                "SELECT id FROM missions WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status_filter, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id FROM missions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    out = []
    for row in rows:
        m = get_mission(row["id"])
        if m:
            out.append(m)
    return out


def get_project_context() -> dict:
    """Return current project context: project_name, domains (list), key_files (list), goals, progress, blockers, last_discussed."""
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM project_context WHERE id=1").fetchone()
    if not row:
        return {
            "project_name": "", "domains": [], "key_files": [], "goals": "", "lifecycle_stage": "",
            "progress": "", "blockers": "", "last_discussed": "", "updated_at": "",
        }
    try:
        domains = json.loads(row["domains"] or "[]")
    except (json.JSONDecodeError, TypeError):
        domains = []
    try:
        key_files = json.loads(row["key_files"] or "[]")
    except (json.JSONDecodeError, TypeError):
        key_files = []
    r = dict(row)
    return {
        "project_name": r.get("project_name") or "",
        "domains": domains,
        "key_files": key_files,
        "goals": r.get("goals") or "",
        "lifecycle_stage": (r.get("lifecycle_stage") or "").strip() or "",
        "progress": (r.get("progress") or "").strip() or "",
        "blockers": (r.get("blockers") or "").strip() or "",
        "last_discussed": (r.get("last_discussed") or "").strip() or "",
        "updated_at": r.get("updated_at") or "",
    }


PROJECT_LIFECYCLE_STAGES = ("idea", "planning", "prototype", "iteration", "execution", "reflection")


def set_project_context(
    project_name: str = "",
    domains: list[str] | None = None,
    key_files: list[str] | None = None,
    goals: str = "",
    lifecycle_stage: str = "",
    progress: str = "",
    blockers: str = "",
    last_discussed: str = "",
) -> None:
    """Update project context. lifecycle_stage: idea|planning|prototype|iteration|execution|reflection (North Star §3)."""
    migrate()
    now = utcnow().isoformat()
    cur = get_project_context()
    if project_name:
        cur["project_name"] = project_name
    if domains is not None:
        cur["domains"] = domains
    if key_files is not None:
        cur["key_files"] = key_files
    if goals:
        cur["goals"] = goals
    if lifecycle_stage and lifecycle_stage.strip().lower() in PROJECT_LIFECYCLE_STAGES:
        cur["lifecycle_stage"] = lifecycle_stage.strip().lower()
    if progress:
        cur["progress"] = progress.strip()
    if blockers:
        cur["blockers"] = blockers.strip()
    if last_discussed:
        cur["last_discussed"] = last_discussed.strip()
    cols = ["project_name", "domains", "key_files", "goals", "lifecycle_stage", "progress", "blockers", "last_discussed", "updated_at"]
    vals = (
        cur["project_name"], json.dumps(cur["domains"]), json.dumps(cur["key_files"]), cur["goals"],
        cur.get("lifecycle_stage", ""), cur.get("progress", ""), cur.get("blockers", ""), cur.get("last_discussed", ""), now,
    )
    with _conn() as db:
        try:
            placeholders = ", ".join(f"{c}=?" for c in cols)
            db.execute(f"UPDATE project_context SET {placeholders} WHERE id=1", vals)
        except sqlite3.OperationalError:
            # Fallback if new columns not yet migrated
            db.execute(
                """UPDATE project_context SET project_name=?, domains=?, key_files=?, goals=?, lifecycle_stage=?, updated_at=? WHERE id=1""",
                (cur["project_name"], json.dumps(cur["domains"]), json.dumps(cur["key_files"]), cur["goals"], cur.get("lifecycle_stage", ""), now),
            )
        db.commit()


def log_telemetry_event(
    task_type: str | None,
    reasoning_mode: str | None,
    model_used: str | None,
    latency_ms: float,
    success: int,
    performance_mode: str | None,
) -> None:
    """Append one local telemetry row (privacy-safe; no external calls)."""
    migrate()
    ts = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """
            INSERT INTO telemetry_events (ts, task_type, reasoning_mode, model_used, latency_ms, success, performance_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, task_type, reasoning_mode, model_used, float(latency_ms), int(success), performance_mode),
        )
        db.commit()


def get_recent_telemetry_events(n: int = 50) -> list[dict]:
    """Return most recent telemetry rows as dicts (id, ts, task_type, ...)."""
    migrate()
    lim = max(1, min(int(n), 500))
    with _conn() as db:
        cur = db.execute(
            """
            SELECT id, ts, task_type, reasoning_mode, model_used, latency_ms, success, performance_mode
            FROM telemetry_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (lim,),
        )
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        out.append({
            "id": r["id"],
            "ts": r["ts"],
            "task_type": r["task_type"],
            "reasoning_mode": r["reasoning_mode"],
            "model_used": r["model_used"],
            "latency_ms": r["latency_ms"],
            "success": r["success"],
            "performance_mode": r["performance_mode"],
        })
    return out
