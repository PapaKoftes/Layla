# docs/system — ground-truth technical reference

This directory holds **code-derived, factual** documentation for the Layla runtime: routes, config keys with defaults, execution paths, and invariants as implemented.

## Precedence (non-negotiable)

| Layer | Role |
|-------|------|
| **`docs/system/*.md`** | **Ground truth** — behavior and structure as reflected in `agent/` source. If narrative docs disagree, **this directory wins**. |
| **[`PROJECT_BRAIN.md`](../../PROJECT_BRAIN.md)** | **Entry point + workflow** — where to start, read order, pinned high-level facts, links into depth. |
| **Other docs** (`docs/*.md`, [`ARCHITECTURE.md`](../../ARCHITECTURE.md), [`CONFIG_REFERENCE.md`](../CONFIG_REFERENCE.md), etc.) | **Narrative / human summaries**, audits, roadmap, onboarding — useful context but may lag code. |
| **[`docs/MODULE_SWEEP_STATUS.md`](../MODULE_SWEEP_STATUS.md)** and **`docs/*_MODULE_SECOND_SWEEP.md`** | **Scoped subsystem exploration** — deep dives per area; keep using these for focused changes. **Do not replace** with `docs/system` alone. |

## When to read what

- Need **exact** route list, config default, or Tier-0 prefetch order → **`docs/system`**.
- Need **how we work** in-repo (small steps, sweeps) → **`PROJECT_BRAIN.md`** + **`AGENTS.md`**.
- Need **subsystem internals** for one module cluster → **one** module sweep from **`MODULE_SWEEP_STATUS`**.

## Files in this directory

| File | Contents |
|------|----------|
| [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md) | App entry, router mounting, two meanings of “autonomous”, request spine |
| [`EXECUTION_SYSTEM.md`](EXECUTION_SYSTEM.md) | Tool execution path, approvals wiring, runtime_safety hooks |
| [`AUTONOMOUS_SYSTEM.md`](AUTONOMOUS_SYSTEM.md) | Tier-0 `/autonomous/run`: value gate, prefetch chain, planner |
| [`MEMORY_SYSTEM.md`](MEMORY_SYSTEM.md) | SQLite, file-backed reuse/wiki, Chroma collections |
| [`TOOL_SYSTEM.md`](TOOL_SYSTEM.md) | Registry assembly, SAFE/DANGEROUS tools, validation threshold |
| [`UI_SYSTEM.md`](UI_SYSTEM.md) | Static UI paths, primary API calls from browser |
| [`CONFIG_SYSTEM.md`](CONFIG_SYSTEM.md) | `runtime_safety.load_config`, merge order, notable absent defaults |
| [`ROUTES.md`](ROUTES.md) | FastAPI route inventory |
| [`CURRENT_LIMITATIONS.md`](CURRENT_LIMITATIONS.md) | Known gaps, remote allowlist quirks, doc/code drift risks |
| [`SYSTEM_INVARIANTS.md`](SYSTEM_INVARIANTS.md) | Rules enforced by code paths cited |
