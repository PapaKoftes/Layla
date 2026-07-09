# State Audit: Memory System (end-to-end)

Scope: every distinct memory store in Layla, how each is written/read, what triggers a save,
whether there is dedup/consolidation, what the user actually sees, and every gap between
"data exists in the backend" and "the user can see/manage it."

Bottom line: Layla has a **rich, over-engineered backend** (10+ distinct stores) but a
**thin, fragmented front-end**. The only coherent user-facing memory surface is the "Browse
learnings" tab. The store that most resembles Claude/ChatGPT "memories about you" (durable
identity facts + relationship memories + timeline + goals) is fully built, has a read endpoint
(`GET /memory/about`), but has **zero UI** — the endpoint is never called by any page.
Saving is a scattered mix of an inline `remember:` command, a background LLM extractor, and an
LLM tool the model must choose to call; there is no single, reliable "save a fact about the
user" path and no cross-store consolidation.

---

## 1. Distinct memory stores — write path / read path

All SQLite tables live in one DB (`layla.db`, path from `db_connection._resolve_db_path()`,
schema in `layla/memory/migrations.py`). "Vector" = ChromaDB under
`layla/memory/chroma_db/`. "Graph" = `layla/memory/knowledge_graph.graphml` (NetworkX).

| # | Store | Backing | WRITE entrypoint | READ entrypoint |
|---|-------|---------|------------------|-----------------|
| 1 | **Learnings** (facts/preferences/strategies/outcomes) | SQLite `learnings` + FTS5 `learnings_fts` + Chroma vector + optional Elasticsearch mirror | `learnings.save_learning()` (canonical via `services.memory.memory_router.save_learning`) | `get_recent_learnings`, `search_learnings_fts`, `search_memories_full` (vector) |
| 2 | **Durable identity facts / profile** | SQLite `user_identity` (KV) | `user_profile.set_user_identity(key, snapshot)`; tool `update_user_identity_tool` | `get_all_user_identity`, `get_durable_facts` |
| 3 | **Relationship memories** (companion intelligence) | SQLite `relationship_memory` + vector | `user_profile.add_relationship_memory()` | `get_recent_relationship_memories` |
| 4 | **Timeline events** (life_event/milestone/goal/blocker/conversation_summary) | SQLite `timeline_events` + vector | `user_profile.add_timeline_event()` | `get_recent_timeline_events` |
| 5 | **Goals** | SQLite `goals` / `goal_progress` | `add_goal`, `add_goal_progress`; tool `add_goal_tool` | `get_active_goals`, `get_goal_progress` |
| 6 | **Episodes** (episodic grouping) | SQLite `episodes` / `episode_events` | `create_episode`, `add_episode_event` | `get_recent_episodes` |
| 7 | **Aspect memories** (per-personality) | SQLite `aspect_memories` | `save_aspect_memory` | `get_aspect_memories` |
| 8 | **Knowledge base / RAG documents** | `knowledge/*.md`,`*.txt` files + `knowledge/_generated/_index.json` + Chroma "knowledge" collection | `routers/knowledge.py` ingest (`/knowledge/ingest`, `/knowledge/import_chat`), KB builder (`/intelligence/kb/build/text`), knowledge watcher | `vector_search(collection="knowledge")`, `get_knowledge_chunks_with_sources`, `_query_kb_articles` |
| 9 | **Vector store** (semantic index) | ChromaDB (`vector_store.py`; Qdrant alt) | `add_vector`, `embed_and_store` (dual-written from save_learning) | `search_memories_full`, `semantic_search`, `search_similar` |
| 10 | **Knowledge graph** (entities/relations) | NetworkX GraphML + SQLite `entities`/`relationships` | `memory_graph.add_node/add_edge`; `memory_router.upsert_entity/upsert_relationship`; `graph_learning.expand_graph_from_learning` (bg thread on every save_learning) | `load_graph`, `get_neighbors`, `personal_knowledge_graph.get_related_entities` |
| 11 | **Conversation history** | SQLite `conversations` / `conversation_messages` (+ summaries, fork tree, tags) | `append_conversation_message`, `create_conversation`, `fork_conversation` | `get_conversation_messages`, `list_conversations_filtered`, `search_conversations_filtered` |
| 12 | **Operator journal** | SQLite `operator_journal` | `journal.add_journal_entry` (`POST /journal`) | `list_journal_entries` (`GET /journal`) |
| 13 | **Operating manual / directives** | `services.personality.operating_manual` (separate store) | `add_note("comm_style", …)` from `memory_commands` directive branch | injected verbatim into system head |

Supporting/adjacent (not user "memory" per se but written by the same paths): `entities`/
`relationships` (memory_router), `tool_outcomes`, `capabilities`, `study_plans`,
`golden_examples`, `outcome_evaluations`, spaced-repetition state columns on `learnings`.

---

## 2. How memories are saved today — triggers & consolidation

There are **five distinct save mechanisms**, none of which is a single coherent "save what
matters about the user" pipeline:

**(a) Inline `remember:` command** — `services/memory/memory_commands.py`. Regex intercepts
user messages starting with remember/memorize/note/store/save. If the phrasing looks like a
standing *directive* (`_DIRECTIVE_RE`: "always…", "call me…", "from now on…") it goes to the
**operating manual** (always-injected). Otherwise it's a `save_learning(kind="user_fact",
confidence=0.9)`. Deterministic, reliable — but the user has to know the magic word.

**(b) Background auto-extraction** — `services/infrastructure/outcome_writer.py::
_auto_extract_learnings()`. Runs in a background thread after an exchange (response ≥ 20 words,
not a greeting). Calls the LLM to "extract 1-2 concise insights", plus regex heuristics for
operator **corrections** ("actually…", "that's wrong") and **preferences** ("i prefer…", "i
like…", "never use…"). Saved as `learnings` with fingerprint dedup (in-memory OrderedDict, lost
on restart). This is the closest thing to Claude's automatic memory, but it saves *insights*,
not structured user facts, and never touches `user_identity`.

**(c) Tool-driven** — the model may call `update_user_identity_tool(key, snapshot)` (writes
`user_identity` — name/timezone/editor/etc.), `save_note`, `vector_store`, `add_goal_tool`.
This is the *only* path that writes durable identity facts from a conversation, and it depends
entirely on the model choosing to call the tool. **No deterministic identity extractor exists**
(grep for auto identity capture: nothing outside personality/tutorial state writers).

**(d) Tool-success patterns** — `_save_outcome_memory()` persists compact "Tool pattern: X
succeeded" strings as `strategy` learnings after finished multi-step runs.

**(e) Context-overflow summarization** — `services/context/context_manager.py::
summarize_history()`. **Only when the context window overflows**, the compressed prefix is
written to `conversation_summaries`, `relationship_memory`, `timeline_events`, AND an episode.
This is the *sole* writer of relationship memories + timeline events in normal operation
(`rules_engine` and `onboarding_interview` are the only other callers). So stores #3/#4/#6 stay
empty for short conversations and only fill on long ones.

**Quality gates before a learning lands** (in `save_learning`): in-process rate limit (20/60s),
`services.memory.learning_filter.filter_learning`, `distill.passes_learning_quality_gate`
(min-score + hard structural reject of run-log echoes / leaked markers via `_LEARNING_REJECT_RE`),
SHA-1 `content_hash` exact-dedup, optional at-rest encryption for `sensitive`.

**Consolidation / dedup (Claude-style):**
- Exact-dup: `content_hash` prevents identical re-inserts.
- Near-dup merge: `distill.memory_distill` (Jaccard ≥ 0.55) and `memory_distill_semantic`
  (embedding clusters) collapse similar learnings into a "[merged from N similar]" summary and
  delete originals. Triggered by `run_distill_after_outcome` and the scheduler's memory job.
- Contradiction handling: `services.memory.consistency_guard.check_and_flag` runs in a bg
  thread on every save_learning and **flags** (does not resolve) likely contradictions;
  surfaced via `GET /memory/conflicts` + `POST /memory/conflicts/{id}/resolve`.
- Decay/forgetting: `_apply_confidence_decay` (exp, 180-day half-life) at read time; SM-2
  spaced-repetition columns.
- Entity merge: `memory_router.upsert_entity` unions aliases/tags, keeps higher confidence.

So consolidation machinery **exists and is fairly sophisticated** — but it operates on the
`learnings` table, not on a unified "user memory" concept, and the merge/distill jobs are
scheduler-driven, not surfaced to or controllable by the user.

---

## 3. What the user actually sees — scattered, not coherent

There is **no single "Memories" surface**. Memory is smeared across at least six disconnected
UI locations:

1. **Memory tab** (`index.html` ~L888, `components/memory.js`) — sub-tabs **Browse /
   Search / Checkpoints** only. Browse = paginated `learnings` (edit/delete/confidence/tags).
   Search = semantic + Elasticsearch over learnings. Checkpoints = file-write snapshots (not
   memory at all). This is the one polished surface, but it shows **only the `learnings`
   table** — not identity, relationship memories, timeline, goals, or the graph.
2. **Growth tab** (`components/growth.js`, `GET /api/growth/stats`) — fact counts, learning-type
   breakdown, velocity sparkline, capabilities, verification review queue, knowledge-watcher
   status, XP/rank. A *stats dashboard about* learnings, not a place to see or manage them.
3. **Knowledge base** (`components/kb.js`, `⌘K → Knowledge base`) — separate overlay over
   `/intelligence/kb/*`; browse/read/build KB articles. Disconnected from the Memory tab.
4. **Journal** (`components/journal.js`, `⌘K → Journal`) — separate overlay over `/journal`;
   read/add operator-journal entries.
5. **Conversations rail** (`components/conversations.js`) — chat history list/search/rename/
   delete/fork. Users likely don't think of this as "memory," and its fork/compare/branches
   backend (`/conversations/*/fork|branches|compare`) is barely surfaced.
6. **Relationship codex** (Plugins tab) — yet another notes-about-people store
   (`.layla/relationship_codex.json`), read-only "suggest" in UI.

A user asking "what does Layla remember about me?" has **no page that answers that question.**
The data for it exists (`/memory/about`) but is orphaned (see §4).

---

## 4. Written-but-never-surfaced / surfaced-but-never-written

**Written but NOT surfaced (backend data the user cannot see):**
- **`user_identity` durable facts** (name, timezone, editor, pronouns, project_roots…). Written
  by `update_user_identity_tool`; injected verbatim into the system prompt
  (`system_head_builder.get_durable_facts`); but **no UI lists or edits them.** `GET
  /memory/about` returns them and `DELETE /memory/identity/{key}` can forget one — both unused
  by any page (`grep memory/about ui/` → none). **This is the single biggest gap** for a
  Claude-style "memories about you" experience.
- **Relationship memories** (`relationship_memory`) — returned by `/memory/about`, no UI.
- **Timeline events** (`timeline_events`) — returned by `/memory/about`, no UI. (Also barely
  *written*: only on context overflow — see below.)
- **Goals** (`goals`) — writable by `add_goal_tool`, returned by `/memory/about`, no dedicated
  UI panel.
- **Episodes** (`episodes`/`episode_events`) — written on overflow, **no read endpoint, no UI**
  at all. Effectively write-only.
- **Aspect memories** (`aspect_memories`) — written by outcome_writer/aspects; only exposed as a
  count in the `memory_stats` tool; no browsing UI.
- **Knowledge graph** (`knowledge_graph.graphml`, `entities`/`relationships`) — grown on every
  save_learning (bg `expand_graph_from_learning`) and by `upsert_entity`; **no graph
  visualization or browser in the UI.** `check_coherence` exists but is CLI-only.
- **Conversation fork/branch/compare** — full backend (`/conversations/{id}/fork|branches|
  compare`), minimal-to-no surfacing in the rail.

**Surfaced but effectively NOT written (UI exists, store stays near-empty in normal use):**
- **Timeline / relationship / episodes** feed `/memory/about`, but their only routine writer is
  the **context-overflow** path (`summarize_history`). Short-to-medium conversations never
  trigger it, so on a typical box these tables are empty — the (non-existent) "about you" page
  would show almost nothing even though the plumbing is there.

**Consistent / no gap:** Learnings (write path b/a/c + Browse UI), Journal (write + read UI),
KB (ingest + KB overlay), Conversations (append + rail). These four are the coherent loops.

---

## 5. Endpoints for memory CRUD vs. what is wired to UI

| Endpoint | Purpose | Wired to UI? |
|----------|---------|--------------|
| `GET /memory/browse` | paginated learnings | ✅ Memory→Browse (`memory.js`) |
| `PATCH /memory/{id}` | edit learning | ✅ Browse inline edit |
| `DELETE /memory/{id}` | delete learning | ✅ Browse delete |
| `GET /memories?q=` (learn.py) | semantic search | ✅ Memory→Search |
| `GET /memory/elasticsearch/search` | keyword search | ✅ Memory→Search (ES box) |
| `GET /memory/stats` | counts | ⚠️ available; primary dashboard uses `/api/growth/stats` |
| `GET /memory/about` | **identity + relationship + timeline + goals + counts** | ❌ **NOT wired — orphaned** |
| `DELETE /memory/identity/{key}` | forget one durable fact | ❌ **NOT wired** |
| `GET /memory/conflicts`, `POST /memory/conflicts/{id}/resolve` | consistency guard | ❌ NOT wired (no UI) |
| `GET/POST /memory/export`, `/memory/import` | bundle move | ✅ `laylaImportMemoryBundle` + export link |
| `GET /memory/file_checkpoints`, `POST …/restore` | file snapshots | ✅ Memory→Checkpoints |
| `POST /learn/`, `POST /learn/correct` | add/correct a fact | ⚠️ backend/tool; `/learn/correct` has no obvious UI |
| `GET /verify/next|stats`, `POST /verify/answer` | fact verification queue | ✅ Growth tab review card |
| `GET /api/growth/stats` | growth dashboard | ✅ Growth tab |
| `POST /conversations`, `GET /conversations[/search]`, rename/delete/tags | chat CRUD | ✅ Conversations rail |
| `POST /conversations/{id}/fork`, `GET …/branches`, `GET …/compare/{other}` | branching | ❌/⚠️ backend built, little/no UI |
| `POST /knowledge/ingest`, `/knowledge/import_chat[_preview]`, `/workspace/index`, `/workspace/cognition[/sync]` | KB/RAG ingest | ⚠️ partial (import chat UI exists; cognition endpoints mostly programmatic) |
| `/intelligence/kb/articles`, `/intelligence/kb/build/text` | KB articles | ✅ `kb.js` overlay |
| `GET /journal`, `POST /journal` | journal | ✅ `journal.js` overlay |
| goals / timeline / relationship / episodes | (no dedicated read routes except via `/memory/about`) | ❌ mostly none |

---

## Recommendations (for the "sane, Claude-style memories" goal)

1. **Ship an "About you" / Memories surface.** `GET /memory/about` + `DELETE
   /memory/identity/{key}` already exist — build the panel that renders identity facts,
   relationship memories, timeline, and goals with per-item forget. This is the highest-leverage,
   lowest-cost fix (backend done, UI missing).
2. **Add a deterministic user-fact extractor.** Today durable identity relies on the model
   choosing to call `update_user_identity_tool`. Add a high-precision post-turn extractor
   (like the preference/correction heuristics in `_auto_extract_learnings`) that writes
   name/timezone/pronouns/tooling into `user_identity` with a confirmation, so facts land
   reliably like Claude/ChatGPT memories.
3. **Write relationship/timeline events on meaningful turns, not only on overflow.** Move (or
   duplicate) the `add_relationship_memory` / `add_timeline_event` writes out of
   `summarize_history` so these stores fill on normal short conversations.
4. **Unify the surfaces.** Fold KB, Journal, About-you, and Learnings under one "Memory" tab
   with sub-tabs so the user has one mental model, and expose the consistency-guard conflicts
   there as a "review/merge" queue (Claude-style memory management).
5. **Surface or retire the orphans** (episodes read path, knowledge-graph browser, fork/compare
   UI) so backend and UI stop drifting.
