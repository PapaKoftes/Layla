# LAYLA — FULL ROADMAP TO AUTONOMOUS AI ASSISTANT

**Goal:** A fully sovereign, locally-run AI companion that can research topics,
build knowledge bases, assist daily programming, operate autonomously on multi-step
tasks, and grow smarter with every interaction. No cloud, no extraction, your machine,
your rules.

---

## CURRENT STATE (as of 2026-05-12, audit-backed)

> See `agent/docs/audit/subsystem_audit.md` for full ground truth (63 subsystems classified).

| Area | Status | Notes |
|---|---|---|
| Core agent loop | ✅ REAL | 5000+ line agent_loop.py, stable |
| Memory (SQLite + ChromaDB) | ✅ REAL | Episodic, vector store, hybrid retrieval all wired |
| Memory router enforcement | ⚠️ PARTIAL | Router exists; enforcement lint added 2026-05-12; episodic/vector writes still bypass |
| 6-Aspect personality system | ✅ REAL | All 6 aspects parametrised with behavior, voice, reasoning depth |
| Debate / Council / Tribunal | ❌ MISSING | North-star first-class feature; no implementation exists |
| Conversation threads | ✅ REAL | `ui/js/layla-conversations.js`, left rail with search |
| Artifact detection + panel | ✅ REAL | `ui/js/layla-artifacts.js`, server-side extraction |
| Memory/learnings browser | ✅ REAL | `ui/js/layla-memory.js`, `routers/memory.py` |
| Global smart search | ✅ REAL | `ui/js/layla-search.js`, `routers/search.py` |
| Voice TTS/STT | ✅ REAL | faster-whisper + kokoro-onnx in requirements.txt |
| Plan visualization | ✅ REAL | `ui/js/layla-plan-viz.js` |
| Autonomous monitoring | ⚠️ PARTIAL | `ui/js/layla-autonomous.js` exists; event coverage incomplete |
| German language learning | ✅ REAL | `services/german_mode.py`, `routers/german.py` |
| Health check suite | ✅ REAL | 12 checks, 858 tests, 12/12 green |
| Multi-device sync (Syncthing) | ⬜ SCAFFOLD | Code exists, zero production importers, daemon not bundled |
| AirLLM (large local models) | ⬜ SCAFFOLD | Code exists, `airllm` not in requirements.txt, default off |
| Prompt compression | ⚠️ PARTIAL | Tier-3 heuristic runs; `llmlingua` not in requirements.txt |
| Prompt optimizer | ✅ REAL | Wired into agent_loop; original_goal preserved via ContextVars |
| Knowledge base builder | ⬜ SCAFFOLD | Code exists, STORM/GraphRAG deps not in requirements.txt |
| Obsidian vault sync | ⚠️ PARTIAL | One-way export connector; not structural mirror |
| Prometheus/structlog | ❌ MISSING | No `prometheus_client`, no `structlog` in codebase |
| Idle scheduler | ❌ MISSING | Coarse process-name skip only; no real idle detection |

**Health checks: 12/12 PASS | Tests: 858 passing | Real assertions: 2/3**

---

## PHASES COMPLETE

### Phase 0 — Backend Observability ✅
- Context budget telemetry
- Structured tool output tracing
- Live workspace index invalidation
- Model router decision logging
- Embedding cache warmup

### Phase 1 — UI Redesign ✅
- Conversation threads sidebar
- Artifacts/canvas panel
- Memory/learnings browser
- Global smart search
- Voice chat (TTS/STT per-aspect personalities)
- Real-time streaming visualization
- Warframe aesthetic maintained

### Phase 2 — Plan Visualization & Autonomy ✅
- Gantt chart plan visualization
- Autonomous execution monitoring with real-time progress
- Prior plans learning integration
- Outcome evaluation feedback UI
- Early-stop / rollback controls

### Phase 3 — Performance & Polish ✅
- Performance optimization (lazy load, IndexedDB)
- WCAG 2.1 AA accessibility pass
- Warframe aesthetic perfected
- Settings panel

### Phase 4 — Backend Upgrades ✅
- Dual-model chain-of-thought routing
- Retrieval ranking by confidence
- Concurrent task context isolation

### Phase 5 — Knowledge & Sync ✅
- Obsidian vault connector (bidirectional)
- Multi-device sync via Syncthing
- Bug detection system (7 check scripts + orchestrator)
- German language learning mode (CEFR + SM-2)

### Phase 6 — Intelligence Enhancement ✅ (this session)
- AirLLM integration (layer-by-layer 70B model inference)
- Prompt compression (LLMLingua / LongLLMLingua + heuristic fallback)
- Prompt optimizer (intent classification → DSPy → structural rewrite)
- Knowledge base builder (Unstructured.io + entity extraction + STORM)
- `/intelligence/*` REST API
- WCAG 2.1 AA full pass (skip-nav, role=log, aria-controls, landmarks)

---

## PHASE 7 — RESEARCH AUTOMATION (weeks 8-9)

### Goal
Layla can independently research any topic, synthesize a structured knowledge article
(STORM-quality), and load it into her knowledge base — all from a single command.

### Tasks

#### 7.1: Autonomous Research Loop (8 hours)
**Files:** `services/research_orchestrator.py`, `routers/research.py` (extend)

Workflow:
```
User: "Research FastAPI async patterns"
  → Layla decomposes into 5-8 sub-questions
  → Searches web (if permitted) or existing KB + workspace
  → Fetches top 3 sources per sub-question via kb_builder.ingest_url()
  → Synthesizes STORM-style article
  → Saves to knowledge/_generated/
  → Reports back with article summary + confidence score
```

Key additions:
- `research_orchestrator.py` — orchestrates decompose → fetch → synthesize
- Sub-question generation using prompt_optimizer classify + structural templates
- Source credibility scoring (domain authority heuristic)
- Incremental progress via SSE (step: "Fetching source 2/5...")

#### 7.2: Topic Graph (4 hours)
**Files:** `services/topic_graph.py`

- Track relationships between KB articles as a directed graph
- Bidirectional link strength based on entity overlap
- `GET /intelligence/kb/graph` — returns D3-compatible node/edge JSON
- UI: force-directed graph visualization in the Research panel

#### 7.3: Research Panel UI Enhancement (4 hours)
**Files:** `ui/js/layla-research.js` (extend)

- Research queue (list of topics to research in sequence)
- "Research this" button next to any message
- Progress bar per research job
- KB article preview pane (rendered Markdown)
- Topic suggestions from current conversation context

#### 7.4: Citation Tracking (3 hours)
**Files:** `services/kb_builder.py` (extend), `layla/memory/db.py`

- Store source URL, fetch date, content hash per KB article
- `GET /intelligence/kb/articles/{id}/citations`
- Stale detection: flag articles whose sources are >30 days old
- Attribution in responses: Layla references KB articles by title

---

## PHASE 8 — ADVANCED TOKEN MANAGEMENT (weeks 10-11)

### Goal
Optimal context usage at all times. Never hit a context limit unexpectedly.
Every token in the context window earns its place.

### Tasks

#### 8.1: Selective Context (3 hours)
**Files:** `services/prompt_compressor.py` (extend)

Integrate **Selective Context** (https://github.com/liyucheng09/selective_context):
- Identifies and removes "self-information-poor" tokens using a small LM
- Operates at token level, complementing LLMLingua's sentence-level pruning
- Config: `selective_context_enabled`, `selective_context_reduction_ratio`

#### 8.2: ContextCite Attribution (4 hours)
**Files:** `services/context_attribution.py` (new)

Integrate **ContextCite** (https://github.com/MadryLab/context-cite):
- After each response, attribute which context snippets contributed most
- Score 0.0–1.0 per retrieved document segment
- Store attribution in tool_calls table alongside response
- UI: hover over response to see "based on: [source]" tooltip

#### 8.3: Dynamic Context Budget Reallocation (5 hours)
**Files:** `services/prompt_tier_budget.py` (extend), `services/context_manager.py`

- Monitor token usage per section (identity / memory / workspace / knowledge / tools)
- Auto-shrink low-signal sections to give budget to high-signal ones
- "Pressure relief valve": when >90% context used, compress memory section first
- Budget telemetry in `/health/context_budget` (Phase 0 work extended)
- Config: `dynamic_budget_enabled`, `budget_pressure_threshold` (default 0.85)

#### 8.4: Conversation Chunking for Long Tasks (4 hours)
**Files:** `agent_loop.py` (extend), `services/task_budget.py` (extend)

- For autonomous tasks >50 steps: auto-split into sessions with handoff summaries
- Each chunk gets a "task continuation prompt" with compressed prior state
- Prevents context overflow on day-long autonomous operations
- Config: `auto_chunk_long_tasks`, `chunk_step_threshold` (default 50)

#### 8.5: Token Pressure Dashboard (3 hours)
**Files:** `ui/js/layla-context-viz.js` (new), `routers/system.py` (extend)

- Real-time stacked bar: identity | memory | workspace | tools | conversation
- Colour coding: green (<60%) → yellow (60-85%) → red (>85%)
- Click section to see contents and compression options
- Accessible: ARIA labels, keyboard navigable

---

## PHASE 9 — FULL AUTONOMY ENGINE (weeks 12-14)

### Goal
Layla operates independently for hours. You assign a mission; she plans, executes,
researches, writes code, tests it, and reports back — without hand-holding.

### Tasks

#### 9.1: Mission Manager UI (6 hours)
**Files:** `ui/js/layla-missions.js` (new/extend)

- Mission board: Kanban-style (backlog / running / done)
- Each mission has: goal, progress %, estimated time, sub-tasks, artifacts produced
- "Launch" a mission from chat with one click
- Pause / resume / abort controls
- Mission replay: re-run any past mission with fresh data

#### 9.2: Long-Horizon Planning (8 hours)
**Files:** `services/plan_service.py` (extend), `services/planner.py`

- Multi-day task decomposition: break 40-hour tasks into day-sized chunks
- Dependency graph: task B can't start until task A produces its artifact
- Resource estimation: "this will take ~3 hours, use ~2M tokens"
- Checkpoint saves: resume after unexpected shutdown mid-mission
- Integration with Syncthing: mission state syncs across devices

#### 9.3: Tool Result Learning (5 hours)
**Files:** `services/experience_replay.py` (extend)

- After each tool call, score the result (0-5 by LLM self-evaluation)
- Store (tool, args_pattern, result_quality) in experience_replay table
- Planner consults replay before choosing tools: "last 10 reads of this file type = 4.2/5"
- Auto-tune tool call arguments based on historical success patterns

#### 9.4: Proactive Initiative Engine (4 hours)
**Files:** `services/initiative_engine.py` (extend)

- Layla monitors workspace changes in background (via Syncthing events / inotify)
- Detects: failing tests, TODO comments, stale dependencies, lint errors
- Surfaces 3 proactive suggestions per session ("I noticed X, want me to fix it?")
- User can approve/dismiss; approved tasks join the mission queue

#### 9.5: Self-Improvement Feedback Loop (6 hours)
**Files:** `services/self_improvement.py` (extend)

- After each mission: score plan quality, tool selection, response quality
- Low-scoring patterns → auto-generated improvement hypotheses
- Layla can propose edits to her own system prompt / aspect behavior
- User approves/denies; approved changes committed to aspect definitions

---

## PHASE 10 — LOADING LAYLA WITH KNOWLEDGE (weeks 15-16)

### Goal
You start loading Layla with all your personal knowledge, codebases, research,
bookmarks, notes, and learning goals. She becomes your second brain.

### Tasks

#### 10.1: Bulk Knowledge Ingestion Pipeline (6 hours)
**Files:** `services/kb_builder.py` (extend), `scripts/bulk_ingest.py` (new)

One-command bulk ingestion:
```bash
python scripts/bulk_ingest.py \
  --dirs ~/notes ~/research ~/code-projects \
  --urls https://docs.python.org https://fastapi.tiangolo.com \
  --pdfs ~/papers/*.pdf \
  --output agent/knowledge/_generated
```

Features:
- Progress bar with ETA
- Deduplication (skip already-ingested content via hash)
- Rate-limited URL fetching (respect robots.txt)
- Format support: .md, .txt, .pdf, .docx, .html, .py, .js, .json, .csv, .epub

#### 10.2: Personal Research Profile (4 hours)
**Files:** `services/personal_knowledge_graph.py` (extend)

- Build a personal topic graph from all ingested knowledge
- Identify expertise areas (highly-connected topics)
- Identify knowledge gaps (isolated topics with few connections)
- Weekly "knowledge summary": what you know, what you're learning, gaps to fill

#### 10.3: Spaced Repetition for All Knowledge (4 hours)
**Files:** `services/study_service.py` (extend), `services/german_mode.py` (pattern)

- SM-2 spaced repetition for any KB article (not just German)
- "Study mode": Layla quizzes you on KB content
- Confidence tracking per article (decreases if you answer wrong)
- Study calendar: due articles per day like Anki

#### 10.4: Research-to-Code Pipeline (5 hours)
**Files:** `services/engineering_pipeline.py` (extend)

- User: "implement what you know about FastAPI rate limiting"
- Layla: retrieves KB article on FastAPI + rate limiting, synthesizes implementation plan, writes code
- Full loop: research → plan → code → test → document
- Citable code comments: "// based on FastAPI docs (kb/fastapi_async_patterns.md)"

---

## UPDATED PRIORITY ORDER (revised after architecture audit)

> **See `SYSTEM_PLAN.md` for the full risk analysis, mitigation strategies,
> verification gates, and file-level build specifications.**
> The plan below was revised to address the critical risks identified:
> memory fragmentation, no canonical entity schema, and scope creep.

**True next priorities (most value, least risk):**

1. **Phase A — Memory Coherence** (CRITICAL BLOCKER)
   - `schemas/entity.py` — canonical data model for everything
   - `services/memory_router.py` — single query interface for all memory
   - Add entities/relationships tables to SQLite
   - Gate: `check_memory_coherence.py` → 0 conflicts

2. **Phase B — Repo Intelligence** (unblocks coding assistance)
   - `services/repo_indexer.py` — unified incremental indexer
   - Codex auto-generation
   - NetworkX graph persistence

3. **Phase C — Bulk Ingestion** (unblocks "loading with knowledge")
   - `scripts/bulk_ingest.py` — one-command knowledge loading
   - `services/people_codex.py` — relationship intelligence

4. **Phase D — Background Scheduler** (unblocks autonomy)
   - APScheduler for auto-reindex, Obsidian sync, memory consolidation

5. **Phase E — Confidence score ≥ 85%** (quality assurance)
   - Fix 5 pre-existing test failures
   - In-process metrics dashboard

6. **Phase F — Language System Generalisation** (low risk, high value)
   - Generalise German mode to any language
   - SM-2 for all KB content

---

## OLD PRIORITY ORDER (superseded)

1. **Confirm test suite passes** — run `python scripts/run_all_checks.py`
2. **Phase 7.1** — Research automation loop (biggest autonomy gain)
3. **Phase 8.3** — Dynamic context budget (prevents context overflow in long sessions)
4. **Phase 9.4** — Proactive initiative engine (makes Layla feel alive even when idle)
5. **Phase 10.1** — Bulk knowledge ingestion (enables "day-to-day use" milestone)
6. **Phase 9.2** — Long-horizon planning (enables the "research topics" milestone)

---

## MILESTONE: READY FOR DAILY USE

Layla is ready for daily use when:

- [ ] All 8 core check scripts pass (confidence ≥ 85%)
- [ ] Test suite ≥ 80% pass rate (currently ~70%)
- [ ] Research automation working (Phase 7.1)
- [ ] Bulk knowledge ingestion working (Phase 10.1)
- [ ] No context overflow on 2-hour autonomous sessions
- [ ] Syncthing sync stable across 2 devices
- [ ] Voice chat working end-to-end

**Estimated: 6-8 more weeks of focused development**

---

## DEPENDENCIES TO INSTALL (for full capability)

```bash
# Core (required)
pip install tiktoken chromadb anthropic fastapi uvicorn

# AirLLM (local large models)
pip install airllm transformers torch

# Prompt compression
pip install llmlingua           # LLMLingua + LongLLMLingua

# Prompt optimization
pip install dspy-ai             # DSPy programmatic prompting
pip install guidance            # Constrained generation

# Knowledge base builder
pip install unstructured[all]   # PDF, DOCX, HTML parsing
pip install pypdf               # Lightweight PDF fallback
pip install spacy && python -m spacy download en_core_web_sm  # NER

# Research / STORM
pip install knowledge-storm     # Stanford STORM (needs LLM API key)

# Testing
pip install pytest pytest-timeout pytest-asyncio
```

---

## OPEN SOURCE PROJECTS INTEGRATED

| Project | Purpose | Status |
|---|---|---|
| [AirLLM](https://github.com/lyogavin/airllm) | 70B models on consumer GPU | ✅ Integrated |
| [LLMLingua](https://github.com/microsoft/LLMLingua) | Prompt compression 5-20x | ✅ Integrated |
| [LongLLMLingua](https://github.com/microsoft/LLMLingua) | Question-aware RAG compression | ✅ Integrated |
| [DSPy](https://github.com/stanfordnlp/dspy) | Programmatic prompt optimization | ✅ Integrated |
| [guidance](https://github.com/guidance-ai/guidance) | Constrained generation | ✅ Integrated |
| [Outlines](https://github.com/outlines-dev/outlines) | Type-safe structured generation | Planned Ph.8 |
| [Unstructured.io](https://github.com/Unstructured-IO/unstructured) | PDF/DOCX/HTML parsing | ✅ Integrated |
| [STORM (Stanford)](https://github.com/stanford-oval/storm) | Wikipedia-quality synthesis | ✅ Integrated (stub) |
| [GraphRAG (Microsoft)](https://github.com/microsoft/graphrag) | Knowledge graph from text | Planned Ph.7 |
| [Selective Context](https://github.com/liyucheng09/selective_context) | Token-level pruning | Planned Ph.8 |
| [ContextCite](https://github.com/MadryLab/context-cite) | Response attribution | Planned Ph.8 |
| [spaCy](https://spacy.io) | NER / entity extraction | ✅ Integrated |
| [Syncthing](https://syncthing.net) | Multi-device sync | ✅ Integrated |
| [ChromaDB](https://www.trychroma.com) | Vector store | ✅ Existing |
| [tiktoken](https://github.com/openai/tiktoken) | Accurate token counting | ✅ Existing |

---

## SOVEREIGNTY PROMISE

Every line of code in this roadmap honours the design principles:

- **Sovereignty** — All processing local. AirLLM runs on your GPU. ChromaDB on your disk.
  LLMLingua on your CPU. No external API calls unless you explicitly configure them.
- **Warframe Aesthetic** — All UI remains dark, angular, sci-fi. No corporate-flat additions.
- **6-Aspect Personality** — All new features (research, KB, autonomy) route through the
  aspect system. Cassandra researches differently from Echo.
- **Honest Bluntness** — Confidence scores are real. Gaps are reported. No false positives suppressed.
- **Memory-Driven Growth** — Every KB article, every research session, every tool outcome
  adds to Layla's permanent memory. She gets smarter with use.
- **Vanilla JS Philosophy** — All new UI panels stay dependency-free vanilla JS modules.
