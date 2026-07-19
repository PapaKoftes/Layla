"""pytest plugin that runs a suite slice under :mod:`_write_tracer`.

Loaded with ``-p _write_tracer_plugin`` so it is imported BEFORE ``conftest.py``. That ordering
matters: it means the collection window (module-level imports in every test file) is traced too,
which is where the operator's repo-root ``layla.db`` was being opened.

Writes a JSON report to ``$LAYLA_WRITE_TRACE_OUT`` at session end. Driven by
``tests/test_operator_state_isolation.py``; not useful standalone.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _write_tracer  # noqa: E402

_TRACER = _write_tracer.WriteTracer().install()


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    out = os.environ.get("LAYLA_WRITE_TRACE_OUT")
    if not out:
        return
    payload = [
        {"path": e.path, "op": e.op, "origin": e.origin}
        for e in _TRACER.events
    ]
    # Written with the *real* open — the tracer is still installed and would otherwise
    # record its own report file.
    _TRACER.uninstall()
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
