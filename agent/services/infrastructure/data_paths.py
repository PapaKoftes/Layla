"""One place to resolve Layla's per-user data directory.

The recurring defect this exists to end: a module writes `Path.home() / ".layla" / "thing.db"` as a
module-level constant. Two consequences, every time.

  1. It ignores ``LAYLA_DATA_DIR``, so an installed or multi-profile deployment writes to the invoking
     user's home instead of the configured data dir.
  2. Because it is evaluated at IMPORT, the value is frozen before any test fixture can redirect it —
     so the test suite writes to the operator's real files. `skill_registry` reached the point of
     running a committed UPDATE against the operator's live database this way.

Both are solved by resolving PER CALL and deriving any directory from the resolved path (never a
separate `_DB_DIR` constant, which is what let `tunnel_audit` keep mkdir'ing the real `~/.layla`
while every test dutifully patched its `_DB_PATH`).

Stdlib-only and dependency-free on purpose: it is imported from `layla/`, `services/` and
`routers/`, and anything heavier here would be an import cycle waiting to happen.
"""
from __future__ import annotations

import os
from pathlib import Path


def layla_data_dir() -> Path:
    """`<LAYLA_DATA_DIR or ~>/.layla` — resolved per call, never cached at import."""
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    root = Path(raw).expanduser().resolve() if raw else Path.home()
    return root / ".layla"


def layla_data_file(*parts: str) -> Path:
    """A file or directory under the data dir, e.g. ``layla_data_file("skill_envs")``."""
    return layla_data_dir().joinpath(*parts)
