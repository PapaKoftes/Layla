# Documentation index

Central index for Layla’s documentation. Links are relative so they work on GitHub and in local clones.

---

## System-level technical reference (factual)

| Path | Description |
|------|-------------|
| [system/](system/) | **Ground-truth** docs derived from `agent/` source: routes, config, execution paths, invariants. **Authoritative when narrative docs disagree.** Start with [system/README.md](system/README.md). |

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
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | Request flow, state, subsystems |
| [LAYLA_SYSTEM_OVERVIEW.md](LAYLA_SYSTEM_OVERVIEW.md) | What Layla is and how the pieces fit |
| [GOLDEN_FLOW.md](GOLDEN_FLOW.md) | End-to-end request lifecycle and contracts |
| [POST_AGENT_RESPONSE_CONTRACT.md](POST_AGENT_RESPONSE_CONTRACT.md) | `POST /agent` response shapes |
| [PRODUCTION_CONTRACT.md](PRODUCTION_CONTRACT.md) | Caps, safety invariants, `/health`, logging |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | North Star sections vs code |
| [RULES.md](RULES.md) | Naming, layout, allowed/forbidden patterns |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | Pre-publish verification |

---

## Capabilities and operators

| Document | Description |
|----------|-------------|
| [TECH_STACK_AND_CAPABILITIES.md](TECH_STACK_AND_CAPABILITIES.md) | Stack and capability domains |
| [CAPABILITIES.md](CAPABILITIES.md) | Capability overview |
| [RUNBOOKS.md](RUNBOOKS.md) | Add tools, aspects, knowledge, workers |
| [SKILLS.md](SKILLS.md) | Skills system |
| [missions.md](missions.md) | Long-running missions |
| [REMOTE_ARCHITECTURE.md](REMOTE_ARCHITECTURE.md) | Remote access patterns |
| [ETHICAL_AI_PRINCIPLES.md](ETHICAL_AI_PRINCIPLES.md) | Ethics and boundaries |

---

## Planning and roadmap

| Document | Description |
|----------|-------------|
| [ROADMAP.md](ROADMAP.md) | Roadmap |
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

---

## Collaborators and audits

| Document | Description |
|----------|-------------|
| [REPO_AUDIT_FOR_COLLABORATORS.md](REPO_AUDIT_FOR_COLLABORATORS.md) | Sharing the repo safely |
| [AI_HANDOFF_REPORT.md](AI_HANDOFF_REPORT.md) | Cumulative handoff context |

---

**Tip:** For AI assistants working in-repo, read **PROJECT_BRAIN.md** and **../AGENTS.md** first; then open only the doc for the subsystem you change.
