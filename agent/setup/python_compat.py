"""
Python runtime compatibility for Layla.

Production-supported: 3.11 and 3.12.
Python >= 3.13: conditionally allowed. The full stack (incl. Chroma) is not guaranteed;
if Chroma is unusable on this interpreter, the result is still startable in a degraded
(semantic memory off) mode when core imports succeed.
"""
from __future__ import annotations

import sys
from typing import Any

# Public strings for critical_blockers (observability / health)
BLOCKER_CHROMADB_INCOMPATIBLE = "chromadb_incompatible"
BLOCKER_CORE_STACK_INCOMPLETE = "core_stack_incomplete"
BLOCKER_PYTHON_TOO_OLD = "python_too_old"


def check_python_compatibility() -> dict[str, Any]:
    """
    Return structured compatibility result.

    status:
      - supported: CPython 3.11 or 3.12
      - supported_unofficial: >= 3.13 — core imports OK; may include chromadb_incompatible
      - unsupported: below 3.11, or >= 3.13 with failing core imports

    critical_blockers:
      Machine-readable codes when parts of the stack cannot run (non-empty implies caveat).

    safe_mode:
      True when Layla should run without full capabilities — currently True only when
      Python >= 3.13 and Chroma cannot be initialized (semantic vector layer disabled).
    """
    vi = sys.version_info
    version = sys.version.split()[0]

    if vi < (3, 11):
        return {
            "version": version,
            "status": "unsupported",
            "issues": ["Python 3.11 or newer is required."],
            "critical_blockers": [BLOCKER_PYTHON_TOO_OLD],
            "safe_mode": True,
        }

    if vi < (3, 13):
        return {
            "version": version,
            "status": "supported",
            "issues": [],
            "critical_blockers": [],
            "safe_mode": False,
        }

    # --- 3.13+ (incl. 3.14): core imports first, then Chroma (optional for startup) ---
    issues: list[str] = []
    try:
        import sqlite3  # noqa: F401
    except ImportError as e:
        issues.append(f"sqlite3: {e}")
    try:
        import threading  # noqa: F401
    except ImportError as e:
        issues.append(f"threading: {e}")
    try:
        import concurrent.futures  # noqa: F401
    except ImportError as e:
        issues.append(f"concurrent.futures: {e}")
    # sentence_transformers is optional — reranking degrades gracefully without it
    # (do not add to issues; server ran 3+ days without it on 0.3.16)

    if issues:
        return {
            "version": version,
            "status": "unsupported",
            "issues": issues,
            "critical_blockers": [BLOCKER_CORE_STACK_INCOMPLETE],
            "safe_mode": True,
        }

    chroma_ok = False
    chroma_detail = ""
    try:
        from layla.memory import vector_store as vs

        vs.reset_chroma_clients()
        coll = vs._get_chroma_collection()
        _ = coll.count()
        chroma_ok = True
    except Exception as e:
        chroma_detail = str(e)

    if chroma_ok:
        return {
            "version": version,
            "status": "supported_unofficial",
            "issues": [],
            "critical_blockers": [],
            "safe_mode": False,
        }

    # Degraded but startable: semantic Chroma layer unavailable (wheels/interpreter mismatch).
    return {
        "version": version,
        "status": "supported_unofficial",
        "issues": [f"vector_store/chroma (non-fatal): {chroma_detail}"],
        "critical_blockers": [BLOCKER_CHROMADB_INCOMPATIBLE],
        "safe_mode": True,
    }
