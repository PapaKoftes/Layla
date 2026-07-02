# GUI Audit 03 — Memory, Knowledge, Codex + Growth/Maturity

Deep, evidence-based audit of the Memory/Knowledge/Codex + Growth/Maturity cluster.
Read-only. Every claim cites `file:line`. Repo root: `C:\Work\Programming\Layla`.

**Scope note on UI state:** The live shipped UI is the pre-rebuild `agent/ui/index.html`
(1281 lines) + ES modules in `agent/ui/components/`. The `.planning/GUI-FEATURE-MAP.md`
describes a *planned* rebuild (rail destinations, command palette) that is not yet built
(current branch is mid-G1: design-system foundation only). This audit reports the **actual
wired UI**, not the planned IA.

---

## 0. Two headline answers (asked in the brief)

### Q1: Is semantic memory actually active on a compiler-free install?
**YES — via a transparent fallback, provided `use_chroma` stays true.**
- When `chromadb` is importable, ChromaDB is used. When it is absent (no C++ toolchain to
  build `chroma-hnswlib`), `vector_store` silently swaps in a **SQLite+NumPy brute-force
  cosine store** (`agent/layla/memory/fallback_store.py:41` `FallbackCollection`, selected at
  `vector_store.py:166-171` and `:396-400`). Brute force is fine at single-user scale.
- The gate is `_vector_enabled()` (`vector_store.py:280`) = "not explicitly disabled via
  `LAYLA_CHROMA_DISABLED`", **NOT** "chromadb present". So embeddings + semantic recall keep
  working compiler-free. Embeddings come from `sentence-transformers` (nomic-embed-text-v1.5
  768d, MiniLM 384d fallback — `vector_store.py:99-107`), which ships wheels.
- **BUT** the retrieval *entry points* used by chat turns gate on the **config flag**
  `use_chroma`, not on `_vector_enabled()`. `retrieve_relevant_memory` (`services/retrieval/__init__.py:83`),
  `retrieve_learnings` (`:152`), `retrieve_documents` (`:170`) all do `if cfg.get("use_chroma")
  → search_memories_full(...) else → search_learnings_fts(...)`. So:
  - Default install (`use_chroma=True`, schema default `config_schema.py:48`): **semantic recall
    active**, ChromaDB or fallback.
  - **"potato" preset sets `use_chroma=False`** (`config_schema.py:21`) → drops to SQLite FTS
    keyword-only. This is the intended low-resource tradeoff, but it means a friend on a weak
    laptop who picks "potato" loses semantic memory even though the fallback store would run.

### Q2: Does the verification/growth loop actually change model behavior, or is it decorative?
**Partly real, mostly latent-by-default.**
- **XP → rank → unlocks is injected into the system prompt.** `system_head_builder.py:724-732`
  calls `get_unlocks_text({"rank": rank})` and appends e.g. *"Your current capabilities:
  Proactive suggestions, Research autonomy"* to `system_instructions`. So rank literally alters
  the prompt the model sees. `maturity_enabled` defaults **True** (`maturity_engine.py:233`).
- **Rank → trust tier gates real autonomy** — but only when opted in. `get_trust_tier()`
  (`maturity_engine.py:236`) returns 0 unless `autonomy_trust_tiers_enabled` is set (**default
  False**, `:251`). When enabled, tier gates: scheduler background jobs (`scheduler/jobs.py:81`
  needs ≥2), autonomous coordinator (`coordinator.py:289` <3 blocks), inline initiative engine
  (`initiative_engine.py:102` <2 blocks). So the loop *can* unlock behavior, but is off by default.
- **Verified facts DO change stored knowledge** — confirming sets matching learnings to
  `confidence=1.0` (`verification_queue.py:236-239`), a correction inserts a new
  `confidence=1.0` learning (`:269-278`), and both feed retrieval ranking (confidence boosts
  recall order, `vector_store.py:_apply_confidence_recency_boost`). Verifying also awards +12 XP
  (`:245`) and auto-writes a wiki entry (`:250-265`).
- **The catch:** the verification *answer* loop has **no UI** (see F13). The queue is populated
  (ingestion pipeline `layla/ingestion/pipeline.py:134`) and its **stats are displayed**
  (growth.js), but nothing in the frontend calls `/verify/next` or `/verify/answer`, so a GUI
  user can never confirm/reject a fact. The behavioral payoff is real but unreachable from the UI.

**Net:** the growth loop is wired end-to-end in the backend and *does* touch the prompt and
autonomy gates, but (a) autonomy gating is off by default and (b) the single most behaviorally
meaningful action — verifying facts — is backend-only. So from a GUI user's vantage it is ~70%
decorative today.

---

## 1. What a "learning" IS + full lifecycle

**Definition.** A row in the SQLite `learnings` table: `{id, content, type/learning_type,
confidence, tags, created_at, source, content_hash, embedding_id, score}` plus a paired vector
in the Chroma/fallback `learnings` collection. Types: `fact | preference | strategy | identity |
outcome | correction | imported` (`learnings.py:82` clamps kind).

**Creation paths.**
1. **`/learn` "remember" button** — a per-message button on Layla bubbles
   (`ui/components/chat-render.js:380` `rememberLaylaBubble` → POST `/learn/` with
   `{content, type:'fact', tags:'ui:remember'}`) → router `learn.py:72 learn()`.
2. **Slash/tool `/learn/`** — same endpoint.
3. **Distillation / autonomous ingestion** — `memory_router.save_learning` (canonical write).
4. **Verification correction** — inserts a `correction` learning at confidence 1.0.

**Write pipeline (`learn.py:72` → `memory_router.save_learning` → `layla.memory.db.save_learning`
at `learnings.py:~30-193`):**
1. Embed content (`vector_store.embed` → `add_vector`) — best-effort; `learn.py:82-93`.
2. **Rate limit** — deque window (`learnings.py:40-52`); over limit → return -1.
3. **Learning filter** — `services/memory/learning_filter.filter_learning` (`learnings.py:56-65`);
   reject → -1.
4. **Learning quality gate** — `distill.passes_learning_quality_gate` (`learnings.py:69-79`).
   Gated by `learning_quality_gate_enabled` (schema default **True**, `config_schema.py:75`;
   *but* `distill.py:47` internally defaults to **False** if config missing — see F16). Scores
   via `score_learning_content` (length/word-count/junk-phrase heuristic, `distill.py:18-38`);
   reject if `< learning_quality_min_score` (default 0.35).
5. **Dedup** by `content_hash` (`learnings.py:95-98`).
6. INSERT; **dual-write** to Chroma if no embedding yet (`:131-144`), marking `needs_reindex=1`
   on failure.
7. **Mirror to Elasticsearch** if enabled (`:168-180`, `elasticsearch_bridge.index_learning`).
8. **Award +10 XP** `learning_saved:<type>` (`:187-191`).
9. Background **graph node** expansion (`:194+`, daemon thread) + `learn.py:97 add_node`.

**Confidence & retrieval threshold.**
- New learnings default `confidence≈0.5` (browse renders 0.5 if null, `memory.js:73`).
- **Adjusted confidence** = confidence with time decay (`learnings.py:_apply_confidence_decay`,
  attached at read at `:282/:335/:428`). Used to re-rank recall
  (`vector_store._apply_confidence_recency_boost :929`, weighted fusion `:665`).
- Config `memory_retrieval_min_adjusted_confidence` (schema `config_schema.py:53`, runtime
  default `runtime_safety.py:440`) is meant to drop low-confidence hits. **It is DEAD** — no
  code reads it as a filter (grep: only schema + defaults reference it). The only live
  min-confidence filter is `retrieve_relevant_memory(min_confidence=...)`
  (`services/retrieval/__init__.py:98`), which callers feed either `0.0` (chat) or the
  hardcoded `PLANNER_MIN_CONFIDENCE=0.75` (`:371`, `retrieve_high_confidence_memory`). **F1.**

**Injection into a chat turn.** `context_builder.py:99-117`:
- `retrieve_relevant_memory(task, k=k_mem, coding_boost=...)` (`:103`) — pooled learnings.
- `build_retrieved_context(task, k, reasoning_mode)` (`:115`) → `services/retrieval/__init__.py:329`
  → `_retrieve_and_build` (`:226`) runs learnings + docs + graph in parallel (ThreadPool),
  fuses into a **"Relevant knowledge:\n* fact: …"** block capped at `MAX_RETRIEVED_CHARS=2000`
  (`:22`), Jaccard-dedup per line. Cached 60s. `learnings_n` (schema default 30) is read in
  `system_head_builder.py:85` for a separate recent-learnings injection.

**Browse / edit / delete** (`components/memory.js`, panel in `index.html:861-887`):
- `laylaMemBrowse(page)` → GET `/memory/browse?page&limit&sort&type&q` → `memory.py:324
  browse_learnings` (SQLite paginated, type/keyword filter, recent|confidence sort). Renders
  cards with confidence %, type, tags, date (`memory.js:66-100`).
- Edit inline → PATCH `/memory/{id}` (`memory.py:384 update_learning`, content/tags).
- Delete → DELETE `/memory/{id}` (`memory.py:432 delete_learning`, also drops Chroma vector).
- **Status: working.**

---

## 2. Retrieval internals

**Semantic memory store.** ChromaDB (`hnsw:space=cosine`) OR the SQLite+NumPy fallback
(`fallback_store.py`). Selected transparently by presence of `chromadb`.

**Full pipeline** (`vector_store.search_memories_full :1010`):
1. **Hybrid** `search_hybrid` (`:684`) = dense vector (`search_similar`) + **BM25**
   (`rank_bm25.BM25Okapi`, index built lazily over ≤2000 learnings `:491`) fused via
   **Reciprocal Rank Fusion** (`_reciprocal_rank_fusion :514`). Config can switch to a
   **weighted linear blend** `retrieval_fusion=weighted` (`_search_hybrid_weighted :604`,
   `w_emb·sim + w_kw·bm25 + w_recency + w_success/adjusted_confidence`).
2. **HyDE** (`search_with_hyde :837`) — only if `hyde_enabled` (schema default **False**,
   `config_schema.py:105`). Generates a hypothetical answer via `llm_gateway.run_completion`,
   embeds it, fuses with the raw query. Extra LLM call per query.
3. **FTS5** keyword merge (`search_learnings_fts`, RRF-fused `:1063-1069`).
4. **Light rerank** → top ≤10 (MMR optional, `mmr_rerank :764`).
5. **Cross-encoder rerank** (`rerank :799`) — `ms-marco-MiniLM-L-6-v2`, optional BGE reranker
   (`use_bge_reranker`). Fails open to identity order if model can't download
   (`_cross_encoder_failed` guard, never retried).
6. **Confidence+recency boost** (`_apply_confidence_recency_boost :929`, skipped in weighted mode).
7. **Domain keyword boost** from active aspect expertise (`_apply_domain_keyword_boost :971`).

**Retrieval-depth knobs (all consumed):**
- `semantic_k` (5) — `pre_loop_setup.py:166`, `system_optimizer.py:115` (perf-tier scaled).
- `knowledge_chunks_k` (5) — `system_optimizer.py:116`; feeds `get_knowledge_chunks*`.
- `learnings_n` (30) — `system_head_builder.py:85`.
- Effective values surfaced in `/health` (`health_snapshot.py:181`).

**Knowledge docs retrieval.** `get_knowledge_chunks_with_sources :1381` — Chroma `knowledge`
collection, priority-ordered (`core>support>flavor`, front-matter parsed `:1229`), aspect &
domain boosts. Parent-document expansion `get_knowledge_chunks_with_parent :870`. Auto-refresh
on file change (`refresh_knowledge_if_changed :1295`, debounced 30s, content-hash incremental).

**`memory_router.query` (the "gatekeeper" router).** Multi-store routing (entities/chroma/graph/
recent/kb). **Its `_query_chromadb` calls `vector_store.semantic_search` which DOES NOT EXIST**
(grep confirms no `def semantic_search`) → that branch always throws + returns []
(`memory_router.py:504-521`). And `memory_router.query` has **no production callers** (only
`tests/test_privacy_separation.py`). So the "gatekeeper" query path is effectively **dead** for
semantic reads; real chat retrieval bypasses it via `services/retrieval`. **F2.** (The write
side `memory_router.save_learning` IS the live canonical write chokepoint — that half works.)

---

## 3. Semantic search vs Elasticsearch search

| | Semantic search | Elasticsearch |
|---|---|---|
| **What** | vector+BM25+FTS+rerank over learnings/knowledge | full-text mirror of learnings |
| **Endpoint** | `/memories` (`learn.py:27`), `/search` (`search.py:18`) | `/memory/elasticsearch/search` (`memory.py:257`) |
| **Store** | Chroma/fallback + SQLite FTS | external ES 8.x server |
| **Default** | **on** (`use_chroma=True`) | **off** (`elasticsearch_enabled=False`, `config_schema.py:80`) |
| **Wired?** | yes, primary | code-complete but inert unless user runs ES + installs pkg |

- **ES is a real, optional mirror, not the default search.** `elasticsearch_bridge.client_from_config`
  (`:20-37`) returns None (clean no-op) when disabled / no URL / package missing. New learnings
  mirror to `{prefix}-learnings` (`learnings.py:170`). The UI exposes it as a subtab that says
  *"Optional mirror. When off, use semantic search above."* (`index.html:896`).
- **Global search** (`/search`, header box → `components/search.js`) fans out to 4 groups:
  conversations (SQLite LIKE + FTS), learnings (`retrieve_relevant_memory` + FTS supplement),
  workspace (code index), knowledge (`retrieve_documents`). **Status: working.** ES is NOT
  consulted by global search — only via its dedicated subtab.

---

## 4. File checkpoints

**What/why.** Pre-write snapshots so `restore_file_checkpoint` can undo agent file edits.
Protects against bad `write_file / apply_patch / search_replace / write_files_batch`.

**Creation.** `services/workspace/file_checkpoints.create_checkpoint :84`, called from
`layla/tools/impl/file_ops.py` and `layla/tools/sandbox_core.py` before mutating writes. Gated by
`file_checkpoint_enabled` (default True). Retention by `file_checkpoint_max_count` (200) /
`_max_bytes` (~200MB) (`enforce_checkpoint_retention :42`).

**List/restore endpoints.** `memory.py:276 /memory/file_checkpoints` (list),
`memory.py:291 /memory/file_checkpoints/restore` (queues approval in safe_mode, else runs
`restore_file_checkpoint`).

**UI.** `index.html:905` checkpoints subtab → `workspace.js:449 loadFileCheckpoints`.
- **BUG (F3): path mismatch.** UI fetches **`/file_checkpoints`** (`workspace.js:453`) but the
  route is **`/memory/file_checkpoints`** (memory router `prefix="/memory"`). No unprefixed route
  exists (grep). → panel always 404s → "Could not load checkpoints". **Backend works; UI broken.**
- **BUG (F4): field mismatch.** UI reads `d.items || d.checkpoints` (`workspace.js:455`) but
  `list_checkpoints` returns a bare list/other shape — compounded by the 404 this is moot but is
  a second contract drift.

**Status: backend working, UI broken (path mismatch).**

---

## 5. Knowledge ingest / import chat / codex / bundle / rebuild

### 5a. Knowledge ingest (directory/source → KB)
- `POST /knowledge/ingest` (`knowledge.py:28`) → `route_helpers.sync_ingest_docs(source, label)`.
  `GET /knowledge/ingest/sources` lists ingested. UI: workspace knowledge subtab.
- Also `POST /workspace/index` (semantic code index) and `/workspace/cognition/sync`.
- **Status: working** (backend solid; UI present in workspace knowledge subtab).

### 5b. Import chat (WhatsApp → knowledge)
- `POST /knowledge/import_chat_preview` (`knowledge.py:102`, parse stats, no write) and
  `POST /knowledge/import_chat` (`:124`, writes markdown to `knowledge/imports/<title>.md` for
  RAG). Only `format=whatsapp` supported (`parse_whatsapp_txt` / `whatsapp_export_to_markdown`).
- **Status: working (backend).** UI presence in workspace is thin — verify a composer exists;
  functionally reachable. Marked **partial** pending a clear UI entry.

### 5c. Relationship codex — *what is it?*
A **workspace-scoped operator notebook about people/relationships**, stored at
`<workspace>/.layla/relationship_codex.json`. NOT a global user profile. Two modes:
- **Direct edit** — `GET/PUT /codex/relationship` (`codex.py:30/45`) load/replace the JSON
  (`{entities:{...}}`). UI: `index.html:915-922` textarea + Load/Save
  (`workspace.js` relationship-codex handlers).
- **Proposals** — `/codex/proposals` (list), `/proposals/generate` (LLM-suggests codex entries
  from goal/recent actions), `/proposals/approve`, `/proposals/dismiss` (`codex.py:72-134`,
  `relationship_codex.generate_proposals`). Optional context injection via
  `relationship_codex_inject_enabled` (per `index.html:916` note).
- Sandbox-guarded (`_resolve_workspace` requires `inside_sandbox`, `codex.py:13-27`).
- **Status: working** for direct edit; **proposals = backend working, UI partial** (the textarea
  is wired; the proposal generate/approve/dismiss flow has limited UI surface).

### 5d. Memory bundle export/import
- `GET /memory/export` (`memory.py:133`) → ZIP of `knowledge/*.md|txt` + `learnings.json` +
  manifest. UI: header overflow link `⬇ Memory bundle` (`index.html:219`, direct download).
- `POST /memory/import` (`memory.py:185`) → merge knowledge (new files only, zip-slip guarded
  `:207-214`) + dedup learnings by 60-char prefix (`:233-244`). 100MB cap.
- **Status: working** (export via direct link; import needs a file picker — present in settings).

### 5e. Memory rebuild
- `vector_store.rebuild_collection :210` deletes+re-indexes the Chroma `learnings` collection
  from SQLite (for embedder dim/model change). Referenced by a `POST /memory/rebuild`
  (warned about in `vector_store.py:190`). **Status: backend working**; UI surface is minimal
  (advanced/settings). Marked **partial** on UI.

---

## 6. Growth / Maturity

**XP sources (all wired, `award_xp` in `maturity_engine.py:292`):**
| Source | XP | Location |
|---|---|---|
| Conversation turn | +3 | `run_finalizer.py:136` |
| Learning saved | +10 | `learnings.py:191` |
| Tool success | +5 | `user_profile.py:211` |
| Fact verified | +12 | `verification_queue.py:245` |
| Approval executed | +15 | `approvals.py:110` |
| Plan executed | +20 | `plans.py:307`, `agent_tasks.py:123`, `run_setup.py:857` |
| Study session | +20 | `scheduler/jobs.py:208` |
| Capability practice | +30 | `capabilities.py:148` |
| Research mission | +50 | `research.py:238` |
| File ingested (watcher) | +8/+5 | `knowledge_watcher.py:296/337` |
| Daily activity + streak | +5..+25 | `maturity_engine.py:503` (via `record_relationship_event`) |

**Ranks/phases/abilities.** XP thresholds `_XP_TO_NEXT = [500,1000,2000,…,100000]`
(`maturity_engine.py:41`). Rank→phase: awakening(0-2) / attunement(3-5) / resonance(6-8) /
sovereignty(9-12) / transcendence(13+) (`phase_for_rank :44`). Unlocks by rank
(`_RANK_UNLOCKS :355`): Proactive suggestions(1), Research autonomy(3), Multi-step planning(5),
Cross-aspect synthesis(7), Full autonomy(10), Teacher mode(12). **Injected into system prompt**
(`system_head_builder.py:728`). Milestones per phase `PHASE_MILESTONES :153`.

**Growth dashboard UI** (`components/growth.js`, panel `index.html:1015-1053`).
- `refreshGrowthDashboard()` (only trigger: "Refresh growth" button `index.html:515` + open) →
  `Promise.all([GET /api/growth/stats, GET /operator/profile])`.
- `/api/growth/stats` (`learn.py:244`): total_facts, high_confidence (≥0.9), type breakdown,
  last-7-day count, velocity-by-week, `verification` stats, `capabilities` (SQL join
  `capabilities`⨝`capability_domains`), `knowledge_watcher` stats, active study plans.
- `/operator/profile` (`settings.py:563`): operator stats + `maturity{xp,rank,phase,unlocks,
  xp_to_next,milestones}`.
- Renders XP bar, rank badge, phase gradient, velocity sparkline, capability trend arrows
  (rising/falling/stable), learning-type chips, verify confirmed/rejected/pending, watcher status.
- **BUG (F5): velocity sparkline mismatch.** `/api/growth/stats` returns `velocity_by_week` as a
  **dict** `{week: count}` (`learn.py:285`) but `growth.js:156/190` treats it as an **array** of
  `{count,label}` (`.slice(-4)`, `w.count`). A dict `.slice` → undefined → sparkline shows "No
  velocity data yet" always.
- **BUG (F6): watcher-status field mismatch.** `get_stats()` returns
  `{running, watch_dirs, files_ingested, files_skipped, mode}` (`knowledge_watcher.py:403`) but
  `growth.js:280-286` reads `w.watched_folders`, `w.files_processed`, `w.files_pending` → always
  "0 folders / 0 processed" even when watching. Non-fatal but the panel is wrong.
- **F7 (data-contract):** `growth.js:64 _XP_THRESHOLDS` and phase names are **duplicated**
  client-side from `maturity_engine`; the XP-to-next it computes ignores the server's
  `xp_to_next`. Drift risk if backend thresholds change.

**Verification queue** (`services/planning/verification_queue.py`).
- Populated: ingestion pipeline submits ≤3 chunks/file at confidence 0.6
  (`layla/ingestion/pipeline.py:134`), driven by knowledge_watcher / `scripts/bulk_ingest.py`.
- `/verify/next` (`learn.py:205`): next pending fact, ≤3 prompts/session, 24h cooldown,
  importance-ordered.
- `/verify/answer` (`learn.py:219`): confirm → learnings `confidence=1.0` + XP + wiki entry;
  correction → new confidence-1.0 learning; reject → marked rejected/unused.
- `/verify/stats` (`learn.py:231`).
- **BUG (F13): the answer loop has NO UI.** grep for `verify/next|verify/answer|verifyAnswer`
  in `ui/` = **zero hits**. growth.js only *shows* the counts. A GUI user cannot confirm/reject
  facts — the entire learn-and-verify feedback loop is unreachable from the frontend. Endpoints
  fully functional (`tests/test_verification_queue.py` covers them). **This is the biggest gap.**

**Capability trends.** `capabilities`/`capability_domains` tables; `level`, `confidence`,
`trend`, `practice_count`. Practice awards +30 XP (`capabilities.py:148`). Rendered as bars +
trend arrows. **Status: working** (assuming rows exist).

**Knowledge watcher.** Auto-started in `main.py:532 start_knowledge_watcher()` but `start()`
returns False when **no watch dirs configured** (`knowledge_watcher.py:184-186`) — empty by
default. So default state = "not active" (correctly shown), and only lights up when the user
configures watched folders. **Status: working (opt-in).**

---

## 7. STATUS TABLE

| Feature | Status | Evidence |
|---|---|---|
| Learning create via `/learn/` + "remember" button | **working** | `chat-render.js:380`→`learn.py:72`→`learnings.py:save_learning` |
| Learning quality gate | **working (default-flag caveat)** | `distill.py:41` (schema default True `config_schema.py:75`; module default False `distill.py:47`) — **F16** |
| Learning filter / rate-limit / dedup | **working** | `learnings.py:40-98` |
| Confidence scoring + adjusted-confidence decay | **working** | `learnings.py:_apply_confidence_decay`, boosts `vector_store.py:929` |
| `memory_retrieval_min_adjusted_confidence` (UI slider) | **dead** | schema/`runtime_safety.py:440` only; no consumer (grep) — **F1** |
| Learning injection into chat turn | **working** | `context_builder.py:103,115`→`retrieval/__init__.py:329` |
| Memory browse / edit / delete | **working** | `memory.js`↔`memory.py:324/384/432` |
| Semantic recall (Chroma) | **working** | `vector_store.search_memories_full:1010` |
| Semantic recall compiler-free (fallback store) | **working** | `fallback_store.py:41`, selected `vector_store.py:166-171` |
| Semantic recall under "potato" preset | **disabled-by-design** | `use_chroma=False` in preset `config_schema.py:21` → FTS-only |
| Hybrid BM25+vector RRF / weighted fusion | **working** | `vector_store.py:684/604` |
| HyDE | **working (opt-in)** | `vector_store.py:837`, `hyde_enabled` default False |
| Cross-encoder / BGE / MMR rerank | **working (fail-open)** | `vector_store.py:799/764` |
| `memory_router.query` semantic path | **broken (dead)** | calls nonexistent `semantic_search` `memory_router.py:508`; no prod caller — **F2** |
| Global smart search (`/search`) | **working** | `search.py:18`↔`search.js` |
| Elasticsearch mirror + search | **working (opt-in, off by default)** | `elasticsearch_bridge.py:20`, `memory.py:257` |
| File checkpoints — create/retention | **working** | `file_checkpoints.py:84`, `file_ops.py`/`sandbox_core.py` |
| File checkpoints — list/restore endpoints | **working** | `memory.py:276/291` |
| File checkpoints — UI panel | **broken** | UI `/file_checkpoints` vs route `/memory/file_checkpoints` — **F3**; field shape — **F4** |
| Knowledge ingest (dir/source→KB) | **working** | `knowledge.py:28` |
| Import chat (WhatsApp→knowledge) | **partial** | backend `knowledge.py:124` solid; thin UI entry — verify |
| Relationship codex — direct edit | **working** | `codex.py:30/45`↔`index.html:915` |
| Relationship codex — proposals | **partial** | backend `codex.py:72-134` working; UI surface limited |
| Memory bundle export | **working** | `memory.py:133`, link `index.html:219` |
| Memory bundle import | **working** | `memory.py:185` |
| Memory rebuild | **partial** | `vector_store.rebuild_collection:210` working; minimal UI |
| XP awards (11 sources) | **working** | table §6 (`award_xp` call sites) |
| Rank/phase/unlocks | **working** | `maturity_engine.py:44/355` |
| Unlocks → system prompt injection | **working** | `system_head_builder.py:728` |
| Trust tier → autonomy gating | **working (opt-in, default off)** | `maturity_engine.py:236`; gates `jobs.py:81`,`coordinator.py:289`,`initiative_engine.py:102` |
| Growth dashboard (XP/rank/caps/types) | **working** | `growth.js`↔`learn.py:244`+`settings.py:563` |
| Growth velocity sparkline | **broken** | dict vs array — **F5** |
| Growth watcher-status widget | **broken** | field-name mismatch — **F6** |
| Verification queue — submit (ingestion) | **working** | `pipeline.py:134` |
| Verification queue — next/answer/stats endpoints | **working** | `learn.py:205/219/231` |
| Verification answer loop — UI | **ui-missing (backend-without-ui)** | zero `/verify/` calls in `ui/` — **F13** |
| Verified fact → confidence 1.0 + XP + wiki | **working** | `verification_queue.py:236-265` |
| Capability trends | **working** | `learn.py:301`, `capabilities.py` |
| Knowledge watcher | **working (opt-in; empty dirs by default)** | `knowledge_watcher.py:184`, `main.py:532` |

---

## 8. TOP UX PROBLEMS (ranked)

1. **[F13] The verify loop is invisible — the flagship "learn & confirm" mechanic has no UI.**
   *Why/impact:* the entire product story ("she asks you to confirm what she learned, and it
   makes her smarter") is backend-complete but the GUI never calls `/verify/next` or
   `/verify/answer`. Facts pile up in the queue at 0.6 confidence and never get user-confirmed;
   the +12 XP / confidence-1.0 / wiki payoff never triggers from normal use. Highest-value,
   lowest-effort fix in the cluster: add a "Facts to confirm (N)" surface in the Growth/Memory
   panel that hits the existing endpoints.

2. **[F3] Checkpoints panel is dead due to a one-word path bug.** *Why/impact:* file checkpoints
   are the safety net for agent file edits, yet the panel always shows "Could not load
   checkpoints" because the UI calls `/file_checkpoints` instead of `/memory/file_checkpoints`.
   Users can't see or restore snapshots → they distrust letting Layla write files. One-line fix.

3. **[F1] "Min-confidence" retrieval slider does nothing.** *Why/impact:* the Memory & Knowledge
   settings expose `memory_retrieval_min_adjusted_confidence` as a live control, but no code
   reads it. A user who cranks it to filter out shaky memories gets zero behavior change — a
   silent-no-op control is worse than no control (erodes trust in the whole settings surface).

4. **[F5/F6] Growth dashboard shows wrong/empty data (sparkline + watcher).** *Why/impact:* two
   independent frontend/backend contract mismatches mean the velocity sparkline is *always*
   empty and the watcher widget *always* reads 0 folders/0 processed, even when both have real
   data. The dashboard is the main "is she growing?" view; showing perpetually-zero widgets makes
   the growth system feel broken/fake.

5. **[F2] `memory_router` "gatekeeper" is half-dead.** *Why/impact:* the module documented as
   "THE MEMORY ROUTER IS THE GATEKEEPER … all reads go through here" has a broken semantic-read
   path (`semantic_search` doesn't exist) and no production read callers. Real retrieval quietly
   bypasses it. Not user-visible today, but it's a landmine: any future feature that trusts the
   router's `query()` for semantic reads will get empty results.

6. **Semantic memory silently downgrades under "potato" [Q1].** *Why/impact:* the compiler-free
   fallback store means semantic memory *could* run on a weak laptop, but the "potato" preset
   sets `use_chroma=False`, dropping to keyword-only FTS. The friend most likely to pick "potato"
   is the one who most benefits from the fallback. Consider decoupling "low resource" from
   "disable semantic" (the fallback is already CPU-cheap), or clearly labeling the tradeoff.

7. **[F7] Duplicated XP thresholds / phase logic client-side.** *Why/impact:* `growth.js`
   hardcodes the XP curve and phase names that also live in `maturity_engine`. The server already
   returns `xp_to_next`; the client recomputes and ignores it → guaranteed drift if thresholds
   ever change. Low user impact now, maintenance hazard.

8. **[F16] Quality-gate default disagreement.** *Why/impact:* `config_schema` advertises the
   learning quality gate as **on** (default True) but `distill.passes_learning_quality_gate`
   treats a missing key as **off** (`distill.py:47`, `cfg.get(..., False)`). On a config that
   omits the key, low-quality learnings slip in despite the UI implying the gate is active.
   Cosmetic-looking, but it means the advertised "we filter junk memories" guarantee isn't
   enforced on default/partial configs.
