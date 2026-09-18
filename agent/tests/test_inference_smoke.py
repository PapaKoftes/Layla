"""Real-inference smoke (R1 / Phase 3 / REQ-20): proves the actual run_completion path
loads a model and completes one turn. Gated on LAYLA_TEST_REAL_LLM so normal CI/unit
runs skip it; the dedicated inference-smoke CI job opts in with a tiny GGUF.

Run locally:
    LAYLA_TEST_REAL_LLM=1 LAYLA_SMOKE_MODEL=models/SmolLM2-360M-Instruct-Q4_K_M.gguf \
      ../.venv-test/Scripts/python -m pytest tests/test_inference_smoke.py -q
"""
import os
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

pytestmark = pytest.mark.skipif(
    not os.environ.get("LAYLA_TEST_REAL_LLM"),
    reason="real-LLM smoke; set LAYLA_TEST_REAL_LLM=1 (inference-smoke CI job)",
)


def _smoke_model() -> Path | None:
    env = os.environ.get("LAYLA_SMOKE_MODEL")
    if env and Path(env).exists():
        return Path(env)
    import runtime_safety as rs
    d = Path(rs.default_models_dir())
    ggufs = [g for g in d.glob("*.gguf") if g.stat().st_size > 1_000_000]  # skip stubs
    return sorted(ggufs, key=lambda p: p.stat().st_size)[0] if ggufs else None


def _text(out) -> str:
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        if out.get("choices"):
            ch = out["choices"][0]
            return (ch.get("message") or {}).get("content") or ch.get("text") or ""
        return out.get("text") or out.get("content") or out.get("response") or ""
    return ""


def test_real_run_completion_one_turn(monkeypatch):
    model = _smoke_model()
    if not model:
        # FAIL, don't skip: the module-level skipif already gated this to the real-LLM job
        # (LAYLA_TEST_REAL_LLM set). Reaching here with no model means the CI wiring that puts the GGUF
        # where the test looks has drifted — a skip would silently re-hollow the gate (which it did:
        # the model went to <repo>/models while conftest pointed default_models_dir at an empty tempdir).
        import runtime_safety as _rs
        pytest.fail(
            "real-LLM smoke: no .gguf found. Set LAYLA_SMOKE_MODEL, or download the model into "
            f"$LAYLA_DATA_DIR/models (default_models_dir()={_rs.default_models_dir()}). "
            "A missing model here is a CI setup failure, not a legitimate skip."
        )

    import runtime_safety as rs
    cfg = dict(rs.load_config())
    cfg.update({
        "model_filename": model.name,
        "models_dir": str(model.parent),
        "n_ctx": 2048, "n_gpu_layers": 0, "n_threads": 2,
        "resource_governor_enabled": False,  # deterministic threads for the smoke
        "use_chroma": False,
    })
    monkeypatch.setattr(rs, "load_config", lambda: cfg)

    from services.llm.llm_gateway import run_completion

    # A continuation prompt so a tiny instruct model reliably generates (a chat-style
    # instruction can legitimately stop at 0 tokens on a 360M model).
    out = run_completion("The capital of France is", max_tokens=24, temperature=0.0)
    text = _text(out)
    # Structural assertions (not exact strings — CPU kernels aren't bit-deterministic):
    assert isinstance(out, dict) and out.get("choices"), f"bad completion shape: {out!r}"
    usage = out.get("usage") or {}
    assert int(usage.get("prompt_tokens") or 0) >= 1, f"model didn't process the prompt: {out!r}"
    assert int(usage.get("completion_tokens") or 0) >= 1, f"model generated nothing: {out!r}"
    assert isinstance(text, str) and text.strip(), f"empty completion from real model: {out!r}"
    assert len(text) < 4000, "completion absurdly long for max_tokens=24"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
