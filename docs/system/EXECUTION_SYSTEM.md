# Execution system (agent loop and tools)

Sources: [`agent/agent_loop.py`](../../agent/agent_loop.py), [`agent/core/executor.py`](../../agent/core/executor.py), [`agent/runtime_safety.py`](../../agent/runtime_safety.py), [`agent/routers/approvals.py`](../../agent/routers/approvals.py).

## Tool dispatch path (generic)

- **`core.executor.run_tool`** ([`agent/core/executor.py`](../../agent/core/executor.py)): loads **`TOOLS[tool_name]["fn"]`**, strips **`goal`** from args, sets thread-local sandbox via **`set_effective_sandbox`**, runs **`pre_tool` / `post_tool` hooks**, applies **timeout** via **`ThreadPoolExecutor`**, caps JSON output size (**256 KB**), returns dict-shaped results.

## Agent loop integration

- **`agent_loop`** imports **`run_tool` as `_run_tool`** and invokes it after intent/args resolution (see tool branch in **`agent_loop`**). **`runtime_safety.log_execution`** is called after successful dispatch paths as implemented in source.

## Approvals (high level)

- Tools may have registry metadata **`require_approval`**. Pending entries are written via **`_write_pending`** in **`agent_loop`** to **`agent/.governance/pending.json`** with **`expires_at`** derived from **`approval_ttl_seconds`** (minimum 60 seconds on write).
- **`runtime_safety.is_tool_allowed(tool_name)`** ([`runtime_safety.py`](../../agent/runtime_safety.py)): tools in **`SAFE_TOOLS`** always allowed; tools in **`DANGEROUS_TOOLS`** require **`approvals.json`** grant (or **`admin_mode`** bypass per code).
- **`POST /approve`** ([`approvals.py`](../../agent/routers/approvals.py)) executes **`TOOLS[tool_name]["fn"](**args)`** after approval and updates pending state.

## Output validation

- **`_maybe_validate_tool_output`** and optional **`core.validator.validate`** run on tool results in **`agent_loop`** as implemented; certain synthetic **`reason`** values skip validation (see **`_SKIP_TOOL_OUTPUT_VALIDATION`** frozenset in **`agent_loop`**).

## This document does not specify

- Full branching inside **`_autonomous_run_impl_core`** (file is large). Refer to **`agent/agent_loop.py`** for line-level behavior.
