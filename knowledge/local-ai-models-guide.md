---
priority: core
domain: ai-models
---

# Local AI Models — What They Are and How to Use Them

## GGUF format

GGUF (GPT-Generated Unified Format) is the standard format for running LLMs locally via llama.cpp. A `.gguf` file contains the model weights in a quantized (compressed) format. Quantization reduces size and speeds up inference at a small quality cost.

## Quantization levels

| Quantization | Bits/weight | Quality loss | Size (7B model) |
|---|---|---|---|
| Q8_0 | 8 | near-zero | ~8 GB |
| Q6_K | 6 | minimal | ~6 GB |
| Q5_K_M | 5 | very low | ~5 GB |
| Q4_K_M | 4 | low | ~4 GB |
| Q3_K_M | 3 | noticeable | ~3.5 GB |
| Q2_K | 2 | significant | ~2.5 GB |

`K_M` = k-quant medium (better quality than basic Q4). For most use cases, `Q4_K_M` or `Q5_K_M` is the sweet spot.

## Context window (n_ctx)

The context window is how many tokens the model can "see" at once. Larger = more memory. Good defaults:
- 4096: standard, works on most hardware
- 8192: good for long conversations or large codebases
- 16384+: requires significant VRAM

## GPU offloading (n_gpu_layers)

- `-1`: offload all layers to GPU (best performance, requires enough VRAM)
- `0`: CPU-only inference (works on any machine, slower)
- `20`: offload 20 layers (partial offload for when VRAM is limited)

With full GPU offload, most 7B models run at 50-100 tokens/sec. CPU-only is 5-15 tokens/sec.

## Recommended models by use case

**General purpose (uncensored, follow instructions well):**
- Dolphin Mistral 7B / Dolphin Llama 3 8B — Eric Hartford's uncensored finetunes
- Hermes 3 (Llama 3.1 8B or 70B) — NousResearch, minimal refusals, good instruction following
- Qwen2.5 Instruct — excellent Chinese-English bilingual, very capable

**Coding:**
- DeepSeek-Coder-V2 Lite — best small coding model
- Qwen2.5-Coder — strong coding, good general capability
- CodeLlama 13B — solid for Python/JS

**Reasoning:**
- DeepSeek-R1 Distill — chain-of-thought reasoning baked in
- Qwen2.5 72B — best overall reasoning at reasonable size

**Small (CPU/low VRAM):**
- Phi-3.5 mini — Microsoft, surprisingly capable for size
- Llama 3.2 3B — decent for simple tasks
- Gemma 2 2B — good instruction following for its size

## llama-cpp-python settings

Key parameters in runtime_config.json:
- `n_ctx`: context window size
- `n_gpu_layers`: -1 for full GPU offload
- `n_batch`: batch size for prompt processing (larger = faster, more VRAM)
- `n_threads`: CPU threads (auto-detected by Layla based on physical core count)
- `flash_attn`: true = faster attention, less VRAM (recommended)
- `type_k/type_v`: 8 = int8 KV cache quantization (halves KV cache VRAM)
- `n_keep`: number of tokens to pin in KV cache (protects system prompt from eviction)
- `temperature`: 0.1=focused, 0.7=creative, 0.0=deterministic
- `repeat_penalty`: 1.1 is a good default to reduce repetition

## Stop sequences

Critical for proper conversation formatting. Common values:
```json
"stop_sequences": ["\nUser:", " User:", "\nHuman:", "\n###"]
```
These prevent the model from generating the next "turn" in a conversation itself.

## Prompt formats

Different models need different prompt formats. llama-cpp-python handles this automatically via the chat completion API, but for raw completion, know your model's format:
- Llama 3: `<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{message}<|eot_id|>`
- Mistral/Mixtral: `[INST] {message} [/INST]`
- Qwen: `<|im_start|>user\n{message}<|im_end|>\n<|im_start|>assistant\n`
- ChatML: `<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{message}<|im_end|>`
