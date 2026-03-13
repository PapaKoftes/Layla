---
priority: core
domain: architecture
aspect: morrigan
---

# Layla Capabilities Map — 59 Tools

Full inventory of every tool Layla can call, organized by capability domain.
All tools are defined in `agent/layla/tools/registry.py`.

---

## 1. Core Reasoning

| Tool | What it does |
|------|-------------|
| `math_eval` | Safe AST-whitelist math: `sqrt(144)`, `pi * r**2`, trig, logs, factorial |
| `sympy_solve` | Symbolic math: solve equations, differentiate, integrate, simplify, factor, LaTeX output |
| `run_python` | Execute arbitrary Python in subprocess (approval required) |

**Missing (roadmap):** logic chain tracing, theorem provers.

---

## 2. Web Intelligence

| Tool | What it does |
|------|-------------|
| `fetch_url` | Raw HTTP fetch. Respects `robots.txt` + AI-exclusion headers. |
| `fetch_article` | Clean article extraction via trafilatura — strips nav/ads/footers |
| `ddg_search` | DuckDuckGo search, pure Python, no browser |
| `browser_navigate` | Full browser navigation + main text extraction (Playwright) |
| `browser_search` | Browser-based DuckDuckGo with rendered results |
| `browser_screenshot` | Full-page screenshot → PNG |
| `browser_click` | Click CSS selector on page (approval required) |
| `browser_fill` | Fill form fields + optional submit (approval required) |
| `crawl_site` | Recursive web crawl — multi-page, depth-limited, optional knowledge ingestion |

**Libraries active:** trafilatura, playwright, beautifulsoup4, httpx, requests

---

## 2b. Semantic Memory — Direct Tool Access

| Tool | What it does |
|------|-------------|
| `vector_search` | Direct ChromaDB semantic search — knowledge/memories/aspects collections |
| `vector_store` | Explicitly embed + store text into vector DB mid-conversation |

---

## 3. Knowledge Retrieval (RAG)

Not tools — these are automatic in every response:
- **BM25 hybrid search** — keyword precision
- **Dense vector search** (ChromaDB + nomic-embed-text) — semantic similarity
- **Reciprocal Rank Fusion** — merges BM25 + dense results
- **Cross-encoder reranking** — sentence-transformers rerank top candidates
- **HyDE** — Hypothetical Document Embeddings for underspecified queries
- **Parent-document retrieval** — returns full context around matched chunks
- **SQLite FTS5** — full-text search on learnings

**Libraries active:** chromadb, sentence-transformers, rank-bm25

---

## 4. Local File Intelligence

| Tool | What it does |
|------|-------------|
| `read_file` | Read text file content (sandboxed) |
| `file_info` | File size, line count, text vs binary detection |
| `list_dir` | Directory listing |
| `read_pdf` | PDF text extraction via PyMuPDF (fitz) or pypdf fallback |
| `read_docx` | Word document text + tables |
| `read_excel` | Excel sheets — data + statistical summary |
| `read_csv` | CSV with pandas stats; stdlib fallback |
| `json_query` | Parse JSON + extract by dot-path |
| `workspace_map` | Full workspace intelligence: tech stack, entry points, key docs, largest/recent files, directory tree |

---

## 5. Code Understanding

| Tool | What it does |
|------|-------------|
| `python_ast` | Full Python file structure: functions, classes, imports, constants |
| `grep_code` | Regex code search (ripgrep preferred, Python fallback) |
| `glob_files` | File discovery by glob pattern |
| `diff_files` | Unified diff of two files |
| `regex_test` | Test regex patterns, return all matches + groups |
| `understand_file` | Infer file purpose from extension + content |

**Roadmap:** tree-sitter (multi-language AST), jedi (jump-to-definition), semgrep

---

## 6. Software Engineering Automation

| Tool | What it does |
|------|-------------|
| `write_file` | Create/overwrite files inside sandbox (approval required) |
| `apply_patch` | Apply unified diff patch with automatic backup |
| `run_python` | Execute Python code in subprocess, 30s timeout |
| `shell` | Run shell command (blocklisted dangerous commands, approval required) |
| `git_status` | Working tree status |
| `git_diff` | Staged + unstaged changes |
| `git_log` | Recent commit history |
| `git_branch` | Current branch name |
| `git_add` | Stage files |
| `git_commit` | Commit staged changes (approval required) |

---

## 7. Memory Systems

| Tool | What it does |
|------|-------------|
| `save_note` | Save a learning to Layla's long-term memory |
| `search_memories` | Semantic search over stored learnings |
| `get_project_context` | Current project metadata: name, domain, goals, lifecycle |
| `update_project_context` | Update project state |

**Automatic memory:** SQLite WAL + FTS5, ChromaDB vector store, diskcache, networkx

---

## 8. Research & Scientific

| Tool | What it does |
|------|-------------|
| `wiki_search` | Wikipedia summaries + disambiguation + related pages |
| `arxiv_search` | arXiv paper search: title, authors, abstract, PDF URL, categories |
| `ddg_search` | Web search results with snippets |
| `fetch_article` | Clean extraction from any article URL |

---

## 8b. Database Schema Intelligence

| Tool | What it does |
|------|-------------|
| `schema_introspect` | Full DB schema: tables, columns, PKs, FKs, row counts, sample rows. SQLite + DuckDB |
| `generate_sql` | NL → SQL with schema auto-grounding. Pair with sql_query() to execute |

---

## 9. Data Science & Analysis

| Tool | What it does |
|------|-------------|
| `read_csv` | Pandas CSV + describe() stats |
| `read_excel` | Excel sheets + stats |
| `sql_query` | SQLite or DuckDB query execution (SELECT; others approval required) |
| `math_eval` | Safe math + stats functions |
| `sympy_solve` | Symbolic algebra, calculus |
| `plot_chart` | Generate PNG charts: bar, line, scatter, pie, histogram, heatmap |

**Roadmap (add if needed):** scikit-learn tools (cluster, classify, regress), statsmodels

---

## 10. Natural Language Intelligence

| Tool | What it does |
|------|-------------|
| `nlp_analyze` | Entity extraction, keywords (KeyBERT), sentiment, sentence segmentation |

**Libraries active:** keybert, spaCy (if `en_core_web_sm` installed), textblob fallback

**Roadmap:** summarize_text (LLM-based), translate_text (Helsinki-NLP models)

---

## 11. Image & Vision

| Tool | What it does |
|------|-------------|
| `ocr_image` | Text extraction from images via EasyOCR (no Tesseract binary) or pytesseract fallback |
| `describe_image` | BLIP image captioning (natural language description). Falls back to EasyOCR text. First run: ~500 MB model download. |

**Libraries active:** easyocr, Pillow; transformers+torch (optional for BLIP)
**Roadmap:** face_detect (opencv), object_detect (ultralytics/YOLO), segment (SAM)

---

## 12. Speech Intelligence

Not tools — integrated into API endpoints:
- **STT:** `POST /voice/transcribe` — faster-whisper (CPU/CUDA)
- **TTS:** `POST /voice/speak` — kokoro-onnx (fallback: browser SpeechSynthesis)

---

## 12b. Tool Self-Reflection & Context Management

| Tool | What it does |
|------|-------------|
| `list_tools` | List all 59 tools with descriptions, risk levels, approval status |
| `tool_recommend` | Given a task, suggest the most relevant tools (keyword + category scoring) |
| `context_compress` | Compress text to token budget: smart (extractive), truncate, middle_out |

---

## 13. System & Environment

| Tool | What it does |
|------|-------------|
| `env_info` | OS, Python version, RAM, CPU, GPU, installed package versions |
| `count_tokens` | Token count via tiktoken or ~4 chars/token estimate |
| `http_request` | General HTTP GET/POST/PUT/DELETE — for REST APIs and webhooks |
| `project_discovery` | Auto-detect workspace: stack, entry points, README summary |

---

## 14. Financial Intelligence

| Tool | What it does |
|------|-------------|
| `stock_data` | Stock/ETF/crypto OHLCV data via yfinance. Includes company info, P/E ratio, market cap. |

**Roadmap:** ccxt (crypto exchanges), pandas-datareader (FRED economic data)

---

## 15. Security Analysis

| Tool | What it does |
|------|-------------|
| `security_scan` | Three modes: `bandit` (Python CWE static analysis), `secrets` (hardcoded key detection), `deps` (pip-audit vulnerability scan) |

---

## Tool Safety Model

```
dangerous: False  → executes immediately (no approval needed)
dangerous: True   → requires allow_run=True AND approval_id to proceed
```

**Approval flow:**
1. Tool returns: `{"ok": false, "reason": "approval_required", "approval_id": "<uuid>"}`
2. Approve: `POST /approve {"id": "<uuid>"}` or `python layla.py approve <uuid>`

**Shell blocklist** (always blocked, even with approval):
`rm`, `del`, `rmdir`, `format`, `mkfs`, `dd`, `shutdown`, `reboot`, `powershell`, `cmd`, `reg`, `netsh`, `sc`, `taskkill`, `cipher`

**Sandbox:** all file tools confined to `sandbox_root` in `runtime_config.json`. Uses `expanduser().resolve()` to handle `~`.

---

## What's Next (Roadmap Tier 2)

| Capability | Library | Tool to build |
|-----------|---------|---------------|
| ML clustering/regression | scikit-learn | `ml_analyze(data, task)` |
| Multi-language AST | tree-sitter | `ast_any_lang(path, lang)` |
| FAISS fast search | faiss-cpu | upgrades `vector_store.py` search speed |
| Geography | geopandas + folium | `geo_query(location)` |
| Docker control | docker SDK | `docker_run(image, cmd)` |
| Email | imaplib | `read_email(folder)` |
| Video frames | ffmpeg-python | `extract_frames(path, fps)` |
| Dependency graph | pyan + networkx | `dep_graph(path)` |
| NSFW content filter | transformers | `content_check(text)` |
| Transcript download | yt-dlp | `yt_transcript(url)` |
| Interactive charts | plotly | `plot_interactive(data)` |
| Clipboard | pyperclip | `clipboard_get/set()` |
