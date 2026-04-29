# LAYLA — MASTER SYSTEM PLAN
## From Current State to Fully Operational Autonomous AI

**Version:** 2.0 (synthesised from repo audit + architecture blueprint + risk analysis)  
**Principle:** Most benefit, least work, deterministic verification at every step.  
**Constraint:** Never rewrite what works. Layer on top. Schema before scale.

---

## SYSTEM IDENTITY (LOCKED)

Layla is a **locally-sovereign, persistently-learning cognitive system**.

Non-negotiable properties:
1. **Persistent** — never re-learns the same data
2. **Structured memory** — not logs, not flat text
3. **Modular** — every subsystem is replaceable without breaking others
4. **Deterministic pipelines** — same input → same output (LLM calls aside)
5. **Observable** — every decision is traceable
6. **Incrementally improving** — each session leaves the system smarter

---

## CRITICAL INSIGHT FROM RISK ANALYSIS

> "You are not at risk of lack of tools or lack of architecture.  
> You are at risk of **too much system, not enough control**."

The single biggest failure point is **memory + indexing coherence**.  
If the five memory stores (SQLite, ChromaDB, knowledge/, codex, graph) disagree,  
every answer becomes unreliable regardless of how powerful the reasoning is.

**This plan is designed to fix that first.**

---

## CURRENT STATE AUDIT

### What we have and it works (do NOT touch)

| Component | File(s) | Status |
|---|---|---|
| Agent core loop | `agent_loop.py` | ✅ Stable |
| Tool execution | `core/executor.py` | ✅ Stable |
| SQLite memory | `layla/memory/db.py` | ✅ Stable |
| ChromaDB vectors | `layla/memory/vector_store.py` | ✅ Stable |
| Context manager | `services/context_manager.py` | ✅ Stable |
| LLM gateway | `services/llm_gateway.py` | ✅ Stable |
| 6-Aspect system | `services/aspect_behavior.py` | ✅ Stable |
| Planning engine | `services/plan_service.py`, `plan_executor.py` | ✅ Stable |
| Plugin system | `services/plugin_loader.py` | ✅ Stable |
| Voice TTS/STT | `services/stt.py`, `routers/voice.py` | ✅ Stable |
| Obsidian connector | `routers/obsidian.py` | ✅ Stable |
| German learning | `services/german_mode.py` | ✅ Stable |
| Syncthing sync | `services/syncthing_sync.py` | ✅ New |
| AirLLM runner | `services/airllm_runner.py` | ✅ New |
| Prompt compressor | `services/prompt_compressor.py` | ✅ New |
| Prompt optimizer | `services/prompt_optimizer.py` | ✅ New |
| KB builder | `services/kb_builder.py` | ✅ New |
| Health check suite | `scripts/run_all_checks.py` | ✅ New |

### What exists but is scattered (needs unification)

| Component | Files | Problem |
|---|---|---|
| Repo intelligence | `services/repo_cognition.py`, `code_intelligence.py` | Not connected to a single queryable index |
| Knowledge graph | `services/personal_knowledge_graph.py`, `graph_reasoning.py`, `graph_cache.py` | Using NetworkX in-memory, not persisted properly |
| Knowledge distiller | `services/knowledge_distiller.py` | Good extraction, output not standardised |
| Doc ingestion | `services/doc_ingestion.py` | Works but stores as flat files, not structured KB |
| Study service | `services/study_service.py` | SM-2 for German only, not generalised |
| Background intelligence | `services/background_intelligence.py` | Runs but findings not routed to memory |
| Codex | `routers/codex.py` | Endpoint exists, schema not enforced |

### Critical gaps (blocks daily use)

| Gap | Impact | Effort |
|---|---|---|
| No unified memory router | Queries hit wrong layer; duplicated facts | Medium |
| No canonical entity schema | Same person/concept stored 3 ways | Low |
| No incremental repo indexing | Full re-index on every change | Medium |
| No background scheduler | Must trigger everything manually | Low |
| No bulk ingestion script | Loading knowledge requires API calls | Low |
| Test coverage <80% | 5 pre-existing failures, unknown regressions | Medium |

---

## BUILD ORDER (STRICT — most value, lowest risk)

### PHASE A — MEMORY COHERENCE (do this first or nothing else works)

**Week 1-2 | ~12 hours | Unblock: everything**

#### A.1 Canonical Entity Schema (2 hours)

Create `agent/schemas/entity.py` — the single truth definition for all stored entities.

```python
# Every entity stored anywhere in Layla uses this schema.
@dataclass
class Entity:
    id: str              # SHA256(type + canonical_name)[:16]
    type: str            # "person" | "concept" | "technology" | "project" | "event" | "file"
    canonical_name: str  # Normalised: lowercase, stripped
    aliases: list[str]   # Other names for this entity
    description: str     # One-line summary
    tags: list[str]      # Free-form tags
    confidence: float    # 0.0-1.0 (how certain we are this is correct)
    source: str          # Where this came from
    created_at: str      # ISO datetime
    updated_at: str      # ISO datetime

# Every relationship also gets a schema:
@dataclass
class Relationship:
    id: str
    from_entity: str     # Entity.id
    to_entity: str       # Entity.id
    type: str            # "uses" | "knows" | "depends_on" | "is_part_of" | "created_by"
    weight: float        # 0.0-1.0 (relationship strength)
    evidence: str        # Where this relationship was extracted from
    created_at: str
```

This schema is used by: KB builder, doc ingestion, repo cognition, memory consolidation, codex.

#### A.2 Memory Router (4 hours)

Create `services/memory_router.py` — routes queries to the right store.

```python
# Logic:
# if query is factual/structured → SQLite codex tables
# if query is semantic/fuzzy     → ChromaDB vector search  
# if query is relational         → NetworkX graph (existing graph_reasoning.py)
# if query is recent/episodic    → SQLite conversations table
# if query is document-level     → knowledge/ directory via kb_builder
#
# For writes: write to ALL relevant stores simultaneously
# For reads: merge results, deduplicate by entity ID, rank by confidence
```

Hook into:
- `services/context_manager.py` (replace scattered retrieval calls)
- `agent_loop.py` `_semantic_recall()` (currently only hits ChromaDB)
- `routers/knowledge.py` (expose as `/memory/query`)

#### A.3 SQLite Codex Tables (3 hours)

Add to `layla/memory/db.py` — structured entity storage alongside conversations:

```sql
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.5,
    source TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    from_entity TEXT NOT NULL REFERENCES entities(id),
    to_entity TEXT NOT NULL REFERENCES entities(id),
    type TEXT NOT NULL,
    weight REAL DEFAULT 0.5,
    evidence TEXT DEFAULT '',
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_rel_from ON relationships(from_entity);
CREATE INDEX IF NOT EXISTS idx_rel_to ON relationships(to_entity);
```

Migration: run at startup in `_db_migrate()`.

#### A.4 Forgetting / Retention Policy (3 hours)

Extend `services/memory_consolidation.py` — the system already has retention policies.  
Add: **confidence decay** (facts not reinforced for 30 days drop confidence by 0.1/week)  
and **deduplication pass** (entities with >85% name similarity → merge with lower-confidence record losing).

---

### PHASE B — REPO INTELLIGENCE (unblocks coding assistance)

**Week 3-4 | ~16 hours | Unblock: code tasks, architecture questions**

#### B.1 Unified Repo Indexer (6 hours)

Create `services/repo_indexer.py` — wraps existing `repo_cognition.py` and `code_intelligence.py`  
into a single, incremental, file-hash-tracked pipeline.

```
Pipeline:
  scan(repo_root)
  → for each file: compute SHA256
  → skip if hash unchanged (stored in .layla/repo_index.json)
  → route by type:
      .py → Tree-sitter AST parse (extract: functions, classes, imports, docstrings)
      .md → chunk + extract entities
      .json/.yaml → config schema detection
      .js/.ts → function/class extraction (regex fallback if Tree-sitter unavailable)
  → embed all chunks → ChromaDB collection "repo_<workspace_name>"
  → extract entities → entities table
  → build dependency graph → NetworkX (persisted as GraphML)
  → generate codex entry for changed modules
```

Output: queryable index that answers:
- "What calls `function_name`?" (call graph)
- "Where is `ClassName` defined?" (index lookup)
- "What are the dependencies of `module.py`?" (dependency graph)
- "What changed since last index?" (hash comparison)

Tree-sitter (optional, graceful fallback):
```bash
pip install tree-sitter tree-sitter-python tree-sitter-javascript
```

If not installed: regex-based extraction (already in `code_intelligence.py`).

#### B.2 Codex Schema Enforcement (4 hours)

Create `agent/codex/` directory structure and generator:

```
agent/codex/
  _index.json          # Master index of all codex entries
  modules/             # One .md per Python module
  architecture.md      # Auto-generated from dependency graph
  api_surface.md       # Auto-generated from router inspection
  data_flows.md        # How data moves between services
```

Each module entry:
```markdown
# services/memory_router.py

**Purpose:** Route memory queries to correct storage layer  
**Inputs:** query: str, query_type: str  
**Outputs:** list[MemoryResult]  
**Pipeline:** classify → route → retrieve → merge → deduplicate  
**Storage:** reads from SQLite + ChromaDB + NetworkX  
**Failure modes:** ChromaDB unavailable → SQLite only fallback  
**Last indexed:** 2026-04-29T12:00:00Z  
```

Auto-generated at index time. Human-editable (system never overwrites manual sections).

#### B.3 Incremental Update Trigger (3 hours)

Extend `services/workspace_index.py` (already has `invalidate_if_changed()`):
- Add: trigger `repo_indexer.scan()` when workspace hash changes
- Add: `GET /workspace/index/status` → last indexed time, changed files, index health
- Add: file watcher using `watchdog` (optional) or poll-on-demand

#### B.4 NetworkX Graph Persistence (3 hours)

`services/personal_knowledge_graph.py` already uses NetworkX.  
Problem: graph is rebuilt from scratch each time.  
Fix: persist as GraphML + maintain incremental updates:

```python
# Save after every modification:
nx.write_graphml(graph, AGENT_DIR / ".layla/knowledge_graph.graphml")

# Load at startup:
if graphml_path.exists():
    graph = nx.read_graphml(graphml_path)
else:
    graph = nx.DiGraph()
```

The `.graphml` file already exists in the repo — just need consistent read/write.

---

### PHASE C — INGESTION PIPELINE (unblocks "loading with knowledge")

**Week 5 | ~10 hours | Unblock: research topics, personal codex**

#### C.1 Bulk Ingestion Script (4 hours)

Create `scripts/bulk_ingest.py`:

```bash
# Load everything in one command:
python scripts/bulk_ingest.py \
  --dirs ~/notes ~/research \
  --urls "https://docs.python.org" "https://fastapi.tiangolo.com" \
  --pdfs ~/papers/*.pdf \
  --topic "programming"

# Features:
# - Progress bar (rich or tqdm)
# - Hash-based deduplication (skip already-ingested content)
# - Respects robots.txt for URLs
# - Routes through memory_router (writes to SQLite + ChromaDB + graph)
# - Outputs: N chunks ingested, M articles generated, K entities discovered
```

This uses the existing `kb_builder.py` + new `memory_router.py`.

#### C.2 People Codex from Conversations (4 hours)

Create `services/people_codex.py`:

```python
# Scans conversation history for people mentions
# Extracts: names, relationships, communication patterns, topics discussed
# Stores: entities table (type="person") + relationships table

# Per-person entry:
{
  "id": "person_john_doe",
  "type": "person",
  "canonical_name": "John Doe",
  "aliases": ["John", "JD", "@johndoe"],
  "description": "Colleague at ACME, works on backend",
  "tags": ["colleague", "python", "backend"],
  "relationship_to_user": "colleague",
  "topics_discussed": ["FastAPI", "deployment", "code review"],
  "last_interaction": "2026-04-20",
  "communication_style": "direct, technical"
}
```

Endpoint: `GET /codex/people` → list of people Layla knows  
Endpoint: `GET /codex/people/{id}` → full person profile  
Auto-populated from conversation history; user can edit.

#### C.3 Structured Ingestion Sources Config (2 hours)

Add to `config.json` schema:

```json
{
  "ingestion_sources": [
    {"type": "directory", "path": "~/notes", "enabled": true, "schedule": "daily"},
    {"type": "url", "url": "https://docs.python.org/3/", "enabled": true},
    {"type": "obsidian", "vault": "~/Documents/Obsidian", "enabled": true}
  ]
}
```

Background scheduler (Phase D) reads this and runs ingestion on schedule.

---

### PHASE D — BACKGROUND SCHEDULER (unblocks autonomy)

**Week 6 | ~8 hours | Unblock: proactive operation**

#### D.1 APScheduler Integration (4 hours)

Create `services/scheduler.py` using APScheduler (lighter than Celery, no broker needed):

```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

# Jobs (all configurable in config.json):
scheduler.add_job(reindex_workspaces,  'interval', hours=2)
scheduler.add_job(run_ingestion_sources, 'cron', hour=3)  # 3am daily
scheduler.add_job(consolidate_memory,  'interval', hours=6)
scheduler.add_job(sync_obsidian,       'interval', minutes=30, 
                   id='obsidian_sync')
scheduler.add_job(check_staleness,     'cron', day_of_week='mon', hour=9)

# Start in main.py lifespan:
scheduler.start()
```

Config: `scheduler_enabled`, per-job `enabled` flags, custom intervals.

#### D.2 Job Status Endpoint (2 hours)

`GET /scheduler/status` → running jobs, last run times, next run times, failure counts.  
`POST /scheduler/run/{job_id}` → trigger a job immediately.

#### D.3 Proactive Suggestions (2 hours)

Extend `services/initiative_engine.py` (already exists):  
- After each index run: check for TODOs, failing tests, stale dependencies
- Surface 3 suggestions in the UI status panel (already has a section for this)
- User approves → task added to mission queue

---

### PHASE E — OBSERVABILITY (quality assurance)

**Week 7 | ~8 hours | Unblock: debugging, performance tuning**

#### E.1 Structured Logging (2 hours)

Extend `services/otel_export.py` (already exists):  
Every log line tagged with: `[workspace=X aspect=Y task_id=Z]`  
Already partially implemented via `services/task_context.py`.  
Fix: ensure all service modules import and use the structured logger.

#### E.2 Lightweight Metrics (no Prometheus yet — too heavy) (3 hours)

Create `services/metrics_collector.py`:

```python
# In-process metrics (no external service needed):
_METRICS = {
    "requests_total": 0,
    "tool_calls_total": defaultdict(int),
    "tool_errors_total": defaultdict(int),
    "avg_response_ms": 0,
    "context_pressure_max": 0.0,
    "memory_queries_total": 0,
    "index_runs_total": 0,
}

# Expose at: GET /metrics/summary
# Persist to: .layla/metrics.json (append-only, rotated daily)
```

Upgrade path to Prometheus: just expose `GET /metrics` in Prometheus text format  
(this is a 2-line change: `prometheus_client.generate_latest()`).

#### E.3 Health Dashboard (3 hours)

Extend the existing Status panel in the UI:
- Memory health: SQLite size, ChromaDB collection counts, graph node/edge counts
- Index health: last indexed, changed files pending, stale entries
- Scheduler health: job statuses, next runs
- Performance: avg response time (last 100), context pressure trend
- Confidence score badge (from `scripts/last_report.json`)

---

### PHASE F — LANGUAGE SYSTEM UPGRADE (generalise German mode)

**Week 8 | ~6 hours | Low risk, high daily value**

The German learning mode already exists and is excellent. Generalise it:

#### F.1 Generalised Language Profile (3 hours)

Extend `services/german_mode.py` → `services/language_system.py`:

```python
# Support any language, not just German
# Profile stored per language in: .layla/language_profiles/{lang_code}.json

# Config:
{
  "language_system_enabled": true,
  "languages": [
    {"code": "de", "target_level": "C1", "active": true},
    {"code": "es", "target_level": "B2", "active": false}
  ],
  "auto_detect": true,   # Detect language in user messages
  "correction_mode": "inline"  # "inline" | "end-of-message" | "off"
}
```

Use `langdetect` (pure Python, no API key) for auto-detection.

#### F.2 SM-2 for All Knowledge (3 hours)

Extend `services/study_service.py`:  
Currently language-only. Add: KB article review mode.  
Any KB article can be "added to study queue" → SM-2 scheduled review.  
"Study mode" sends Layla a KB article and she quizzes the user on it.

---

## VERIFICATION SYSTEM (DETERMINISTIC)

Every phase has a **deterministic verification gate**. Nothing proceeds until the gate passes.

### Gates

| After Phase | Gate command | Must produce |
|---|---|---|
| A (Memory coherence) | `python scripts/check_memory_coherence.py` | 0 conflicts, >90% entity dedup rate |
| B (Repo intelligence) | `python scripts/check_repo_index.py` | Index complete, 0 parse errors |
| C (Ingestion) | `python scripts/check_ingestion.py` | All sources reachable, 0 schema violations |
| D (Scheduler) | `python scripts/check_scheduler.py` | All jobs registered, last run within SLA |
| E (Observability) | `python scripts/run_all_checks.py` | Confidence score ≥ 85% |
| F (Language) | `python -m pytest tests/test_language_system.py -q` | 100% pass |

Each gate script follows the same interface as existing check scripts (exit 0 = pass, 1 = fail).  
All gates run in `run_all_checks.py` once implemented.

### Current gate status

```
python scripts/run_all_checks.py

Bug patterns         PASS   All checks passed.
Config validation    PASS   WARNINGS: 1 issue(s)
Import resolution    PASS   PASS
Security scan        PASS   All security checks passed.
API contracts        WARN   118 untested routes (acceptable)
DB schema            PASS   All DB checks passed.
UI symbol check      PASS   OK 1 html file, 381 defs
Pytest suite         ⚠      816/821 pass (5 pre-existing)

Confidence score: 75%  → target: 85% by Phase E
```

---

## RISK MITIGATIONS (from audit)

Each identified risk has a specific counter-measure:

| Risk | Counter-measure | Owner |
|---|---|---|
| Memory fragmentation | Canonical entity schema (Phase A.1) + memory router (A.2) | A |
| No canonical data model | `schemas/entity.py` enforced everywhere | A |
| Hidden state drift | Memory router: single write path for all stores | A |
| Embedding drift | Version-tag all ChromaDB collections with model ID; auto-reindex on model change | B |
| Memory bloat | Confidence decay + retention policy (A.4) | A |
| No forgetting | Explicit decay and dedup pass in memory_consolidation.py | A |
| Graph explosion | NetworkX only for local workspace; Neo4j only if graph > 100K nodes (Phase E+) | B |
| Codex false authority | Confidence score on every entry; flag low-confidence entries in UI | A |
| Ingestion noise | `min_confidence` filter in memory_router; entropy scoring in kb_builder | C |
| Tree-sitter gaps | Regex fallback already in code_intelligence.py | B |
| Scheduler race conditions | APScheduler job coalescing + file locks (services/file_lock.py already exists) | D |
| Scope creep | Hard rule: never build Phase N+2 until Phase N gate passes | ALL |
| Non-determinism | Verification gates enforce observable, testable outcomes | ALL |

---

## WHAT TO INSTALL

```bash
# Already installed (do not reinstall):
anthropic fastapi uvicorn chromadb tiktoken

# Phase A — memory coherence (pure Python, no deps):
# Nothing new needed

# Phase B — repo intelligence:
pip install tree-sitter tree-sitter-python tree-sitter-javascript networkx

# Phase C — ingestion:
pip install langdetect unstructured[pdf] pypdf watchdog rich

# Phase D — scheduler:
pip install apscheduler

# Phase E — observability (optional, upgrade path):
pip install prometheus-client

# Phase F — language system:
pip install langdetect  # Already installed in Phase C

# Intelligence layer (Phase 6, already integrated):
pip install llmlingua dspy-ai guidance airllm transformers torch
pip install spacy && python -m spacy download en_core_web_sm
```

---

## DO NOT BUILD YET

These are real requirements but building them now is premature and risky:

| Item | Why wait | When |
|---|---|---|
| Neo4j | NetworkX is sufficient until >100K nodes; Neo4j adds DevOps complexity | Phase F+ |
| Redis | SQLite with WAL mode serves as fast cache; add Redis only under load | After 100 concurrent users |
| Celery | APScheduler handles all needs without a broker/worker infrastructure | Never (APScheduler is enough) |
| Prometheus/Grafana | In-process metrics are sufficient; add only when debugging requires it | Phase E+ |
| GraphRAG (Microsoft) | Requires Azure OpenAI API; defeats sovereignty constraint | Optional, gated |
| STORM (Stanford) | Needs LLM API key; use kb_builder's own synthesis pipeline | When API key available |
| Full spaCy models (lg) | `en_core_web_sm` is enough; larger models need 800MB+ RAM | When quality gap identified |

---

## DAILY USE READINESS CHECKLIST

Layla is ready for daily use — research, coding, autonomous tasks — when:

- [ ] Phase A complete: memory router live, entity schema enforced, 0 coherence conflicts
- [ ] Phase B complete: repo indexer running, codex auto-generated for agent/ directory
- [ ] Phase C complete: `bulk_ingest.py` works end-to-end with your notes/docs
- [ ] Phase D complete: scheduler running, Obsidian synced automatically
- [ ] Health check: confidence score ≥ 85% (`python scripts/run_all_checks.py`)
- [ ] Test suite: 0 pre-existing failures (`python -m pytest tests/ -q --tb=no`)
- [ ] Voice chat end-to-end working
- [ ] Syncthing stable across 2 devices (if multi-device needed)
- [ ] At least 1000 KB chunks ingested from your personal knowledge

**Estimated: 4-6 weeks of focused work on Phases A-D**

---

## EXECUTION DISCIPLINE

1. **Start each session** with `python scripts/run_all_checks.py` to confirm baseline
2. **End each session** with a commit and re-run of health checks
3. **Never skip a gate** — if the gate doesn't pass, fix it before proceeding
4. **One phase at a time** — don't start B until A gate passes
5. **Smallest useful change** — prefer 50-line targeted additions over 500-line rewrites
6. **Test-driven** — write the test for the gate first, then build until it passes

---

## FILE MAP (what to create for each phase)

### Phase A
```
agent/schemas/entity.py              Canonical entity + relationship dataclasses
agent/schemas/__init__.py
agent/services/memory_router.py      Route queries to correct memory layer
agent/scripts/check_memory_coherence.py  Gate: 0 schema conflicts
```
Modify:
```
agent/layla/memory/db.py             Add entities + relationships tables
agent/services/memory_consolidation.py  Add confidence decay
agent/services/context_manager.py   Use memory_router for retrieval
```

### Phase B
```
agent/services/repo_indexer.py       Unified incremental repo indexer
agent/codex/                         Generated codex directory
agent/scripts/check_repo_index.py   Gate: index complete, 0 errors
```
Modify:
```
agent/services/workspace_index.py   Trigger repo_indexer on hash change
agent/services/personal_knowledge_graph.py  Persist GraphML on write
```

### Phase C
```
agent/scripts/bulk_ingest.py        One-command knowledge loading
agent/services/people_codex.py      Extract people from conversations
agent/scripts/check_ingestion.py    Gate: sources reachable, schemas valid
```
Modify:
```
agent/services/kb_builder.py        Route output through memory_router
agent/services/doc_ingestion.py     Use entity schema
```

### Phase D
```
agent/services/scheduler.py         APScheduler job registry
agent/scripts/check_scheduler.py    Gate: all jobs registered
```
Modify:
```
agent/main.py                       Start/stop scheduler in lifespan
agent/routers/system.py             Add /scheduler/status endpoint
```

### Phase E
```
agent/services/metrics_collector.py  In-process metrics
agent/scripts/check_metrics.py       Gate: metrics collecting
```
Modify:
```
agent/routers/system.py             Add /metrics/summary
agent/ui/index.html                 Extend status panel with metrics
```

### Phase F
```
agent/services/language_system.py   Generalised language profile (wraps german_mode.py)
agent/tests/test_language_system.py Tests for generalised system
```
Modify:
```
agent/services/german_mode.py       Delegate to language_system.py
agent/services/study_service.py     Add KB article study mode
```
