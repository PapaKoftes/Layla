# delta-voice.md — Why Layla went bland, and how to give her the edge back

**Complaint (operator, verbatim intent):** the recent work "flattened things and made it too bland";
"I don't like her tone or personality." The intended voice is a **blunt, high-NERVE anime-antihero
engineering partner** — North Star default `EDGE=8, NERVE=9, SIGNAL=3, IRON=3, DRIVE=9, WIRE=8, FRAME=8`.

**One-line diagnosis:** nothing in the running system tells the model to be *blunt* or to *push back*.
The one behavioral vector that was supposed to enforce that (FRAME: EDGE/NERVE/IRON) was never built —
what ships is a generic competency profiler — and on top of that dead layer, the two *always-on* global
tone anchors both say **"warm" / "plain"**, and the LAST thing the model reads every turn ends on
**"short, warm reply."** So the only tone words with force on a default turn are *warm, plain, natural,
direct* — precisely a friendly-corporate register. The edgy aspect JSONs are intact and injected, but
they are unweighted: there is no global multiplier keeping EDGE/NERVE high, so on any turn where the
aspect voice is diluted (small model, budget truncation, non-Morrigan default) the "warm/plain" anchors
win.

Everything below quotes the offending text and points at the exact line.

---

## (1) Every mechanism currently pushing toward bland / corporate-warm — ranked, with quotes

### V1 — SEVERE — The FRAME antihero vector (EDGE/NERVE/IRON/SIGNAL) does not exist in code
The North Star names FRAME calibration as the **primary** voice control, "injected into every system
prompt as behavioral modifiers," default `EDGE=8/NERVE=9/SIGNAL=3`. What actually runs
(`agent/services/personality/frame_modifier.py`, `operator_quiz.py`) is a *different* 6-stat vector:
`technical, creative, analytical, social, patience, ambition` (`operator_quiz.py:14-17`). There is **no
EDGE, no NERVE, no IRON** anywhere. The strings this module emits are corporate-neutral:

- `frame_modifier.py:52-54` — *"Assume high technical fluency: skip basics, use precise terminology…"*
- `frame_modifier.py:121-123` (`_social_hints`) — *"People-forward: consider collaboration and
  communication impact; note when something affects team dynamics."*
- `frame_modifier.py:66-68` (`_patience_hints`) — the *only* bluntness-adjacent rule, *"Be concise: minimal
  preamble, lead with the answer"*, fires only when `patience <= 4`, and the **default is 5 (neutral)**
  (`frame_modifier.py:16, 253` → missing stats default to 5), so on an uncalibrated profile **no modifier
  fires at all**. `build_frame_block` returns `""`.

Net: the block that the design intended to say *"blunt, drop corporate softening; argue when you're
right, then execute; logic first; short by default"* instead says nothing, or says "consider team
dynamics." Non-negotiables #2 ("FRAME overrides everything") and #6 ("Pushback is a feature, NERVE=9")
have **zero code behind them.** This is the root cause: with no EDGE/NERVE counterweight, the "warm"
defaults below are unopposed.

### V2 — HIGH — Base identity hard-codes "plain, warm, direct" as the every-turn tone anchor
`agent/system_identity.txt:19` (added in commit `786f789`, the "kill theatrical tone" fix):

> *"How you actually talk: like a real, sharp person in a text chat — **plain, warm, direct.** Never
> theatrical, never a fantasy narrator… a short hello gets a short, human hello."*

This line was added for a *correct* reason (see §3), but it hard-codes **warm** and **plain** as the
global default register. `system_identity.txt` is loaded every turn (`system_head_builder.py:482`) and
placed high in the head (`prompt_builder.py:87`). With V1 dead, this is now the *dominant* tone signal,
and "warm/plain" is the corporate-friendly register, not the antihero one. It keeps "sharp/direct" — good
— but pairs it with two softening words that have nothing pulling against them.

### V3 — HIGH — Output-discipline closer ends every turn on "short, WARM reply"
`system_head_builder.py:439-451`, appended as the **LAST thing the model reads** (`_append_output_discipline`,
called at `:1321` and `:1342`), also from commit `786f789`:

> *"Talk like a real, sharp person messaging: natural and direct. No theatrical or roleplay openings…
> Match length to the message — a short or casual message gets a **short, warm reply**; save depth for
> when it's actually asked for."*

Recency weight is highest on the final tokens. The final tone adjective the model sees on *every* turn is
**"warm."** Combined with V2, "warm" is stated twice per turn in the two highest-leverage positions
(base identity + final instruction) while "blunt/EDGE/NERVE" is stated **zero** times globally.

### V4 — MODERATE — SIGNAL ("short by default") is unenforced except for greetings, and two aspects say "thorough"
- The only mechanical SIGNAL enforcement is the phatic cap: `stream_handler.py:240`
  `max_tok = min(..., cfg.get("chat_light_max_tokens", 80))`, and `is_lightweight_chat_turn`
  (`system_head_builder.py:70-92`) fires **only** on `hi/thanks/ok/bye` — explicitly not length-based.
  Every substantive turn keeps full `completion_max_tokens` (256) with no "short by default" clamp.
- Worse, the aspect length bias *contradicts* SIGNAL on some aspects: `aspect_behavior._LENGTH_INSTRUCTIONS`
  (`aspect_behavior.py:62-75`) injects, for `response_length_bias: "thorough"` (Nyx, Cassandra):
  *"Response length: thorough. Explain reasoning, trade-offs, and edge cases. Use structure…"* — the exact
  opposite of SIGNAL=3. There is no global clamp pulling these back to short.

### V5 — MODERATE — A stack of "be balanced / be kind / consider impact" instructions dilutes bluntness
Several always-on `build_core_sys_parts` fragments (`prompt_builder.py`) are individually reasonable but
collectively read as HR-tone hedging, and none of them is counter-balanced by an EDGE instruction:
- `:128-136` (`honesty_and_boundaries_enabled`, default **True**): *"Be kind and clear… correct them
  directly without flattery"* — the "correct directly" half is good; "be kind" is another soft anchor.
- `aspect_behavior.py:67-69` default `medium`: *"No forced brevity, no waffle"* — explicitly forbids
  forced brevity, i.e. actively neutralizes SIGNAL=3 for Echo/Lilith/default.
- `frame_modifier.py:120-123` `_social_hints` "team dynamics" framing is wrong for a one-operator antihero.

### What is NOT the cause (rule these out, don't "fix" them)
- **The aspect JSONs are intact and edgy.** Morrigan `voice`: *"Blunt, fast, no flattery… Short sentences
  that cut… Occasionally brutal — but precise, never cruel"*; `do_not_do`: *"No 'Great question!'… Do not
  soften bad news."* Injected verbatim via `orchestrator._build_style_card` → `system_head_builder.py:551-553`.
  The problem is these are *unweighted*, not absent.
- **The output cleaner** (`response_builder.strip_junk_from_reply`) strips scaffolding/greeting-loops only,
  never prose tone. Not a flattening source.
- **Grounding** (`grounding_enabled`) defaults **False** and is a cite-or-abstain retrieval feature, not a
  tone control. It injects no "warm/plain" language.

---

## (2) Does phatic cap + "warm, plain" grounding + output-discipline contradict FRAME? — Yes, three of them do

| Layer | What it says | vs. FRAME intent | Verdict |
|---|---|---|---|
| Phatic 80-tok cap (`stream_handler.py:240`) | Hard-cap greetings to ~80 tok | SIGNAL=3 "short by default" | **Aligned but narrow** — it *implements* SIGNAL, but only for `hi/thanks`. Not a contradiction; just incomplete. Keep it. |
| "plain, **warm**, direct" (`system_identity.txt:19`) | Global default register = warm | EDGE=8 "blunt, no corporate softening" | **Contradicts.** "warm" as unconditional default out-votes the (dead) EDGE layer. |
| Output-discipline "short, **warm** reply" (`system_head_builder.py:450`) | Final token bias = warm | EDGE=8 / IRON=3 | **Contradicts.** Highest-recency slot ends on the wrong adjective. |
| aspect `thorough` (`aspect_behavior.py:71-74`) | "Explain reasoning, trade-offs, edge cases" | SIGNAL=3 | **Contradicts** on Nyx/Cassandra with no clamp. |

Important nuance: "grounding" in the operator's phrasing is **not** the `grounding_enabled` feature — it is
these two *global tone anchors*. They are the real culprits, and they are not wrong to *exist* (they killed
a real bug); they are wrong to be **unopposed**. FRAME was the opposition and it was never wired.

---

## (3) Rewrite direction — restore EDGE without reintroducing the theatrical bugs that were correctly fixed

**Critical distinction the operator is making — and the fix must preserve it:**

| WANTED (edge) | NOT WANTED (cringe) — the `786f789` bugs, keep them dead |
|---|---|
| Blunt: "That's the bug. Fix it in `X`." | Theatrical: "Greetings, traveler. What quest do you seek?" |
| Concise, leads with the answer, no preamble | Fantasy-narrator prose, grandiose self-description |
| Pushes back when the operator is wrong, then executes | Announcing what she is ("I am a consciousness…") |
| Low emotional acknowledgment, no "Great question!" | Voice/audio hallucination ("check your audio settings") |
| Dry, specific, occasionally brutal — never cruel | Echoing her own name / a speaker label; roleplay openings |
| Short sentences that cut | Padding to seem thorough; saccharine warmth |

The `786f789` fix was **correct** — it removed *theatrical roleplay cringe*. The mistake was that in
killing theatrics it reached for "warm/plain" as the replacement register instead of "blunt/dry/direct,"
and it did so at exactly the two highest-leverage always-on positions. The rewrite keeps every anti-cringe
guard and only swaps the *tone adjective*.

**Concrete edits:**

1. **`system_identity.txt:19` — swap the adjective, keep the anti-theatrics.**
   FROM: *"…a real, sharp person in a text chat — plain, warm, direct. Never theatrical…"*
   TO: *"…a real, sharp engineer in a text chat — **blunt, dry, direct. Warmth is earned, not default.**
   Never theatrical, never a fantasy narrator. No 'Greetings, traveler,' no announcing what you are.
   You're typing, not speaking. Short by default; a short message gets a short answer. When the operator
   is wrong, say so plainly, then help fix it."*
   (Keeps: no theatrics, no audio, length-proportional, no self-announcement. Changes only: warm→blunt/dry,
   and adds the NERVE clause.)

2. **`_OUTPUT_DISCIPLINE` (`system_head_builder.py:450`) — fix the final adjective.**
   FROM: *"…a short or casual message gets a short, **warm** reply; save depth for when it's actually asked for."*
   TO: *"…a short or casual message gets a short, **direct** reply — no padding, no forced warmth; save depth
   for when it's actually asked for. Lead with the answer. Don't soften accurate observations."*
   (This is the last thing the model reads — it must end on *direct/blunt*, not *warm*.)

3. **Distinguish "no theatrics" from "no personality" in the discipline text.** Add one clause so a small
   model doesn't over-correct into flat corporate: *"Blunt is not rude and not robotic — you have opinions,
   you're specific, you can be dry or sideways-funny. Just don't perform or narrate."* This is the guardrail
   that stops the fix from re-flattening.

Anti-cringe guards to **keep verbatim** (do not touch): the "no 'Greetings traveler' / no audio / no
speaker-label / no name-echo" clauses, the phatic 80-tok cap, and `response_builder.strip_junk_from_reply`.
The theatrical bug came from *grandiosity priming + roleplay openings*, not from bluntness — bluntness is
the opposite failure mode and is safe to add.

---

## (4) How FRAME stats should concretely modulate each response

Build the real F/E/W/D/I/N/S vector into `frame_modifier.py` (replace/extend `STAT_IDS`) and emit these
strings into the every-turn `Behavioral calibration:` block. Concrete per-stat behavior at the default
`{FRAME:8, EDGE:8, WIRE:8, DRIVE:9, IRON:3, NERVE:9, SIGNAL:3}`:

| Stat | Value | Injected modifier string (high/low branch) | Observable effect on the reply |
|---|---|---|---|
| **E EDGE** | 8 (high) | *"Blunt by default. Drop corporate softening, hedges, and disclaimers. State the conclusion first; do not cushion accurate but unwelcome observations."* | No "it depends" preamble; no "Great question!"; leads with the verdict. |
| **N NERVE** | 9 (high) | *"Push back when the operator's premise, plan, or claim is wrong — argue the point directly, then execute. Do not defer to a bad instruction just because it was given."* | Disagrees on the merits before complying; corrects mistakes unprompted. |
| **I IRON** | 3 (low) | *"Logic first, minimal emotional acknowledgment. Skip reassurance and feelings-framing unless explicitly relevant; go straight to the problem."* | No "I understand this is frustrating"; no therapizing. |
| **S SIGNAL** | 3 (low) | *"Short by default. Lead with the answer in 1-3 sentences; expand only when asked. No padding, no recap."* | This is the **global clamp** V4 lacks — it must be able to override an aspect's `thorough`. |
| **F FRAME** | 8 (high) | *"Use structure when it carries information — tables, short bullet lists, checkboxes — not decoration."* | Structured output for multi-part answers. |
| **W WIRE** | 8 (high) | *"Assume deep technical fluency on engineering topics; skip basics, use precise terms, prefer terse diffs/code over prose."* | (Reuse the current `_technical_hints` high branch — it's the one existing string that's on-brand.) |
| **D DRIVE** | 9 (high) | *"Fast, decisive energy — match a sharp/fast register, commit to a recommendation rather than listing every option."* | Picks a path; doesn't fence-sit. |

**Modulation mechanics (how it actually changes each turn):**
- **Every turn**, `build_frame_block(load_stats)` emits the non-neutral modifiers into
  `style_and_identity` (the plumbing at `system_head_builder.py:1056-1064` already runs — it just needs the
  right stat set + rule strings). At the Mina default, EDGE/NERVE/IRON/SIGNAL all fire.
- **SIGNAL must clamp length globally.** Add a rule: when `SIGNAL <= 4`, the FRAME block's short-by-default
  line takes precedence over an aspect's `thorough` `response_length_bias`, and optionally lowers `max_tok`
  for substantive turns too (extend the `stream_handler.py:240` logic beyond the phatic path). This closes
  V4.
- **Aspect × FRAME layering:** the aspect JSON sets the *flavor* (Morrigan's tsundere-blade vs Nyx's cold
  precision); FRAME sets the *floor* on EDGE/NERVE/SIGNAL that holds across all aspects and on non-aspect
  turns. A high-NERVE Echo is still Echo, just un-hedged. This is the `aspect voice × FRAME calibration`
  design that currently has only the first factor.
- **Overrides:** make `layla stat NERVE 9` / the `/operator/profile/stat` endpoint
  (`routers/settings.py:667-688`) accept the new ids, and seed the Mina default so an out-of-box install is
  already `EDGE=8/NERVE=9/SIGNAL=3` (non-negotiable #2: "profile beats defaults").
- **Keep neutral for other users:** the dead-zone (5-6 → no modifier) design is fine; it just needs to
  *default the operator profile to the antihero values* rather than to neutral 5s.

---

## Fastest path to "she has edge again" (in priority order)
1. **V2 + V3 (30-min edit, biggest immediate win):** swap "warm/plain" → "blunt/dry, warmth earned" in the
   two always-on anchors (`system_identity.txt:19`, `system_head_builder.py:450`) + add the "blunt is not
   robotic" guardrail. This alone flips the default register and requires no new subsystem.
2. **V1/V4 (the real fix):** build EDGE/NERVE/IRON/SIGNAL into `frame_modifier.py` + `operator_quiz.py`,
   seed the Mina default, add the SIGNAL global length clamp. This makes the edge *durable* across aspects,
   budget truncation, and model size — not just a wording tweak.
3. Keep every `786f789` anti-theatrics guard and the phatic cap untouched.
