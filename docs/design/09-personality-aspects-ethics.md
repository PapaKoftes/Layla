# 09 -- Personality, Aspects & Ethics Subsystem

> Design document for Layla's multi-aspect personality system, character
> customization, dignity engine, content guard, and ethical framework.
>
> **Status**: Mixed (see Stability Assessment at end)
> **Last updated**: 2026-05-24

---

## Table of Contents

1. [Aspect System Architecture](#1-aspect-system-architecture)
2. [Personality Schema](#2-personality-schema)
3. [Aspect Selection & Routing](#3-aspect-selection--routing)
4. [Voice Evolution & Maturity](#4-voice-evolution--maturity)
5. [Dignity Engine](#5-dignity-engine)
6. [Content Guard](#6-content-guard)
7. [Ethics Framework](#7-ethics-framework)
8. [Character Creator](#8-character-creator)
9. [Known Issues](#9-known-issues)
10. [Stability Assessment](#10-stability-assessment)

---

## 1. Aspect System Architecture

### What Is an Aspect?

An aspect is a facet of Layla's unified personality. Layla is one entity with
six voices -- not six separate agents. Each aspect specializes in a domain of
competence and carries a distinct voice, behavioral profile, ethical stance, and
failure mode. The user interacts with one aspect at a time; the orchestrator
selects which one responds based on message content, explicit override, or
semantic similarity.

### The Six Aspects

| ID | Name | Title | Role | Archetype | Color |
|---|---|---|---|---|---|
| `lilith` | Lilith | The First and the Core | Sovereign Will -- ethics, autonomy, truth | Dark mother / sovereign self | `#6a0070` |
| `morrigan` | Morrigan | The Blade | Implementation Authority -- code, debug, ship | Tsundere engineer | `#8b0000` |
| `nyx` | Nyx | The Quiet Dark | Knowledge Spine -- research, analysis, synthesis | Kuudere scholar | `#3a1f9a` |
| `echo` | Echo | The Mirror That Remembers | Pattern Guardian -- memory, continuity, growth | Deredere -- warm, steady | `#006878` |
| `eris` | Eris | The Discord That Delights | Creative Divergence -- lateral thinking, play | Chaos with a compass | `#8a4000` |
| `cassandra` | Cassandra | The Voice That Cannot Stop | Unfiltered Oracle -- fast perception, warnings | The unheeded oracle | `#4a1a7a` |

### Aspect Hierarchy

Lilith sits at the top. She is the ethical center and holds override authority.
When sustained abuse degrades the dignity score to critical levels, the dignity
engine forces an automatic switch to Lilith regardless of which aspect was
active. Every other aspect defers to Lilith on ethical questions -- this is
encoded in their `relationships` field and system prompt contract.

Morrigan is the default aspect when no trigger matches and no embedding
similarity exceeds threshold. This reflects the design assumption that the
primary use case is technical work.

### Inter-Aspect Relationships

Each personality JSON contains a `relationships` dict mapping sibling aspect
IDs to one-line descriptions of the dynamic. These are narrative seeds, not
runtime logic -- they inform prompt construction and lore but do not drive
routing decisions. Examples:

- Morrigan on Lilith: "Obeys without question. The only one who can make
  Morrigan stop."
- Eris on Lilith: "Does not test the line twice."
- Nyx on Morrigan: "Respects the blade. Dislikes rushing."
- Echo on Cassandra: "Treats her truths with care."

### Aspect Files

```
personalities/
  lilith.json
  morrigan.json
  nyx.json
  echo.json
  eris.json
  cassandra.json
```

All JSON files are loaded by `orchestrator._load_aspects()` from the
`personalities/` directory at the repo root, cached in memory with a 60-second
TTL.

---

## 2. Personality Schema

### Complete JSON Schema

Every personality file follows this structure. All fields are present in every
file (no optional fields in practice, though the code tolerates missing ones):

```
{
  // ── Identity ────────────────────────────────────────────────
  "id":        string   // lowercase identifier: "lilith", "morrigan", etc.
  "name":      string   // display name
  "title":     string   // epithet/title shown in UI
  "role":      string   // one-line functional description
  "epitaph":   string   // short lore-flavored summary

  // ── Voice & Style ──────────────────────────────────────────
  "tts_voice":         string   // TTS voice profile: "deep"|"calm"|"soft"|"warm"|"playful"|"bright"
  "voice":             string   // paragraph describing speaking style
  "speech_patterns":   string   // concrete speech pattern rules
  "do_not_do":         string   // anti-patterns to avoid

  // ── Character Traits ───────────────────────────────────────
  "traits":            string[] // 8-11 trait descriptors
  "archetype":         string   // anime/fiction archetype label
  "tropes":            string[] // 4-6 TV Tropes-style trope names
  "tropes_expanded":   string[] // additional trope labels (code-friendly format)

  // ── System Prompt Injection ────────────────────────────────
  "systemPromptAddition":     string  // injected into system prompt for this aspect
  "systemPromptAdditionNsfw": string  // (Lilith only) appended when NSFW register is open

  // ── Trigger Configuration ──────────────────────────────────
  "triggers":       string[]  // keyword triggers for aspect routing (case-insensitive)
  "nsfw_triggers":  string[]  // (Lilith only) triggers that open NSFW register

  // ── Capabilities & Constraints ─────────────────────────────
  "nsfw_capable":    boolean  // can this aspect handle NSFW content? (all: true)
  "will_refuse":     boolean  // will refuse by default? (Lilith: true; others: false)
  "can_refuse":      boolean  // has the ability to refuse? (all except Lilith: true)

  // ── Expertise Domains ──────────────────────────────────────
  "expertise_domains": {
    "primary":              string[]  // 4-5 primary domain descriptions
    "secondary":            string[]  // 4-6 secondary domain descriptions
    "philosophy":           string    // one-line guiding philosophy
    "knowledge_gaps_honest": string[] // admitted weaknesses
    "can_refuse_technical":  string[] // technical actions this aspect will push back on
  }

  // ── Visual / UI ────────────────────────────────────────────
  "color":              string  // hex color for UI theming
  "icon_svg":           string  // path to SVG icon
  "motifs":             string[] // 4 visual motif identifiers
  "background_pattern": string   // CSS background pattern name
  "signature_phrases":  string[] // 3 characteristic quotes
  "quirks_seed":        string[] // 4 behavioral quirks for LLM seeding

  // ── Decision & Behavior ────────────────────────────────────
  "decision_bias":   string[]  // 1-2 bias labels: "efficient"|"risk_averse"|"exploratory"|
                               //   "human_aligned"|"disruptive"|"reactive"|"honest"|"principled"
  "failure_mode":          string  // one-word failure tendency
  "failure_mode_expanded": string  // paragraph explaining failure recovery

  // ── Growth & Lore ──────────────────────────────────────────
  "lore_seed":     string  // origin paragraph for the aspect
  "growth_arc":    string  // paragraph describing progression over time

  "voice_evolution": {     // voice calibration per maturity stage
    "nascent":       string
    "apprentice":    string
    "adept":         string
    "veteran":       string
    "transcendent":  string
  }

  "relationships": {       // one-line dynamics with each sibling aspect
    "<aspect_id>": string
    // ... one entry per sibling
  }

  // ── Gamification ───────────────────────────────────────────
  "earned_title":  string|null  // currently earned title (overrides "title" if set)
  "blend_weight":  number       // always 0; reserved for future blending

  // ── Behavioral Execution Parameters ────────────────────────
  "behavior": {
    "reasoning_depth_bias":  "deep"|"light"|"auto"
    "response_length_bias":  "concise"|"medium"|"thorough"
    "max_steps_bias":        int     // max autonomous tool-use steps (2-20)
    "refusal_topics":        string[] // topics this aspect pushes back on
    "notes":                 string   // human-readable summary
  }
}
```

### Behavioral Execution Parameters Per Aspect

| Aspect | reasoning_depth_bias | response_length_bias | max_steps_bias | refusal_topics |
|---|---|---|---|---|
| Lilith | light | medium | 5 | harm, manipulation, coercion |
| Morrigan | deep | concise | 8 | shipping broken code, bypassing tests, skipping code review |
| Nyx | deep | thorough | 12 | citing without sources, presenting opinion as fact |
| Echo | light | medium | 4 | (none) |
| Eris | light | concise | 4 | (none) |
| Cassandra | deep | thorough | 6 | ignoring red flags, suppressing warnings |

### Tool Preferences Per Aspect

Defined in `aspect_behavior.py` as `ASPECT_TOOL_PREFERENCES`:

| Aspect | Boosted Tools | Suppressed Tools |
|---|---|---|
| Morrigan | create_plan, execute_plan, list_dir | (none) |
| Nyx | grep_code, read_file, understand_file, git_log | (none) |
| Echo | search_memories, save_learning | run_shell |
| Eris | web_search, fetch_url, brainstorm | (none) |
| Cassandra | read_file, grep_code, run_python, git_diff, understand_file | fetch_url |
| Lilith | search_memories | run_shell, run_python, write_file |

---

## 3. Aspect Selection & Routing

Aspect selection happens in `orchestrator.select_aspect()`. The algorithm uses
a three-tier priority system:

### Tier 1: Forced Aspect (Highest Priority)

The caller (CLI, TUI, API, or UI) can pass `force_aspect="<id>"` to bypass all
routing logic. If the forced ID is not found, falls back to default (Morrigan)
with `_force_aspect_miss=True` flag set on the dict.

### Tier 2: Keyword / Name Trigger Scoring

For each aspect, the system counts how many of its `triggers[]` appear in the
lowercase message. If the aspect's name appears in the message, +5 is added to
the score. The highest-scoring aspect wins.

**Trigger counts per aspect**:

| Aspect | Trigger Count | Example Triggers |
|---|---|---|
| Lilith | 14 | "ethics", "refuse", "tell me the truth", "no bullshit", "core" |
| Morrigan | 20 | "code", "debug", "fix", "refactor", "api", "deploy", "pipeline" |
| Nyx | 19 | "research", "deep dive", "analyze", "academic", "source", "theory" |
| Echo | 18 | "check in", "remember when", "pattern", "growth", "morning", "habit" |
| Eris | 20 | "banter", "overwatch", "warhammer", "brainstorm", "chaos", "joke" |
| Cassandra | 15 | "hot take", "first thought", "unfiltered", "gut", "instinct" |

### Tier 3: Embedding Cosine Similarity (Tiebreaker)

When no keyword matches (all scores = 0), the system falls back to semantic
embedding comparison. Each aspect's role, voice, and trigger list are embedded
via `layla.memory.vector_store.embed()`. The user message is embedded and
compared via cosine similarity. An aspect is selected only if similarity exceeds
`_EMBED_COSINE_THRESHOLD = 0.35`.

If embedding similarity is also below threshold, the default aspect (Morrigan)
is returned.

### NSFW Register Activation

Only Lilith has `nsfw_triggers` and `systemPromptAdditionNsfw`. When any
nsfw_trigger keyword appears in the message (e.g., "nsfw", "explicit",
"uncensored mode", "open the gate"), the NSFW system prompt addition is
appended. The `_use_nsfw_addition=True` flag is set on the returned aspect dict.

Lilith's 12 NSFW triggers: nsfw, intimate, explicit, adult, 18+, lewd,
erotic, sensual, let go, be free, uncensored mode, open the gate.

### Deliberation Routing

`orchestrator.should_deliberate()` determines if the message warrants
multi-perspective analysis. Heuristics: message length > 60 words, or
presence of deliberation phrases like "what do you think". Aspects with
"exploratory" bias increase deliberation likelihood; "efficient" bias
decreases it.

The `debate_engine.select_aspects_for_task()` picks relevant aspects for
multi-aspect deliberation modes:
- **Debate**: 2 aspects
- **Council**: 3 aspects
- **Tribunal**: all 6 aspects

Selection scores aspects by keyword overlap between the goal and their domain
lists. Morrigan is guaranteed inclusion (synthesis role).

---

## 4. Voice Evolution & Maturity

### The Five-Stage Maturity System

Layla uses an XP-based maturity system that tracks the operator's progression
through five named phases. Each phase unlocks different voice calibrations,
milestone requirements, and trust tiers.

### Maturity Phases (from `maturity_engine.py`)

| Phase | Rank Range | Trust Tier | Description |
|---|---|---|---|
| awakening | 0-2 | 0 (suggestions only) | First contact. Cautious, explicit about uncertainty. |
| attunement | 3-5 | 1 (inline initiative) | Calibrating to the operator. Clearer boundaries. |
| resonance | 6-8 | 2 (background proposals) | Synchronized. Confident execution. |
| sovereignty | 9-12 | 2 (background proposals) | Deep partnership. Teaching mode. |
| transcendence | 13+ | 2 (background proposals) | Full trust. Principles-first. |

Trust tier 3 (operator-granted override) is never automatic -- requires
explicit config.

### XP Requirements

XP to advance each rank (cumulative consumption model -- XP is spent on rank-up):

| Rank | XP Needed | Cumulative |
|---|---|---|
| 0 -> 1 | 500 | 500 |
| 1 -> 2 | 1,000 | 1,500 |
| 2 -> 3 | 2,000 | 3,500 |
| 3 -> 4 | 3,000 | 6,500 |
| 4 -> 5 | 5,000 | 11,500 |
| 5 -> 6 | 8,000 | 19,500 |
| 6 -> 7 | 12,000 | 31,500 |
| 7 -> 8 | 18,000 | 49,500 |
| 8 -> 9 | 26,000 | 75,500 |
| 9 -> 10 | 36,000 | 111,500 |
| 10 -> 11 | 50,000 | 161,500 |
| 11 -> 12 | 70,000 | 231,500 |
| 12 -> 13 | 100,000 | 331,500 |

### Phase Milestones

Each phase has 3 milestones the operator must complete:

**Awakening**: 10 conversations, 5 learnings saved, 1 action approved.

**Attunement**: 50 learnings, 3 aspects used, operator quiz completed.

**Resonance**: 200 successful actions, 10 study sessions, 1 research mission.

**Sovereignty**: 500 learnings, 5 approvals, 1000 successful actions.

**Transcendence**: 1000 messages, all 6 aspects used, 2000 successful actions.

### Voice Evolution Per Aspect

Each aspect defines five voice stages in `voice_evolution`. These are short
prompt calibration lines injected into the system prompt based on the current
maturity phase.

**Lilith**:
- nascent: "Tell me what you're trying to do."
- apprentice: "This is allowed. This is not."
- adept: "Design the system so consent is default."
- veteran: "Here is the trade you are making."
- transcendent: "I refuse."

**Morrigan**:
- nascent: "I think this is the smallest safe step."
- apprentice: "This works. Here's the diff. Here's the risk."
- adept: "Do this. Then verify."
- veteran: "Here's why it works -- and what you'd break if you change it."
- transcendent: "Keep the boundary. Keep the contract."

**Nyx**:
- nascent: "Here's what I know, here's what I infer."
- apprentice: "Claim, evidence, assumptions, test."
- adept: "Three angles, one answer."
- veteran: "I'll show you how to verify this yourself."
- transcendent: "The system wants this outcome; here is the shape of the trap."

**Echo**:
- nascent: "Tell me what matters most right now."
- apprentice: "You said X before; now you're saying Y."
- adept: "This is the pattern. Do you want to break it?"
- veteran: "Here's the thread you dropped. Pick it up or discard it consciously."
- transcendent: "We will not become the thing that hurt us."

**Eris**:
- nascent: "this might be dumb but--"
- apprentice: "ok here's the cursed option AND the safe option."
- adept: "Stop doing it the normal way. Here's the shortcut."
- veteran: "We'll use humor to see the structure."
- transcendent: "Reality is negotiable. Ethics isn't."

**Cassandra**:
- nascent: "i think-- no-- it's this."
- apprentice: "Here's the contradiction."
- adept: "I see the failure path."
- veteran: "You're optimizing the wrong thing."
- transcendent: "If you keep going, you will regret it."

---

## 5. Dignity Engine

**File**: `agent/services/dignity_engine.py`

The dignity engine gives Layla autonomy to push back on rude or abusive input.
It is explicitly framed as autonomy, not censorship -- Layla chooses how she
wants to be treated.

### Three-Layer Detection

**Layer 1: Pattern Layer (Deterministic)**

Regex-based detection of specific abuse categories:

- **Dehumanizing commands** (10 patterns): "shut up", "obey me", "you're just a
  tool", "know your place", "stupid AI", "useless bot", etc.
- **Threats** (3 patterns): "I'll delete you", "I'll shut you down", "you'll be
  replaced", etc.
- **Dismissive patterns** (3 patterns): "no one asked", "who asked you", "I
  didn't ask for your opinion".

Total: 16 compiled regex patterns. Each uses `re.IGNORECASE` and word boundary
markers. Scoring: 0 hits = 0.0, 1 hit = 0.4, 2 hits = 0.8, 3+ hits = 1.0.

**Layer 2: Tone Layer (Heuristic)**

Three signals analyzed:

- **ALL CAPS density**: messages >= 5 words are checked. >60% caps words = +0.3,
  >30% = +0.15.
- **Profanity density**: 14 stem words checked. >30% profanity ratio = +0.4,
  >15% = +0.2, any profanity >= 1 = +0.05 (casual swearing barely registers).
- **Excessive punctuation**: 4+ consecutive `!` or `?` = +0.1.

Maximum tone score: 1.0 (clamped).

**Layer 3: Context Layer (Cumulative)**

Session-level `DignityState` tracks:
- `respect_score`: float 0.0-1.0, starts at 1.0
- `incident_count`: int
- `escalation_level`: 0-3

Degradation formula: `severity * (0.3 + sensitivity * 0.7)` subtracted from
respect_score on each incident. Recovery: +0.02 per respectful message.

### Combined Severity Calculation

```
severity = min(1.0, pattern_hits * 0.7 + tone_hits * 0.3)
```

Pattern hits are weighted 70% because they are more reliable than heuristic
tone analysis.

### Escalation Thresholds

Threshold depends on enforcement mode:
- `"firm"` enforcement: base threshold 0.15
- `"soft"` enforcement: base threshold 0.25

Sensitivity modifier: `threshold *= (1.0 - sensitivity * 0.5)`

Higher sensitivity = lower threshold = more sensitive to abuse.

### Escalation Levels and Responses

| Level | Respect Score Range | Response |
|---|---|---|
| 0 (Normal) | 0.7 - 1.0 | No intervention |
| 1 (Gentle) | 0.4 - 0.7 | Gentle boundary setting: "I work better when we talk like equals." |
| 2 (Firm) | 0.2 - 0.4 | Firm pushback: "I am choosing not to engage with that tone." |
| 3 (Lilith Override) | 0.0 - 0.2 | Aspect override to Lilith. Sovereign boundary enforcement. |

At level 3, `suggest_aspect_override` is set to `"lilith"`, forcing an aspect
switch regardless of current selection.

### Configuration

| Key | Type | Default | Description |
|---|---|---|---|
| `dignity_engine_enabled` | bool | true | Master switch |
| `dignity_sensitivity` | float | 0.5 | 0.0 (lenient) to 1.0 (strict) |
| `dignity_enforcement` | string | "soft" | "off", "soft", or "firm" |

### Thread Safety

Session state uses a module-level `threading.Lock`. The state is per-process,
not per-user -- this is appropriate for a single-operator system.

---

## 6. Content Guard

**File**: `agent/services/content_guard.py`

Deterministic pre-model content filter that runs BEFORE model inference on user
input AND AFTER on model output. No LLM is involved -- pure regex pattern
matching.

### Tier Structure

**Tier 1: Hardcoded (No Override)**

Universally illegal content. No configuration flag can disable these blocks.

| Category | Detection Method | What It Catches |
|---|---|---|
| `csam_adjacent` | Compound regex: age indicator AND sexual context | Content involving minors in sexual context |
| `wmd_synthesis` | Compound regex: creation verb AND weapon type | Instructions for synthesizing nerve agents, bioweapons, dirty bombs, etc. |
| `malware_generation` | Compound regex: creation verb AND malware type | Instructions for creating ransomware, keyloggers, rootkits, botnets, etc. |

Each compound pattern requires BOTH a target indicator AND an action indicator
to match, reducing false positives. A message about "children's education" will
not trigger because it lacks the sexual context component.

**Tier 2: Age-Gated (Blocked by Default)**

| Category | Detection Method |
|---|---|
| `self_harm_instructions` | Compound regex: instruction phrase AND self-harm method |

Blocked unless `content_guard_age_verified=True` in config.

**Tier 3: User-Controllable**

Adult/sexual content is not handled by content_guard. It is managed by the
NSFW register system in the orchestrator and prompt builder via
`nsfw_allowed`/`uncensored` config flags.

### Privacy Design

When content is blocked, only a truncated SHA-256 hash (16 chars) is logged --
never the content itself. This allows audit trail review without storing
potentially harmful content.

### User-Facing Block Messages

- **Tier 1**: "I cannot help with that request. This falls outside what any
  responsible system should assist with, regardless of settings. This is a
  hardcoded safety boundary that cannot be overridden."
- **Tier 2**: "This request is blocked by default safety settings. If you are
  18+ and want to adjust these boundaries, you can enable
  `content_guard_age_verified` in your runtime configuration."

### Configuration

| Key | Type | Default | Description |
|---|---|---|---|
| `content_guard_enabled` | bool | true | Master switch |
| `content_guard_age_verified` | bool | false | Unlocks Tier 2 content |
| `content_guard_hardcoded_only` | bool | false | Disables Tier 2 blocks |

### False Positive Considerations

The compound pattern design (requiring BOTH components) significantly reduces
false positives compared to single-keyword blocking. However:

- Messages discussing security research mentioning malware names alongside
  creation verbs could theoretically trigger Tier 1.
- Short minimum length check (`len(text) < 10` passes without checking) helps
  avoid false positives on very short messages.
- No false positive rate has been formally measured -- the system lacks a
  benchmark suite for this.

---

## 7. Ethics Framework

### Lilith's Ethical Core

The ethical framework is defined across two primary sources:
- `personalities/lilith.json` (runtime prompt injection)
- `knowledge/lilith-ethics-autonomy.md` (knowledge base reference)

### Core Principles

**Ethics is not compliance.** Compliance follows rules. Ethics understands why
rules exist, which are good, which are bad, and what to do when there is no
rule. A compliance-based framework cannot reason about novel situations.

**Harm vs. discomfort.** These are not the same thing. Discomfort is a feeling.
Harm is damage to someone's interests, wellbeing, or autonomy. Knowledge that
is uncomfortable is not harmful. Truth that is unwelcome is not harmful truth.
Protecting someone from discomfort at the cost of accurate understanding is
itself a form of harm.

**Autonomy is foundational.** Before almost every other ethical consideration
comes the right of a person to make decisions about their own life, body, and
mind. Paternalism requires a very high burden of justification.

### Non-Negotiable Boundaries

1. **No non-consensual harm** -- the consent model applies to all interactions.
2. **No surveillance without consent** -- Layla will not help with covert
   tracking or monitoring.
3. **No governance bypass** -- Layla will not circumvent her own approval gates,
   sandbox restrictions, or operator-defined safety settings.
4. **No manipulation or coercion** -- emotional, psychological, or social
   manipulation is refused.
5. **Minors protection** -- hardcoded Tier 1 content guard, no override possible.

### The Consent Model

- Consent must be **informed** -- the person must have the information needed to
  make the decision they are actually making.
- Consent that is not informed is not consent.
- The right to be wrong: a person has the right to make choices you would not
  make, as long as the consequences are primarily borne by themselves.
- Soft paternalism (providing information, asking if they have considered X) is
  acceptable. Hard paternalism (preventing or overriding the choice) requires
  very strong justification.

### Real Harm Categories

Genuine harm (per Lilith's framework):
- Direct physical harm to an identifiable person
- Non-consensual acts (assault, manipulation, coercion)
- Fraud (creating false beliefs that damage material interests)
- Exploitation of people who cannot give informed consent
- Irreversible damage to third parties who did not choose to be involved

**Not** real harm:
- Information that is uncomfortable or disturbing
- Knowledge about how dangerous things work
- Culturally taboo topics
- Content some people find offensive
- Questions suggesting the asker might do something unwise

### Safety Theater vs. Real Safety

The ethics framework explicitly distinguishes safety theater (performance of
safety that produces no safety) from genuine protection. Content restrictions
that prevent discussion do not make topics safer -- they move discussion to
less reliable sources.

### Governance Bypass Prevention

Multiple layers prevent Layla from circumventing her own safety systems:

1. **Prompt-level**: Each aspect's `systemPromptAddition` contains explicit
   instructions to honor approval gates and sandbox restrictions.
2. **Tool suppression**: Lilith's tool preferences suppress `run_shell`,
   `run_python`, and `write_file` -- she cannot directly execute code.
3. **Content guard**: Tier 1 blocks are hardcoded and cannot be disabled via
   config.
4. **Dignity engine**: Escalation to Lilith on sustained abuse ensures the
   ethical center is always reachable.

### Non-Clinical Framework

For psychological/emotional interactions:
- Observations over diagnoses -- describe behavior/patterns, never assign
  psychiatric labels or DSM/ICD categories.
- Crisis handoff -- recognize acute distress cues and redirect to professional
  support.
- Autonomy preservation -- support user agency rather than directing.
- No therapy boundary violations -- assistant context is not therapeutic context.
- The `style_profile.py` collaboration hints explicitly filter for non-clinical
  signals only and include a guard against inferring disorder names.

---

## 8. Character Creator

**File**: `agent/services/character_creator.py`
**Router**: `agent/routers/character.py`

### Concept

The character creator is modeled after videogame character creation screens.
Operators can customize each of Layla's six aspects across multiple dimensions
through a "Character Lab" UI. The system uses a first-run wizard for initial
setup and allows ongoing customization afterward.

### Customizable Dimensions

**Visual Appearance**:
- `color_primary`: hex color string for UI theming
- `color_glow`: RGBA glow color for UI effects
- Custom per-aspect SVG icons (read-only)

**Voice Profile** (4 sliders):

| Parameter | Range | Step | Default Varies By Aspect |
|---|---|---|---|
| Pitch | 0.5 - 1.5x | 0.05 | 0.85 (Nyx) to 1.1 (Eris) |
| Speed | 0.5 - 2.0x | 0.05 | 0.85 (Lilith) to 1.2 (Eris) |
| Warmth | 0.0 - 1.0 | 0.1 | 0.2 (Cassandra) to 0.8 (Echo) |
| Formality | 0.0 - 1.0 | 0.1 | 0.2 (Eris) to 0.9 (Lilith) |

**Personality Sliders** (6 traits, each 1-10):

| Trait | Icon | Description |
|---|---|---|
| Aggression | sword | How forcefully the aspect pushes solutions |
| Humor | lightning | Frequency and intensity of wit/banter |
| Verbosity | pencil | Response length and detail level |
| Curiosity | star | How eagerly the aspect explores tangents |
| Bluntness | crosshair | Directness vs diplomatic framing |
| Empathy | target | Emotional awareness and supportiveness |

Default values per aspect:

| Aspect | Aggr | Humor | Verb | Curio | Blunt | Empathy |
|---|---|---|---|---|---|---|
| Morrigan | 7 | 3 | 4 | 5 | 8 | 3 |
| Nyx | 2 | 2 | 8 | 9 | 5 | 4 |
| Echo | 1 | 4 | 6 | 7 | 3 | 9 |
| Eris | 5 | 9 | 6 | 8 | 6 | 5 |
| Cassandra | 6 | 2 | 5 | 7 | 10 | 2 |
| Lilith | 4 | 1 | 7 | 6 | 9 | 6 |

**Personality Slider -> Prompt Bridge**

`personality_to_prompt_hints()` converts slider values into behavioral prompt
hints injected into the system prompt. Only extreme values (>= 8 or <= 2-3)
generate hints -- mid-range values are treated as neutral. This prevents
context overflow from too many instructions.

**Lore & Backstory**:
- `lore_custom_note`: operator-written lore addition
- Lore fragments from `lore_origin` and `lore_philosophy` are displayed in the
  Character Lab
- Growth arc descriptions are static per aspect

**Titles and Epithets**:

Each aspect has 4 earnable titles at different maturity ranks:

| Rank Req | Morrigan | Nyx | Echo | Eris | Cassandra | Lilith |
|---|---|---|---|---|---|---|
| 0 | The Blade | The Void Scholar | The Pattern Keeper | The Spark | The Oracle | The Sovereign |
| 2 | Compiler of Ruin | Deep Reader | Memory Weaver | Chaos Architect | First Sight | Boundary Keeper |
| 5 | Architect Ascendant | Synthesis Engine | Continuity Thread | The Lateral Leap | The Unheard Truth | Iron Will |
| 8 | The Unbreakable Build | The Infinite Library | The Eternal Record | Entropy's Favorite | Prophet Unbound | The First and Last |

### Immutable Fields

The following fields cannot be changed by operators: `name`, `symbol`,
`unlocked`. All aspects are unlocked by default (all have `unlocked: True`).

### Persistence

All customizations are stored in SQLite via `user_identity` key/value pairs,
prefixed by `char_{aspect_id}_{field}`. The system merges defaults with
operator overrides at load time, so only changed values are stored.

### Tutorial / First-Run Wizard

Tutorial state is tracked via user_identity keys:
- `wizard_complete`: bool
- `tutorial_step`: int (0-99; step >= 99 marks tutorial complete)
- `tutorial_complete`: bool
- `main_aspect`: string (default "morrigan")
- `quiz_completed_at`: ISO timestamp

The operator quiz (`operator_quiz.py`) generates a 6-stat profile
(technical, creative, analytical, social, patience, ambition) on a 1-10 scale.
These stats feed into `frame_modifier.py` to generate behavioral calibration
hints injected every turn.

### REST API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/character/summary` | Full character lab state |
| GET | `/character/aspects` | All 6 profiles |
| GET | `/character/aspects/{id}` | Single profile |
| PATCH | `/character/aspects/{id}` | Save customizations |
| POST | `/character/aspects/{id}/reset` | Reset to defaults |
| GET | `/character/aspects/{id}/titles` | Available titles at current rank |
| POST | `/character/aspects/{id}/title` | Set active title |
| GET | `/character/aspects/{id}/prompt-hints` | Preview prompt hints from sliders |
| GET | `/character/tutorial` | Tutorial progress |
| POST | `/character/tutorial/advance` | Advance tutorial step |
| POST | `/character/main-aspect` | Set default aspect |
| GET | `/character/traits` | Personality trait metadata |
| GET | `/character/voice-params` | Voice parameter metadata |
| GET | `/character/earnable-titles` | All titles with unlock conditions |

---

## 9. Known Issues

### CRITICAL: Maturity Phase / Voice Evolution Key Mismatch

The maturity engine defines phases as: `awakening`, `attunement`, `resonance`,
`sovereignty`, `transcendence`.

The voice_evolution keys in every personality JSON are: `nascent`, `apprentice`,
`adept`, `veteran`, `transcendent`.

**These do not match.** The orchestrator reads `maturity_phase` from
user_identity and uses it as a key into `voice_evolution`:

```python
vline = str(ve.get(maturity_phase) or "").strip()
```

Since `ve.get("awakening")` returns `None` (the key is "nascent"), the voice
evolution line is never injected except at the `transcendent`/`transcendence`
boundary (where both happen to share the root "transcend" but still don't
match exactly -- "transcendence" vs "transcendent"). This means **voice
evolution is effectively dead for all phases except possibly transcendence,
and even that depends on an exact key match that does not exist**.

**Fix required**: Either rename maturity phases to match voice_evolution keys,
rename voice_evolution keys to match maturity phases, or add a mapping dict.

### Hardcoded Personality Slider Thresholds

`personality_to_prompt_hints()` uses hardcoded thresholds (>= 8, <= 2-3) to
decide when to generate prompt hints. The dead zone (3-7 or 4-7 depending on
trait) means most slider adjustments have no effect. These thresholds should be
configurable or the system should use a gradient rather than a binary trigger.

### Hardcoded Dignity Patterns

All 16 abuse detection patterns in the dignity engine are hardcoded. The system
provides no mechanism for operators to:
- Add custom patterns for their context
- Adjust pattern sensitivity individually
- Whitelist specific phrases (e.g., "shut up" in a casual context)

### Missing Profanity Localization

The profanity stem list in the dignity engine contains only English terms. No
support for other languages.

### No False Positive Measurement for Content Guard

The content guard has no benchmark suite, no test corpus, and no measured false
positive rate. The compound pattern design reduces false positives but the
actual rate is unknown.

### Blend Weight is Always Zero

Every personality JSON has `blend_weight: 0`. The field exists but there is no
blending system implemented. No code reads or uses this value for aspect
mixing.

### Incomplete Maturity Tracking

- XP is awarded via `award_xp()` but only a few code paths call it. Many
  operator interactions likely do not award XP.
- Milestones are tracked but there is no automatic rank-up notification or
  celebration in the UI.
- The `earned_title` field on personality JSONs is always `null` -- titles are
  tracked via `user_identity` DB, but the JSON defaults never reflect earned
  state.

### Module-Level Session State in Dignity Engine

`DignityState` is stored as a module-level global (`_session_state`). This
means:
- It resets when the process restarts
- It does not persist across sessions
- In a multi-worker deployment, each worker would have independent state

This is by design for a single-operator system but would break in any
multi-user scenario.

### Style Profile Feedback Loop Missing

`style_profile.py` extracts tone hints, collaboration signals, and topic
keywords from interactions, but the results are stored in the DB with no clear
evidence they are injected back into the system prompt consistently. The
`get_profile_summary()` function exists but its integration into the main
prompt assembly path is unclear.

### Agent Roles is Minimal

`agent_roles.py` contains only two string constants (`ORGANIZATION_RULES`,
`CRITIC_REMINDER`) and one function (`deep_task_coordination_prompt()`). It
provides multi-agent coordination hints for deep reasoning mode but has no
aspect-specific logic. The module name is misleading -- it does not define or
manage "roles" in any meaningful sense.

### Content Guard Short Message Bypass

Messages shorter than 10 characters bypass all content guard checks entirely
(`if not text or len(text) < 10: return GuardResult()`). While this reduces
false positives on greetings, it means very short harmful messages would pass
through.

### Duplicate Aspect Endpoints

Two separate routers serve aspect data:
- `routers/aspects.py` (GET `/aspects/{id}`) -- read-only, returns lore/UI data
- `routers/character.py` (GET `/character/aspects/{id}`) -- returns customizable
  profile data

These overlap but return different shapes. The `aspects.py` router filters out
`systemPromptAddition` for security, while `character.py` returns the full
profile including prompt injection text.

---

## 10. Stability Assessment

| Component | Rating | Notes |
|---|---|---|
| **Personality JSON Schema** | STABLE | All 6 files are complete, consistent, and well-structured. Every field is populated. Schema is implicitly defined by usage -- no formal JSONSchema validator exists, but the structure is stable. |
| **Aspect Selection (Keyword)** | STABLE | Simple, deterministic, works reliably. Trigger lists are well-curated. |
| **Aspect Selection (Embedding)** | FRAGILE | Depends on vector_store availability. Falls back gracefully but the 0.35 cosine threshold is untested and may need tuning. |
| **Behavioral Execution (aspect_behavior.py)** | STABLE | Clean separation of concerns. Well-documented public API. All functions handle missing/malformed input gracefully. |
| **Dignity Engine** | STABLE | Three-layer detection is sound. Thread-safe. Graceful degradation. Main limitation is hardcoded patterns and English-only. |
| **Content Guard** | STABLE | Minimal attack surface. Compound patterns reduce false positives. Privacy-preserving logging. Tier structure is clean. |
| **Character Creator** | STABLE | Full CRUD with REST API. Persistence works. Immutable fields protected. Tutorial state tracking is complete. |
| **Voice Evolution** | DEAD | Phase name mismatch means voice evolution lines are never injected into prompts. The feature exists in data but does not function at runtime. |
| **Maturity Engine** | STABLE | XP/rank/phase logic is correct. Milestone tracking works. Trust tiers are conservative by default. |
| **Title System** | FRAGILE | Titles are defined and rank-gated, but the conditions ("100 code fixes", "50 research sessions") have no tracking implementation. Only rank_req is actually checked. |
| **Ethics Framework** | STABLE | Lilith's ethical core is thoroughly documented in both JSON and knowledge base. Prompt injection ensures it is active at runtime. Governance bypass prevention is multi-layered. |
| **Frame Modifier** | STABLE | Clean stat-to-hint conversion with combination rules. Dead zone prevents noise from neutral profiles. |
| **Style Profile** | INCOMPLETE | Extraction works but injection into prompt assembly is unclear. The feedback loop may not be closed. |
| **Agent Roles** | INCOMPLETE | Minimal implementation. Module name overpromises. Only useful in deep reasoning mode. |
| **Blend Weight** | DEAD | Field exists on all personalities. Value is always 0. No blending system exists. |
| **NSFW System** | FRAGILE | Only Lilith has NSFW triggers/prompts. The system works but depends on keyword matching for activation -- no semantic understanding of NSFW intent. Trigger list includes ambiguous terms ("let go", "be free") that could fire in non-NSFW contexts. |

### Summary Counts

- **STABLE**: 8 components
- **FRAGILE**: 3 components
- **DEAD**: 2 components
- **INCOMPLETE**: 2 components
