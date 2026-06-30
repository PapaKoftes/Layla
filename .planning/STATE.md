# Project State

**Project:** Layla — **companion-first**, private, low-end-friendly, multilingual local AI with a soul;
personalities = hardware-adaptive domain kits (coding is one kit, not the headline).
**Updated:** 2026-06-30
**Read first:** [`STRATEGY.md`](STRATEGY.md) (the wedge + cuts) · [`UPGRADES.md`](UPGRADES.md) (the backlog) ·
[`ROADMAP.md`](ROADMAP.md) (MVP/V2/V3/Dream tiers).

## WHERE WE ARE — remediation done; strategy re-tiered; install proven on this machine

- **Remediation complete:** R1–R8 + R10 shipped. Security (R5 `remote_api_key` gating), CI inference
  smoke (R1), config consolidation (R3), two-store backup (R4), **TestClient suite un-skipped + 12
  hidden bugs fixed (R6)**, **206 back-compat shims removed → canonical imports (R8)**, backend audit
  (R10). **Suite: 2508 passed, 0 failed.** R9 (god-module splits) is the last open item → now UPG-00b.
- **Installer is real and self-verifying:** `scripts/selftest.py` (deep self-test: model load + a REAL
  inference turn in a subprocess so a SIGILL is caught, not fatal) gates `install/fresh_install.ps1`
  (+ `-Verify` doctor, `-Pair`). Guided pairing `scripts/pair.py` (HOST rotates a hashed token; CLIENT
  verifies the link). `connect_tunnel.ps1` made R5-safe.
- **Proven end-to-end on this box (16 GB / CPU-only / tier1 = the friend's tier):**
  selftest `--server` PASS — `/health` (197 tools), `/ui` (200), `/agent` (200); core selftest PASS
  **0 warnings** (model + embedder + SQLite+NumPy fallback RAG).
- **RAG-grounding fix:** compiler-free installs no longer disable semantic memory (the fallback serves
  it). UPG-02 (sqlite-vec) will supersede the bespoke fallback.
- **UI:** reverted to the clean original damask; **direction locked** — clean/streamlined (mockup #1) +
  real-historical-art ornament, kept subtle. Live GUI-polish pass deferred to the running app (now possible).
- **Strategy wrapped into GSD (this update):** STRATEGY.md + UPGRADES.md added; ROADMAP re-tiered.

## Measured truths (still drive all decisions)
- On a 16 GB CPU box the recommender picks **Qwen2.5-Coder-3B** (loads + completes a real turn — verified
  by selftest). 7B-Q4 ≈ 5 tok/s here; usable for focused edits, not from-scratch self-verification.
- **Small-model-on-CPU cannot win "serious coding" vs the cloud** → coding is a strong *aspect*, made
  credible by **hybrid escalation (UPG-01)**, not the headline. Lead with private + low-end + multilingual + soul.
- Speculative decoding is unhelpful on CPU (measured slower). RAG grounding is the #1 correctness lever for small models.
- **Reuse > reinvent:** sqlite-vec / FastEmbed / FlashRank / Outlines / Ollama-backend shrink code AND
  improve low-end quality (UPGRADES Tier A).

## Next action (MVP tier — see ROADMAP "Tiers" + UPGRADES)
1. **Win-win OSS swaps:** UPG-10 engine abstraction → UPG-02 sqlite-vec → UPG-03 FastEmbed/model2vec →
   UPG-05 constrained decoding. (Each deletes hand-rolled code.)
2. **Scope cut** (UPG-00a) + **finish R9** (UPG-00b) + **retire trap installers** (UPG-00c).
3. **Doctor panel** (UPG-31) + **honesty card** (UPG-24) + **live GUI polish** to the clean #1 look.
4. Then V2 opens with **hybrid escalation (UPG-01)**.

## Key context for any session
- The dev box mirrors the target user (16 GB / CPU / no-GPU) — measure here, it transfers.
- Verify against implementation, not docs; report measurements honestly even when they contradict prior claims.
- Plugins = **MCP only**; engine behind one interface ({llama.cpp, Ollama, OpenAI-compatible}).
- UI work must not require backend rewrites beyond additive endpoints; the API is the contract.
- `runtime_config.json` is gitignored (local). Commit cadence: feature commits separate from
  `docs(planning)` bookkeeping; end messages with the Co-Authored-By trailer.
- Heavyweight, mostly-historical planning docs: `REMEDIATION-PLAN.md` (R1–R10, done), `WATERTIGHT-PLAN.md`,
  `UNIFIED-ROADMAP.md`, `MILESTONE-friend-ready.md`, `FULL-HISTORY.md`, `codebase/` map, `research/`.
