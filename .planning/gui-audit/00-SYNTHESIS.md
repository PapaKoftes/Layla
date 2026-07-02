# Layla GUI — Deep Audit Synthesis (2026-07-03)

Consolidates the six evidence-based traces in this folder (`01`–`06`). Every claim
below is backed by a `file:line` citation in the source doc named in brackets.

## The one-sentence verdict

**Layla's backend is a genuinely rich, mostly-working agent platform; the GUI is a
thin, drifted, partly-broken skin that hides most of it and exposes controls that
do nothing.** The gap between *what Layla can do* and *what you can reach and trust
in the interface* is the central problem — not the paint. My earlier feature-map
described that paint and a proposed IA that **isn't built**; it never checked whether
the controls work. Most don't.

---

## A. Dead / broken controls — the UI lies to the user (fix-or-cut FIRST)

These are visible, clickable, and do nothing (or the wrong thing). Each erodes trust.

| Control | Reality | Src |
|---|---|---|
| **"Plan first"** toggle | dead — `send()` never reads it (server supports `plan_mode`) | 01 |
| **"Think harder" / reasoning-effort** | dead — never read (server supports `reasoning_effort`) | 01 |
| **Pipeline-clarify** panel | broken — server returns questions, UI never shows them | 01 |
| **Context-usage bar** | permanent `Ctx: —` placeholder; SSE `ctx_pct` ignored | 01 |
| **Prompt-history ↑** | 404 — calls `/conversations/prompt_history` (nonexistent) | 01 |
| **Rail "Load more"** | broken — server ignores `offset`, capped ~30 chats | 01 |
| **Compact** | ignores `conversation_id` — compacts a global buffer | 01 |
| **Working-notes draft** | never clears — silently leaks into every later turn | 01 |
| **Voice sliders** (pitch/warmth/formality/speed) | dead — `/voice/speak` ignores them | 02, 05 |
| **TTS volume slider** | no-op — no GainNode in the audio path | 05 |
| **Checkpoints panel** | 404 — `/file_checkpoints` vs real `/memory/file_checkpoints` | 03 |
| **`min_adjusted_confidence`** slider | no-op — no code reads the key | 03 |
| **Growth velocity + watcher** widgets | always empty — dict-vs-array / field-name mismatch | 03 |
| **Update-check** | 404 — `/version/check_update` vs real `/update/check` | 06 |
| **"Save appearance & lite"** | saves nothing — wrong DOM ids + wrong endpoint | 06 |
| **Potato preset** button | 404 — POSTs `/settings/preset/potato` (path) not body | 06 |
| **Delete study plan** | no UI control though `DELETE` endpoint exists | 05 |

## B. Backend-without-UI — built, powerful, unreachable (surface honestly or cut)

The most valuable capabilities are invisible. This is where the product's soul is hiding.

| Capability | State | Src |
|---|---|---|
| **Verify / "it learns" loop** (`/verify/next`+`/answer`) | **the flagship mechanic — zero UI**; sets confidence=1.0, awards XP, writes wiki | 03 |
| **Autonomous mode** | real bounded read-only loop, but **unreachable**: defaults false, force-reset at startup, **not in `EDITABLE_SCHEMA`** | 04 |
| **Missions** board/horizon/pause/resume | whole mission lifecycle product, **zero UI callers** | 04 |
| **Spawn agents + blackboard** | implemented + callable, no GUI path | 05 |
| **Remote / tunnel / tailscale / Syncthing / phone-URL** | full backends, **no reachable GUI** — can't enable remote access except by editing config (itself remote-blocked) | 06 |
| **Image → vision** | server accepts images, no composer attach path | 01 |
| **Diagnostics**: `/metrics`, `/audit`, `/tools/history`, `/health/trace\|deps`, `/usage`, `cot_stats`, `session/grants` | rich + live, little/no UI | 04, 06 |

## C. UI-without-backend / inert

- Voice sliders (B above), **color picker** (partial — chat rail uses a separate hardcoded palette), 02.
- Inert settings keys: `ui_theme_preset` (no loader), `syncthing_*` (not even in schema), `ui_font_size`/`ui_animation_level` (not schema keys). 06.

## D. Architectural duplication — two of everything (collapse to one source of truth)

| Concept | Two implementations | Src |
|---|---|---|
| Aspect definitions | `personalities/*.json` (runtime) **vs** `character_creator.ASPECT_DEFAULTS` (SQLite) — they disagree on facts | 02 |
| Onboarding | setup.js 3-step **tour** **vs** onboarding.js **interview** — share the same `#onboarding-overlay` id | startup |
| "Governor" | `performance_mode` (auto/low/mid/high) **vs** idle `ResourceGovernor` (whisper/breathe/sprint) | 04 |
| Deliberation | debate engine (solo/debate/council/tribunal) **vs** single-model "inner voices" | 02 |
| Skills | Python `SKILLS` dict (planner hint) **vs** markdown `SKILL.md` files (UI panel) | 05 |
| Plans | durable SQLite `/plans/*` (UI) **vs** file `/plan/*` (no UI) | 04 |

## E. Wedge betrayals — the strategy is actively undermined by the GUI

1. **Potato preset disables semantic memory** (`use_chroma=False`) — the low-end machine
   that most needs the compiler-free SQLite+NumPy fallback gets keyword-only FTS. The wedge
   is "private + low-end + it remembers"; the preset breaks the third. [03]
2. **The "it learns about you" promise is invisible** — the verify loop has no UI. [03]
3. **Agentic power is built but unreachable** — autonomous mode + missions + agents. [04]

## F. What genuinely works — PRESERVE these (the redesign must not break them)

Send pipeline (SSE+JSON, persistence, tool-trace, streaming stats) [01] · aspects at
inference (prompt injection, reasoning depth, max-steps, refusal block, retrieval boost)
[02] · deliberation engine, all modes [02] · personality sliders → prompt hints [02] ·
memory retrieval via SQLite+NumPy fallback [03] · sandbox enforcement, fails closed [05] ·
STT (faster-whisper) + TTS (kokoro) [05] · approvals (TTL, grant-session/pattern) [04] ·
XP wiring (11 real paths) [03] · conversations CRUD, memory browse/edit, global search,
knowledge ingest, bundle export/import, relationship codex, Obsidian, mDNS pairing [01,03,06].

---

## G. Redesign principles (derived from the evidence, not taste)

1. **Truth in controls.** Every control maps to a working backend path, or it is removed.
   No dead toggles. (Resolves §A.)
2. **Surface the soul.** The verify/learn loop, missions, and agents are the product's
   differentiation — surface them properly or cut them honestly, no dormant middle. Start
   with the verify loop. (Resolves §B.)
3. **One of each.** Collapse every §D duplication to a single source of truth.
4. **Honor the wedge.** Potato keeps semantic memory (the fallback exists *for* it). Private +
   low-end + it-remembers must all hold. (Resolves §E.)
5. **Legible safety.** Unify bypass / approvals / safe-mode / governor into one honest surface.
6. **Then, and only then, the visual IA.** The rail + conversations + chat + slide-in panels +
   grouped settings — but every element now verified-working.

## H. Implementation order — lowest risk → highest (so trust is rebuilt before repaint)

1. **Kill-or-wire the dead controls** (§A) — mostly mechanical; the single biggest trust win.
2. **Fix the broken endpoints** — checkpoints/update-check/potato/prompt-history/appearance 404s.
3. **Fix silent-correctness bugs** — compact `conversation_id`, working-notes clear, **potato `use_chroma`**.
4. **Surface the flagship** backend-without-UI — verify loop first, then missions/agents/autonomous toggle.
5. **Collapse the duplications** (§D) — one aspect model, one onboarding, one governor.
6. **Visual + IA redesign** (G2–G6) on a foundation where everything is real.

Steps 1–3 are safe, high-trust, and independently shippable. The visual redesign rides on top —
it should be the *last* layer, not the first, because a beautiful skin over dead controls is the
exact problem we started with.

---

*Backing detail (full traces, per-feature how-to-use + options + status tables + ranked UX
problems): `01-chat-loop.md`, `02-aspects-personality.md`, `03-memory-knowledge-growth.md`,
`04-models-research-autonomy.md`, `05-workspace-skills-voice-artifacts.md`,
`06-settings-connectivity-diagnostics.md`.*
