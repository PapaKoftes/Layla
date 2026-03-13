# Layla Milestone v1.0.0

**Release: Planning engine, retrieval ranking, memory decay, observability improvements**

---

## System Architecture

Layla is a local-first AI companion and engineering agent:

- **Runtime**: FastAPI server at `localhost:8000`
- **Inference**: llama-cpp-python with GGUF models
- **Memory**: SQLite (`layla.db`) + optional ChromaDB for semantic search
- **Knowledge**: NetworkX graph, markdown docs in `knowledge/`
- **Aspects**: 6 personality modes (Morrigan, Nyx, Echo, Eris, Cassandra, Lilith)

---

## Tool Ecosystem

- **100+ tools** across file, code, web, data, system
- **Metadata**: name, description, category, risk_level (validated at startup)
- **Sandbox**: All file/shell operations confined to `sandbox_root`
- **Approval**: write/run require explicit approval when `allow_write`/`allow_run` enabled

---

## Memory Design

- **Learnings**: Structured facts, preferences, strategies (SQLite + FTS5)
- **Confidence decay**: `adjusted_confidence = confidence * exp(-age_days/180)`
- **Deduplication**: content_hash prevents duplicates
- **Quality filter**: Rejects length < 40, uncertainty phrases; summarizes > 300 chars

---

## Planning System

- **Trigger**: Long goals or keywords (analyze, build, research, investigate, plan)
- **Config**: `planning_enabled: true` in runtime_config
- **Flow**: LLM produces 3–6 steps; each step executed sequentially via agent
- **Output**: Combined status and summary

---

## Study Engine

- **Plans**: Stored in `study_plans`; scheduler runs when active
- **Autonomous study**: Runs topics in background (daemon threads)
- **Capabilities**: Optional growth tracking and practice validation

---

## Retrieval Pipeline

- **Sources**: Vector (Chroma), BM25 (FTS), knowledge graph, learnings
- **Scoring**: `score = vector*0.5 + bm25*0.3 + graph*0.2 + confidence*0.1`
- **Top K**: 6 results; cache TTL 60 seconds
- **Chroma-disabled**: Falls back to FTS + graph only

---

## Safety Model

- **Background threads**: `daemon=True` (auto-learn, graph expand, prewarm)
- **Network retry**: tenacity for fetch/remote calls
- **Approval flow**: write_file, shell, apply_patch require `layla approve <uuid>`
- **Robots.txt**: AI-exclusion directives respected

---

## Observability

Structured events (loguru or stdlib). All events include: `timestamp`, `event_type`, `duration`, `status`.

**Lifecycle**
- `agent_started` — server startup
- `agent_shutdown` — server shutdown (with duration_ms)

**Planning**
- `planner_invoked` — planning engine triggered (steps, goal_preview)
- `agent_plan_created`, `agent_plan_step`, `agent_plan_completed`

**Retrieval**
- `retrieval_cache_hit` — cache served result (no fetcher call)
- `retrieval_cache_miss` — cache miss, fetcher invoked (duration_ms)
- `retrieval_results`, `memory_retrieval`

**Tools & memory**
- `tool_call`, `tool_result`
- `learning_saved`, `learning_skipped`
- `study_started`, `study_completed`
