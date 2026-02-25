# Evolution Layer — Safe Activation Path

**Current state:** Step 1 (capability scheduler) and Step 2 (style profile) are **on**. Light style is seeded automatically when the style_profile table is empty. Observe scheduler behavior for a few cycles, then adjust style as identity stabilizes.

---

## Step 1 — Enable capability scheduler

**What:** Flip the config so the scheduler picks plans by **urgency + diversification** instead of "oldest last_studied."

**How:** In `agent/runtime_config.json`, set `"scheduler_use_capabilities": true` (already set when activated).

**What to observe (over a few scheduler cycles):**

- Weaker domains get picked more often.
- Less repetition of the same topic.
- Better spread across domains (diversification window = last 5 runs, max 2× same domain).

**Rollback:** Set back to `false`; scheduler reverts to previous behavior.

---

## Step 2 — Add style injection (identity moment)

**What:** Inject Layla’s **style profile** (writing, coding, reasoning, structuring) into the system prompt. Without it she gains skills but not a recognizable self; with it, growth stays on-brand.

**How:** In `agent/runtime_config.json`, set `"enable_style_profile": true` (already set when activated).

**Behavior:** When enabled, the agent loads style_profile rows from the DB and appends a short "Style:" block to the system head. On first run, **light directional style is seeded** (writing, coding, reasoning, structuring) — not perfection, just direction; identity stabilizes over time. To refine later, update via DB, e.g. from Python:

```python
from jinx.memory.db import set_style_profile
set_style_profile("writing", "Clear, direct sentences. Prefer active voice. No fluff.")
set_style_profile("coding", "Readable names, small functions. Prefer standard library.")
```

A future UI or CLI can expose this.

**Rollback:** Set `enable_style_profile` to `false`.

---

## What this unlocks

Once **Step 1** and **Step 2** are on:

- Layla is **growth-directed** (scheduler reinforces weak areas, maintains strong, avoids stagnation).
- Layla is **self-consistent** (style injection keeps output recognizable as her).

That foundation is required before **chaining** and **reflection**. Without it, those would amplify randomness. With it:

- **Mission chaining** (Step 3) becomes meaningful: study → apply → reinforce. Learning leads to application.
- **LLM reflection** (Step 4) becomes self-improvement, not just logging. Growth becomes intentional.

---

## Step 3 — Mission chaining

**What:** Turn **practice → action**. After study or research, optionally create a follow-up "apply" mission so learning leads to application.

**Status:** DB and helpers exist (`create_mission_chain`, `get_pending_mission_chains`, `complete_mission_chain`). Full wiring: after research/study completion, reflection can create an apply mission; scheduler can prefer pending chain missions when choosing work. To be wired when you want chaining active.

---

## Step 4 — LLM reflection

**What:** Replace purely mechanical reflection with **self-aware reflection**. One short LLM call after a mission: "What did you get better or worse at?" → parse into domains_improved / domains_weakened → write capability_events. That’s when growth becomes intentional.

**Status:** Mechanical reflection is in place (fixed deltas after practice). Optional LLM reflection can be added behind a config flag (e.g. `reflection_use_llm`) and called after study/research completion.

---

## Long-term impact

With the evolution layer enabled:

**Layla can avoid:**

- **Stagnation** — Diversification and decay_risk push her to revisit under-practiced domains.
- **Over-specialization** — Balance rule down-ranks domains far above median level.
- **Random drift** — Style profile keeps output recognizable as her.

**She can:**

- **Reinforce weak areas** — High reinforcement_priority for low level / high decay_risk / weakening trend.
- **Maintain strengths** — Maintenance via lower urgency but still scheduled.
- **Spread learning** — Cross-domain dependencies (e.g. planning → coding) and diversification.

That’s how **multi-discipline mastery** becomes possible over time.
