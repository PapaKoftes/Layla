# Operator guide: sandbox and writable paths

Layla's dedicated file tools (read/write/edit) are path-jailed to your configured **sandbox** (the jail holds against `..`, UNC, and junction tricks). Shell and `run_python` are different: they only require their *working directory* to be inside the sandbox — the command itself runs as your OS user with full host access, gated by a destructive-command denylist and the approval gate (which is the real boundary, not the denylist).

## Key config

- **`sandbox_root`** ([`agent/runtime_safety.py`](../agent/runtime_safety.py)) — typically your home directory or a dedicated folder. Resolved with `.expanduser().resolve()`.
- **`workspace_root`** on `POST /agent` — the active project folder; tools like `search_replace`, `grep_code`, etc. resolve relative paths against it when applicable.

## What “inside sandbox” means

[`layla/tools/registry.py`](../agent/layla/tools/registry.py) exposes `inside_sandbox(path)`. The filesystem read/write/edit tools reject paths **outside** the sandbox tree. Shell/`run_python` check only that their working directory is inside the tree — they do **not** confine what the launched process can then read, write, or reach on the network.

## Practical setup

1. Set **sandbox_root** wide enough for your repos (often `~` or `C:\Users\you`).
2. Set **workspace path** in the Web UI to the **repository** you are editing.
3. Enable **allow_write** / **allow_run** only when you intend mutations; approvals still apply for dangerous tools.

## Remote / LAN

If **`remote_enabled`** is true, read [**REMOTE_ARCHITECTURE.md**](REMOTE_ARCHITECTURE.md): bind address, Bearer token, and **`remote_allow_endpoints`** still apply—sandbox rules are **not** disabled by remote mode.
