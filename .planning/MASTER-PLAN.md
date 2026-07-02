# Layla — Master Plan to Truly Done (2026-07-02)

The complete, honest list + plan of **everything** between here and *"nothing deferred,
nothing half-implemented, GUI locked, truly ready."* No spin. Item detail lives in
[`UPGRADES.md`](UPGRADES.md); strategy in [`STRATEGY.md`](STRATEGY.md); this is the
execution order + acceptance gates.

Effort is in **focused passes** (≈ one work session each). Total to truly-done: **~28 passes.**
Status: `✅ done` · `🟡 half` · `⬜ not started`.

## The bar — what "truly ready" MEANS (the final gate)

A build is *truly ready* only when ALL are true:
1. `fresh_install.ps1` run on a clean box produces a working `.venv` and **passes `selftest --server`** (not inferred — demonstrated).
2. The **GUI is built to the locked "clean #1" look** and you have signed off against the running screen.
3. **Scope is cut to the wedge** (no bloat pretending to be product).
4. **Zero `[~]`/`⬜` items remain** in UPGRADES, or each remaining one is explicitly `[—] cut` with a reason.
5. Full suite green + real install green + one end-to-end human UAT (a real coding/chat session on the friend's tier).

## Honest snapshot

- **Substrate DONE:** R1–R8+R10, security (R5/R10/R11), self-test-gated installer machinery, pairing, RAG-grounding fix, GGUF/atomic-download hardening. **2512 tests green.**
- **Ledger:** 4 done · 6 half · 26 open · 1 cut. **Phase 2 (install) now DONE.**
- **Not done:** the GUI build, the scope cut, the real install run, and 32 upgrade items.

---

## Phase 0 — Substrate ✅ (done; listed for completeness)
R1–R8+R10, security hardening, installer self-test (`scripts/selftest.py`), pairing
(`scripts/pair.py`), RAG fallback, GGUF validation + atomic download, trap-installer retirement.
**No further work.**

## Phase 1 — GUI LOCK 🟡 (the most-demanded; ~6 passes) — *needs your sign-off per pass*
Goal: the whole UI matches the **clean, dark, streamlined #1** look; ornament from real
historical art, subtle; you approve each pass against the **running app**.
- **1.1 Design system lock (S)** — codify tokens: palette (locked #0a0008/#8b0000/#3d0050),
  a spacing scale, a type scale (Cinzel display + JetBrains Mono body), and ONE ornament rule
  (subtle engraved damask on chrome only). Kill ad-hoc inline styles.
- **1.2 Core chrome (M)** — header/topbar, sidebar nav, status chips, dashboard cards →
  streamlined #1 (consistent density, remove clutter, align the aspect switcher).
- **1.3 Chat surface (M)** — message bubbles, streaming, input composer, code blocks → clean.
- **1.4 Panels & modals (M)** — settings, Models & Kits, memory, research, artifacts, dashboard →
  one consistent card system.
- **1.5 Aspect switcher + BG3 creator + setup wizard (M)** — refined to the aesthetic.
- **1.6 Responsive + a11y + polish + SIGN-OFF (M)** — mobile PWA, WCAG pass, then you say "locked."
**Acceptance:** every screen matches #1; you approve; `check_ui_symbols.py` + e2e-ui green.

## Phase 2 - PROVE THE INSTALL ✅ (DONE 2026-07-02)
- **2.1** Run `install\fresh_install.ps1` for real → creates `.venv` (compiler-free) → provisions a
  model → **`selftest --server` passes on `.venv`**. Fix anything that surfaces.
- **2.2** Clean-profile / fresh-clone dry run so "clone → one command → working" is demonstrated.
**Acceptance:** a real `.venv` exists and passes the self-test; install is proven, not inferred.
**DONE:** Found the installer had NEVER run — `fresh_install.ps1`/`connect_tunnel.ps1` failed to PARSE (non-ASCII read as ANSI by PowerShell 5.1) + a `Find-Py312` bug. Fixed (ASCII-only + clean version check). `.venv` built end-to-end; `selftest` on `.venv` = PASS 0 warnings (model loads + real turn + RAG).

## Phase 3 — SCOPE CUT ⬜ (UPG-00a; the strategy's #1; ~2 passes)
Reversible **parking behind flags**, not deletion (keep tests green):
- **3.1** Cluster/work-unit mesh → `experimental` flag, off by default, hidden from UI.
- **3.2** Deliberation → surface **solo/debate** only on weak tiers (auto via governor, UPG-14);
  council/tribunal become explicit opt-in.
- **3.3** Gamification/maturity → opt-in, demoted from the default surface.
- **3.4** Tools → curate a **core set per aspect**; gate the long tail behind "advanced."
**Acceptance:** default surface = the wedge; parked features documented + reversible; suite green.

## Phase 4 — FOUNDATION SWAPS ⬜ (memory/engine; ~4 passes)
- **4.1 UPG-10 engine abstraction (M)** — one interface over {llama.cpp, Ollama, OpenAI-remote}.
- **4.2 UPG-02 sqlite-vec (M)** — replace the bespoke `FallbackCollection`; keep the Chroma-shaped API;
  `test_fallback_store` green; delete hand-rolled cosine.
- **4.3 UPG-03 FastEmbed / model2vec (M)** — ONNX/static embeddings; drop torch+sentence-transformers weight.
- **4.4 UPG-11 one SQLite memory file + UPG-04 FlashRank (M)** — consolidate; light CPU rerank.
**Acceptance:** memory runs on sqlite-vec + FastEmbed, lighter + faster on CPU; all memory tests green.
*(This is where R9/UPG-00b is absorbed — vector_store is rewritten here, so we don't split-then-replace.)*

## Phase 5 — QUALITY ⬜ (the small-model correctness levers; ~4 passes)
- **5.1 UPG-05 constrained decoding (M)** — GBNF grammars + Outlines for tool-call/JSON reliability.
- **5.2 UPG-01 hybrid escalation (M)** — bigger-local / BYO-cloud toggle; ends the quality objection.
- **5.3 UPG-14 governor auto-cap (S)** + **UPG-20 self-consistency (M)**.
- **5.4 UPG-21 project-aware coding context (M)** — repo map, symbol index, @file.
**Acceptance:** measurable quality lift (eval harness, UPG-22) vs today; tool calls reliable.

## Phase 6 — ECOSYSTEM & INTEROP ⬜ (~3 passes)
- **6.1 UPG-06 Ollama backend + UPG-41 Ollama API (M)** — drive Ollama; be drivable by Open WebUI.
- **6.2 UPG-40 first-class `/v1` (S)** — documented OpenAI drop-in.
- **6.3 UPG-12 MCP-only plugins (M)** — converge routers + cursor-mcp; **UPG-09 Open WebUI decision**.
**Acceptance:** Layla is a drop-in on OpenAI/Ollama clients; plugins are MCP-only.

## Phase 7 — PRODUCT POLISH ⬜ (~3 passes)
- **7.1 UPG-24 honesty card (S)** — realistic per-tier expectations at setup.
- **7.2 UPG-31 Doctor panel (S)** — surface `selftest` live in the UI.
- **7.3 UPG-23 multilingual/Castilla flagship (M)** + **UPG-22 eval harness in CI (M)**.
- **7.4 UPG-35 finish (S)** — HTTP-range resume + catalog `sha256`/`size` + disk pre-check.
**Acceptance:** Castilla is a first-class story; quality is measured in CI; downloads fully robust.

## Phase 8 — LATER / DREAM ⬜ (post-ready; ~5+ passes)
UPG-07 (RapidOCR/Piper), UPG-08 (DSPy), UPG-13 (Tauri shell), UPG-33 (memory sync),
UPG-34 (VS Code/CLI/mobile clients), UPG-36 (a11y/command palette/recipes), UPG-37 (MCP marketplace),
UPG-42 (HF Hub/ONNX). Not required for "ready"; the movement roadmap.

---

## Execution order (dependency-correct)

```
Phase 1 GUI  ─┐  (parallel-safe; needs your sign-off)
Phase 2 Install ┘  → prove it works
        ↓
Phase 3 Scope cut  → focus
        ↓
Phase 4 Foundation swaps (absorbs R9)  → lighter/faster memory
        ↓
Phase 5 Quality  → good answers on small models
        ↓
Phase 6 Ecosystem  → drop-in interop
        ↓
Phase 7 Polish  → Castilla flagship, measured, robust  ← TRULY READY gate here
        ↓
Phase 8 Later/Dream (optional, post-ready)
```

**Truly-ready gate = end of Phase 7** (Phase 8 is the movement, not the release).
Honest total to the gate: **~23 focused passes**; +Phase 8 ≈ 28.

## The one dependency I can't remove
**Phase 1 (GUI) needs your eyes.** I build each pass against the running app and show you;
you say "locked" or "again." Everything else I can drive to green autonomously.
