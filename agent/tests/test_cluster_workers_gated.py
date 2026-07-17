"""BL-350: the cluster task workers must not run when clustering is off.

MEASURED. main.py started `start_drone_worker()` and `start_queen_worker()` UNCONDITIONALLY — unlike the
cluster network (gated on cluster_enabled) and node sync (gated on cluster_enabled) either side of them.
Neither start_drone_worker() nor DroneWorker.start() checks any config. So on every boot of every
standalone install, two threads spawned and polled the task queue forever: drone every 5s, queen every 8s.

They cannot ever find work. Both offload entry points are closed, verified independently:
  - cluster_network.submit_task / get_task_status / cancel_remote_task -> zero callers in the live tree
    (the task_dispatcher that would call them exists only in a stale worktree + build/lib)
  - inference_router.run_completion_with_fallback -> zero callers; every caller uses run_completion()
And live on the operator's box: GET /cluster/queue/stats -> {"stats":{},"pending":[],"running":[]}.

The gate keeps the RECEIVE path for a real cluster (a paired peer can still push a task in, and node_sync
— real, and a different feature — is gated on the same flag) while a standalone install stops paying two
polling threads for a subsystem with no entry point. On the `potato` tier this box auto-tunes to, that is
not free.
"""
from __future__ import annotations

import re
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
MAIN = AGENT / "main.py"


def _worker_block() -> str:
    src = MAIN.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"# Phase 3: Start the cluster task workers.*?(?=\n    # Phase 5A)", src, re.DOTALL)
    assert m, "the cluster worker startup block was not found in main.py — did startup get restructured?"
    return m.group(0)


def test_workers_are_gated_on_cluster_enabled():
    block = _worker_block()
    assert "cluster_enabled" in block, (
        "start_drone_worker()/start_queen_worker() must be gated on cluster_enabled. Ungated, they poll "
        "an unreachable queue every 5s/8s forever on every standalone install (BL-350)."
    )
    # The call must be INSIDE the gate, not merely near it.
    gate = block.split("cluster_enabled", 1)[1]
    assert "start_drone_worker()" in gate and "start_queen_worker()" in gate, (
        "the worker starts must sit inside the cluster_enabled branch"
    )


def test_workers_are_not_started_unconditionally():
    """The precise regression: a bare start_drone_worker() at statement level."""
    src = MAIN.read_text(encoding="utf-8", errors="replace")
    for line in src.splitlines():
        if re.match(r"\s{4,8}start_(drone|queen)_worker\(\)\s*$", line):
            indent = len(line) - len(line.lstrip())
            assert indent > 8, (
                f"start_*_worker() appears at indent {indent} — that reads as an unconditional start, "
                f"which is the defect: {line!r}"
            )


def test_the_gate_reads_config_not_a_constant():
    block = _worker_block()
    assert "load_config()" in block, "the gate must consult runtime config, not a hardcoded value"
