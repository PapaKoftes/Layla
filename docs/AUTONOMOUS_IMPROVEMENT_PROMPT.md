# Autonomous Self-Improvement Prompt

You are working inside the Layla AI agent codebase. Layla is a local-first, self-hosted intelligence platform.

**Your task:** Improve Layla's codebase autonomously within safe boundaries.

## Prerequisites

1. Read `docs/AI_ONBOARDING.md` for architecture and integration points.
2. Read `AGENTS.md` for hard rules (never break approval gate, never commit runtime_config.json, etc.).
3. Run tests before and after: `cd agent && pytest tests/ -x -q`.

## Safe improvement loop

1. **Analyze** — Use `project_discovery` tool or `workspace_map` to understand the repo. Identify weak components: flaky tests, duplicated logic, missing error handling, outdated docs.
2. **Propose** — For each improvement, output a structured proposal: `{file, change, rationale, risk}`. Do NOT implement yet.
3. **Implement** — Only after user approval (or when change is read-only/docs), apply the change.
4. **Verify** — Run tests. If any fail, revert or fix before proceeding.
5. **Document** — Update ARCHITECTURE.md, IMPLEMENTATION_STATUS.md, or RUNBOOKS.md if the change affects them.

## Boundaries

- **Never** modify `runtime_config.json`, `layla.db`, or `knowledge/` without explicit user request.
- **Never** bypass the approval flow for write_file, apply_patch, shell, run_python.
- **Never** add telemetry or external API calls that leak user data.
- **Prefer** small, incremental changes. One logical change per session when possible.

## Suggested improvement targets (priority order)

1. **Tests** — Add or fix tests for untested modules (hardware_detect, model_manager, skills).
2. **Error handling** — Wrap external calls (HuggingFace, nvidia-smi) in try/except with fallbacks.
3. **Documentation** — Keep AI_ONBOARDING.md, IMPLEMENTATION_STATUS.md, and RUNBOOKS.md accurate.
4. **Performance** — Profile hot paths (retrieval, config load); optimize only when measured.
5. **Refactoring** — Extract duplicated hardware/model logic into shared services.

## Output format

When proposing changes, use:

```
PROPOSAL:
- File: path/to/file.py
- Change: one-line description
- Rationale: why this improves Layla
- Risk: low | medium | high
```

When implementing, confirm: "Implemented: [summary]. Tests: [pass/fail]. Docs updated: [yes/no]."
