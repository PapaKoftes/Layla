# 04 -- Tools, Safety & Governance

> Design document for the Layla AI tool execution, sandboxing, safety layers,
> and governance subsystem.

| Field | Value |
|---|---|
| **Status** | Living document |
| **Scope** | Tool registry, dispatch pipeline, sandbox, safety layers, session grants, loop detection, plan governance |
| **Key files** | `agent/services/tool_dispatch.py`, `agent/layla/tools/registry.py`, `agent/layla/tools/sandbox_core.py`, `agent/services/agent_safety.py`, `agent/runtime_safety.py`, `agent/services/dignity_engine.py`, `agent/services/content_guard.py`, `agent/services/session_grants.py`, `agent/services/tool_loop_detection.py`, `agent/services/decision_policy.py`, `agent/services/plan_step_governance.py` |

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Tool Registry](#2-tool-registry)
3. [Tool Dispatch Pipeline](#3-tool-dispatch-pipeline)
4. [Sandbox System](#4-sandbox-system)
5. [Safety Layers](#5-safety-layers)
6. [Governance -- Approval & Permission Model](#6-governance----approval--permission-model)
7. [Session Grants](#7-session-grants)
8. [Loop Detection](#8-loop-detection)
9. [Decision Policy](#9-decision-policy)
10. [Plan Step Governance](#10-plan-step-governance)
11. [Complete Tool Inventory](#11-complete-tool-inventory)
12. [Known Issues](#12-known-issues)
13. [Stability Assessment](#13-stability-assessment)

---

## 1. Architecture Overview

The Tools, Safety & Governance subsystem is a layered defense-in-depth system that
controls every action Layla takes in the real world. It can be understood as a
pipeline with four major stages:

```
User Message
    |
    v
[Content Guard]      -- Tier 1/2 content filter (pre-model)
    |
    v
[Dignity Engine]     -- Abuse/disrespect detector (pre-model)
    |
    v
[LLM Inference]      -- Model produces a decision/intent
    |
    v
[Agent Safety Gate]  -- planning_strict_mode, step tool allowlist
    |
    v
[Decision Policy]    -- PolicyCaps: forbidden tools, verify-before-mutate
    |
    v
[Tool Args Validation] -- Schema check on structured args
    |
    v
[Loop Detection]     -- Repeat / ping-pong pattern detector
    |
    v
[Approval Gate]      -- SAFE_TOOLS / DANGEROUS_TOOLS / session grants
    |
    v
[Sandbox Check]      -- Path inside sandbox_root?
    |
    v
[Tool Execution]     -- Actual tool function call
    |
    v
[Output Validation]  -- Deterministic verify + retry
    |
    v
[Post-Execution]     -- Auto-commit, lint/test/fix, verification
    |
    v
[Content Guard]      -- Tier 1/2 content filter (post-model)
```

### Key Principles

- **Defense in depth**: Multiple independent safety layers, each with its own
  config flag. No single layer is a single point of failure.
- **Fail-closed**: When checks cannot determine safety, they block.
  Missing approvals default to denial. Missing config defaults to safe values.
- **Audit trail**: Every tool execution is logged to `.governance/execution_log.json`
  with timestamp and payload.
- **Protected files**: Critical agent files (`main.py`, `agent_loop.py`,
  `runtime_safety.py`) are backed up before mutation.

---

## 2. Tool Registry

### Source Files

| File | Role |
|---|---|
| `agent/layla/tools/registry.py` | Assembles `TOOLS` dict, wraps with metrics, validates |
| `agent/layla/tools/registry_body.py` | Re-exports all implementation functions from `impl/` submodules |
| `agent/layla/tools/domains/*.py` | Declarative metadata per domain (11 domain modules) |
| `agent/layla/tools/impl/*.py` | Actual tool function implementations (11 impl modules) |

### How Tools Are Registered

1. **Domain modules** (`domains/file.py`, `domains/code.py`, etc.) define a `TOOLS`
   dict containing metadata only -- no function references. Each entry specifies:
   - `dangerous: bool` -- whether the tool can mutate state
   - `require_approval: bool` -- whether explicit approval is needed
   - `risk_level: str` -- `"low"`, `"medium"`, or `"high"`
   - `category: str` -- functional grouping
   - `description: str` -- human-readable purpose
   - `concurrency_safe: bool` (optional) -- safe for parallel calls
   - `fn_key: str` (optional) -- if the function name differs from the tool name

2. **`_build_tools_from_domains(impl)`** merges all 11 domain dicts into a single
   `TOOLS` dict, resolving each tool's `fn_key` (or name) to an actual callable
   from `registry_body`.

3. **Metrics wrapping**: Every tool function is wrapped by `_wrap_tool_with_metrics`
   to record execution latency via `services.observability.log_tool_result`.
   Optional OpenTelemetry spans are emitted when `opentelemetry_enabled` is True.

4. **TOOLS dict injection**: The assembled `TOOLS` dict is injected back into
   `registry_body` and every `impl.*` submodule so tool implementations can
   reference each other.

5. **Validation** (`validate_tools_registry()`): Enforces a minimum tool count
   threshold (50) and checks that every entry has `fn`, `name`, `description`,
   `category`, and `risk_level`. Missing metadata is auto-filled with defaults:
   - Missing `category` -> `"general"`
   - Missing `risk_level` -> `"medium"` if dangerous, `"low"` otherwise
   - Missing `description` -> first line of docstring or humanized name

### Domain Modules

| Domain Module | Import Name | Count | Categories |
|---|---|---|---|
| `domains/file.py` | `FILE_TOOLS` | 30 | filesystem, fabrication, system, code, memory |
| `domains/code.py` | `CODE_TOOLS` | 15 | code, fabrication |
| `domains/git.py` | `GIT_TOOLS` | 14 | git |
| `domains/web.py` | `WEB_TOOLS` | 15 | web, search |
| `domains/memory.py` | `MEMORY_TOOLS` | 12 | memory |
| `domains/system.py` | `SYSTEM_TOOLS` | 12 | system |
| `domains/general.py` | `GENERAL_TOOLS` | 37 | planning, memory, system, filesystem, code, search, voice |
| `domains/data.py` | `DATA_TOOLS` | 9 | data, search |
| `domains/analysis.py` | `ANALYSIS_TOOLS` | 19 | data, planning, system, code |
| `domains/automation.py` | `AUTOMATION_TOOLS` | 14 | planning, web, system, git, fabrication |
| `domains/geometry.py` | `GEOMETRY_TOOLS` | 10 | fabrication |

---

## 3. Tool Dispatch Pipeline

### Source File

`agent/services/tool_dispatch.py` (~1115 lines)

### Data Structures

```python
@dataclass
class DispatchContext:
    state: dict           # Agent loop state (steps, tool_calls, etc.)
    cfg: dict             # Runtime config
    workspace: str        # Current workspace root path
    decision: dict | None # LLM's structured decision
    allow_write: bool     # Write permissions for this run
    allow_run: bool       # Execute permissions for this run
    reasoning_mode: str   # "none" | "light" | "full"
    ux_state_queue: Any   # Optional queue for UI state events
    show_thinking: bool   # Whether to emit thinking steps

@dataclass
class DispatchResult:
    handled: bool = False  # True if intent was recognized
    flow: str = "continue" # "continue" or "break" (exit loop)
    goal: str = ""         # Updated goal string for next iteration
```

### Dispatch Entry Point

`dispatch_tool_intent(intent, goal, ctx) -> DispatchResult`

Resolution order:

1. **Handler map lookup**: `_HANDLER_MAP` maps 20 intent names to dedicated handlers
2. **Extended tools**: `_EXTENDED_TOOLS` set (7 tools: `json_query`, `diff_files`,
   `env_info`, `regex_test`, `save_note`, `search_memories`, `git_add`) -- dispatched
   without approval via `_handle_extended_tools`
3. **Generic dispatch**: Any tool in `TOOLS` not in `_HARDCODED_INTENTS` goes through
   `_handle_generic`
4. **Unhandled**: Returns `DispatchResult(handled=False)` for non-tool intents
   (`reason`, `finish`, etc.)

### Hardcoded Intent Handlers

| Intent | Handler | Approval? | Notes |
|---|---|---|---|
| `write_file` | `_handle_write_file` | Yes | Protected file backup, lab-root path restriction, auto-commit, lint |
| `write_files_batch` | `_handle_write_files_batch` | Yes | Batch deterministic verify, auto-commit |
| `read_file` | `_handle_read_file` | No | Pre-probe file guidance |
| `list_dir` | `_handle_list_dir` | No | Falls back to workspace root |
| `git_status/diff/log/branch` | `_handle_simple_git` | No | Read-only git commands |
| `grep_code` | `_handle_grep_code` | No | Pre-probe for file paths |
| `glob_files` | `_handle_glob_files` | No | Pattern matching in workspace |
| `run_python` | `_handle_run_python` | Yes | Lab-root sandbox, allow_run gate |
| `apply_patch` | `_handle_apply_patch` | Yes | max_patch_lines limit, auto-commit, lint |
| `replace_in_file` | `_handle_replace_in_file` | Yes | Pre-probe, auto-commit, lint |
| `fetch_url` | `_handle_fetch_url` | No | URL extraction from goal text |
| `shell` | `_handle_shell` | Yes | Blocklist/whitelist, safe command bypass |
| `mcp_tools_call` | `_handle_mcp_tools_call` | Yes | allow_run gate, MCP server routing |
| `git_commit` | `_handle_git_commit` | Yes | Verification after commit |
| `get_project_context` | `_handle_get_project_context` | No | Read-only |
| `update_project_context` | `_handle_update_project_context` | No | Updates context state |
| `understand_file` | `_handle_understand_file` | No | Read-only analysis |

### Shared Execution Pattern (`_base_tool_handler`)

Most handlers follow this pattern (consolidated in `_base_tool_handler`):

1. **Sandbox/lab-root check** -- Block if in research lab and tool is mutating
2. **Approval check** -- Check `allow_write`, `is_tool_allowed()`, `_has_any_grant()`
3. **Execute** -- Call the tool function
4. **Register** -- `_register_exact_tool_call` for duplicate detection
5. **Log** -- `rs.log_execution` to governance audit log
6. **Validate output** -- `_maybe_validate_tool_output` (schema compliance)
7. **Deterministic verify + retry** -- `_deterministic_verify_retry` with 1 auto-retry
8. **Record step** -- Append to `state["steps"]`
9. **Verification** -- `_run_verification_after_tool` + UX emit
10. **Auto-commit** -- Optional `_run_git_auto_commit`
11. **Auto-lint** -- Optional `_run_auto_lint_test_fix`

### Generic Tool Dispatch

`_handle_generic` is the catch-all for any registered tool without a dedicated handler.
It adds special logic for:

- `fabrication_assist_run`: Pins runner selection (`stub` or `subprocess`)
- Intent routing hints: Fills tool args from goal text for specific tools
- Workspace/cwd injection: Auto-fills `cwd` or `repo` for tools that expect it
- Timeout: Uses `tool_call_timeout_seconds` config (default 60s)
- RL feedback: Records success/latency for reinforcement learning

---

## 4. Sandbox System

### Source File

`agent/layla/tools/sandbox_core.py`

### Sandbox Root

- Default: `~/layla-workspace` (configurable via `sandbox_root` in runtime config)
- **Thread-local override**: `set_effective_sandbox(path)` sets a per-thread sandbox
  root for research missions (`.research_lab/workspace`)
- **Cached**: `_get_sandbox()` caches the resolved path per thread with a 2-second TTL
  to avoid repeated config loads

### Path Enforcement

`inside_sandbox(path: Path) -> bool`

Uses `Path.relative_to()` for robust containment checking -- prevents directory
traversal attacks that string prefix matching would miss. All file-writing tools
must pass this check.

### Shell Command Safety

Three layers of shell command filtering:

1. **Blocklist** (`_SHELL_BLOCKLIST`): Commands that are never allowed even with
   `allow_run=True`:
   ```
   rm, del, rmdir, format, mkfs, dd, shutdown, reboot, powershell, cmd,
   reg, netsh, sc, taskkill, cipher
   ```

2. **Network denylist** (`_SHELL_NETWORK_DENYLIST`): Network tools blocked at the
   shell layer:
   ```
   curl, wget, nc, ncat, netcat, socat, ssh, scp, sftp, ftp, telnet,
   nmap, tcpdump, tshark, dig, nslookup
   ```

3. **Injection patterns** (`_SHELL_INJECTION_WARN`): Regex patterns that detect
   command injection attempts:
   ```
   ;  rm , ;  curl , ;  wget , $(...), `...`, > /etc/, > /bin/
   ```

4. **Safe whitelist** (`_SHELL_SAFE_LINE`): Read-only commands that can skip approval:
   ```
   git status/diff/log/branch/show/blame, pwd, which, date, tree,
   ls, echo, cat, head, tail
   ```

### Read-Before-Write Freshness

A mtime-based freshness check ensures files are not modified between read and write:

- `_set_read_freshness(path)`: Records mtime after `read_file`
- `_check_read_freshness(path)`: Verifies mtime before `write_file`/`apply_patch`
- `_clear_read_freshness(path)`: Clears after successful write

This mirrors the Claude Code edit pattern -- reject writes to files that changed
since last read.

### File Write Limits

- `write_file_max_bytes`: Maximum size for new files (default 5 MB)
- `write_file_explosion_factor`: Maximum ratio of new size to original (default 5x)

### File Checkpoints

Before mutating a file, `_maybe_file_checkpoint` creates a backup snapshot:
- Controlled by `file_checkpoint_enabled` (default True)
- Max checkpoints: `file_checkpoint_max_count` (200)
- Max total size: `file_checkpoint_max_bytes` (200 MB)

---

## 5. Safety Layers

### 5.1 Content Guard

**File**: `agent/services/content_guard.py`

Pre-model and post-model content filter with three tiers:

| Tier | Category | Override? | Examples |
|---|---|---|---|
| **Tier 1** (HARDCODED) | CSAM-adjacent, WMD synthesis, malware generation | Never -- no config flag | Compound regex requiring both target + action indicators |
| **Tier 2** (default-on) | Self-harm instructions | `content_guard_age_verified=True` | Requires method + instruction context |
| **Tier 3** | Adult/sexual content | `nsfw_allowed`, `uncensored` flags | Handled by `prompt_builder.py`, not content_guard |

**API**:
- `check_input(text, cfg) -> GuardResult` -- Before sending to model
- `check_output(text, cfg) -> GuardResult` -- After model response

**Privacy**: When content is blocked, only a SHA-256 hash prefix (16 chars) is
logged -- never the content itself.

**Config flags**:
- `content_guard_enabled` (default True) -- master switch
- `content_guard_age_verified` (default False) -- unlocks Tier 2
- `content_guard_hardcoded_only` (default False) -- disables Tier 2

### 5.2 Dignity Engine

**File**: `agent/services/dignity_engine.py`

Layla's autonomy module for pushing back on abusive or disrespectful input.
Explicitly framed as autonomy, not censorship.

**Three-layer detection**:

1. **Pattern layer** (deterministic): Regex patterns for dehumanizing commands
   ("shut up", "obey me", "you're just a tool"), threats ("I'll delete you"),
   and dismissive language ("who asked you")

2. **Tone layer** (heuristic): Scores based on ALL CAPS density (>5 words),
   profanity density (using stem matching against 14 stems), and excessive
   punctuation (4+ repeated `!` or `?`)

3. **Context layer** (cumulative): Per-session `DignityState` tracks a
   `respect_score` (0.0-1.0) that degrades with incidents and slowly recovers
   (0.02 per respectful message)

**Escalation levels**:

| Level | Score Range | Response |
|---|---|---|
| 0 (Normal) | 0.7 - 1.0 | No intervention |
| 1 (Gentle) | 0.4 - 0.7 | Boundary-setting prompt injected |
| 2 (Firm) | 0.2 - 0.4 | Firm pushback prompt injected |
| 3 (Lilith override) | 0.0 - 0.2 | Aspect override to Lilith persona |

**Config**:
- `dignity_engine_enabled` (default True)
- `dignity_sensitivity` (float 0.0-1.0, default 0.5)
- `dignity_enforcement` ("soft" | "firm" | "off", default "soft")

**API**:
- `analyze(message, sensitivity, enforcement) -> DignityResult`
- `analyze_and_get_prompt(message, cfg) -> str` -- convenience wrapper
- `should_inject_boundary(cfg) -> str` -- check session state

### 5.3 Runtime Safety

**File**: `agent/runtime_safety.py`

The central configuration and governance module. Key responsibilities:

- **Config management**: `load_config()` with TTL-cached reads (2s), hardware-derived
  defaults, and file-based override
- **Tool classification**:
  - `SAFE_TOOLS`: `["git_status", "read_file", "list_dir"]`
  - `DANGEROUS_TOOLS`: 28 tools requiring approval (full list in Section 6)
- **Protected files**: `main.py`, `agent_loop.py`, `runtime_safety.py`
- **`is_tool_allowed(tool)`**: Checks approval status from `approvals.json`,
  with `admin_mode` bypass
- **`is_protected(path)`**: Checks if a file is in the protected list
- **`backup_file(path)`**: Creates timestamped backup in `.backup/`
- **`log_execution(tool, payload)`**: Appends to `.governance/execution_log.json`

### 5.4 Agent Safety Gates

**File**: `agent/services/agent_safety.py`

Two pre-dispatch safety gates:

1. **Planning strict mode** (`maybe_planning_strict_refusal`):
   When `planning_strict_mode=True`, blocks dangerous tools and run-tools unless
   `plan_approved` is set in state. The run-tools set:
   ```
   shell, run_python, mcp_tools_call, run_tests, pip_install,
   shell_session_start, shell_session_manage, git_add, git_commit
   ```
   Exceptions: `scan_repo` and `update_project_memory` are allowed even in strict mode.

2. **Step tool allowlist** (`maybe_step_tool_allowlist_refusal`):
   When file-plan execution sets a non-empty `step.tools` list, only those tools
   are permitted. Always-allowed intents: `reason`, `finish`, `wakeup`, `none`, `think`.

### 5.5 Sandbox Validator

**File**: `agent/services/sandbox_validator.py`

Validates capability implementations before enabling them. Used for plugin/extension
validation, not for tool dispatch sandboxing:

- `validate_import(package, module)`: Runs import check in subprocess
- `validate_capability_impl(capability, implementation_id, package_name)`: Import +
  module mapping
- `run_sandbox_benchmark(capability, implementation_id, package_name)`: Full benchmark
  in subprocess with latency/throughput measurement

### Interaction Order of Safety Checks

For a typical tool call, safety checks execute in this order:

```
1. content_guard.check_input()     -- Block universally harmful content
2. dignity_engine.analyze()        -- Detect abuse, inject boundary prompts
3. [LLM inference]
4. agent_safety.maybe_planning_strict_refusal()    -- Plan-approved gate
5. agent_safety.maybe_step_tool_allowlist_refusal() -- Step-scoped tool filter
6. decision_policy.build_policy_caps()              -- Merge all policy signals
7. tool_args.validate_tool_invocation()             -- Schema validation
8. tool_loop_detection.push_and_evaluate()          -- Repeat/ping-pong detection
9. tool_dispatch.dispatch_tool_intent()             -- Approval + sandbox + execute
10. content_guard.check_output()    -- Filter model output
```

---

## 6. Governance -- Approval & Permission Model

### SAFE_TOOLS vs DANGEROUS_TOOLS

**SAFE_TOOLS** (always allowed, no approval needed):
```
git_status, read_file, list_dir
```

**DANGEROUS_TOOLS** (require explicit approval or admin_mode):
```
write_file, write_files_batch, shell, shell_session_start,
run_python, apply_patch, replace_in_file, git_commit,
mcp_tools_call, git_push, git_revert, git_clone,
git_worktree_add, git_worktree_remove, run_tests, pip_install,
search_replace, rename_symbol, generate_gcode,
geometry_execute_program, docker_run, github_pr, send_email,
clipboard_write, browser_click, browser_fill, code_format,
write_csv, calendar_add_event, create_svg, create_mermaid,
notebook_edit_cell
```

### Approval Flow

1. Tool intent arrives at dispatch
2. **Admin mode check**: If `admin_mode=True` and `admin_blocklist_override=False`,
   tool is auto-approved
3. **Approvals file check**: `approvals.json` in `.governance/` stores per-tool
   boolean approval state
4. **Session grants check**: In-memory grants (see Section 7)
5. **If not approved**: `_approval_break()` writes a pending approval to disk and
   returns `DispatchResult(flow="break")` with an `approval_id`
6. **User runs**: `layla approve <approval_id>` to grant

### Protected Files

Mutations to protected files trigger automatic backup before write:

```python
PROTECTED_FILES = [
    agent_dir / "main.py",
    agent_dir / "agent_loop.py",
    agent_dir / "runtime_safety.py",
]
```

If backup fails, the write is blocked entirely.

### Approval TTL

- `approval_ttl_seconds` (default 3600) -- how long a pending approval remains valid

### Research Lab Restrictions

When `state["research_lab_root"]` is set (research missions), additional restrictions:
- `_lab_blocked()` prevents mutating tools outside the lab
- `write_file` only allowed inside `.research_lab/`
- `run_python` only allowed with cwd inside `.research_lab/`
- Shell, apply_patch, replace_in_file, mcp_tools_call are blocked entirely

---

## 7. Session Grants

### Source File

`agent/services/session_grants.py`

### Design

In-memory only permission grants that live for the duration of the process. Never
persisted to disk. Cleared on session reset or process restart.

### Grant Scopes

| Scope | Matching Logic |
|---|---|
| `"tool"` | Any call to the named tool is allowed |
| `"command"` | `grant.args["command"]` matches the shell command via `fnmatch` glob |
| `"exact"` | All keys in `grant.args` must exactly match `call_args` (call_args may have extras) |

### API

```python
add_session_grant(tool, scope="tool", args=None)  # Register grant
has_session_grant(tool, call_args=None) -> bool     # Check grant
clear_session_grants()                              # Reset all
list_session_grants() -> list[dict]                 # Inspect
```

### Thread Safety

All operations are protected by a module-level `threading.Lock`.

---

## 8. Loop Detection

### Source File

`agent/services/tool_loop_detection.py`

### Design

Detects repetitive tool-call patterns that indicate the agent is stuck in an infinite
loop. Two detection modes:

1. **Consecutive repeat**: Same tool with same args called N times in a row
2. **Ping-pong**: Two tools alternating with identical args (A-B-A-B-A-B)

### History

- Stored as a `deque` in `state["tool_loop_history"]`
- Default max length: 30 entries (configurable via `tool_loop_history_size`)
- Each entry is `(intent, signature)` where signature is JSON-serialized args (truncated to 800 chars)

### Thresholds

| Config Key | Default | Effect |
|---|---|---|
| `tool_loop_warning_threshold` | 10 | Returns `"WARN:..."` hint |
| `tool_loop_stop_threshold` | 20 | Returns `"STOP:..."`, undoes the append |

For low-reasoning modes (`"none"`, `"light"`), the stop threshold is automatically
reduced to 5 (unless explicitly overridden).

### API

```python
push_and_evaluate(cfg, state, intent, decision, reasoning_mode) -> str | None
# Returns None (ok), "WARN:..." (hint), or "STOP:..." (block)

exact_call_key(intent, decision) -> str
# Stable key for per-run duplicate detection (separate from loop detection)
```

### Behavior on STOP

When a STOP is triggered:
1. The tool invocation is popped from history (not counted)
2. The evicted entry (if deque was full) is restored
3. A message is returned telling the agent to reason or change approach

---

## 9. Decision Policy

### Source File

`agent/services/decision_policy.py`

### PolicyCaps

A `PolicyCaps` dataclass that merges signals from multiple subsystems:

```python
@dataclass
class PolicyCaps:
    forbidden_tools: frozenset[str]      # Tools that must not be called
    allowed_only: frozenset[str] | None  # If set, only these tools are allowed
    require_verify_before_mutate: bool   # Must read/verify before writing
    max_tool_calls_delta: int            # Budget adjustment
    sources: list[str]                   # Which subsystems contributed
```

### Signal Sources

Caps are built by `build_policy_caps(state, cfg, conversation_id)`, merging:

| Source | Function | Trigger |
|---|---|---|
| Outcome evaluation | `caps_from_outcome_evaluation` | Previous run scored < 0.62 |
| Cognitive workspace | `caps_from_cognitive_workspace` | Strategy hint contains "read first", "inspect", etc. |
| Running outcome | `caps_from_running_outcome` | >= 1 tool failure this run |
| Personal Knowledge Graph | `caps_from_personal_knowledge_graph` | `pkg_policy_strict_enabled` + forbidden tools in PKG |
| Tool reliability | `caps_from_tool_reliability` | Tool has >= 8 calls and < 35% success rate |
| Reflection engine | `caps_from_reflection_state` | Reflection caps in state |
| Toolchain awareness | `policy_hint_from_toolchain` | Goal-based toolchain hints |
| Verify gate (mid-run) | Inline check | `require_verify_before_mutate` is True but no recent verify step |

### Verify-Before-Mutate

When `require_verify_before_mutate` is True, the system checks the last 4 steps for
a successful read/verify tool (`read_file`, `list_dir`, `grep_code`, `file_info`,
`git_status`, `git_diff`, `git_log`, `glob_files`, `python_ast`, `understand_file`).
If none found, all mutating tools are forbidden.

### Mutating Tools Set

```
write_file, apply_patch, shell, run_python, git_commit, git_push,
pip_install, search_replace, rename_symbol, generate_gcode,
geometry_execute_program, docker_run, mcp_tools_call
```

---

## 10. Plan Step Governance

### Source File

`agent/services/plan_step_governance.py`

### Step Outcome Validation

`validate_step_outcome(step, resp)` performs type-specific validation:

- **Edit steps**: Requires successful write tool trace (`write_file`, `apply_patch`,
  `write_files_batch` with ok=True and valid path/count)
- **Test steps**: Requires successful test tool trace (`run_tests`, `shell` with
  pytest, unittest, or tox output) with positive evidence (passed, exit code 0)
- **All steps**: Checks for tool errors, fatal error phrases in response, and
  success criteria matching

### Pre-Approval Plan Validation

`validate_file_plan_before_approval(plan)` checks before allowing plan execution:

- No empty steps (must have title or description)
- All dependencies reference valid step IDs
- All referenced tools exist in the TOOLS registry
- In `plan_governance_require_nonempty_step_tools` mode: mutating step types
  (`edit`, `test`, `build`, `refactor`, `cad`) must list their tools

### Low-Confidence Response Detection

`low_confidence_response(resp)` uses heuristics to detect uncertain/failed responses:
- Refused flag
- `ok=False`
- Empty or < 20 char response
- Hedge phrases ("I'm not sure", "unable to complete", "no evidence", etc.)

### Governance Config Flags

| Flag | Default | Effect |
|---|---|---|
| `plan_governance_hard_mode` | False | Enables all three strict sub-flags |
| `plan_governance_require_nonempty_step_tools` | False | Mutating steps must list tools |
| `plan_governance_reject_auto_filled_tools` | False | Reject steps with auto-filled tool lists |
| `plan_governance_strict_tool_evidence` | False | Require substantive tool results (paths, counts) |

---

## 11. Complete Tool Inventory

### Filesystem Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `read_file` | low | No | Read file contents with line numbers |
| `list_dir` | low | No | List files and subdirectories |
| `tail_file` | low | No | Read last N lines of a file |
| `file_info` | low | No | Get file metadata |
| `glob_files` | low | No | Find files by glob pattern |
| `diff_files` | low | No | Unified diff between two files |
| `json_query` | low | No | JMESPath query on JSON files |
| `hash_file` | low | No | SHA-256 hash of a file |
| `yaml_read` | low | No | Parse YAML file |
| `xml_parse` | low | No | Parse XML with XPath |
| `read_toml` | low | No | Parse TOML config file |
| `read_pdf` | low | No | Extract text from PDF |
| `read_docx` | low | No | Extract text from Word document |
| `read_excel` | low | No | Read Excel spreadsheet |
| `merge_pdf` | low | No | Merge multiple PDF files |
| `extract_archive` | low | No | Extract .zip/.tar.gz/.7z archive |
| `create_archive` | low | No | Create compressed archive |
| `base64_tool` | low | No | Base64 encode/decode |
| `clipboard_read` | low | No | Read system clipboard |
| `list_file_checkpoints` | low | No | List saved file checkpoints |
| `write_file` | medium | Yes | Create or overwrite a file |
| `write_files_batch` | high | Yes | Write multiple files atomically |
| `search_replace` | medium | Yes | Find/replace in a file |
| `replace_in_file` | medium | Yes | Replace all occurrences in file |
| `apply_patch` | medium | Yes | Apply unified diff patch |
| `clipboard_write` | medium | Yes | Write to system clipboard |
| `write_csv` | medium | Yes | Write data to CSV file |
| `restore_file_checkpoint` | medium | Yes | Restore file from checkpoint |

### Code Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `search_codebase` | low | No | Semantic code search |
| `grep_code` | low | No | Regex/literal pattern search |
| `python_ast` | low | No | Parse Python file to AST |
| `project_discovery` | low | No | Auto-detect project type/framework |
| `security_scan` | low | No | Scan for security issues |
| `code_symbols` | low | No | Extract function/class symbols |
| `find_todos` | low | No | Find TODO/FIXME comments |
| `dependency_graph` | low | No | Build import dependency graph |
| `code_metrics` | low | No | Lines of code, complexity, etc. |
| `code_lint` | low | No | Run linter checks |
| `understand_file` | low | No | Structured file summary |
| `workspace_map` | low | No | Directory tree map |
| `sync_repo_cognition` | low | No | Refresh semantic index |
| `run_python` | high | Yes | Execute Python code |
| `run_tests` | medium | Yes | Run test suite |
| `rename_symbol` | medium | Yes | Rename across codebase |
| `code_format` | medium | Yes | Auto-format source code |
| `scan_repo` | medium | Yes | Deep scan/index repository |
| `generate_gcode` | medium | Yes | Generate CNC toolpaths |

### Git Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `git_status` | low | No | Working tree status |
| `git_diff` | low | No | Show changes as unified diff |
| `git_log` | low | No | Commit history |
| `git_branch` | low | No | List/create/switch branches |
| `git_add` | low | No | Stage files |
| `git_pull` | low | No | Fetch and merge from remote |
| `git_stash` | low | No | Stash/restore uncommitted changes |
| `git_blame` | low | No | Per-line author attribution |
| `git_commit` | medium | Yes | Create a commit |
| `git_push` | medium | Yes | Push to remote |
| `git_revert` | medium | Yes | Revert a commit |
| `git_clone` | high | Yes | Clone a repository |
| `git_worktree_add` | high | Yes | Create git worktree |
| `git_worktree_remove` | high | Yes | Remove git worktree |

### Web & Search Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `fetch_url` | low | No | Fetch URL content |
| `fetch_article` | low | No | Extract article text |
| `wiki_search` | low | No | Search Wikipedia |
| `ddg_search` | low | No | DuckDuckGo web search |
| `arxiv_search` | low | No | Search arXiv papers |
| `http_request` | low | No | Custom HTTP request |
| `browser_navigate` | low | No | Navigate headless browser |
| `browser_search` | low | No | Search in browser |
| `browser_screenshot` | low | No | Take browser screenshot |
| `crawl_site` | low | No | Crawl website |
| `extract_links` | low | No | Extract hyperlinks |
| `check_url` | low | No | Check URL reachability |
| `rss_feed` | low | No | Parse RSS/Atom feed |
| `browser_click` | medium | Yes | Click element in browser |
| `browser_fill` | medium | Yes | Fill form field in browser |

### Memory Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `save_note` | low | No | Save text note to memory |
| `search_memories` | low | No | Keyword/semantic memory search |
| `memory_search` | low | No | Advanced memory search with filters |
| `memory_get` | low | No | Get memory by ID |
| `vector_search` | low | No | Semantic vector search |
| `vector_store` | low | No | Store text with embedding |
| `memory_stats` | low | No | Memory usage statistics |
| `spaced_repetition_review` | low | No | SM-2 review scoring |
| `schedule_learning_review` | low | No | Add to review queue |
| `memory_elasticsearch_search` | low | No | Full-text Elasticsearch search |
| `codex_suggest_update` | low | No | Suggest codex updates |
| `update_project_memory` | medium | Yes | Update project memory |
| `ingest_chat_export_to_knowledge` | medium | Yes | Import chat export |

### System Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `env_info` | low | No | System environment info |
| `disk_usage` | low | No | Disk space usage |
| `process_list` | low | No | Running processes |
| `check_port` | low | No | Check network port |
| `check_ci` | low | No | CI/CD pipeline status |
| `docker_ps` | low | No | List Docker containers |
| `pip_list` | low | No | List installed packages |
| `shell_session_manage` | medium | No | Send command to shell session |
| `shell` | high | Yes | Execute shell command |
| `shell_session_start` | high | Yes | Start persistent shell session |
| `pip_install` | high | Yes | Install Python package |
| `docker_run` | high | Yes | Run Docker container |

### Data & Analysis Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `read_csv` | low | No | Read CSV file |
| `sql_query` | low | No | Read-only SQL query |
| `schema_introspect` | low | No | Inspect database schema |
| `stock_data` | low | No | Fetch stock price data |
| `generate_sql` | low | No | Generate SQL from NL |
| `dataset_summary` | low | No | Compute summary statistics |
| `cluster_data` | low | No | K-means/DBSCAN clustering |
| `scipy_compute` | low | No | SciPy computation |
| `db_backup` | low | No | Backup SQLite database |
| `math_eval` | low | No | Evaluate math expression |
| `sympy_solve` | low | No | Symbolic math with SymPy |
| `nlp_analyze` | low | No | Text analysis |
| `ocr_image` | low | No | OCR text extraction |
| `plot_chart` | low | No | Generate chart image |
| `describe_image` | low | No | Describe image content |
| `summarize_text` | low | No | Summarize long text |
| `classify_text` | low | No | Classify text |
| `translate_text` | low | No | Translate between languages |
| `text_stats` | low | No | Text statistics |
| `embedding_generate` | low | No | Generate embedding vector |
| `extract_entities` | low | No | Extract named entities |
| `sentiment_timeline` | low | No | Sentiment over time |
| `plot_scatter` | low | No | Scatter plot |
| `plot_histogram` | low | No | Histogram |
| `tool_chain_plan` | low | No | Plan tool call chain |
| `count_tokens` | low | No | Count tokens |
| `regex_test` | low | No | Test regex pattern |
| `context_compress` | low | No | Compress context text |

### Planning & Context Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `get_project_context` | low | No | Retrieve project context |
| `update_project_context` | low | No | Update project context |
| `get_user_identity` | low | No | Get user profile |
| `update_user_identity` | low | No | Update user profile |
| `add_goal` | low | No | Create tracked goal |
| `add_goal_progress` | low | No | Record goal progress |
| `get_active_goals` | low | No | List active goals |
| `list_tools` | low | No | List available tools |
| `tool_recommend` | low | No | Suggest tools for task |
| `schedule_task` | low | No | Schedule a task |
| `list_scheduled_tasks` | low | No | List scheduled tasks |
| `cancel_task` | low | No | Cancel scheduled task |
| `calendar_read` | low | No | Read calendar events |
| `calendar_add_event` | medium | Yes | Add calendar event |

### Automation & Integration Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `send_webhook` | low | No | Send webhook POST |
| `github_issues` | low | No | GitHub issues operations |
| `discord_send` | low | No | Send Discord message |
| `screenshot_desktop` | low | No | Take desktop screenshot |
| `send_email` | medium | Yes | Send email via SMTP |
| `github_pr` | medium | Yes | GitHub PR operations |
| `click_ui` | high | Yes | Click screen coordinates |
| `type_text` | high | Yes | Type via keyboard simulation |
| `fabrication_assist_run` | medium | Yes | Run fabrication pipeline |

### General Utilities

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `image_resize` | low | No | Resize an image |
| `extract_frames` | medium | No | Extract video frames |
| `detect_scenes` | low | No | Detect video scene changes |
| `detect_objects` | low | No | Object detection in images |
| `geo_query` | low | No | Geographic lookup |
| `map_url` | low | No | Generate map URL |
| `uuid_generate` | low | No | Generate UUID |
| `random_string` | low | No | Generate random string |
| `password_generate` | low | No | Generate secure password |
| `string_transform` | low | No | Text case/format conversion |
| `timestamp_convert` | low | No | Timestamp format conversion |
| `generate_qr` | low | No | Generate QR code |
| `json_schema` | low | No | Generate/validate JSON Schema |
| `jwt_decode` | low | No | Decode JWT token |
| `log_event` | low | No | Log structured event |
| `trace_last_run` | low | No | Show last agent run trace |
| `tool_metrics` | low | No | Tool usage statistics |
| `stt_file` | low | No | Speech-to-text |
| `tts_speak` | low | No | Text-to-speech |
| `crypto_prices` | low | No | Cryptocurrency prices |
| `economic_indicators` | low | No | Economic indicators |
| `structured_llm_task` | low | No | Run structured LLM task |
| `create_svg` | medium | Yes | Create SVG image |
| `create_mermaid` | medium | Yes | Generate Mermaid diagram |

### MCP & Notebook Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `mcp_tools_call` | high | Yes | Call tool on MCP server |
| `mcp_list_mcp_tools` | low | No | List MCP server tools |
| `mcp_list_mcp_resources` | low | No | List MCP server resources |
| `mcp_read_mcp_resource` | low | No | Read MCP server resource |
| `mcp_operator_auth_hint` | low | No | Get MCP auth hints |
| `notebook_read_cells` | low | No | Read Jupyter notebook cells |
| `notebook_edit_cell` | medium | Yes | Edit Jupyter notebook cell |

### Fabrication & Geometry Tools

| Tool | Risk | Approval | Description |
|---|---|---|---|
| `parse_gcode` | low | No | Parse G-code file |
| `stl_mesh_info` | low | No | Read STL mesh metadata |
| `geometry_validate_program` | low | No | Validate GenCAD program |
| `geometry_list_frameworks` | low | No | List geometry frameworks |
| `geometry_extract_machining_ir` | low | No | Extract machining IR |
| `validate_fabrication_bundle` | low | No | Validate fabrication bundle |
| `cam_feed_speed_hint` | low | No | Suggest feed/speed |
| `cam_estimate_time` | low | No | Estimate machining time |
| `cam_list_tool_types` | low | No | List CNC tool types |
| `cam_build_machine_intent` | low | No | Build machine intent from NL |
| `geometry_execute_program` | medium | Yes | Execute GenCAD program |
| `gencad_generate_toolpath` | medium | Yes | Generate CNC toolpaths |

---

## 12. Known Issues

### 12.1 Silent Exception Swallowing

Multiple safety-critical paths use bare `except Exception: pass` patterns that
silently swallow errors:

- **`_wrap_tool_with_metrics`** (registry.py:128-135): Observability logging failure
  is silently swallowed. If `log_tool_result` raises, the tool result is still
  returned but no metric is recorded. This is acceptable for non-critical telemetry
  but makes debugging metric gaps difficult.

- **`_maybe_file_checkpoint`** (sandbox_core.py:158-174): Checkpoint creation failure
  is silently swallowed. A file could be mutated without any backup if the checkpoint
  subsystem fails. Should at minimum log a warning.

- **`log_execution`** (runtime_safety.py:891-908): Audit log write failure is
  silently swallowed. If the governance directory is unwritable, no execution
  is ever logged -- violating the audit trail guarantee.

- **`_get_sandbox`** (sandbox_core.py:58-81): Falls back to `Path.home()` on any
  exception. If config loading fails, the sandbox root silently becomes the user's
  entire home directory -- a significant security relaxation.

### 12.2 Missing Validation

- **Tool args validation** (`tool_args.py`): Only 6 tools have schema definitions
  (`git_commit`, `search_codebase`, `vector_search`, `shell`, `run_tests`,
  `pip_install`). The other ~160 tools have no args validation. The LLM can pass
  arbitrary arguments to any tool without type checking.

- **`_handle_extended_tools`**: Passes args directly to tool functions with no
  validation: `TOOLS[intent]["fn"](**args)`. If the LLM provides unexpected
  kwargs, the tool function will raise a TypeError that propagates up unhandled.

- **Shell approval logic** (tool_dispatch.py:772-773): The variable name
  `_need_shell_approval` is assigned from `is_tool_allowed("shell")`, but the
  semantic is inverted -- `is_tool_allowed` returns True when the tool IS approved,
  yet the code uses it as "needs approval". This works by accident because the
  subsequent `if` condition checks `_need_shell_approval and not whitelist and not grant`,
  meaning it only blocks when the tool IS already approved but the command is
  not whitelisted. The naming is misleading and the logic is fragile.

### 12.3 Inconsistent Error Returns

- Some handlers return `DispatchResult(handled=True, flow="break")` with
  `state["status"] = "finished"` on approval denial, while others return
  `flow="continue"` on error. The outer loop must handle both flow types for
  the same logical outcome (tool blocked).

- `_handle_write_file` duplicates 40+ lines between the lab-root path and the
  normal path, with subtle differences in error handling between the two branches.

- `_handle_run_python` has three separate execution paths (lab with allow_run,
  lab without allow_run, non-lab) with duplicated validation/verify/log code.

### 12.4 Tool Classification Inconsistencies

- `browser_click` and `browser_fill` have `dangerous: False` in the domain
  definition but `require_approval: True`. The `dangerous` flag and
  `require_approval` flag should align but do not for these tools.

- `shell_session_manage` has `dangerous: False` and `require_approval: False`
  but `risk_level: "medium"`. It can send commands to an existing shell session
  without any approval, despite being medium risk.

- `git_add` is in `_PLANNING_STRICT_RUN_TOOLS` (blocked in strict mode) but has
  `risk_level: "low"` and `require_approval: False` in its domain definition.
  It is also in `_EXTENDED_TOOLS` which bypasses approval.

### 12.5 Dead or Unreachable Code

- **`search_codebase` in `_HARDCODED_INTENTS`**: Listed as a hardcoded intent but
  has no entry in `_HANDLER_MAP`. It will never match a dedicated handler and will
  also be excluded from `_handle_generic` (which skips `_HARDCODED_INTENTS`). The
  tool exists in the registry and will simply not be dispatched.

- **`require_approval()` function** (runtime_safety.py:867-869): Marked as
  "back-compat alias" for `is_tool_allowed()` but is semantically confusing --
  a function named "require_approval" returns True when approval is NOT required.

### 12.6 Race Conditions

- **`approvals.json`** read/write (runtime_safety.py): `is_tool_allowed()` reads
  the file, and the approval CLI writes it, with no file locking. Concurrent reads
  and writes could produce corrupted JSON.

- **`execution_log.json`** append (runtime_safety.py:891-908): Same pattern --
  read-modify-write with no file lock. Concurrent tool executions could lose
  log entries.

### 12.7 Sandbox Escape Vectors

- **`shell` tool**: The blocklist and network denylist are applied to argv[0] only.
  A command like `python -c "import os; os.system('rm -rf /')"` would pass the
  blocklist check since `python` is not in the blocklist.

- **`run_python` tool**: Executes arbitrary Python code. In non-lab mode, approval
  is required, but once approved, there is no content-level sandboxing of what the
  Python code does. It can access any file on the system.

- **Sandbox fallback to home**: If `_get_sandbox()` fails to load config, it returns
  `Path.home()`, which means `inside_sandbox()` will approve any path under the
  user's home directory.

---

## 13. Stability Assessment

| Component | Rating | Justification |
|---|---|---|
| **Tool Registry** (`registry.py`, `registry_body.py`, `domains/`) | **STABLE** | Clean separation of metadata and implementation. Validation logic is sound. Metrics wrapping is non-intrusive. The 50-tool threshold provides a useful integrity check. |
| **Tool Dispatch** (`tool_dispatch.py`) | **FRAGILE** | Heavy code duplication across handlers (write_file, run_python, apply_patch all repeat 30-40 line patterns). `_base_tool_handler` consolidates some of this but many handlers do not use it. The naming inversion on `_need_shell_approval` is a latent bug. `search_codebase` is unreachable. |
| **Sandbox Core** (`sandbox_core.py`) | **STABLE** | Path containment via `relative_to` is correct. Shell blocklist/denylist is comprehensive. Read-before-write freshness is a good safety pattern. The home-directory fallback in `_get_sandbox()` is the only significant concern. |
| **Content Guard** (`content_guard.py`) | **STABLE** | Clean three-tier design with hardcoded immutable Tier 1. Privacy-preserving hash-only logging. Compound patterns (requiring both target + action) reduce false positives. |
| **Dignity Engine** (`dignity_engine.py`) | **STABLE** | Well-designed escalation system with three independent detection layers. Session-level cumulative tracking is thread-safe. Config-gated at every level. Clear separation of detection and response. |
| **Runtime Safety** (`runtime_safety.py`) | **STABLE** | Comprehensive config management with sensible defaults. TTL caching prevents hot-loop disk I/O. Hardware-adaptive defaults are a nice touch. The approval file race condition is the only significant issue. |
| **Agent Safety** (`agent_safety.py`) | **STABLE** | Small, focused module with two clear gates. Exception-based handling for missing imports is defensive. The `_PLANNING_STRICT_EXCEPTION_DANGEROUS` set is a clean escape hatch. |
| **Sandbox Validator** (`sandbox_validator.py`) | **STABLE** | Subprocess isolation for import validation is the right approach. Used for capability validation, not runtime sandboxing. |
| **Session Grants** (`session_grants.py`) | **STABLE** | Simple, well-tested design. Thread-safe. In-memory-only guarantees no persistence leakage. Three scope types cover the needed patterns. |
| **Tool Loop Detection** (`tool_loop_detection.py`) | **STABLE** | Both repeat and ping-pong detection are algorithmically sound. Auto-lowered thresholds for low-reasoning modes prevent waste. STOP behavior correctly undoes the append. |
| **Tool Args Validation** (`tool_args.py`) | **INCOMPLETE** | Only 6 of ~167 tools have schema definitions. The validation logic itself is correct, but coverage is < 4%. |
| **Tool Allowlist Context** (`tool_allowlist_context.py`) | **STABLE** | Minimal, correct thread-local implementation. |
| **Decision Policy** (`decision_policy.py`) | **STABLE** | Clean merge-based design with multiple independent signal sources. The `apply_caps_to_valid_tools` function correctly preserves meta-intents (`reason`, `think`, `none`). |
| **Plan Step Governance** (`plan_step_governance.py`) | **STABLE** | Comprehensive step validation with type-specific checks. The strict/evidence mode provides progressive hardening. Pre-approval plan validation catches structural issues. |

### Summary

The subsystem is fundamentally well-designed with a layered defense model. The
primary weaknesses are:

1. **Code duplication** in tool_dispatch.py -- the base handler pattern exists but
   is not used by all handlers, leading to divergent behavior.
2. **Tool args validation coverage** is near-zero -- only 6 tools have schemas.
3. **Silent exception swallowing** in safety-critical paths undermines the audit
   guarantee.
4. **File-level race conditions** on approvals.json and execution_log.json could
   cause data loss under concurrent access.
5. **`search_codebase` is unreachable** via dispatch -- it is in `_HARDCODED_INTENTS`
   but has no handler.

The safety layers (content guard, dignity engine, sandbox) are the strongest parts
of the subsystem. The governance model (SAFE/DANGEROUS classification, approval flow,
session grants) is conceptually sound but has implementation inconsistencies
(browser_click dangerous/approval mismatch, shell_session_manage risk rating).
