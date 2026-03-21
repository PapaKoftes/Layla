"""
Deterministic JSON-in/JSON-out echo kernel for SubprocessJsonRunner tests.

Run: python -m fabrication_assist.assist.echo_kernel <path-to-config.json>
Prints one JSON line (ProductResult) to stdout.

Env (tests only):
  ECHO_KERNEL_FAIL=1       -> exit 2
  ECHO_KERNEL_BAD_JSON=1   -> print non-JSON, exit 0
  ECHO_KERNEL_SLEEP=<float> -> sleep before work (timeout tests)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def build_result_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    vid = str(cfg.get("id") or cfg.get("name") or "variant")
    seed = hashlib.sha256(vid.encode()).hexdigest()[:8]
    base = 0.5 + (int(seed[:4], 16) % 5000) / 20000.0
    return {
        "variant_id": vid,
        "label": str(cfg.get("label", vid)),
        "score": round(min(0.99, base), 4),
        "metrics": {
            "assembly_simplicity": round(base * 0.9, 4),
            "material_efficiency": round(base * 0.85, 4),
            "machining_time_proxy": round(1.0 - base * 0.3, 4),
        },
        "notes": f"echo_kernel seed={seed}",
        "feasible": True,
    }


def main() -> int:
    if os.environ.get("ECHO_KERNEL_FAIL") == "1":
        print("kernel failed (test)", file=sys.stderr)
        return 2
    sleep_s = os.environ.get("ECHO_KERNEL_SLEEP")
    if sleep_s:
        try:
            time.sleep(float(sleep_s))
        except ValueError:
            pass
    if len(sys.argv) < 2:
        print("usage: echo_kernel <config.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"missing config file: {path}", file=sys.stderr)
        return 2
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        print("config must be a JSON object", file=sys.stderr)
        return 2
    out = build_result_from_config(cfg)
    line = json.dumps(out, separators=(",", ":"))
    if os.environ.get("ECHO_KERNEL_BAD_JSON") == "1":
        print("NOT_JSON_OUTPUT")
        return 0
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
