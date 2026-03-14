---
priority: core
domain: troubleshooting
---

# Layla Troubleshooting Guide

## Linux (Ubuntu / Fedora) — startup fails

**Symptom:** `bash start.sh` or `uvicorn main:app` fails immediately, or pip install fails with "No CMAKE_CXX_COMPILER" / "Python.h not found".

**1. Run the diagnostic first:**
```bash
# Linux/macOS
source .venv/bin/activate
python agent/diagnose_startup.py

# Windows
.venv\Scripts\activate
python agent\diagnose_startup.py
```
This reports which dependency or import is failing.

**2. Install system build dependencies before pip install:**
- **Ubuntu/Debian:** `sudo apt install build-essential cmake libsndfile1`
- **Fedora:** `sudo dnf install python3-devel gcc-c++ cmake libsndfile`
- **Arch:** `sudo pacman -S base-devel cmake libsndfile`

Then re-run `bash install.sh` (or `pip install -r agent/requirements.txt` if venv already exists).

**3. Use `python -m uvicorn` (avoids PATH issues):**
```bash
cd agent
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
The `start.sh` script uses this by default. If you run uvicorn manually and get "command not found", use `python -m uvicorn` instead.

**4. If llama-cpp-python fails to build:**
- Ensure gcc, g++, cmake are installed (see step 2)
- `python3-devel` (Fedora) or `python3-dev` (Ubuntu) provides `Python.h` — required for compilation
- Try: `pip install llama-cpp-python --no-cache-dir` to force a clean rebuild

**5. If ChromaDB / sentence-transformers fails:**
- ChromaDB needs SQLite ≥ 3.35. If you see sqlite3 errors: `pip install pysqlite3-binary`
- sentence-transformers downloads models on first use — ensure internet access

---

## Layla won't start

**"Model not found" error**
- Check `agent/runtime_config.json` — the `model_filename` must match a real file in `models/`
- List what's in `models/`: `ls models/` (Linux/macOS) or `dir models\` (Windows)
- The filename is case-sensitive on Linux

**"venv not found" or "python not found"**
- Run `INSTALL.bat` (Windows) or `bash install.sh` (Linux/macOS) first
- The venv is at `.venv/` in the repo root
- No model yet? Run `python agent/first_run.py` — the wizard can download one

**Port 8000 already in use**
- Another process is on port 8000. Change the port: `uvicorn main:app --port 8001`
- Or kill the existing process: `netstat -ano | findstr 8000` (Windows), `lsof -i :8000` (Linux)

**Uvicorn won't start or crashes**
- Run from the agent directory: `cd agent && uvicorn main:app --host 127.0.0.1 --port 8000`
- Or: `cd agent && python -m uvicorn main:app --host 127.0.0.1 --port 8000`
- Ensure venv is activated and uvicorn is installed: `pip install uvicorn[standard]`
- On Fedora, install build deps first: `sudo dnf install python3-devel` (needed for some compiled deps)

**FastAPI import errors**
- Activate the venv: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Linux)
- Reinstall: `pip install -r agent/requirements.txt`

## Model loads but responses are wrong/garbled

**Model outputs stop sequences or repeats itself**
- Check `stop_sequences` in config — must match your model's format
- Common: `["\nUser:", " User:"]` for most instruct models
- For Llama 3: add `"<|eot_id|>"` to stop sequences

**Model doesn't follow instructions**
- Check you're using an *instruct* or *chat* finetuned model, not a base model
- Base models (e.g. `llama-3.2-3b.gguf` without `-Instruct`) don't follow instructions

**Context fills up mid-conversation**
- Increase `n_ctx` in config (e.g. 8192). Requires more VRAM.
- Reduce `convo_turns` (number of past turns kept in context)

## Slow inference

**Very slow generation (< 3 tokens/sec)**
- If you have a GPU: check `n_gpu_layers` is `-1` (full offload) not `0`
- Verify CUDA is working: `python -c "from llama_cpp import Llama; print('ok')"`
- Check `flash_attn: true` and `type_k: 8, type_v: 8` in config

**Slow to start (first message takes 30+ seconds)**
- This is normal on first run — the model is loading into memory
- Subsequent messages should be fast
- Enable the LLM pre-warm (default on) — it loads the model at startup

**Slow embedder**
- The embedder (`nomic-embed-text` or `all-MiniLM-L6-v2`) loads on first use
- It pre-warms at startup — should be instant after that
- If very slow, try `all-MiniLM-L6-v2` (smaller) by editing `vector_store.py`

## Memory / ChromaDB issues

**"ChromaDB error" at startup**
- ChromaDB stores its data in `agent/chroma/` — delete it to reset: `rm -rf agent/chroma`
- This will lose the knowledge index (it will rebuild on next start) but not learnings

**Layla doesn't remember things**
- Check `layla.db` exists in the repo root
- Run `python layla.py ask "what do you remember about me"` to test
- Learnings are in the `learnings` table in SQLite — inspect with any SQLite viewer

**Cross-encoder reranking not working**
- Requires internet access on first use to download `cross-encoder/ms-marco-MiniLM-L-6-v2`
- If download fails, it silently falls back to BM25+vector without reranking

## Voice problems

**Mic button doesn't work**
- Browser needs microphone permission — check browser settings
- `faster-whisper` must be installed: `pip install faster-whisper`
- Test: `POST http://localhost:8000/voice/transcribe` with audio bytes

**TTS not working**
- `kokoro-onnx` and `soundfile` must be installed: `pip install kokoro-onnx soundfile`
- On first use, downloads ~80MB ONNX model — needs internet
- If not installed, Layla falls back to browser SpeechSynthesis automatically

**Browser automation (Playwright) fails**
- Run: `playwright install chromium`
- Check it's installed: `python -c "from playwright.sync_api import sync_playwright; print('ok')"`

## Cannot send a message

**Send button stays disabled**
- Type something in the input box — the button enables only when there's text
- If it still won't enable, check the browser console (F12 → Console) for JavaScript errors

**Clicking Send does nothing or shows an error**
- **"Model not ready"** — Configure a model: run `python agent/first_run.py` or put a `.gguf` in `models/` and set `model_filename` in `agent/runtime_config.json`. See MODELS.md.
- **"Model error: ... path ..."** — The model file path is wrong. Check `models_dir` and `model_filename` in config; the file must exist.
- **Using a remote LLM?** — Set `llama_server_url` in `runtime_config.json` (e.g. `http://localhost:11434` for Ollama). No local .gguf needed.
- **Request hangs or times out** — Model may be loading (first request can take 30+ seconds). Or the model is too large for your RAM — try a smaller one.

**Check model status:** Open `http://localhost:8000/health` — if `model_loaded` is false, fix the config before sending.

---

## UI problems

**UI not loading at http://localhost:8000/ui**
- Server must be running: `cd agent && uvicorn main:app --host 127.0.0.1 --port 8000`
- Check the server logs for errors

**Aspects not working (clicking Lilith shows Morrigan)**
- `personalities/lilith.json` must exist — check `personalities/` folder
- If missing, it falls back silently to Morrigan

**UI slow or fonts not loading**
- The UI loads Google Fonts and CDN libraries — requires internet on first load
- Cached by browser after first load

## Approval issues

**Layla keeps saying "approval required"**
- Run: `python layla.py pending` to see what's waiting
- Approve: `python layla.py approve <uuid>`
- Or use the web UI Approvals panel

**Can't approve via CLI**
- Make sure the venv is activated: `.venv\Scripts\activate`
- The CLI is at the repo root: `python layla.py`
