# State Audit — Backend↔UI Wiring Gaps

**Scope:** Cross-check every mounted FastAPI router in `agent/routers/*.py` against the UI layer in `agent/ui/` (52 components + `core/` + `services/`) to find (A) backend capabilities with **no UI surface** and (B) UI calls hitting **missing/renamed backend endpoints**.

**Method:**
- Enumerated 58 router files; confirmed which are mounted in `agent/main.py` (all functional routers are `include_router`'d; `learn.py` is self-included via `agent.py`; `paths.py` is a constants module, not a router).
- Extracted every `@router.{get,post,...}` path per router (prefix-aware).
- Extracted every API path literal called from `agent/ui/components/*.js` (and reconciled the local `fetch(url,…)` wrapper pattern, which hides paths behind a `url` variable — verified via whole-tree grep, filtering out docstring/comment matches).
- Reconciled prefix mismatches (e.g. router `prefix="/memory"` vs a bare `/elasticsearch` UI call).

**Bottom line:** The backend is *far* larger than the UI. ~18 mounted, functional feature routers have **zero UI surface**, several of them headline "intelligence-tier" vision features (mood, goals, world-state, decisions, timeline, learned-skills, cross-project, feedback, explain, operating-manual, automation, vision/VLM). Two confirmed **broken** UI→backend calls exist (`/codex/user`, `/elasticsearch/search`), both silently 404 in shipped panels.

---

## Router mount status (main.py)

All routers listed below are mounted and functional. `learn.py` is nested under `agent.py` (mounted at `/`). `paths.py` is not a router (layout constants). `__init__.py` is empty.

---

## (A) Backend capabilities with NO UI surface (UNSURFACED)

Severity key: **HEADLINE** = named in the product vision / intelligence-tier backlog (BL-2xx) as a marquee capability; **MID** = real user-facing feature but secondary; **MINOR** = utility/diagnostic or already covered by an adjacent surfaced endpoint.

| # | Router (prefix) | Key endpoints | Feature | Severity | Notes |
|---|---|---|---|---|---|
| 1 | `world_state.py` (`/world`) | `GET /world`, `GET /world/summary` | **World State Model** (BL-241) | **HEADLINE** | Entity/relationship world model. No component references `/world` anywhere. |
| 2 | `decisions.py` (`/decisions`) | `GET/POST /decisions`, `/decisions/search`, `/decisions/{id}` | **Decision Memory** (BL-235) | **HEADLINE** | "Why did we decide X" recall. Zero UI. No `decisions.js` component exists. |
| 3 | `timeline.py` (`/timeline`) | `GET /timeline`, `/timeline/days`, `/timeline/episodes`, `/timeline/episodes/{id}` | **Temporal Memory Timeline** (BL-234) | **HEADLINE** | Episodic timeline. The only `/timeline` hit in UI is a *docstring* in `workspace.js`, not a call. No `timeline.js`. |
| 4 | `learned_skills.py` (`/skills/learned`) | `GET /skills/learned`, `/acquire`, `/{name}`, `/{name}/invoke` | **Skill Acquisition from Tasks** (BL-238) | **HEADLINE** | Layla learning & invoking new skills. Nothing calls `/skills/learned`. (`/skills` in workspace.js is the *static* tool registry, a different router — `system.py`.) |
| 5 | `cross_project.py` | `GET /intelligence/cross-project/graph`, `/intelligence/cross-project/related` | **Cross-Project Reasoning** (BL-232) | **HEADLINE** | Knowledge graph across projects. No UI. |
| 6 | `goals.py` (`/goals`) | `GET /goals`, `/goals/suggestions`, `POST /goals`, `/{id}/progress`, `/{id}/status` | **Goals & Proactive Progress** (BL-240) | **HEADLINE** | Goal tracking + proactive nudges. No UI. |
| 7 | `mood.py` (`/mood`) | `GET /mood`, `POST /mood/signal`, `/mood/reset` | **Emotional Presence** (BL-190) | **HEADLINE** | Mood/emotional-state model. No UI reads or displays mood. |
| 8 | `feedback.py` (`/feedback`) | `POST /feedback`, `GET /feedback/stats`, `/feedback/hint` | **Learning from Feedback** (BL-242) | **HEADLINE** | Thumbs-up/down learning loop. No feedback affordance in UI. |
| 9 | `explain.py` (`/explain`) | `POST /explain` | **Explainable Reasoning Mode** (BL-237) | **HEADLINE** | "Explain your reasoning". No UI trigger. |
| 10 | `operating_manual.py` (`/manual`) | `GET /manual`, `/manual/summary`, `/manual/notes`, `POST /manual/notes` | **Personal Operating Manual** (BL-236) | **HEADLINE** | User's how-to-work-with-me manual. No UI. |
| 11 | `automation.py` (`/automation`) | `GET/POST /automation/rules`, `/rules/{id}/enabled`, `DELETE`, `POST /automation/emit` | **Event-Driven Automation** (BL-233) | **HEADLINE** | Rule engine (if-this-then-that). No UI to view/create rules. |
| 12 | `vision.py` (`/vision`) | `GET /vision/status`, `POST /vision/analyze` | **Visual Understanding (VLM/OCR)** (BL-230) | **HEADLINE** | Image analysis. No UI upload/analyze path. |
| 13 | `learning_verification.py` (`/memory/verification`) | `POST /memory/verification/run`, `GET /memory/verification/contradictions` | **Memory Self-Consistency / Contradiction Detection** (BL-192) | **HEADLINE** | Contradiction surfacing. No UI. (Distinct from the `/verify/*` quiz loop, which *is* surfaced via `verify.js`/`growth.js`.) |
| 14 | `agents.py` (`/agents`) | `POST /agents/spawn`, `GET /agents/blackboard/{job_id}` | **Multi-agent spawn + blackboard** | **MID** | Sub-agent orchestration. No UI. (Consistent with the known multi-agent gating; the blackboard has no viewer.) |
| 15 | `intelligence.py` — AI compute half (`/intelligence/airllm/*`, `/compress`, `/compress/rag`, `/optimize`) | AirLLM generate/chat/unload, context compression, prompt optimizer | **AirLLM / Compression / Prompt Optimizer** | **MID** | The **KB half** of this router (`/intelligence/kb/*`) IS surfaced (`kb.js`, settings-full). The compute/optimizer half is not. |
| 16 | `missions.py` — board/horizon views (`GET /missions/board`, `GET /missions/horizon`) | Server-computed Kanban board + horizon grouping | **MID** | `missions.js` IS wired for `/mission*` CRUD but builds its *own* board client-side from the flat `/missions` list — the server's pre-grouped `/missions/board` and `/missions/horizon` projections are unused. |
| 17 | `conversations.py` — **branching** (`POST /{id}/fork`, `GET /{id}/branches`, `GET /{id}/compare/{other_id}`) | **Conversation branching / fork-compare** | **HEADLINE** | Backend + API shipped per project notes ("UI pending"). Confirmed: `conversations.js` has no fork/branch/compare call. This is the explicitly-noted pending-UI feature. |
| 18 | `knowledge.py` — research→KB ingest (`GET /knowledge/ingest/sources`, `POST /knowledge/ingest`) | **Research → Knowledge-Base ingest** | **MID** | `settings-full.js` wires only `/knowledge/import_chat`. The generic `/knowledge/ingest` (+ source listing) has no UI. |

### Partially-unsurfaced sub-endpoints (router is otherwise surfaced)

| Router | Unsurfaced sub-endpoints | Severity | Notes |
|---|---|---|---|
| `memory.py` (`/memory`) | `GET /memory/stats`, `/memory/about`, `/memory/export`, `POST /memory/import`(*import is wired*), `GET /memory/conflicts`, `POST /memory/conflicts/{id}/resolve` | **MID** | `memory.js` wires `/memory/browse` + `/memory/import`; `workspace.js` wires `/memory/file_checkpoints`. **Memory conflict resolution** (`/memory/conflicts` + resolve) — a self-consistency feature — has no UI. `stats`/`about`/`export` also unsurfaced. |
| `character.py` (`/character`) | `GET /character/earnable-titles` | **MINOR** | Most of the character router is surfaced by `character-creator.js`; the earnable-titles catalog view is not. |
| `system.py` (remote/tunnel/tailscale block) | `/remote/tunnel/*`, `/remote/tailscale/*`, `/remote/token/rotate`, `/remote/audit*` | **MID** | Remote-access / tunnel management (Cloudflare/Tailscale funnel, token rotation, access audit) has no UI panel — it's config-file / CLI only. Named in remote-mode allowlist but no component drives it. |
| `tools_history.py` (`/tools`) | `GET /tools/history` | **MINOR** | `tools-history.js` calls `/tools/analysis` (aggregated) but not the raw `/tools/history` list. Low impact (analysis subsumes it). |
| `journal.py` | `GET /journal/daily` | **MINOR** | `journal.js` wires `/journal` (list+add) but not the `/journal/daily` rollup. |
| `approvals.py` | `POST /refresh_lens_knowledge` | **MINOR** | No UI trigger. |
| `debate.py` | (fully surfaced) | — | `debate.js` wires `/debate` + `/debate/modes`. OK. |
| `learn.py` (`/verify/*`, `/api/growth/stats`, `/memories`, `/schedule`) | `GET /verify/stats` used by `verify.js`; `/schedule` (POST) | **MINOR** | `/schedule` (autonomous-study scheduling) not obviously driven from a component. |

---

## (B) UI calls to MISSING / RENAMED backend endpoints (BROKEN)

| # | UI file | UI call | Backend reality | Severity | Effect |
|---|---|---|---|---|---|
| 1 | `settings-full.js` (`refreshRelationshipCodex`, `saveRelationshipCodex`) | `GET /codex/user`, `PUT /codex/user` | **No such route.** `codex.py` (prefix `/codex`) exposes `GET/PUT /codex/relationship` (+ `/codex/proposals*`). The endpoint was renamed `user`→`relationship` and the UI was not updated. | **HEADLINE (broken)** | The "Relationship codex" settings panel always shows `Error` on load and every Save fails (404). A shipped, visible panel is dead. Fix = rename UI calls to `/codex/relationship`. |
| 2 | `workspace.js` (elasticsearch search box, line ~445) | `GET /elasticsearch/search?q=…` | **Wrong prefix.** The real route is `GET /memory/elasticsearch/search` (`memory.py` has `prefix="/memory"`). The UI drops the `/memory` prefix. | **MID (broken)** | The workspace full-text/Elasticsearch search returns 404 (when ES is even configured). Fix = call `/memory/elasticsearch/search`. Note: the sibling `/memories?q=` call on line 429 IS correct (learn router top-level route). |

> No other broken calls found. Spot-checked the non-obvious ones and they resolve correctly: `/execute` in workspace.js is `/plans/{id}/execute` (real), `/agent/background` (real, `agent_tasks.py`), `/onboarding/stage` (real), `/setup/auto`, `/doctor`, `/platform/*`, `/study_plans/*`, `/plans/{id}/viz` — all present.

---

## Cross-reference summary (per feature)

**Fully surfaced (UI reaches it):** agent, agent_tasks, approvals, autonomous, character, cluster, codex*(broken sub-call), conversations*(no branching), debate, german, improvements, intelligence-KB, journal, kits/marketplace, knowledge-import, language/tutor, macros, memory-browse/import/checkpoints, metrics, missions-CRUD, obsidian, pairing, plans, projects, research, search, session, settings, setup_profiles, study, sync, tools-analysis, voice, workspace-platform, openai/ollama-compat (client APIs).

**UNSURFACED routers (no UI at all):** `world_state`, `decisions`, `timeline`, `learned_skills`, `cross_project`, `goals`, `mood`, `feedback`, `explain`, `operating_manual`, `automation`, `vision`, `learning_verification`, `agents`, + AI-compute half of `intelligence`, + `missions/board`+`missions/horizon`, + conversation branching, + `knowledge/ingest`, + `memory/conflicts`, + remote-tunnel management.

**Count:** ~18 distinct mounted feature-areas with zero user-reachable surface; 12 of them are HEADLINE intelligence-tier / vision features.

---

## Why this matters (interpretation)

The user's intuition is correct: a large slice of the **BL-230..242 "intelligence tier"** and **BL-190/192 emotional/verification** work is **built, tested, and mounted server-side but has no UI door**. These aren't stubs — the routers have real handlers and DB backing (per the shipped/tested backlog). The gap is purely the last-mile UI wiring:

- The **flagship differentiators** of Layla's vision (a companion with *mood*, *goals*, a *world model*, *decision memory*, a *timeline of episodes*, *learned skills*, *cross-project reasoning*, *self-consistency/contradiction checks*, *explainable reasoning*, and an *operating manual*) are exactly the ones with no surface. A user running the app today cannot see or drive any of them.
- Two visible panels are **actively broken** (`/codex/user`, `/elasticsearch/search`) — cheap, high-value fixes (one-line path renames each).
- The lowest-effort / highest-impact next steps: (1) fix the two broken calls; (2) surface `conversation branching` (explicitly flagged "UI pending"); (3) build read-only panels for mood / goals / world-state / timeline / decisions (they already have clean GET endpoints returning summaries).

## Suggested remediation order

1. **Fix broken** — rename `/codex/user`→`/codex/relationship` (settings-full.js); `/elasticsearch/search`→`/memory/elasticsearch/search` (workspace.js). *(trivial)*
2. **Surface conversation branching** — fork/branches/compare in `conversations.js`. *(already-shipped backend, flagged pending)*
3. **Read-only "presence" panels** — mood, goals, world_state/summary, timeline, decisions: all have GET `…/summary`-style endpoints → low-effort dashboards.
4. **Interactive** — operating_manual notes, feedback thumbs, automation rules, learned_skills invoke, vision analyze, memory/conflicts resolve.
5. **Wire server projections** — swap missions.js client-side board for `/missions/board`+`/missions/horizon`; add `/knowledge/ingest` and `/memory/verification` triggers.
