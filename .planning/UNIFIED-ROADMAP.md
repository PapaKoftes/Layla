# Unified Roadmap — reconciling the refactor + this session

**Date:** 2026-06-29. Reconciles **two parallel lines that were both yours**:
- `origin/master` — a 645-file **refactor + companion-first VISION** (agent-loop decomposition, service reorg into 19 packages, frontend ES-module rearchitecture, Tier 0–5 hardening, `docs/VISION.md` 10-phase plan, ADR-006).
- `friend-ready-session` (this session) — **security hardening + best-local-coding** (REQ-10/11/12, hardware→kit recommender, compiler-free memory fallback, benchmark, fresh installer, tunnel, planning).

## The product direction, reconciled (this is the key integration)
The refactor's **ADR-006 is canonical**: **Companion First, Workstation Second**; *No New Major Systems*; *Every system must produce felt user impact*; *Progressive Disclosure*. My session over-indexed on coding/workstation. The unified truth:

> **Layla is a companion-first living experience where personalities are domain kits. Coding (the "morrigan" aspect) is one strong domain — the friend's use case — but it is workstation depth that emerges *second*, behind the companion soul.** The Warframe-mystic UI serves warmth + identity + progressive disclosure; the character-creator/quiz are onboarding into that companion.

So my coding kits/benchmark/scaffolding are **valid but reprioritized below** the companion-experience work, and must respect "no new major systems" (they're small enhancements, not new platforms).

## Unified phases (15) and where we are

**Foundation**
1. **Security & trust boundary** (REQ-10/11/12) — ✅ DONE *(mine; on branch)*
2. **Legal & launch** (copyleft guard, AGPL removed, reload-off) — ✅ DONE *(mine; on branch)*
3. **Architecture: agent-loop decomposition + 19-package service reorg + boundary tests** — ✅ DONE *(refactor; on master)*
4. **Frontend modularization** (31 IIFE → ES modules, bus/state/actions) — ✅ DONE *(refactor; on master)*
5. **Compiler-free runtime** (CPU wheels + SQLite/NumPy memory fallback + hardware→kit recommender) — ✅ DONE *(mine; on branch)*

**Companion soul** *(refactor's VISION P1–P2,P4,P7 — highest priority next)*
6. **Verifiable core** (suite green on real stack ✓, coding benchmark ✓, inference-smoke CI ☐) — ◑ PARTIAL (2/3) *(mine)*
7. **Experience Unification** (companion runtime, continuity memory, passive initiative, emotional presence) — ☐ OPEN
8. **Growth system** (ranks, visible growth moments, XP rebalance) — ◑ PARTIAL *(XP hooks wired in refactor; rest open)*
9. **Memory & learning pipeline** (verification loop, conversational confirmation, interest modeling) — ◑ PARTIAL *(store + fallback done; pipeline open)*
10. **Relationship system** (people space, relationship reflection) — ☐ OPEN

**Product surface**
11. **UI/UX — unified** (companion-first warmth + Warframe-mystic aesthetic + BG3 character creator + Fallout-NV intake quiz + progressive disclosure) — ☐ OPEN *(aesthetic LOCKED + mockups; frontend now modular helps; no `ui-next/` code yet)*
12. **Coding domain depth** *(workstation-second)* (kit contents + scaffolding: repo-map, diff-edits, GBNF, codebase RAG) — ◑ PARTIAL *(recommender + benchmark done; scaffolding open)*
13. **Multi-device & connect** (pairing UX, device identity, remote tunnel, E2E cluster) — ◑ PARTIAL *(tunnel script built; pairing UX + E2E open)*
14. **Performance & resource intelligence** (governor wiring, model-thrashing prevention, background scheduler) — ☐ OPEN
15. **Deployment & distribution** (one-command installer ✓, docker/portable ☐, CI/CD gating ☐) — ◑ PARTIAL *(fresh installer + provisioner built; docker + release-gating open)*

*(+ ongoing: architectural cleanup — split `infrastructure/`, reduce shim surface — refactor, in progress.)*

## WHERE WE ARE
- **Fully done: 5/15** (phases 1–5).
- **Partial: 6/15** (6, 8, 9, 12, 13, 15).
- **Open: 4/15** (7, 10, 11, 14).
- **Weighted ≈ 8/15** (5 done + 6 partials at ~half).

### The honest caveat
That ~5/15 is **split across two un-merged branches** — the refactor's done work (3, 4) is on `master`; mine (1, 2, 5, 6) is on `friend-ready-session`. **Neither branch alone is 5/15; only the merge is.** So:

**The single gating task = the integration merge** (25 conflicts, scoped in `HANDOFF.md §6a`). Until it lands, `master` is ~2/15 (3, 4 + partials) and my branch is ~3/15 (1, 2, 5 + partials). After the merge, `master` becomes the true ~5/15 and everything downstream proceeds from one base.

### Recommended order after the merge (companion-first)
6 (finish verifiable core) → 11 (the unified UI — biggest felt impact) → 7 (companion runtime — the soul) → 13 (connect both, your stated goal) → 12 (coding depth) → 8/9/10/14 → 15.
