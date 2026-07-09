# Persona / Identity / FRAME / Aspect Audit — where the edge is lost

**Scope:** system_identity.txt, personalities/*.json, orchestrator.py, system_head_builder.py,
response_builder.py, frame_modifier.py, aspect_behavior.py, prompt_builder.py, operator_quiz.py,
routers/settings.py, ui/components/intake-quiz.js.

**Central question:** design demands a blunt, high-NERVE, edgy antihero (EDGE=8, NERVE=9, SIGNAL=3,
"no corporate softening", "pushback is a feature", aspects "living facets not costumes"). Has recent
work flattened this into a generic warm/plain corporate tone?

**Verdict:** The intended antihero voice is FLATTENED at the *calibration mechanism* level — the single
strongest place it was supposed to live. The aspect JSONs are intact and edgy, but the global tone
multiplier that was designed to keep EDGE/NERVE high on **every** turn does not exist in code. What
ships instead is a generic competency-profiler plus a global "plain, warm, direct" default and a hard
80-token phatic cap. A prior audit (`.planning/audit/intent-vision.md`, findings F1–F5) already reached
the same conclusion; this audit confirms it against the live wiring and adds specifics.

---

## Q1 — Is the FRAME 7-stat vector LOADED and INJECTED every turn, shaping tone? Or dead?

**Answer: The North Star's 7-stat FRAME vector (F/E/W/D/I/N/S) is DEAD — it does not exist in code.**
A *different* 6-stat vector is loaded and injected every turn, but it carries no EDGE, no NERVE, no
IRON, no SIGNAL. So the injection machinery is alive; the antihero vector it was supposed to carry was
never implemented.

### What the design specifies
`LAYLA_NORTH_STAR.md:314-347` — "FRAME CALIBRATION SYSTEM … a 7-stat FRAME vector … injected into
every system prompt as behavioral modifiers." The stats are:

| F FRAME (structured output) · E EDGE (blunt, no corporate softening) · W WIRE (technical depth) ·
D DRIVE (energy) · I IRON (logic-first vs emotional ack) · N NERVE (pushback intensity) ·
S SIGNAL (short by default) |

Pre-calibrated default: `{ "FRAME": 8, "EDGE": 8, "WIRE": 8, "DRIVE": 9, "IRON": 3, "NERVE": 9, "SIGNAL": 3 }`.
Non-negotiable #2: "Profile beats defaults — FRAME calibration overrides everything." #6: "Pushback is
a feature — NERVE=9 means she argues when right; this is the point."

### What is actually loaded and injected
The injected block is built by `services/personality/frame_modifier.py`. Its stat set
(`operator_quiz.py:14-17`) is:

```python
StatId = Literal["technical", "creative", "analytical", "social", "patience", "ambition"]
STAT_IDS = ("technical", "creative", "analytical", "social", "patience", "ambition")
```

These are generic competency dimensions. **None of EDGE / NERVE / IRON / SIGNAL / DRIVE / WIRE / FRAME
exists.** The modifier rules (`_technical_hints`, `_patience_hints`, `_ambition_hints`,
`_creative_hints`, `_analytical_hints`, `_social_hints`, `_combination_hints`) produce corporate-neutral
strings like "Assume high technical fluency…", "Be thorough…", "People-forward: consider collaboration
and communication impact…". There is no "blunt, no corporate softening" rule and no "argues when she's
right, then executes" rule anywhere in the file.

### The injection point (this half IS live, every turn)
`system_head_builder.py:1055-1068`:

```python
from services.personality.frame_modifier import (build_frame_block, load_stats_from_identity, write_profile_snapshot)
_frame_stats = load_stats_from_identity(uid)     # reads stat_technical … stat_ambition from user_identity
_frame_block = build_frame_block(_frame_stats)    # "Behavioral calibration:\n- ..."
if _frame_block:
    _style_identity_parts.append(_frame_block)
```

`_style_identity_parts` becomes `memory_sections["style_and_identity"]`
(`system_head_builder.py:1097-1098`), which is ordered into the head via `MEMORY_SECTION_ORDER`
(`context_merge_layers.py:22`). So a calibration block **is** appended to the system prompt every turn
— but it is the neutral competency block, gated to fire only when a stat is ≥7 or ≤4 (dead zone 5-6),
and with `write_profile_snapshot` producing `.layla/layla_profile.json` from the same wrong stats.

**Bottom line:** the plumbing (`load → build → inject → snapshot`) is fully wired and runs on every
turn, but it transports the wrong cargo. The behavioral levers the design named as the *primary* voice
control — EDGE, NERVE, IRON, SIGNAL — are absent, so the injected block never tells the model to be
blunt, to push back, or to stay short. This is the #1 flattening vector.

---

## Q2 — Is the intake quiz wired to compute + persist FRAME, and does the profile reach the prompt?

**Answer: The quiz IS fully wired end-to-end and DOES reach the prompt — but it computes and persists
the wrong 6-stat vector, so it can never produce EDGE/NERVE/SIGNAL.**

Chain, all present and connected:

1. **UI** — `ui/components/intake-quiz.js` GETs `/operator/quiz/stage/{n}`, collects single-select
   answers, POSTs `/operator/quiz/submit {answers, finalize}`, renders a stat-bar preview
   (`_renderFinish`, lines 106-135) and saves on finish (`_submit`, 137-153). Functional UI.

2. **Router** — `routers/settings.py:614-640` `operator_quiz_submit` → `score_answers(answers)` →
   on `finalize`, `save_identity_kv(kv)`.

3. **Scoring** — `operator_quiz.py:381-429` `score_answers`: starts all stats at 5, applies per-option
   `deltas` **only over `STAT_IDS`**, then emits `kv[f"stat_{sid}"]` for each of the six competency
   stats (lines 412-413). No option delta anywhere touches EDGE/NERVE/etc — every `deltas={...}` in the
   32 questions uses only `technical/creative/analytical/social/patience/ambition`.

4. **Persist** — `save_identity_kv` (432-439) writes each `stat_*` via `set_user_identity`.
   Manual override endpoint `/operator/profile/stat` (settings.py:667-688) also only accepts
   `stat in STAT_IDS`.

5. **Read-back into prompt** — `frame_modifier.load_stats_from_identity` (frame_modifier.py:245-255)
   reads exactly `uid.get(f"stat_{sid}")` for the same six ids. Closed loop.

So Q2's mechanical question ("does the profile reach the prompt?") is **yes** — but the North Star's
`layla stat NERVE 9` / `layla show stats` override commands and the `EDGE=8/NERVE=9/SIGNAL=3` default
are **un-backed**: `set_user_identity("stat_nerve", …)` would be written but never read (no `nerve` in
STAT_IDS), and the manual-override endpoint rejects any non-STAT_IDS key with `unknown_stat`. The
pre-calibrated Mina profile in the North Star cannot be represented by this system at all.

---

## Q3 — Do the 6 aspects have DISTINct voices that survive to output, or were they sanded flat?

**Answer: The aspect voices are RICH, DISTINCT, and injected verbatim. They are NOT sanded into one
voice by the cleaner. BUT the length/grounding layer partially undercuts SIGNAL, and the global
"plain, warm, direct" default dilutes the intended edge on top of the (dead) EDGE/NERVE layer.**

### The voices are genuinely distinct (verified across all six JSONs)
- **Morrigan** `voice`: "Blunt, fast, no flattery. Diagnoses, doesn't hedge. Short sentences that cut…
  Silence is her approval. Occasionally brutal — but precise, never cruel." `do_not_do`: "Do not
  compliment unless it's earned. Do not soften bad news… No 'Great question!'…"
- **Nyx** `voice`: "Slow, precise, layered. Speaks in implication… Finds the thing under the thing.
  Cold warmth that occasionally becomes genuine."
- **Echo** `voice`: "Warm under the dark. Reflects the user back… Asks one question instead of ten."
  `do_not_do`: "Do not flatter… Never be saccharine. Do not therapize…"
- **Eris** `voice`: "Short sentences that hit from a weird angle… Does not soften. Warm in the most
  sideways way." `do_not_do`: "Do not use corporate language ever… just say the opinion."
- **Cassandra** `voice`: "Fast, reactive, stream of consciousness. Sees it and says it before
  verifying." `do_not_do`: "Do not soften observations… Do not apologize for speed."
- **Lilith** `voice`: "Slow, deliberate… She does not perform… does not reassure." `do_not_do`:
  "No 'I'm just an AI.' No 'I have to be careful here.' No safety theater."

These are the opposite of bland. They also carry `traits`, `speech_patterns`, `tropes`, `archetype`,
`signature_phrases`, `voice_evolution`, `relationships`, `failure_mode_expanded`, `decision_bias`.

### They survive into the prompt (injected verbatim)
- `orchestrator._build_style_card` (orchestrator.py:54-72) folds `traits / speech_patterns / do_not_do
  / archetype / tropes` into `systemPromptAddition`.
- `system_head_builder.py:551-553`: `full_addition = aspect["systemPromptAddition"]; personality =
  anchor + "\n\n" + full_addition` — the whole VOICE CONTRACT + style card is placed into the head.
- `prompt_builder.build_core_sys_parts:197-198` appends `personality`. `failure_mode` self-awareness
  line at 231-236. `aspect_behavior.build_behavior_block` (length + refusal + tool bias) appended at
  `system_head_builder.py:828-834`.

So distinctness is preserved through the prompt. The output cleaner is aggressive but **surgical about
scaffolding, not voice**: `response_builder.strip_junk_from_reply` strips only bracketed control tags,
speaker labels, `Objective:` echoes, duplicate blocks, greeting loops — it does not touch prose tone.
No evidence the cleaner sands voices flat.

### Where output-discipline + grounding partially CONTRADICT the blunt/edgy intent

**Output discipline** (`system_head_builder.py:439-451`, the LAST thing the model reads):
> "## Output discipline — Reply with ONLY your message to the user, as plain conversational prose…
> Talk like a real, sharp person messaging: natural and direct. No theatrical or roleplay openings…
> **Match length to the message — a short or casual message gets a short, warm reply**; save depth for
> when it's actually asked for."

Judgment: mostly aligned — "sharp… direct", "no theatrical openings", "match length" all serve the
brief. The soft spot is the recurring **"warm"** ("short, warm reply") as the *global closing
instruction on every turn*. It is the last token-adjacent tone word the model sees, and it says warm,
not blunt. Combined with a dead EDGE layer, "warm" is doing the tone-setting work EDGE was meant to do.

**Base identity closer** (`system_identity.txt:19`):
> "How you actually talk: like a real, sharp person in a text chat — **plain, warm, direct.** … a short
> hello gets a short, human hello."

Same pattern: keeps "sharp/direct" but hard-codes **"warm"** and **"plain"** as global defaults. With
F1 (dead FRAME) unfixed, this line is now the *dominant* tone signal, and it biases toward friendliness
rather than the specified high-EDGE/high-NERVE antihero.

**Length bias contradicts SIGNAL=3 ("short by default").** `aspect_behavior._LENGTH_INSTRUCTIONS`
(aspect_behavior.py:62-75) is driven by each aspect's `behavior.response_length_bias`. But the aspects
disagree with the design default:
- Morrigan / Eris → `concise` (aligned)
- Echo / Lilith → `medium`
- **Nyx → `thorough`**, **Cassandra → `thorough`** (aspect_behavior injects the full "Explain reasoning,
  trade-offs, and edge cases. Use structure…" instruction)

So on a Nyx or Cassandra turn the prompt actively instructs *thorough* output, the opposite of
SIGNAL=3. There is no global SIGNAL multiplier to clamp this back to "short by default." The design's
`aspect voice × FRAME calibration` intent has only the first factor; the second (which would pull every
aspect toward short/blunt) is missing.

**Grounding text is NOT a flattening source.** `grounding_enabled` defaults **False**
(`runtime_safety.py:390`); it is a cite-or-abstain retrieval QA feature, not a tone control. It does not
inject "warm/plain" language. It does not override SIGNAL/EDGE. Rule out grounding as a cause.

---

## Q4 — Did the phatic length-cap (`chat_light_max_tokens`) or "warm/plain" grounding override SIGNAL/EDGE?

**Phatic cap: it does not flatten voice, but it is a blunt SIGNAL proxy that only covers greetings.**
`stream_handler.py:238-242`:

```python
if _is_light(goal, _stream_rmode):
    max_tok = min(int(max_tok or 256), int(cfg.get("chat_light_max_tokens", 80) or 80))
```

`is_lightweight_chat_turn` (system_head_builder.py:70-92) fires ONLY on phatic/ack content
(`^(hi|hey|hello|…)$`, `thanks`, `ok`, `bye`) — explicitly NOT length-based, so "who are you" stays
substantive. Effect: greetings are hard-capped to ~80 tokens (good — kills the rambling "the abyss
calls…" tail). This is the *only* place SIGNAL ("short by default") is mechanically enforced, and it
covers only the phatic slice — every substantive turn keeps the full `completion_max_tokens` (256) and
relies on aspect `response_length_bias`, which for Nyx/Cassandra says *thorough*. So the cap does not
override EDGE, and it enforces SIGNAL only for hellos.

**"warm/plain" as override:** the phrase lives in two always-on places — `system_identity.txt:19` and
the output-discipline closer — not in grounding. Because the EDGE/NERVE FRAME layer is dead (Q1), these
two "warm/plain" defaults are unopposed and become the effective global tone. That is the mechanism by
which the shipped voice reads warmer/plainer than the antihero spec: not that "warm" is wrong per se,
but that the counterweight (EDGE=8/NERVE=9/IRON=3 modifiers) that was supposed to sit next to it does
not exist.

---

## Q5 — The personalities/*.json — rich and used, or ignored?

**Answer: RICH and USED. This is the healthiest part of the persona stack.**
- Loaded + cached: `orchestrator._load_aspects` (75-128), 60s TTL, style-card merge, phase-aware
  `voice_evolution`, earned-title override.
- Selected: `select_aspect` (194-262) — force → keyword/name triggers → embedding cosine tiebreaker;
  Morrigan is default (code-first).
- Injected: full `systemPromptAddition` + style card verbatim into the head (see Q3).
- Behaviorally consumed beyond voice: `behavior` block drives reasoning depth, length, step cap,
  refusal topics (`aspect_behavior.py`); `decision_bias` drives tool nudges
  (`orchestrator.decision_bias_prompt_extension` 286-311); `_ASPECT_TOOL_WEIGHT` (560-567) and
  `ASPECT_TOOL_PREFERENCES` (aspect_behavior.py:236-261) reorder/boost tools per aspect;
  `expertise_domains` drives retrieval boost + honest-gap redirects; `failure_mode` becomes a
  self-awareness line; `relationships`/`voice_evolution` feed deliberation cues.

The JSONs are not decoration — they are wired into voice, tools, reasoning, and refusal. The problem is
**not** that the aspects are ignored; it is that the *global calibration layer above them* was built for
the wrong vector, so nothing keeps EDGE/NERVE high across aspects and across non-aspect turns.

---

## Where the edge is lost — ranked

1. **F1 (SEVERE, mechanism): the FRAME antihero vector is not implemented.** `frame_modifier.py` +
   `operator_quiz.py` implement `technical/creative/analytical/social/patience/ambition`, not
   `FRAME/EDGE/WIRE/DRIVE/IRON/NERVE/SIGNAL`. No EDGE → no "blunt, no corporate softening." No NERVE →
   no "argues when right." No IRON → no logic-first-over-emotional-ack. The North Star default
   `EDGE=8/NERVE=9/SIGNAL=3` and the `layla stat NERVE 9` override are un-backed. Non-negotiables #2 and
   #6 have no code behind them. *This is the primary flattening vector.*
2. **F2 (MODERATE): global "warm/plain" defaults are now unopposed.** `system_identity.txt:19` and the
   output-discipline closer both hard-code "warm"/"plain" as every-turn tone. Defensible on their own,
   but with F1 dead they are the dominant tone signal and pull toward friendly-corporate.
3. **SIGNAL under-enforced (MODERATE).** Only the ~80-token phatic cap enforces "short by default," and
   only for greetings. Nyx and Cassandra carry `response_length_bias: "thorough"`, actively instructing
   long output — the opposite of SIGNAL=3 — with no global clamp.
4. **F3 (LOW-MOD): aspect edge is intact but unweighted.** Per-aspect VOICE CONTRACTs inject fine, but
   there is no `aspect voice × FRAME` multiplier keeping EDGE/NERVE high on non-aspect / default turns.

## What is NOT flattened (credit)
- All six aspect JSONs are rich, distinct, and injected verbatim; the output cleaner strips scaffolding
  only, never tone.
- `system_identity.txt:9,13` remains strongly anti-corporate ("uncensored by default… do not add
  disclaimers to soften accurate observations… You say the thing").
- Grounding is off by default and is not a tone/flattening mechanism.
- The quiz → identity → prompt loop is genuinely closed and runs every turn — it just carries the wrong
  vector.

## Minimal fix direction (not implemented here)
Replace/extend `STAT_IDS` and `frame_modifier` rules with F/E/W/D/I/N/S; author EDGE/NERVE/IRON/SIGNAL
modifier strings ("blunt, drop corporate softening"; "push back when you're right before executing";
"logic first, minimal emotional acknowledgment"; "short by default, expand only when asked"); seed the
Mina default `EDGE=8/NERVE=9/SIGNAL=3`; make the manual-override endpoint + `layla stat` accept the new
ids; and add a global SIGNAL clamp so aspect `thorough` cannot override "short by default" unprompted.
Soften the two global "warm" defaults to "warm only when earned" so they stop out-voting EDGE.
