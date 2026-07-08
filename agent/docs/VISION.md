# LAYLA: Full Gap Closure & Product Unification Plan

> **Status**: Approved. Implementation begins next development cycle.
>
> **Context**: After completing three major architecture plans (Frontend ES Module
> Rearchitecture, Maturity System Wiring, Backend Service Reorganization), a full
> product analysis revealed that Layla's engineering is 85-90% complete but the
> *product experience* is 60-65%. The gap is the difference between "all systems
> work" and "using Layla feels like having a companion that grows with you."
>
> **Core mission**: Transform Layla from "an advanced local AI platform" into
> "a coherent living companion experience."

---

## Phase 0: Rules for All Future Development

These rules apply to ALL work going forward. No exceptions.

### Rule 1: No New Major Systems

Do not add new memory types, planning engines, frameworks, UI tabs, or
infrastructure layers until existing systems feel unified. The codebase has
13 active subsystems. They need connection, not company.

### Rule 2: Every System Must Produce Felt User Impact

If a subsystem exists, the user must *feel* it — not just technically have it.

- XP exists → user must emotionally notice growth
- Memory exists → recall must feel natural, not robotic
- Curiosity exists → Layla must proactively surface discoveries

### Rule 3: Companion First, Workstation Second

UI priority order: warmth, clarity, continuity, discoverability, power-user depth.
NOT: subsystem exposure, diagnostics, dashboards everywhere.

### Rule 4: Progressive Disclosure Everywhere

Beginner users see: conversation, relationship, memory moments, simple actions.
Advanced systems emerge gradually through usage, trust, and rank.

---

## Phase 1: Experience Unification (Highest Priority)

**Goal**: Connect all existing engines into one coherent living experience.

### 1.1 Companion Runtime Layer

Create a central orchestration layer that unifies personality state, emotional
context, ongoing goals, relationship state, curiosity priorities, and long-term
continuity. Everything routes through this layer — it becomes "Layla's living state."

**Location**: `services/companion/`

| Module | Purpose |
|--------|---------|
| `emotional_state.py` | Track conversational tone, stress signals, rapport level |
| `continuity_manager.py` | Unresolved topics, recurring interests, unfinished plans |
| `initiative_manager.py` | Orchestrate soft/curiosity/care initiative classes |
| `relationship_context.py` | Surface relationship history into conversation context |
| `lived_experience.py` | Aggregate all state into a single "living state" snapshot |

### 1.2 Continuity Memory

Add a memory layer for:
- Unresolved topics ("did you ever finish the CNC optimization?")
- Emotional callbacks ("you seemed stressed yesterday")
- Recurring interests ("you mentioned wanting to learn German")

This is the *real* companion layer — what makes Layla feel like she remembers
your life, not just your data.

### 1.3 Passive Initiative Engine

Three initiative classes:

| Type | Examples | Feel |
|------|----------|------|
| **Soft** (reminders) | Check-ins, resurfacing, callbacks | Warm, attentive |
| **Curiosity** (research) | Overnight research, related discoveries, generated insights | Surprising, valuable |
| **Care** (wellbeing) | Workload awareness, stress detection, routine recognition | Protective, rare |

**Critical**: Initiative must feel contextual, rare enough, earned, and never
spammy. This is not a notification system.

### 1.4 Emotional Presence Layer

Personality must affect behavior, not just prompt adjectives:
- More reserved after conflict
- Warmer after long-term trust
- Different response pacing and initiative frequency
- Changing humor style based on evolved relationship

---

## Phase 2: Growth System Rework

**Goal**: Make progression feel real, not mechanical.

### 2.1 Rank Unlock Architecture

| Rank | Unlock | User Perception |
|------|--------|-----------------|
| 0 | Reactive assistant | Cautious, responsive |
| 1 | Proactive reminders | Starts offering unsolicited tips |
| 2 | Independent curiosity | Researches things on her own |
| 3 | Relationship synthesis | References emotional patterns |
| 4 | Autonomous learning sessions | Studies topics overnight |
| 5+ | Long-term project stewardship | Manages ongoing work independently |

Users should *notice* evolution — not check a dashboard for it.

### 2.2 Visible Growth Moments

Add:
- Milestone conversations ("I've been learning from you for 100 hours")
- Reflection moments ("here's what I've noticed about how you work")
- Memory anniversaries ("a month ago you started the CNC project")
- "Things I've learned about you" summaries

Growth must feel emotional and relational, not gamified.

### 2.3 XP Rebalance

Current system too slow for casual use. Add weighted quality bonuses:
- Long-term consistency bonuses
- Project completion bonuses
- Teaching moments (user explains something)
- Collaborative planning rewards

---

## Phase 3: UI/UX Restructure

**Goal**: Transform from "AI workstation" to "living companion interface."

### 3.1 Radical UI Simplification

Default experience: minimal. Advanced systems: contextual expansion only.

Primary view: conversation + subtle contextual cards.
Right panel: collapsible companion space (not a control panel).

### 3.2 Replace Dashboard Mentality

Remove excessive metrics and debug-heavy visibility. Replace with:
- Narrative summaries ("Layla has learned 47 things about your work")
- Relationship continuity ("you've been talking more about robotics lately")
- Memory moments ("remember when you solved the threading bug?")
- Active projects and ongoing interests

### 3.3 Information Hierarchy

Priority order:
1. Current conversation
2. Ongoing relationship
3. Active goals/projects
4. Recent memories
5. Proactive insights
6. Advanced systems/tools

### 3.4 Redesign Onboarding

Current onboarding is technical (hardware detection first). New sequence:

1. "What should I call you?"
2. "What do you want help with most?"
3. "What kind of presence do you prefer?" (quiet / curious / proactive / analytical / emotional)
4. Hardware detection happens silently in the background

This changes first impression, emotional framing, and perceived identity.

### 3.5 Progressive Disclosure

New users see almost nothing. Features unlock through usage, trust, rank,
and context relevance. Solves overwhelm.

---

## Phase 4: Memory & Learning Pipeline Completion

**Goal**: Make learning feel alive and autonomous.

### 4.1 Complete Verification Loop

Full chain: ingest → extract → classify → verify → ask user confirmation →
commit to memory/wiki → resurface naturally later.

### 4.2 Conversational Learning Confirmation

Replace silent ingestion with natural verification:
> "I noticed this file relates to your CNC workflow. Should I connect it
> to your optimization project notes?"

Creates trust, visibility, and companionship.

### 4.3 Long-Term Interest Modeling

Build a persistent interest graph tracking: recurring subjects, passions,
abandoned projects, skill trajectories. Powers initiative, recommendations,
and emotional continuity.

---

## Phase 5: Multi-Device & Cluster Productization

**Goal**: Turn engineering achievement into usable feature.

### 5.1 Pairing UX

Consumer flow: Desktop shows "Pair Device" → Phone scans QR → Done.
No manual configs.

### 5.2 Device Identity

Layla understands desktop vs mobile context, adapts behavior by device
capabilities and availability.

### 5.3 E2E Cluster Validation

Full test matrix: phone+desktop, laptop+desktop, intermittent connectivity,
model handoff, sync conflicts, task recovery.

---

## Phase 6: Performance & Resource Intelligence

**Goal**: Make Layla feel smooth and alive.

### 6.1 Governor Wiring

Governor should control: inference depth, background jobs, initiative frequency,
consolidation timing, embedding priority, idle learning.

### 6.2 Model Thrashing Prevention

Implement hysteresis windows, cooldown timers, and activity smoothing to prevent
rapid load/unload cycles.

### 6.3 Background Intelligence Scheduler

During idle: memory consolidation, research, relationship synthesis, spaced
repetition, summarization, curiosity exploration. Critical for "living entity"
perception.

---

## Phase 7: Relationship System Expansion

**Goal**: Make relationships visible and meaningful.

### 7.1 People & Relationship Space

Add a People panel showing: known people, relationship summaries, important
memories, interaction evolution, emotional associations.

### 7.2 Relationship Reflection

Examples of natural relationship awareness:
- "You mention Edgar often lately"
- "Your tone changes when discussing work"
- "You seem excited about CNC optimization again"

---

## Phase 8: Testing Evolution

**Goal**: Test experiences, not just functions.

### 8.1 Full Journey Tests

Mandatory flows: onboarding → first conversation → memory creation → recall →
initiative → relationship continuity → growth unlock → autonomous learning.

### 8.2 Companion Consistency Tests

Test: personality persistence, emotional continuity, memory coherence,
initiative quality, growth progression.

---

## Phase 9: Deployment & Distribution

**Goal**: Become installable by normal humans.

### 9.1 One-Click Installer

Windows installer with model manager, dependency bootstrap, GPU detection,
and onboarding launcher.

### 9.2 Docker + Portable Modes

Developer mode, portable local mode, consumer installer mode.

### 9.3 CI/CD

Automated tests, release validation, migration validation, packaging verification.

---

## Phase 10: Architectural Cleanup

**Goal**: Reduce future entropy.

### 10.1 Split infrastructure/ Dumping Ground

Current 65-file catch-all → split into: runtime, integrations, orchestration,
utilities, platform.

### 10.2 Generalize Specificity Leaks

Files like `german_mode.py` should be abstracted into a general language
learning framework.

### 10.3 Reduce Shim Surface

Plan gradual deprecation of backward-compat shims with migration windows
and compatibility tracking.

---

## Target State

The end state: a persistent local intelligence that remembers naturally, grows
visibly, initiates meaningfully, evolves relationally, learns autonomously,
feels emotionally continuous, stays private, lives across devices, and becomes
more valuable over time.

NOT "a giant local AI control panel."

That distinction is the entire future of the project.

---

## Current Architecture Snapshot (Post-Rearchitecture)

| Metric | Value |
|--------|-------|
| Python LOC | ~24,270 |
| JavaScript LOC | ~12,870 |
| API Endpoints | 363 |
| SQLite Tables | 49 |
| Service Subdirectories | 19 |
| Real Service Modules | 216 |
| Backward-Compat Shims | 204 |
| Tests (collected) | 2,936 |
| Agent Loop | 910 lines (down from 1,574) |
| Inference Backends | 4 (llama.cpp, Ollama, OpenAI, LiteLLM) |
| Aspects | 6 (Morrigan, Nyx, Echo, Eris, Cassandra, Lilith) |
| Memory Types | 4 (episodic, semantic, relationship, working) |

## Readiness Assessment

| Dimension | Score | Primary Gap |
|-----------|-------|-------------|
| Architecture | 90% | None |
| Memory/Learning | 85% | Verification loop disconnected |
| Personality/Growth | 70% | Rank unlocks don't gate behavior |
| Autonomous Agency | 75% | Proactive initiative not wired |
| Multi-Device | 60% | Never tested E2E |
| Relationship/Dignity | 80% | Relationship visibility missing |
| UI/UX Warmth | 65% | Too complex, onboarding too technical |
| Privacy/Local-First | 95% | None |
| Testing | 85% | No E2E user journey test |
| Deployment | 40% | No installer, requires dev setup |
| **Overall** | **~75%** | Experience cohesion |
