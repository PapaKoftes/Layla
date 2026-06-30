# Layla — Session Handoff (continue here)

**Purpose:** hand over everything this Claude Code session was doing so a new session
(on the laptop or anywhere) continues with full intent intact. Read this, then
`.planning/STATE.md`, then keep driving the GSD loop. Updated 2026-06-29.

---

## 1. What Layla is (and the sharpened thesis)
A **local-first, self-hosted AI agent** (Python/FastAPI + llama.cpp) — chat → model
decides → approved tool runs → verified answer, all on your machine, no cloud, with
approval-gated file/shell/code mutation.

**The thesis that emerged:** personalities ("aspects") are **hardware-adaptive domain
kits**, not skins. Each aspect = {best local model for *this* machine + curated
skills/tools + tuned prompt + settings + visual identity}. The installer **detects the
hardware and provisions the optimal kit per domain**. "morrigan" = the coding kit.

## 2. Honest framing (don't lose this)
A market-viability audit concluded: as a head-to-head product Layla is **redundant**
(Cline/Aider/Continue, Ollama/Jan/Open WebUI, SillyTavern all dominate). So we operate
**personal-first** — a delightful tool for a friend on a 16GB CPU laptop — with the
**curation of per-domain kits + the aesthetic** as the only real novelty, and a
`/v1`-backend "pivot to a layer on an incumbent" as the hedge if it must scale.

## 3. Runtime reality (the old "can't run here" caveat is GONE)
- **Python 3.12** installed; `.venv-test` runs the full suite + **real inference**.
- The dev box **== the friend's tier** (4-core / 16GB / no-GPU), so measurements transfer.
- Models on disk (gitignored): `Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf`, `SmolLM2-360M-…`.

## 4. Measured truths (these drive every decision)
- 7B-Q4 ≈ **5 tok/s** on this CPU tier; **memory-bandwidth-bound** (thread tuning doesn't help).
- Quality: **good at focused edits/specs**, weaker on complex from-scratch self-verification.
- **Speculative decoding is unhelpful on CPU** (measured *slower*).
- **Benchmark**: Qwen-Coder-7B = **100% pass@1** on the curated 10-problem set (easy-to-medium
  → strong fundamentals, not saturation; add HumanEval-164 for a discriminating score).
- ⇒ "Best local coding" = best *responsive* model (7B) + **scaffolding** (repo-map, diff-edits,
  GBNF, codebase RAG), not a bigger model.

## 5. DONE & verified (don't redo)
| Area | Status |
|---|---|
| Security: trust-boundary/auth (REQ-10/11), keyring secrets (REQ-12) | ✅ Phase 1, 58 tests |
| Legal: copyleft CI guard + THIRD_PARTY (REQ-02) | ✅ Phase 2, 11 tests |
| Privacy: audit-log secret/PII redaction (REQ-43) | ✅ 11 tests |
| Local-coding foundation: inference + `recommend_kit` + **compiler-free memory fallback** (REQ-70/71/72) | ✅ Phase 11, 21+87 tests |
| Verifiable core: **suite green on real stack (1734 pass)** + **benchmark harness** (REQ-74) | ✅ Phase 12 (2/3) |
| Fresh-install + tunnel + this handoff | ✅ `install/`, this file |

Full suite: **1734 passed, 0 failed** on 3.12 (`cd agent; ../.venv-test/Scripts/python.exe -m pytest -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint"` — set `CI=1` to apply the canonical exclusions).

## 6. OPEN — the work to finish (GSD phases, priority order)
See `.planning/ROADMAP.md` (Milestone 2, Phases 11–19) for full criteria. Next up:
1. **Phase 12 criterion 2** — `inference-smoke` CI job (seam ready: `LAYLA_TEST_REAL_LLM`; SmolLM2 on disk) + gate `release.yml`.
2. **Phase 13** — onboarding wires `recommend_kit` into `first_run`; per-domain kit *contents* (skills/prompts), not just a model; kit upgrades (embedding selection, IQ-quants, benchmark-driven choice).
3. **Phase 14** — coding-quality scaffolding (repo-map, search/replace diff-edits, GBNF, codebase RAG via the fallback store, KV cache). *The biggest quality lever.*
4. **Phase 15** — full-app E2E + one-command install (mostly built — see `install/`) + `/v1` seam + portable character cards.
5. **Phases 16–19** — the **Warframe-mystic UI** from scratch (`ui-next/` Vite+React+TS): foundation → core chat → BG3 aspect creator + Fallout-NV intake quiz → polish. Aesthetic is LOCKED (near-black `#0a0008` + magenta `#c0006a`, per-aspect colors, `--wf-cut` angular panels, glyph/sigil SVGs, organic per-aspect watermarks; the active aspect re-themes the shell).

Known minor issue: local `_TESTCLIENT_FILES` hang on `.venv-test` (httpx version; CI-skipped) — pin/upgrade httpx so they run locally too.

## 7. Install / connect (built this session — see install/)
- **Fresh laptop:** `git clone … && powershell -File install\fresh_install.ps1` (compiler-free; auto-detects HW → downloads the right kit). Full guide: `install/INSTALL.md`.
- **Connect to main PC (remote tunnel):** `install\connect_tunnel.ps1` on the host (cloudflared + bearer token; secure by REQ-10/11).
- **Provision/re-provision a model:** `agent/install/provision_model.py [--prefer quality|balanced|speed] [--dry-run]`.

## 8. How to continue (GSD discipline)
- The plan lives in `.planning/`: `PROJECT.md` (thesis), `ROADMAP.md` (phases 1–19 + Progress + Requirement Coverage), `REQUIREMENTS.md` (REQ-01..85), `STATE.md` (live status), `phases/<NN>/{CONTEXT,VERIFICATION}.md`.
- Loop per phase: read CONTEXT → execute the slices → write VERIFICATION → update ROADMAP/STATE → atomic commit.
- **Verify against implementation, not docs.** Every change gets a runnable test. **Report measurements honestly even when they contradict earlier claims** (we corrected the spec-decoding overclaim and two stale security tests this way).
- Commit style: feature commits separate from `docs(planning)`; end messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Don't push/commit unless asked.
- Tests run on `.venv-test` (3.12). The 3.14 box can only run pure-stdlib tests.

## 9. Pointers
- Kit engine: `agent/install/model_selector.py::recommend_kit` · catalog: `agent/models/model_catalog.json`
- Memory fallback: `agent/layla/memory/fallback_store.py` (compiler-free vector store)
- Benchmark: `scripts/benchmark_coding.py` · scorecards: `benchmarks/`
- Security: `agent/services/auth.py`, `tunnel_auth.py`, `secret_store.py`, `secret_filter.py`
- UI today: `agent/ui/` (the original; palette + per-aspect patterns to carry into `ui-next/`)
