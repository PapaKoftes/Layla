# Operator guide: approvals, diff preview, grants, undo

Layla gates dangerous tools behind **`allow_write`** / **`allow_run`**, **`runtime_safety.is_tool_allowed`**, and optional **pending approvals**.

## Typical flow

1. Model proposes a mutating tool → loop may return **`approval_required`** with **`approval_id`** (`GET /pending` lists rows).
2. **`POST /approve`** executes the stored tool call. The Web UI approvals panel shows **`args.diff`** when the server attached a preview ([`agent_loop._approval_preview_diff`](../agent/agent_loop.py)).
3. **Session grant:** checkbox flows map to **`grant_pattern`** / **`save_for_session`** ([`agent/routers/approvals.py`](../agent/routers/approvals.py)) so repeated similar actions avoid re-prompting within policy.
4. **`POST /undo`** is **git-oriented** (revert last Layla auto-commit when configured) — not “revoke approval id.” See [GOLDEN_FLOW.md](GOLDEN_FLOW.md).

## Verify in UI

1. Disable blanket auto-approve; provoke **`write_file`** or **`apply_patch`**.
2. Confirm pending appears; expand diff **`<pre>`** if shown.
3. Approve once; confirm tool result **`ok`** in the next **`GET /pending`** refresh.

Remote operators: keep **`remote_allow_endpoints`** minimal; approvals still apply. See [REMOTE_ARCHITECTURE.md](REMOTE_ARCHITECTURE.md).
