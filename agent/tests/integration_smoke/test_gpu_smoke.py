"""GPU smoke: load a real GGUF with GPU offload when maintainer env is set (self-hosted / local only)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[2]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

pytestmark = [pytest.mark.gpu_smoke, pytest.mark.timeout(300)]


def test_gpu_llama_loads_configured_gguf():
    if os.environ.get("LAYLA_GPU_SMOKE", "").strip().lower() not in ("1", "true", "yes"):
        pytest.skip("LAYLA_GPU_SMOKE not enabled")
    gguf = os.environ.get("LAYLA_GPU_SMOKE_GGUF", "").strip()
    if not gguf or not Path(gguf).is_file():
        pytest.skip("LAYLA_GPU_SMOKE_GGUF not set or file missing")
    layers = int(os.environ.get("LAYLA_GPU_SMOKE_N_GPU_LAYERS", "1"))
    n_ctx = int(os.environ.get("LAYLA_GPU_SMOKE_N_CTX", "512"))
    from llama_cpp import Llama

    Llama(gguf, n_gpu_layers=layers, n_ctx=n_ctx, verbose=False)
