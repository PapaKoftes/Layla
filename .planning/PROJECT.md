# Layla

## What This Is

Layla is a **local-first, self-hosted AI agent platform** — a Python/FastAPI server that wraps a locally-loaded GGUF model (via `llama-cpp-python`) and exposes a tool-using agent loop over a web UI, CLI/TUI, an OpenAI-compatible `/v1` API, and optional MCP. It keeps all data on the operator's machine (SQLite + optional Chroma memory) and gates every side-effecting tool (file write / shell / code execution) behind explicit `allow_write`/`allow_run` + an approval flow.

**The sharpened thesis (2026-06-29):** Layla expresses itself through **personality *aspects*, and each aspect is a *domain-optimized kit*** — not a cosmetic skin. An aspect bundles {best local model for the user's hardware + the right skills/tools + a tuned system prompt + inference settings + a visual identity}. The product's job is to **detect the user's hardware on first run and provision the best possible experience it can actually run**, per domain. "Morrigan" (the architect) = the coding kit; other aspects own research, writing, reasoning, etc.

**North-star user (now concrete):** a friend on a **16GB-RAM, CPU-only laptop** who wants genuinely useful, private, *delightful* programming help. Aspirational: self-hosting operators who want a sovereign AI whose personalities are curated, hardware-aware domain experts.

## Core Value

**A capable, tool-using AI that runs entirely on your own hardware, safely acts on your files/system, and auto-tunes itself — model and domain kit — to the best experience your machine can run, with no cloud and no telemetry.** If everything else fails, the core loop (chat → model decides → approved tool runs → verified answer) must work and be trustworthy.

The defensible edge is **curation, not the engine**: the engine (llama.cpp), the runners (Ollama/LM Studio), and the chat UIs are commodities. The bet is that *assembling the optimal local kit per domain per hardware tier, auto-provisioned and wrapped in a personality*, is what no incumbent does well.

> **Current operating strategy → [`STRATEGY.md`](STRATEGY.md) (2026-06-30).** The market audit below
> was sharpened into an explicit wedge (private + low-end + multilingual + companion **soul**), a ~60%
> scope cut, a reuse-don't-reinvent principle, and MVP/V2/V3/Dream tiers. Backlog: [`UPGRADES.md`](UPGRADES.md).

## Honest viability framing (from the 2026-06-29 market audit)

An evidence-based audit (VC/PM/skeptic lens, web-researched) concluded that **as a market product competing head-on, Layla is redundant** — local coding (Cline/Aider/Continue), local runners/UIs (Ollama/Jan/Open WebUI, 25+ chat UIs), and companions/personalities (SillyTavern + Chub.ai) are all owned by far larger communities, and developers still prefer cloud for serious coding quality. **Conclusions we are operating under:**
- **Primary frame = a delightful personal tool** (the friend). Market non-viability is irrelevant to a gift; judge by *does she love and use it*.
- **The only real novelty is the aesthetic + the domain-kit personality system.** That is where effort should concentrate.
- **If it ever matters beyond her → pivot to a *layer on an incumbent*** (the personality/kit experience on an OpenAI-compatible engine) rather than maintaining a whole platform solo.
- **Measured reality check (this hardware tier):** Qwen2.5-Coder-7B-Q4 ≈ **5 tok/s** on 4-core/16GB CPU; quality is **good for focused edits/refactors, weaker on from-scratch self-verification**; **speculative decoding does NOT help on CPU** (memory-bandwidth-bound — measured *slower*). "Best possible local coding" here means the best *responsive* model + strong scaffolding, not the biggest model.

## Project Direction (two layers)

**Layer 1 — Remediation substrate (in progress).** An 88-finding adversarial audit established a critical security class, an untested core, and architectural/data risk. Phases 1–2 are shipped (security finish, legal/copyleft); 3–10 harden CI, inference, data, config, and the agent-loop god-file. This makes Layla safe to expose, legal to ship, and verifiably correct.

**Layer 2 — Friend-Ready milestone (the product North Star).** Two parallel tracks on the hardened foundation:
- **Track A — Daily-Driver:** best-possible *local* coding for a 16GB CPU box: hardware→domain-kit auto-provisioning, a compiler-less install, full-app E2E, and a **HumanEval/MBPP benchmark** so quality is measured.
- **Track B — The Layla Interface:** a from-scratch UI in the **"Warframe-mystic" midpoint aesthetic** — the angular sci-fi panel/glyph structure of the new direction rendered in the original's near-black + magenta/violet per-aspect identity — plus a **BG3-style aspect (character) creator** and a **Fallout-NV-style intake quiz** that shapes the default personality.

## Key Decisions
- **Local-first, single process, one model + one global lock** — deliberate; no required cloud services.
- **Personalities are domain kits**, not skins; the active aspect re-themes the UI (per-aspect colors already exist: morrigan=crimson, nyx=indigo, echo=blue, eris=brown, cassandra=teal, lilith=wine).
- **Installer detects hardware → provisions the optimal kit** (`install/model_selector.recommend_kit`), honoring a *CPU usability ceiling* (don't pick a model too slow to enjoy).
- **Approval-gated mutation** stays the trust backbone; deny-by-default.
- **UI rebuild = modern framework (React/Vite, TS)**, built to static assets served by the existing FastAPI backend; the API is the contract.
- **Python 3.11/3.12 only**; a real `.venv-test` (3.12) now runs the full suite + actual inference on the dev box (which *is* the friend's tier: 4-core/16GB/no-GPU).
- **Verify against implementation, not docs** — every change backed by a runnable test; report measurements honestly even when they contradict prior claims.

## Out of Scope (for now)
- Horizontal scaling / multi-node inference (single-process model accepted).
- Platform-scale market ambition (see viability framing — personal-first, or pivot to a layer).
- Rewrites of backend internals beyond the remediation phases — prefer surgical, regression-safe changes.

## Evolution
- **2026-06 (early):** Adversarial audit (88 findings) → trust-boundary class remediation → independent re-review → class-elimination → core-logic tests + bounded model cache. GSD adopted; codebase mapped.
- **2026-06-29:** Stood up a real 3.12 env + live CPU inference (proved E2E). Measured the honest local-coding reality. Ran a market-viability audit (→ personal-first + curation-moat framing). Sharpened the thesis to **hardware-adaptive domain-kit personalities**; shipped the `recommend_kit` engine. Locked the **Friend-Ready** two-track milestone and the **Warframe-mystic midpoint** UI direction.
- **2026-06-30:** Finished remediation (R1–R8 + R10; **2508 tests**; removed 206 back-compat shims → canonical imports; un-skipped the TestClient suite, fixing 12 hidden bugs incl. a Windows `time.monotonic()` resolution bug; restored RAG grounding on compiler-free installs). Shipped a **self-test-gated installer** (`scripts/selftest.py` — proves a real inference turn; SIGILL-safe) + **guided pairing** (`scripts/pair.py`), **proven end-to-end on the friend's tier** (16 GB CPU: `/health` 197 tools, `/ui`, `/agent` all green; RAG via fallback). Ran a senior-strategist/architect/OSS **adversarial product evaluation** → wrapped into GSD as **`STRATEGY.md`** (the wedge; cut ~60% of surface; coding = an aspect, not the headline) + **`UPGRADES.md`** (reuse-don't-reinvent backlog — sqlite-vec, FastEmbed/model2vec, FlashRank, Outlines, optional Ollama backend, Tauri; **hybrid escalation** as the quality unlock) + **ROADMAP** re-tiered to **MVP/V2/V3/Dream**. UI reverted to the clean original; direction locked (clean #1 + real-art ornament, subtle).
