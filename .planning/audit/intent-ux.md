# Layla — Intended UX / UI & Feature Vision (GSD audit: intent map)

**Author:** GSD intent-analyst pass · **Date:** 2026-07-09
**Scope:** what Layla's UX/UI is *supposed* to be — synthesized from the release
plan, canonical PLAN, BACKLOG, VISION (ADR-006), and the design docs. This is the
**intended** model, not a verification of what ships. Where the docs contradict
each other (there are two live design directions), both are recorded with the
governing decision.

**Primary sources:**
- `RELEASE-CASTILLA.md` — the release identity (Spanish-first, potato-tier, per-aspect kits).
- `.planning/CASTILLA_RELEASE_PLAN.md` — the **locked UI/UX remediation plan** (U1–U9), the design direction, the redesign mandate, and the installer track. *This is the most authoritative intent doc for the UI.*
- `.planning/PLAN.md` §6 — the **GUI redesign spec** (5 principles, design tokens, IA, Settings model, startup flow, G1–G6 build order).
- `agent/docs/VISION.md` + `agent/docs/adr/006` — **Companion-First** product rules and the 10-phase experience plan (onboarding, memory, growth, relationships).
- `docs/design/08-ui-frontend.md`, `09-personality-aspects-ethics.md`, `02-memory-and-knowledge.md` — subsystem design + stability truth.
- `.planning/BACKLOG.md` — itemized feature intent (BL-###), including the German→any-language tutor, intake quiz, memories, aspects, per-aspect differentiation.

**A note on the two design directions (important context):** the codebase carries
**two live aesthetic specs that disagree**, and this matters for anyone reading UI intent:
1. **Warframe-mystic / neon HUD** (`docs/design/08`, old `layla-enhanced.css`) — clip-path panels, void-glow, scanlines, `--wf-cut`. **Explicitly retired** ("stale claims retired — do not resurrect", PLAN §11).
2. **Disciplined Dual-Tone** (`CASTILLA_RELEASE_PLAN` Part 0, PLAN §6) — the **governing** direction: keep the gothic/wine-rose *companion* identity as accents/moments, but make the **work canvas** calm, legible, humanist-sans, generously spaced. **This is the locked call (Decisions #1, 2026-07-07), with a full-redesign mandate** — rebuild layout/IA from scratch where better, don't just retint.

Everything below describes the **Dual-Tone / Companion-First** target.

---

## 0. The one-paragraph intent

Layla is meant to feel like a **private, local companion that grows with you**, not
an AI control panel (ADR-006 Rule 3: *Companion First, Workstation Second*). The
surface should lead with **one conversation, one active aspect, and felt continuity**
(memory that resurfaces, growth you notice, initiative that's rare and warm), with
all the platform power reachable through **progressive disclosure** — a command
palette, a slide-in context panel, and grouped Settings — never a firehose. The
brand is deliberately gothic/mythic (goddess "aspects", Cinzel wordmark, wine-rose
on near-black); the discipline is to make that read as *intentional and premium*,
not busy. First run must be **honest** (tell the truth about the machine) and
**proven** (run a live self-test before saying "ready").

---

## 1. Tabs / Panels / Views — what is supposed to exist

The intended IA (PLAN §6 "IA", reinforced by `CASTILLA_RELEASE_PLAN` U5/U6) is a
**disciplined shell**, deduped to *one canonical place per destination*. The current
app has **duplicate destinations** (Settings ×3, every panel in both a left
`sidebar-nav` and a right `rcp-tab` strip — verified in `ui/index.html:293-299` and
`:442-447`); the intent is to collapse these.

### 1.1 Intended shell layout (PLAN §6 IA)

```
┌────┬──────────────┬───────────────────────────────┬─────────────┐
│Asp │ Conversations│ Main work canvas              │ Context     │
│rail│ (280px,      │ slim header:                  │ panel       │
│64px│ collapsible) │  title · aspect · 1 system dot│ (320px,     │
│    │ - new chat   │  · … menu                     │ slide-in,   │
│    │ - search     │ messages (chat, hero to code) │ OFF by      │
│    │ - conv list  │ composer                      │ default)    │
└────┴──────────────┴───────────────────────────────┴─────────────┘
```

- **Aspect rail (64px, left):** the aspect switcher IS the primary navigation gesture
  (PLAN §6 principle 4: "the aspects ARE the navigation"). Shows the 6 aspects; active
  aspect re-themes the whole shell.
- **Conversations rail (280px, collapsible):** new chat + search + conversation list
  only. (§4 below.)
- **Main work canvas:** slim header (conversation title · active aspect · a **single
  system dot** that pops a governor/health/uptime popover · a `…` overflow menu),
  then the message list, then the composer. The status-chip *row* (governor, maturity,
  facts, cluster, uptime — currently 5 cards in the sidebar, `index.html:302-338`)
  collapses into that one dot.
- **Right context panel (320px, slide-in, OFF by default):** panels are *overlays/
  slide-ins*, **not** a permanent third column (the current 520px right panel that
  auto-opens over the composer is the exact anti-pattern U5 targets, `main.js:228`).

### 1.2 Kept surfaces (the canonical destination list)

PLAN §6 names exactly six kept surfaces; `CASTILLA_RELEASE_PLAN` U6 says the
right-panel tab strip is the *single* canonical destination list:

| Surface | What it is / does |
|---|---|
| **Chat** | The work canvas — conversation + code + composer. The default. |
| **Aspects** | Aspect switcher + per-aspect "why switch to me" detail (see §6). Aspect *creator* lives in Settings, not here. |
| **Memory / Knowledge** | The memories experience — learnings, facts, knowledge, relationship codex (see §3). This is the "memories tab." |
| **Models & Kits** | Hardware-aware model browser/downloader + the kit marketplace (per-aspect domain kits). |
| **Settings** | 8 grouped, progressively-disclosed pages (see §1.3). One gear entry (topbar), not three. |
| **Doctor** | Diagnostics/health/self-test (operator-facing, demoted from the companion rail). |

Everything else (Research, Artifacts, Library, Missions, Journal, Sync, Codex,
Approvals, Plans, Debate, Improvements, Tools-history, Verify-learnings, Macros,
Timeline, KB, Intake-quiz, Language tutor, Custom-aspect, Kit-marketplace,
System-diagnostics) is intended to be reachable via the **⌘K command palette**
(the progressive-disclosure surface — BACKLOG W2 wired ~20 of these as palette
commands) and/or folded into the six kept surfaces, **not** as always-visible tabs.
The command palette itself is **feature-gated**: a command hides when its feature is
off (BL-208), so a minimal install shows almost nothing (VISION Phase 3.5).

### 1.3 Settings — 8 grouped pages (PLAN §6 "Settings")

Intent: *every* config key has a home in **8 grouped Settings pages** with progressive
disclosure (common visible, advanced collapsed) so "nothing is lost and nothing
overwhelms." The exhaustive config-key→page ledger was written as `GUI-FEATURE-MAP.md`
(now in git history; recover when building G3/Settings). The **aspect creator** lives
in Settings, not the aspect rail. Content policy (uncensored/NSFW), deliberation mode,
optional-feature install, appearance, workspace presets, remote access all live here.

### 1.4 Current-vs-intent gap (tabs)

- Current: **duplicate nav** — left `sidebar-nav` (Dashboard/Settings/Models/Library/
  Research/Artifacts) mirrors the right `rcp-tabs` (Dashboard/Settings/Library/
  Research/Artifacts). Settings has 3 entry points. → Intent: **one** canonical strip,
  one Settings gear (U6/W3/W8).
- Current: right panel is a **520px permanent-ish column that auto-opens over the
  composer**. → Intent: **320px slide-in, off by default, opens on explicit action**
  (U5/W2).
- Current: sidebar is a **~20-block firehose** (aspects + maturity card + 5 status
  cards + nav). → Intent: **≤~8 primary items**; telemetry moves to Dashboard/Doctor
  (U5/W5).

---

## 2. Onboarding / Calibration flow (intake quiz → FRAME → profile)

There are **two intended onboarding framings**, and they've been reconciled. Read
them as: **VISION sets the *emotional* order; CASTILLA/PLAN set the *honest-proof*
spine; W-S adds the *self-configuring* keystone.**

### 2.1 The intended first-run sequence (PLAN §6 "Startup", the governing spine)

A **calm, honest, 5-step** flow — "proof not a promise":

1. **Welcome** — `∴ LAYLA` — "A private AI that's yours — runs on your machine,
   remembers what matters." (2-card welcome + local-first/honest/your-data promise —
   built as `components/welcome.js`, BL-091.)
2. **Your machine (honesty card)** — "16 GB · CPU → Qwen2.5-Coder-3B, fast for edits
   and chat." Hardware detection surfaced *honestly*, right-sized (RELEASE-CASTILLA;
   `hardware_probe`). This is the **honesty card** (UPG-24).
3. **Get the model** — one resumable, checksummed progress bar / "Found it ✓"
   (`model_downloader`, `provision_model.recommend_kit`; W7/U7 make this a first-class
   guided step instead of plumbing).
4. **Your space** — pick a workspace folder.
5. **Ready — run the self-test LIVE** — `model loads ✓ · a real reply ✓ · memory ✓`
   → Start chatting (`components/self-test.js`, G5). Personality/voice = optional
   "make it yours," never forced.

### 2.2 The W-S "self-configuring" keystone (BL-200…209) — *what you want to do*

Layered onto the spine (after the model is ready, before the tour): an **intent-driven
setup wizard** so the operator picks a **startup default that fits what they want to
do**, enabling only the tools they need (potato thesis: load only what's needed).

- **"What do you want to do?"** — pick a **use-case profile**: Companion · Coding ·
  Language-learning · Research · Power · Minimal(potato) (`components/setup-profiles.js`,
  BL-201/202). Each profile pre-selects features + aspects + defaults.
- **"Optional features"** — a checklist (voice, MCP, elasticsearch, discord,
  fabrication, remote, vision, …) with **size + deps shown**, pre-seeded by the chosen
  profile, installed on demand (`FEATURE_MANIFEST`, 15 features, BL-200/203/204).
- Persists via `POST /setup/apply`; re-runnable any time via ⌘K → "Set up / reconfigure
  Layla" (BL-206/209). Feature state gates tools (BL-205) and palette commands (BL-208).

### 2.3 The intake quiz → FRAME → profile (identity calibration)

Distinct from feature-setup: a **personality/identity calibration** (VISION 3.4 wanted
this to *lead* the emotional framing; it's implemented as the operator quiz):

- **Intake quiz** — a **S.P.E.C.I.A.L.-style** scenario quiz (`components/intake-quiz.js`,
  REQ-80/BL-093) over `/operator/quiz/*`. Scenario questions across stages → a scored
  **6-stat identity profile**: `technical, creative, analytical, social, patience,
  ambition` (1–10 each; `operator_quiz.py`).
- **FRAME** — those stats feed `frame_modifier.py`, which generates **behavioral
  calibration hints injected every turn** (the "FRAME" = the operator-profile modifier
  that shapes how Layla shows up). Persisted with `finalize:true`.
- The **older 6-step wizard** (`layla-wizard.js`: welcome → setup-check → workspace →
  personality quiz (9 Q) → aspect selection → ready) is the legacy shape; VISION 3.4's
  intended *emotional* order is: **"What should I call you?" → "What do you want help
  with most?" → "What kind of presence do you prefer?" (quiet/curious/proactive/
  analytical/emotional) → hardware detection happens silently in the background.** That
  emotional-first framing is the aspiration; the honest-proof spine (§2.1) is the
  shipped contract.

### 2.4 Onboarding safety (W1/U7) — a hard requirement

**Finishing onboarding must NOT silently enable remote access.** During the audit,
completing the wizard auto-`POST`ed `/setup/apply` and flipped `remote_enabled:true`.
For a privacy product this must be an **explicit, off-by-default, clearly-explained
opt-in** ("Expose Layla to your network / the internet?" with the security
implications). Default first run leaves `remote_enabled:false` (`run_first_time.py`,
`/setup/apply`).

---

## 3. Memory experience — the "memories tab"

The intent is **transparency + felt recall**, not a raw DB browser. Memory is the
companion's *felt* backbone (ADR-006 Rule 2: "recall must feel natural, not robotic").

### 3.1 What a memory / learning / fact is (the model to expose)

The memory subsystem (design/02) has layered surfaces the UI should make legible:

- **Learnings** — the atomic unit. SQLite `learnings` (content, kind/type, confidence,
  source, tags, score) + a Chroma vector for semantic recall. Saved via `save_learning`,
  quality-gated (min 0.35), deduped by content hash. Can be **encrypted at rest** when
  `privacy_level="sensitive"` (BL-020).
- **Facts / entities** — the **relationship codex** (people/things Layla knows about),
  `relationship_codex.json` + `codex_db` entities, browsable/editable (`components/codex.js`,
  BL-044; `/codex/relationship`).
- **Knowledge** — ingested docs/articles (`knowledge/` → Chroma "knowledge" collection;
  KB articles via `components/kb.js`, BL-045).
- **Timeline / episodes** — dated events + reconstructable episodes (`services/memory/
  timeline.py`, BL-234) — intended as a calendar/heatmap ("a month ago you started the
  CNC project").
- **Personal knowledge graph** — structured personal context (NetworkX GraphML).

### 3.2 How memories should be saved (the intended pipeline — VISION Phase 4)

The **complete verification loop**, made *conversational* not silent:
`ingest → extract → classify → verify → **ask user confirmation** → commit to
memory/wiki → resurface naturally later`. The felt version:

> "I noticed this file relates to your CNC workflow. Should I connect it to your
> optimization project notes?"

This is the **Verify-learnings** experience (`components/verify.js`, BL-052 +
`learning_verification.py`, BL-192): step through facts Layla is unsure about →
**confirm** (green) or **correct** (reveal a correction box). Contradiction detection
flags learnings that make opposite claims about the same subject. Also: **feedback
learning** — 👎 + a written correction routes into `save_learning(kind=correction)`
and becomes a prompt hint next turn (BL-242, closing the RL loop).

### 3.3 How memories should be shown / managed (the "memories tab")

- **Browse** — paginated learning list (`components/memory.js`, `/memory/browse`) with
  type/keyword filter, sort (recent/confidence), **inline edit** (PATCH) + **delete**
  (DELETE). Import/export a memory bundle (BL-053).
- **Search** — global search groups results by **Conversations / Learnings / Workspace /
  Knowledge** (`components/search.js`); semantic memory search via `/memories`.
- **The narrative layer (the real intent, VISION 3.2/3.3)** — the memories surface
  should *not* be a metrics dashboard. Replace dashboard-mentality with **narrative
  summaries**: "Layla has learned 47 things about your work," "you've been talking more
  about robotics lately," "remember when you solved the threading bug?", plus active
  projects/ongoing interests. Memory should feel like *she remembers your life, not
  your data* (Continuity Memory: unresolved topics, emotional callbacks, recurring
  interests — VISION 1.2).
- **Precedence is a real, ordered contract** (`MEMORY_PRECEDENCE.md`,
  `context_merge_layers.py`): git snapshot → project instructions → repo cognition →
  project memory → skills → aspect memories → learnings → semantic recall → unified
  retrieval → conversation summaries → relationship memory → timeline → style/identity
  → knowledge graph → strategies. Later layers must not contradict earlier without an
  explicit override. (Relevant if the UI ever exposes "why did she say that.")

### 3.4 Memory precedence: codex vs auto-summary

The **relationship codex** (operator-authored) is canonical for named relationships;
**relationship memory** (auto-summarized) is supporting context and must not override
the codex. The UI should make the operator-authored codex first-class and editable
(PRODUCT_UX_ROADMAP: "Codex first-class").

---

## 4. Conversation experience — sidebar, synthesized titles, history, search

### 4.1 The sidebar / conversation rail

Intended (PLAN §6): a **280px collapsible** rail with, in priority order, **New chat +
search + the conversation list** — and *nothing else competing* (aspects collapse to a
single active-aspect chip; status cards move out — U5/W5). Conversations support
pinning, rename, delete, tags, export, and **project grouping/filtering**
(`components/conversations.js`). Branching/fork-compare exists at the API level
(`fork_conversation`, `/conversations/{id}` branch).

### 4.2 Synthesized titles — NOT timestamps (a real intent, currently a gap)

**Intent:** conversations should carry **meaningful, synthesized titles** (a short
descriptor of *what the conversation is about*), never timestamps and never the raw
first message. The memory note "earned-title garbage" and the chat-pipeline fix
(commit c5b117a) call out title quality as load-bearing for the companion feel.

**Current reality (gap):** `layla/memory/conversations.py:_auto_name_conversation`
just **truncates the first user message to 40 chars + "…"** — it is *not* an
LLM-synthesized topic title. The frontend deliberately keeps a creation-time
placeholder for new chats to avoid a "title stuck loading" bug
(`conversations.js:14`). So the *intended* behavior — a short synthesized title like
"Fixing the threading deadlock" or "German A2 practice" — is **not yet implemented**;
it's first-message truncation today. This is a concrete intent-vs-impl delta worth
flagging to any UX build.

### 4.3 History & search

- **History** — conversations persist in SQLite (`conversations` table, multi-session),
  cached client-side in IndexedDB (`updated_at` index) for fast navigation.
- **Search** — per-conversation search (Ctrl+F), conversation-list search with
  `tag:`/`after:`/`before:` filters, and the global search overlay (debounced,
  AbortController-cancelled, grouped results). Prompt history via ArrowUp/Down.

---

## 5. Maturity / Growth UI evolution

The growth system is meant to be **felt and relational, not gamified** (VISION Phase 2;
ADR-006 Rule 2). "Users should *notice* evolution — not check a dashboard for it."

### 5.1 The maturity model (design/09 §4)

Five named phases gate trust tiers and voice calibration:

| Phase | Rank | Trust tier | Feel |
|---|---|---|---|
| awakening | 0–2 | 0 (suggestions only) | First contact; cautious, explicit about uncertainty |
| attunement | 3–5 | 1 (inline initiative) | Calibrating; clearer boundaries |
| resonance | 6–8 | 2 (background proposals) | Synchronized; confident execution |
| sovereignty | 9–12 | 2 | Deep partnership; teaching mode |
| transcendence | 13+ | 2 | Full trust; principles-first |

Each rank *unlocks behavior* (VISION 2.1): rank 1 → proactive reminders; 2 →
independent curiosity; 3 → relationship synthesis; 4 → autonomous learning sessions;
5+ → long-term project stewardship. Progressive disclosure means **new users see almost
nothing; features emerge through usage, trust, and rank** (VISION 3.5).

### 5.2 How growth should show up in the UI

- **Visible growth moments** (VISION 2.2), not a progress bar: milestone conversations
  ("I've been learning from you for 100 hours"), reflection moments ("here's what I've
  noticed about how you work"), memory anniversaries, "things I've learned about you"
  summaries.
- The maturity/XP card + rank-up ceremony exist (`refreshMaturityCard`, growth widgets;
  the "it learns" verify loop now has a UI per PLAN §10). But the intent is to **move
  the XP/rank card OUT of the primary rail** (U5) — telemetry belongs in Dashboard, not
  outranking "New chat." The **narrative** is the surface, the numbers are secondary.
- **Growth is gated by flags** (`maturity_enabled`) and by scope-cut decisions:
  gamification-as-headline was explicitly **cut** (PLAN §2, §5). So the intended UI is
  *subtle growth moments*, **not** a prominent XP/level HUD.

### 5.3 Known intent-vs-impl truth (design/09 §9)

- **Voice evolution is DEAD** at runtime: maturity phase names (`awakening…`) don't
  match the `voice_evolution` JSON keys (`nascent…`), so per-phase voice lines are
  never injected. Intent: they *should* recalibrate the aspect's voice per phase.
- Title *conditions* ("100 code fixes") aren't tracked — only `rank_req` is checked.
- XP is awarded from only a few code paths; rank-up has no automatic celebration wired
  everywhere. These are the growth gaps between intent and reality.

---

## 6. Aspect switching / display

Aspects are the **defining UX idea** (PLAN §1 thesis; §6 principle 4). Layla is **one
entity with six voices**, not six agents. Each aspect is meant to be a **domain-optimized
*kit***: {best local model for the hardware + right skills/tools + tuned system prompt +
inference settings + visual identity}.

### 6.1 The six aspects (canonical)

| ID | Name | Title | Domain / role | `--asp` color |
|---|---|---|---|---|
| morrigan | Morrigan | The Blade | Coding / implementation (default) | #8b0000 crimson |
| nyx | Nyx | The Quiet Dark | Research / analysis / synthesis | #6a1f9c violet |
| echo | Echo | The Mirror That Remembers | Memory / continuity / growth | #2f5aa8 blue |
| eris | Eris | The Discord That Delights | Creative / lateral / play | #b06a1e amber |
| cassandra | Cassandra | The Voice That Cannot Stop | Critique / warnings / fast perception | #1f7a72 teal |
| lilith | Lilith | The First and the Core | Safety / ethics / boundaries (override authority) | #a33b52 rose |

Canonical label = **"Aspects"** (Decision #4). Keep the goddess **names as identity**
but **lead with function** in the UI: show `Coding · Morrigan`, `Research · Nyx`, so a
first-timer never has to learn "Morrigan = software engineering" to start coding (U6/W4).

### 6.2 How switching should work / display (the primary gesture)

- The **aspect rail is the navigation** — switching personality is the primary gesture.
- On switch, the **whole shell re-themes**: `--asp`/`--asp-glow`/`--asp-mid` CSS vars
  update, `data-aspect` on `<body>` flips, per-aspect SVG sigil/sprite loads, and the
  accent **eases** across the UI (450ms `@property <color>` interpolation, BL-094;
  instant for reduced-motion). Verified reconciled so all 6 `--asp` tokens match each
  identity (G4/BL-095).
- **Aspect lock** prevents auto-routing (pin the current aspect).
- **Selection precedence** (orchestrator, design/09 §3): forced aspect → keyword/name
  trigger scoring → embedding cosine tiebreaker (≥0.35) → default (Morrigan). Dignity
  engine can force-override to **Lilith** on sustained abuse.

### 6.3 The NEW requirement — make differentiation *visible* + real (U9)

Key finding: aspects are already **~60% behaviorally distinct** (distinct system prompt/
voice, reasoning-depth bias, response-length bias, max-steps, refusal authority, decision
bias, aspect-scoped memory retrieval — all injected live per turn) — **the
differentiation just isn't visible.** Two intended deliverables:

- **U9a (higher value) — surface the character that already exists.** Per aspect show a
  compact **"why switch to me" card**: its **domain** (primary/secondary from
  `expertise_domains`), **response length + reasoning depth**, **refusal stance**, **tool
  bias**, and **voice** — in the switcher and an aspect-detail view. This is where
  "surface more options" lands.
- **U9b (opt-in wiring) — make switching change *more*:** per-aspect **tool
  preferences** (boost/suppress — e.g. Lilith suppresses `run_shell`/`write_file`, Nyx
  boosts research tools), per-aspect **sampling** (temp/top_p), per-aspect **model
  routing** (`preferred_model`). All no-op unless a JSON declares it (per-aspect model
  overrides are already wired, PLAN §5/P5).

### 6.4 Aspect creation / customization (the "Character Lab")

- **Character Lab** (`character.py`, design/09 §8): RPG-style customization of the 6 —
  6 personality **sliders** (aggression, humor, verbosity, curiosity, bluntness,
  empathy, 1–10), 4 **voice** sliders (pitch, speed, warmth, formality), color, **titles**
  (4 earnable per aspect, rank-gated), lore. Sliders → prompt hints (only extreme values
  fire). Persisted in `user_identity`.
- **Custom aspect creator** (REQ-79/BL-092): create your OWN named aspect that inherits
  behavior/voice/model from a chosen base built-in, overriding name/sigil/tagline/accent/
  prompt-hint. Additive — the 6 built-ins are never touched. Lives in **Settings**, not
  the rail.

---

## 7. Other user-facing features described in docs/backlog (the disclosure catalog)

These are meant to be **user-facing but progressively disclosed** (command palette /
folded into the six surfaces / gated by feature), per ADR-006 Rule 4. All were wired as
palette commands or panels in BACKLOG W2/W13:

**Companion / knowledge**
- **Language tutor (any language)** — the German tutor generalized to **any language**
  (German/Italian/Spanish first): check-my-writing (`/correct`), flashcard **SRS**, CEFR
  **level**, **placement quiz** (`/calibrate`), correction history, per-`(user,language)`
  profiles, a **language picker** (BL-040/220). Plus **native-language response** — Layla
  can converse natively in any language while persona/capabilities stay identical
  (`response_language`, BL-160). This is the "in your language" wedge.
- **Relationship codex / People space** — known people, relationship summaries,
  interaction evolution, emotional associations (`components/codex.js`; VISION Phase 7
  "People & Relationship Space"). Relationship reflection: "You mention Edgar often
  lately," "your tone changes when discussing work."
- **Journal** — Layla's own entries + operator-added (`components/journal.js`, BL-042).
- **Timeline** — dated events / episodes, meant as a calendar/heatmap (BL-234).
- **Operating manual** — a living doc of derived identity + habits + workflows (BL-236).

**Agentic / research**
- **Research missions** — depth-staged research with approval cards, mission status,
  investigation templates (`components/research.js`). Voice: `RESEARCH_MISSION_UI_GUIDE.md`.
- **Missions board** — kanban of running/paused/queued/done missions (BL-041).
- **Plans & projects** — workspace-scoped plans (create-by-goal → approve → execute,
  step expansion, status badges) + projects (BL-048); Gantt plan-viz.
- **Background/agent tasks** — start a background agent goal, list + cancel (BL-050).
- **Deliberate (aspects)** — solo/debate/council/tribunal multi-aspect modes (BL-046);
  gated behind the `multi_agent` feature.
- **Improvements (self)** — self-improvement proposals: generate/approve/reject (BL-047).
- **Macros / workflows** — record a run's successful steps, replay with params (BL-231).
- **Knowledge base** — browse/read/build-from-text articles (BL-045).

**Trust / control**
- **Approvals & session grants** — pending tool approvals (approve/deny) + active session
  grants with revoke-all (`components/approvals.js`, BL-049). Approval-gating is the trust
  backbone and must be **visible/demoable** (diff/command previews — REQ-63).
- **Tool history & health** — per-tool call counts, success rate, latency (BL-051).
- **Verify learnings** — the conversational memory-verification queue (BL-052; §3.2).
- **System diagnostics** — a ⌘K overlay: governor/health/cot_stats/metrics/security/
  capabilities cards, live (BL-054). Doctor panel (UPG-31).

**Voice / multimodal**
- **Voice** — mic record → transcribe → auto-send; server Kokoro TTS with per-aspect
  voice styles, browser SpeechSynthesis fallback; voice speed/volume settings.
- **Vision** — analyze images (local GGUF VLM + OCR), image input on `/v1` (BL-230).

**Multi-device / ecosystem**
- **Pairing / Sync** — consumer pairing UX: **Desktop shows "Pair Device" → Phone scans
  QR → Done**, no manual configs (VISION 5.1). PIN pairing + paired-device permission
  toggles (`components/pairing.js`); Syncthing status + peer devices + setup guide
  (BL-043). Memory/knowledge sync across paired instances (BL-161).
- **Remote access** — cloudflared/tailscale/tunnel to reach Layla from a phone URL —
  **explicit opt-in, off by default** (W1/U7; `REMOTE_ACCESS.md`).
- **Kit marketplace** — browse/install curated domain kits (Coding Pro, Researcher,
  Voice, Privacy Vault, …), one-click install (`components/marketplace.js`, BL-156).
- **Clients** — CLI, mobile PWA (installable, `manifest.json`+`sw.js`), and editor
  interop via OpenAI-/Ollama-compatible endpoints (no plugin needed).

**Cross-cutting UX intent**
- **i18n / RTL** — full 11-language i18n + RTL (`ui/core/i18n.js` + `ui/locales/*.json`);
  the app must localize, not just render English.
- **a11y** — WCAG 2.1 AA: skip-to-content, focus-visible accent rings on all controls,
  reduced-motion kill-switch, high-contrast mode, ARIA on tabs.
- **Responsive/mobile** — off-canvas sidebar drawer with a working hamburger, topbar
  collapses to `⋮`, chat full-width, zero horizontal overflow (U8/BL-221).
- **Privacy** — no external font/CDN calls (self-host fonts; U1); "runs-on-your-machine"
  must not phone home.

---

## 8. The design-token intent (the system every screen consumes)

The **locked design system** (PLAN §6, canonical `layla-rebuild.css :root` as of
2026-07-04) — with the `CASTILLA_RELEASE_PLAN` U1–U4 *disciplining* it:

- **Palette (one bloodline):** `--bg #0a0008` near-black · `--surface #17021c` /
  `-2 #1f0626` / `-3 #2b0c34` · text `#ece7f3`/dim `#a294b0`/faint · **`--accent #b11655`
  wine-rose** (the signature CTA, *fills only*) · `--accent-text #e85d8a` (text/links
  only) · `--accent-2` muted violet · per-aspect `--asp` · `--success #3fae6b` /
  `--danger #d0454e`. U2: kill off-palette hues (the teal `#4ecdc4`), fix 3 AA failures,
  neutralize the saturated purple border, fix the light-theme token gap.
- **Type (U1 — the highest-leverage fix):** the *shipped* spec says "mono everywhere"
  (JetBrains Mono) + Cinzel wordmark; the **governing remediation (U1)** overrides that to
  a **font-role trio**: `--font-ui` (humanist sans — Inter/IBM Plex, self-hosted, for
  body/labels/buttons/forms) · `--font-mono` (code/hashes/model-ids/metrics only) ·
  `--font-display` (Cinzel — **wordmark + aspect identity ONLY**). Real 6-step scale
  (12/14/16/20/28/40), weight contrast (400 body / 500 labels / 600 headings). *This is
  the single biggest "make it feel premium" lever.*
- **Icons (U3):** one **inline-SVG line-icon set** (Lucide/Feather, `currentColor`), a
  new `components/icons.js`. Retire the half-Unicode-glyph / half-emoji mishmash; keep
  exactly one intentional glyph (the `∴` wordmark). Each aspect gets a *recognizable*
  functional icon (code/telescope/memory/spark/gavel/shield), not `⚔✦◎⚡⌖⊛`.
- **Shape/space (U4):** 3 radii (6/10/14), the `--sp-1..7` scale (4/8/12/16/24/32/48),
  generous rhythm, roomier composer, comfortable chat max-width. Motion: 120ms hover /
  200ms panels, **no glows** (the Warframe void-glow is retired). Ornament budget =
  damask ~4% on empty states + a 2px accent hairline for active state.

---

## 9. The empty / landing state

Intent (U5/W2): **one** empty state, not the current three (`#context-chip`, static
`#chat-empty`, and a JS hero). Pick the **richer JS hero** as the single source (the
"∴ she is waiting" hero + prompt tiles), reconcile the wordmark/tagline to one voice,
first paint shows **one empty state, right panel closed, composer full-width**.

---

## 10. Summary — the intended UX in one frame

Layla should open to a **calm work canvas** with **one conversation and one active
aspect**, an **aspect rail** as the primary navigation, a **clean conversation rail**
(new chat + search + list with *synthesized* titles), and **everything else behind
progressive disclosure** (⌘K palette + a slide-in context panel + 8 grouped Settings
pages). First run is **honest** (right-sized model, honesty card) and **proven** (live
self-test), lets you **pick what you want to do** (profiles + optional features) and
**calibrate identity** (intake quiz → FRAME → profile), never silently enabling remote
access. **Memory feels like she remembers your life** (narrative summaries, conversational
verification, resurfacing), **growth is felt not gamified** (subtle moments, not an XP
HUD), and **aspects are genuinely, visibly different** (a "why switch to me" card backed by
real behavioral differentiation). The gothic/wine-rose soul stays — as *accents and
moments*, disciplined by a real type/color/icon/space token system.

**Highest-signal intent-vs-impl deltas for a UX build to know:**
1. Conversation titles are **first-message truncation**, not LLM-synthesized topic titles (§4.2).
2. Nav is **duplicated** (Settings ×3, panels ×2); intent is one canonical strip (§1.4).
3. Right panel **auto-opens as a 520px column**; intent is a 320px off-by-default slide-in (§1.4).
4. Onboarding can **silently enable remote access**; intent is explicit opt-in, off by default (§2.4).
5. **Voice evolution is dead** (phase/key mismatch); intent is per-phase voice recalibration (§5.3).
6. Body type is **monospace everywhere**; intent (U1) is a humanist-sans work canvas (§8).
7. Aspect differentiation is **invisible**; intent (U9a) is a "why switch to me" card (§6.3).
