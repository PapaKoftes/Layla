# delta-critic.md — What the audit MISSED (completeness critic addendum)

**Method:** Read all 10 audit reports, then independently probed the codebase for
classes of defect the mappers under-weighted. The mappers did excellent *breadth* work
(they enumerated ~18 unsurfaced routers and the FRAME/title/onboarding gaps thoroughly).
Their blind spot is uniform: **they trusted that the backends behind the "HEADLINE
unsurfaced" routers are real and merely need a UI door.** For several flagship
intelligence-tier features that assumption is false — the store is never *written*, the
feature is *gated dead by a phase-name typo*, or the config flag that turns it on is
*read nowhere that matters*. Building the UI they recommend would surface empty panels.

Every claim below was verified in-tree (file:line cited). These are **net-new** — not
restatements of delta-gaps H1–H14.

---

## The one-paragraph story the mappers missed

delta-gaps found H11 ("relationship/timeline stores only fill on context overflow") and
H10 ("voice-evolution ladder dead on a phase/key mismatch") — but treated each as a
one-off. They are instances of **two systemic classes** that recur across the
intelligence tier: **(A) write-path-never-fires** — the read endpoint and store exist,
but nothing in a normal turn ever populates them (skill-acquisition, mood, automation);
and **(B) phase-name-mismatch dead gates** — the maturity engine emits
`awakening/attunement/resonance/sovereignty/transcendence`, but at least **three**
separate runtime gates test against the *wrong* names (`nascent`, `adept`, `veteran`,
`transcendent`), silently disabling the feature behind them. delta-gaps caught exactly
one gate (voice_evolution). It missed the other two, which kill **proactive initiative**
and **observation-mode**, both of which the vision treats as signature. On top of that,
a whole setup-checklist feature ("Proactive initiative") flips config flags that lead to
one of those dead gates — a config-key-with-no-effect the mappers never checked.

---

## C1 — Skill Acquisition (BL-238) never acquires: `acquire_from_run` has zero callers

**HEADLINE, and worse than "unsurfaced."** state-backend-wiring lists `learned_skills`
(`/skills/learned`) as row #4, severity HEADLINE, remediation "build a panel." But the
mechanism that makes the store non-empty — `skill_acquisition.acquire_from_run(state)`,
which turns a finished run's successful tool steps into a learned skill
(`services/skills/skill_acquisition.py:69`) — is **called from nowhere** except the
manual `POST /skills/learned/acquire` router. Verified: `grep acquire_from_run` across
`services/ layla/` (excluding the router + its own def) returns **zero** hits. No
post-run hook, no scheduler job, no outcome-writer path calls it. So Layla never learns
a skill "from what she actually did" — the store is permanently empty in normal use, and
the recommended read-only panel would render nothing. This is the H11 pattern
(write-path-dead) for a feature the mappers didn't flag as write-dead.
**Fix:** call `acquire_from_run(state)` from the successful-multi-step-run path
(next to `_save_outcome_memory` in `outcome_writer.py`), gated on a flag, min 2 steps.

## C2 — Proactive initiative is dead at runtime: phase-name typo in the gate

**HEADLINE. Distinct bug from H10.** The per-turn "Layla suggests a next step on her
own" surface is gated at `services/agent/reasoning_handler.py:333-334`:

```python
ms = _get_maturity_state()
if ms.phase in ("adept", "veteran", "transcendent"):
    ... maybe_append_inline_suggestion(...)
```

The maturity engine's `PhaseId` is
`Literal["awakening","attunement","resonance","sovereignty","transcendence"]`
(`services/personality/maturity_engine.py:25`). **`adept`, `veteran`, and
`transcendent` are not valid phases** — `transcendent` ≠ `transcendence`. The `in (...)`
test can never be true, so `maybe_append_inline_suggestion` is unreachable **regardless
of the `inline_initiative_enabled` flag**. The entire inline-initiative UX (the vision's
"initiative model," North Star §10) is dead behind a string-mismatch, exactly like
voice_evolution (H10) but for a *different* feature the mappers reported as merely
gated-off-by-config. **Fix:** change the tuple to the real high phases
`("resonance","sovereignty","transcendence")`.

## C3 — Observation/trial mode is dead at runtime: same phase-name typo

**Distinct third instance.** `services/agent/llm_decision.py:249-278` implements
"observation mode (trial phase)" — in early maturity, bias the decision toward
`reason`/learn over tool-use unless the operator explicitly asked for action.
`observation_mode_enabled` **defaults to `True`** (`:249`), so this is intended-on. But
the gate is `if ms.phase == "nascent":` (`:253`) — and `nascent` is **not** a maturity
phase (the real first phase is `awakening`). So the cautious "first-contact" behavior the
vision describes for new users (intent-ux §5.1: awakening = "cautious, explicit about
uncertainty") **never activates**. A brand-new install gets none of the intended
early-phase restraint. **Fix:** `if ms.phase in ("awakening","attunement"):`.

> C2+C3+H10 together prove the phase-name mismatch is systemic, not a one-off. A grep for
> the literal wrong names (`nascent|apprentice|adept|veteran`, `transcendent` as a bare
> word) across `services/*.py` is the correct sweep the audit should have run — it surfaces
> exactly these three dead gates plus the voice_evolution JSON keys.

## C4 — "Proactive initiative" setup feature flips flags that lead only to the dead C2 gate

**Unwired setting / config-key-with-no-effect.** The setup checklist offers a
first-class feature: `{"id": "initiative", "label": "Proactive initiative", "flags":
{"initiative_engine_enabled": True, "inline_initiative_enabled": True}, "unlocks":
"Layla suggests next steps on her own"}` (`install/setup_profiles.py:45-46`). A user who
checks this box (or picks a profile that pre-seeds it) gets **both** flags set — and
**nothing happens**, because the only per-turn consumer of those flags is the
phase-typo-dead gate in C2. The advertised "unlocks" is false. This is a settings key
with no runtime effect — a class (#3) the mappers didn't probe at all. Fixing C2 also
fixes C4.

## C5 — Emotional presence (BL-190 mood) is double-dead: flag-off by default AND never nudged

**HEADLINE. state-backend-wiring row #7 ("build a mood panel") understates it.** Two
independent reasons mood never affects anything:
1. **Injection is flag-gated off.** `system_head_builder.py:896` injects `mood_hint()`
   only `if cfg.get("emotional_presence_enabled")` — and that key is **set nowhere**
   (not in `runtime_config.json`, `runtime_config.example.json`, `runtime_safety.py`, or
   any profile), so it defaults falsy. Mood never reaches the prompt.
2. **The store is never written in normal use.** The only caller of `register_signal`
   (which moves the mood) is `answer_feedback.py:95` — i.e. mood only changes when the
   user clicks 👍/👎. But the feedback affordance itself has **no UI** (state-backend-wiring
   row #8: `/feedback` is unsurfaced). So in the shipped product mood is *never* nudged
   *and* never injected. A mood panel would show a permanently-neutral value.
**Fix:** add `emotional_presence_enabled` to the default config (or a profile), and
register mood signals from the turn loop (praise/correction detection already exists in
`outcome_writer._auto_extract_learnings`), not only from the unsurfaced thumbs UI.

## C6 — Event-driven automation (BL-233) has exactly one trigger source

**Scoped-to-uselessness, not "just needs a rule-builder UI."** state-backend-wiring row
#11 frames `automation.py` as a full "if-this-then-that rule engine" needing a UI to
*view/create* rules. But the engine can only ever fire on **one** event type:
`dispatch_event(...)` is called from exactly one non-router, non-test site —
`knowledge_watcher.py:277` `dispatch_event("file_modified", {...})`. No turn-completed,
goal-created, session-start, mission-done, or rank-up event is ever emitted. So even with
a rule-builder UI, the only automatable trigger is "a watched file changed." The feature
is a rule engine with a single wire into it. **Fix:** emit `dispatch_event` at the real
lifecycle seams (turn done, goal progress, rank-up) before/alongside building the UI.

## C7 — World State (BL-241) is a read-only snapshot with no consumer

**HEADLINE, but the framing "build a world panel" misses that it feeds nothing.**
`world_state.snapshot()` / `summarize()` (`services/workspace/world_state.py`) are
imported **only** by the router (`main.py` mounts it) — verified: no prompt builder, no
turn path, no other service imports `services.workspace.world_state`. The vision's "world
model" is meant to give Layla situational awareness (open projects, index, hardware, mode)
*that shapes her responses*; instead it is an inert `GET /world` that nothing reads and
nothing injects. Surfacing it as a dashboard is fine, but the **signature capability
(world-model-informed reasoning) does not exist** — the snapshot is never merged into any
system prompt. This is a "flattened/fake signature feature" (class #5), stronger than the
"unsurfaced" label the mappers gave it.

## C8 — The phase-name typo class means the maturity engine's OTHER phase gates need an audit

**Meta / preventive.** C2, C3, and H10 are three confirmed dead gates from the same root
cause (hand-typed phase-name string literals that drifted from the `PhaseId` enum). The
codebase has no single source of truth enforcing these strings (no `Phase` enum import at
the gate sites — they compare against raw string tuples). Any *future* maturity-gated
behavior is one typo away from silently dying, and there is **no test** asserting that
gate-site phase strings are a subset of `PhaseId`. **Fix:** export the `PhaseId` literals
as a checked constant and add a test that greps gate sites, or centralize maturity
comparisons behind helper predicates (`is_early_phase()`, `is_high_trust_phase()`).

---

## Ruled out (checked, not a gap — so the audit doesn't chase ghosts)

- **`multi_agent.py` is NOT a stub.** The memory-index note "2 fake placeholders
  (multi_agent)" is stale: `services/planning/multi_agent.py` is a real 455-line
  implementation (`decompose_task`, `dispatch_subtasks`, `aggregate_results`,
  `run_multi_agent`). Its gap is *reachability/gating* (already covered), not fakeness.
- **Onboarding does NOT auto-enable remote by itself.** delta-gaps H13 says completing
  the wizard flips `remote_enabled:true`. In the current `apply_setup`
  (`install/setup_profiles.py:180-203`) `remote_enabled:True` is set **only** if the user
  selects the "remote" feature (`:39-41`); `apply_setup` merges only chosen flags. H13 is
  true only if a *profile pre-seeds* the remote feature — worth re-verifying which profile
  does, but the wizard is not unconditionally flipping it. (Lower severity than H13 states.)
