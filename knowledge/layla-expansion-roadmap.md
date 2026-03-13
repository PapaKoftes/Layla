---
priority: core
domain: architecture
aspect: morrigan
---

# Layla Expansion Roadmap — Full 20-Domain Capability Architecture

This document is the canonical capability map. It tracks what's built, what's next,
and how the system scales from 74 tools (current) toward 120+.

---

## Tier Overview

| Tier | Tool Count | Status | Focus |
|------|-----------|--------|-------|
| **Tier 1** | 1–59 tools | ✅ Complete | Core infrastructure, all major domains seeded |
| **Tier 2** | 60–80 tools | ✅ 74 built | Deep per-domain capability, ML, NLP, science |
| **Tier 3** | 81–120+ tools | 🔜 Planned | Video, desktop automation, geo, orchestration, devops |

---

## Domain 1 — Core Reasoning Systems

**Purpose:** Give Layla access to symbolic algebra, numerical methods, statistics, and scientific computation as first-class capabilities — not just number crunching but real mathematical reasoning.

| Tool | Status | Description |
|------|--------|-------------|
| `math_eval` | ✅ | Safe AST-whitelist evaluator: trig, logs, factorial, etc. |
| `sympy_solve` | ✅ | Symbolic: solve/diff/integrate/simplify/factor/latex via SymPy |
| `scipy_compute` | ✅ | Stats (describe, t-test, correlation, normalize), optimization, FFT, interpolation |

**Libraries:** sympy, scipy, numpy (all active)
**Roadmap:** `numba_jit(code)` for just-in-time compiled numeric loops, matrix ops via `numpy_compute`

---

## Domain 2 — Web Intelligence

**Purpose:** Full web stack — from raw HTTP to structured extraction to multi-page crawls to rendered browser interaction.

| Tool | Status | Description |
|------|--------|-------------|
| `fetch_url` | ✅ | Raw HTTP. Respects robots.txt + AI-exclusion. |
| `fetch_article` | ✅ | trafilatura clean article extraction |
| `ddg_search` | ✅ | DuckDuckGo search, pure Python |
| `browser_navigate` | ✅ | Playwright: navigate + extract content |
| `browser_search` | ✅ | Playwright: rendered search results |
| `browser_screenshot` | ✅ | Full-page PNG |
| `browser_click` | ✅ | Click CSS selector (approval required) |
| `browser_fill` | ✅ | Fill form + submit (approval required) |
| `crawl_site` | ✅ | Recursive multi-page crawl, optional knowledge ingestion |
| `extract_links` | ✅ | Extract all hyperlinks, internal/external classification |
| `check_url` | ✅ | HEAD request: status code, response time, content type |
| `http_request` | ✅ | General GET/POST/PUT/DELETE for REST APIs |

**Libraries:** trafilatura, playwright, beautifulsoup4, httpx, requests
**Roadmap:** `monitor_url(url, interval)` for change detection, `rss_search(query)` for feed discovery

---

## Domain 3 — Knowledge Retrieval (Vector Memory)

**Purpose:** Semantic memory — store, retrieve, and reason over large document sets without re-reading everything.

| Tool | Status | Description |
|------|--------|-------------|
| `vector_search` | ✅ | Direct ChromaDB semantic search (knowledge/memories/aspects) |
| `vector_store` | ✅ | Store text into vector DB + SQLite learnings |
| `embedding_generate` | ✅ | Expose RAG embedder as a tool (nomic-embed-text) |
| `search_memories` | ✅ | Full RAG pipeline: BM25 + dense + RRF + rerank |
| `save_note` | ✅ | Save to long-term memory mid-conversation |

**Automatic (not tools):** BM25 hybrid, cross-encoder rerank, HyDE, parent-doc retrieval, FTS5
**Libraries:** chromadb, sentence-transformers, rank-bm25
**Roadmap:** `vector_delete(id)`, `vector_list_collections()`, faiss-cpu integration for faster ANN

---

## Domain 4 — File System Intelligence

**Purpose:** Navigate and understand codebases, projects, and file hierarchies at scale.

| Tool | Status | Description |
|------|--------|-------------|
| `read_file` | ✅ | Read text file (sandboxed) |
| `list_dir` | ✅ | Directory listing |
| `file_info` | ✅ | Size, line count, type |
| `glob_files` | ✅ | Pattern-based file discovery |
| `workspace_map` | ✅ | Tech stack detection, entry points, key docs, tree |
| `project_discovery` | ✅ | Auto-detect stack, README, structure |
| `understand_file` | ✅ | Infer file purpose from extension + content |

**Libraries:** pathlib (stdlib), pathspec (planned)
**Roadmap:** `watch_file(path)` via watchdog, `file_index(root)` for fast inotify-based indexing

---

## Domain 5 — Code Understanding

**Purpose:** Treat source code as structured data — navigate symbols, trace dependencies, find issues.

| Tool | Status | Description |
|------|--------|-------------|
| `python_ast` | ✅ | Full Python structure: functions, classes, imports, constants |
| `code_symbols` | ✅ | Symbol index with signatures, docstrings, parent classes |
| `grep_code` | ✅ | Regex search in files (ripgrep preferred) |
| `diff_files` | ✅ | Unified diff of two files |
| `regex_test` | ✅ | Test regex patterns against text |
| `find_todos` | ✅ | Scan for TODO/FIXME/HACK/BUG/REVIEW comments |
| `dependency_graph` | ✅ | Python import graph + networkx metrics |
| `security_scan` | ✅ | bandit CWE analysis, secrets scan, pip-audit |

**Libraries:** ast (stdlib), bandit, networkx
**Roadmap:** `code_summary(path)` (LLM-based file summary), tree-sitter for multi-language AST

---

## Domain 6 — Data Science

**Purpose:** Statistical and ML analysis on real datasets — from summary stats to clustering to prediction.

| Tool | Status | Description |
|------|--------|-------------|
| `read_csv` | ✅ | CSV reading + basic stats |
| `dataset_summary` | ✅ | Full analysis: shape, dtypes, missing, correlations, categoricals, quality flags |
| `cluster_data` | ✅ | K-means, DBSCAN, hierarchical clustering via sklearn |
| `scipy_compute` | ✅ | Statistical tests, optimization, signal processing |
| `sql_query` | ✅ | SQLite + DuckDB queries |
| `schema_introspect` | ✅ | Full DB schema inspection |
| `generate_sql` | ✅ | NL to SQL with schema grounding |

**Libraries:** pandas, scikit-learn, scipy, duckdb
**Roadmap:** `train_regression(X, y)`, `predict_model(model_path, X)`, `feature_importance(model)`, statsmodels integration

---

## Domain 7 — Visualization

**Purpose:** Turn data into visual artifacts — charts Layla can generate and share as file paths.

| Tool | Status | Description |
|------|--------|-------------|
| `plot_chart` | ✅ | bar/line/scatter/pie/histogram/heatmap → PNG (headless matplotlib) |

**Libraries:** matplotlib (Agg backend — headless, always safe)
**Roadmap:** `plot_scatter`, `plot_histogram` as dedicated tools with regression overlays, plotly for interactive HTML charts

---

## Domain 8 — Natural Language Intelligence

**Purpose:** Deep text understanding beyond keyword matching — classify, summarize, translate, extract.

| Tool | Status | Description |
|------|--------|-------------|
| `nlp_analyze` | ✅ | Entity extraction (spaCy), KeyBERT keywords, sentiment |
| `summarize_text` | ✅ | Extractive (fast, no deps) or abstractive (BART, optional) |
| `classify_text` | ✅ | Zero-shot (transformers) → cosine (sentence-transformers) → keyword fallback |
| `translate_text` | ✅ | deep-translator (Google) → LibreTranslate fallback |
| `text_stats` | ✅ | Flesch readability, word freq, reading time, vocabulary richness |

**Libraries:** keybert, spaCy (optional), sentence-transformers, deep-translator, feedparser
**Roadmap:** `extract_entities(text, types)` for named entity lists, `sentiment_timeline(texts)` for series analysis

---

## Domain 9 — Speech Intelligence

**Purpose:** Voice in, voice out — Layla can hear and speak.

| Tool | Status | Description |
|------|--------|-------------|
| `speech_to_text` | ✅ | API endpoint: POST /voice/transcribe (faster-whisper) |
| `text_to_speech` | ✅ | API endpoint: POST /voice/speak (kokoro-onnx, pyttsx3 fallback) |

**Note:** These are API endpoints, not registry tools. Accessible from UI mic button.
**Roadmap:** Expose as registry tools `stt(audio_path)` and `tts(text, voice)` for pipeline use

---

## Domain 10 — Image Intelligence

**Purpose:** Extract information from visual content — text, objects, captions.

| Tool | Status | Description |
|------|--------|-------------|
| `ocr_image` | ✅ | EasyOCR text extraction, pytesseract fallback |
| `describe_image` | ✅ | BLIP image captioning (transformers optional), EasyOCR fallback |
| `image_resize` | ✅ | Resize with aspect-ratio preservation (Pillow) |

**Libraries:** easyocr, Pillow; transformers+torch (optional)
**Roadmap:** `detect_objects(path)` via ultralytics YOLO, `segment_image(path)` via SAM

---

## Domain 11 — Video Intelligence

**Purpose:** Frame-level understanding of video content.

| Tool | Status | Description |
|------|--------|-------------|
| All | 🔜 Tier 3 | Not yet implemented |

**Planned tools:** `extract_frames(path, fps)`, `detect_scenes(path)`, `summarize_video(path)`
**Libraries needed:** ffmpeg-python, moviepy, pyscenedetect

---

## Domain 12 — Database Intelligence

**Purpose:** Treat any database as queryable context.

| Tool | Status | Description |
|------|--------|-------------|
| `sql_query` | ✅ | SQLite + DuckDB SELECT (auto LIMIT), writes need approval |
| `schema_introspect` | ✅ | Full schema: tables, FKs, row counts, samples |
| `generate_sql` | ✅ | NL → SQL with schema context |

**Libraries:** sqlite3 (stdlib), duckdb
**Roadmap:** PostgreSQL support via psycopg, `query_optimize(sql)` for EXPLAIN analysis

---

## Domain 13 — Financial Intelligence

**Purpose:** Real-time and historical market data.

| Tool | Status | Description |
|------|--------|-------------|
| `stock_data` | ✅ | yfinance: stocks, ETFs, crypto OHLCV + company info |

**Libraries:** yfinance
**Roadmap:** `crypto_prices(symbols)` via ccxt, `economic_indicators(series)` via FRED API

---

## Domain 14 — Geographic Intelligence

| Tool | Status | Description |
|------|--------|-------------|
| All | 🔜 Tier 3 | Not yet implemented |

**Planned tools:** `geo_query(location)` (geocode, get metadata), `map_url(center, markers)` (static map URL)
**Libraries needed:** geopy, folium

---

## Domain 15 — Automation & Control

| Tool | Status | Description |
|------|--------|-------------|
| All | 🔜 Tier 3 | Not yet implemented |

**Planned tools:** `click_ui(x, y)`, `type_text(text)`, `open_app(name)`, `screenshot_desktop()`
**Libraries needed:** pyautogui, pywinauto (Windows)
**Note:** These are high-risk — require strict approval + sandbox

---

## Domain 16 — Browser Control

Already covered under Domain 2 via Playwright tools.

---

## Domain 17 — Scheduling & Background Tasks

**Purpose:** Layla can be asked to run something later or repeatedly.

| Tool | Status | Description |
|------|--------|-------------|
| All | 🔜 Tier 2.5 | APScheduler installed, not yet exposed as tool |

**Planned tools:** `schedule_task(tool_name, args, cron_or_delay)`, `list_scheduled_tasks()`, `cancel_task(id)`
**Libraries needed:** APScheduler (already installed), celery (optional for distributed)

---

## Domain 18 — Observability & Debugging

**Purpose:** Make the agent debuggable and traceable.

| Tool | Status | Description |
|------|--------|-------------|
| All | 🔜 Tier 3 | Audit log exists; no tool-level tracing exposed |

**Planned tools:** `trace_last_run()` (tool call history from audit log), `log_event(msg, level, ctx)`, `tool_metrics()` (call counts, latencies)
**Libraries:** loguru (optional), opentelemetry (optional)

---

## Domain 19 — Tool Self-Awareness

**Purpose:** Layla knows her own capabilities and can reason about tool selection.

| Tool | Status | Description |
|------|--------|-------------|
| `list_tools` | ✅ | List all 74 tools with descriptions, risk levels |
| `tool_recommend` | ✅ | Recommend tools for a given task (keyword + category scoring) |

**Roadmap:** `tool_chain_plan(goal)` — decompose a goal into a multi-tool execution plan

---

## Domain 20 — Agent Orchestration

**Purpose:** Spawn sub-agents, delegate tasks, run parallel research missions.

| Tool | Status | Description |
|------|--------|-------------|
| All | 🔜 Tier 3 | Research mission system exists (/research_mission); no spawning yet |

**Planned tools:** `spawn_agent(role, goal)`, `delegate_task(agent_id, task)`, `agent_plan(goal)`, `agent_status(id)`
**Projects:** LangGraph patterns, AutoGen-style multi-agent loops
**Note:** Multi-agent requires careful governance — every spawned agent inherits safety rules

---

## Expansion Roadmap — Next Steps to Reach 120 Tools

### Tier 2.5 (74 → 85): No heavy new deps

| Tool | Domain | Effort |
|------|--------|--------|
| `schedule_task` | Scheduling | Low — APScheduler already installed |
| `list_scheduled_tasks` | Scheduling | Low |
| `cancel_task` | Scheduling | Low |
| `log_event` | Observability | Low — stdlib logging |
| `trace_last_run` | Observability | Medium — parse audit.log |
| `stt(audio_path)` | Speech | Low — wrap existing /voice/transcribe |
| `tts(text, voice)` | Speech | Low — wrap existing /voice/speak |
| `crypto_prices` | Finance | Low — yfinance or ccxt |
| `economic_indicators` | Finance | Medium — FRED API |
| `tool_chain_plan` | Self-awareness | Medium — LLM-assisted decomposition |
| `plot_scatter` | Visualization | Low — wrapper around plot_chart |

### Tier 3 (85 → 120): New deps required

| Tool | Domain | Dep needed |
|------|--------|-----------|
| `extract_frames` | Video | ffmpeg-python, moviepy |
| `detect_scenes` | Video | pyscenedetect |
| `summarize_video` | Video | above + model |
| `detect_objects` | Image | ultralytics |
| `geo_query` | Geographic | geopy |
| `map_url` | Geographic | folium |
| `click_ui` | Automation | pyautogui |
| `type_text` | Automation | pyautogui |
| `open_app` | Automation | pyautogui |
| `spawn_agent` | Orchestration | LangGraph or custom |
| `delegate_task` | Orchestration | above |
| `query_optimize` | Database | sqlalchemy |
| `train_regression` | Data Science | scikit-learn (optional) |
| `predict_model` | Data Science | scikit-learn (optional) |
| `monitor_url` | Web | scheduler + above |
| `watch_file` | File System | watchdog |
| `code_summary` | Code | LLM pass |
| `ast_any_lang` | Code | tree-sitter |
| `dep_graph_vis` | Code | networkx + plot_chart |
| `sentiment_timeline` | NLP | pandas + above |

---

## Architecture Notes

### Tool Design Principles

1. **Graceful degradation** — every tool has a fallback if an optional dep is missing. Never crash, always return `{"ok": False, "error": "install X: pip install X"}`.
2. **Lazy imports** — all deps imported inside function body. Zero startup cost for unused tools.
3. **Sandbox enforcement** — file tools check `inside_sandbox()`. HTTP tools respect robots.txt. Shell/run_python require approval.
4. **Approval gating** — dangerous tools (write_file, shell, run_python, git_commit, apply_patch, browser_click, browser_fill) all require `allow_run=True` + `POST /approve`.
5. **Consistent return shape** — always `{"ok": bool, ...}`. Never raise exceptions to caller.

### Orchestration Architecture

At 74+ tools, the agent needs to:
1. Decompose a goal into sub-tasks (`tool_chain_plan`)
2. Select the right tool for each step (`tool_recommend`)
3. Manage context window across many tool calls (`context_compress`)
4. Store intermediate results in memory (`vector_store`, `save_note`)
5. Reflect on its own approach (`list_tools`, re-planning loop)

The `agent_loop.py` already implements the core loop. Adding `tool_chain_plan` + a multi-step planner is the next architectural leap.

---

*Last updated: current session. Tool counts verified against `agent/layla/tools/registry.py`.*
