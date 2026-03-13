---
priority: core
domain: tools
aspect: morrigan
---

# Tools Reference — All 40 Tools

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
