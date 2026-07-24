# LAYLA — FULL COMPLETION PLAN

**Date:** 2026-05-12  
**Baseline:** 858 tests, 12/12 checks green, 338 modules clean, 195 tools, 233 routes, 57 DB tables  
**Goal:** Every subsystem REAL. Every PARTIAL promoted. Every SCAFFOLD either promoted or honestly deferred. Every MISSING built. Zero lies in documentation.

**Build rule:** Never break what works. Every phase ends with `run_all_checks.py` still 12/12. Every new module gets tests.

---

## INVENTORY: WHAT REMAINS

Sources: subsystem audit (63 classified), verification sweep (9 domains), SYSTEM_PLAN.md phases, ROADMAP.md phases 7-10, plan file phases 11-14.

### By severity

| Priority | Count | Items |
|----------|-------|-------|
| **CRITICAL** (blocks daily use) | 5 | Memory router full enforcement, debate engine, `layla/codex/` module, `layla/scheduler/` extraction, test depth |
| **HIGH** (major functionality gap) | 8 | Research automation, bulk ingestion, Prometheus+structlog, reranker, expert routing, context budget reallocation, UI code-split, idle scheduler |
| **MEDIUM** (partial → real) | 9 | LLMLingua full activation, Obsidian bidirectional, autonomous monitoring coverage, aspect-keyed model routing, settings UI, Syncthing promotion, original_goal downstream preservation, confidence_pct calculation fix, repo_index signal fix |
| **LOW** (scaffold → real or polish) | 7 | AirLLM promotion, KB builder STORM/GraphRAG, language generalisation, tool descriptions hand-written, tool categorisation, mDNS/mesh networking, crash dumps |
| **DEFERRED** (future vision, not this cycle) | 4 | Neo4j graph at >100K nodes, Qdrant replacing ChromaDB, WireGuard mesh, Streamlit dev console |

**Total actionable items: 29**  
**Estimated hours: ~280**  
**Estimated calendar: 8-10 focused weeks**

---

## PHASE 1: STRUCTURAL INTEGRITY (Week 1-2, ~35 hours)

> Fix the load-bearing walls before adding rooms.

### 1.1 Complete Memory Router Enforcement (8 hours)

**Problem:** 12 production files still call `save_learning()` directly, bypassing the memory router. The lint check only catches `from layla.memory.db import save_learning` — it doesn't catch files that import `db` and then call `db.save_learning()`.

**Files to migrate:**
- `agent/main.py` — background job writes
- `agent/services/study_service.py` — study session outcomes
- `agent/routers/learn.py` — user-submitted learnings
- `agent/routers/memory.py` — memory import/export
- `agent/layla/tools/impl/memory.py` — tool-triggered saves
- `agent/services/memory_commands.py` — command-driven saves
- `agent/layla/memory/distill.py` — distillation outputs
- `agent/services/knowledge_distiller.py` — periodic distillation
- `agent/services/reflection_engine.py` — reflection outputs
- `agent/services/outcome_writer.py` — plan outcome saves

**Implementation:**
```python
# In each file, replace:
from layla.memory.db import save_learning
# With:
from services.memory_router import save_learning

# In the router itself, add write-through to all layers:
def save_learning(content, *, tags="", kind="fact", **kwargs):
    """Canonical write path — SQLite + ChromaDB + graph entity extraction."""
    result = _save_learning(content, tags=tags, kind=kind, **kwargs)
    _index_to_vector(content, result)      # ChromaDB
    _extract_and_link_entities(content)     # Graph
    return result
```

**Strengthen lint check:** Update `scripts/check_memory_router_enforcement.py` to also catch `db.save_learning(`, `learnings.save_learning(`, and any direct `INSERT INTO learnings` outside of `layla/memory/`.

**Gate:** `check_memory_router_enforcement.py` reports 0 offenders (currently 0 for the narrow check; will catch more with broadened pattern).

**Tests:** Add `test_memory_router_enforcement_comprehensive.py` — imports every module that was migrated and verifies the call path goes through `memory_router`.

---

### 1.2 Build `layla/scheduler/` Module (6 hours)

**Problem:** 10+ background jobs live inline in `main.py:384-587` making them untestable and `main.py` 1089 lines. Plan Phase 14 calls for a `layla/scheduler/` module.

**New files:**
```
agent/layla/scheduler/__init__.py      # Package init
agent/layla/scheduler/registry.py      # Job definitions + registration
agent/layla/scheduler/jobs.py          # All job functions (extracted from main.py)
agent/layla/scheduler/activity.py      # Activity window + game detection (from main.py:82-102)
agent/layla/scheduler/config.py        # Per-job config (interval, enabled, conditions)
```

**Implementation:**
```python
# registry.py
from apscheduler.schedulers.background import BackgroundScheduler

_scheduler: BackgroundScheduler | None = None

def create_scheduler(cfg: dict) -> BackgroundScheduler:
    """Create and configure the scheduler. Called from main.py lifespan."""
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _register_all_jobs(_scheduler, cfg)
    return _scheduler

def _register_all_jobs(sched, cfg):
    from layla.scheduler.jobs import (
        mission_worker_job, bg_reflect, bg_codex,
        bg_memory_consolidation, bg_initiative, bg_cleanup,
        bg_repo_reindex, scheduled_study_job, intelligence_job,
        rl_preference_job,
    )
    # Register each with configurable intervals from cfg
    ...
```

**Migration:** Replace inline job code in `main.py` with:
```python
from layla.scheduler.registry import create_scheduler
sched = create_scheduler(cfg)
sched.start()
app.state.scheduler = sched
```

**Gate:** `main.py` drops from ~1089 to ~750 lines. All jobs still run (verified by test that creates scheduler and checks job list). Existing scheduler-related tests still pass.

**Tests:** `tests/test_scheduler_registry.py` — verify all jobs register, activity guard works, game detection skips correctly.

---

### 1.3 Build `layla/codex/` Module (8 hours)

**Problem:** Plan Phase 11 calls for a canonical codex (Person/Project/Concept/Event/Skill) with its own CRUD module. Currently: entity schema exists in `schemas/entity.py`, tables exist in DB, `routers/codex.py` exists, but no `layla/codex/` package with the linker that auto-associates new learnings with existing entities.

**New files:**
```
agent/layla/codex/__init__.py          # Package init + public API
agent/layla/codex/codex_db.py          # CRUD for codex entities (wraps layla/memory/db entities table)
agent/layla/codex/linker.py            # Auto-link new learnings → existing codex entities
agent/layla/codex/enricher.py          # Extract entities from text (spaCy if available, regex fallback)
```

**Implementation:**

```python
# codex_db.py
def upsert_entity(entity_type, canonical_name, *, description="", tags=None,
                  confidence=0.5, source="", aliases=None) -> dict:
    """Create or update a codex entity. Deduplicates by type+name."""
    ...

def link_entities(from_id, to_id, rel_type, *, weight=0.5, evidence="") -> dict:
    """Create a relationship between two entities."""
    ...

def search_entities(query, *, entity_type=None, min_confidence=0.3, limit=20) -> list:
    """Search codex by name, alias, or description."""
    ...

def get_entity_graph(entity_id, depth=2) -> dict:
    """Return entity + N-hop neighborhood as {nodes, edges}."""
    ...
```

```python
# linker.py
def auto_link_learning(learning_content: str, learning_id: int) -> list[dict]:
    """
    Given a new learning, extract entity mentions and link to existing codex entries.
    Uses enricher.extract_entities() for NER, then fuzzy-matches against codex.
    Creates new entities if confidence > 0.7 and no match found.
    """
    entities = extract_entities(learning_content)
    links = []
    for ent in entities:
        match = find_best_codex_match(ent["name"], ent["type"])
        if match and match["score"] > 0.8:
            links.append(link_learning_to_entity(learning_id, match["id"]))
        elif ent["confidence"] > 0.7:
            new_ent = upsert_entity(ent["type"], ent["name"], source="auto-linker")
            links.append(link_learning_to_entity(learning_id, new_ent["id"]))
    return links
```

```python
# enricher.py
def extract_entities(text: str) -> list[dict]:
    """Extract named entities from text. Uses spaCy if available, regex fallback."""
    try:
        import spacy
        nlp = _get_spacy_model()
        doc = nlp(text)
        return [{"name": ent.text, "type": _map_spacy_label(ent.label_),
                 "confidence": 0.8} for ent in doc.ents]
    except ImportError:
        return _regex_entity_extraction(text)

def _regex_entity_extraction(text: str) -> list[dict]:
    """Fallback: detect capitalized phrases, URLs, file paths, @mentions."""
    ...
```

**Wire into memory router:** After every `save_learning()` call, run `auto_link_learning()` in the background.

**Gate:** `tests/test_codex_module.py` — CRUD ops, linker, entity graph retrieval. Codex entries appear after saving learnings with entity mentions.

---

### 1.4 Fix Confidence Metrics (3 hours)

**Problem:** `run_all_checks.py` reports `confidence_pct: 100` while `real_assertions: 2/3`. The confidence score should weight real assertions at >=50%.

**Files:** `agent/scripts/run_all_checks.py`

**Changes:**
- Weight real assertions at 50% of confidence score
- Fix `repo_index_populated` signal: accept "no sandbox_root configured" as N/A instead of false
- Result: real_assertions goes from 2/3 → 3/3 (or 2/2 with N/A), confidence becomes truthful

**Also fix:** Remove duplicate "valorant" in `_SCHEDULER_SKIP_PROCESSES` (main.py line 83).

**Gate:** `real_assertions` = 3/3 or all-applicable passing. `confidence_pct` reflects reality.

---

### 1.5 Preserve `original_goal` Downstream (4 hours)

**Problem:** `agent_loop.py:3078` captures `goal_original` but the optimized goal becomes canonical for memory writes, reflection, and planning. User's authored text is lost.

**Files:** `agent/agent_loop.py`

**Changes:**
- Thread `original_goal` into `state["original_goal"]` (already captured at line 3078)
- In all `save_learning()` calls within autonomous_run: use `original_goal` as the human-readable source, not the optimized rewrite
- In reflection engine: reference `original_goal` for "what did the user actually ask"
- In plan titles/descriptions: use `original_goal`

**Gate:** New test `test_original_goal_preservation.py` — run autonomous flow with an optimized goal, verify learnings reference the original text.

---

### 1.6 Test Depth Improvement — Phase 1 (6 hours)

**Problem:** 65% of source modules have no test. Assert-to-test ratio is 2.8. Near-zero error-path testing.

**Priority targets (highest-traffic untested modules):**
1. `services/context_manager.py` — context assembly (used every request)
2. `services/llm_gateway.py` — LLM dispatch hub (26 importers)
3. `services/coordinator.py` — plan execution coordinator (7 importers)
4. `services/reflection_engine.py` — background reflection
5. `layla/memory/vector_store.py` — ChromaDB operations

**Per module:**
- 5-8 test functions covering happy path + error path
- At least 2 `pytest.raises` per module (timeout, invalid input, missing config)
- Use `monkeypatch` to mock LLM calls; test real DB operations against tmp SQLite

**Gate:** Test count rises from 858 → 900+. Assert-to-test ratio rises to ≥3.5 for new tests.

---

## PHASE 2: DEBATE ENGINE + ASPECT INTELLIGENCE (Week 3-4, ~40 hours)

> Close the single biggest north-star gap.

### 2.1 Debate / Council / Tribunal Engine (20 hours)

**Problem:** North-star calls multi-aspect deliberation "first-class." Zero implementation exists. Today: solo aspect per turn.

**New files:**
```
agent/services/debate_engine.py         # Core multi-aspect deliberation
agent/services/council.py               # 3-aspect council mode
agent/services/tribunal.py              # Full 6-aspect tribunal (rare, expensive)
agent/routers/debate.py                 # API surface
agent/tests/test_debate_engine.py       # Tests
```

**Modes:**
```python
class DeliberationMode(str, Enum):
    SOLO = "solo"           # Current behavior (1 aspect)
    DEBATE = "debate"       # 2 aspects argue, synthesize
    COUNCIL = "council"     # 3 aspects deliberate, vote
    TRIBUNAL = "tribunal"   # All 6 aspects, full deliberation (expensive)

# Config:
# deliberation_mode: "solo" | "debate" | "council" | "tribunal" | "auto"
# deliberation_auto_threshold: complexity score that triggers multi-aspect
```

**Implementation — debate_engine.py:**
```python
async def run_debate(goal: str, state: dict, aspects: list[str],
                     cfg: dict) -> DebateResult:
    """
    Run multi-aspect deliberation.
    1. Each aspect generates an independent response (parallel LLM calls)
    2. Responses are exchanged — each aspect critiques the others
    3. Synthesis pass: merge into a single response with noted disagreements
    """
    # Phase 1: Independent generation
    responses = {}
    for aspect_id in aspects:
        system_prompt = build_aspect_system_prompt(aspect_id, state)
        response = await llm_gateway.run_completion_async(
            system_prompt + goal, aspect_id=aspect_id
        )
        responses[aspect_id] = response

    # Phase 2: Cross-critique
    critiques = {}
    for aspect_id in aspects:
        other_responses = {k: v for k, v in responses.items() if k != aspect_id}
        critique_prompt = build_critique_prompt(aspect_id, goal, other_responses)
        critique = await llm_gateway.run_completion_async(critique_prompt)
        critiques[aspect_id] = critique

    # Phase 3: Synthesis
    synthesis_prompt = build_synthesis_prompt(goal, responses, critiques)
    final = await llm_gateway.run_completion_async(synthesis_prompt)

    return DebateResult(
        final_response=final,
        aspect_responses=responses,
        critiques=critiques,
        mode=DeliberationMode.DEBATE,
        participating_aspects=aspects,
    )
```

**Auto-trigger logic:**
```python
# In agent_loop.py, before generating response:
def _select_deliberation_mode(goal, state, cfg):
    mode = cfg.get("deliberation_mode", "auto")
    if mode != "auto":
        return mode

    # Heuristic: complex/ethical/ambiguous → multi-aspect
    complexity = estimate_task_complexity(goal, state)
    if complexity > cfg.get("deliberation_auto_threshold", 0.7):
        return "council"
    if any(kw in goal.lower() for kw in ("should i", "trade-off", "compare",
           "ethical", "risky", "dangerous", "controversial")):
        return "debate"
    return "solo"
```

**Aspect selection for debate/council:**
```python
# Select aspects based on task domain:
ASPECT_DOMAINS = {
    "morrigan": ["strategy", "leadership", "battle", "authority"],
    "nyx":      ["analysis", "investigation", "depth", "truth"],
    "echo":     ["empathy", "communication", "people", "feelings"],
    "eris":     ["creativity", "chaos", "alternatives", "disruption"],
    "cassandra": ["code", "engineering", "debugging", "architecture"],
    "lilith":   ["ethics", "boundaries", "independence", "warning"],
}
# Pick 2-3 most relevant aspects for the task domain
```

**API:**
```
POST /agent { "message": "...", "deliberation_mode": "debate" }
  → Response includes: aspect_responses, critiques, synthesis

GET /debate/history?limit=10
  → Past deliberations with outcomes
```

**UI integration:**
- Show aspect avatars during deliberation
- Expandable "debate log" showing each aspect's position
- Visual vote tally for council decisions

**Gate:** `test_debate_engine.py` — 15+ tests covering solo, debate, council modes. Mock LLM responses. Verify synthesis includes all aspect positions.

---

### 2.2 Aspect-Keyed Model Routing (6 hours)

**Problem:** `services/model_router.py` routes by reasoning_mode + task_type, not by aspect. Plan calls for per-aspect model differentiation.

**Files:** `agent/services/model_router.py`, `agent/runtime_safety.py`

**Changes:**
```python
# New config key:
"aspect_model_overrides": {
    "cassandra": {"preferred_model": "deepseek-coder-v2", "reasoning_mode": "deep"},
    "eris": {"preferred_model": "dolphin-mixtral", "temperature_boost": 0.2},
    "nyx": {"preferred_model": "qwen2.5-coder", "reasoning_mode": "analytical"},
}

# In route_model_for_task():
def route_model_for_task(task_type, reasoning_mode, *, aspect_id=None, **kwargs):
    # Check aspect override first
    if aspect_id and cfg.get("aspect_model_overrides", {}).get(aspect_id):
        override = cfg["aspect_model_overrides"][aspect_id]
        if "preferred_model" in override:
            return _resolve_model(override["preferred_model"])
    # Fall through to existing logic
    ...
```

**Gate:** Tests verify aspect override takes precedence; fallback to standard routing when no override configured.

---

### 2.3 Aspect-Tool Ordering (4 hours)

**Problem:** `services/aspect_behavior.py:146` returns step caps per aspect, but tools are not aspect-biased.

**Files:** `agent/services/aspect_behavior.py`, `agent/agent_loop.py`

**Changes:**
```python
# In aspect_behavior.py, add:
ASPECT_TOOL_PREFERENCES = {
    "cassandra": {"boost": ["read_file", "grep_code", "run_python", "git_diff"],
                  "suppress": ["fetch_url"]},
    "echo":     {"boost": ["search_memories", "save_learning"],
                  "suppress": ["run_shell"]},
    "nyx":      {"boost": ["grep_code", "read_file", "understand_file"],
                  "suppress": []},
    "eris":     {"boost": ["web_search", "fetch_url", "brainstorm"],
                  "suppress": []},
    ...
}

def get_tool_bias(aspect_id: str) -> dict:
    """Return tool preference weights for an aspect."""
    return ASPECT_TOOL_PREFERENCES.get(aspect_id, {})
```

In `agent_loop.py` decision logic: when LLM proposes a tool, check aspect bias. Boost score for preferred tools, reduce for suppressed (never block — just weight).

**Gate:** Test that Cassandra's tool selection favors code tools over web tools.

---

### 2.4 Autonomous Monitoring Event Coverage (4 hours)

**Problem:** `ui/js/layla-autonomous.js` exists but streaming event coverage from `agent_loop.py` is incomplete.

**Files:** `agent/agent_loop.py`, `agent/ui/js/layla-autonomous.js`

**Emit events for:**
- Step start/complete with tool name and duration
- Decision reasoning ("chose X because Y")
- Aspect switch events
- Plan progress (step N of M)
- Error/retry events
- Deliberation events (debate start, aspect responses, synthesis)

**Format:**
```python
# In agent_loop.py, add emit_progress() calls:
emit_progress({
    "type": "step_start",
    "step_index": i,
    "total_steps": len(steps),
    "tool": tool_name,
    "aspect_id": current_aspect,
    "timestamp": utcnow().isoformat()
})
```

**Gate:** UI shows real-time step progression for autonomous runs.

---

### 2.5 Settings UI Panel (6 hours)

**Problem:** No dedicated `layla-settings.js`. Settings surface only via wizard + ad-hoc forms.

**New file:** `agent/ui/js/layla-settings.js`

**Sections:**
- General: default aspect, deliberation mode, language, timezone
- Safety: tool permissions, sandbox settings, network access
- Cognitive: toggle each cognitive layer (personality, lens, rhythm, reflection, knowledge, operational guidance)
- Models: preferred model, aspect overrides, context budget limits
- Voice: TTS engine, speech rate, volume, per-aspect voice
- Scheduler: enable/disable per job, adjust intervals
- Privacy: data directory, export all data, delete all data
- Advanced: debug logging, performance mode, experimental features

**Warframe aesthetic:** Dark panels with angular chrome borders, aspect-colored toggle switches, scan-line overlay on headers.

**Gate:** All settings persist to `runtime_config.json` via existing `/settings` API. Each section toggleable.

---

## PHASE 3: OBSERVABILITY + METRICS (Week 5, ~25 hours)

> Make every decision traceable. Debug anything.

### 3.1 Prometheus Metrics (8 hours)

**New files:**
```
agent/services/metrics.py              # prometheus_client registry + metric definitions
agent/routers/metrics.py               # GET /metrics (Prometheus scrape endpoint)
```

**Add to requirements.txt:** `prometheus_client>=0.20`

**Metrics:**
```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Counters
TOOL_CALLS = Counter("layla_tool_calls_total", "Total tool calls", ["tool_name", "result"])
MEMORY_OPS = Counter("layla_memory_ops_total", "Memory operations", ["layer", "op"])
LLM_REQUESTS = Counter("layla_llm_requests_total", "LLM requests", ["model", "aspect_id"])
SCHEDULER_RUNS = Counter("layla_scheduler_runs_total", "Scheduler job runs", ["job_name", "status"])

# Histograms
TOOL_DURATION = Histogram("layla_tool_duration_seconds", "Tool call duration", ["tool_name"])
LLM_LATENCY = Histogram("layla_llm_latency_seconds", "LLM request latency", ["model"])
EMBEDDING_LATENCY = Histogram("layla_embedding_latency_seconds", "Embedding latency")

# Gauges
CONTEXT_PRESSURE = Gauge("layla_context_pressure_ratio", "Context window pressure")
ACTIVE_MISSIONS = Gauge("layla_active_missions", "Currently running missions")
MEMORY_SIZE = Gauge("layla_memory_entries", "Total memory entries", ["type"])
```

**Instrument:** Add 1-2 line metric increments to:
- `core/executor.py` (tool calls)
- `services/llm_gateway.py` (LLM requests)
- `services/memory_router.py` (memory ops)
- `layla/scheduler/jobs.py` (scheduler runs)
- `services/context_manager.py` (context pressure)

**Endpoint:** `GET /metrics` → Prometheus text format

**Gate:** `curl /metrics` returns non-empty Prometheus output with at least 5 metric families.

---

### 3.2 Structured Logging with structlog (6 hours)

**Add to requirements.txt:** `structlog>=24.0`

**New file:** `agent/services/structured_log.py`

```python
import structlog

def configure_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )

def bind_context(**kwargs):
    """Bind context vars for structured logging: aspect_id, run_id, workspace."""
    structlog.contextvars.bind_contextvars(**kwargs)
```

**Migration:** Replace `logging.getLogger("layla")` with `structlog.get_logger()` in the 15 highest-traffic modules. Keep stdlib logging as fallback for modules not yet migrated.

**Integration:** In `agent_loop.py`, bind `aspect_id`, `run_id`, `workspace` at start of every run.

**Gate:** Log output is JSON. Each line carries `aspect_id` + `run_id` when available.

---

### 3.3 Grafana Dashboard (5 hours)

**New files:**
```
docker/grafana/provisioning/dashboards/layla.json    # Dashboard definition
docker/grafana/provisioning/datasources/prometheus.yml
docker/docker-compose.grafana.yml                    # Optional Grafana + Prometheus stack
```

**Dashboard panels:**
- Tool call success rate (last 24h)
- LLM latency histogram (p50/p95/p99)
- Memory operations by layer
- Context pressure over time
- Active missions timeline
- Scheduler job status grid
- Embedding latency trend

**Optional:** User runs `docker compose -f docker/docker-compose.grafana.yml up` to get Grafana. Works without Docker too (just use `/metrics` endpoint directly).

**Gate:** Dashboard JSON is valid. `docker compose config` validates. `/metrics` endpoint serves data.

---

### 3.4 Crash Dumps and Error Reporting (3 hours)

**Files:** `agent/services/crash_handler.py` (new)

```python
import sys, traceback, json
from pathlib import Path

CRASH_DIR = Path.home() / ".layla" / "crashes"

def install_crash_handler():
    """Install global exception handler that writes crash dumps."""
    original_hook = sys.excepthook

    def crash_hook(exc_type, exc_value, exc_tb):
        CRASH_DIR.mkdir(parents=True, exist_ok=True)
        dump = {
            "timestamp": utcnow().isoformat(),
            "exception": str(exc_value),
            "type": exc_type.__name__,
            "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
        }
        path = CRASH_DIR / f"crash_{int(time.time())}.json"
        path.write_text(json.dumps(dump, indent=2))
        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = crash_hook
```

**Wire into:** `main.py` lifespan startup.

**Gate:** Crash dump directory exists after startup. Simulated exception produces valid JSON dump.

---

### 3.5 Health Dashboard UI Enhancement (3 hours)

**Files:** `agent/ui/js/layla-perf.js` (extend)

Add to the existing performance panel:
- Memory health: SQLite DB size, ChromaDB collections, graph nodes/edges
- Scheduler: job list with last-run times, next-run times, status badges
- Metrics: live counters from `/metrics/summary` (no Prometheus required)
- Confidence score badge from `last_report.json`
- Context pressure gauge (real-time)

**Gate:** Panel shows live data. All sections populate.

---

## PHASE 4: RESEARCH AUTOMATION + INGESTION (Week 6-7, ~40 hours)

> Make Layla a knowledge machine.

### 4.1 Autonomous Research Loop (12 hours)

**New file:** `agent/services/research_orchestrator.py`

**Workflow:**
```
User: "Research FastAPI async patterns"
  → Decompose into 5-8 sub-questions (LLM)
  → For each sub-question:
      → Search existing KB + workspace (local first)
      → If permitted: web search (DuckDuckGo) → fetch top 3 URLs → extract text
      → Score source credibility (domain authority heuristic)
  → Synthesize STORM-style article from all sources
  → Extract entities → auto-link to codex
  → Save to knowledge/_generated/ as markdown
  → Report summary + confidence score + citation list
```

**Key functions:**
```python
async def research_topic(topic: str, *, depth: str = "standard",
                         allow_web: bool = True, max_sources: int = 15) -> ResearchResult:
    """Full research pipeline. Returns structured article + metadata."""

def decompose_topic(topic: str) -> list[str]:
    """Break topic into 5-8 searchable sub-questions."""

def synthesize_article(topic: str, sources: list[Source]) -> str:
    """STORM-style synthesis: outline → section drafts → merge → polish."""

def score_credibility(url: str, content: str) -> float:
    """Domain authority + content quality heuristic. 0.0-1.0."""
```

**SSE progress:**
```
data: {"type": "decomposing", "sub_questions": 6}
data: {"type": "searching", "question": "What is FastAPI async?", "index": 1, "total": 6}
data: {"type": "fetching", "url": "https://...", "index": 2, "total": 5}
data: {"type": "synthesizing", "sections_complete": 3, "total_sections": 6}
data: {"type": "done", "article_id": "...", "confidence": 0.85}
```

**API:**
```
POST /research {"topic": "...", "depth": "deep", "allow_web": true}
GET /research/{id}/status
GET /research/{id}/article
```

**Gate:** End-to-end test: research a topic → article generated → entities extracted → KB updated. Mock web fetches.

---

### 4.2 Bulk Ingestion Pipeline (8 hours)

**New files:**
```
agent/scripts/bulk_ingest.py            # CLI script
agent/layla/ingestion/__init__.py       # Pipeline entry point
agent/layla/ingestion/extractors.py     # Text extraction (PDF, DOCX, HTML, plain text)
agent/layla/ingestion/chunker.py        # Semantic chunking with overlap
agent/layla/ingestion/web.py            # URL → clean text (trafilatura, already in requirements)
```

**CLI:**
```bash
python scripts/bulk_ingest.py \
  --dirs ~/notes ~/research \
  --urls "https://docs.python.org" \
  --pdfs ~/papers/*.pdf \
  --topic "programming" \
  --dry-run  # Preview what would be ingested
```

**Pipeline:**
```
input (file/URL/text)
  → extract text (PDF via pypdf/unstructured, HTML via trafilatura, MD/TXT direct)
  → chunk (sentence-aware, 512 tokens, 64 token overlap)
  → embed → ChromaDB upsert via memory_router
  → extract entities → codex auto-link
  → generate KB article (optional, for large documents)
  → deduplicate (SHA256 content hash, skip if already ingested)
```

**Progress:** Rich progress bar with ETA. Summary report at end.

**Gate:** Ingest a test directory of 10 files → chunks appear in ChromaDB → entities in codex.

---

### 4.3 Topic Graph Visualization (5 hours)

**New file:** `agent/services/topic_graph.py`

Build a graph of how KB articles relate to each other based on shared entities and content similarity.

**API:** `GET /intelligence/kb/graph` → D3-compatible `{nodes: [...], edges: [...]}`

**UI:** Force-directed graph in the Research panel. Click node → article preview.

**Gate:** Graph populates after research/ingestion. D3 JSON validates.

---

### 4.4 Citation Tracking (4 hours)

**Extend:** `agent/services/kb_builder.py`, `agent/layla/memory/db.py`

- Store source URL, fetch date, content hash per article
- Staleness detection: flag articles whose sources are >30 days old
- `GET /intelligence/kb/articles/{id}/citations`
- Attribution in responses: "based on [article title]"

**Gate:** Citations appear for researched articles. Stale articles flagged.

---

### 4.5 LLMLingua Full Activation (4 hours)

**Problem:** Only Tier-3 heuristic runs. `llmlingua` not in requirements.txt.

**Changes:**
- Add `llmlingua` to requirements.txt as optional extra: `llmlingua>=0.2; extra == "compression"`
- In `services/prompt_compressor.py`: add graceful detection — if `llmlingua` installed, use Tier-1; otherwise fall back to Tier-3 (current behavior)
- Document in `MODELS.md` / `CONFIG_REFERENCE.md` how to enable full compression

**Gate:** With `llmlingua` installed: Tier-1 compression activates. Without: Tier-3 still works. No import errors either way.

---

### 4.6 Reranker Layer (4 hours)

**New file:** `agent/services/reranker.py`

```python
def rerank(query: str, documents: list[str], *, top_k: int = 5) -> list[dict]:
    """
    Rerank documents by relevance to query.
    Uses cross-encoder if sentence-transformers available, otherwise BM25 score.
    """
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        scores = model.predict([(query, doc) for doc in documents])
        ranked = sorted(zip(documents, scores), key=lambda x: -x[1])
        return [{"content": doc, "score": float(score)} for doc, score in ranked[:top_k]]
    except ImportError:
        return _bm25_rerank(query, documents, top_k)
```

**Wire into:** `services/retrieval.py` — after vector search, before returning results to context.

**Gate:** Retrieval quality test: reranker moves more relevant docs to top positions.

---

### 4.7 Obsidian Bidirectional Sync (3 hours)

**Problem:** Currently one-way export. Plan Phase 5.1 calls for bidirectional.

**Extend:** `agent/services/obsidian_sync.py`

Add:
- Watch Obsidian vault for changes (file hash comparison)
- Import new/modified `.md` files from Obsidian → Layla knowledge
- Conflict resolution: newer modification wins, with backup of losing version
- Sync status endpoint: `GET /obsidian/sync/status`

**Gate:** Change a file in Obsidian vault → appears in Layla knowledge. Change in Layla → exported to Obsidian.

---

## PHASE 5: ADVANCED TOKEN MANAGEMENT (Week 8, ~20 hours)

> Never hit a context limit unexpectedly. Every token earns its place.

### 5.1 Dynamic Context Budget Reallocation (6 hours)

**Extend:** `agent/services/context_manager.py`, `agent/services/prompt_tier_budget.py`

```python
# Auto-shrink low-signal sections when pressure > 85%
def rebalance_budget(sections: dict[str, BudgetSection]) -> dict[str, BudgetSection]:
    total_used = sum(s.used for s in sections.values())
    total_budget = sum(s.budget for s in sections.values())
    pressure = total_used / max(total_budget, 1)

    if pressure > 0.85:
        # Compress memory section first (most compressible)
        sections["memory"].budget = int(sections["memory"].budget * 0.6)
        # Then workspace
        sections["workspace"].budget = int(sections["workspace"].budget * 0.7)
    return sections
```

**Config:** `dynamic_budget_enabled`, `budget_pressure_threshold` (default 0.85)

**Gate:** Test that context never overflows on 50-step autonomous run.

---

### 5.2 Conversation Chunking for Long Tasks (5 hours)

**Extend:** `agent/agent_loop.py`, `agent/services/task_budget.py`

For autonomous tasks >50 steps:
- Auto-split into sessions with handoff summaries
- Each chunk gets a "task continuation prompt" with compressed prior state
- Memory carries forward via learnings, not raw conversation

**Config:** `auto_chunk_long_tasks`, `chunk_step_threshold` (default 50)

**Gate:** 60-step autonomous run completes without context overflow.

---

### 5.3 Token Pressure Dashboard (4 hours)

**New file:** `agent/ui/js/layla-context-viz.js`

Real-time stacked bar chart:
- Segments: identity | memory | workspace | tools | conversation
- Color: green (<60%) → yellow (60-85%) → red (>85%)
- Click segment to see contents and compression options
- ARIA labels, keyboard navigable

**Gate:** Dashboard updates in real-time during conversation.

---

### 5.4 Selective Context Integration (3 hours)

**Extend:** `agent/services/prompt_compressor.py`

Add Tier-0: Selective Context (token-level pruning via small LM).
- Graceful: only if `selective-context` package installed
- Otherwise fall through to existing tiers

**Gate:** With package installed: compression ratio improves 10-30%. Without: no change.

---

### 5.5 ContextCite Attribution (2 hours)

**New file:** `agent/services/context_attribution.py`

After each response, attribute which context snippets contributed most.
- Store attribution scores in `tool_calls` table alongside response
- UI: hover over response to see "based on: [source]" tooltip

**Gate:** Attributions appear for responses that used retrieved context.

---

## PHASE 6: FULL AUTONOMY ENGINE (Week 9-10, ~35 hours)

> Layla operates independently for hours.

### 6.1 Mission Manager UI Enhancement (8 hours)

**Extend:** `agent/ui/js/layla-missions.js`

Kanban board:
- Columns: backlog | running | paused | done
- Each card: goal, progress %, estimated time, sub-tasks, artifacts
- Drag between columns to change state
- "Launch from chat" — one-click mission creation
- Pause / resume / abort controls
- Mission replay: re-run with fresh data

**Warframe aesthetic:** Dark cards with angular chrome, aspect-colored progress bars, glow on active missions.

---

### 6.2 Long-Horizon Planning (8 hours)

**Extend:** `agent/services/plan_service.py`, `agent/services/planner.py`

Multi-day task decomposition:
- Break 40-hour tasks into day-sized chunks
- Dependency graph: task B waits for task A's artifact
- Resource estimation: "~3 hours, ~2M tokens"
- Checkpoint saves: resume after shutdown
- Integration with scheduler: auto-resume missions

---

### 6.3 Tool Result Learning (5 hours)

**Extend:** `agent/services/experience_replay.py`

After each tool call:
- Score result quality (0-5 by LLM self-evaluation)
- Store (tool, args_pattern, result_quality) in experience table
- Planner consults before choosing tools: "last 10 reads of this file type = 4.2/5"
- Auto-tune tool arguments based on success patterns

---

### 6.4 Proactive Initiative Engine Enhancement (4 hours)

**Extend:** `agent/services/initiative_engine.py`

Background monitoring:
- Detect: failing tests, TODO comments, stale dependencies, lint errors
- Surface 3 proactive suggestions per session
- User approves → task joins mission queue
- Configurable: `initiative_enabled`, `initiative_max_suggestions`

---

### 6.5 Self-Improvement Feedback Loop (5 hours)

**Extend:** `agent/services/self_improvement.py`

Post-mission scoring:
- Plan quality, tool selection, response quality
- Low-scoring patterns → auto-generated improvement hypotheses
- Layla proposes edits to her own system prompt / aspect behavior
- User approves/denies; approved changes committed

---

### 6.6 Idle Scheduler (5 hours)

**New file:** `agent/layla/scheduler/idle_detector.py`

Real idle detection (not just game-process skip):
- CPU usage < 30% for 5 min → idle
- No keyboard/mouse input for 10 min → idle
- Combine with game detection (existing)
- When idle: run low-priority background tasks (reindex, consolidation, research queue)
- When active: pause background tasks, prioritize responsiveness

**Config:** `idle_detection_enabled`, `idle_cpu_threshold`, `idle_timeout_minutes`

---

## PHASE 7: KNOWLEDGE LOADING + LANGUAGE (Week 11-12, ~25 hours)

> Layla becomes your second brain.

### 7.1 Personal Research Profile (5 hours)

**Extend:** `agent/services/personal_knowledge_graph.py`

- Build personal topic graph from all ingested knowledge
- Identify expertise areas (highly-connected graph clusters)
- Identify knowledge gaps (isolated nodes with few edges)
- Weekly "knowledge summary" learning: what you know, what you're learning, what's missing

---

### 7.2 Spaced Repetition for All Knowledge (5 hours)

**Extend:** `agent/services/study_service.py`

Currently SM-2 for German only. Generalize:
- Any KB article can be "added to study queue"
- SM-2 scheduled review with configurable intervals
- "Study mode": Layla quizzes you on content
- Confidence tracking per article
- Study calendar: due articles per day

---

### 7.3 Generalize Language System (5 hours)

**Extend:** `agent/services/german_mode.py` → `agent/services/language_system.py`

- Support any language (not just German)
- Per-language profile in `.layla/language_profiles/{lang_code}.json`
- Auto-detection via `langdetect` (pure Python)
- Correction modes: inline, end-of-message, off
- CEFR level tracking per language

---

### 7.4 Research-to-Code Pipeline (5 hours)

**Extend:** `agent/services/engineering_pipeline.py`

```
User: "implement what you know about FastAPI rate limiting"
  → Retrieve KB article on FastAPI + rate limiting
  → Synthesize implementation plan
  → Write code with cited comments
  → Run tests
  → Save implementation as learning
```

Full loop: research → plan → code → test → document → learn

---

### 7.5 People Codex from Conversations (5 hours)

**New file:** `agent/services/people_codex.py`

Scan conversation history for people mentions:
- Extract: names, relationships, communication patterns, topics
- Store as codex entities (type="person") with relationships
- `GET /codex/people` → list of people Layla knows
- Auto-populated, user-editable

---

## PHASE 8: SCAFFOLD PROMOTION + POLISH (Week 13-14, ~30 hours)

> Promote every scaffold to real or honestly defer it.

### 8.1 AirLLM Promotion (4 hours)

Add `airllm` to requirements.txt as optional extra.
Wire one production importer beyond the router (e.g., scheduler job that auto-selects AirLLM for large models when GPU VRAM < model requirement).
Add integration test that loads a tiny model via AirLLM path.

---

### 8.2 KB Builder STORM/GraphRAG (6 hours)

Promote to at least one real production path:
- STORM: use in research_orchestrator.py for article synthesis (if `knowledge-storm` installed)
- GraphRAG: use in topic_graph.py for entity extraction (if `graphrag` installed)
- Both graceful-degrade to existing heuristics

---

### 8.3 Syncthing Promotion (4 hours)

Wire one production importer: nightly auto-rescan job in scheduler.
Add sync status to the health dashboard.
Document setup in `docs/GETTING_STARTED.md`.

---

### 8.4 UI Code-Split (8 hours)

**Problem:** `ui/js/layla-app.js` is 4024 lines / 181KB.

Split into ES modules:
```
layla-app.js        → core state machine + routing (~800 lines)
layla-chat.js       → chat rendering + streaming (~600 lines)  [already partially exists as chat.js]
layla-input.js      → input handling + autocomplete (~400 lines)
layla-aspect.js     → aspect switching + animations (~300 lines)
layla-voice.js      → voice recording + playback (~300 lines)
layla-sidebar.js    → left panel management (~200 lines) [already exists as sidebar.js]
layla-panels.js     → right panel management (~200 lines) [already exists as panels.js]
layla-utils.js      → shared utilities (~200 lines)
```

Use native ES module `<script type="module">` for new splits. Keep backward-compatible `<script>` loading for vendor libs.

**Gate:** All UI functions still work. No console errors. Total JS size unchanged (just distributed).

---

### 8.5 Tool Descriptions and Categorization (4 hours)

**Problem:** All 195 tool descriptions are auto-generated from function names. 185/195 tools are "general" category.

Write hand-crafted descriptions for the 50 most-used tools.
Add proper categories to domain files:
```python
# layla/tools/domains/file.py
TOOLS["read_file"] = {
    "category": "filesystem",
    "description": "Read the contents of a file. Returns text with line numbers.",
    ...
}
```

Categories: `filesystem`, `code`, `git`, `web`, `memory`, `search`, `system`, `voice`, `planning`, `fabrication`.

---

### 8.6 Test Depth Improvement — Phase 2 (4 hours)

Target the remaining high-traffic untested modules:
- `services/outcome_writer.py`
- `services/initiative_engine.py`
- `services/knowledge_distiller.py`
- `services/experience_replay.py`
- `services/memory_consolidation.py`

5-8 tests each with error paths. Push total to 950+ tests.

---

## PHASE 9: MULTI-DEVICE + NETWORKING (Week 15, ~15 hours) ✅ COMPLETE

> Scale from phone to datacenter.

### 9.1 mDNS Discovery (5 hours) ✅

**New file:** `agent/services/mdns_discovery.py`

Use `zeroconf` (pure Python) to broadcast and discover Layla instances on local network.
- Service type: `_layla._tcp.local.`
- Metadata: device name, hardware tier, available models, API port, version, instance_id
- Auto-discovery in UI: "Other Layla instances on your network"
- Auto-start in server lifespan; auto-stop on shutdown
- Peer health checking via `/health` endpoint ping
- Best-peer selection by hardware tier ranking
- `zeroconf>=0.131` added to requirements.txt

---

### 9.2 Device Pairing Flow (5 hours) ✅

**New files:** `agent/routers/pairing.py`, `agent/ui/js/layla-pairing.js`

- 6-digit cryptographic PIN pairing (secrets.randbelow)
- Shared secret generation (32-byte hex) for peer-to-peer auth
- Device list in settings panel (Network & Devices card)
- Permission model: read_learnings, write_learnings, inference_offload, sync_knowledge, remote_tools
- PIN expiry (configurable TTL, default 300s)
- Paired devices persisted to `.governance/paired_devices.json`
- Full REST API: pair, confirm, list, unpair, health-check, permissions
- Warframe-aesthetic UI: peer cards, PIN overlay with countdown, permission toggles
- Router registered in main.py

---

### 9.3 Cluster Model Offloading (5 hours) ✅

**Extended:** `agent/services/inference_router.py`

When local hardware can't run a model:
- Check paired devices for available capacity (filtered by inference_offload permission)
- Route inference to the most powerful available device (tier ranking: gpu_high > gpu_mid > gpu_low > cpu)
- Fallback chain: local GPU → local CPU → paired device → queue for later
- `run_completion_with_fallback()` — drop-in replacement for `run_completion()` with cluster offloading
- `get_cluster_status()` — diagnostics: local tier, backend, available peers, fallback chain description
- Human-readable fallback chain for UI display

**Tests:** 42 new tests (14 mDNS, 17 pairing, 11 cluster). Total: 1277+ passing.

---

## VERIFICATION GATES (CUMULATIVE)

| Phase | Gate | Must Produce |
|-------|------|-------------|
| 1 | `run_all_checks.py` | 12/12 PASS, real_assertions 3/3, 900+ tests |
| 2 | `test_debate_engine.py` | Debate/council/tribunal modes pass |
| 3 | `curl /metrics` | Non-empty Prometheus output |
| 4 | `scripts/bulk_ingest.py --dry-run` | Pipeline completes on test data |
| 5 | 60-step autonomous run | No context overflow |
| 6 | Mission board E2E | Create → run → pause → resume → complete |
| 7 | Study mode test | Quiz generates from KB article |
| 8 | UI lighthouse audit | Performance score > 80 |
| 9 | mDNS discovery test | Two instances find each other |

---

## TOTAL EFFORT SUMMARY

| Phase | Description | Hours | Calendar |
|-------|-------------|-------|----------|
| 1 | Structural Integrity | 35 | Week 1-2 |
| 2 | Debate Engine + Aspect Intelligence | 40 | Week 3-4 |
| 3 | Observability + Metrics | 25 | Week 5 |
| 4 | Research Automation + Ingestion | 40 | Week 6-7 |
| 5 | Advanced Token Management | 20 | Week 8 |
| 6 | Full Autonomy Engine | 35 | Week 9-10 |
| 7 | Knowledge Loading + Language | 25 | Week 11-12 |
| 8 | Scaffold Promotion + Polish | 30 | Week 13-14 |
| 9 | Multi-Device + Networking | 15 | Week 15 |
| **TOTAL** | | **265** | **15 weeks** |

---

## DESIGN INTEGRITY (ENFORCED EVERY PHASE)

- [ ] **Sovereignty** — All data local. No cloud calls. No telemetry extraction.
- [ ] **Warframe Aesthetic** — Dark void, angular chrome, sci-fi tactical. Not corporate flat.
- [ ] **6-Aspect Personality** — Every new feature routes through aspect system. Debate engine makes aspects first-class.
- [ ] **Honest Bluntness** — No fake confidence scores. No phantom features in docs. SCAFFOLD means SCAFFOLD.
- [ ] **Memory-Driven Growth** — Every session, research, tool outcome adds to permanent memory via the canonical router.
- [ ] **Vanilla JS Philosophy** — No React. No heavy frameworks. Modular vanilla JS.
- [ ] **Never Regress** — `run_all_checks.py` must pass after every phase. Test count only goes up.
- [ ] **Scalable** — Hardware tiers are capability multipliers, never feature gates. Phone gets all features, slower.

---

## DEFERRED (NOT THIS CYCLE)

These items are acknowledged but deliberately deferred until the above 9 phases are complete:

| Item | Reason for Deferral |
|------|-------------------|
| Neo4j (graph > 100K nodes) | NetworkX handles current scale; migrate when graph actually grows past limit |
| Qdrant replacing ChromaDB | ChromaDB works; migration is risky for minimal gain at current data volume |
| WireGuard mesh | Syncthing + mDNS covers the primary use case; WireGuard is infrastructure complexity |
| Streamlit dev console | Not needed; FastAPI + vanilla JS UI covers all debugging needs |
| Full Grafana stack in production | Optional Docker setup in Phase 3 is sufficient; mandatory Grafana is over-engineering |

---

## BUILD ORDER DEPENDENCY GRAPH

```
Phase 1 (Structural Integrity)
  ├── Phase 2 (Debate Engine) — needs memory router + codex
  ├── Phase 3 (Observability) — independent, can parallel with Phase 2
  └── Phase 4 (Research + Ingestion) — needs codex + scheduler
       └── Phase 5 (Token Management) — needs research for long-context testing
            └── Phase 6 (Autonomy) — needs everything above
                 └── Phase 7 (Knowledge Loading) — needs research + autonomy
                      └── Phase 8 (Polish) — needs everything working
                           └── Phase 9 (Multi-Device) — final layer
```

**Critical path:** 1 → 2 → 4 → 6 → 7 → 8  
**Parallel track:** 3 (can start alongside Phase 2)

---

## PHASE 10: CHARACTER CREATOR + TUTORIAL SYSTEM (Week 16, ~10 hours) ✅ COMPLETE

Videogame-style character creation system for all 6 Layla aspects with full customization, titles, lore, and guided tutorial intro.

### Deliverables

| Item | File(s) | Status |
|------|---------|--------|
| **Character Creator Service** | `services/character_creator.py` (~464 lines) | ✅ |
| **Character Creator Router** | `routers/character.py` (14 endpoints) | ✅ |
| **Character Lab UI** | `ui/js/layla-character-creator.js` (~470 lines) | ✅ |
| **Character Lab CSS** | `ui/css/layla-enhanced.css` (+250 lines) | ✅ |
| **Tutorial/Intro System** | Integrated into `layla-character-creator.js` | ✅ |
| **HTML Integration** | `ui/index.html` (overlays, header button, script tag) | ✅ |
| **Main.py Wiring** | `main.py` (import + router registration) | ✅ |
| **Tests** | `tests/test_character_creator.py` (28 tests, all passing) | ✅ |

### Features
- **Aspect card strip**: Horizontal selector with per-aspect color coding and glow effects
- **Personality sliders** (6): aggression, humor, verbosity, curiosity, bluntness, empathy — each generates behavioral prompt hints injected into the system prompt
- **Voice profile** (4): pitch, speed, warmth, formality — per-aspect tuning
- **Color customization**: Primary color picker with live preview
- **Title system**: Earnable titles per aspect, rank-gated via maturity engine (4 titles each, 24 total)
- **Lore display**: Origin story + philosophy per aspect
- **Prompt hints preview**: Live view of active behavioral modifiers from slider positions
- **Reset to defaults**: Per-aspect factory reset
- **Set as main**: Choose your primary aspect
- **Wizard integration**: `renderWizardCharacterStep()` for first-run character selection with mini stat bars
- **Tutorial**: 6-step guided intro (welcome → aspects → chat → memory → character lab → complete) with element highlighting and progressive disclosure
- **Warframe aesthetic**: Clip-paths, glow effects, scanline compatibility, aspect-reactive colors throughout

### API Endpoints (14 total)
```
GET  /character/summary          — Full lab summary with all profiles + tutorial state
GET  /character/aspects          — All 6 profiles
GET  /character/aspects/{id}     — Single profile
PATCH /character/aspects/{id}    — Save customizations
POST /character/aspects/{id}/reset — Reset to defaults
GET  /character/aspects/{id}/titles — Available titles at current rank
POST /character/aspects/{id}/title  — Set active title
GET  /character/aspects/{id}/prompt-hints — Live behavioral hints
GET  /character/tutorial         — Tutorial progress
POST /character/tutorial/advance — Advance tutorial step
POST /character/main-aspect      — Set main aspect
GET  /character/traits           — Trait slider metadata
GET  /character/voice-params     — Voice slider metadata
GET  /character/earnable-titles  — All earnable titles across aspects
```

---

## COMPREHENSIVE AUDIT (Week 16)

Full codebase audit completed covering all 6 domains. Results documented in `AUDIT_REPORT.md`.

- **13 critical bugs** identified across backend (7), frontend (5), config (1)
- **14 medium bugs** identified
- **68% of services** lack dedicated test coverage
- **106 undocumented config keys** scattered across codebase
- **25+ open-source integration candidates** evaluated
- **20-item prioritized improvement roadmap** produced
