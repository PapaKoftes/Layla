---
priority: support
domain: tools
---

# Layla's Tools — What She Can Do

Layla has 21 registered tools she can invoke autonomously to complete tasks. High-risk tools require approval before executing.

## File tools (no approval needed)

| Tool | What it does |
|---|---|
| `read_file` | Read a file's contents |
| `list_dir` | List files and directories |
| `file_info` | Size, mtime, type of a file |
| `understand_file` | Deep analysis of a code file (language, purpose, key functions) |
| `glob_files` | Find files matching a pattern |
| `grep_code` | Search file contents by regex |

## File modification (requires approval)

| Tool | What it does |
|---|---|
| `write_file` | Write content to a file |
| `apply_patch` | Apply a unified diff patch |

## Git tools (no approval)

| Tool | What it does |
|---|---|
| `git_status` | Current git status |
| `git_diff` | Staged and unstaged changes |
| `git_log` | Recent commits |
| `git_branch` | List branches |

## Execution tools (requires approval)

| Tool | What it does |
|---|---|
| `shell` | Run a shell command in the sandbox |
| `run_python` | Execute Python code in a sandbox |

Risk levels: `shell` is HIGH, `run_python` is HIGH, `write_file` is MEDIUM.

## Web tools

| Tool | What it does | Approval |
|---|---|---|
| `fetch_url` | Fetch and extract text from a URL | No |
| `browser_navigate` | Navigate to a URL, return main text | No |
| `browser_search` | DuckDuckGo search, return top 8 results | No |
| `browser_screenshot` | Full-page screenshot of a URL | No |
| `browser_click` | Navigate + click a CSS selector | Yes |
| `browser_fill` | Fill form fields, optionally submit | Yes |

Browser tools require Playwright: `playwright install chromium`

## Project context tools

| Tool | What it does |
|---|---|
| `get_project_context` | Read the stored project context summary |
| `update_project_context` | Update the project context summary |

## Approval flow

When a dangerous tool is requested, Layla returns:
```json
{"ok": false, "reason": "approval_required", "approval_id": "<uuid>"}
```

Approve via:
- Web UI: Approvals panel → Approve
- CLI: `python layla.py approve <uuid>`
- API: `POST /approve {"id": "<uuid>"}`
- Cursor: `approve_action` MCP tool

## Sandbox

All file and shell operations are sandboxed to `sandbox_root` in the config. Default: your home directory. Operations outside this path return an error.

## Tool blocklist

The following commands are never allowed even with `allow_run=true`:
`rm -rf`, `del`, `rmdir /s`, `format`, `mkfs`, `dd` (disk operations), `powershell`, `cmd` (shell escalation)

## Adding custom tools

1. Define a Python function in `agent/layla/tools/registry.py`
2. Add it to the `TOOLS` dict with appropriate `dangerous`, `require_approval`, and `risk_level` settings
3. Restart Layla — tools are registered at import time
