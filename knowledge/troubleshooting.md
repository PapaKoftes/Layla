---
priority: core
domain: troubleshooting
---

# Layla Troubleshooting Guide

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
