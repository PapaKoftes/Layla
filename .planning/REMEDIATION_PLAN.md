# Layla Remediation Plan — Intent-vs-Reality (GSD)

**Created:** 2026-07-09 · **Source:** 11-agent audit in [`.planning/audit/`](audit/) (intent-vision, intent-ux,
state-{ui,memory,chat,backend-wiring,persona}, delta-{gaps,ux-parity,voice,critic}).

## Diagnosis (one line)
The backend is *over*-built; the last mile is missing or mis-wired. Three compounding failures:
**(1) flattening** — the FRAME antihero vector (EDGE/NERVE/SIGNAL) doesn't exist in code, and two always-on
"warm/plain" tone anchors are unopposed; **(2) burial** — ~18 working routers + ~24 panels have no discoverable
UI door; **(3) dead signatures** — several flagship features are write-dead or gated-dead (maturity phase-name
typos, no write-path), so they'd surface empty.

## Operator decisions (2026-07-09)
- **Voice target:** *Direct, but keep some warmth.* Drop corporate softening, add real pushback, keep a warmth
  baseline + medium length. NOT full-brutal antihero. Restore FRAME as the enforcement mechanism but tune the
  default vector softer than the North Star's raw EDGE=8/NERVE=9 (e.g. EDGE~6, NERVE~7, SIGNAL~4, IRON~4).
- **Approach:** Phased GSD, run it through — roadmap of record here; execute phase-by-phase, commit each
  checkpoint, operator tests the running result between phases.
- **First wave:** *Un-bury + un-break features.*

## Non-negotiables (carry through every phase)
Work on **master** directly (never branch). Never commit operator-state (`runtime_config.json`, `layla.db`,
`knowledge_graph.graphml`, `agent/.layla/`, `vector_meta.json`, `.governance/`). Commits end with the
`Co-Authored-By: Claude Opus 4.8` trailer. Keep per-aspect sigils (⚔✦◎⚡⌖⊛) and the Warframe aesthetic. Run
pytest from `.venv-test`; app from `.venv`. Preserve the anti-theatrics guards from commit 786f789 (no
"Greetings traveler", no audio/voice, no self-name echo) — restoring edge must NOT reintroduce roleplay cringe.

---

## PHASE 1 — Un-break + Un-bury  *(current)*

### 1A · Un-break (surgical, verified)
| # | Fix | Evidence | Change |
|---|-----|----------|--------|
| C2 | Proactive-initiative gate dead (phase typo) | `reasoning_handler.py:334` `in ("adept","veteran","transcendent")` | → `("resonance","sovereignty","transcendence")` |
| C3 | First-run observation mode dead (phase typo) | `llm_decision.py:253` `== "nascent"` | → `in ("awakening","attunement")` |
| H10 | Voice-evolution ladder dead (key mismatch) | `personalities/*.json` keys `nascent/apprentice/adept/veteran/transcendent` vs engine `awakening/…/transcendence` | reconcile keys or map |
| C1 | Skill-acquisition never fires (no caller) | `skill_acquisition.acquire_from_run` only called by its router | wire into post-run in `outcome_writer` (flag-gated, ≥2 steps) |
| C5 | Mood double-dead (flag off + never nudged) | `system_head_builder.py:896` reads `emotional_presence_enabled` (set nowhere); `register_signal` only on thumbs UI | add default flag + register signals from turn loop |
| C8 | Phase-name typos can recur (no guard) | gate sites compare raw strings vs `PhaseId` | export checked constants + helper predicates + test |
| H8 | Codex settings panel 404 | `settings-full.js:277,300` `/codex/user` | → `/codex/relationship` |
| H9 | Workspace ES search 404 | `workspace.js:445` `/elasticsearch/search` | → `/memory/elasticsearch/search` |

### 1B · Un-bury (surface features)
- **Palette discoverability (H6):** add a visible ⌘K spotlight affordance (Warframe console glyph); fix the
  double-bound / mis-documented Ctrl+K ("Clear input" hint is the opposite binding).
- **Surface flagship intelligence features (H3):** mood, goals, world-state, timeline, decisions, learned-skills,
  cross-project — wire panels + promote a curated few into visible nav. NB: several need their 1A write-path fix
  first (mood/skills/world) or they render empty — do 1A before surfacing those.
- **World-state actually informs reasoning (C7):** inject `world_state.summarize()` into the system head (not
  just a `GET /world` dashboard) — otherwise it's an inert snapshot.

## PHASE 2 — Voice / edge (calibrated: direct + warmth)
- Rebuild FRAME with the real behavioral axes (EDGE/NERVE/IRON/SIGNAL + FRAME/WIRE/DRIVE) in
  `frame_modifier.py` + `operator_quiz.py`; emit per-stat modifier strings into the every-turn calibration block.
- Seed the operator default vector to the *tuned* values (direct+warmth, not raw antihero).
- Fix the two always-on anchors: `system_identity.txt:19` and `_OUTPUT_DISCIPLINE` closer — swap "warm" default
  → "direct; warmth earned", add the "blunt is not robotic" guardrail, add SIGNAL global length clamp that can
  override an aspect's `thorough`.
- Keep all 786f789 anti-theatrics guards + the phatic cap.

## PHASE 3 — Memories tab + synthesized titles (Claude/ChatGPT parity, Layla-voiced)
- "What Layla Knows About You" panel on `GET /memory/about` + per-item forget; per-aspect "how {aspect} sees you"
  strip; conflict/merge review strip.
- Deterministic confirm-to-file identity extractor; fill relationship/timeline on meaningful turns (not only on
  context overflow); "memory updated" receipt chip in Layla's voice.
- Async title synthesizer (extractive fallback on low tiers); fix the frozen-at-turn-1 + empty-first-message
  cases; run through the aspect/earned-title strip.

## PHASE 4 — Chat management + reliability
- Date-bucketed rail grouping (Warframe dividers, keep aspect dot/tags); fix broken pagination (`offset`
  ignored → duplicates); server-side durable pins; FTS5 search; reload fidelity (roles/segments, no silent
  swallow); surface fork/branch/compare.

## PHASE 5 — Polish / cleanup (lower ROI)
- Nav de-duplication (two nav systems + triple Settings); palette command de-dup (german/tutor, verify×2);
  font-role trio (U1) if desired; onboarding remote-default re-verify (H13, lower severity per critic).

## Verification discipline
Each phase: change → `.venv-test` pytest on touched areas + ruff → restart app → live-verify the running
result → commit checkpoint → report remaining work. Operator tests + redirects between phases.
