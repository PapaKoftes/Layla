# External resources — models, benchmarks, discovery

Curated links for **operators** choosing hardware, GGUF tiers, and judging coding/chat models. Layla stays self-contained; these are **references**, not bundled dependencies.

## Local LLM ecosystems

- **[Awesome Local LLM](https://github.com/janhq/awesome-local-ai)** — Broad index of local AI tools, UIs, and runtimes (useful orientation; verify freshness of individual entries).

## Model selection & hardware fit

- **VRAM / fit calculators** — Search for “LLM VRAM calculator” or “GGUF VRAM estimator”; many compare quant (Q4_K_M, Q8) × context × model size. Use alongside Layla’s own [MODELS.md](../MODELS.md) tiers.
- **LLM Explorer** — Third-party model browsers (search “LLM Explorer” / Hugging Face model hub filters) for context length, license, and quant availability.
- **[Models.dev](https://models.dev/)** — Model metadata and pricing comparisons (mostly API-focused; still useful for capability labels).

## Benchmarks & evals (justify recommendations)

- **[Artificial Analysis](https://artificialanalysis.ai/)** — Latency, quality, and leaderboard-style comparisons (check methodology).
- **LMSys / Chatbot Arena** — Human-preference arena rankings (search “LMSys Chatbot Arena”); good for *relative* chat quality, not coding-only.
- **[SWE-bench](https://www.swebench.com/)** — Software engineering benchmark; cited by coding-model leaderboards.
- **Aider / coding leaderboards** — Search “Aider LLM leaderboard” for code-edit benchmarks tied to real edits.

## Discovery & sourcing (GGUF / weights)

- **[Hugging Face](https://huggingface.co/)** — Primary source for GGUF quants; [bartowski](https://huggingface.co/bartowski) and similar accounts are common for Llama/Qwen/etc. quants.
- **Awesome ML / Awesome LLM** — GitHub lists (search “awesome machine learning”, “awesome llm”); good for papers, tools, and datasets—not all are local-first.

## Voice / STT (already in Layla)

Layla uses **faster-whisper** (`stt_file` tool, `/voice/transcribe`). Optional upgrades are **operator choice** (better whisper model size, GPU). Third-party TTS/STT catalogs are not required for core functionality.

## Policy note

Avoid bundling **jailbreak directories** or **ToS-violating “free API”** stacks into the repo; they do not improve Layla’s local, operator-owned design.
