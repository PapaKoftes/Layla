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

## Next actions
1. (A1) finish Qwen-Coder download → smoke a real coding generation.
2. (A2) resolve `chromadb`/`torch` CPU install so the stack is complete on a compiler-less box.
3. (A4) scaffold the benchmark harness.
4. (B1) scaffold `ui-next/` with the design system + a first Warframe-aesthetic shell.
