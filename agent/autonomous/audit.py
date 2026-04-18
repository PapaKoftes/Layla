from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.types import StepRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLog:
    def __init__(self, *, agent_dir: Path):
        self.path = (agent_dir / ".governance" / "autonomous_audit.jsonl").resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_event(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("ts", _now_iso())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def write_step(self, *, run_id: str, step: StepRecord) -> None:
        d = asdict(step)
        args_summary = ""
        try:
            dec = step.decision
            if dec.type == "tool" and isinstance(dec.args, dict):
                args_summary = json.dumps(dec.args, ensure_ascii=False, default=str)[:1200]
        except Exception:
            args_summary = ""
        result_size = 0
        try:
            if isinstance(d.get("tool_result"), dict):
                tr = dict(d["tool_result"])
                blob = json.dumps(tr, ensure_ascii=False, default=str)
                result_size = len(blob)
                if len(blob) > 12000:
                    d["tool_result"] = {"ok": tr.get("ok", True), "truncated": True, "keys": sorted(tr.keys())[:40]}
        except Exception:
            pass
        self.write_event({
            "type": "step",
            "run_id": run_id,
            "args_summary": args_summary,
            "result_size": result_size,
            "step": d,
        })

    def write_final(self, *, run_id: str, final: dict[str, Any]) -> None:
        self.write_event({"type": "final", "run_id": run_id, "final": final})

