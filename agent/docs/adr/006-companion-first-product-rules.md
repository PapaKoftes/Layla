# ADR-006: Companion-First Product Rules

**Status:** Accepted  
**Date:** 2026-05-26  
**Context:** After completing three major architecture plans (Frontend ES Module Rearchitecture, Maturity System Wiring, Backend Service Reorganization), a full product analysis revealed that engineering is 85-90% complete but the product experience is 60-65%. The gap is the difference between "all systems work" and "using Layla feels like having a companion that grows with you." Four permanent rules were adopted to govern all future development.

## Decision

### Rule 1: No New Major Systems

Do not add new memory types, planning engines, frameworks, UI tabs, or infrastructure layers until existing systems feel unified. The codebase has 13 active subsystems. They need connection, not company.

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

## Consequences

- All new work is evaluated against these four rules before approval.
- Features that add complexity without felt user impact are rejected.
- UI changes default to simplification over exposure.
- The full implementation roadmap is documented in [docs/VISION.md](../VISION.md) (Phases 1-10).
- These rules apply permanently — they are not scoped to a single release cycle.
