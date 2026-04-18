# Layla — Roadmap and Plan

This document is the single place for the full product and engineering plan. Add new items here as the project evolves.

---

## How to use this doc

- **Done**: Shipped and documented.
- **In progress**: Actively being worked on.
- **Planned**: Agreed direction; not yet started.
- **Optional / backlog**: Nice to have; no commitment.

---

## Current milestones (M1–M6)

| ID | Focus | Status | Notes |
|----|--------|--------|--------|
| M1 | Stabilize and document | Done | DB path, Python 3.11–3.12, runbooks, first-run docs |
| M2 | Research pipeline | Partial | Stages documented; stop/retry and tests can be extended |
| M3 | Study and memory | Done | Study plans, wakeup, learnings, tests |
| M4 | Approval and safety | Partial | Flow documented and tested; policy in runtime_safety.py |
| M5 | Extensibility runbooks | Done | Add tool, aspect, knowledge in RUNBOOKS.md |
| M6 | Optional enhancements | Partial | PDF loader, trace ID, RAG citations; Notion = export to Markdown |

Details: [MILESTONES](MILESTONES.md).

---

## Product and feature plan (extensible)

### Core experience

- Local GGUF model via llama-cpp-python (done)
- Multi-aspect identity and tool loop with approval (done)
- Persistent memory and optional RAG with cited sources (done)
- Wakeup, initiative, project-discovery one-liner (done)
- Research missions and staged pipeline (done)
- Optional: more research stages or depth presets (planned as needed)

### Docs and onboarding

- README, ARCHITECTURE, RUNBOOKS, first-run and model setup (done)
- Tech stack and capabilities doc (done)
- Roadmap and milestones (done)
- Optional: video or interactive first-run walkthrough (backlog)

### Extensibility

- Add tool / aspect / knowledge runbooks (done)
- Config-driven features: remote, trace ID, scheduler, initiative (done)
- Optional: Notion API loader; more doc types (backlog)

### Operations and observability

- Optional trace ID for debugging (done)
- Remote trigger with auth; design in REMOTE_ARCHITECTURE.md (done)
- Optional: structured logging or analytics export (backlog)

---

## Where to add new items

- **New milestone**: Add a row to the table above or a new M7+ section; update MILESTONES.md if needed.
- **New feature**: Add a bullet under the relevant heading with [ ] or [x].
- **New theme** (e.g. Mobile, Plugins): Add a new section and bullets.

**Inspiration and end goal:** Growth over time (learning, evolving, deepening across sessions) is part of the product vision. That spirit is an inspiration and goal for Layla; it is not a separate selectable aspect.

Keep this file concise; link to RUNBOOKS, MILESTONES, and TECH_STACK_AND_CAPABILITIES.md for detail.
