---
priority: core
domain: devops
aspects: Morrigan, Nyx
difficulty: intermediate
related: observability-operations.md, testing-strategy.md, security-engineering-basics.md
---

# DevOps CI/CD patterns

## Goals

- Keep `main` releasable.
- Make failures cheap and fast (fail early; narrow blame surface).
- Ship safely: reproducible builds, auditable changes, and rollback paths.

## Pipeline shape (recommended baseline)

### 1) Validate fast (PR)

- **Lint + typecheck** first (seconds to 1–2 minutes).
- **Unit tests** next (parallel; keep under ~5 minutes if possible).
- **Build** next (artifact produced in CI, not on developer machines).
- **Security checks**: dependency audit / SCA, secret scanning.

### 2) Validate deeper (merge / nightly)

- **Integration tests** (database + external service mocks).
- **E2E UI tests** (Playwright) when relevant; isolate flakiness.
- **Performance / regression** checks only when you have a baseline and a reason.

### 3) Release (tag)

- Tag triggers **build once** and publish artifacts.
- Run a **release gate** (smoke test + provenance metadata).
- Produce a **release note** (changelog fragment, upgrade notes, breaking changes).

## Quality gates

- **Branch protection**: required checks + no direct pushes to protected branches.
- **Test determinism**: mark flaky tests and quarantine; do not let flakes become “normal.”
- **Coverage**: prefer “coverage on changed lines” over global thresholds.
- **Dangerous actions**: require approvals (e.g., deployments, migrations, irreversible ops).

## Versioning and releases

- Prefer **SemVer**: `MAJOR.MINOR.PATCH`.
- Use **conventional commits** if you want automated release notes.
- Keep release notes structured:
  - Summary
  - Notable changes
  - Breaking changes
  - Migration steps (if any)

## Rollbacks

- Always define rollback strategy before shipping:
  - **Config rollback** (feature flags) is fastest.
  - **Artifact rollback** (previous build) is second.
  - **Data rollback** is hardest; avoid needing it.

## Observability for the pipeline itself

- Track CI duration, flaky rate, cache hit rate, and failure taxonomy.
- If you can’t measure it, you can’t improve it.

---
priority: core
domain: devops
aspects: morrigan, nyx
difficulty: intermediate
related: testing-strategy.md, observability-operations.md, git-workflow-practices.md
---

## CI/CD pipeline patterns (ship-ready defaults)

### Goals
- **Fast feedback**: keep the “PR green” loop under ~10 minutes when possible.
- **Trustworthy gates**: tests that run on merge must be deterministic and meaningful.
- **Safe deploys**: prefer incremental rollouts with quick rollback.

### A solid baseline pipeline
- **Pre-commit / local** (developer machine): formatting, linting, unit tests for touched modules.
- **PR checks**:
  - **Static**: type/lint, dependency audit (at least lockfile diff review), license scan if relevant.
  - **Unit tests**: fast, isolated, no network.
  - **Integration**: only for services that changed; use containers or local fixtures.
  - **E2E**: run on schedule or for release branches; don’t gate every PR unless stable and fast.
- **Main branch**:
  - run full suite (or full suite for impacted modules via test selection)
  - build artifacts (wheels, containers)
  - publish + tag + changelog generation

### Test gate discipline
- **Fail fast**: order checks by speed and likelihood of failure.
- **No flaky tests**: quarantine quickly (label + track), don’t normalize “rerun until green.”
- **Hermetic tests**: pin seeds, freeze time where needed, isolate filesystem.

### Versioning + releases
- **Semantic versioning** if you publish to others; otherwise use date-based tags plus a changelog.
- **Release artifacts** should be reproducible from a tag.
- **Changelog entries** should reflect operator-facing value + safety changes.

### Rollback strategy
- Prefer **immutable deploys** (build once, deploy the same artifact).
- Have a **one-command rollback** path to a previous known-good version.
- For migrations, use **forward-compatible** schema changes when possible.

