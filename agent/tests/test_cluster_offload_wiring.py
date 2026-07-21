"""Phase 13 criterion 5 (clustering): LAN clustering moved zero work because nothing offloaded.

Every piece existed and none were connected:

  * `get_best_peer_for_inference()` ranks discovered peers by hardware tier (gpu_high > gpu_mid > gpu_low > cpu)
  * `run_completion_cluster(peer, ...)` sends a completion to a peer and returns the text
  * `DroneWorker._handle_inference` on the receiving side runs it and reports back
  * `cluster_offload_enabled` exists in config
  * the UI ships an Enable toggle — translated into 11 locales

...and `run_completion_with_cluster`, the one function that joined them, had NO ENTRY POINT
(verified in its own docstring, BL-350). Every caller used `run_completion()` directly.

Worse than unwired: it was designed as a FAILURE FALLBACK — local first, peer only if local raises.
On the target machine local never raises, it succeeds slowly, so even wired it would never have
offloaded. The operator's intent is the opposite — "anchor a potato to a bigger dedicated gaming PC
... to work with a compute cluster" — which means PREFER the better machine while it is there.

`try_cluster_offload_first` implements that, and these tests pin the safety properties, because an
offload path that can fail a turn is worse than no offload path at all.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.llm import inference_router as ir

GOOD = {"choices": [{"message": {"content": "answer from the gaming PC"}}]}
GPU_PEER = {"name": "battlestation", "hardware_tier": "gpu_high", "ip": "192.168.1.5", "port": 8000}
CPU_PEER = {"name": "other-potato", "hardware_tier": "cpu", "ip": "192.168.1.9", "port": 8000}


def _call(cfg, peer, cluster_result=GOOD, raises=None):
    def _run_cluster(*a, **k):
        if raises:
            raise raises
        return cluster_result

    with patch("services.cluster.mdns_discovery.get_best_peer_for_inference", return_value=peer), \
         patch("services.cluster.mdns_discovery.detect_hardware_tier", return_value="cpu"), \
         patch.object(ir, "run_completion_cluster", _run_cluster):
        return ir.try_cluster_offload_first("hello", 256, 0.2, None, 30, cfg)


class TestOffloadHappensWhenItShould:
    def test_a_beefier_peer_serves_the_completion(self):
        out = _call({"cluster_offload_enabled": True, "hardware_tier": "cpu"}, GPU_PEER)
        assert out is GOOD, "a gpu_high peer was available and the work stayed local"

    def test_disabled_by_default_costs_nothing(self):
        """The flag is off by default; this sits on the inference hot path."""
        out = _call({}, GPU_PEER)
        assert out is None


class TestOffloadIsRefusedWhenItWouldNotHelp:
    def test_a_peer_that_does_not_outrank_local_is_ignored(self):
        """Same-tier or weaker is pure added latency — the point is a BETTER machine."""
        out = _call({"cluster_offload_enabled": True, "hardware_tier": "cpu"}, CPU_PEER)
        assert out is None, "offloaded to a peer no stronger than this box; that is a slowdown"

    def test_a_gpu_local_does_not_offload_to_an_equal_gpu(self):
        out = _call({"cluster_offload_enabled": True, "hardware_tier": "gpu_high"}, GPU_PEER)
        assert out is None

    def test_no_peer_means_local(self):
        out = _call({"cluster_offload_enabled": True, "hardware_tier": "cpu"}, None)
        assert out is None


class TestOffloadCanNeverFailATurn:
    """An unreachable gaming PC must cost one attempt, never the user's answer."""

    def test_a_raising_peer_falls_back_to_local(self):
        out = _call({"cluster_offload_enabled": True, "hardware_tier": "cpu"}, GPU_PEER,
                    raises=OSError("connection refused"))
        assert out is None, "a dead peer must degrade to local, not propagate"

    @pytest.mark.parametrize("bad", [
        {}, {"choices": []}, {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": "   "}}]}, None,
    ])
    def test_a_malformed_or_empty_peer_reply_is_not_accepted(self, bad):
        """A blank reply must not be mistaken for a successful offload and shipped to the user."""
        out = _call({"cluster_offload_enabled": True, "hardware_tier": "cpu"}, GPU_PEER,
                    cluster_result=bad)
        assert out is None, f"accepted {bad!r} as a completion — the user would get an empty answer"

    def test_discovery_blowing_up_falls_back_to_local(self):
        with patch("services.cluster.mdns_discovery.get_best_peer_for_inference", side_effect=RuntimeError("mdns down")), \
             patch("services.cluster.mdns_discovery.detect_hardware_tier", return_value="cpu"):
            out = ir.try_cluster_offload_first(
                "hello", 256, 0.2, None, 30, {"cluster_offload_enabled": True, "hardware_tier": "cpu"},
            )
        assert out is None


def test_the_gateway_actually_calls_the_offload():
    """The whole defect was a correct function nobody called. Assert the wiring, by AST."""
    import ast
    from pathlib import Path

    src = (Path(ir.__file__).parent / "llm_gateway.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = any(
        isinstance(n, ast.Call)
        and (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) == "try_cluster_offload_first"
        for n in ast.walk(tree)
    )
    assert called, (
        "llm_gateway.run_completion does not call try_cluster_offload_first — clustering is back to "
        "moving zero work, which is exactly the state BL-350 recorded"
    )
