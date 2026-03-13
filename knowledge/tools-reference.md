---
priority: core
domain: tools
aspect: morrigan
---

# Tools Reference — All 29 Tools

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
