# ∴ Model Guide — Which GGUF to Download

Layla runs any GGUF-format model via llama.cpp.  
Pick the right one for your hardware. Put the `.gguf` file in the `models/` folder.

**Very tight hardware:** Use a small Tier 3–4 model *and* apply **potato mode** (Web UI → Settings → *Apply potato preset*, or `POST /settings/preset` with `{"preset":"potato"}`). See [docs/POTATO_MODE.md](docs/POTATO_MODE.md).

---

## How to pick

**Rule of thumb:**
- You need the model to fit in your **GPU VRAM** (or RAM if CPU-only).
- Q4_K_M = best balance of size vs quality. Q5_K_M = slightly better, slightly larger. Q8 = near-lossless, largest.
- Bigger parameter count = smarter, but slower and needs more memory.

---

## Tier 1 — Big GPU (16GB+ VRAM) or 48GB+ RAM

Best overall intelligence. Comparable to GPT-4 class outputs.

| Model | Size | HuggingFace Link |
|---|---|---|
| **Qwen2.5-72B-Instruct-Q4_K_M** | ~42 GB | [bartowski/Qwen2.5-72B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-72B-Instruct-GGUF) |
| **Llama-3.3-70B-Instruct-Q4_K_M** | ~43 GB | [bartowski/Llama-3.3-70B-Instruct-GGUF](https://huggingface.co/bartowski/Llama-3.3-70B-Instruct-GGUF) |
| **DeepSeek-R1-Distill-Qwen-32B-Q4_K_M** *(reasoning)* | ~19 GB | [bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF](https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF) |

**Uncensored picks (Tier 1):**
| Model | Notes |
|---|---|
| [Dolphin-2.9-Llama3-70B-Q4_K_M](https://huggingface.co/mradermacher/dolphin-2.9-llama3-70b-GGUF) | Eric Hartford's uncensored finetune of Llama 3 70B |
| [Hermes-3-Llama-3.1-70B-Q4_K_M](https://huggingface.co/bartowski/Hermes-3-Llama-3.1-70B-GGUF) | NousResearch Hermes 3, follows instructions well, minimal refusals |

---

## Tier 2 — Medium GPU (8–16GB VRAM) or 16–32GB RAM

Sweet spot for most gaming PCs and workstations.

| Model | Size | HuggingFace Link |
|---|---|---|
| **Qwen2.5-14B-Instruct-Q5_K_M** | ~10 GB | [bartowski/Qwen2.5-14B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF) |
| **Mistral-NeMo-12B-Instruct-Q5_K_M** | ~8 GB | [bartowski/Mistral-Nemo-Instruct-2407-GGUF](https://huggingface.co/bartowski/Mistral-Nemo-Instruct-2407-GGUF) |
| **Gemma-2-9B-Instruct-Q5_K_M** | ~6.5 GB | [bartowski/gemma-2-9b-it-GGUF](https://huggingface.co/bartowski/gemma-2-9b-it-GGUF) |
| **DeepSeek-Coder-V2-Lite-Q4_K_M** *(coding)* | ~9 GB | [bartowski/DeepSeek-Coder-V2-Lite-Instruct-GGUF](https://huggingface.co/bartowski/DeepSeek-Coder-V2-Lite-Instruct-GGUF) |

**Uncensored picks (Tier 2):**
| Model | Notes |
|---|---|
| [Dolphin-2.9-Mistral-7B-Q5_K_M](https://huggingface.co/mradermacher/dolphin-2.9-mistral-7b-v2-GGUF) | Compact, capable, fully uncensored |
| [Hermes-3-Llama-3.1-8B-Q5_K_M](https://huggingface.co/bartowski/Hermes-3-Llama-3.1-8B-GGUF) | Best small uncensored option |

---

## Tier 3 — Small GPU (4–8GB VRAM) or 8–16GB RAM

Lightweight, fast, surprisingly capable.

| Model | Size | HuggingFace Link |
|---|---|---|
| **Qwen2.5-7B-Instruct-Q5_K_M** | ~5 GB | [bartowski/Qwen2.5-7B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF) |
| **Llama-3.2-8B-Instruct-Q4_K_M** | ~5 GB | [bartowski/Llama-3.2-8B-Instruct-GGUF](https://huggingface.co/bartowski/Llama-3.2-8B-Instruct-GGUF) |
| **Phi-3.5-mini-instruct-Q4_K_M** | ~2.5 GB | [bartowski/Phi-3.5-mini-instruct-GGUF](https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF) |
| **Qwen2.5-Coder-7B-Instruct-Q5_K_M** *(coding)* | ~5 GB | [bartowski/Qwen2.5-Coder-7B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF) |

---

## Tier 4 — CPU-only or very low RAM (4–8GB)

Slow but it works. Great for testing or low-power devices.

| Model | Size | HuggingFace Link |
|---|---|---|
| **Llama-3.2-3B-Instruct-Q8_0** | ~3.2 GB | [bartowski/Llama-3.2-3B-Instruct-GGUF](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF) |
| **Phi-3.5-mini-instruct-Q2_K** | ~1.5 GB | [bartowski/Phi-3.5-mini-instruct-GGUF](https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF) |
| **Llama-3.2-1B-Instruct-Q8_0** | ~1.3 GB | [bartowski/Llama-3.2-1B-Instruct-GGUF](https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF) |

---

## How to download

### Option 1 — Browser
Go to any HuggingFace link above → click **Files and versions** → download the `.gguf` file.

### Option 2 — Command line (huggingface_hub)
```bash
pip install huggingface_hub
python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='bartowski/Qwen2.5-7B-Instruct-GGUF', filename='Qwen2.5-7B-Instruct-Q5_K_M.gguf', local_dir='models/')"
```

### Option 3 — wget / curl
```bash
# Example (replace URL with the direct download link from HuggingFace)
wget -P models/ "https://huggingface.co/.../resolve/main/model.Q4_K_M.gguf"
```

---

## After downloading

1. Move the `.gguf` file into the `models/` folder at the repo root.
2. Run `agent/first_run.py` (or edit `agent/runtime_config.json` directly):
   ```json
   {
     "model_filename": "Qwen2.5-7B-Instruct-Q5_K_M.gguf"
   }
   ```
3. Launch Layla: `START.bat` (Windows) or `bash start.sh` (Linux/macOS).

---

## Performance tuning in `agent/runtime_config.json`

```json
{
  "model_filename": "your-model.gguf",
  "n_ctx": 4096,
  "n_gpu_layers": -1,
  "n_batch": 512,
  "flash_attn": true,
  "type_k": 8,
  "type_v": 8,
  "completion_max_tokens": 256,
  "temperature": 0.2,
  "uncensored": true,
  "nsfw_allowed": true
}
```

| Key | What it does |
|---|---|
| `n_ctx` | Context window size. Higher = more memory. Start at 4096. |
| `n_gpu_layers` | `-1` = offload all layers to GPU. `0` = CPU only. Try `-1` first. |
| `n_batch` | Batch size. Higher = faster prompt processing. 512 is a good default. |
| `flash_attn` | `true` = faster attention, less VRAM. Always leave this on. |
| `type_k` / `type_v` | `8` = int8 KV cache quantization. Halves KV cache VRAM. Leave at 8. |
| `completion_max_tokens` | Max tokens per reply. 256 is fast. 512–1024 for longer outputs. |
| `temperature` | How creative/random. `0.1` = focused. `0.7` = creative. |
| `uncensored` | `true` = no content filtering. Layla will respond to anything. |

---

## Boss / minion (dual GGUF)

Use a **small fast** model for short chat turns and a **larger** model for coding and reasoning when you have enough RAM (or accept the risk of forcing dual load).

1. Put both `.gguf` files under `models/` (or your configured `models_dir`).
2. In `agent/runtime_config.json`:
   - **`model_filename`** (or **`coding_model`**) — heavy / agent model.
   - **`chat_model`** or **`models.fast`** — fast chat model basename.
   - Optional: **`chat_model_path`** / **`agent_model_path`** — absolute paths to existing files (basename must still resolve under `models_dir` for loading unless you use the same filename there).
   - **`dual_model_threshold_gb`** — minimum **free** system RAM (GB) before dual routing activates (default `24`). Lower it if you know both models fit.
   - **`force_dual_models`** — if `true`, skip the RAM gate (operator accepts possible OOM). Default `false`.
   - **`route_default_to_chat_model`** — if `true`, heuristic class `default` uses the fast chat model when a chat/fast model is configured. Default `false`.

`GET /health` and `GET /platform/models` include a **`model_routing`** object (`routing_enabled`, `dual_models_active`, resolved `chat_basename` / `agent_basename`, etc.) for debugging.

---

## Voice models (optional)

Layla supports voice input/output when these are installed:

**Speech-to-text (faster-whisper):**
```bash
pip install faster-whisper
```
Model auto-downloads. Set `whisper_model` in config: `"base"` (fast) or `"small"` / `"medium"` (better accuracy).

**Text-to-speech (kokoro-onnx):**
```bash
pip install kokoro-onnx soundfile
```
~80 MB download, fully offline, high quality. Set `tts_voice` in config (default: `"af_heart"`).

---

*Recommended source for GGUF files: [bartowski on HuggingFace](https://huggingface.co/bartowski) — consistently reliable quants.*
