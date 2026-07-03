# Layla — Deep Research Addendum (evidence + magnitudes + caveats) — 2026-07-03

Deepens [`FULL-LIST.md`](FULL-LIST.md) with (a) codebase-grounded evidence of what's hand-rolled,
(b) current tool status + **cited magnitudes**, and (c) the non-obvious caveats that change the
recommendation. Sources at the bottom.

---

## 1. Reuse swaps — verified in the code, quantified from the field

### 1.1 Vector store → **sqlite-vec**  [confirms UPG-02]
- **Hand-rolled today (verified):** THREE parallel vector paths — `agent/layla/memory/fallback_store.py`
  (SQLite+NumPy cosine), `vector_store.py` (Chroma wrapper), and `vector_qdrant.py` (a Qdrant path).
  Plus cosine in `distill.py`. That's the "which store is real?" duplication.
- **Current status:** sqlite-vec is production-grade — SIMD distance kernels, 2/3/4-bit TurboQuant
  scans, runs anywhere SQLite runs, **~30 MB default footprint**; `sqlite-vss` (the old Faiss one) is
  **deprecated in favor of sqlite-vec**. Prebuilt, no C toolchain → keeps the compiler-free property.
- **Win:** deletes the bespoke NumPy ANN + collapses 3 paths to 1; faster exact/approx search on CPU.
- **Caveat:** it's an exact/brute-ish + quantized-scan store, ideal at our scale (thousands–low-millions
  of vectors); not a distributed ANN — perfect for local-first.

### 1.2 Embeddings → **model2vec** (potato) / **FastEmbed** (modest)  [confirms UPG-03]
- **Hand-rolled/heavy today:** torch + sentence-transformers on the recall path.
- **Cited magnitudes:**
  - **model2vec** (static): **~20,000–30,000 sentences/sec on CPU**, **500× faster**, **50× smaller**;
    a **32 MB** model keeps **~92% of MiniLM's MTEB** (51.66 vs 56.09). Beats GloVe/FastText outright.
  - **FastEmbed** (ONNX): **~2,500 QPS on consumer CPU vs ~120 for raw Transformers = 12×**, sub-ms
    latency; ONNX Runtime broadly gives **3–5× speed + 60–80% less memory** than the torch path.
  - sentence-transformers model ≈ 400 MB + a ~5 GB torch image.
- **Win on potato:** drop torch entirely → **hundreds of MB saved** + semantic memory becomes affordable,
  which **resolves the `use_chroma=false` tradeoff** — "it remembers" holds on low-end.
- **Recommendation:** model2vec default on potato; FastEmbed on modest; keep sentence-transformers as an
  opt-in "quality" embedder on capable tiers only.

### 1.3 Token counting → **tiktoken / model tokenizer**  [NEW — R9]
- **Hand-rolled today (verified, ≥4 sites):** char÷4 heuristics — `core/validator.py:81`
  (`len(result_str)//4`), `layla/ingestion/chunker.py:15` (`estimate_tokens`),
  `layla/tools/impl/analysis.py:138,417` (`int(chars/4)`), and `services/context/context_manager.
  token_estimate_messages` (used by `/ctx_viz`, `session.py:42`).
- **Win:** one accurate tokenizer (tiktoken, or `llama_cpp`'s own `.tokenize()`) → correct context
  budgeting, chunk sizing, and result-truncation → fewer silent overflows/truncations. Small, safe.

### 1.4 Downloads/HTTP → **huggingface_hub** + **httpx**  [NEW — R12/R13]
- **Hand-rolled today (verified):** `first_run.py:187` `urlretrieve` (non-resumable),
  `install/model_downloader.py:234` `_download_direct_http`, and `urllib.request.urlopen` scattered
  across every web tool (`tools/web.py:163`, `tools/impl/web.py:253,425`, `impl/system.py:290`,
  `impl/automation.py:190,373,390`, `impl/analysis.py:709`).
- **Win:** `hf_hub_download` gives **resumable + checksum-verified + mirror-aware** model pulls
  (fixes UPG-35/42); one **httpx** client gives consistent timeouts/retries/HTTP-2 across the web tools.

### 1.5 Constrained decoding → **GBNF / llguidance** (built into llama.cpp)  [confirms UPG-05, refined]
- **Cited:** on JSONSchemaBench (~10k schemas), **Guidance/llguidance had LOWER per-token latency than
  unconstrained** (~6–9 ms vs ~15–16 ms) — it can skip sampling when the grammar forces the next token.
  llama.cpp has **automatic JSON-Schema→GBNF** conversion built in, and now ships **llguidance** support.
- **Caveat (important):** some models lose **>20% accuracy** when forced into a rigid structure ("when
  correct isn't usable"). So: constrain tool-call/JSON *envelopes*, keep reasoning free-form; design
  grammars that don't fight the model. It's the cheapest correctness win **when applied surgically**.

---

## 2. Performance levers — quantified, with the non-obvious caveats

### 2.1 The potato bottleneck is **memory bandwidth**, not CPU
- **Cited:** for CPU inference the dominant factor is RAM bandwidth; single→dual-channel took a 34B from
  **1.5 → 4 tok/s**. Implication: on a real potato, pushing a *smaller* model + smaller ctx beats a
  bigger model, and there's little to gain from more cores. This reframes the whole tier matrix.

### 2.2 KV-cache quantization — q8_0 default, q4_0 only for short ctx, needs flash-attn
- **Cited:** q8_0 = 1 byte/elem (vs FP16 2 B) with **no significant quality loss**; q4_0 = 0.5 B,
  **~72% KV reduction**. 7B@32K: FP16 ≈ 4 GB → q8_0 ≈ 2 GB → q4_0 ≈ 1 GB. **But** q4_0 can be **up to
  ~92% slower at 64K** ctx (dequant overhead); prompt throughput is unaffected. **KV-quant requires
  flash-attention.** → Matrix refinement: **potato = q4_0** (it runs *short* 2048 ctx, so the slowdown
  doesn't bite and the RAM saving is what matters); **modest/capable = q8_0**; **flash-attn on** everywhere it's supported.

### 2.3 Cold-start: **mmap** cuts it 60s → <2s
- **Cited:** mmap model loading drops cold-start from ~60 s to **<2 s on NVMe** (GGUF is built for mmap).
  → ensure mmap is on by default; don't mlock on low-RAM boxes.

### 2.4 Threads = **physical cores** (not logical)
- **Cited:** threads should match *physical* cores; going 8→9 on an 8-core **drops** performance
  (hyperthreading overhead on matmul). → detect physical cores; stop defaulting to logical.

### 2.5 Flash attention (`--flash-attn`)
- **Cited:** reduces attention memory read/writes, speeds prefill, and is the **prerequisite for
  KV-quant**. → enable wherever the build supports it.

### 2.6 Prefill batch (`n_batch` 512–2048), prefix/KV caching
- Larger `n_batch` speeds prompt ingestion; reusing the system-prompt KV across turns cuts first-token
  latency. Both are standard llama.cpp levers we should expose per tier.

---

## 3. Refined potato playbook (research-adjusted)

| Knob | 🥔 Potato (bandwidth-bound) | ⚙️ Modest | 🚀 Capable |
|---|---|---|---|
| Model | 1.5–3B Q4_K_M / IQ4_XS (small = bandwidth win) | 7B Q4_K_M | 14B+/GPU |
| n_ctx | 2048 | 4096 | 8192+ |
| KV cache | **q4_0** (short ctx, RAM-bound) + flash-attn | **q8_0** + flash-attn | f16/q8_0 |
| Embeddings | **model2vec** (30k/s, 32 MB, no torch) | **FastEmbed** (ONNX, 12×) | sentence-transformers (opt) |
| Vector store | **sqlite-vec** (~30 MB) | sqlite-vec | sqlite-vec (+rerank) |
| Rerank | off | FlashRank | cross-encoder |
| Deliberation | solo | debate | council/tribunal |
| Threads | = physical cores | = physical cores | = physical cores |
| mmap | on (cold-start <2s) | on | on |
| torch loaded? | **no** | optional | yes |

**Single highest-leverage move (P0):** sqlite-vec + model2vec → drops torch, makes semantic memory
affordable on a potato (the wedge promise), and deletes 3 bespoke vector paths + the NumPy cosine.

---

## Sources
- [sqlite-vec (asg017) — SQLite vector search](https://github.com/topics/sqlite-vec?l=python) · [Embedded intelligence with sqlite-vec (DEV)](https://dev.to/aairom/embedded-intelligence-how-sqlite-vec-delivers-fast-local-vector-search-for-ai-3dpb) · [sqlite-vss deprecated → sqlite-vec](https://github.com/asg017/sqlite-vss)
- [Model2Vec (MinishLab)](https://github.com/MinishLab/model2vec) · [Model2Vec 50× smaller / 500× faster](https://medium.com/@hrishikesh19202/supercharge-your-transformers-with-model2vec-shrink-by-50x-run-500x-faster-c640c6bc1a42) · [FastEmbed (qdrant)](https://github.com/qdrant/fastembed) · [FastEmbed ONNX lightweight inference](https://johal.in/fastembed-onnx-lightweight-embedding-inference-2025/) · [CPU-optimized embeddings (Haystack)](https://haystack.deepset.ai/blog/cpu-optimized-models-with-fastrag)
- [llama.cpp KV-quant discussion (#5932)](https://github.com/ggml-org/llama.cpp/discussions/5932) · [Ollama K/V quantisation (smcleod)](https://smcleod.net/2024/12/bringing-k/v-context-quantisation-to-ollama/) · [Which quantization to use (arXiv 2601.14277)](https://arxiv.org/pdf/2601.14277)
- [llama.cpp CPU perf (johannesgaessler)](https://johannesgaessler.github.io/llamacpp_performance) · [Squeezing performance out of llama.cpp (Medium)](https://medium.com/@ekansh.jain2011/squeezing-every-drop-of-performance-out-of-llama-cpp-the-practitioners-guide-to-local-ai-2bcc3663f06f) · [Your local LLM is slow — 5 config flags (OmniForge)](https://omniforge.online/blog/your-local-llm-is-slow-because-of-five-config-flags)
- [llguidance in llama.cpp (docs)](https://github.com/ggml-org/llama.cpp/blob/master/docs/llguidance.md) · [Grammar-constrained generation (TianPan)](https://tianpan.co/blog/2026-04-16-grammar-constrained-generation-output-reliability) · [When Correct Isn't Usable — structured output in small models (arXiv 2605.02363)](https://arxiv.org/pdf/2605.02363)
