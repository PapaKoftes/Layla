# Layla Install Profiles

Layla has 48+ direct dependencies organized into install profiles. You only need
**Core** to run the agent. Every other profile is optional -- features degrade
gracefully when their packages are absent.

---

## 1. Quick Start (Core Only)

```bash
# Create a virtual environment
python -m venv agent/venv
# Windows
agent\venv\Scripts\activate
# Linux / macOS
source agent/venv/bin/activate

# Install core dependencies (~250 MB)
pip install -r agent/requirements.txt
```

The full `requirements.txt` installs everything that is uncommented. For a
leaner install, cherry-pick the sections you need (each section is labeled with
comments in that file) or use the profile groups below.

To run with only the bare minimum:

```bash
pip install fastapi "uvicorn[standard]" pydantic sqlite-utils duckdb \
    apscheduler httpx orjson chromadb sentence-transformers \
    langchain-text-splitters beautifulsoup4 tiktoken tenacity \
    diskcache Pillow PyYAML networkx numpy psutil llama-cpp-python
```

Then start the server:

```bash
cd agent
uvicorn main:app --host 0.0.0.0 --port 8000
# or: python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 2. Available Profiles

| Profile | Approx. Size | Key Packages | What It Enables |
|---------|-------------|--------------|-----------------|
| **Core** | ~250 MB | FastAPI, uvicorn, pydantic, sqlite-utils, duckdb, apscheduler, httpx, orjson, chromadb, sentence-transformers, langchain-text-splitters, beautifulsoup4, tiktoken, tenacity, diskcache, Pillow, PyYAML, networkx | Agent chat, memory, vector search, web server, scheduling, text splitting |
| **ML** | ~2 GB | torch, transformers, scikit-learn, torchao | Image captioning (BLIP), clustering, classification, advanced embeddings |
| **Voice** | ~600 MB | faster-whisper, kokoro-onnx, soundfile, sounddevice | Speech-to-text (Whisper), text-to-speech (Kokoro ONNX or pyttsx3 fallback) |
| **Vision** | ~1.5 GB | easyocr, pytesseract, ultralytics | OCR from images, object detection (YOLOv8) |
| **Crawl** | ~260 MB | trafilatura, playwright, crawl4ai | Web crawling, article extraction, browser automation |
| **Search** | ~10 MB | rank-bm25, faiss-cpu | BM25 hybrid search, fast approximate nearest neighbor |
| **Research** | ~50 MB | PyMuPDF, pypdf, wikipedia, arxiv, yfinance, duckduckgo-search, pandas | PDF reading, Wikipedia, arXiv papers, financial data, web search |
| **Viz** | ~80 MB | matplotlib, plotly, seaborn, folium | Charts (bar, line, scatter, pie, heatmap), interactive maps |
| **Dev** | ~30 MB | pytest, pytest-asyncio, pytest-timeout, pytest-cov, ruff, bandit | Testing, linting, security analysis |

### Additional Install Packs

The interactive installer (`python agent/install/installer_cli.py`) also offers
feature packs defined in `agent/install/packs/*.json`:

| Pack | Description | Extra Steps |
|------|-------------|-------------|
| `voice` | sounddevice for live mic input | -- |
| `browser` | Playwright for browser automation tools | Runs `playwright install chromium` automatically |
| `e2e` | pytest-playwright for UI end-to-end tests | Run `playwright install chromium` after |
| `intelligence` | spaCy NER + entity extraction | Downloads `en_core_web_sm` model |
| `research` | feedparser, deep-translator, yfinance | -- |
| `observability` | prometheus_client, structlog | -- |

Install a pack manually:

```bash
python agent/install/installer_cli.py packs install voice
python agent/install/installer_cli.py packs install browser
```

List available packs:

```bash
python agent/install/installer_cli.py packs list
```

---

## 3. Combining Profiles

Mix and match profiles by installing the packages from each group you need.

**Researcher workstation** (chat + PDFs + web search + charts):

```bash
# Core (always required)
pip install fastapi "uvicorn[standard]" pydantic sqlite-utils duckdb \
    apscheduler httpx orjson chromadb sentence-transformers \
    langchain-text-splitters beautifulsoup4 tiktoken tenacity \
    diskcache Pillow PyYAML networkx numpy psutil llama-cpp-python

# Research
pip install PyMuPDF pypdf wikipedia arxiv yfinance duckduckgo-search pandas

# Viz
pip install matplotlib
```

**Voice assistant** (chat + speech-to-text + text-to-speech):

```bash
# Core (always required)
pip install fastapi "uvicorn[standard]" pydantic sqlite-utils duckdb \
    apscheduler httpx orjson chromadb sentence-transformers \
    langchain-text-splitters beautifulsoup4 tiktoken tenacity \
    diskcache Pillow PyYAML networkx numpy psutil llama-cpp-python

# Voice
pip install faster-whisper kokoro-onnx soundfile sounddevice
```

**Full local AI** (everything, ~3.5 GB):

```bash
pip install -r agent/requirements.txt
python agent/install/installer_cli.py packs install browser
python agent/install/installer_cli.py packs install voice
python agent/install/installer_cli.py packs install intelligence
```

**Minimal CI runner** (tests only, no ML/voice):

```bash
pip install fastapi "uvicorn[standard]" pydantic sqlite-utils duckdb \
    apscheduler httpx orjson chromadb sentence-transformers \
    langchain-text-splitters beautifulsoup4 tiktoken tenacity \
    diskcache Pillow PyYAML networkx numpy psutil llama-cpp-python

pip install pytest pytest-asyncio pytest-timeout pytest-cov httpx python-multipart
```

---

## 4. How Optional Imports Work (Graceful Degradation)

Every optional dependency is guarded with a `try/except` at the point of use.
When a package is missing, the feature is disabled -- not the whole agent.

### Pattern used in the codebase

```python
# Example from services/tts.py
try:
    import kokoro_onnx
    _HAS_KOKORO = True
except ImportError:
    _HAS_KOKORO = False

# At call time:
if not _HAS_KOKORO:
    raise ImportError(
        "kokoro-onnx not installed. pip install kokoro-onnx  # or: pip install layla[voice]"
    )
```

```python
# Example from layla/geometry/machining_ir.py
try:
    import ezdxf
except ImportError:
    logger.debug("extract_features_from_dxf: ezdxf not installed")
    return []
```

### What happens when a dependency is missing

| Scenario | Behavior |
|----------|----------|
| Voice packages missing | `/agent` chat works; voice endpoints return a clear error naming the missing package |
| easyocr missing | OCR tools return an error suggesting `pip install easyocr` |
| matplotlib missing | Chart tools return an error; all other tools work |
| PyMuPDF missing | Falls back to pypdf; if both missing, PDF reading tools report the issue |
| chromadb missing | Vector memory disabled; agent uses SQLite-only memory |
| tree-sitter missing | Code intelligence features downgraded; logged as `missing` in `/health/deps` |
| spaCy missing | Entity extraction uses simpler keyword-based fallback |

The agent never crashes on a missing optional dependency. Error messages always
include the exact `pip install` command to fix it.

---

## 5. Checking What's Installed

### GET /health/deps

Returns a JSON map of dependency name to status (`ok`, `missing`, or `error`):

```bash
curl http://localhost:8000/health/deps
```

```json
{
  "dependencies": {
    "llama_cpp": "ok",
    "chroma": "ok",
    "voice_stt": "missing",
    "voice_tts": "missing",
    "tree_sitter": "missing",
    "gpu": "none"
  }
}
```

For a deeper check that actually probes ChromaDB with a test embed+search:

```bash
curl "http://localhost:8000/health/deps?deep=true"
```

### GET /health

The main health endpoint includes the same dependency map plus model status,
feature flags, effective config, and hardware info. Use it for a full system
overview:

```bash
curl http://localhost:8000/health
```

### pip check

Verify that installed packages have compatible versions:

```bash
pip check
```

Or use the built-in doctor command:

```bash
python agent/install/installer_cli.py doctor
```

This runs `pip check`, verifies `runtime_config.json` exists, and reports the
configured model filename.

---

## 6. Common Combinations by Use Case

| Use Case | Profiles | Approx. Total Size |
|----------|----------|-------------------|
| **Chat-only bot** (text in, text out) | Core | ~250 MB |
| **Voice assistant** | Core + Voice | ~850 MB |
| **Research agent** (PDFs, web, arXiv) | Core + Research + Crawl | ~560 MB |
| **Data analyst** (CSV, charts, finance) | Core + Research + Viz | ~380 MB |
| **Vision + OCR pipeline** | Core + Vision | ~1.75 GB |
| **Full ML workstation** | Core + ML + Vision + Voice | ~4.5 GB |
| **Everything** | All profiles + all packs | ~3.5-5 GB |
| **CI / testing** | Core + Dev | ~280 MB |

### Disk space tips

- `torch` is the biggest single dependency (~2 GB). It is pulled in by
  the ML profile and indirectly by Vision (easyocr depends on torch).
  If you install both ML and Vision, torch is shared -- no double download.
- `sentence-transformers` (part of Core) pulls a smaller torch subset
  via its own dependency chain. If you later add the full ML profile,
  pip upgrades in place.
- Model files (`.gguf`) are separate from pip packages. A typical model
  is 2-8 GB. They live in `~/.layla/models/` (or `models/` in the repo).

### Reproducible installs

For production or CI, pin exact versions:

```bash
# Generate a lock file from your current environment
pip freeze > agent/requirements-lock.txt

# Reproduce later
pip install -r agent/requirements-lock.txt
```

A partial lock file already exists at `agent/requirements-lock.txt` with
critical version pins for FastAPI, llama-cpp-python, chromadb, and others.
