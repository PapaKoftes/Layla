# Getting the local AI model (GGUF)

Layla runs on a **local GGUF model** loaded via llama-cpp-python. This guide explains where to get a model, how to choose one for your hardware and use case, and how to install and configure it so Layla is ready to run.

---

## 1. Where to get GGUF models

- **Hugging Face (recommended)**  
  Browse GGUF models: [huggingface.co/models?library=gguf](https://huggingface.co/models?library=gguf)  
  Many repos offer several **quantizations** (e.g. Q4_K_M, Q5_K_M, Q8_0) in the "Files and versions" tab.

- **TheBloke**  
  [TheBloke](https://huggingface.co/TheBloke) publishes many quantized GGUF models (Llama, Mistral, Phi, etc.). Pick a model repo, then choose a quantization file.

- **Other sources**  
  Any `.gguf` file that works with [llama.cpp](https://github.com/ggerganov/llama.cpp) will work with llama-cpp-python. Some projects also distribute GGUF on their own sites.

---

## 2. Choosing the right model for your hardware and use case

| Factor | What to consider |
|--------|-------------------|
| **RAM / VRAM** | Model size and quantization determine memory use. ~7B Q4: ~4–5 GB; 13B Q4: ~8 GB; 20B+ Q4: 12 GB+. Prefer smaller or more quantized (Q4) if you have limited RAM. |
| **CPU vs GPU** | llama-cpp-python can use CPU only or GPU (CUDA/Metal). GPU speeds up inference; CPU-only is fine for smaller models (e.g. 7B Q4). Install `llama-cpp-python` with the right backend for your OS/GPU (see [llama-cpp-python](https://github.com/abetlen/llama-cpp-python#installation)). |
| **Quantization** | **Q4_K_M** or **Q5_K_M**: good balance of quality and size. **Q8_0**: higher quality, larger. **Q2_K** / **Q3_K_S**: smallest, lower quality. For a capable assistant, Q4_K_M or Q5_K_M is a solid default. |
| **Use case** | Coding/agent: 7B–13B instruction-tuned models (e.g. Mistral, CodeLlama, Phi) are often enough. For deeper reasoning or longer context, consider 13B+ or 20B+ if your machine fits it. |

**Practical default:** A **7B or 13B model**, **Q4_K_M** or **Q5_K_M**, from Hugging Face or TheBloke. Example repo names: `TheBloke/Mistral-7B-Instruct-v0.2-GGUF`, `TheBloke/CodeLlama-13B-Instruct-GGUF` — then pick one `.gguf` file from the list (e.g. `*Q4_K_M.gguf`).

---

## 3. Download and install

### Option A: Download from Hugging Face in the browser

1. Open the model repo on Hugging Face (e.g. [TheBloke/Mistral-7B-Instruct-v0.2-GGUF](https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF)).
2. Open the **Files and versions** tab.
3. Download the `.gguf` file you want (e.g. `mistral-7b-instruct-v0.2.Q4_K_M.gguf`).
4. Put it in the **`models/`** folder at the **root of the Layla repo** (create `models/` if it does not exist).

### Option B: Download with Python (huggingface_hub)

From the repo root (with `huggingface_hub` installed):

```bash
pip install huggingface_hub
```

Then in Python (or a one-off script):

```python
from huggingface_hub import hf_hub_download

# Example: download a specific file from TheBloke/Mistral-7B-Instruct-v0.2-GGUF
path = hf_hub_download(
    repo_id="TheBloke/Mistral-7B-Instruct-v0.2-GGUF",
    filename="mistral-7b-instruct-v0.2.Q4_K_M.gguf",
    local_dir="models",
    local_dir_use_symlinks=False,
)
print(path)  # e.g. models/mistral-7b-instruct-v0.2.Q4_K_M.gguf
```

Use the same `local_dir="models"` so the file ends up in `models/` at the repo root.

### Option C: Clone the whole repo (only if you want every quantization)

```bash
git lfs install
git clone https://huggingface.co/TheBloke/SomeModel-GGUF models/SomeModel-GGUF
```

Then point Layla at the specific `.gguf` file inside `models/SomeModel-GGUF/` (see step 4).

---

## 4. Configure Layla to use the model

1. **Path:** Ensure the `.gguf` file is under the repo’s **`models/`** directory (e.g. `models/mistral-7b-instruct-v0.2.Q4_K_M.gguf`).

2. **Config:** Set `model_filename` in `agent/runtime_config.json` to the **filename only** (or the path relative to `models/` if you use a subfolder).  
   - If the file is `models/my-model.Q4_K_M.gguf`, set:
     ```json
     "model_filename": "my-model.Q4_K_M.gguf"
     ```
   - The app resolves this relative to the `models/` directory at repo root (see README and ARCHITECTURE).

3. **First run:** If `agent/runtime_config.json` does not exist, copy from `agent/runtime_config.example.json`, then set `model_filename` and `sandbox_root` as in [RUNBOOKS](RUNBOOKS.md#first-run).

---

## 5. Verify setup

1. Start the server from the `agent` directory:
   ```bash
   cd agent
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```
2. Open [http://localhost:8000/health](http://localhost:8000/health). If the model loads, you get a healthy status (or 503 until DB is ready).
3. Open [http://localhost:8000/ui](http://localhost:8000/ui) and send a message to confirm the model responds.

If the model path is wrong or the file is missing, the server may fail at startup or when handling the first request; check the console for errors.

---

## 6. Optional: GPU acceleration (llama-cpp-python)

For faster inference, install `llama-cpp-python` with GPU support **before** installing other dependencies:

- **CUDA (NVIDIA):**
  ```bash
  CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
  ```
- **Metal (Apple M1/M2):**
  ```bash
  CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
  ```

Then reinstall the rest of the requirements from `agent/requirements.txt` if needed. The same GGUF file is used; the backend will use GPU when available.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Choose a GGUF model (e.g. Hugging Face / TheBloke), pick a quantization (e.g. Q4_K_M). |
| 2 | Download the `.gguf` file into the repo’s **`models/`** folder. |
| 3 | Set **`model_filename`** in `agent/runtime_config.json` to that filename. |
| 4 | Start the server and test with `/health` and `/ui`. |

For first-run setup (venv, config, database), see [RUNBOOKS](RUNBOOKS.md#first-run) and the main [README](../README.md).
