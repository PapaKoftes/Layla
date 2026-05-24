# 02 -- Memory & Knowledge Subsystem

> Design document for `agent/layla/memory/`.
> Covers architecture, schema, data flow, vector stores, thread safety,
> migrations, retention, and per-module stability assessment.
>
> Last updated: 2026-05-24

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Flow](#2-data-flow)
3. [Retention & Cleanup](#3-retention--cleanup)
4. [Vector Store](#4-vector-store)
5. [Thread Safety](#5-thread-safety)
6. [Migration System](#6-migration-system)
7. [Known Issues](#7-known-issues)
8. [Every Table -- Complete Schema Reference](#8-every-table----complete-schema-reference)
9. [Stability Assessment](#9-stability-assessment)

---

## 1. Architecture Overview

### 1.1 Storage Engines

The memory subsystem uses three distinct storage engines:

| Engine | Purpose | Location |
|--------|---------|----------|
| **SQLite** (WAL mode) | Structured data, relations, telemetry, plans, tasks | `<LAYLA_DATA_DIR>/layla.db` or repo root `layla.db` |
| **ChromaDB** (PersistentClient) | Vector embeddings for learnings + knowledge docs | `agent/layla/memory/chroma_db/` |
| **NetworkX GraphML** | Knowledge graph (nodes + edges) | `agent/layla/memory/knowledge_graph.graphml` |

An optional **Qdrant** adapter (`vector_qdrant.py`) exists as an alternative to ChromaDB.
It is config-gated (`vector_backend: "qdrant"`) and not the default path.

### 1.2 Module Map

```
layla/memory/
  db.py                 # Barrel re-export (facade)
  db_connection.py      # Thread-local SQLite connection pool
  migrations.py         # Schema creation + versioned migrations
  learnings.py          # Learnings CRUD, spaced repetition, FTS
  vector_store.py       # ChromaDB embeddings, hybrid search, reranking
  vector_qdrant.py      # Qdrant adapter (alternative backend)
  conversations.py      # Multi-session chat storage
  user_profile.py       # Relationship memory, timeline, identity, goals, episodes
  memory_graph.py       # NetworkX knowledge graph (GraphML)
  distill.py            # Memory consolidation (Jaccard + semantic clustering)
  capabilities.py       # Evolution layer: decay, trend, reinforcement scheduling
  capabilities_db.py    # Capabilities SQLite CRUD
  journal.py            # Operator journal entries
  improvements.py       # Self-improvement proposals
  missions_db.py        # Missions, mission chains, background tasks
  projects_db.py        # Layla projects, project context
  tasks_db.py           # Coordinator/execution task persistence
  rl_preferences.py     # RL feedback preference cache
  telemetry_db.py       # Telemetry events, model outcomes
  routing_telemetry.py  # Router decision telemetry
  strategy_stats.py     # Strategy success/failure tallies
  audit_session.py      # Wakeup log, audit trail, session prompts, tool grants
  plans_db.py           # Study plans, layla plans, repo cognition snapshots
```

### 1.3 Connection Lifecycle

1. `db_connection._conn()` is called by every module before any SQL operation.
2. A thread-local (`threading.local()`) connection is checked:
   - If alive and pointing at the correct DB path, it is reused.
   - If stale (failed `SELECT 1` probe) or path-mismatched, it is closed and recreated.
3. On first creation, `_make_connection()` opens a new SQLite connection with:
   - `check_same_thread=False`
   - `row_factory = sqlite3.Row`
   - PRAGMAs: `journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-32000` (32 MB),
     `temp_store=MEMORY`, `mmap_size=268435456` (256 MB), `busy_timeout=5000` (5 s),
     `foreign_keys=ON`.
4. The DB path resolves via `LAYLA_DATA_DIR` env var, or falls back to
   `<repo_root>/layla.db`. Tests can patch `layla.memory.db._DB_PATH`.

### 1.4 How SQLite and ChromaDB Interact

SQLite is the authoritative store for all structured data. ChromaDB stores
vector embeddings as a secondary index. The link between them is the
`learnings.embedding_id` column, which holds the ChromaDB document UUID.

When a learning is saved:
1. SQLite row is inserted first (always).
2. The content is embedded and written to ChromaDB.
3. The returned ChromaDB UUID is written back to `learnings.embedding_id`.
4. If the ChromaDB write fails, `learnings.needs_reindex` is set to `1`.
5. A background reindexer (`reindex_failed_learnings()`) retries up to 50 rows.

Knowledge documents (from the `knowledge/` directory) are indexed into a
separate ChromaDB collection named `"knowledge"`. These have no SQLite backing;
their canonical store is the filesystem, with ChromaDB as an index.

---

## 2. Data Flow

### 2.1 Learning Lifecycle

```
User says something
       |
       v
save_learning(content, kind, ...)
       |
       |-- Rate limit check (20/60s in-process deque)
       |-- learning_filter.filter_learning() (external service, optional)
       |-- distill.passes_learning_quality_gate() (heuristic 0-1, min 0.35)
       |-- Content hash dedup (SHA-1 of content)
       |
       v
INSERT INTO learnings (content, type, learning_type, confidence,
                       source, content_hash, score, tags, ...)
       |
       v
ChromaDB dual-write:
  embed(content) -> 768d vector (nomic) or 384d (MiniLM fallback)
  add_vector(vec, metadata) -> UUID
  UPDATE learnings SET embedding_id = UUID
       |
       |-- On failure: SET needs_reindex = 1
       |
       v
Background side-effects (daemon threads, best-effort):
  - elasticsearch_bridge.index_learning()
  - graph_learning.expand_graph_from_learning()
  - personal_knowledge_graph.invalidate_personal_graph()
  - maturity_engine.award_xp(10)
```

### 2.2 Retrieval Pipeline

```
search_memories_full(query, k=5)
       |
       v
  Step 1: Hybrid retrieval (top 20)
    - search_hybrid(): BM25 (rank_bm25 over recent 2000 learnings)
                      + dense vector (ChromaDB cosine)
                      fused via RRF or weighted linear blend
    - Optional: HyDE (generate hypothetical answer, embed, fuse)
       |
       v
  Step 2: FTS5 merge
    - search_learnings_fts(): SQLite FTS5 (Porter stemmer + unicode61)
    - Fused with Step 1 via RRF
       |
       v
  Step 2b: Light rerank (top 10)
    - Optional MMR (Maximal Marginal Relevance) for diversity
       |
       v
  Step 3: Cross-encoder rerank (top k)
    - cross-encoder/ms-marco-MiniLM-L-6-v2 (default)
    - Optional BGE reranker (config: use_bge_reranker + bge_reranker_model)
       |
       v
  Step 4: Confidence + recency boost
    - Score = 0.6 * semantic_rank + 0.2 * adjusted_confidence + 0.2 * recency
    - Skipped when weighted fusion mode already blended these signals
       |
       v
  Step 5: Domain keyword boost (optional)
    - Active aspect's domain keywords get a small score uplift
```

### 2.3 Knowledge Document Indexing

```
knowledge/ directory (*.md, *.txt, *.pdf)
       |
       v
index_knowledge_docs(knowledge_dir)
       |
       |-- Parse optional YAML front matter (priority, domain, aspects, difficulty, related)
       |-- Chunk text: RecursiveCharacterTextSplitter (600 chars, 100 overlap)
       |     fallback: paragraph-aware hard split
       |-- Content hash per chunk (SHA-1) for incremental dedup
       |-- Batch embed via embed_batch()
       |
       v
ChromaDB "knowledge" collection:
  - Deterministic IDs: "{source_path}_{chunk_index}"
  - Upsert only changed chunks (content_hash comparison)
  - Delete stale IDs (removed/renamed files)
       |
       v
refresh_knowledge_if_changed():
  - Fingerprint = SHA-1 of all file paths + mtimes + sizes
  - Debounced (min 30s between checks)
```

### 2.4 Knowledge Graph (GraphML)

```
add_node(label, metadata)
       |
       v
NetworkX DiGraph:
  - Node: id (auto-increment int), label (120 chars), metadata (JSON), created_at
  - Auto-link: embed label, search ChromaDB for similar, add "similar_to" edges
       |
       v
write_graphml() -> knowledge_graph.graphml

Legacy migration: knowledge_graph.json -> GraphML (one-time, renames .json.migrated)
```

### 2.5 Conversation Flow

```
create_conversation(id, title, aspect_id)
       |
       v
INSERT INTO conversations (id, title, aspect_id, ...)
       |
       v
append_conversation_message(conversation_id, role, content, ...)
       |
       |-- Auto-name: first user message -> title (40 chars)
       |-- Content cap: configurable max_chars (default 100K)
       |-- FTS trigger: auto-populates conversation_messages_fts
       |
       v
add_conversation_summary(summary)
       |
       |-- Embed summary -> ChromaDB learnings collection
       |-- INSERT INTO conversation_summaries
```

---

## 3. Retention & Cleanup

### 3.1 Learnings Confidence Decay

- Formula: `adjusted = confidence * exp(-age_days / 180)`
- Half-life: ~125 days (confidence halves every ~125 days)
- Applied at read time (not stored); original `confidence` column is preserved
- Used for retrieval scoring, not deletion

### 3.2 Memory Distillation

`distill.py` provides two consolidation strategies:

| Strategy | Method | Threshold |
|----------|--------|-----------|
| Jaccard | Word-set overlap ratio | >= 0.55 similarity |
| Semantic | Agglomerative clustering (cosine, average linkage) | sklearn required |

Process:
1. Group similar learnings (2+ items per group).
2. Summarize each group (first sentence of each, max 400 chars).
3. Delete original learnings from SQLite + ChromaDB.
4. Insert merged summary as a new learning with `type="distilled"`.
5. Triggered by `run_distill_after_outcome(n=50)` after outcome memory writes.

### 3.3 Learnings Archive

Table `learnings_archive` stores soft-deleted learnings instead of hard-deleting them.
Columns include `archived_at`, `archive_reason` (default `"confidence_decay"`),
and `original_confidence`. Currently the archive table is created but no code
actively moves records into it -- this is a prepared-but-unused mechanism.

### 3.4 Study Plan Progress Trimming

`update_study_progress()` caps the progress JSON array at 50 entries,
discarding the oldest when exceeded.

### 3.5 Conversation Message Cap

Messages are capped at `conversation_message_max_chars` (config, default 100,000
characters) at insert time.

### 3.6 Orphan Cleanup

`_cleanup_orphaned_records()` runs once per process (inside migration):
- Deletes `conversation_messages` with no parent `conversations` row.
- Deletes `relationships` with no parent `entities` row (both from_entity and to_entity).
- Deletes `goal_progress` with no parent `goals` row.
- Deletes `episode_events` with no parent `episodes` row.

### 3.7 What Has No Retention Policy

The following tables grow without bound and have no cleanup mechanism:

- `audit` -- unbounded append
- `wakeup_log` -- unbounded append
- `telemetry_events` -- unbounded append
- `model_outcomes` -- unbounded append
- `route_telemetry` -- unbounded append
- `tool_outcomes` -- unbounded append
- `tool_calls` -- unbounded append
- `capability_events` -- unbounded append
- `golden_examples` -- unbounded append
- `session_prompts` -- unbounded append
- `operator_journal` -- unbounded append
- `timeline_events` -- unbounded append
- `relationship_memory` -- unbounded append
- `episode_events` -- unbounded append
- `conversation_summaries` -- unbounded append
- `strategy_stats` -- bounded by unique (task_type, strategy) pairs

---

## 4. Vector Store

### 4.1 Embedding Models

| Model | Dimensions | Usage |
|-------|-----------|-------|
| `nomic-ai/nomic-embed-text-v1.5` | 768 | Primary (via sentence-transformers) |
| `all-MiniLM-L6-v2` | 384 | Fallback if nomic unavailable |

Quantization:
- GPU: `model.half()` (float16, 2x VRAM reduction)
- CPU: `torchao` int8 dynamic quantization when available; no fallback to deprecated `torch.quantization`

### 4.2 Caching

- **LRU cache**: `_embed_cached` with `maxsize=1024`. Cached per unique text string.
  Thread-safe (`functools.lru_cache` is inherently thread-safe in CPython).
- **BM25 index cache**: Rebuilt when learnings count changes. Up to 2000 learnings
  indexed at a time.

### 4.3 ChromaDB Collections

| Collection | Content | ID Scheme |
|------------|---------|-----------|
| `"learnings"` | Learning embeddings | Random UUID |
| `"knowledge"` | Knowledge doc chunks | `"{source_path}_{chunk_index}"` (deterministic) |

Both use `hnsw:space = cosine`.

Metadata stored per vector:
- learnings: `content`, `type`, `tags` (optional), `embed_model` (provenance)
- knowledge: `priority`, `domain`, `aspects`, `difficulty`, `related`, `source`,
  `chunk_index`, `content_hash`

### 4.4 Dimension Mismatch Detection

On ChromaDB initialization, the code peeks at the first stored embedding and
compares its dimensionality against the current model's output. A warning is
logged on mismatch. A `rebuild_collection()` endpoint re-indexes all SQLite
learnings into a fresh ChromaDB collection.

### 4.5 Embedding Model Provenance (P1-4)

Every vector write includes `embed_model` in metadata. On collection init,
stored model name is compared against current; mismatch triggers a warning.

### 4.6 Qdrant Adapter

`vector_qdrant.py` provides:

| Function | Description |
|----------|-------------|
| `is_available(cfg)` | Check if qdrant-client is installed + server reachable |
| `get_client(cfg)` | Thread-safe cached client |
| `ensure_collection(cfg, vector_size)` | Idempotent collection creation (cosine) |
| `add_memories(cfg, memories)` | Batch upsert points |
| `search_memories(cfg, embedding, ...)` | Nearest-neighbor with metadata filters |
| `delete_memories(cfg, ids)` | Point deletion |
| `get_stats(cfg)` | Collection statistics |

Config keys: `vector_backend` (`"chroma"` or `"qdrant"`), `qdrant_url`,
`qdrant_api_key`, `qdrant_collection` (default `"layla-memories"`).

### 4.7 Cross-Encoder Reranking

Two cross-encoder paths:
1. Default: `cross-encoder/ms-marco-MiniLM-L-6-v2`
2. Optional BGE: config `use_bge_reranker` + `bge_reranker_model`

Both use `sentence_transformers.CrossEncoder`. Loaded lazily; failure flags
prevent retry attempts (`_cross_encoder_failed`, `_bge_cross_encoder_failed`).

---

## 5. Thread Safety

### 5.1 Connection Pool

- **Mechanism**: `threading.local()` in `db_connection.py`.
- Each thread gets its own `sqlite3.Connection` instance.
- Connections are created with `check_same_thread=False`.
- Stale detection: `SELECT 1` probe before reuse.
- Path mismatch detection: old connection closed if DB path changed (test isolation).
- Explicit cleanup: `close_thread_connection()` for shutdown hooks.

### 5.2 Locks

| Lock | Type | Protects | Location |
|------|------|----------|----------|
| `_MIGRATION_LOCK` | `threading.Lock` | Migration runs at most once per process | `migrations.py` |
| `_embedder_lock` | `threading.RLock` | Embedder model init | `vector_store.py` |
| `_chroma_lock` | `threading.RLock` | ChromaDB learnings collection init | `vector_store.py` |
| `_knowledge_lock` | `threading.Lock` | ChromaDB knowledge collection init | `vector_store.py` |
| `_bm25_lock` | `threading.Lock` | BM25 index rebuild | `vector_store.py` |
| `_rate_lock` | `threading.Lock` | Learning save rate limiter | `learnings.py` |
| `_client_lock` | `threading.Lock` | Qdrant client init | `vector_qdrant.py` |

### 5.3 Thread Safety Notes

- RLocks are used for embedder and ChromaDB because `_get_embedder()` can be
  called recursively from `_get_chroma_collection()` during dimension checks.
- `embed_batch()` is explicitly documented as NOT locked -- it must only be
  called from single-threaded context builders.
- The LRU cache (`_embed_cached`) is thread-safe in CPython due to the GIL.
- SQLite connections use WAL mode, allowing concurrent readers with a single writer.
  `busy_timeout=5000` handles write contention.

### 5.4 Potential Race Conditions

1. **BM25 rebuild**: The `_bm25_doc_count` check and rebuild are inside a lock,
   but the count comparison uses `len(docs)` from `get_recent_learnings()`, which
   reads from SQLite outside the lock. A learning inserted between the count check
   and the rebuild could cause a stale index until the next count change.
2. **Knowledge fingerprint**: `_knowledge_fingerprint` and `_knowledge_last_check_ts`
   are module-level globals written without a lock. In multi-threaded contexts,
   concurrent `refresh_knowledge_if_changed()` calls could trigger duplicate
   re-indexes.
3. **Dual-write consistency**: Between `INSERT INTO learnings` and the subsequent
   `UPDATE learnings SET embedding_id = ...`, another thread could read the row
   without an `embedding_id`. The `needs_reindex` flag mitigates but does not
   eliminate the window.

---

## 6. Migration System

### 6.1 How Migrations Work

- `migrate()` is called at the top of every domain module function.
- A process-level guard (`_MIGRATED` flag + `_MIGRATION_LOCK`) ensures
  `_migrate_impl()` runs at most once per process.
- All table creation uses `CREATE TABLE IF NOT EXISTS` (idempotent).
- Column additions use `ALTER TABLE ADD COLUMN` wrapped in `try/except`
  for `"duplicate column"` errors (idempotent).
- Index creation uses `CREATE INDEX IF NOT EXISTS` (idempotent).

### 6.2 Version Tracking

- Table `schema_version` (singleton row, `id=1`) stores the current version.
- Version 0 = pre-versioning (all CREATE TABLE IF NOT EXISTS).
- Version 1 = baseline (all existing migrations have run).
- Future migrations gate on `if version < N`.
- Currently only version 1 is used. No higher-version migrations exist yet.

### 6.3 Migration Order

1. `schema_version` table created.
2. Core tables: `learnings`, `study_plans`, `wakeup_log`, `audit`, `aspect_memories`.
3. Performance indexes for core tables.
4. `outcome_evaluations` table.
5. FTS5 virtual table `learnings_fts` + sync triggers.
6. `earned_titles` table.
7. Telemetry tables: `telemetry_events`, `model_outcomes`, `golden_examples`, `route_telemetry`.
8. Column additions to `learnings`: `learning_type`, `confidence`, `source`, `content_hash`, `score`, `importance_score`, `next_review_at`, `tags`, `needs_reindex`, `aspect_id`, `privacy_level`.
9. Column additions to `study_plans`: `momentum_score`, `domain_id`, `linked_capability_event_id`.
10. Evolution layer tables (via `_migrate_evolution_layer()`): `capability_domains`, `capabilities`, `capability_events`, `capability_dependencies`, `style_profile`, `mission_chains`, `scheduler_history`, `project_context`, `capability_implementations`.
11. Seed data: 10 core + 13 fabrication capability domains, 12 dependency edges, 4 style profile defaults.
12. `missions`, `background_tasks`, `repo_cognition_snapshots`, `conversation_summaries`.
13. Chat tables: `conversations`, `conversation_messages`, FTS5 + triggers.
14. `operator_journal`, `self_improvement_proposals`, `layla_projects`.
15. Additional column additions to `conversations`, `conversation_summaries`, `layla_projects`.
16. Companion tables: `relationship_memory`, `timeline_events`, `user_identity`, `episodes`, `episode_events`, `tool_outcomes`, `goals`, `goal_progress`.
17. `rl_preferences`, `codex_discoveries`, `journal_entity_links`, `learnings_archive`.
18. Orphan cleanup (`_cleanup_orphaned_records()`).
19. JSON migration (`_migrate_learnings_json()`): imports from `learnings.json` if present.
20. Session tables: `session_prompts`, `tool_permission_grants`, `layla_plans`, `tasks`, `strategy_stats`, `tool_calls`.
21. Entity tables: `entities`, `relationships` (with FK CASCADE).
22. Privacy columns: `entities.privacy_level`, `learnings.privacy_level`.
23. Schema version stamped to 1.

### 6.4 Schema Conflict Handling

- All DDL is idempotent (IF NOT EXISTS / duplicate column catch).
- Each migration block is independently wrapped in `try/except`.
- A failure in one block logs a warning but does not prevent subsequent blocks.
- This means partial migrations are possible: some tables/columns may exist
  while others failed.

---

## 7. Known Issues

### 7.1 Missing Indexes

- `conversation_messages` has no index on `role` (would help filtering assistant vs user messages).
- `relationship_memory` has no index on `embedding_id`.
- `timeline_events` has no index on `event_type`.
- `operator_journal` has no index on `project_id` or `conversation_id`.
- `goals` has no index on `project_id`.
- `capability_events` has no index on `domain_id` (queried by domain frequently).
- `missions` has no index on `created_at` (used in ORDER BY).

### 7.2 Missing Foreign Keys

- `learnings.aspect_id` -> no FK to any aspects table (aspects are concept-level, not DB-backed).
- `background_tasks.conversation_id` -> no FK to `conversations`.
- `operator_journal.project_id` -> no FK to `layla_projects`.
- `operator_journal.conversation_id` -> no FK to `conversations`.
- `timeline_events.project_id` -> no FK to `layla_projects`.
- `goals.project_id` -> no FK to `layla_projects`.
- `study_plans.domain_id` -> no FK to `capability_domains`.
- `study_plans.linked_capability_event_id` -> no FK to `capability_events`.
- `mission_chains.parent_mission_id` -> no FK to `missions`.
- `missions.workspace_root` -> no FK (free text).
- `route_telemetry.conversation_id` -> no FK to `conversations`.
- `conversation_summaries.embedding_id` -> no FK (ChromaDB UUID, cross-store).
- `journal_entity_links.journal_id` -> no FK to `operator_journal`.
- `journal_entity_links.entity_id` -> no FK to `entities`.
- `episode_events.event_id` -> polymorphic reference (no FK possible with `source_table`).

### 7.3 Orphan Record Risks

- Deleting a conversation deletes its messages (explicit in `delete_conversation()`),
  but does not clean up `conversation_summaries` or `conversation_messages_fts` triggers
  (FTS triggers handle delete, but summaries referencing the conversation remain).
- Deleting entities cascades to relationships (FK ON DELETE CASCADE), but does not
  clean up `codex_discoveries` or `journal_entity_links`.
- `learnings_archive` rows are never cleaned up.
- `tool_calls` with stale `run_id` values accumulate indefinitely.

### 7.4 Tables Without Retention

See Section 3.7 for the full list. Key concern: `tool_calls`, `telemetry_events`,
`audit`, and `capability_events` will grow proportional to usage without any TTL
or compaction.

### 7.5 Stale Caches

- BM25 index only refreshes when document count changes. Edits to existing
  learnings do not trigger a rebuild.
- Knowledge fingerprint uses file mtime + size; content changes with identical
  size are missed (unlikely but possible).
- LRU embed cache is never invalidated when the embedding model changes at runtime.
  `rebuild_collection()` does not clear the LRU cache.

### 7.6 ChromaDB/SQLite Sync

- If ChromaDB is wiped but SQLite retains `embedding_id` values, all vector
  lookups silently return no results. The `needs_reindex` flag only covers
  write-time failures, not post-hoc data loss.
- `rebuild_collection()` addresses this but must be called manually via
  `POST /memory/rebuild`.

### 7.7 learnings_archive Not Used

The `learnings_archive` table is created during migration but no production
code path writes to it. The `archive_reason` column suggests it was intended
for confidence-decay-based archival, but this was never implemented.

### 7.8 FTS Content Sync on Bulk Delete

The FTS5 `content=` external content table relies on triggers for sync.
`delete_learnings_by_id()` uses a plain `DELETE FROM learnings WHERE id IN (...)`,
which fires the `learnings_fts_delete` trigger correctly. However, bulk deletes
via direct SQL (bypassing the function) could desync FTS.

---

## 8. Every Table -- Complete Schema Reference

### 8.1 schema_version

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY, CHECK (id = 1) | Singleton row |
| version | INTEGER | NOT NULL, DEFAULT 0 | Current schema version |
| updated_at | TEXT | | ISO timestamp |

### 8.2 learnings

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| content | TEXT | NOT NULL | Learning text |
| type | TEXT | DEFAULT 'fact' | Original type column |
| created_at | TEXT | NOT NULL | ISO timestamp |
| embedding_id | TEXT | | ChromaDB document UUID |
| learning_type | TEXT | DEFAULT 'fact' | fact, preference, strategy, identity, distilled |
| confidence | REAL | DEFAULT 0.5 | 0.9 study, 0.7 LLM, 0.4 heuristic |
| source | TEXT | DEFAULT '' | Origin of the learning |
| content_hash | TEXT | DEFAULT '' | SHA-1 of content (dedup) |
| score | REAL | DEFAULT 1.0 | Quality score 0-1 |
| importance_score | REAL | DEFAULT 0.5 | Spaced repetition importance 0-1 |
| next_review_at | TEXT | | ISO timestamp for next review |
| tags | TEXT | DEFAULT '' | Comma-separated tags |
| needs_reindex | INTEGER | DEFAULT 0 | 1 = ChromaDB write failed |
| aspect_id | TEXT | DEFAULT '' | Facet attribution |
| privacy_level | TEXT | DEFAULT 'public' | public, personal, sensitive |

**Indexes:**
- `idx_learnings_type` on `(type)`
- `idx_learnings_id_desc` on `(id DESC)`
- `idx_learnings_embedding_id` on `(embedding_id)`
- `idx_learnings_content_hash` on `(content_hash)`
- `idx_learnings_aspect` on `(aspect_id)`

### 8.3 learnings_fts (FTS5 virtual table)

| Column | Notes |
|--------|-------|
| content | FTS5-indexed, content='learnings', content_rowid='id' |

Tokenizer: `porter unicode61`

**Sync triggers:** `learnings_fts_insert`, `learnings_fts_delete`, `learnings_fts_update`

### 8.4 learnings_archive

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY | From original learning |
| content | TEXT | NOT NULL | |
| type | TEXT | DEFAULT 'fact' | |
| created_at | TEXT | NOT NULL | |
| archived_at | TEXT | NOT NULL | When archived |
| archive_reason | TEXT | DEFAULT 'confidence_decay' | |
| original_confidence | REAL | DEFAULT 0 | |
| tags | TEXT | DEFAULT '' | |
| aspect_id | TEXT | DEFAULT '' | |

### 8.5 outcome_evaluations

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| conversation_id | TEXT | NOT NULL | |
| created_at | TEXT | NOT NULL | |
| evaluation_json | TEXT | NOT NULL | JSON-encoded evaluation dict |

**Indexes:**
- `idx_outcome_evaluations_cid_id_desc` on `(conversation_id, id DESC)`

### 8.6 study_plans

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | |
| topic | TEXT | NOT NULL | |
| status | TEXT | DEFAULT 'active' | |
| progress | TEXT | DEFAULT '[]' | JSON array of {note, at} |
| created_at | TEXT | NOT NULL | |
| last_studied | TEXT | | ISO timestamp |
| momentum_score | REAL | DEFAULT 0 | |
| domain_id | TEXT | | FK to capability_domains (not enforced) |
| linked_capability_event_id | INTEGER | | FK to capability_events (not enforced) |

**Indexes:**
- `idx_study_plans_status` on `(status)`

### 8.7 wakeup_log

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| timestamp | TEXT | NOT NULL | |
| greeting | TEXT | | |
| notes | TEXT | | |

### 8.8 audit

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| timestamp | TEXT | NOT NULL | |
| tool | TEXT | NOT NULL | Tool name |
| args_summary | TEXT | | Truncated to 200 chars |
| approved_by | TEXT | | Who approved |
| result_ok | INTEGER | | 0 or 1 |

**Indexes:**
- `idx_audit_tool` on `(tool)`
- `idx_audit_id_desc` on `(id DESC)`

### 8.9 aspect_memories

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| aspect_id | TEXT | NOT NULL | e.g. echo, morrigan, nyx |
| content | TEXT | NOT NULL | |
| created_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_aspect_memories_aspect` on `(aspect_id)`

### 8.10 earned_titles

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| aspect_id | TEXT | PRIMARY KEY | |
| title | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |

### 8.11 telemetry_events

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| ts | TEXT | NOT NULL | ISO timestamp |
| task_type | TEXT | | |
| reasoning_mode | TEXT | | |
| model_used | TEXT | | |
| latency_ms | REAL | | |
| success | INTEGER | | |
| performance_mode | TEXT | | |

**Indexes:**
- `idx_telemetry_ts` on `(ts)`

### 8.12 model_outcomes

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| ts | TEXT | NOT NULL | |
| model_used | TEXT | NOT NULL | |
| task_type | TEXT | | |
| success | INTEGER | DEFAULT 0 | |
| score | REAL | | |
| latency_ms | REAL | | |

**Indexes:**
- `idx_model_outcomes_ts` on `(ts)`
- `idx_model_outcomes_model_task` on `(model_used, task_type)`

### 8.13 golden_examples

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| ts | TEXT | NOT NULL | |
| task_type | TEXT | NOT NULL | |
| goal_summary | TEXT | NOT NULL | |
| decision_pattern | TEXT | NOT NULL | |
| outcome_score | REAL | NOT NULL | |
| usage_count | INTEGER | DEFAULT 0 | |

**Indexes:**
- `idx_golden_examples_ts` on `(ts)`
- `idx_golden_examples_task_score` on `(task_type, outcome_score)`

### 8.14 route_telemetry

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| created_at | TEXT | NOT NULL | |
| conversation_id | TEXT | | |
| goal | TEXT | | Truncated to 2000 chars |
| task_type | TEXT | | |
| is_meta_self | INTEGER | DEFAULT 0 | |
| has_workspace_signals | INTEGER | DEFAULT 0 | |
| decision_action | TEXT | | |
| decision_tool | TEXT | | |
| preflight_ok | INTEGER | | Nullable |
| preflight_reason | TEXT | | |
| final_status | TEXT | | |
| parse_failed | INTEGER | DEFAULT 0 | |

**Indexes:**
- `idx_route_telemetry_created_at` on `(created_at)`
- `idx_route_telemetry_cid_id_desc` on `(conversation_id, id DESC)`

### 8.15 capability_domains

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | e.g. coding, research, cnc_machining |
| name | TEXT | NOT NULL | Display name |
| description | TEXT | | |
| created_at | TEXT | NOT NULL | |

Seeded with 10 core domains + 13 fabrication domains.

### 8.16 capabilities

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| domain_id | TEXT | PRIMARY KEY, REFERENCES capability_domains(id) | |
| level | REAL | NOT NULL, DEFAULT 0.5 | 0-1 proficiency |
| confidence | REAL | NOT NULL, DEFAULT 0.5 | |
| trend | TEXT | NOT NULL, DEFAULT 'stable' | improving, stable, weakening, stagnant |
| last_practiced_at | TEXT | | |
| decay_risk | REAL | NOT NULL, DEFAULT 0.5 | 0-1 |
| reinforcement_priority | REAL | NOT NULL, DEFAULT 0.5 | 0-1, higher = more urgent |
| practice_count | INTEGER | NOT NULL, DEFAULT 0 | |
| updated_at | TEXT | NOT NULL | |

### 8.17 capability_events

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| domain_id | TEXT | NOT NULL | |
| event_type | TEXT | NOT NULL | practice, cross_signal, decay_tick |
| mission_id | TEXT | | |
| delta_level | REAL | DEFAULT 0 | |
| delta_confidence | REAL | DEFAULT 0 | |
| notes | TEXT | | |
| usefulness_score | REAL | DEFAULT 0.5 | |
| learning_quality_score | REAL | DEFAULT 0.5 | |
| created_at | TEXT | NOT NULL | |

### 8.18 capability_dependencies

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| source_domain_id | TEXT | NOT NULL | |
| target_domain_id | TEXT | NOT NULL | |
| weight | REAL | NOT NULL, DEFAULT 0.2 | Cross-domain propagation weight |

PRIMARY KEY: `(source_domain_id, target_domain_id)`

Seeded with 6 core + 6 fabrication dependency edges.

### 8.19 capability_implementations

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| capability_name | TEXT | NOT NULL | e.g. vector_search, embedding |
| implementation_id | TEXT | NOT NULL | |
| package_name | TEXT | NOT NULL | |
| status | TEXT | NOT NULL, DEFAULT 'candidate' | candidate, active, benchmarked |
| latency_ms | REAL | | |
| throughput_per_sec | REAL | | |
| memory_mb | REAL | | |
| benchmark_results | TEXT | | |
| last_benchmarked_at | TEXT | | |
| sandbox_valid | INTEGER | DEFAULT 0 | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |

PRIMARY KEY: `(capability_name, implementation_id)`

**Indexes:**
- `idx_cap_impl_status` on `(status)`

### 8.20 style_profile

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| key | TEXT | PRIMARY KEY | writing, coding, reasoning, structuring |
| profile_snapshot | TEXT | | Natural-language style description |
| last_reinforced_at | TEXT | | |
| drift_score | REAL | DEFAULT 0 | |
| updated_at | TEXT | NOT NULL | |

Seeded with 4 default profiles (writing, coding, reasoning, structuring).

### 8.21 mission_chains

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | |
| parent_mission_id | TEXT | | |
| mission_type | TEXT | NOT NULL | |
| goal_summary | TEXT | | |
| outcome_summary | TEXT | | |
| status | TEXT | NOT NULL, DEFAULT 'pending' | pending, completed |
| capability_domains | TEXT | | JSON array of domain IDs |
| created_at | TEXT | NOT NULL | |
| completed_at | TEXT | | |

### 8.22 scheduler_history

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| domain_id | TEXT | | |
| plan_id | TEXT | | |
| created_at | TEXT | NOT NULL | |

### 8.23 project_context

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY, CHECK (id = 1) | Singleton row |
| project_name | TEXT | DEFAULT '' | |
| domains | TEXT | DEFAULT '[]' | JSON array |
| key_files | TEXT | DEFAULT '[]' | JSON array |
| goals | TEXT | DEFAULT '' | |
| lifecycle_stage | TEXT | DEFAULT '' | idea, planning, prototype, iteration, execution, reflection |
| progress | TEXT | DEFAULT '' | |
| blockers | TEXT | DEFAULT '' | |
| last_discussed | TEXT | DEFAULT '' | |
| updated_at | TEXT | NOT NULL | |

### 8.24 missions

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | |
| goal | TEXT | NOT NULL | |
| plan_json | TEXT | NOT NULL | JSON array of plan steps |
| status | TEXT | NOT NULL, DEFAULT 'pending' | pending, running, completed, failed |
| current_step | INTEGER | NOT NULL, DEFAULT 0 | |
| results_json | TEXT | DEFAULT '[]' | JSON array of step results |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |
| workspace_root | TEXT | DEFAULT '' | |
| allow_write | INTEGER | DEFAULT 0 | |
| allow_run | INTEGER | DEFAULT 0 | |

**Indexes:**
- `idx_missions_status` on `(status)`

### 8.25 background_tasks

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | |
| conversation_id | TEXT | DEFAULT '' | |
| goal | TEXT | NOT NULL | |
| aspect_id | TEXT | DEFAULT '' | |
| status | TEXT | NOT NULL, DEFAULT 'queued' | queued, running, done, failed |
| priority | INTEGER | DEFAULT 0 | |
| result | TEXT | DEFAULT '' | |
| error | TEXT | DEFAULT '' | |
| created_at | TEXT | NOT NULL | |
| started_at | TEXT | DEFAULT '' | |
| finished_at | TEXT | DEFAULT '' | |
| updated_at | TEXT | NOT NULL | |
| kind | TEXT | DEFAULT 'background' | |
| progress_json | TEXT | DEFAULT '[]' | |

**Indexes:**
- `idx_background_tasks_created` on `(created_at DESC)`
- `idx_background_tasks_status` on `(status)`

### 8.26 repo_cognition_snapshots

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| workspace_root | TEXT | PRIMARY KEY | Resolved absolute path |
| label | TEXT | DEFAULT '' | |
| fingerprint | TEXT | DEFAULT '' | |
| pack_json | TEXT | DEFAULT '{}' | Up to 500K chars |
| pack_markdown | TEXT | NOT NULL, DEFAULT '' | Up to 800K chars |
| file_manifest_json | TEXT | DEFAULT '[]' | Up to 200K chars |
| updated_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_repo_cognition_updated` on `(updated_at DESC)`

### 8.27 conversation_summaries

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| summary | TEXT | NOT NULL | Truncated to 8000 chars |
| created_at | TEXT | NOT NULL | |
| embedding_id | TEXT | DEFAULT '' | ChromaDB UUID |

**Indexes:**
- `idx_conversation_summaries_created` on `(created_at DESC)`

### 8.28 conversations

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | UUID |
| title | TEXT | DEFAULT '' | Auto-named from first user message |
| aspect_id | TEXT | DEFAULT '' | |
| dominant_aspect | TEXT | DEFAULT '' | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |
| message_count | INTEGER | DEFAULT 0 | |
| project_id | TEXT | DEFAULT '' | |
| tags | TEXT | DEFAULT '' | Comma-separated normalized tags |

**Indexes:**
- `idx_conversations_updated_at` on `(updated_at DESC)`

### 8.29 conversation_messages

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | UUID |
| conversation_id | TEXT | NOT NULL | FK -> conversations(id) |
| role | TEXT | NOT NULL | user, assistant, system |
| content | TEXT | NOT NULL | Capped at 100K chars |
| aspect_id | TEXT | DEFAULT '' | |
| created_at | TEXT | NOT NULL | |
| token_count | INTEGER | DEFAULT 0 | |

**Indexes:**
- `idx_conv_msgs_conversation_id` on `(conversation_id, created_at)`

### 8.30 conversation_messages_fts (FTS5 virtual table)

| Column | Notes |
|--------|-------|
| content | FTS5-indexed |
| conversation_id | UNINDEXED (stored but not searchable) |

`content='conversation_messages'`, `content_rowid='rowid'`

**Sync triggers:** `conversation_messages_fts_insert`, `conversation_messages_fts_delete`, `conversation_messages_fts_update`

### 8.31 operator_journal

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| created_at | TEXT | NOT NULL | |
| entry_type | TEXT | NOT NULL, DEFAULT 'note' | note, recap, thread, etc. |
| content | TEXT | NOT NULL | Truncated to 20K chars |
| tags | TEXT | DEFAULT '' | Normalized comma-separated |
| project_id | TEXT | DEFAULT '' | |
| aspect_id | TEXT | DEFAULT '' | |
| conversation_id | TEXT | DEFAULT '' | |

**Indexes:**
- `idx_operator_journal_created` on `(created_at DESC)`
- `idx_operator_journal_type` on `(entry_type)`

### 8.32 self_improvement_proposals

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| created_at | TEXT | NOT NULL | |
| status | TEXT | NOT NULL, DEFAULT 'pending' | pending, approved, rejected, applied |
| title | TEXT | NOT NULL | Truncated to 200 chars |
| rationale | TEXT | DEFAULT '' | Truncated to 2000 chars |
| risk_level | TEXT | DEFAULT 'low' | |
| domain | TEXT | DEFAULT '' | |
| instructions | TEXT | DEFAULT '' | JSON or plain text, up to 20K chars |

**Indexes:**
- `idx_improvements_created` on `(created_at DESC)`
- `idx_improvements_status` on `(status)`

### 8.33 layla_projects

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | UUID |
| name | TEXT | NOT NULL, DEFAULT '' | |
| workspace_root | TEXT | DEFAULT '' | |
| aspect_default | TEXT | DEFAULT '' | |
| skill_paths_json | TEXT | DEFAULT '[]' | JSON array |
| system_preamble | TEXT | DEFAULT '' | Up to 8000 chars |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |
| cognition_extra_roots | TEXT | DEFAULT '' | JSON or free text, up to 16K chars |

**Indexes:**
- `idx_layla_projects_updated` on `(updated_at DESC)`

### 8.34 relationship_memory

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| user_event | TEXT | NOT NULL | Interaction summary, up to 4000 chars |
| timestamp | TEXT | NOT NULL | |
| embedding_id | TEXT | DEFAULT '' | ChromaDB UUID |

**Indexes:**
- `idx_relationship_memory_timestamp` on `(timestamp DESC)`

### 8.35 timeline_events

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| event_type | TEXT | NOT NULL | life_event, project_milestone, goal, blocker, conversation_summary |
| content | TEXT | NOT NULL | Up to 4000 chars |
| timestamp | TEXT | NOT NULL | |
| importance | REAL | DEFAULT 0.5 | 0-1 |
| embedding_id | TEXT | DEFAULT '' | ChromaDB UUID |
| project_id | TEXT | DEFAULT '' | |
| created_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_timeline_events_timestamp` on `(timestamp DESC)`
- `idx_timeline_events_importance` on `(importance DESC)`

### 8.36 user_identity

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| key | TEXT | PRIMARY KEY | verbosity, humor_tolerance, formality, response_length, life_narrative_summary |
| snapshot | TEXT | DEFAULT '' | Up to 4000 chars |
| updated_at | TEXT | NOT NULL | |

### 8.37 episodes

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | UUID prefix (16 chars) |
| summary | TEXT | DEFAULT '' | Up to 500 chars |
| started_at | TEXT | NOT NULL | |
| ended_at | TEXT | | |
| created_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_episodes_started` on `(started_at DESC)`

### 8.38 episode_events

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| episode_id | TEXT | NOT NULL | |
| event_type | TEXT | NOT NULL | |
| event_id | TEXT | | Up to 64 chars |
| source_table | TEXT | | Up to 32 chars |
| created_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_episode_events_episode` on `(episode_id)`

### 8.39 tool_outcomes

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| tool_name | TEXT | NOT NULL | |
| context | TEXT | DEFAULT '' | Up to 500 chars |
| success | INTEGER | NOT NULL | 0 or 1 |
| latency_ms | REAL | DEFAULT 0 | |
| quality_score | REAL | DEFAULT 0.5 | 0-1 |
| created_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_tool_outcomes_tool` on `(tool_name)`
- `idx_tool_outcomes_created` on `(created_at DESC)`

### 8.40 goals

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | UUID prefix (16 chars) |
| title | TEXT | NOT NULL | Up to 200 chars |
| description | TEXT | DEFAULT '' | Up to 1000 chars |
| status | TEXT | DEFAULT 'active' | |
| project_id | TEXT | DEFAULT '' | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_goals_status` on `(status)`

### 8.41 goal_progress

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| goal_id | TEXT | NOT NULL | |
| note | TEXT | DEFAULT '' | Up to 500 chars |
| progress_pct | REAL | DEFAULT 0 | 0-100 |
| created_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_goal_progress_goal` on `(goal_id)`

### 8.42 rl_preferences

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| tool_name | TEXT | PRIMARY KEY | |
| score | REAL | | RL feedback score |
| hint | TEXT | | |
| updated_at | TEXT | | |

### 8.43 codex_discoveries

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| entity_id | TEXT | NOT NULL, PRIMARY KEY | |
| discovered_at | TEXT | NOT NULL | |
| discovery_context | TEXT | DEFAULT '' | |
| notified | INTEGER | DEFAULT 0 | |

### 8.44 journal_entity_links

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| journal_id | INTEGER | NOT NULL | |
| entity_id | TEXT | NOT NULL | |

PRIMARY KEY: `(journal_id, entity_id)`

### 8.45 session_prompts

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| prompt | TEXT | NOT NULL | Up to 10K chars |
| aspect | TEXT | | Up to 128 chars |
| created_at | TEXT | DEFAULT (datetime('now')) | |

**Indexes:**
- `idx_session_prompts_id_desc` on `(id DESC)`

### 8.46 tool_permission_grants

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | UUID |
| tool | TEXT | NOT NULL | Up to 128 chars |
| pattern | TEXT | NOT NULL | Glob pattern, up to 512 chars |
| scope | TEXT | DEFAULT 'session' | session or permanent |
| created_at | TEXT | | |
| expires_at | TEXT | | |

### 8.47 layla_plans

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | UUID |
| workspace_root | TEXT | NOT NULL, DEFAULT '' | Resolved absolute path |
| goal | TEXT | NOT NULL, DEFAULT '' | |
| context | TEXT | NOT NULL, DEFAULT '' | |
| steps_json | TEXT | NOT NULL, DEFAULT '[]' | JSON array of step dicts |
| status | TEXT | NOT NULL, DEFAULT 'draft' | draft, approved, executing, paused, done, blocked |
| conversation_id | TEXT | NOT NULL, DEFAULT '' | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_layla_plans_ws` on `(workspace_root)`
- `idx_layla_plans_status` on `(status)`
- `idx_layla_plans_updated` on `(updated_at DESC)`

### 8.48 tasks

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | UUID |
| goal | TEXT | NOT NULL | |
| status | TEXT | NOT NULL, DEFAULT 'pending' | pending, running, done, failed |
| plan_json | TEXT | DEFAULT '{}' | JSON dict |
| results_json | TEXT | DEFAULT '[]' | JSON array |
| execution_state_json | TEXT | DEFAULT '{}' | JSON dict |
| conversation_id | TEXT | DEFAULT '' | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_tasks_conv` on `(conversation_id)`
- `idx_tasks_updated` on `(updated_at DESC)`

### 8.49 strategy_stats

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| task_type | TEXT | NOT NULL | Truncated to 120 chars |
| strategy | TEXT | NOT NULL | Truncated to 120 chars |
| success_count | INTEGER | NOT NULL, DEFAULT 0 | |
| fail_count | INTEGER | NOT NULL, DEFAULT 0 | |
| last_updated_at | TEXT | NOT NULL | |

UNIQUE: `(task_type, strategy)`

**Indexes:**
- `idx_strategy_stats_task` on `(task_type)`

### 8.50 tool_calls

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| run_id | TEXT | NOT NULL, DEFAULT '' | |
| tool_name | TEXT | NOT NULL | |
| args_hash | TEXT | DEFAULT '' | |
| result_ok | INTEGER | DEFAULT 0 | |
| error_code | TEXT | DEFAULT '' | |
| duration_ms | INTEGER | DEFAULT 0 | |
| created_at | TEXT | NOT NULL | |
| cost_usd | REAL | DEFAULT 0.0 | LLM cost tracking (Phase 3) |
| provider | TEXT | DEFAULT '' | |
| model_used | TEXT | DEFAULT '' | |

**Indexes:**
- `idx_tool_calls_run_id` on `(run_id)`
- `idx_tool_calls_tool_name` on `(tool_name)`
- `idx_tool_calls_created` on `(created_at DESC)`

### 8.51 entities

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | |
| type | TEXT | NOT NULL | person, concept, technology, code_symbol, etc. |
| canonical_name | TEXT | NOT NULL | |
| aliases | TEXT | DEFAULT '[]' | JSON array |
| description | TEXT | DEFAULT '' | |
| tags | TEXT | DEFAULT '[]' | JSON array |
| confidence | REAL | DEFAULT 0.5 | |
| source | TEXT | DEFAULT '' | |
| evidence | TEXT | DEFAULT '' | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |
| last_seen_at | TEXT | DEFAULT '' | |
| attributes | TEXT | DEFAULT '{}' | JSON dict |
| privacy_level | TEXT | DEFAULT 'public' | public, personal, sensitive |

**Indexes:**
- `idx_entities_type` on `(type)`
- `idx_entities_name_type` UNIQUE on `(canonical_name, type)`
- `idx_entities_privacy` on `(privacy_level)`

### 8.52 relationships

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | |
| from_entity | TEXT | NOT NULL, REFERENCES entities(id) ON DELETE CASCADE | |
| to_entity | TEXT | NOT NULL, REFERENCES entities(id) ON DELETE CASCADE | |
| type | TEXT | NOT NULL | |
| weight | REAL | DEFAULT 0.5 | |
| evidence | TEXT | DEFAULT '' | |
| source | TEXT | DEFAULT '' | |
| bidirectional | INTEGER | DEFAULT 0 | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |

**Indexes:**
- `idx_rel_from` on `(from_entity)`
- `idx_rel_to` on `(to_entity)`
- `idx_rel_type` on `(type)`

---

## 9. Stability Assessment

| Module | Rating | Rationale |
|--------|--------|-----------|
| `db_connection.py` | **STABLE** | Simple, well-tested thread-local pool. PRAGMAs are production-grade. |
| `migrations.py` | **STABLE** | Idempotent, additive-only. Risk: monolithic function will grow unwieldy. Version gating is in place but not yet exercised. |
| `learnings.py` | **STABLE** | Core path with rate limiting, dedup, quality gate, dual-write consistency tracking. Defensive coding throughout. |
| `vector_store.py` | **STABLE** | Mature hybrid search pipeline (BM25 + dense + FTS5 + cross-encoder + HyDE). Well-documented thread safety. Dimension mismatch detection. |
| `conversations.py` | **STABLE** | Straightforward CRUD with FTS and tag support. Content cap prevents unbounded writes. |
| `user_profile.py` | **STABLE** | Clean separation of concerns (relationship memory, timeline, identity, episodes, goals, tool outcomes). |
| `memory_graph.py` | **FRAGILE** | File-based persistence (GraphML). No locking for concurrent writes. Auto-link via vector search creates coupling to ChromaDB. Legacy JSON migration is one-shot. |
| `distill.py` | **STABLE** | Two distillation strategies (Jaccard, semantic). Quality gate is configurable. No side effects beyond DB writes. |
| `capabilities.py` | **STABLE** | Evolution layer with decay model, trend computation, cross-domain propagation, and usefulness gating. Well-structured. |
| `capabilities_db.py` | **STABLE** | Clean CRUD layer. Upsert logic for implementations is correct. |
| `journal.py` | **STABLE** | Minimal, correct. Tag normalization is shared pattern. |
| `improvements.py` | **STABLE** | Simple CRUD with status FSM. No complex logic. |
| `missions_db.py` | **STABLE** | Missions + background tasks. JSON serialization for plans/results. INSERT OR REPLACE pattern. |
| `projects_db.py` | **STABLE** | Projects + project context singleton. Lifecycle stage validation. |
| `tasks_db.py` | **STABLE** | Minimal coordinator task persistence. JSON fields auto-parsed on read. |
| `rl_preferences.py` | **STABLE** | 35-line module. Upsert with ON CONFLICT. |
| `telemetry_db.py` | **STABLE** | Append-only telemetry. Success rate aggregation with min_count threshold. |
| `routing_telemetry.py` | **STABLE** | Append-only router decision log. |
| `strategy_stats.py` | **STABLE** | Upsert success/fail counters with UNIQUE constraint. Preferred strategy selection. |
| `audit_session.py` | **STABLE** | Wakeup log, audit trail, session prompts, tool permission grants with fnmatch matching. |
| `plans_db.py` | **STABLE** | Study plans + layla plans + repo cognition snapshots. Status FSM validation. |
| `vector_qdrant.py` | **INCOMPLETE** | Functional adapter but not integrated into the main retrieval pipeline. No hybrid search, no reranking, no knowledge collection. Config-gated and secondary to ChromaDB. |
| `db.py` (barrel) | **STABLE** | Pure re-export facade. No logic. |
| `learnings_archive` (table) | **DEAD** | Table created in migration but no production code writes to it. |
| `golden_examples` (table) | **DEAD** | Table created in migration. No domain module writes to or reads from it. |
| `codex_discoveries` (table) | **INCOMPLETE** | Table created. No CRUD module found in `layla/memory/`. May be used by external services. |
| `journal_entity_links` (table) | **INCOMPLETE** | Table created. No CRUD module found in `layla/memory/`. May be used by external services. |

### Legend

- **STABLE** -- Production-ready, well-tested patterns, defensive error handling.
- **FRAGILE** -- Works but has structural risks (no locking, file-based persistence, tight coupling).
- **INCOMPLETE** -- Partially implemented; missing integration or unused infrastructure.
- **DEAD** -- Created but never used by any code path.
