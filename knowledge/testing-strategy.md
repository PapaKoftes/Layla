---
priority: core
domain: engineering
aspects: Morrigan, Nyx
difficulty: beginner
related: devops-cicd-patterns.md, observability-operations.md
---

# Testing strategy

## Test pyramid (practical version)

- **Unit tests**: fast, deterministic, local. Most tests should live here.
- **Integration tests**: verify boundaries (DB, filesystem, external API contracts).
- **E2E tests**: verify one or two golden paths; keep few and stable.

The point is not “more tests.” The point is **cheap confidence**.

## What to test

- **Core logic**: pure functions, parsing, ranking, state transitions.
- **Safety invariants**: approval gates, sandbox boundaries, refusal policy.
- **Critical I/O**: database migrations, config load/save, file operations.

## What not to test (or test sparingly)

- Visual polish (unless it breaks the app).
- Third-party library behavior (wrap it; test your wrapper).
- Flaky browser paths without determinism.

## Flaky test discipline

- If it flakes, it stops being a test and becomes noise.
- Quarantine or skip with a clear reason and follow-up plan.
- Prefer determinism: fixed seeds, controlled time, stable fixtures.

## Boundaries and mocks

- Mock external services at the boundary, not everywhere.
- Use “contract tests” for stable API shapes.
- Prefer small fixtures over large recordings.

## Regression tests

- Every bugfix should get a test that fails before the fix and passes after.
- Keep regression tests minimal and specific.

---
priority: core
domain: engineering
aspects: morrigan, nyx
difficulty: beginner
related: devops-cicd-patterns.md, api-design-patterns.md
---

## Testing strategy (unit → integration → e2e)

### Core rules
- Tests must be **deterministic**: no network, no real clocks, no shared mutable state.
- Prefer **small tests** that isolate behavior and fail with a clear reason.
- When bugs happen, add a **regression test** that fails before the fix and passes after.

### Test pyramid (practical)
- **Unit tests**: pure functions, small modules, validation logic, parsing.
- **Integration tests**: filesystem + DB + HTTP routes (still local), service wiring.
- **E2E tests**: UI automation and multi-service flows; keep few, keep stable.

### Mocking guidelines
- Mock **boundaries** (HTTP, filesystem, subprocess), not internal logic.
- If mocking makes tests unreadable, consider refactoring the code boundary.

### Flaky test discipline
- Quarantine quickly, don’t ignore.
- Add labels/markers (e.g. `slow`, `e2e_ui`).
- Capture failure context: logs, seed, inputs, snapshots.

