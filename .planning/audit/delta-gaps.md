# Layla — Master GAP LIST (Intent vs. Actual)

**GSD gap-analysis pass · 2026-07-09**

**Method:** Cross-referenced the seven foundational audit reports (`intent-vision.md`,
`intent-ux.md`, `state-ui.md`, `state-memory.md`, `state-chat.md`, `state-backend-wiring.md`,
`state-persona.md`) against each other and spot-checked the code they cite
(`operator_quiz.py:14-17`, `conversations.py:46-52`, `system_head_builder.py:1055-1068`,
`settings-full.js:277/300`, `workspace.js:445`, `personalities/morrigan.json:106-111`, and the
`ui/` grep for `/memory/about`, `/world`, `/decisions`, `/mood`, `/goals`). Every code claim
below was verified in-tree; nothing is taken on faith from the upstream reports.

---

## The one-paragraph story

Layla's problem is **not** that things aren't built. The backend is *over*-built: 10+ memory
stores, ~18 fully-mounted intelligence-tier routers, a rich six-aspect persona system, a
maturity engine, a command palette wired to ~40 commands. The problem is that the **last mile
— the layer that makes the product *feel* like the vision — is missing or wired to the wrong
thing.** Three failures compound: (1) the **FRAME antihero vector is a fiction** — the code
ships a generic 6-stat competency profiler (`technical/creative/analytical/social/patience/
ambition`), not the North Star's `F/E/W/D/I/N/S`, so EDGE/NERVE/IRON/SIGNAL — the levers that
were supposed to keep the voice blunt and pushback-heavy on *every* turn — literally do not
exist, leaving a global "plain, warm, direct" default unopposed; (2) the **signature features
are invisible** — mood, goals, world-state, decision memory, timeline, learned skills,
cross-project reasoning, the "about you" memory surface, conversation branching, and ~14 other
panels are backend-complete but have zero UI door (or are ⌘K-palette-only with no discoverable
affordance); and (3) the **companion polish that sells the fantasy is unbuilt** — conversation
titles are a 40-char truncation of message #1, growth's voice-evolution ladder is dead on a
phase/key name mismatch, and two shipped panels are outright broken by one-line endpoint
typos. The headline divergence is therefore a *flattening + burial* story: the edgy,
memory-rich, growing companion exists in code and JSON, but the running product presents as a
generic warm chatbot with a firehose sidebar and a frozen chat title.

---

## HEADLINE divergences (read these first)

### H1 — The FRAME antihero vector does not exist (persona flattening, mechanism-level)

The North Star specifies a 7-stat behavioral vector — **F**RAME, **E**DGE, **W**IRE, **D**RIVE,
**I**RON, **N**ERVE, **S**IGNAL — "injected into every system prompt as behavioral modifiers,"
pre-calibrated to `{EDGE:8, NERVE:9, SIGNAL:3, IRON:3, …}` for the operator. The code
(`operator_quiz.py:17`, verified) implements a *different* 6-stat vector:
`("technical", "creative", "analytical", "social", "patience", "ambition")`. There is **no
EDGE** (→ no "blunt, no corporate softening"), **no NERVE** (→ no "argues when she's right"),
**no IRON** (→ no logic-first-over-emotional-ack), and SIGNAL is only weakly proxied by
`patience`, which defaults neutral (5) and fires nothing. The injection plumbing is fully live
(`system_head_builder.py:1055-1068`, verified) — it just carries the wrong cargo every turn.
Non-negotiables #2 ("FRAME calibration overrides everything") and #6 ("Pushback is a feature,
NERVE=9") have **no code behind them**. This is the single mechanism by which the antihero
voice got flattened toward corporate warmth, and both persona audits independently converged on
it as finding F1/#1.

### H2 — "warm/plain" is the unopposed global tone default

With the EDGE/NERVE layer dead (H1), the two always-on tone signals that survive both hard-code
**warm**: `system_identity.txt:19` ("plain, warm, direct") and the output-discipline closer
("a short or casual message gets a short, **warm** reply" — the *last* thing the model reads
each turn). Individually defensible (they kill fantasy-narrator RP and right-size greetings),
but with no EDGE counterweight they *are* the effective global voice. The aspect JSONs stay
edgy and are injected verbatim (`system_head_builder.py:551-553`) — but nothing keeps EDGE/NERVE
high on default turns or multiplies the aspect edge. Design intended `aspect voice × FRAME
calibration`; only the first factor ships.

### H3 — The intelligence-tier signature features have no UI door

~18 mounted, functional routers have zero UI surface; 12 are HEADLINE vision features:
`world_state` (BL-241), `decisions` (BL-235), `timeline` (BL-234), `learned_skills` (BL-238),
`cross_project` (BL-232), `goals` (BL-240), `mood` (BL-190), `feedback` (BL-242), `explain`
(BL-237), `operating_manual` (BL-236), `automation` (BL-233), `vision` (BL-230). Verified: the
only `/timeline` reference in `workspace.js` is a docstring, not a call; no component references
`/world`, `/decisions`, `/mood`, or `/goals`. These are the *flagship differentiators* — a
companion with mood, goals, a world model, decision memory, an episode timeline — and a user
running the app today cannot see or drive a single one.

### H4 — "What does Layla remember about me?" has no page

The store most resembling Claude/ChatGPT "memories about you" (durable `user_identity` facts +
relationship memories + timeline + goals) is fully built with a clean read endpoint
`GET /memory/about` and a `DELETE /memory/identity/{key}` forget path — and **no page calls
either** (verified: `grep memory/about ui/` → zero hits). The one coherent memory surface (the
Memory→Browse tab) shows *only* the `learnings` table. This is the highest-leverage,
lowest-cost memory fix: backend done, UI missing.

### H5 — Conversation titles are first-message truncation, not synthesized

`_auto_name_conversation` (`conversations.py:46-52`, verified) truncates the first user message
to 40 chars + "…". There is no LLM title synthesis anywhere. Worse, the title is frozen at
turn 1 (`count==0` guard) and an empty first message (image-only turn) sticks the row at
"New chat" forever with no retitle. The rail row reads as "first-message-text + raw timestamp"
— exactly the timestamp-y naming the operator dislikes and the "earned-title garbage" the
memory index flagged.

---

## The two nav failures (UX-parity)

### H6 — Duplicated navigation + triple Settings; ~24 panels are ⌘K-only

The app has *two* visible nav systems (left `sidebar-nav` and right `rcp-tabs`) exposing the
same ~9 surfaces, with **Settings reachable 3 ways**. A *third* nav — the ⌘K palette — is the
**only** route to ~24 feature panels (missions, journal, debate, codex, kb, plans, verify,
tutor, macros, marketplace, improvements, tools-history, sync, agent-tasks, custom-aspect,
system-diagnostics, self-test, setup-profiles, …). And the palette has **no discoverable
affordance**: no button, no hint; the only two Ctrl+K hints in the whole UI both say "Clear
input" — the *opposite* binding, which is itself double-bound and shadowed. A mouse-only user
can never reach two dozen features.

### H7 — Aspect differentiation is real but invisible

Aspects are ~60% behaviorally distinct (distinct prompt/voice, reasoning depth, length bias,
step cap, refusal authority, tool bias, aspect-scoped memory — all injected live) but the
switcher surfaces none of it. Intent (U9a) is a compact "why switch to me" card per aspect
(domain, length, refusal stance, tool bias, voice). The character *exists*; it just doesn't
show.

---

## Two broken flows (cheap, high-value)

### H8 — Relationship codex settings panel is dead (404)

`settings-full.js:277,300` (verified) call `GET/PUT /codex/user`; the real route is
`/codex/relationship`. The endpoint was renamed and the UI wasn't. A shipped, visible panel
shows `Error` on load and every Save 404s. One-line fix.

### H9 — Workspace Elasticsearch search is dead (404)

`workspace.js:445` (verified) calls `/elasticsearch/search`; the real route is
`/memory/elasticsearch/search` (the `/memory` prefix was dropped). One-line fix.

---

## Structural memory + growth gaps

### H10 — Voice-evolution ladder is dead at runtime (phase/key mismatch)

`personalities/morrigan.json:106-111` (verified) keys `voice_evolution` as
`nascent/apprentice/adept/veteran/transcendent`, but the maturity engine emits phases
`awakening/attunement/resonance/sovereignty/transcendence`. The keys never match (only
`transcend*` loosely aligns), so the per-phase voice recalibration — the mechanism that makes
growth *audible* — never injects. Growth is tracked numerically but never changes how she
sounds.

### H11 — Relationship/timeline/episode stores only fill on context overflow

`add_relationship_memory` / `add_timeline_event` / episode writes happen *only* inside
`summarize_history` (context-overflow path). Short-to-medium conversations never trigger it, so
on a typical box these stores stay empty — meaning even if H4's "about you" page shipped, it'd
render almost nothing. The felt-continuity backbone has no routine writer.

### H12 — No deterministic user-fact extractor

Durable identity (`user_identity`) is written *only* when the model chooses to call
`update_user_identity_tool`. There's no high-precision post-turn extractor for
name/timezone/pronouns/tooling, so facts land unreliably — unlike the Claude/ChatGPT memory
experience the vision points at.

---

## Onboarding / privacy

### H13 — Onboarding can silently enable remote access

For a sovereignty product this is the sharpest violation: completing the wizard auto-`POST`ed
`/setup/apply` and flipped `remote_enabled:true`. Intent (W1/U7) is explicit, off-by-default,
clearly-explained opt-in. Default first run must leave `remote_enabled:false`.

---

## Design-system flattening

### H14 — Monospace-everywhere body type vs. humanist-sans work canvas

The shipped spec is "mono everywhere" (JetBrains Mono); the governing U1 remediation overrides
that to a font-role trio (`--font-ui` humanist sans for body, `--font-mono` for code only,
`--font-display` Cinzel for wordmark/aspect identity only). U1 is called the single biggest
"make it feel premium" lever, and it's unbuilt.

---

*(Full itemized gap schema — 22 gaps with intent/current/fix/severity/effort — returned
separately as the structured GAP_SCHEMA.)*
