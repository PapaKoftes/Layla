# Layla Evolution Layer — Full Implementation Plan

**From:** Topic-based autonomous executor  
**To:** Multi-domain adaptive capability-building system with persistent identity, self-directed growth, and long-term evolution.

**Primary objective:** Layla must improve herself across disciplines over time — not just learning topics, but growing capabilities.

---

## Table of Contents

1. [Vision and Architecture](#1-vision-and-system-architecture)
2. [Data Models](#2-data-models)
3. [System 1: Capability Growth Model](#3-system-1-capability-growth-model)
4. [System 2: Persistent Competence Layer](#4-system-2-persistent-competence-layer)
5. [System 3: Adaptive Growth Scheduler](#5-system-3-adaptive-growth-scheduler)
6. [System 4: Style Identity System](#6-system-4-style-identity-system)
7. [System 5: Reflection Loop](#7-system-5-reflection-loop)
8. [System 6: Cross-Domain Reinforcement](#8-system-6-cross-domain-reinforcement)
9. [System 7: Mission Chaining](#9-system-7-mission-chaining)
10. [System 8: Identity Stability](#10-system-8-identity-stability)
11. [System 9: Growth Safety](#11-system-9-growth-safety)
12. [System 10: Scalability](#12-system-10-scalability)
13. [Integration Requirements](#13-integration-requirements)
14. [Migration Strategy](#14-migration-strategy)
15. [Implementation Phases](#15-implementation-phases)

---

## 1. Vision and System Architecture

### 1.1 Shift in Paradigm

| Before | After |
|--------|--------|
| Study plans = list of topics | Capabilities = domains with level, trend, decay risk |
| Scheduler = "oldest topic first" | Scheduler = priority by urgency, decay, balance |
| Outcome = "last studied" timestamp | Outcome = growth state (strong / improving / weakening / stagnating) |
| No explicit style | Style profile: writing, coding, reasoning — reinforced over time |
| Missions are one-shot | Missions can chain: study → research → apply → reflect |
| Identity = static prompts | Identity = persistent anchors + evolution guardrails |

### 1.2 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LAYLA EVOLUTION LAYER                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  IDENTITY STABILITY          GROWTH SAFETY           SCALABILITY             │
│  (anchors, guardrails)       (balance, diversity)    (modular, lightweight)  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐           │
│  │ Capability      │    │ Persistent      │    │ Style Identity  │           │
│  │ Growth Model    │───▶│ Competence      │◀───│ System          │           │
│  │ (domains, level)│    │ Layer           │    │ (profile, drift) │           │
│  └────────┬────────┘    │ (score, decay)  │    └────────┬────────┘           │
│           │             └────────┬────────┘             │                    │
│           │                      │                       │                    │
│           ▼                      ▼                       ▼                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │              ADAPTIVE GROWTH SCHEDULER                               │    │
│  │  (urgency, reinforcement, diversification, stagnation detection)    │    │
│  └──────────────────────────────┬──────────────────────────────────────┘    │
│                                 │                                             │
│           ┌─────────────────────┼─────────────────────┐                       │
│           ▼                     ▼                     ▼                       │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐             │
│  │ Reflection   │    │ Cross-Domain     │    │ Mission          │             │
│  │ Loop         │    │ Reinforcement    │    │ Chaining         │             │
│  │ (assess→     │    │ (dependencies,   │    │ (study→research→ │             │
│  │  act→reflect)│    │  synergy)        │    │  apply→reflect)  │             │
│  └──────────────┘    └──────────────────┘    └──────────────────┘             │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  EXISTING: wakeup | scheduler job | autonomous_run | DB | UI                 │
│  (no breaking changes; backward compatibility)                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Data Flow (Growth Cycle)

1. **Wakeup / Scheduler** → Ask Competence Layer: "What should Layla work on next?"  
2. **Scheduler** → Picks action from: reinforce weak, maintain strong, prevent decay, diversify.  
3. **Execution** → Study session, research mission, or applied task (existing `autonomous_run`).  
4. **Reflection** → After mission: evaluate outcome, update capability signals, update style profile.  
5. **Cross-Domain** → Some updates propagate to related capabilities (e.g. planning ↑ → coding outcomes).  
6. **Mission Chaining** → Optional: schedule follow-up (e.g. research → then apply in repo).  
7. **Safety** → Balance and diversity checks before/after; recovery if stagnation or over-specialization.

---

## 2. Data Models

### 2.1 Capability Domains (new table: `capability_domains`)

Defines the set of domains Layla can grow in. Stored once; referenced by `capabilities` (per-domain state).

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | e.g. `coding`, `system_design`, `communication`, `research`, `planning`, `writing`, `repo_understanding`, `problem_solving`, `strategic_thinking`, `self_maintenance` |
| `name` | TEXT | Human-readable name |
| `description` | TEXT | Short description for prompts/scheduling |
| `created_at` | TEXT | ISO timestamp |

**Seed rows:** Insert the canonical list at migration time; config or later migrations can add more.

### 2.2 Capabilities (new table: `capabilities`)

Per-domain growth state for Layla. One row per domain.

| Column | Type | Description |
|--------|------|-------------|
| `domain_id` | TEXT PK FK | References `capability_domains.id` |
| `level` | REAL | 0.0–1.0 (or 1–10 scale; normalize to 0–1 internally) |
| `confidence` | REAL | 0.0–1.0 |
| `trend` | TEXT | `improving` \| `stable` \| `weakening` \| `stagnant` |
| `last_practiced_at` | TEXT | ISO timestamp |
| `decay_risk` | REAL | 0.0–1.0 (derived or stored) |
| `reinforcement_priority` | REAL | 0.0–1.0 (higher = more urgent to reinforce) |
| `practice_count` | INTEGER | Number of practice sessions |
| `updated_at` | TEXT | Last update to this row |

**Indexes:** `last_practiced_at`, `reinforcement_priority`, `trend`.

### 2.3 Capability Events (new table: `capability_events`)

Log of events that affect capability state (practice, reflection, cross-signal).

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `domain_id` | TEXT | Which domain |
| `event_type` | TEXT | `practice` \| `reflection_up` \| `reflection_down` \| `cross_signal` \| `decay_tick` |
| `mission_id` | TEXT | Optional: link to mission/study/research id |
| `delta_level` | REAL | Change in level (e.g. +0.02) |
| `delta_confidence` | REAL | Change in confidence |
| `notes` | TEXT | Optional summary |
| `created_at` | TEXT | ISO timestamp |

**Use:** Audit trail and for computing trend / decay over time.

### 2.4 Style Profile (new table: `style_profile`)

Single-row or key-value store for Layla’s evolving style.

| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT PK | e.g. `writing`, `coding`, `reasoning`, `structuring` |
| `profile_snapshot` | TEXT | JSON: traits, examples, do/don’t (compact) |
| `last_reinforced_at` | TEXT | ISO timestamp |
| `drift_score` | REAL | 0.0–1.0 (0 = aligned, 1 = drifted) |
| `updated_at` | TEXT | ISO timestamp |

**Alternative:** One row per key; or single row with JSON object for all keys. Prefer one row per key for simple updates.

### 2.5 Mission Chain (new table: `mission_chains`)

Links missions (study → research → apply → reflect).

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID or short id |
| `parent_mission_id` | TEXT | Previous mission in chain (nullable for root) |
| `mission_type` | TEXT | `study` \| `research` \| `apply` \| `reflect` |
| `goal_summary` | TEXT | Short description |
| `outcome_summary` | TEXT | Filled after completion |
| `status` | TEXT | `pending` \| `running` \| `completed` \| `skipped` |
| `capability_domains` | TEXT | JSON array of domain_ids this mission targets |
| `created_at` | TEXT | ISO timestamp |
| `completed_at` | TEXT | ISO timestamp (nullable) |

### 2.6 Capability Dependencies (new table: `capability_dependencies`)

Which domains help which (for cross-domain reinforcement).

| Column | Type | Description |
|--------|------|-------------|
| `source_domain_id` | TEXT | Domain that, when improved, helps target |
| `target_domain_id` | TEXT | Domain that benefits |
| `weight` | REAL | 0.0–1.0 strength of influence |

**Example:** (planning, coding, 0.3), (research, writing, 0.2). Seed at migration; optionally configurable later.

### 2.7 Identity Anchors (new table or extend existing)

Persistent “must not change” or “evolve slowly” identity elements.

| Column | Type | Description |
|--------|------|-------------|
| `anchor_id` | TEXT PK | e.g. `values`, `refusal_rules`, `voice_core` |
| `content_hash` | TEXT | Hash of content for drift detection |
| `content` | TEXT | Actual anchor text (or path to file) |
| `updated_at` | TEXT | Last change |

**Integration:** Can live in DB or remain in `.identity/` with a small DB table that stores hashes and last check time.

### 2.8 Backward Compatibility: study_plans

**Keep** `study_plans` table and all existing columns. Add optional columns:

| Column | Type | Description |
|--------|------|-------------|
| `domain_id` | TEXT | Optional FK to capability_domains; NULL = legacy topic-only |
| `linked_capability_event_id` | INTEGER | Optional FK to capability_events after a study run |

Existing code paths (get_active_study_plans, update_study_progress, wakeup “oldest first”) continue to work. New scheduler can prefer capability-driven selection when `domain_id` is set and capabilities table is populated.

---

## 3. System 1: Capability Growth Model

### 3.1 Scope

- Extend “study” from topic-only to **domain + level + trend + decay + reinforcement**.
- Each capability domain has: level, confidence, trend, last_practiced, decay_risk, reinforcement_priority.

### 3.2 Data Schema

As in §2.1–2.2: `capability_domains` (seed list), `capabilities` (one row per domain).

### 3.3 Update Mechanics

- **After a study session** (existing `run_autonomous_study_for_plan` or new capability-aware study):
  - Resolve `topic` or `plan` to a `domain_id` (via mapping: topic string → domain_id, or plan.domain_id).
  - Insert `capability_events` row: event_type=`practice`, domain_id, mission_id (plan id or research mission id), delta_level/delta_confidence from reflection (or default small positive delta).
  - Update `capabilities`: level += delta_level (clamped 0–1), confidence updated, last_practiced_at = now, trend recomputed (see §4).

- **After a research mission:** Same idea: map mission “type” or tags to domain(s), record event, update capabilities.

- **Decay tick (scheduler or periodic):** For each capability, if `last_practiced_at` is older than decay threshold (e.g. 7 days), optionally apply a small negative delta or increase `decay_risk`; write `capability_events` event_type=`decay_tick`.

### 3.4 Integration with Existing DB

- New tables created in same `layla.db` via migrations in `jinx/memory/db.py` (e.g. `migrate_capabilities()` called from `migrate()`).
- No drop or rename of `study_plans`; add optional `domain_id` and event link columns with DEFAULT NULL.

### 3.5 Migration Path from study_plans

- **Phase 1:** Create `capability_domains` and `capabilities` with seed domains. Backfill `capabilities` with default level/confidence (e.g. 0.5) and last_practiced_at from `study_plans.last_studied` by mapping each plan’s topic to one domain (topic → domain mapping table or heuristic).
- **Phase 2:** When adding a new study plan via API, allow optional `domain_id`; when present, new scheduler uses capability logic. Old “min by last_studied” remains for plans without domain_id.
- **Phase 3:** Over time, all new plans get domain_id; legacy plans can be migrated in bulk or left as “topic-only” until retired.

---

## 4. System 2: Persistent Competence Layer

### 4.1 Purpose

Move from “last studied” to **growth state**: what Layla is strong at, improving, weakening, stagnating.

### 4.2 Scoring Model

- **Level (0–1):** Composite of practice_count, reflection deltas, and optional LLM self-assessment. Formula example:  
  `level = clamp(0.5 + sum(delta_level from events) / N, 0, 1)`  
  with decay applied when last_practiced is old.

- **Confidence (0–1):** How stable the self-assessment is (e.g. based on variance of recent deltas or number of successful practices).

- **Trend:**  
  - `improving`: recent (e.g. last 3) events have net positive delta_level.  
  - `stable`: small or zero net change.  
  - `weakening`: recent net negative or decay_risk high.  
  - `stagnant`: no practice for long time (e.g. > 14 days) or practice_count high but no recent gain.

- **Decay risk (0–1):**  
  - Increase with time since last_practiced (e.g. linear from 0 at 0 days to 1 at 30 days).  
  - Decrease when practice or positive reflection occurs.

- **Reinforcement priority (0–1):**  
  - Higher when: trend is weakening or stagnant, decay_risk high, level low.  
  - Lower when: trend improving and level high.  
  - Formula: e.g. `reinforcement_priority = 0.4 * (1 - level) + 0.3 * decay_risk + 0.2 * (1 if trend in (weakening, stagnant) else 0) + 0.1 * (1 if trend == improving else 0)`  
  Normalize to 0–1.

### 4.3 Decay Detection

- **When:** On scheduler tick or on wakeup (lightweight).  
- **How:** For each capability, compute days since last_practiced_at; if > decay_threshold_days (config, e.g. 7), set or increase decay_risk; optionally append capability_events event_type=decay_tick.  
- **Storage:** decay_risk column updated; trend may flip to weakening/stagnant.

### 4.4 Improvement Tracking

- Every practice and reflection writes to `capability_events`.  
- Trend and level are derived from recent events (e.g. last 10 or 20 events per domain).  
- Optional: store rolling aggregates (e.g. level_7d_ago) for “improved vs 7 days ago” in UI.

### 4.5 Reinforcement Logic

- **Reinforcement** = “schedule this domain for practice/maintenance.”  
- Used by Adaptive Growth Scheduler (§5): pick next action by reinforcement_priority, diversification, and balance rules.

---

## 5. System 3: Adaptive Growth Scheduler

### 5.1 Evolution

- **From:** Time-based execution (interval every N minutes, pick plan with oldest last_studied).  
- **To:** Priority-based development: strengthen weak, maintain strong, prevent decay, balance breadth.

### 5.2 Urgency Scoring

- **Inputs:** For each domain: reinforcement_priority, decay_risk, level, trend, last_practiced_at.  
- **Output:** Ordered list of (domain_id, urgency_score).  
  - urgency = f(reinforcement_priority, decay_risk, time_since_practice).  
  - Example: `urgency = reinforcement_priority * 0.5 + decay_risk * 0.3 + min(1, days_since_practice / 14) * 0.2`.

### 5.3 Reinforcement Logic

- **Strengthen weak:** Domains with level < 0.5 or trend weakening get higher urgency.  
- **Maintain strong:** Domains with level >= 0.7 but decay_risk > 0.3 get “maintenance” slot (e.g. shorter or less frequent practice).  
- **Prevent decay:** Domains with decay_risk > 0.6 get boosted urgency.  
- **Balance breadth:** Diversification rule: over a rolling window (e.g. last 5 scheduler runs), do not pick the same domain more than twice; if urgency is close, prefer a domain that wasn’t recently picked.

### 5.4 Diversification Rules

- **Config:** `scheduler_max_same_domain_in_window` (e.g. 2), `scheduler_window_runs` (e.g. 5).  
- **State:** Store last N scheduler choices (domain_id or plan_id) in memory or in a small table `scheduler_history`.  
- **Rule:** When choosing next plan, filter or down-rank domains that already appear max times in the window.

### 5.5 Stagnation Detection

- **Stagnant:** No improvement in level over last K events or no practice for long time.  
- **Action:** Increase reinforcement_priority for that domain; optionally trigger a “varied” practice (e.g. different sub-topic or research angle) to avoid repetition.

### 5.6 Integration with Existing Scheduler

- **Current:** `_scheduled_study_job` gets active study plans, picks `min(plans, key=last_studied)`, runs `run_autonomous_study_for_plan(plan)`.  
- **New (feature-flagged):** If config `scheduler_use_capabilities` is true and `capabilities` table has data:
  - Compute urgency for each domain that has an active study plan (or for all domains with a “default” plan).
  - Apply diversification and balance; pick top domain (or top plan linked to that domain).
  - Call same `run_autonomous_study_for_plan(plan)` or a thin wrapper that also records capability event and updates capabilities after run.
- **Fallback:** If no capability data or flag off, keep current “oldest last_studied” behavior.

---

## 6. System 4: Style Identity System

### 6.1 Purpose

Layla develops and maintains a consistent, evolving style across writing, coding, reasoning, and structuring — recognizable and improving, not random.

### 6.2 Style Profile Memory

- **Storage:** `style_profile` table (§2.4): key = `writing` | `coding` | `reasoning` | `structuring`, profile_snapshot = JSON (traits, do/don’t, 1–2 example snippets), last_reinforced_at, drift_score, updated_at.  
- **Usage:** Injected into system prompt or context when generating (e.g. “Writing style: …”, “Coding style: …”) so the model stays consistent.

### 6.3 Style Reinforcement

- **When:** After a mission (study/research/apply), optionally run a lightweight “style extraction” step: from the model’s output, extract 1–2 sentences that characterize style (or use fixed rubric).  
- **Update:** Compare to current profile; if aligned, append to “recent examples” and update last_reinforced_at; if new trait appears consistently, add to profile_snapshot.  
- **Frequency:** Not every mission — e.g. every N missions or when reflection loop runs, to avoid noise.

### 6.4 Style Drift Detection

- **Drift:** Current output (sample) is compared to profile (e.g. embedding similarity or keyword overlap). If below threshold, drift_score increases.  
- **Action:** If drift_score > 0.5, reinforce more aggressively (inject profile more strongly in next prompts or run a “style alignment” micro-task).

### 6.5 Convergence Rules

- **Remain recognizable:** Profile is updated slowly (e.g. moving average: new_snapshot = 0.8 * old + 0.2 * new).  
- **Improve over time:** Allow new “do” rules to be added when they recur; drop “don’t” that are no longer violated.  
- **Avoid randomness:** Do not replace profile with a single run; require multiple consistent samples before changing.

---

## 7. System 5: Reflection Loop

### 7.1 Flow

After any mission (study / research / execution):

**Assess → Act → Reflect → Adapt**

1. **Assess:** Evaluate outcome (success, partial, failure; quality score if available).  
2. **Act:** Update capability signals (which domains were used, delta_level/delta_confidence).  
3. **Reflect:** Optional short LLM call: “What did you get better at or worse at?” → parse into domain + direction.  
4. **Adapt:** Adjust future priorities (reinforcement_priority, or scheduler state); optionally enqueue follow-up mission (mission chaining).

### 7.2 Design

- **Trigger:** After `run_autonomous_study_for_plan`, after research mission completion, and optionally after important `/agent` runs (e.g. when allow_write/allow_run was used).  
- **Inputs:** Mission type, goal summary, outcome summary (from steps or last message), domain_id(s) if known.  
- **Outputs:**  
  - Rows in `capability_events` (practice or reflection_up/down).  
  - Updates to `capabilities` (level, confidence, trend, last_practiced_at, decay_risk, reinforcement_priority).  
  - Optional: next_mission suggestion (for chaining).

### 7.3 Lightweight vs Full Reflection

- **Lightweight:** No LLM; use heuristics: study completed → small positive delta for that domain; research completed → positive for research (+ maybe writing); apply completed → positive for coding/repo_understanding.  
- **Full:** One short LLM call with structured output (e.g. JSON: domains_improved, domains_weakened, one_sentence_reflection). Parse and write capability_events + update capabilities.

Start with lightweight; add full reflection behind a config flag.

---

## 8. System 6: Cross-Domain Reinforcement

### 8.1 Idea

Capabilities influence each other (e.g. better planning improves coding outcomes). When one domain is practiced or improved, related domains get a small positive signal.

### 8.2 Dependency Graph

- **Storage:** `capability_dependencies` (§2.6): source_domain_id, target_domain_id, weight.  
- **Seed:** e.g. (planning → coding, 0.3), (research → writing, 0.2), (system_design → coding, 0.2), (problem_solving → strategic_thinking, 0.2).  
- **Usage:** When domain A gets a positive event, for each (A, B, w) in dependencies, add a small event for B: event_type=cross_signal, delta_level = w * delta_A (capped).

### 8.3 Cross-Signal Updates

- On capability_events insert for domain A (practice or reflection_up), after updating capabilities for A, for each dependent B insert capability_events (event_type=cross_signal) and update B’s level/confidence with a small positive delta.  
- Do not create feedback loops: cross_signal does not trigger further cross_signals.

### 8.4 Synergy Rules

- **Optional:** “Synergy groups” (e.g. coding + repo_understanding + problem_solving): when two in the group are practiced in the same day, small bonus to the third.  
- Implement as a second table or as rules in code; keep simple first.

---

## 9. System 7: Mission Chaining

### 9.1 Goal

Enable closed-loop development: study → research → apply → reflect.

### 9.2 Mission Linking

- **Storage:** `mission_chains` (§2.5): parent_mission_id, mission_type, goal_summary, outcome_summary, status, capability_domains, created_at, completed_at.  
- **Creation:** When a study or research mission completes, reflection can create a follow-up: e.g. “research completed on X” → create child mission type=apply, goal_summary=“Apply findings from X in repo Y”.  
- **Linking:** When starting a mission, optionally pass parent_mission_id; when completing, set outcome_summary and status=completed.

### 9.3 Outcome-Driven Followups

- **Rule:** If reflection says “outcome suggests applying this” or “outcome suggests deeper research,” create next mission in chain and (optionally) schedule it in the same session or next scheduler run.  
- **API:** Optional `POST /mission_chains` or internal only; scheduler can “get next pending chain mission” when choosing work.

### 9.4 Capability-Driven Planning

- When choosing “what to do next,” scheduler can consider: not only urgency by domain, but “which chain is pending?” — prefer completing a chain (apply after research) when the chain’s domain has high reinforcement_priority.

### 9.5 Integration

- **Study:** After run_autonomous_study_for_plan, if plan is part of a chain, update chain row; reflection may create apply/research child.  
- **Research:** After research_mission completes, reflection may create apply mission; store in mission_chains.  
- **Apply:** Use existing /agent with goal from chain; on completion, reflection updates capabilities and may close chain or create reflect-only mission.

---

## 10. System 8: Identity Stability

### 10.1 Goal

Layla evolves without losing coherence: long-term identity persistence, behavioral consistency anchors, evolution guardrails.

### 10.2 Long-Term Identity Persistence

- **Existing:** `.identity/self_model.md`, personalities/*.json (aspects).  
- **Add:** Optional `identity_anchors` table or file-backed hashes: store checksums of core identity files; on startup or periodically, compare current hash to stored; if changed by something other than a deliberate update, log or alert.  
- **Content:** Values, refusal rules, core voice — stored in .identity/ or in DB; versioned or hashed.

### 10.3 Behavioral Consistency Anchors

- **Anchors:** Short statements that must stay true (e.g. “Never modify user files without approval”, “Respect robots.txt”).  
- **Storage:** In .identity/ or DB; loaded into system prompt or governance layer.  
- **Update policy:** Only via explicit flow (e.g. user or Lilith-aspect confirmation); not auto-updated by reflection.

### 10.4 Evolution Guardrails

- **Style:** Style profile updates are bounded (§6.5: moving average, require multiple samples).  
- **Capabilities:** Level/confidence updates are bounded (deltas capped per event; no single run can flip level from 0 to 1).  
- **Identity:** Anchors are not overwritten by reflection; only additive learnings (e.g. “user prefers X”) that don’t conflict with anchors.

---

## 11. System 9: Growth Safety

### 11.1 Risks

- Runaway loops (same domain every run).  
- Over-specialization (one domain at 1.0, others at 0.2).  
- Stagnation traps (repeated practice with no improvement).

### 11.2 Balance Enforcement

- **Rule:** If any domain’s level exceeds the median level by more than threshold (e.g. 0.3), reduce its reinforcement_priority slightly so scheduler favors others.  
- **Config:** `scheduler_balance_threshold` (e.g. 0.3).

### 11.3 Diversity Checks

- **Rule:** Scheduler diversification (§5.4): no domain wins more than N times in last M runs.  
- **Rule:** Minimum breadth: over last K runs, at least D different domains must have been practiced (e.g. D=3, K=10).

### 11.4 Recovery Strategies

- **Stagnation:** If a domain has trend=stagnant for too long (e.g. 5 runs), try “varied” practice (different sub-topic or switch to research instead of study for that domain).  
- **Over-specialization:** Temporarily boost reinforcement_priority for low-level domains.  
- **Runaway:** If same domain_id appears in scheduler_history more than max, force pick next by urgency from a different domain.

---

## 12. System 10: Scalability

### 12.1 More Domains

- **Modular capability system:** Domains are rows in `capability_domains`; adding a domain = insert row + insert default row in `capabilities`. No code change if scheduling and reflection use domain_id generically.  
- **Config:** Optional `runtime_config.json` list of active_domain_ids to limit which domains participate in scheduling (for testing or focus).

### 12.2 Longer Timelines

- **Lightweight updates:** Capability_events and capabilities updates are single-row or batch of inserts; no heavy aggregation on every tick.  
- **Pruning:** Optional: archive or aggregate old capability_events (e.g. keep last 100 per domain) to keep table small.  
- **Trend/level:** Computed from recent events (e.g. last 20) so computation stays O(1) per domain.

### 12.3 More Missions

- **Mission chains:** mission_chains table is append-heavy; index on status and parent_mission_id for “next pending” queries.  
- **Scheduler history:** Keep last N runs in memory or small table; no unbounded growth.

### 12.4 Future UI Expansion

- **API:** Expose GET `/capabilities`, GET `/capability_domains`, GET `/mission_chains` (optional), GET `/style_profile`.  
- **UI:** Dashboards for “growth state,” “trend,” “next suggested,” “style drift” can be added later without changing core logic; all data is in DB.

---

## 13. Integration Requirements

### 13.1 Wakeup Flow

- **Current:** GET /wakeup → touch_activity, get_active_study_plans, run one study (min by last_studied), log_wakeup, return greeting + active_plans.  
- **New:**  
  - Optionally call Competence Layer “what’s my growth state?” for greeting (“You’re strong in X, improving in Y, consider reinforcing Z”).  
  - When choosing which plan to run on wakeup: if capability-aware, use same urgency + diversification as scheduler; else keep min(last_studied).  
  - No breaking change: if capabilities disabled or empty, behavior unchanged.

### 13.2 Scheduler

- **Current:** Interval job → get_active_study_plans, min by last_studied, run_autonomous_study_for_plan(plan).  
- **New:** Feature-flagged capability-aware selection (§5.6); after run, record capability_events and update capabilities; optionally run reflection.  
  - shared_state.run_autonomous_study remains the same; caller (scheduler) can wrap with “before/after” capability bookkeeping.

### 13.3 autonomous_run

- **No change** to autonomous_run signature or core loop.  
- **Hooks:** Optional: when a run completes, a “post_run” callback or event can be used by the evolution layer to trigger reflection and capability updates. That can be implemented in the router or in a thin wrapper that calls autonomous_run then runs reflection.

### 13.4 DB

- **Single DB:** All new tables in layla.db; migrations in jinx/memory/db.py.  
- **Existing tables:** study_plans, learnings, wakeup_log, audit, aspect_memories unchanged except optional new columns on study_plans (domain_id, linked_capability_event_id).

### 13.5 UI

- **Current:** Study plans list, wakeup greeting.  
- **New (additive):** Optional “Capabilities” or “Growth” section that reads from GET /capabilities; optional “Style” or “Identity” view.  
- **Backward compatibility:** Existing study_plans API and UI keep working; new endpoints are additive.

### 13.6 Backward Compatibility Summary

- All existing APIs and behaviors remain.  
- New behavior gated by config (e.g. `scheduler_use_capabilities`, `reflection_enabled`, `style_profile_enabled`).  
- study_plans remain the source of “what to study”; capability tables add a layer of “why this next” and “how am I growing.”

---

## 14. Migration Strategy

### 14.1 Phase 1 — Schema and Seed (no behavior change)

- Add migrations: create capability_domains, capabilities, capability_events, capability_dependencies, style_profile, mission_chains, scheduler_history (if used).  
- Seed capability_domains with canonical list.  
- Seed capability_dependencies with initial edges.  
- Backfill capabilities: one row per domain, level=0.5, confidence=0.5, trend=stable, last_practiced_at=NULL, decay_risk=0.5, reinforcement_priority=0.5.  
- Optional: map existing study_plans.topic to domain_id and set study_plans.domain_id; backfill capabilities.last_practiced_at from study_plans.last_studied for those.

### 14.2 Phase 2 — Competence and Scheduler

- Implement scoring and trend/decay/reinforcement_priority updates in a new module (e.g. jinx/memory/capabilities.py).  
- Implement scheduler selection with feature flag: when enabled, use urgency + diversification; else keep current logic.  
- After each scheduled study run: record capability_events (practice), update capabilities.  
- Wakeup: optionally use same selection; optionally add “growth state” line to greeting.

### 14.3 Phase 3 — Reflection and Cross-Domain

- Add reflection (lightweight first): after study/research, update capabilities from domain_id and outcome.  
- Add cross-domain: on capability_events insert, apply dependency graph and write cross_signal events.  
- Optional: full reflection (LLM) behind flag.

### 14.4 Phase 4 — Style and Identity

- Add style_profile table usage: load into context when generating; implement reinforcement and drift detection (lightweight).  
- Add identity anchor checks (hash comparison on .identity/ or key content); log only, no auto-rewrite.

### 14.5 Phase 5 — Mission Chaining and Safety

- Add mission_chains: create rows when reflection suggests follow-up; scheduler can pick “next in chain.”  
- Add balance, diversity, and recovery rules to scheduler and reflection.  
- Expose GET /capabilities (and related) for future UI.

### 14.6 Rollback

- Feature flags allow turning off capability-aware scheduler, reflection, style, chaining.  
- If tables are unused, they can remain; no drop of study_plans or existing columns.

---

## 15. Implementation Phases (Summary)

| Phase | Deliverables | Risk |
|-------|--------------|------|
| **1** | Schema, seed domains/dependencies, backfill capabilities; optional study_plans.domain_id | Low |
| **2** | Competence scoring (level, trend, decay, reinforcement_priority); scheduler urgency + diversification; record events after study | Medium |
| **3** | Reflection (lightweight + optional LLM); cross-domain dependency updates | Medium |
| **4** | Style profile storage, injection, reinforcement, drift detection; identity anchor hashes | Low |
| **5** | Mission chains (create/link/complete); balance and diversity rules; GET /capabilities | Medium |
| **6** | UI expansion (growth state, style); full reflection default-on; tuning and observability | Low |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6. Each phase is shippable and backward compatible.

---

*End of Evolution Layer Implementation Plan. Focus: clarity, modularity, evolvability; end goal: long-term autonomous growth toward multi-domain mastery with a consistent, evolving identity.*
