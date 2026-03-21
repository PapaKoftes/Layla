# Module Second Sweep — Template

Use this skeleton when adding a new subsystem or refreshing an existing one. Pair with a row in [`MODULE_SWEEP_STATUS.md`](MODULE_SWEEP_STATUS.md).

**Filename:** `docs/<AREA>_MODULE_SECOND_SWEEP.md`

---

## Metadata

- **Area:** (e.g. `agent/layla/geometry/`)
- **Status:** Draft | In progress | Done
- **Owner / date:** (optional)

## 1. Scope and entry points

- Primary modules / files
- Public API (functions, tools, routes)
- What is explicitly out of scope

## 2. Data flow

- Request or call chain (1–3 sentences or a short diagram reference to [`ARCHITECTURE.md`](../ARCHITECTURE.md))
- Config keys read (`runtime_safety.load_config()`)

## 3. Safety and invariants

- Sandbox / approval / path rules
- Secrets, URLs, subprocesses
- Failure modes that must not become silent success

## 4. Failure modes and logging

- Expected errors vs bugs
- Logger usage (`layla` INFO vs DEBUG)
- Observability hooks (`/health`, metrics)

## 5. Tests and verification

- Tests that cover the above (`agent/tests/...`)
- How to run: `cd agent && pytest tests/... -q`
- Optional deps / CI skips (`pytest.importorskip`)

## 6. Open risks / follow-ups

- Tech debt
- Future refactors (do not block shipping)

---

**After publishing:** Update [`MODULE_SWEEP_STATUS.md`](MODULE_SWEEP_STATUS.md), [`docs/IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) if North Star mapping changes, and [`CHANGELOG.md`](../CHANGELOG.md) if user-visible.
