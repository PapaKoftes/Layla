# Layla — The Full In-Depth List (2026-07-03)

Everything, in one place: the open work + optimizations + reuse-don't-reinvent swaps + the
potato-tier playbook. Merges [`gui-audit/OPEN-ITEMS.md`](gui-audit/OPEN-ITEMS.md) (issues/
deferrals/unbuilt) with [`UPGRADES.md`](UPGRADES.md) (backlog) and new analysis.

> Note: the two parallel research agents for this pass hit the account session limit and
> returned empty, so the reuse + potato sections below are compiled by hand from the audit,
> UPGRADES, and direct analysis. file:line cites are from the audit where known; a few
> magnitudes are estimates flagged with "~".

---

## PART 1 — Open items (full detail in OPEN-ITEMS.md)
- ✅ 16 fixed+verified · ⏸️ 7 deferred-with-reason · ❌ ~67 open audit issues · 🏗️ ~20 never-built.
- Headline gaps: dead chrome (retry btn, file-chips, ctx_viz, /usage, diff stub, image→vision),
  ~20 backend-without-UI (remote/tunnel/tailscale/sync, missions, agents, metrics/audit),
  8 architectural duplications, and G2–G6 of the repaint (5/6 unbuilt).

---

## PART 2 — Reuse-don't-reinvent (delete hand-rolled code, gain speed/quality)

Action key: **swap** = replace ours with the lib · **add** = add lib alongside · **collapse** = pick one of a duplicate pair and delete the other.

### Already in UPGRADES (confirmed — these DELETE bespoke code)
| # | Hand-rolled today | Replace with | Win | UPG |
|---|---|---|---|---|
| R1 | SQLite+NumPy `FallbackCollection` + hand cosine (`vector_store.py`, `fallback_store.py`) | **sqlite-vec** (Apache, no compiler) | deletes ~vector code, faster ANN, still offline | UPG-02/11 |
| R2 | torch + sentence-transformers embeddings | **model2vec** (static, MIT) / **FastEmbed** (ONNX) | −hundreds of MB RAM, ms-CPU embeds | UPG-03 |
| R3 | heavy BGE cross-encoder rerank | **FlashRank** (Apache, ONNX) | tiny CPU reranker | UPG-04 |
| R4 | regex/hand tool-call + JSON parsing | **Outlines** / **llguidance** / llama.cpp **GBNF** (+ instructor) | reliable tool calls on small models | UPG-05 |
| R5 | llama-cpp wheel/SIGILL management | optional **Ollama** backend behind engine-abstraction | kills the #1 install failure mode | UPG-06/10 |
| R6 | easyocr heft; kokoro-only TTS | **RapidOCR/docTR** (ONNX); add **Piper** | lighter OCR; robust TTS | UPG-07 |
| R7 | hand prompt-tuning | **DSPy** (MIT) | systematically better weak-model prompts | UPG-08 |
| R8 | PyInstaller `launcher.py` | **Tauri** (Rust, tiny) | smaller, native shell | UPG-13 |

### NEW candidates (not in UPGRADES — found in the audit / analysis)
| # | Hand-rolled today | Replace with | Win | Risk |
|---|---|---|---|---|
| R9 | token/context estimation by char÷4 heuristics (`context_manager.token_estimate_messages`) | **tiktoken** or the model's own `llama_cpp` tokenizer | accurate context budgeting → fewer overflow/truncation bugs | low |
| R10 | hand dict-merge config in the `runtime_safety` god-module | **pydantic-settings** / pydantic models | typed+validated config; kills the "inert key / wrong-shape / default-mismatch" class of bugs (F16, A1, `syncthing_*`) | moderate |
| R11 | custom study/scheduler loops (`scheduler_study_*`) | **APScheduler** | robust cron/interval + persistence; less bespoke threading | low |
| R12 | model download via `urlretrieve` (non-resumable) | **huggingface_hub** `hf_hub_download` (resume + checksum + mirror) or httpx+Range | resumable, verified downloads (also UPG-35/42) | low |
| R13 | scattered `requests`/`urllib` calls | **httpx** (timeouts/retries/async/HTTP2), one client | consistent networking, fewer hangs | low |
| R14 | custom retry/backoff loops | **tenacity** | declarative, tested backoff | low |
| R15 | hand-rolled dict/LRU caches | `functools.lru_cache` / **diskcache** | bounded + persistent caches | low |
| R16 | custom SSE framing in `/agent` | **sse-starlette** `EventSourceResponse` | correct heartbeats/backpressure/cancel | moderate |
| R17 | bespoke fuzzy/string matching | **rapidfuzz** (prebuilt wheels) | faster, correct fuzzy match | low |
| R18 | two vector paths, two plan stores, two governors, two skill registries, two aspect models, two onboarding | **collapse** (keep the better side, delete the other) | −a lot of code + ends "which is real?" confusion (§D) | moderate–invasive |
| R19 | server-side markdown/sanitize (if any) | reuse vendored marked/DOMPurify; **bleach**/`markdown-it-py` server | one sanitizer, XSS-safe | low |
| R20 | whisper STT footprint | keep faster-whisper; offer **whisper.cpp** on potato | lower RAM STT option | low |

---

## PART 3 — Performance optimizations (general, all tiers)
| # | Lever | Win | Notes |
|---|---|---|---|
| P1 | **Prefix/prompt KV caching** — reuse system-prompt KV across turns (`cache_prompt`, `n_keep`) | big first-token latency drop | likely not enabled today |
| P2 | **KV-cache quantization** (`type_k`/`type_v` = q8_0 or q4_0) | ~½ KV RAM → bigger `n_ctx` on same box | expose as a tier knob |
| P3 | **Lazy imports** of torch / sentence-transformers / chromadb / whisper / tts | faster startup + lower idle RAM | import only when the feature runs |
| P4 | **Model hot-swap + param labeling** — reload on switch; mark live (temp/top_p) vs load-time (n_ctx/gpu/batch/threads) | fixes audit "silent no-op until reload"; add a "Reload model" button | audit [04] |
| P5 | **n_threads = physical cores**, tuned `n_batch`/`n_ubatch`, **mmap on**, mlock off on low-RAM | steadier tok/s, no thrash | some hardcoded today |
| P6 | **Speculative decoding** (tiny draft model) where supported | faster decode | capable tiers |
| P7 | **Embedding cache** (content-hash → vector) | avoids recompute on repeated recall | pairs with R2 |
| P8 | **Request serialization + backpressure** (`llm_serialize_per_workspace`) | prevents OOM under concurrency | knob exists; verify enforced |
| P9 | **Streaming end-to-end** (no full-buffer) + **chat virtualization** for long threads | responsive UI, less DOM/GC | UI |
| P10 | **Resumable + checksummed downloads** + disk pre-check | no re-downloading multi-GB models | R12 / UPG-35 |

---

## PART 4 — Potato-tier playbook (make it fly on a weak CPU box)

**The single biggest win:** ship **static/ONNX embeddings (model2vec/FastEmbed) + sqlite-vec** so
semantic memory stays ON even on a potato — dropping **torch entirely** saves hundreds of MB and
resolves the current `use_chroma=false` tradeoff (the wedge promise "it remembers" holds on low-end).

**Adaptive per-tier auto-config** (detect RAM/CPU/GPU at setup → set everything below automatically;
extend the `potato` preset into a real matrix; show the **honesty card**, UPG-24):

| Knob | 🥔 Potato (≤8GB, weak CPU) | ⚙️ Modest (8–16GB) | 🚀 Capable (16GB+/GPU) |
|---|---|---|---|
| Model | Qwen2.5-Coder-1.5B/3B Q4_K_M (or IQ4_XS) | 7B Q4_K_M | 14B+ Q4/Q5 or GPU offload |
| `n_ctx` | 2048 | 4096 | 8192+ |
| KV cache | q4_0 | q8_0 | f16 |
| Embeddings | model2vec (static) | FastEmbed (ONNX) | sentence-transformers (opt) |
| Semantic memory | **on** (sqlite-vec + static) | on | on + rerank |
| Rerank | off | FlashRank | BGE cross-encoder |
| Deliberation | solo only | solo/debate | council/tribunal |
| Tools | curated core per aspect | most | full |
| Background/autonomy | off / whisper-throttled | breathe | sprint |
| UI | low-fx, reduced motion, virtualized | normal | full |
| torch loaded? | **no** | optional | yes |

Governor already has hooks (`resource_governor`, UPG-14) — wire it to enforce this matrix, not just idle-throttle.

---

## PART 5 — Product / small-model quality levers
- **Constrained decoding** (R4/UPG-05) — the cheapest correctness win.
- **Hybrid escalation** (UPG-01) — one toggle to a bigger local / BYO-cloud model; ends the quality objection.
- **Self-consistency voting** (UPG-20) for factual/reasoning turns.
- **Project-aware coding context** (UPG-21) — repo map + symbol index + `@file`.
- **Eval harness in CI** (UPG-22) — HumanEval/MBPP/SWE-bench-Lite/MTEB/RAGAS; measure, don't assert.
- **RAG quality** — HyDE (have) + hybrid + rerank + chunk tuning + dedup; the new `min_confidence` floor.
- **DSPy** prompt optimization (UPG-08).

---

## PART 6 — One merged priority order

**P0 — now (cheap × high, and they DELETE code or shrink RAM):**
1. Finish the kill-or-wire open items (the remaining ❌ dead chrome + partials).
2. **Static embeddings + sqlite-vec** (R1+R2) → potato semantic memory + drop torch. *Biggest single win.*
3. **Constrained decoding** (R4) → reliable tool calls on small models.
4. **KV-quant + prefix cache + lazy imports** (P1–P3) → more context, faster start, less RAM.

**P1 — next (unlocks quality + robustness):**
5. **Engine abstraction + Ollama + hybrid escalation** (R5/UPG-01/10) → kills install pain + quality objection.
6. **FlashRank** (R3) + **tiktoken** context accuracy (R9) + **pydantic-settings** config (R10).
7. **Adaptive per-tier auto-config + honesty card** (Part 4 / UPG-24); **model hot-swap + param labels** (P4).

**P2 — then (pay down debt + measure):**
8. **Collapse the 8 duplications** (R18) → delete code, end "which is real?".
9. **Project-aware coding** (UPG-21) + **eval harness** (UPG-22) + **DSPy** (UPG-08).
10. Surface the backend-without-UI cluster (remote/tunnel/sync, missions, agents, diagnostics) — or cut.

**P3 — later (the repaint + reach):**
11. **GUI rebuild G2–G6** on the real (de-lied) foundation; the new IA; command palette; grouped settings.
12. **Tauri shell** (R8/UPG-13); clients (VS Code/CLI/mobile PWA); MCP kit marketplace.

*Rule of thumb: every P0/P1 item either deletes hand-rolled code, shrinks the RAM/CPU footprint, or
makes a small model answer correctly — which is exactly "runs well on a potato AND gives good answers."*
