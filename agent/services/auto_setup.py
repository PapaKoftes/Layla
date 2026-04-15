"""Idempotent post-install setup steps (model path, doctor, flags in DB)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def run_auto_setup(*, write_config: bool = True) -> dict[str, Any]:
    """
    Run lightweight checks after first-run wizard. Extend with model download hooks as needed.
    """
    import runtime_safety

    cfg = runtime_safety.load_config()
    out: dict[str, Any] = {"ok": True, "steps": []}
    try:
        from services.system_doctor import run_diagnostics

        doc = run_diagnostics(include_llm=False)
        out["doctor"] = doc.get("status", "unknown")
        out["steps"].append("doctor")
    except Exception as e:
        out["steps"].append(f"doctor_failed:{e}")
    if write_config:
        out["steps"].append("config_loaded")
        out["model_filename"] = (cfg.get("model_filename") or "").strip()
    return out
