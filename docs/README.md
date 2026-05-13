# Documentation Index

Central index for Layla’s documentation. Links are relative so they work on GitHub and in local clones.

**Last updated:** 2026-05-12 | **Tests:** 858 passing | **Health checks:** 12/12 green

---

## System-level technical reference (factual)

| Path | Description |
|------|-------------|
| [system/](system/) | **Ground-truth** docs derived from `agent/` source: routes, config, execution paths, invariants. **Authoritative when narrative docs disagree.** Start with [system/README.md](system/README.md). |
| [../agent/docs/audit/](../agent/docs/audit/) | **Subsystem audit** (2026-05-12): 63 subsystems classified as REAL/PARTIAL/SCAFFOLD/MISSING. Ground truth for gaps. |
| [../agent/scripts/README.md](../agent/scripts/README.md) | Health check scripts: 12 checks covering bugs, config, imports, security, API contracts, DB, UI symbols, wiring, memory router enforcement, and pytest. |

Other documents under `docs/` are primarily **explanatory** (onboarding, audits, roadmap, conventions). Use **`docs/system/`** when you need behavior-level precision.

---

## Start here

| Document | Description |
|----------|-------------|
| [../README.md](../README.md) | Product overview, install, screenshots, quick links |
| [ONBOARDING_15_MIN.md](ONBOARDING_15_MIN.md) | **15-minute** operator checklist (single path) |
| [GETTING_STARTED.md](GETTING_STARTED.md) | Fast path: install, start server, first-run UI |
| [GETTING_THE_MODEL.md](GETTING_THE_MODEL.md) | GGUF choice, download, paths, hardware tiers |
| [../MODELS.md](../MODELS.md) | Model catalog, Hugging Face links, config snippets |
| [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) | Runtime keys and behavior |
| [SECURITY.md](SECURITY.md) | Threat model, remote access, operator hygiene |
| [media/README.md](media/README.md) | Readme screenshots/GIF — automation + manual recording |
| [VERIFICATION.md](VERIFICATION.md) | **CI parity:** pytest markers, coverage, Playwright / deep workflows |

---

## Architecture and runtime

| Document | Description |
|----------|-------------|
| [../PROJECT_BRAIN.md](../PROJECT_BRAIN.md) | Stable system summary — read before deep repo scans |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | Request flow, state, subsystems (47 KB — comprehensive) |
| [LAYLA_SYSTEM_OVERVIEW.md](LAYLA_SYSTEM_OVERVIEW.md) | What Layla is and how the pieces fit |
| [GOLDEN_FLOW.md](GOLDEN_FLOW.md) | End-to-end request lifecycle and contracts |
| [POST_AGENT_RESPONSE_CONTRACT.md](POST_AGENT_RESPONSE_CONTRACT.md) | `POST /agent` response shapes |
| [PRODUCTION_CONTRACT.md](PRODUCTION_CONTRACT.md) | Caps, safety invariants, `/health`, logging |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | North Star sections vs code |
| [RULES.md](RULES.md) | Naming, layout, allowed/forbidden patterns |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | Pre-publish verification |

---

## Personality and aspects

| Document | Description |
|----------|-------------|
| [../LAYLA_NORTH_STAR.md](../LAYLA_NORTH_STAR.md) | Vision, FRAME calibration, design principles |
| [PERSONALITY_LAYER_ARCHITECTURE.md](PERSONALITY_LAYER_ARCHITECTURE.md) | Personality expression layer design (prompt-only, feature-flagged) |
| [PERSONALITY_LAYER_UNDERSTANDING.md](PERSONALITY_LAYER_UNDERSTANDING.md) | How personality is injected, aspect selection, refusal, UX states |
| [ETHICAL_AI_PRINCIPLES.md](ETHICAL_AI_PRINCIPLES.md) | Ethics and boundaries |

---

## Capabilities and operators

| Document | Description |
|----------|-------------|
| [TECH_STACK_AND_CAPABILITIES.md](TECH_STACK_AND_CAPABILITIES.md) | Stack and capability domains |
| [CAPABILITIES.md](CAPABILITIES.md) | Capability overview |
| [RUNBOOKS.md](RUNBOOKS.md) | Add tools, aspects, knowledge, workers |
| [SKILLS.md](SKILLS.md) | Skills system |
| [missions.md](missions.md) | Long-running missions |
| [RESEARCH_MISSION_UI_GUIDE.md](RESEARCH_MISSION_UI_GUIDE.md) | How to run/resume 24h research missions from the UI |
| [REMOTE_ARCHITECTURE.md](REMOTE_ARCHITECTURE.md) | Remote access patterns |

---

## Planning and roadmap

| Document | Description |
|----------|-------------|
| [../SYSTEM_PLAN.md](../SYSTEM_PLAN.md) | Master development plan (from current state to fully operational) |
| [../COMPLETION_PLAN.md](../COMPLETION_PLAN.md) | **Full completion plan** — 9 phases, 265 hours, every gap addressed (2026-05-12) |
| [ROADMAP.md](ROADMAP.md) | Phase-by-phase roadmap |
| [MILESTONES.md](MILESTONES.md) | Milestones |
| [TASKS.md](TASKS.md) | Lightweight backlog pointer |

---

## Engineering depth

| Document | Description |
|----------|-------------|
| [MODULE_SWEEP_STATUS.md](MODULE_SWEEP_STATUS.md) | Subsystem sweep registry |
| [MODULE_SWEEP_TEMPLATE.md](MODULE_SWEEP_TEMPLATE.md) | Template for new sweeps |
| [STRUCTURED_ENGINEERING_PARTNER.md](STRUCTURED_ENGINEERING_PARTNER.md) | Engineering pipeline |
| [ADAPTIVE_EXECUTION_ENGINE.md](ADAPTIVE_EXECUTION_ENGINE.md) | Budgets and adaptive execution |
| [FINAL_SYSTEM_READINESS.md](FINAL_SYSTEM_READINESS.md) | Research lab, mission state, runtime limits audit |

---

## Collaborators and audits

| Document | Description |
|----------|-------------|
| [REPO_AUDIT_FOR_COLLABORATORS.md](REPO_AUDIT_FOR_COLLABORATORS.md) | Sharing the repo safely |
| [../AGENTS.md](../AGENTS.md) | AI/contributor operations manual (read-first for AI assistants) |

---

## Archived (historical)

Older diagnostic reports, point-in-time audits, and handoff docs live in [`archive/`](archive/).

---

**Tip:** For AI assistants working in-repo, read **PROJECT_BRAIN.md** and **../AGENTS.md** first; then open only the doc for the subsystem you change.
