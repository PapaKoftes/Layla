# Milestone: Friend-Ready Layla

**Started:** 2026-06-29 · **Goal:** A friend with a **16GB-RAM, CPU-only laptop** can install Layla and get **very good, benchmarked programming help**, through a **completely redesigned UI**.

This supersedes the remediation-only focus. Remediation phases 1–10 continue as the *hardening substrate*; this milestone adds two product tracks on top.

## Locked decisions (2026-06-29)
| Decision | Choice | Implication |
|---|---|---|
| Friend's hardware | ~16GB RAM, no real GPU | CPU-bound → 7B-class Q4 coder model is the ceiling |
| Primary coding model | **Qwen2.5-Coder-7B-Instruct Q4_K_M** (~4.7GB) | Strong CPU coder; 3B-Q4 as a speed fallback |
| Sequencing | **Both tracks in parallel** | Visible progress on app-quality and UI together |
| "Benchmarked" | **Standard coding benchmark** (HumanEval / MBPP pass@1) | Objective, comparable scorecard per model |
| UI build | **Modern framework (React + Vite, TS)** | Built to static assets, served by the existing FastAPI backend |

## Proven foundation (today)
- Python 3.12.10 installed; `.venv-test` real test env built; **205 tests pass on 3.12**.
- Real model downloaded via Layla's own downloader; **live CPU inference confirmed** (SmolLM2-360M: 0.2s load, 43.7 tok/s).
- `llama-cpp-python` CPU wheel installs cleanly (no compiler needed).

---

## Track A — Daily-Driver (programming-grade, benchmarked, transferable)
**A1. Coding model** — Qwen2.5-Coder-7B-Instruct Q4 downloading; register in `model_catalog.json` + set as default; keep 3B-Q4 as the speed option. *(in progress)*
**A2. CPU-only install completeness** — the transferability blocker. `chromadb`/`chroma-hnswlib` need a C++ build; `torch` (embeddings) didn't install. Resolve with prebuilt CPU wheels (or a `use_chroma:false` + lightweight vector fallback) so `pip install` works on a fresh CPU Windows box **with no compiler**.
**A3. Full-app E2E** — boot `serve.py` + agent loop + tools; drive a real coding task through the HTTP API end-to-end (not just raw llama).
**A4. Benchmark harness** — a HumanEval/MBPP pass@1 runner against the local model via `services.llm_gateway`; emit a scorecard (model, quant, tok/s, pass@1). Folds into remediation Phase 3/4 (verifiable core / eval).
**A5. One-command install** — a clean `install/` path that sets up interpreter + venv + model on her laptop. The "transfer right now" deliverable.

## Track B — The Layla Interface (UI from scratch)
Aesthetic: **black + dark-purple**, **Warframe** sci-fi paneling & glyphs, motion-rich.
**B1. Frontend foundation** — `ui-next/` Vite+React(TS); design-token system (palette, type scale, Warframe panel/glyph SVG kit); FastAPI serves the static build.
**B2. Core chat** — the agent chat experience in the new aesthetic, wired to the existing API (streaming, tool calls, memory views).
**B3. Personality character creator (BG3-style)** — create/edit Layla "aspects": name, sigil/portrait, trait sliders, voice, synthesized system-prompt. Persists into the existing personality/aspects backend.
**B4. Adaptive personality quiz (Fallout-NV style)** — a S.P.E.C.I.A.L.-style intake quiz that shapes Layla's default personality; answers map to config + aspect weighting.
**B5. Polish & motion** — Warframe-grade transitions, glyph animation, optional sound cues; responsive.

## Cross-cutting
- Everything stays **local-first** and regression-guarded (tests on `.venv-test`).
- Backend API is the contract between the new UI and the agent core — UI work must not require backend rewrites beyond additive endpoints.

## UI aesthetic — LOCKED: "Warframe-mystic" midpoint
The blend of the new sci-fi direction and the original identity:
- **Structure** from the Warframe direction: angular cut-corner panels (`--wf-cut`), Orokin-style glyphs/sigils, HUD status chips, energy edge-lines.
- **Soul** from the original: near-black `--bg #0a0008`, magenta `--accent #c0006a` signature, **per-aspect colors** (morrigan=crimson `#8B0000`, nyx=indigo, echo=blue, eris=brown, cassandra=teal, lilith=wine); the active aspect re-themes the whole shell via `--asp`.
- **Texture**: the existing organic per-aspect SVG patterns (morrigan-circuits, nyx-constellations, …) as panel watermarks. The sci-fi frame *holds* the personality. (Mockup shown 2026-06-29.)

## Canonical plan locations (this milestone is now folded into the GSD plan)
- `PROJECT.md` — thesis (domain-kit personalities), viability framing, two-layer direction.
- `ROADMAP.md` → "Milestone 2 — Friend-Ready" — Track A (A1–A7) + Track B (B1–B5).
- `REQUIREMENTS.md` — REQ-70..81.
- `STATE.md` — live runtime status, measured truths, track status, next action.

## Progress log
- **2026-06-29:** Stack proven (A1 ✅), kit recommender shipped (A2 ✅, REQ-71). Measured: 7B ≈ 5 tok/s, good edits, **spec-decoding unhelpful on CPU** (corrected the kit to not overclaim). Market-viability audit → personal-first + curation-moat framing. UI midpoint aesthetic locked + mockup shown.

## Next actions
1. **(A3)** compiler-less `chromadb`/`torch` install — the transferability blocker.
2. **(A4)** wire `recommend_kit` into the `first_run` onboarding/startup sequence.
3. **(A5)** HumanEval/MBPP benchmark harness → first scorecard for Qwen-Coder-7B.
4. **(B1)** scaffold `ui-next/` (Vite+React+TS) with the locked Warframe-mystic design tokens.
