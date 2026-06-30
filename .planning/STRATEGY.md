# Layla — Operating Strategy (2026-06-30)

Distilled from the senior-strategist/architect/OSS adversarial evaluation. This is the
*why* that governs `ROADMAP.md` and `UPGRADES.md`. PROJECT.md holds the vision; this
holds the hard decisions and the cuts.

## The one-line truth

Layla competes in the most crowded corner of OSS (local inference, local chat UIs, local
coding, local companions) and is **more focused than none of the leaders in any single
lane.** Its *only* defensible position is the **intersection**: a **private, offline,
low-end-friendly, multilingual, personality-driven companion-assistant** with
hardware-adaptive domain kits. Win the intersection or lose to focused incumbents.

## The wedge (what we ARE)

> *"The local AI with a soul that runs well on a potato, in your language, and can
> actually do things — fully private."*

- **Companion-leaning, not coding-leaning.** Coding-as-flagship is the one claim small-
  model-on-CPU structurally **cannot win** vs the cloud (Claude/Cursor/Copilot) or vs focused
  local coders (Continue/Aider/Tabby). Lead with private + low-end + multilingual + *soul*.
  The nearest real adjacent market is the companion crowd (SillyTavern/Backyard), not Cursor.
- **Coding stays a strong aspect, not the headline.** It's "good for focused edits/refactors"
  (measured), made *credible* by hybrid escalation (UPG-01), not by pretending 3B-on-CPU rivals the cloud.

## The single biggest mistake (and the fix)

**Trying to be everything.** 197 tools, 6 aspects, cluster mesh, tribunal council, voice,
vision, OCR, browser, gamification — one small team cannot out-maintain Ollama + Open WebUI +
Continue + SillyTavern *simultaneously*. The session already paid for this (god-modules, 206
shims, RAG silently off on the target install, no inference self-test until 2026-06-30).

**Fix: cut ~60% of surface to the wedge.** Cut/park: cluster/work-unit mesh, tribunal (6-aspect)
council, maturity gamification as a headline, and the long tail of the 197 tools. Every tool we
keep is a tool we maintain forever.

## The leverage principle: reuse, don't reinvent

The engine, vector store, embeddings, rerankers, constrained decoding, and OCR are all
**commodities with better OSS than we hand-rolled**. The moat is **curation + kits + soul**,
never the plumbing. Concrete swaps in `UPGRADES.md` (sqlite-vec, FastEmbed/model2vec, FlashRank,
Outlines, optional Ollama backend, Tauri shell). Adopting them *shrinks maintenance AND improves
low-end quality* — the rare win-win.

## Positioning

| | Decision |
|---|---|
| Primary audience | Privacy/offline + low-end + non-English + companion-lovers. **Not** pro coders. |
| Compete against | SillyTavern/Backyard (companion) + AnythingLLM (local RAG) — **not** Cursor. |
| Standards bet | OpenAI `/v1` + **MCP** (plugins) + Ollama API. Be a drop-in, not an island. |
| Plugin system | **MCP only.** Never invent a second one. |
| Engine | Abstract behind one interface: llama.cpp **and** Ollama **and** OpenAI-compatible remote. |
| License | Non-commercial today caps venture/enterprise. Treat as an **OSS cause**, not a cap table. |

## Verdict carried forward (from PROJECT.md viability audit, now sharpened)

- **As a venture: no.** Non-commercial license + brutal incumbents + small-model quality ceiling
  + solo-scale maintenance against that surface = wrong risk/return.
- **As an OSS passion/community project: yes.** The niche is real and underserved, the
  privacy/low-end/multilingual angle is honest, and the *soul* is genuinely differentiating
  (the Castilla story is the proof-of-heart). Fund as a movement (sponsors), not a startup.
- **Success = "does the friend (and people like her) love and use it,"** not market share.

## Non-negotiables (the trust + honesty backbone — keep)

- Local-first, approval-gated mutation, deny-by-default, loopback-default, hashed tokens,
  OS-keyring secrets (R5/R10/R11 hardening — already shipped and good).
- Verify against implementation, not docs; report measurements honestly even when they
  contradict prior claims (e.g. spec-decoding-on-CPU; RAG-was-silently-off).
- Every install must **prove a real inference turn** before declaring success (`scripts/selftest.py`).

## What this changes in the plan

1. ROADMAP re-tiers around the wedge: **MVP (narrow) → V2 (credible) → V3 (platform) → Dream (movement)**.
2. UPGRADES backlog leads with the **win-win OSS swaps** + **hybrid escalation** + **constrained decoding**.
3. Maintenance-debt paydown (finish R9; keep cutting surface) is a first-class roadmap item, not a chore.
