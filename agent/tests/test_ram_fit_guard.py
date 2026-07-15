"""Minimum-RAM guard: refuse to load a model too large for this machine instead of letting Llama()
thrash swap and get OOM-killed with no message (the failure a non-technical user hits on an 8 GB box
with a 7B model). Guard lives in llm_gateway._ram_fit_error and is surfaced by both model_loaded_status
(clean pre-check) and _get_llm (hard backstop)."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.llm import llm_gateway as g  # noqa: E402

GB = 1024 ** 3


def _vm(total_gb, avail_gb):
    return SimpleNamespace(total=int(total_gb * GB), available=int(avail_gb * GB))


def _check(model_gb, total_gb, avail_gb, cfg):
    with patch("os.path.getsize", return_value=int(model_gb * GB)), \
         patch("psutil.virtual_memory", return_value=_vm(total_gb, avail_gb)):
        return g._ram_fit_error("/models/x.gguf", cfg)


CPU = {"n_gpu_layers": 0}


def test_refuses_7b_on_8gb_cpu_box():
    err = _check(4.4, 8.0, 3.0, CPU)
    assert err and "Not enough RAM" in err and "4.4 GB" in err and "8.0 GB" in err


def test_allows_7b_on_16gb_cpu_box():
    assert _check(4.4, 16.0, 9.0, CPU) is None


def test_allows_3b_on_8gb_cpu_box():
    assert _check(1.8, 8.0, 4.0, CPU) is None


def test_refuses_14b_on_16gb_cpu_box():
    err = _check(8.5, 16.0, 10.0, CPU)
    assert err and "Not enough RAM" in err


def test_gpu_offload_is_never_blocked():
    # n_gpu_layers != 0 → weights go to VRAM, RAM guard must not fire even for a huge file.
    assert _check(20.0, 8.0, 2.0, {"n_gpu_layers": -1}) is None
    assert _check(20.0, 8.0, 2.0, {"n_gpu_layers": 35}) is None


def test_remote_inference_is_never_blocked():
    assert _check(20.0, 8.0, 2.0, {"n_gpu_layers": 0, "llama_server_url": "http://host:8080"}) is None


def test_override_flag_disables_guard():
    assert _check(4.4, 8.0, 3.0, {"n_gpu_layers": 0, "skip_ram_fit_check": True}) is None


def test_helpers_are_wired_into_status_and_load():
    # The clean pre-check (model_loaded_status) and the hard backstop (_get_llm) both consult it.
    import inspect
    assert "_ram_fit_error" in inspect.getsource(g.model_loaded_status)
    assert "_ram_fit_error" in inspect.getsource(g._get_llm)
