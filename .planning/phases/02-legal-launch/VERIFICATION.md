# Phase 2 Verification: Legal & launch safety

**Status:** ✅ COMPLETE · **Date:** 2026-06-29 · **Requirement:** REQ-02

Executed directly (stdlib-only, no 3.12 runtime needed).

## Success criteria → evidence

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | No AGPL dependency bundled under the proprietary license | ✅ (prior) | PyMuPDF removed; `pypdf` (BSD-3) fallback. |
| 2 | Default launch does not run `uvicorn --reload` | ✅ (prior) | `LAYLA_RELOAD` defaults off in `serve.py`. |
| 3 | `THIRD_PARTY`/`NOTICE` from a license scan **+ CI fails on a new copyleft dep** | ✅ | `scripts/check_copyleft.py`, `THIRD_PARTY.md`, `ci.yml` "License compliance" step. |

## What shipped
- **`scripts/check_copyleft.py`** — stdlib (`importlib.metadata`) scan of installed
  distribution metadata; exits non-zero on a strong-copyleft (AGPL/GPL/SSPL) package.
  Reasons over **structured** SPDX `License-Expression` + trove `License ::` classifiers,
  not the free-text body, to avoid false positives. Escape hatches: GPL-with-linking-
  exception (PyInstaller), dual-license-with-permissive-option (Apache-OR-GPL), weak
  copyleft (LGPL/MPL), and an `ALLOW` set.
- **`THIRD_PARTY.md`** — policy table, enforcement pointer, the one known weak-copyleft
  dep (python-zeroconf, LGPL-2.1), and a per-extra direct-dependency accounting.
- **`.github/workflows/ci.yml`** — "License compliance — no strong-copyleft deps (REQ-02)"
  step in the `test` job (runs against the real installed dependency tree, 3.11 + 3.12).

## Verification performed
- Ran the guard against the live env: correctly cleared **scipy** (BSD + bundled GPL
  notice text), **pyinstaller** (GPLv2 + linking exception), **pyinstaller-hooks-contrib**
  (Apache-OR-GPLv2 dual) and flagged only **PyMuPDF** — a *stale local install* not in
  `pyproject.toml`, so CI's clean install is green.
- `agent/tests/test_check_copyleft.py` — **11 unit tests** over synthetic metadata pin
  every verdict (AGPL/GPL/SSPL block; linking-exception/dual/LGPL/MIT allow; the
  LGPLv2 ⊃ "gplv2" substring trap). All pass; ruff clean.

## Notes
- The guard, not the hand-maintained `THIRD_PARTY.md` table, is the source of truth — it
  reads real installed metadata, so it can't drift from what actually ships.
- A genuine future false positive is cleared by adding the package name to `ALLOW` with a
  justifying comment.
