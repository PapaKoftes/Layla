# Operator guide: sandbox and writable paths

Layla restricts file and shell tools to paths under your configured **sandbox** unless a tool explicitly resolves paths differently.

## Key config

- **`sandbox_root`** ([`agent/runtime_safety.py`](../agent/runtime_safety.py)) — typically your home directory or a dedicated folder. Resolved with `.expanduser().resolve()`.
- **`workspace_root`** on `POST /agent` — the active project folder; tools like `search_replace`, `grep_code`, etc. resolve relative paths against it when applicable.

## What “inside sandbox” means

[`layla/tools/registry.py`](../agent/layla/tools/registry.py) exposes `inside_sandbox(path)` checks used by filesystem and code tools. Paths **outside** the sandbox tree are rejected for those tools.

## Practical setup

1. Set **sandbox_root** wide enough for your repos (often `~` or `C:\Users\you`).
2. Set **workspace path** in the Web UI to the **repository** you are editing.
3. Enable **allow_write** / **allow_run** only when you intend mutations; approvals still apply for dangerous tools.

## Remote / LAN

If **`remote_enabled`** is true, read [**REMOTE_ARCHITECTURE.md**](REMOTE_ARCHITECTURE.md): bind address, Bearer token, and **`remote_allow_endpoints`** still apply—sandbox rules are **not** disabled by remote mode.
