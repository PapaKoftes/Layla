# Delta: UX Parity with Claude/ChatGPT — Adopt the Patterns, Keep the Identity

**Frame:** The user wants Layla to adopt the *general strokes* of Claude/ChatGPT for
**features + usability** — a real Memories tab with sane save logic, synthesized
conversation titles, and table-stakes chat management (grouping, rename, delete,
search, pin) — while **fully preserving** what makes Layla Layla: the 6 aspects,
FRAME, the blunt antihero voice, the Warframe aesthetic, local-first, and
growth/maturity.

This document maps each Claude/ChatGPT pattern to **(a)** what Layla has today,
**(b)** the specific gap, **(c)** a concrete adoption plan that preserves uniqueness,
and — critically — **(d)** where blindly copying Claude/ChatGPT would *harm* Layla's
identity and how to reconcile.

Source of truth: `state-memory.md`, `state-chat.md`, `state-ui.md` (this audit set).

---

## Guiding principle: parity is about *legibility*, not *sameness*

Claude/ChatGPT's usability wins come from three things Layla lacks, none of which
require diluting its personality:

1. **One coherent surface per mental model** ("what do you remember about me?" →
   one page). Layla has the data in 10+ stores but no page that answers the question.
2. **Automatic, low-friction capture with a visible "memory updated" receipt.**
   Layla captures a lot but silently, into the wrong-shaped store, and shows no receipt.
3. **Names and grouping that let you *find* a past chat.** Layla names chats with a
   40-char prefix of message #1 and lists them as a flat timestamped wall.

Everything below adopts those three affordances **through Layla's own vocabulary** —
"aspects," "FRAME," "durable facts," Warframe sigils — rather than importing a
generic Claude/ChatGPT chrome. That distinction is the whole point of this delta.

---

## Part A — MEMORIES tab (the flagship gap)

### Claude/ChatGPT pattern
A single **Memory** surface listing salient facts the assistant has saved *about you*
(name, role, preferences, ongoing projects), auto-extracted from conversation, with:
view / edit / delete per item, dedup, and a transient **"Memory updated"** toast +
an inline "✎ Manage memories" affordance the moment a fact is saved.

### What Layla has today
- **Backend is over-built, not under-built.** `GET /memory/about` already aggregates
  identity facts + relationship memories + timeline + active goals + counts
  (`routers/memory.py:64`), and `DELETE /memory/identity/{key}` already forgets one
  durable fact (`routers/memory.py:120`). **Neither is called by any UI** — the whole
  "about you" endpoint is orphaned (`state-memory.md §4`, "single biggest gap").
- The one polished memory surface — **Library → Memory → Browse** (`memory.js`) —
  shows *only* the `learnings` table (edit/delete/confidence/tags), not identity,
  relationships, timeline, or goals. It even has humane kind-labels already
  ("You told me", "Preference", "What worked" — `memory.js:67`).
- **Five uncoordinated save paths** exist (`state-memory.md §2`): inline `remember:`
  command, background LLM insight-extractor, model-chosen `update_user_identity_tool`,
  tool-success patterns, and context-overflow summarization. Only the model *choosing*
  to call a tool ever writes a durable identity fact — there is **no deterministic
  user-fact extractor**.
- Real **consolidation machinery exists** (exact-hash dedup, Jaccard + embedding
  near-dup merge, contradiction flagging via `consistency_guard`, confidence decay)
  but it runs scheduler-side on `learnings` only and is invisible/uncontrollable to
  the user.

### The specific gaps
1. **No "About you" / Memories surface** — the question "what does Layla remember
   about me?" has no page, despite the endpoint existing.
2. **No deterministic identity capture** — durable facts land only if the model
   volunteers a tool call, so the Memories page would often be near-empty.
3. **No "memory updated" receipt** — saves are silent; the user never learns the
   memory exists or that they can manage it.
4. **Relationship/timeline stores only fill on context overflow** — on a typical
   local box they stay empty, so even a wired page shows little.
5. **Consolidation/conflict queue is invisible** — `GET /memory/conflicts` +
   `POST /memory/conflicts/{id}/resolve` exist but aren't surfaced.

### Adoption plan (preserves uniqueness)
- **Build a "What Layla Knows" panel** as a new sub-tab under the existing Library →
  Memory tab (alongside Browse/Search/Checkpoints), rendering `GET /memory/about`.
  Group into sections that use *Layla's* vocabulary, not ChatGPT's flat list:
  - **Durable facts** (identity KV) — per-item ✎ edit / ✕ forget wired to the
    existing `DELETE /memory/identity/{key}`. (Edit = forget + re-set.)
  - **People & bonds** (relationship memories) — read + forget.
  - **Timeline** (life events / milestones / goals / blockers) as a vertical
    Warframe-styled thread.
  - **Goals** with progress.
  Reuse `memory.js`'s existing kind-label + relative-time helpers for visual
  consistency; do **not** import a new design language.
- **Add a deterministic, high-precision post-turn identity extractor** modeled on the
  preference/correction heuristics already in `outcome_writer._auto_extract_learnings`
  (`state-memory.md §2b`): match name / timezone / pronouns / editor / project-roots
  and write them to `user_identity` (via the same path `update_user_identity_tool`
  uses), gated behind a **confirmation** so nothing lands silently.
- **Add a "memory updated" receipt in Layla's voice.** When a durable fact or salient
  learning is saved, emit it in the turn's done-frame and render a small, dismissible
  chip under the reply: e.g. *"Filed that under what I know about you. ✎ Manage"* —
  linking straight to the new panel. The blunt-antihero tone stays (Layla *notes*
  things, she doesn't gush "Got it! 😊"). This is the single highest-ROI usability win.
- **Fill relationship/timeline on meaningful turns, not only on overflow** — duplicate
  the `add_relationship_memory` / `add_timeline_event` writes out of `summarize_history`
  onto a lightweight per-turn heuristic so the panel isn't empty (`state-memory.md §rec3`).
- **Surface the conflict/merge queue** inside the same panel as a "Review" strip
  ("2 things I might be remembering wrong →"), wired to the existing `/memory/conflicts`
  endpoints — this is Layla's honest, self-auditing version of Claude's dedup.

### ⚠️ Where copying Claude/ChatGPT would HARM Layla — and the reconciliation
- **Do NOT collapse the 6-aspect memory model into one flat "memory."** Layla has
  `aspect_memories` (per-personality). ChatGPT has a single assistant, so its memory is
  monolithic. Blindly flattening would erase the aspects' distinct relationships with
  the user. **Reconcile:** the Memories panel shows *shared* durable facts globally, but
  keep a per-aspect "how {aspect} sees you" strip so Morrigan and Nyx can hold different
  read-outs. Aspect identity is a feature, not noise to normalize away.
- **Do NOT hide the machinery to look "clean."** ChatGPT deliberately conceals its
  consolidation. Layla's brand is *transparent, self-improving intelligence* (growth /
  maturity / verification queue). **Reconcile:** surface the conflict/decay/merge
  activity as a first-class, Layla-voiced "I reconciled these" feed rather than hiding
  it — turn the mechanism into a personality beat.
- **Do NOT adopt ChatGPT's over-eager auto-save.** ChatGPT saves aggressively and can
  feel creepy. Layla is **local-first** and blunt — her differentiator is *trustworthy*
  memory. **Reconcile:** default the new deterministic extractor to **confirm-before-file**
  for durable identity facts (opt-in silent mode in Settings for power users), and make
  every saved fact one-click forgettable. "Local-first + you own the memory" is a selling
  point ChatGPT can't match; lean into it.

---

## Part B — SYNTHESIZED conversation titles

### Claude/ChatGPT pattern
After the first exchange, the assistant **generates a short semantic title** (~4-6
words) summarizing the conversation, and the sidebar updates in place.

### What Layla has today
- The **only** title logic is `_auto_name_conversation` (`conversations.py:46`): the
  first user message truncated to 40 chars. **No LLM synthesis exists anywhere**
  (`state-chat.md §2`).
- The title is **frozen at turn 1** and only set if it was empty at insert time
  (guard `count==0`); an empty/image-only first message → permanent "New chat"
  (BREAK A).
- The rail row reads as "first-message-text + raw timestamp" (`conversations.js:274-277`),
  which is exactly the timestamp-y feel the user dislikes.
- `earned_title` is a **red herring** — it's the aspect honorific system, unrelated to
  chat naming (`state-chat.md §2`).
- The wiring to *display* a title is intact: `rename_conversation` works
  (`conversations.py:92`) and the done-frame already calls `refreshConversationList`
  (`app.js:607`).

### The specific gaps
1. **No title synthesizer** — the requested behavior is entirely unbuilt.
2. **Frozen-at-turn-1** — no retitle ever, so even a good title can't improve, and an
   empty first message strands "New chat" forever.
3. Dropped done-frames leave the title (and the "loading" bubble) permanently stale,
   with no poll fallback (BREAK B/D).

### Adoption plan (preserves uniqueness)
- **Add `services/agent/title_synthesizer.py`** (or extend `response_builder.py`,
  which already has `synthesize_direct_answer`). Generate a ~4-6-word title from the
  first user+assistant exchange, run it through the **same reply-cleaning path** that
  strips aspect/earned-title markers (`test_earned_title_leak.py`) so persona sigils
  don't leak into the sidebar.
- **Trigger it server-side once per conversation** right after the first assistant
  message is persisted, in each `/agent` done-path, calling the already-working
  `rename_conversation`. Guard so it runs exactly once (`state-chat.md §rec`).
- **Emit the new title in the done-frame** so the rail updates without a full re-fetch,
  and **fix the freeze**: allow a one-time retitle when the current title is empty or
  still the raw first-message prefix.
- **Give the synthesizer Layla's voice, lightly.** Titles should be crisp and literal
  (findability first) but may carry a faint edge where natural — this is a place to be
  *subtle*, not to inject aspect flavor that hurts scanability.

### ⚠️ Where copying Claude/ChatGPT would HARM Layla — and the reconciliation
- **Do NOT let title synthesis fire a heavy extra LLM call on a potato-tier box.**
  Layla's local CPU floor is ~14s first-token (per MEMORY / auto-tune notes). A
  synchronous title call would add latency to every first turn. **Reconcile:** run
  synthesis **async in the background after the done-frame** (rail already refreshes on
  the next event), and on the lowest hardware tiers fall back to a smarter
  *extractive* title (keyword/noun-phrase pick from the first exchange) instead of a
  generative call. Local-first means titles must never tax the turn.
- **Do NOT strip Layla's aspect attribution from the rail to mimic ChatGPT's flat
  list.** The per-conversation aspect dot (`conv-asp-dot`) is identity signal.
  **Reconcile:** keep the aspect sigil/dot on each row; the synthesized title replaces
  only the *text*, not the aspect coloring.

---

## Part C — CHAT MANAGEMENT (grouping, rename, delete, search, pin)

### Claude/ChatGPT pattern
Sidebar with **date-bucketed grouping** (Today / Yesterday / Previous 7 days / older),
rename, delete, full-text search, pin, and reliable "load more" history.

### What Layla has today (`state-chat.md §4`)
| Feature | Status |
|---|---|
| Rename | ✅ Works (`✎` + `POST /rename`) |
| Delete | ✅ Works (cascades messages) |
| Search | ⚠️ Works but uses `LIKE`, not the existing FTS5 mirror; supports `tag:`/`after:`/`before:` mini-syntax |
| Pin | ⚠️ **Client-only** (`localStorage`), no server `pinned` column — lost across devices/cache-clear |
| Tags | ✅ Works |
| Export | ✅ Works (JSON blob) |
| Fork / branch / compare | ✅ **Backend only**, no rail UI |
| **Date grouping** | ❌ **MISSING** — flat list, raw `updated_at` slice per row (`conversations.js:275`) |
| **Load more** | ❌ **BROKEN** — client sends `offset` the server ignores; every click re-fetches page 1 and **appends duplicates**; history effectively capped at 30 (BREAK E) |

Reload also has real breaks: silent-swallow on failure (BREAK F), all non-user roles
flattened to 'layla' losing the rich turn UI (BREAK G), and active-row scroll reading a
divergent state store (BREAK H).

### The specific gaps
1. **No date bucketing** — the single most-visible parity gap in the sidebar.
2. **Pagination is broken** — server never honors `offset`; history capped + duplicated.
3. **Pin is not durable** — device-local only.
4. **Search under-uses the FTS5 index** it already maintains.
5. **Reload loses rich turn UI and fails silently.**

### Adoption plan (preserves uniqueness)
- **Add Today / Yesterday / Previous 7 days / Previous 30 days / Older grouping** in
  `_renderSessionList` by bucketing on `updated_at` before render, with Warframe-styled
  section dividers (thin sigil rule, not a generic gray label). Keep the aspect dot,
  pin glyph (`⟡`), project chip, and tag chips already on each row.
- **Fix pagination end-to-end** (BREAK E): add `offset` to `list_conversations` /
  `list_conversations_api` / `search` and to the DB `LIMIT ? OFFSET ?`, so "Load more"
  truly pages instead of duplicating.
- **Persist pins server-side**: add a `pinned` column to `conversations` +
  `POST /conversations/{id}/pin`, and have the rail read server pins (fall back to
  localStorage for migration). Cross-device pin is a real durability win.
- **Switch search to the existing FTS5 mirror** (`conversation_messages_fts`) for the
  free-text term while keeping the `tag:`/`after:`/`before:` mini-syntax — faster,
  same UX.
- **Fix reload fidelity** (BREAK F/G/H): surface a toast on load failure instead of a
  silent `catch {}`, persist enough role/segment metadata to reconstruct at least
  aspect attribution and tool/thinking segments on reload, and unify the
  `currentConversationId` vs `appState` scroll target.
- **Surface fork/branch/compare** (currently backend-only) as a small "branches"
  affordance on the row context menu — this is a *Layla-unique* capability (conversation
  branching) that Claude/ChatGPT don't expose; leaning into it is differentiation, not
  parity-chasing.

### ⚠️ Where copying Claude/ChatGPT would HARM Layla — and the reconciliation
- **Do NOT strip the aspect/project/tag metadata off rows to match ChatGPT's minimal
  list.** That metadata (which aspect answered, project binding, tags) is Layla's
  organizational edge. **Reconcile:** date-group *and* keep the per-row Warframe chrome;
  grouping is additive, not a replacement for identity signal.
- **Do NOT hide branching to look like a linear-history clone.** Conversation
  fork/compare is a capability Claude/ChatGPT lack. **Reconcile:** surface it as a
  distinctly-Layla power feature rather than dropping it for visual conformity.

---

## Part D — OTHER TABLE-STAKES USABILITY

### D1. Command-palette features have no visible entry point
**Pattern (Claude/ChatGPT):** a discoverable "⌘K" spotlight *and* visible nav for
core features. **Layla today** (`state-ui.md`): ~24 feature panels (Journal, KB,
Deliberate, Codex, Plans, Missions, Verify, Macros, Tool history, Diagnostics…) are
reachable **only** via ⌘K, which itself has **no button, no hint** — and the only two
Ctrl+K hints in the UI say "Clear input," the *opposite* binding (`state-ui.md §1-3`).
**Gap:** mouse-only users can never reach 2/3 of the app; the palette is undiscoverable
and mis-documented; Ctrl+K is double-bound.
**Adoption (preserve uniqueness):** add a visible **spotlight affordance** (a ⌘K glyph
in the header, styled as a Warframe console prompt) that opens the *existing* palette;
fix the Ctrl+K double-bind and correct the shortcut sheet; promote the highest-value
palette panels (Memories/About-you, Journal, KB) into the visible right-panel nav so
the flagship memory work in Part A is actually reachable by clicking. **Harm to avoid:**
don't drown the clean chat-first layout in 24 nav buttons — group the long tail behind
one discoverable palette, just make the palette itself *visible* and label a curated
few in nav.

### D2. Search is fragmented across three boxes
Global header search (`search.js`), rail search, and Memory→Search are separate.
**Adoption:** keep them, but ensure the global search covers conversations + learnings
+ the new "about you" facts so one query answers "where did I mention X?" — Claude's
unified search value, in Layla's existing header search.

### D3. Feature duplication dilutes navigation
`german.js` and `tutor.js` are redundant palette entries over the same `/language/*`
endpoints; `verify.js` is surfaced twice (`state-ui.md §4-5`). **Adoption:** consolidate
to reduce the 40+ palette commands — pure cleanup, no identity cost.

### ⚠️ Cross-cutting harm to avoid
- **Do NOT sand off the Warframe aesthetic, aspect sigils, or blunt voice to look like
  Claude/ChatGPT.** The user explicitly wants uniqueness kept. Every new surface
  (Memories panel, date dividers, title chips, "memory updated" receipt) must be built
  in Layla's existing design tokens and voice. Parity is in the *information
  architecture and reliability*, never in the skin or the personality.

---

## Priority ranking (highest ROI first)
1. **Memories/"About you" panel** — backend done, UI missing; answers the core question. (B-gap, high)
2. **Synthesized titles (async + extractive fallback)** — the user named this explicitly. (high)
3. **"Memory updated" receipt** — makes memory legible/trustworthy; cheap. (high)
4. **Date grouping in the rail** — most-visible sidebar parity gap. (medium)
5. **Fix broken pagination + durable server-side pins.** (medium)
6. **Deterministic confirm-to-file identity extractor.** (medium)
7. **Visible palette affordance + fix Ctrl+K mis-binding; promote Memories to nav.** (medium)
8. **FTS5 search, reload fidelity, palette de-dup.** (low-medium cleanup)
