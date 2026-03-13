---
priority: core
domain: tools
aspect: morrigan
---

# Tools Reference — All 74 Tools

Layla's complete tool registry. Dangerous tools require `allow_run=true` AND approval via `POST /approve` before they execute.

---

## File System (read-only)

| Tool | Parameters | Notes |
|------|-----------|-------|
| `read_file` | `path: str` | Returns file content (first 8000 chars). Must be inside sandbox. |
| `file_info` | `path: str` | Size, line count, text vs binary. No content returned. |
| `list_dir` | `path: str` | Returns sorted list of `{name, type}` for all entries. |

## File System (write) — approval required

| Tool | Parameters | Notes |
|------|-----------|-------|
| `write_file` | `path: str, content: str` | Creates or overwrites file inside sandbox. |
| `apply_patch` | `original_path: str, patch_text: str` | Applies unified diff. Creates `.bak_*` backup first. |

## Code Search & Analysis

| Tool | Parameters | Notes |
|------|-----------|-------|
| `grep_code` | `pattern: str, path: str, file_glob: str = "*"` | Regex search in files. Uses ripgrep, falls back to Python. |
| `glob_files` | `pattern: str, root: str` | Find files by glob pattern. Returns up to 200 matches. |
| `json_query` | `path: str, query: str = ""` | Parse JSON + extract by dot-path. `"a.b.0.c"` → nested value. |
| `diff_files` | `path_a: str, path_b: str` | Unified diff of two files. |
| `regex_test` | `pattern: str, text: str, flags: str = ""` | Test regex, returns all matches + groups. Flags: i, m, s. |
| `understand_file` | `path: str, content: str = None` | Interprets file intent by extension and content. |

## Execution — approval required

| Tool | Parameters | Notes |
|------|-----------|-------|
| `shell` | `argv: list, cwd: str` | Run a shell command. Blocked commands: rm, del, rmdir, format, shutdown, etc. |
| `run_python` | `code: str, cwd: str` | Execute Python in subprocess. 30s timeout. Temp file, cleaned up after. |

## Git

| Tool | Parameters | Notes |
|------|-----------|-------|
| `git_status` | `repo: str` | Working tree status. |
| `git_diff` | `repo: str` | Unstaged + staged changes (first 8000 chars). |
| `git_log` | `repo: str, n: int = 10` | Last N commits (oneline format). |
| `git_branch` | `repo: str` | Current branch name. |
| `git_add` | `repo: str, path: str = "."` | Stage files. `"."` stages all. |
| `git_commit` | `repo: str, message: str, add_all: bool = False` | Commit staged changes. **Approval required.** |

## Web & Browser

| Tool | Parameters | Notes |
|------|-----------|-------|
| `fetch_url` | `url: str, store: bool = False` | HTTP fetch. Respects robots.txt + AI-exclusion. `store=True` saves to knowledge/fetched/. |
| `browser_navigate` | `url: str, timeout_ms: int = 15000` | Navigate + extract main text content. Requires playwright. |
| `browser_search` | `query: str` | DuckDuckGo search. Returns top 8 results with snippets. |
| `browser_screenshot` | `url: str` | Full-page screenshot. Returns path to PNG. |
| `browser_click` | `url: str, selector: str` | Navigate, click CSS selector, return updated page text. **Approval required.** |
| `browser_fill` | `url: str, fields: dict, submit_selector: str = ""` | Fill form fields `{selector: value}`. **Approval required.** |

## System & Environment

| Tool | Parameters | Notes |
|------|-----------|-------|
| `env_info` | _(none)_ | OS, Python version, RAM, CPU, GPU, key package versions. |

## Memory

| Tool | Parameters | Notes |
|------|-----------|-------|
| `save_note` | `content: str, tag: str = "note"` | Save a learning to Layla's memory mid-conversation. |
| `search_memories` | `query: str, n: int = 8` | Semantic search over Layla's own stored learnings. |

## Project Context

| Tool | Parameters | Notes |
|------|-----------|-------|
| `get_project_context` | _(none)_ | Current project name, domain, goals, lifecycle stage. |
| `update_project_context` | `project_name, domains, key_files, goals, lifecycle_stage` | Update project state. Lifecycle: idea/planning/prototype/iteration/execution/reflection. |
| `project_discovery` | `workspace_root: str = ""` | Auto-detect tech stack, entry points, structure. Falls back to manual file scan. |

## Research & Information

| Tool | Parameters | Notes |
|------|-----------|-------|
| `read_pdf` | `path: str, max_pages: int = 30` | Extract text from PDF via PyMuPDF (fitz) or pypdf fallback. |
| `fetch_article` | `url: str` | Clean article extraction via trafilatura — strips nav, ads, footers. Best for research reading. |
| `wiki_search` | `query: str, sentences: int = 8, lang: str = "en"` | Wikipedia summary. Returns title, URL, summary, related pages. Handles disambiguation gracefully. |
| `ddg_search` | `query: str, max_results: int = 10, region: str = "wt-wt"` | DuckDuckGo search. Pure Python — no browser required. Returns title, href, snippet. |
| `arxiv_search` | `query: str, max_results: int = 5, sort_by: str = "relevance"` | Search arXiv. Returns title, authors, abstract, PDF URL, categories. |

## Data & Analysis

| Tool | Parameters | Notes |
|------|-----------|-------|
| `read_csv` | `path: str, max_rows: int = 50, describe: bool = True` | Read CSV + stats summary via pandas. Falls back to stdlib csv if pandas unavailable. |
| `math_eval` | `expression: str` | Safe math: `sqrt(144) + pi * 2`. Strict AST whitelist, no exec. |
| `count_tokens` | `text: str, model: str = "gpt-4"` | Token count via tiktoken or ~4 chars/token estimate. |
| `http_request` | `url: str, method: str = "GET", body: str = "", headers: dict, timeout: int = 15` | General HTTP request. Use for REST APIs, webhooks, POST endpoints. |
| `python_ast` | `path: str` | Analyze Python file structure: functions, classes, imports, constants, line count. |

## Semantic Memory (Direct Access)

| Tool | Parameters | Notes |
|------|-----------|-------|
| `vector_search` | `query: str, collection: str = "knowledge", k: int = 8` | Direct semantic search over ChromaDB. collection: knowledge/memories/aspects. |
| `vector_store` | `text: str, metadata: dict, collection: str = "memories"` | Store text into vector DB + SQLite learnings. Embeds immediately. |

## File System Intelligence

| Tool | Parameters | Notes |
|------|-----------|-------|
| `workspace_map` | `root: str = "", max_files: int = 500, include_content_preview: bool = False` | Full workspace map: tech stack, entry points, key docs, largest files, recently modified, 2-level tree. |

## Web Crawl

| Tool | Parameters | Notes |
|------|-----------|-------|
| `crawl_site` | `url: str, max_pages: int = 20, max_depth: int = 2, same_domain: bool = True, store_knowledge: bool = False` | Recursive site crawl via trafilatura. store_knowledge=True saves pages to knowledge/fetched/ for RAG indexing. |

## Database Schema Intelligence

| Tool | Parameters | Notes |
|------|-----------|-------|
| `schema_introspect` | `db_path: str` | Full schema: tables, columns, types, PKs, FKs, row counts, 3-row samples. SQLite + DuckDB. |

## Tool Self-Reflection

| Tool | Parameters | Notes |
|------|-----------|-------|
| `list_tools` | `filter_by: str = "", include_dangerous: bool = True` | List all 59 tools with descriptions, risk levels, approval requirements. |
| `tool_recommend` | `task: str` | Given a task, suggest the most relevant tools (keyword + category scoring). |

## Context Management

| Tool | Parameters | Notes |
|------|-----------|-------|
| `context_compress` | `text: str, target_tokens: int = 2000, strategy: str = "smart"` | Compress text: smart (extractive), truncate, middle_out. Returns ratio + token estimates. |
| `generate_sql` | `question: str, schema: str = "", db_path: str = ""` | NL → SQL with schema grounding. Auto-introspects db_path if provided. Pair with sql_query() to execute. |

## Image Understanding

| Tool | Parameters | Notes |
|------|-----------|-------|
| `describe_image` | `path: str, detail: str = "brief"` | BLIP image captioning via transformers. Falls back to EasyOCR text extraction. First run downloads ~500 MB model. |

## NLP — Summarization, Classification, Translation

| Tool | Parameters | Notes |
|------|-----------|-------|
| `summarize_text` | `text: str, sentences: int = 5, method: str = "extractive"` | extractive (no deps) or abstractive (BART via transformers). |
| `classify_text` | `text: str, labels: list, threshold: float = 0.0` | zero-shot (transformers) → cosine (sentence-transformers) → keyword fallback. |
| `translate_text` | `text: str, target_lang: str = "en", source_lang: str = "auto"` | deep-translator (Google) → LibreTranslate public API fallback. |
| `text_stats` | `text: str` | Flesch readability, word/sentence counts, vocab richness, top words, reading time. |

## Code Intelligence (Extended)

| Tool | Parameters | Notes |
|------|-----------|-------|
| `code_symbols` | `path: str, include_private: bool = False` | Symbol index: functions, classes, methods, signatures, docstrings. File or directory. |
| `find_todos` | `path: str, tags: list = [...]` | Scan for TODO/FIXME/HACK/BUG/REVIEW/OPTIMIZE. Returns file+line+message. |
| `dependency_graph` | `path: str` | Python import graph. local vs external. networkx metrics if available. |

## URL Intelligence

| Tool | Parameters | Notes |
|------|-----------|-------|
| `extract_links` | `url: str, same_domain: bool = False, max_links: int = 100` | Extract hyperlinks from a page. Internal/external classification. |
| `check_url` | `url: str, timeout: int = 10` | HEAD request: status code, response time, content type, accessibility check. |

## Scientific Computation

| Tool | Parameters | Notes |
|------|-----------|-------|
| `scipy_compute` | `operation: str, params: dict` | ops: stats.describe/ttest/correlation/normalize, optimize.minimize, integrate.quad, fft, interpolate |

## Machine Learning

| Tool | Parameters | Notes |
|------|-----------|-------|
| `cluster_data` | `data: list, n_clusters: int = 3, method: str = "kmeans", features: list` | kmeans/dbscan/hierarchical. Input: list of dicts or numeric lists. Returns labels + stats. |
| `dataset_summary` | `path: str` | Full analysis: shape, dtypes, missing, numeric stats, correlations, categorical counts, quality flags. |

## RSS / Feeds

| Tool | Parameters | Notes |
|------|-----------|-------|
| `rss_feed` | `url: str, max_items: int = 20, include_content: bool = False` | Parse RSS/Atom. include_content=True fetches full article via trafilatura. |

## Embedding Generation

| Tool | Parameters | Notes |
|------|-----------|-------|
| `embedding_generate` | `text: str \| list, normalize: bool = True` | Generate embeddings using Layla's RAG model (nomic-embed-text). String or batch. |

## Image Utilities

| Tool | Parameters | Notes |
|------|-----------|-------|
| `image_resize` | `path: str, width: int = 0, height: int = 0, output_path: str = "", maintain_aspect: bool = True` | Pillow resize. One dimension is enough with maintain_aspect=True. |

## Symbolic & Advanced Math

| Tool | Parameters | Notes |
|------|-----------|-------|
| `sympy_solve` | `expression: str, variable: str = "x", mode: str = "solve"` | Modes: solve/diff/integrate/simplify/expand/factor/latex/numeric. Returns result + LaTeX. |

## NLP Intelligence

| Tool | Parameters | Notes |
|------|-----------|-------|
| `nlp_analyze` | `text: str, tasks: list = ["entities","keywords","sentiment","sentences"]` | spaCy NER + KeyBERT keywords + sentiment. Falls back to NLTK/heuristics. |

## Image & OCR

| Tool | Parameters | Notes |
|------|-----------|-------|
| `ocr_image` | `path: str, lang: str = "eng"` | EasyOCR first (no Tesseract binary needed), pytesseract+Pillow fallback. Returns text + confidence. |

## Visualization

| Tool | Parameters | Notes |
|------|-----------|-------|
| `plot_chart` | `data: dict, chart_type: str = "bar", title, output_path, xlabel, ylabel` | Types: bar/line/scatter/pie/histogram/heatmap. Saves PNG, returns path. Uses Agg backend (headless). |

## Document Formats (expanded)

| Tool | Parameters | Notes |
|------|-----------|-------|
| `read_docx` | `path: str` | Word document text + table data. Requires python-docx. |
| `read_excel` | `path: str, sheet: str = "", max_rows: int = 100` | Excel sheets + stats via pandas; openpyxl fallback. |

## Database Intelligence

| Tool | Parameters | Notes |
|------|-----------|-------|
| `sql_query` | `db_path: str, query: str, limit: int = 200` | SELECT queries on .db/.sqlite/.duckdb files. Auto-injects LIMIT. DuckDB handles in-memory. |

## Financial Intelligence

| Tool | Parameters | Notes |
|------|-----------|-------|
| `stock_data` | `ticker: str, period: str = "1mo", include_info: bool = True` | OHLCV data + company info. Supports stocks, ETFs, crypto (BTC-USD), indices (^GSPC). |

## Security Analysis

| Tool | Parameters | Notes |
|------|-----------|-------|
| `security_scan` | `path: str, scan_type: str = "bandit"` | `bandit`: Python CWE static analysis. `secrets`: pattern scan for API keys/tokens. `deps`: pip-audit vulnerability scan. |

---

## Tool Safety Model

```
dangerous: False  → executes immediately
dangerous: True   → requires allow_run=True AND approval_id to proceed

Approval flow:
1. Tool returns: {"ok": false, "reason": "approval_required", "approval_id": "<uuid>"}
2. Approve: POST /approve {"id": "<uuid>"} or python layla.py approve <uuid>
3. Next agent turn: tool executes with approved state
```

**Shell blocklist** (always blocked even with approval):
`rm`, `del`, `rmdir`, `format`, `mkfs`, `dd`, `shutdown`, `reboot`, `powershell`, `cmd`, `reg`, `netsh`, `sc`, `taskkill`, `cipher`

**Sandbox**: all file operations are confined to `sandbox_root` in `runtime_config.json`. Default: user home dir. Correctly handles `~` via `expanduser().resolve()`.
