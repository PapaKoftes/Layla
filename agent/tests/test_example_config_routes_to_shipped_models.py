"""A fresh install's config (seeded from runtime_config.example.json) must not route to a model it doesn't have.

The example shipped models.code = "magicoder", so every install routed coding-looking turns to
Magicoder-S-DS-6.7B (never downloaded): a fallback + warning on every such turn.
"""
import json
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "runtime_config.example.json"


def test_no_per_task_model_is_preselected():
    cfg = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
    models = cfg.get("models") or {}
    assert isinstance(models, dict) and models, "PROBE BROKEN: example has no models block"
    chosen = {k: v for k, v in models.items() if (v or "").strip()}
    assert not chosen, f"the example config routes to models a fresh install has not downloaded: {chosen}"
    for k in ("coding_model", "reasoning_model", "chat_model", "decision_model"):
        assert not (cfg.get(k) or ""), f"{k} must be empty in the shipped example"
