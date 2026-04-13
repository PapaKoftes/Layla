# Memory and context precedence

When multiple memory surfaces apply, **later layers in this list must not contradict earlier ones** without an explicit operator override. Implementation: `agent/services/context_merge_layers.py` defines the canonical order for the **memory block** portion of the system prompt.

## Order (highest authority first)

1. **Git snapshot** — current branch/status (ephemeral factual)
2. **Project instructions** — `AGENTS.md` / `CLAUDE.md` / `.layla/*` from workspace
3. **Repository cognition** — deterministic digest (verify against files when editing)
4. **Project memory** — `.layla/project_memory.json` (structural map; verify against source)
5. **Matched skills** — task-scoped
6. **Aspect memories** — per-aspect observations
7. **Learnings** — SQLite `learnings`
8. **Semantic recall** — Chroma / embeddings
9. **Unified retrieval** — hybrid retrieval block
10. **Conversation summaries** — compressed history
11. **Relationship memory** — derived companion context (often from compression)
12. **Timeline events** — dated events
13. **Style / user identity** — tone and operator prefs
14. **Personal knowledge graph** — structured personal context
15. **Reasoning strategies** — heuristic hints

**System instructions** (identity, safety, codex, anti-drift, honesty) are assembled separately in `_build_system_head` and take precedence over the memory block when the model follows instructions — see [SUBSYSTEM_REGISTRY.md](SUBSYSTEM_REGISTRY.md).

## Codex vs relationship memory

- **Relationship codex** (operator-authored relational facts, injected in system instructions): canonical for named relationships the operator maintains.
- **Relationship memory** (often auto-summarized): supporting context; do not treat as authoritative over codex.

## Goals vs project memory

- **Project memory** file: repo-local plan and todos.
- **Goals** (SQLite): cross-session objectives; both can appear in project context lines — prefer explicit `goals` table titles for commitments, project memory for file-backed checklists.
