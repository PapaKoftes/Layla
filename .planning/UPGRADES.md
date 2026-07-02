# Layla — Additions & Upgrades Backlog (2026-06-30)

Every addition/upgrade from the strategic evaluation, as trackable items. Governed by
`STRATEGY.md` (the wedge + reuse-don't-reinvent). Prioritized by **impact × effort** and
tagged with a **tier** (MVP / V2 / V3 / Dream) and an **action** (interface / embed / fork /
build / cut). `[ ]` open · `[~]` partial · `[x]` done · `[—]` cut.

Legend — action: **interface** = call it as a dependency; **embed** = vendor/integrate the lib;
**fork** = take + modify; **build** = our own; **cut** = remove from scope.

---

## Tier 0 — Maintenance-debt paydown (do alongside everything; the real long-term killer)

- `[ ]` **UPG-00a · cut · MVP** — **Scope cut to the wedge.** Park/remove: cluster/work-unit mesh,
  tribunal (6-aspect) council, maturity gamification as a headline, and the long tail of the 197
  tools (keep a curated core per aspect). *Why: one team cannot maintain 10 products.* (STRATEGY §mistake)
- `[~]` **UPG-00b · build · MVP** — **R9 god-module splits** (vector_store/migrations/tool_dispatch/
  cursor-server) via aggregator pattern. Last "nothing-deferred" item; pairs with the OSS swaps that
  delete code. *(R1–R8 + R10 already done.)*
- `[x]` **UPG-00c · cut · MVP** — **Retire trap installers** (root `install.ps1`/`INSTALL.bat` —
  compiler path, 3.14-breaking). Redirect to `fresh_install.ps1`. *(Docs already deprecate them.)*

## Tier A — OSS reuse swaps (win-wins: less code AND better low-end quality)

- `[ ]` **UPG-01 · build+interface · MVP · (Impact H × Effort M)** — **Hybrid escalation.** One toggle
  to route a turn to a bigger local model or a BYO-key cloud model when the user wants quality.
  *Neutralizes the entire small-model quality objection.* Foundation = engine abstraction (UPG-10).
- `[ ]` **UPG-02 · embed · MVP · (H × M)** — **sqlite-vec** (asg017/sqlite-vec, Apache-2.0) **replaces the
  bespoke SQLite+NumPy `FallbackCollection`.** Same no-compiler property, far more capable. Deletes
  hand-rolled vector code.
- `[ ]` **UPG-03 · embed · MVP · (H × M)** — **FastEmbed** (qdrant/fastembed, Apache, ONNX) or
  **model2vec** (MinishLab, MIT, static embeddings, ms-CPU) **replaces torch+sentence-transformers** for
  embeddings. Drops hundreds of MB + huge speedup on a potato. Keep sentence-transformers only as an
  opt-in "quality" embedder.
- `[ ]` **UPG-04 · embed · V2 · (M × L)** — **FlashRank** (PrithivirajDamodaran, Apache) — tiny CPU
  cross-encoder reranker; replaces the heavy BGE cross-encoder on low-end tiers.
- `[ ]` **UPG-05 · embed · MVP · (H × L)** — **Constrained decoding**: llama.cpp **GBNF grammars** +
  **Outlines** (dottxt-ai/outlines, Apache) for tool-call/JSON reliability. *Biggest small-model
  correctness win; cheapest.* (Complements existing `instructor`.)
- `[ ]` **UPG-06 · interface · V2 · (H × M)** — **Optional Ollama backend** (ollama/ollama, MIT). Let
  Layla drive Ollama instead of managing llama-cpp wheels/SIGILL itself — solves the hardest install
  problem and unlocks its model library. Keep llama.cpp as the embedded default.
- `[ ]` **UPG-07 · embed · V2 · (M × M)** — Lighter OCR: **RapidOCR** (Apache, ONNX) or **docTR**
  (Apache) instead of easyocr's heft. **Piper TTS** (rhasspy/piper, MIT) alongside kokoro.
- `[ ]` **UPG-08 · interface · V2 · (M × M)** — **DSPy** (stanfordnlp/dspy, MIT) to systematically
  optimize prompts/pipelines for weak models — directly serves "good answers from small models."
- `[ ]` **UPG-09 · decision · V2 · (H × —)** — **Open WebUI positioning call**: evaluate making
  Layla's differentiated layer (aspects+kits+soul) ride on/interop with Open WebUI (MIT, ~50k★) vs
  keeping the custom UI only for the soul we can't get there. *Strategic, not just technical.*

## Tier B — Architecture upgrades

- `[ ]` **UPG-10 · build · MVP · (H × M)** — **Engine abstraction**: one interface over
  {embedded llama.cpp, Ollama, OpenAI-compatible remote}. Foundation for UPG-01/06. Removes
  SIGILL/wheel pain as a hard dependency.
- `[ ]` **UPG-11 · embed · MVP · (H × M)** — **One SQLite memory file**: sqlite-vec (vectors) +
  FTS5 (keyword, have) + FastEmbed (embeddings) + FlashRank (rerank). Delete the bespoke store.
- `[~]` **UPG-12 · build · V2 · (M × M)** — **MCP-only plugin system.** Converge routers +
  `cursor-layla-mcp` onto MCP servers; never invent a second plugin model. (Client+server exist.)
- `[ ]` **UPG-13 · adopt · V3 · (M × M)** — **Tauri desktop shell** (Rust, tiny) around FastAPI+UI,
  replacing the PyInstaller `launcher.py`.
- `[~]` **UPG-14 · build · MVP · (M × L)** — **Governor auto-caps deliberation on CPU** (solo/debate
  only on weak tiers; reserve council for GPU). Hooks already exist in `resource_governor`.

## Tier C — AI / learning features

- `[ ]` **UPG-20 · build · V2 · (M × M)** — **Self-consistency voting** for factual/reasoning turns.
- `[ ]` **UPG-21 · build · V2 · (H × M)** — **Project-aware coding context**: repo map, symbol index,
  `@file` mentions — table stakes vs Continue/Aider for the coding aspect.
- `[ ]` **UPG-22 · interface · V2 · (M × M)** — **Eval harness in CI**: HumanEval/MBPP (have) +
  **SWE-bench-Lite** (agentic) + **MTEB** (embeddings) + **RAGAS** (retrieval). Quality measured, not asserted.
- `[ ]` **UPG-23 · build · V2 · (M × M)** — **Multilingual polish (Castilla flagship)**: Spanish eval
  (FLORES-200/XQuAD subsets), language-assist kit, first-class non-English UX.
- `[ ]` **UPG-24 · build · MVP · (M × L)** — **Honesty card**: realistic, benchmarked expectations per
  kit per hardware tier shown at setup (anti-overpromise).

## Tier D — Product / QoL / ecosystem

- `[x]` **UPG-30 · build · MVP** — **Deep startup self-test** (`scripts/selftest.py`) — *shipped 2026-06-30*.
- `[ ]` **UPG-31 · build · MVP · (M × L)** — **Doctor panel** in the UI (surface selftest live).
- `[x]` **UPG-32 · build · MVP** — **Guided pairing wizard** (`scripts/pair.py`) — *shipped 2026-06-30*.
- `[ ]` **UPG-33 · build · V3 · (M × M)** — **Knowledge/memory sync** across paired instances
  (extends pairing).
- `[ ]` **UPG-34 · build · V3 · (M × M)** — **Clients**: VS Code extension, CLI, **mobile PWA via the
  pairing tunnel** (phone → home instance). PWA/service-worker already present.
- `[~]` **UPG-35 · build · V2 · (M × M)** — GGUF magic-byte validation done (setup-ready + downloader); resume/atomic + catalog checksums remain. **Safe browser model download**: route `/setup/download`
  through `model_downloader` (resume/atomic/validate); populate catalog `sha256`/`size`; disk pre-check;
  consolidate the 4 model catalogs to one.
- `[ ]` **UPG-36 · build · V3 · (L × M)** — Accessibility (full WCAG pass; started), command palette,
  recipes (saved tool chains), file-watch/scheduled agent triggers.
- `[ ]` **UPG-37 · build · Dream · (M × H)** — **MCP kit marketplace**: community-shipped aspect kits.

## Tier E — Standards & interop (be a drop-in, not an island)

- `[~]` **UPG-40 · build · MVP** — First-class **OpenAI `/v1`** server (have `openai_compat`; make it a
  documented drop-in so any OpenAI client can use Layla).
- `[ ]` **UPG-41 · build · V2** — **Ollama API** compatibility (so Open WebUI/others drive Layla).
- `[ ]` **UPG-42 · build · V2** — **HF Hub** pull + checksums (fixes empty-catalog `sha256`); **ONNX**
  for CPU embeddings/OCR; **GGUF** (have).

---

## Shipped this session (2026-06-30) — the substrate these build on

- **R1–R8 + R10** remediation complete (security, CI inference smoke, config consolidation, two-store
  backup, real-`remote_api_key` gating, TestClient suite un-skipped + 12 hidden bugs fixed, **206 shims
  removed → canonical imports**, inference-backend audit). Suite: **2508 passed**.
- **RAG-grounding fix** — compiler-free installs no longer disable semantic memory; the SQLite+NumPy
  fallback serves RAG (the bug UPG-02 will then supersede with sqlite-vec).
- **Self-test-gated installer** + **guided pairing** + **R5-safe tunnel** — proven end-to-end on a
  16 GB CPU box (= the friend's tier): selftest `--server` PASS (/health 197 tools, /ui 200, /agent 200),
  core selftest PASS 0 warnings (model + embedder + fallback RAG).
- **UI** reverted to the clean original damask (direction locked: clean/streamlined #1 + real-art
  ornament, subtle); live GUI-polish pass deferred to the running app.
