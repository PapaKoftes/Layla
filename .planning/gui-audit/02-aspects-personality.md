# GUI Deep Audit 02 — Aspects / Personalities + Character Lab + Deliberation

**Cluster owner:** aspects, Character Lab, deliberation modes, titles/tutorial.
**Method:** read-only trace GUI → handler → API → router → service → prompt/model → storage.
**Date:** 2026-07-02. **Repo:** C:\Work\Programming\Layla.

> Headline answer to the key question (do Character Lab sliders affect behavior?):
> **Personality sliders = FUNCTIONAL** (they inject prompt hints at inference).
> **Voice sliders = COSMETIC/DEAD** (TTS ignores them; only a hardcoded per-aspect speed is used).
> **Color picker = COSMETIC beyond the Lab** (persists, but the live chat rail uses a *different* hardcoded palette).

---

## 0. The two parallel aspect systems (critical architecture note)

There are **TWO independent aspect data models** in the codebase, and they do not share storage:

1. **The runtime aspect system** — `personalities/*.json` (repo root, NOT `agent/`), loaded by
   `orchestrator._load_aspects()` (`agent/orchestrator.py:74-127`). This is the RICH, authoritative
   definition used at inference: `role`, `voice`, `traits`, `systemPromptAddition`,
   `systemPromptAdditionNsfw`, `nsfw_triggers`, `expertise_domains`, `decision_bias`, `behavior`
   (reasoning_depth_bias / response_length_bias / max_steps_bias / refusal_topics), `triggers`,
   `failure_mode`, `voice_evolution`. **This is what actually changes Layla's behavior.**

2. **The Character Lab system** — `agent/services/personality/character_creator.py`
   `ASPECT_DEFAULTS` (`:33-160`), persisted to SQLite `user_identity` under keys
   `char_<aspect>_<field>`. This holds the 6 personality sliders (1–10), 4 voice sliders,
   colors, titles, lore text. It is **mostly a separate, parallel definition** with only ONE
   live bridge into inference (`personality_to_prompt_hints`, see §Character-Lab).

The two even disagree on facts: e.g. Lilith's title is "The Sovereign" in the Character Lab
(`character_creator.py:141`) but "The First and the Core" in the runtime JSON
(`personalities/lilith.json:4`). Morrigan's slider bluntness is 8 in the Lab but her runtime
`behavior.response_length_bias` is "concise" in the JSON — related but independently authored.

This split is the root cause of most UX problems in this cluster (see TOP UX PROBLEMS).

---

## 1. The SIX aspects — what each is FOR and what really differs

**Definitions live in `personalities/*.json`** (morrigan, nyx, echo, eris, cassandra, lilith),
loaded and cached (60s TTL) by `orchestrator._load_aspects()`. On load, `_build_style_card()`
(`orchestrator.py:53-71`) folds `traits`/`speech_patterns`/`do_not_do`/`archetype`/`tropes` into
the `systemPromptAddition`, and a maturity-phase-aware `voice_evolution` line is appended
(`orchestrator.py:111-121`).

| Aspect | Role (from JSON) | Voice register | Runtime `behavior` (JSON) | Decision bias | NSFW | Refuses? |
|---|---|---|---|---|---|---|
| **Morrigan** ⚔ | "Implementation Authority. Code, architecture, debugging, execution. The aspect that ships." | Blunt, fast, no flattery, short cutting sentences | depth=deep, length=concise, max_steps=8 | efficient, risk_averse | capable | can (not by default) |
| **Nyx** ✦ | Research, depth, synthesis (`role`/domains: analysis, investigation) | Layered, precise, finds deeper pattern | (JSON not read in full, but slider verbosity=8, curiosity=9) | — | — | — |
| **Echo** ◎ | Reflection, patterns, memory, empathy/communication | Reflective, notices patterns & absence | high empathy (slider 9) | — | — | — |
| **Eris** ⚡ | Creative chaos, banter, lateral leaps, disruption | Fast, sideways, breaks the frame | high humor (slider 9) | — | — | — |
| **Cassandra** ⌖ | Unfiltered oracle — perception, anomaly, contradiction, prediction, risk | Sees it immediately, reactive | max bluntness (slider 10) | — | — | — |
| **Lilith** ⊛ | "Sovereign Will… ethics, full autonomy, absolute depth… absolute authority" | Slow, deliberate, unhurried, gentle-and-devastating | depth=light, length=medium, max_steps=5, refusal_topics=[harm,manipulation,coercion] | principled, honest | capable (has `systemPromptAdditionNsfw`) | **will_refuse=true** |

**What ACTUALLY changes when you switch aspect** (evidence, all live):
1. **System prompt** — `run_setup.py:192/214` calls `orchestrator.select_aspect(goal, force_aspect=aspect_id)`; the chosen aspect's `systemPromptAddition` (+ style card + voice evolution) is injected via `prompt_builder`/`system_head_builder`. Distinct per aspect. **WORKING.**
2. **Reasoning depth** — `run_setup.py:219` calls `aspect_behavior.apply_reasoning_depth(active_aspect, mode)`; Morrigan forces `deep`, Lilith downgrades to `light` (`aspect_behavior.py:107-143`). **WORKING.**
3. **Max autonomous tool steps** — `run_setup.py:731` calls `aspect_behavior.get_max_steps(aspect, base)`; Morrigan caps at 8, Lilith at 5 (`aspect_behavior.py:146-167`). **WORKING.**
4. **Response-length + refusal-topic instruction** — `system_head_builder.py:717-720` calls `build_behavior_block(aspect)` and appends it to the system prompt (Lilith gets the explicit "refuse harm/manipulation/coercion" line). **WORKING.**
5. **Retrieval boosting** — `llm_decision.py` uses `extract_aspect_domain_keywords(aspect)` → `semantic_recall(domain_boost_terms=…)` (`llm_decision.py:94-140, 548-552`), so an aspect's `expertise_domains` bias memory retrieval. **WORKING.**
6. **NSFW register** — `orchestrator._maybe_add_nsfw_mode()` (`:264-273`) flips `_use_nsfw_addition` when the message contains an aspect `nsfw_triggers` keyword; `prompt_builder.py:207-212` then injects `systemPromptAdditionNsfw`. Only Lilith ships this block. **WORKING (Lilith only).**
7. **Failure-mode self-awareness** — `prompt_builder.py:230-236` injects `failure_mode_expanded`. **WORKING.**
8. **TTS speed** — `voice.py:60-66` maps aspect_id → a **hardcoded** speed. **WORKING but crude** (see §Voice).
9. **Color/glow** — `aspect.js:setAspect()` sets CSS vars from a **hardcoded** `ASPECT_COLORS` (`aspect.js:14-21`). **WORKING but not sourced from data.**

**What does NOT change (defined but dormant/dead):**
- **Per-aspect model routing** (`aspect_model_overrides`) — supported by `model_router._resolve_aspect_model` / `route_model(aspect_id=…)` and fully unit-tested (`test_aspect_model_routing.py`), but the **live main-chat routing call `route_model(task)` at `llm_gateway.py:389` passes NO aspect_id**, and the config default is `{}` (`runtime_safety.py:615`). So aspects do NOT swap models in normal chat. **DORMANT / config-gated (empty by default).**
- **Per-aspect tool boost/suppress** (`ASPECT_TOOL_PREFERENCES`, `get_tool_preferences`, `aspect_behavior.py:217-251`) — referenced **only by tests**; no production call site. Cassandra's "boost read_file / suppress fetch_url", Lilith's "suppress run_shell/run_python/write_file", etc. are **never applied** to tool selection. **DEAD at runtime.**

---

## 2. Aspect switching + lock + @mention

**Rail switch** — `index.html:266-286` six `.aspect-btn` with `data-action="setAspect" data-arg="<id>"`
→ `main.js:267` (`setAspect` action) → `aspect.js:setAspect(id)` (`:63-116`).
`setAspect` updates `appState.aspect.current`, toggles button `.active`, updates the two badges,
sets CSS custom props from `ASPECT_COLORS`, shows a toast "Now talking to …", swaps the doodle
overlay + sprite, and emits `bus 'aspect:switched'`.
**IMPORTANT: rail switch is PURELY CLIENT-SIDE.** It persists nothing server-side. The chosen
aspect only reaches the backend as `payload.aspect_id` on the *next send* (`app.js:301`) →
`req.aspect_id` → `select_aspect(force_aspect=…)`. There is **no** POST that saves "current aspect"
on switch (contrast the Character Lab "Set as Main", which does POST `/character/main-aspect`).

**Lock** — lock button → `aspect.js:toggleAspectLock()` (`:118-129`). Sets module-scoped
`_aspectLocked` + `window._aspectLocked`, changes the 🔒/🔓 glyph and title. Two effects:
1. `setAspect(id)` early-returns if `_aspectLocked && !force` (`:64`) — blocks rail clicks from changing the aspect.
2. In send (`app.js:272`): `if (window._aspectLocked) msgAspect = window.currentAspect;` — this **overrides any @mention**, forcing the locked aspect. So "lock" = "pin this aspect; ignore both rail clicks and @mentions."
**Note:** the tooltip says lock "prevents auto-routing," but server-side auto-routing only happens when `aspect_id` is empty; since the UI always sends the current aspect, the practical effect is UI-level pinning of @mention/rail, not backend routing suppression. **WORKING (semantics slightly oversold).**

**@mention mid-message** — two parts:
- *Autocomplete dropdown*: `input.js` (`_mentionActive`, `_showMentionDropdown`, `_pickMention`, arrow-key nav at `:32-83`) triggered by typing `@…`.
- *Parse on send*: `app.js:258-271` — `msg.match(/^@([a-z]+)\s*/i)`; if the token matches an ASPECT id/name, `msgAspect` is set to that aspect and the `@token` is stripped from the sent message (display keeps `@name`). Only matches at **start of message** (`^@`), single token, so "reply @nyx" mid-sentence is NOT honored — only a leading `@nyx …`. Locked aspect wins over mention (`:272`). **WORKING (leading-mention only).**

---

## 3. Character Lab (`character-creator.js` + `/character` router + `character_creator.py`)

**Entry:** header `🎭 Character Lab` (`index.html:225`, `data-action="openCharacterLab …"`) →
`main.js:341` → `character-creator.js:openCharacterLab()` (`:330-337`): shows `#character-lab-overlay`,
calls `loadCharacterData()` then `renderCharacterLab()`.

**Data load** — `loadCharacterData()` (`:39-64`) `Promise.all` of `GET /character/summary`,
`/character/traits`, `/character/voice-params` → router `character.py:47/161/168` →
`character_creator.get_character_summary()` / `PERSONALITY_TRAITS` / `VOICE_PARAMS`.
`get_character_summary()` (`character_creator.py:424-463`) merges `ASPECT_DEFAULTS` with any
SQLite overrides via `load_all_profiles()` and folds in the maturity rank + available titles.

### 3a. Personality sliders (aggression, humor, verbosity, curiosity, bluntness, empathy — 1–10)
- Rendered from `/character/traits` metadata (`character_creator.py:164-171`) via `_renderSlider` (`character-creator.js:67-80`); range 1–10 step 1.
- On `input`, `_bindSliders` (`:170-187`) writes to `_dirty[aspect]["personality_<id>"] = val` (no live server call).
- **Save** → `_saveCurrentAspect()` (`:253-271`) `PATCH /character/aspects/<id>` with the dirty dict → router `character.py:77-88` → `save_aspect_customization()` (`character_creator.py:231-251`) writes each field to SQLite `char_<aspect>_<field>`.
- **DOWNSTREAM EFFECT — REAL:** `personality_to_prompt_hints(aspect_id)` (`character_creator.py:312-365`) converts slider extremes (≥8 or ≤2/≤3) into behavioral sentences (e.g. bluntness≥8 → "Be direct and unfiltered; do not soften criticism."). This IS injected into the live system prompt: `prompt_builder.py:218-229` — guarded by `cfg.get("character_creator_enabled", True)` (key absent from schema ⇒ defaults **on**) and keyed on the primary aspect id. **So moving a personality slider to an extreme genuinely changes the next reply's system prompt.** Mid-range sliders (4–7) emit no hint (by design). **FUNCTIONAL.**
- Caveat: hints are coarse (threshold-based, not proportional) and only for the *primary* aspect of the turn, not secondary/persona-focus.

### 3b. Voice sliders (pitch, speed, warmth, formality)
- Rendered from `/character/voice-params` (`character_creator.py:175-180`): pitch 0.5–1.5, speed 0.5–2.0, warmth 0–1, formality 0–1.
- Save path identical (PATCH → SQLite `char_<aspect>_voice_<id>`).
- **DOWNSTREAM EFFECT — NONE (DEAD).** The TTS endpoint `/voice/speak` (`voice.py:41-67`) does **not** read the Character Lab voice profile at all. It uses a hardcoded `_ASPECT_SPEEDS` dict (`voice.py:60-66`: morrigan 1.05, nyx 0.82, …) keyed only on `aspect_id`, and passes `speed_override` to `speak_to_bytes`. `pitch`, `warmth`, `formality`, and the operator's customized `speed` are all ignored (grep for `voice_warmth|voice_pitch|voice_formality` in `voice.py` = **0 matches**). The sliders persist and re-render, but changing them has **zero audible effect**. **COSMETIC / UI-WITHOUT-BACKEND.**

### 3c. Color picker
- `_renderAspectDetail` renders a `<input type=color data-field="color_primary">` (`character-creator.js:124-126`); `_bindColorPickers` (`:189-197`) stores to `_dirty[aspect].color_primary`; Save persists to SQLite.
- **DOWNSTREAM EFFECT — LIMITED.** The Character Lab's own detail panel uses the saved color, and `/aspects/{id}` (aspects.py) returns `color`. BUT the live chat rail color comes from a **separate hardcoded** `ASPECT_COLORS` in `aspect.js:14-21` (and the runtime JSON `color` field), NOT from the Lab's `color_primary`. So customizing an aspect's color in the Lab does **not** recolor the chat UI. Only `color_glow` and `color_primary` inside the Lab reflect it. **PARTIAL / mostly cosmetic.**

### 3d. Titles
- `available_titles` come from `EARNABLE_TITLES` (`character_creator.py:184-221`) filtered by maturity rank (`get_available_titles`, `:370-373`). Rendered as `.charlab-title-btn` (`:129-140`).
- Click → `_bindTitleSelect` (`:199-216`) `POST /character/aspects/<id>/title` → `set_active_title()` → saved as `char_<aspect>_active_title`. Re-renders. **WORKING** (persists; used as the Lab's displayed title). Whether the *runtime* prompt uses it: `_load_aspects` overrides `title` from `get_earned_title(aid)` (a different SQLite table written by `study.py:527`/`save_earned_title`), NOT from the Character Lab `active_title`. So the Lab title is **display-only** and does not become the runtime earned title. **PARTIAL.**

### 3e. Prompt-hints preview
- `_loadHintsPreview(aid)` (`:274-286`) `GET /character/aspects/<id>/prompt-hints` → `personality_to_prompt_hints` → lists the active hint sentences (or "No special hints active (sliders near center)"). This is an honest live preview of exactly what §3a injects. **WORKING** — and it's the one place the Lab tells the truth about what's wired.

### 3f. Save vs Set-as-Main vs Reset
- **Save Changes** — PATCH dirty fields to SQLite (see 3a). Toast "Saved N changes". **WORKING.**
- **Set as Main** — `_bindActionButtons` (`:224-238`) `POST /character/main-aspect {aspect_id}` → `set_main_aspect()` writes `main_aspect` to SQLite (`character_creator.py:413-419`); also calls `window.setAspect()` and sets `localStorage.layla_default_aspect`. On next boot, `bootstrap.js:360-363`/`health.js:150` read `identity.default_aspect` and switch the rail. **WORKING.**
- **Reset Defaults** — confirm dialog → `POST /character/aspects/<id>/reset` → `reset_aspect_to_defaults()` deletes all `char_<aspect>_*` SQLite keys (`character_creator.py:291-307`). **WORKING.**

### 3g. Wizard + tutorial integration
- `renderWizardCharacterStep()` (`:348-394`) renders the 6-aspect chooser used in first-run; picking sets `_selectedAspect`, `window.setAspect`, and `localStorage.layla_default_aspect` (no server persist here — relies on later "Set as Main" or default read).
- **Tutorial overlay** — `TUTORIAL_STEPS` (6 steps: welcome, aspects, chat, memory, character_lab, complete) (`:397-404`). `startTutorial()`/`_renderTutorialStep()` render a dialog with progress dots, Back/Next/Skip, and DOM highlight of `step.highlight`. Next → `POST /character/tutorial/advance {step}` (`:454`); Finish/Skip → advance to step 99 → `advance_tutorial(99)` sets `tutorial_complete=true` (`character_creator.py:404-410`). Auto-starts 1.5s after load if wizard done & tutorial not complete (`initCharacterCreator`, `:471-482`). **WORKING.** (Minor: `aspects` step highlights `#aspect-bar`, `character_lab` step highlights `#charlab-open-btn` — both exist in index.html.)

---

## 4. Deliberation modes (solo / auto / debate / council / tribunal)

**Two DIFFERENT deliberation mechanisms exist — do not conflate them:**

### 4a. The debate engine (the multi-aspect one this cluster is about)
- **Service:** `agent/services/planning/debate_engine.py`.
- **Modes** (`:73-83`): solo=1, debate=2, council=3, tribunal=6 aspects. `run_deliberation()` (`:242-338`).
- **Mode selection:** `auto` → `select_deliberation_mode()` (`:107-141`) keyword-detects: tribunal triggers ("comprehensive review", "full analysis", "every angle") > council ("ethical", "risky", "dilemma", "harm") > debate ("should i", "trade-off", "vs", "compare") > else word-count heuristic (>80w→council, >40w→debate, else solo).
- **Aspect selection:** `select_aspects_for_task()` (`:144-186`) scores aspects by keyword overlap with `ASPECT_DOMAINS` (`:39-46`), always forces Morrigan in (she synthesizes); tribunal = all 6.
- **Pipeline (non-solo):** 3 phases — (1) independent generation per aspect in parallel (`_parallel_llm_calls`, ThreadPoolExecutor, `debate_max_workers` default 3, 55s pool timeout); (2) cross-critique (each aspect critiques the others, ≤400 tok); (3) synthesis (`_synthesize`, `:510-580`) — Morrigan/Layla merges into one voice + emits `SYNTHESIS_NOTES:`. Each aspect's mini system prompt is built by `_build_aspect_system_prompt` from the runtime JSON `name/role/voice/systemPromptAddition` (`:372-386`).
- **Cost/latency:** solo = 1 LLM call. debate = 2 gen + 2 critique + 1 synth = **5 calls**. council = 3+3+1 = **7**. tribunal = 6+6+1 = **13 calls** (parallelized in waves of 3). Params: `debate_max_tokens`=800, `debate_temperature`=0.7, `debate_synthesis_max_tokens`=1200.
- **Council heterogeneous models:** `_aspect_model_override` (`:398-410`) reads `council_aspect_models` map (aspect→model tag) and swaps the model per aspect via ContextVar (`_run_aspect_completion`, `:413-429`). This is the ONLY live per-aspect model swap in the product.

**Wiring into the main chat:** the mode is a **global config setting `deliberation_mode`**, NOT a per-message payload field.
- UI: chat-options `<select id="deliberation-mode-select" data-on-change="setDeliberationMode">` (`index.html:602-611`; options solo/auto/debate/council/tribunal, default `auto` selected in markup). Also duplicated as a raw config key in `config_schema.py:119`.
- Handler: `settings-full.js:setDeliberationMode()` (`:347-361`) → `POST /settings {deliberation_mode}` → persisted to runtime config.
- Consumed at inference by BOTH streaming and non-streaming paths:
  - `stream_handler.py:181-214`: if `deliberation_mode != solo` and not `skip_deliberation`, calls `run_deliberation(mode=…)`, and if result mode ≠ solo, emits a `__DELIB_META__…__DELIB_END__` SSE line then the final response, and **returns early** (bypasses the normal agent loop).
  - `reasoning_handler.py:164-188`: same routing for the non-stream path (`state["deliberation_result"]`).
- UI render of the transcript: `app.js:459-513` extracts `obj.deliberation`, stores `div._deliberationMeta`, shows a "N voices contributing" badge, and `chat-render.js:_renderDeliberationTranscript` (`:605-643`) renders per-aspect responses/critiques.
- **STATUS: WORKING**, with one important gap: the `<select>` runs `setDeliberationMode` on change but there is **no observed load-time sync** that sets the dropdown to the persisted `deliberation_mode` on boot — the markup hardcodes `auto` as selected. So the visible control can drift from the actual saved setting. Also, because it routes *around* the normal agent loop, non-solo modes lose tools/plans/approvals (pure text deliberation only).

**When a user picks each:**
- **Solo** — normal single-voice chat; fastest; the default for coding/task work.
- **Auto** — let Layla escalate to debate/council/tribunal by detecting decision/ethics/review language; the sensible everyday default (and the markup default).
- **Debate** — you explicitly want two opposing takes synthesized (architecture trade-offs, "X vs Y").
- **Council** — ethically/riskily loaded or complex decisions wanting 3 weighted perspectives.
- **Tribunal** — rare, expensive, "look at this from every angle" (13 LLM calls); the map parks this as experimental (§Tier-3).

### 4b. The single-model "inner voices" deliberation (separate, older)
- `orchestrator.should_deliberate(goal, aspect)` (`:313+`) + `build_deliberation_prompt()` (`:366-383`) produce a **single** prompt where one model role-plays all aspects speaking one line each, concluding as [MORRIGAN]. Triggered by `show_thinking` or deliberation phrases — independent of `deliberation_mode`. Runs only when the debate engine did NOT route (`stream_handler.py:216`, `reasoning_handler.py:193-194`). **WORKING** but easily confused with 4a; overlapping triggers ("should i") fire both systems' heuristics.

---

## 5. Titles / traits / earnable-titles + tutorial (recap of statuses)
- `/character/earnable-titles` (`character.py:175-179`) returns the full `EARNABLE_TITLES` map. **WORKING** endpoint; the Lab uses the rank-filtered `available_titles` instead. Titles are display-only vs the runtime `earned_title` (§3d). **PARTIAL.**
- `/character/traits` + `/character/voice-params` metadata endpoints. **WORKING.**
- Tutorial: **WORKING** (§3g).
- Maturity card (`aspect.js:refreshMaturityCard`, `:132-199`) `GET /operator/profile` drives rank/phase/XP + rank-up ceremony — adjacent to this cluster (Growth), **WORKING**, but the ranks it surfaces are what gate title unlocks here.

---

## STATUS TABLE

| Feature | Status | Evidence |
|---|---|---|
| Aspect definitions (6 rich personas) | **working** | `personalities/*.json`; `orchestrator._load_aspects` orchestrator.py:74-127; style card :53-71 |
| Aspect switch (rail) affects reply | **working** | app.js:301 payload.aspect_id → run_setup.py:192/214 `select_aspect(force_aspect=)` |
| Rail switch persists across reload | **partial** | client-only (aspect.js:63-116); no server save on switch; only "Set as Main" persists |
| Per-aspect system prompt injection | **working** | prompt_builder.py:197-236; systemPromptAddition + failure_mode |
| Per-aspect reasoning depth | **working** | run_setup.py:219 `apply_reasoning_depth`; aspect_behavior.py:107-143 |
| Per-aspect max tool steps | **working** | run_setup.py:731 `get_max_steps`; aspect_behavior.py:146-167 |
| Per-aspect length/refusal block | **working** | system_head_builder.py:717-720 `build_behavior_block` |
| Per-aspect retrieval boost (expertise_domains) | **working** | llm_decision.py:94-140,548-552 domain_boost_terms |
| NSFW register (aspect nsfw_triggers) | **working (Lilith only)** | orchestrator.py:264-273; prompt_builder.py:207-212; only lilith.json has `systemPromptAdditionNsfw` |
| Aspect lock | **working** | aspect.js:118-129; app.js:272 forces current aspect over @mention |
| @mention mid-message | **working (leading only)** | app.js:258-271 `/^@([a-z]+)/`; input.js dropdown :32-83 |
| Per-aspect **model** override (main chat) | **dormant/dead** | route_model supports aspect_id (model_router.py:330) but live call llm_gateway.py:389 passes none; default `{}` runtime_safety.py:615 |
| Per-aspect **tool** boost/suppress | **dead** | ASPECT_TOOL_PREFERENCES aspect_behavior.py:217-251 referenced **only** by tests; no prod call site |
| Character Lab: personality sliders → prompt | **working** | personality_to_prompt_hints character_creator.py:312-365 → prompt_builder.py:218-229 |
| Character Lab: voice sliders → TTS | **ui-without-backend (dead)** | voice.py:41-67 hardcoded `_ASPECT_SPEEDS`; ignores pitch/warmth/formality/custom speed |
| Character Lab: color picker → chat UI | **partial (cosmetic)** | saved to SQLite but chat rail uses hardcoded aspect.js:14-21; not sourced from color_primary |
| Character Lab: titles | **partial** | persists active_title; runtime uses separate get_earned_title (study.py:527), not Lab title |
| Character Lab: prompt-hints preview | **working** | character-creator.js:274-286 → /character/aspects/{id}/prompt-hints |
| Character Lab: Save / Set-Main / Reset | **working** | PATCH/`/main-aspect`/`/reset` character.py:77-97,152-156 |
| Deliberation debate engine (solo/debate/council/tribunal) | **working** | debate_engine.py; stream_handler.py:181-214; reasoning_handler.py:164-188 |
| Deliberation mode dropdown persistence | **partial** | setDeliberationMode POST /settings (settings-full.js:347-361); no boot-time sync back to `<select>` (markup hardcodes `auto`) |
| Deliberation bypasses tools/approvals | **working-by-design (risk)** | non-solo returns early before agent loop (stream_handler.py:213-214) |
| Council heterogeneous models | **working (opt-in)** | `council_aspect_models` debate_engine.py:398-429 |
| Single-model "inner voices" deliberation | **working (duplicate concept)** | orchestrator.should_deliberate/build_deliberation_prompt :313-383 |
| Tutorial overlay (6 steps) | **working** | character-creator.js:397-468; /tutorial/advance |
| Earnable-titles endpoint | **working** | character.py:175-179 |
| Two parallel aspect data models | **duplicate (architectural)** | character_creator.ASPECT_DEFAULTS vs personalities/*.json — divergent titles/values |

---

## TOP UX PROBLEMS (ranked)

1. **Voice sliders are a lie (dead controls).** The Character Lab presents four precise voice
   knobs (pitch/speed/warmth/formality) with numeric feedback, but `/voice/speak` ignores all of
   them and uses a hardcoded per-aspect speed (`voice.py:60-66`). *Why it matters:* users spend
   effort tuning a voice that never changes — the single most trust-eroding thing in this cluster.
   *Fix:* either wire the saved voice profile into `speak_to_bytes` (map warmth/formality to
   available kokoro voices, pitch/speed to synthesis params) or remove/disable the sliders and
   label TTS as aspect-preset only.

2. **Two divergent aspect definitions confuse "what am I even editing."** The Lab edits
   `character_creator.ASPECT_DEFAULTS` (sliders/colors/titles in SQLite) while the actual persona
   voice/behavior lives in `personalities/*.json`. They disagree on titles and are authored
   independently, so editing "bluntness" in the Lab does not touch Morrigan's real `voice`/`do_not_do`
   contract, and Lab titles never become runtime titles. *Impact:* the deep customizer feels
   authoritative but only controls a thin slice. *Fix:* unify on one source, or clearly scope the
   Lab as "tuning overlay on top of the fixed persona."

3. **Rich aspect differentiation is half-wired: model + tool preferences are dead.**
   `ASPECT_TOOL_PREFERENCES` (Cassandra suppresses fetch, Lilith suppresses shell/write, etc.) and
   `aspect_model_overrides` are fully built + tested but never called in the live loop
   (`llm_gateway.py:389` drops aspect_id; tool prefs have no prod caller). *Impact:* aspects feel
   more similar than the design intends; Lilith does not actually become safer at the tool layer,
   Cassandra does not actually prefer analysis tools. *Fix:* thread `aspect_id` into `route_model`
   and apply `get_tool_preferences` in the tool-ranking step (both are one-line integrations).

4. **Deliberation mode control can silently disagree with reality + is buried.** The dropdown fires
   on change but nothing syncs it to the persisted `deliberation_mode` at boot (markup hardcodes
   `auto`), so a user who set "council" last week sees "Auto." It's also a global setting styled like
   a per-message toggle. *Impact:* confusion about whether debate is on; accidental expensive tribunal
   runs. *Fix:* load and reflect the saved value on init; consider making it per-conversation and
   showing a cost hint (debate≈5×, council≈7×, tribunal≈13× LLM calls).

5. **Non-solo deliberation quietly drops tools/plans/approvals.** When `deliberation_mode != solo`,
   `stream_handler`/`reasoning_handler` route to the debate engine and `return` before the normal
   agent loop — so file writes, code execution, and plan/approval governance never run; you get a
   text-only committee answer. *Impact:* a user in "debate" mode asking Layla to *do* something gets
   discussion, not action, with no signal that tools were skipped. *Fix:* either restrict debate to
   advisory turns, or feed the synthesized decision back into the tool loop.

6. **Aspect switch doesn't persist; lock semantics are oversold.** Clicking a rail aspect changes
   only the client until the next send; a reload reverts to the default aspect (server never told).
   The lock tooltip claims it "prevents auto-routing," but its real effect is pinning the UI against
   @mention/rail clicks (`app.js:272`). *Impact:* mismatch between mental model and behavior after
   refresh; misleading lock copy. *Fix:* persist current aspect per conversation server-side; reword
   the lock tooltip to "pin aspect (ignore @mentions & switching)."

7. **@mention only works as a leading token.** `^@([a-z]+)` (`app.js:258`) ignores mid-sentence
   mentions and multi-word names, and silently no-ops on typos (the `@foo` is sent literally).
   *Impact:* users who type "hey @cassandra what about…" get the current aspect with a stray `@`.
   *Fix:* validate against ASPECT list on send and surface an inline hint when a mention is
   unrecognized; optionally support mid-message routing.

8. **Personality-slider hints are coarse and primary-only.** Hints fire only at ≥8/≤2 thresholds and
   only for the turn's primary aspect (`prompt_builder.py:218-229`), so mid-range tuning (4–7) has
   zero effect and the preview says "no special hints." *Impact:* sliders feel inert across most of
   their range. *Fix:* interpolate hint strength across the range, or relabel sliders as
   three-position (low/neutral/high) to match the actual thresholds.
