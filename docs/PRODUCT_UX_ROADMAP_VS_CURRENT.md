# Product UX roadmap vs current Layla (evaluation)

This document maps an older “Life OS / personal intelligence” product draft to what the repository actually ships today, and lists **deferred** work so expectations stay honest.

## Summary table

| Theme | Vision pain | Current state | Gap |
|--------|-------------|---------------|-----|
| Setup | Too many steps for non-technical users | Web first-setup overlay (`/ui`), `/setup_status`, `INSTALL.bat` / `install.sh`, hardware probe | No single wizard for language + tone + “depth”; optional integrations (Discord, etc.) stay separate |
| Mental model | User doesn’t know what is remembered | `GET /platform/knowledge`, Library → Knowledge panel, Memory subtab, `/learnings`, `/memory/stats` | Learnings were easy to miss; relationship codex lived only on disk until API/UI; when distill vs reply fires is still mostly implicit |
| Relationship codex | Should be visible and editable | `.layla/relationship_codex.json` + [`agent/services/relationship_codex.py`](../agent/services/relationship_codex.py) | **Addressed in this track:** `GET/PUT /codex/relationship`, Workspace **Codex** tab, optional `relationship_codex_inject_enabled` |
| Personality over time | “Knows me deeply” not just flavor | Dynamic `personalities/*.json`, planner/decision nudges | No DB-backed longitudinal “relationship tone evolution” product |
| Fast vs heavy model | Small model for chat/routing | [`agent/services/model_router.py`](../agent/services/model_router.py), `chat_model` / `coding_model` / `reasoning_model` | Operator-configured; not a single in-UI “depth” slider |
| Parallel brain | Serialized LLM, heavy context | Batched read-only tools, RAG knobs, planning bias | Still one primary decision path per step; not a full tiered context loader product |
| Background intelligence | Proactive curiosity / reflection | Study scheduler, distill, missions, file-plan loops | Not one unified “continuous life agent” orchestrator |
| Chat import from UI | Drag/drop / obvious path | Tool `ingest_chat_export_to_knowledge` (approval-gated, path under workspace) | Documented in RUNBOOKS; no dedicated upload endpoint in this track |

## Deferred (not claimed as shipped)

- **Life OS** — goals/habits/time coaching as a first-class product layer  
- **Full psychological modeling UI** — beyond operator-written codex + existing memory fields  
- **Financial / health intelligence** — dedicated domains  
- **Navigable life knowledge graph** — beyond current graph hints and DB helpers  
- **True parallel multi-LLM** reasoning pipelines  
- **Discord/Meta onboarding** — separate from core Layla install  

## Intent of recent UX work

1. **Transparency** — counts and lists for learnings; clearer copy for memory vs codex.  
2. **Codex first-class** — browse/edit JSON-backed relationship notes in the Library without hunting for files.  
3. **Optional injection** — when enabled, a **short capped** codex digest may enter the system context (local data only; operator opt-in).  
4. **Documentation** — this file + IMPLEMENTATION_STATUS / ARCHITECTURE / RUNBOOKS pointers.

## Related code

| Piece | Location |
|--------|----------|
| Codex service | [`agent/services/relationship_codex.py`](../agent/services/relationship_codex.py) — `suggest_codex_updates` / `codex_has_entities` (read-only hints) |
| Codex HTTP | [`agent/routers/codex.py`](../agent/routers/codex.py) |
| Codex in loop | When `relationship_codex_inject_enabled`: digest in **system head** right after **identity**; **decision** JSON prompt gets `decision_bias_prompt_extension(..., relationship_codex_active=True)`; **inline initiative** prefixes suggestions when codex has entities. Tool **`codex_suggest_update`** (read-only, no auto-write). |
| System head / memory assembly | [`agent/agent_loop.py`](../agent/agent_loop.py) `_build_system_head` |
| Learnings API | [`agent/main.py`](../agent/main.py) `GET /learnings`, `DELETE /learnings/{id}` |
| Memory bundle | [`agent/routers/memory.py`](../agent/routers/memory.py) |
