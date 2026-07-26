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

from unittest.mock import MagicMock, patch

import pytest

from services.llm import inference_router as ir
from services.llm import llm_gateway as gw

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


# ── Plan #19: STREAMING-path offload ────────────────────────────────────────────────────────────
#
# The non-stream branch already offloaded (llm_gateway calls try_cluster_offload_first before the
# local retry loop). The STREAMING branch — the DEFAULT UI path — did not, so a streamed turn always
# ran locally even with a paired GPU peer available: the chat path moved zero work. These pin the
# streaming seam's three load-bearing properties.
#
# All hermetic: runtime_safety.load_config is patched to a controlled cfg (tool_routing_enabled off
# so no model-router classification fires; a huge dual-model threshold so no dual-model probe fires),
# and the LOCAL streaming backend (inference_router.run_completion, which the gateway imports as _run
# at call time) is mocked — so no real GGUF is ever loaded.

# tool_routing_enabled off + a huge dual_model_threshold_gb keep _effective_model_filename cheap and
# deterministic; model_filename gives it a concrete basename to return.
_STREAM_CFG_ON = {
    "cluster_offload_enabled": True,
    "hardware_tier": "cpu",
    "tool_routing_enabled": False,
    "dual_model_threshold_gb": 999999,
    "model_filename": "test.gguf",
}
_STREAM_CFG_OFF = {
    # cluster_offload_enabled deliberately absent → the common, clustering-off case.
    "hardware_tier": "cpu",
    "tool_routing_enabled": False,
    "dual_model_threshold_gb": 999999,
    "model_filename": "test.gguf",
}


def _local_stream_mock(*chunks):
    """A mock standing in for the LOCAL streaming backend (inference_router.run_completion).

    Returns a MagicMock so callers can assert `.called`; each invocation yields `chunks` and asserts
    the gateway actually requested stream=True on the local seam.
    """
    def _impl(*_a, **kw):
        assert kw.get("stream") is True, "gateway drove the local seam without stream=True"
        return (c for c in chunks)

    return MagicMock(side_effect=_impl)


class TestStreamingOffload:
    def test_a_peer_serves_the_stream_local_model_is_not_touched(self):
        """(a) A beefier peer serves a STREAMED turn (as a single chunk); the local model never runs."""
        local = MagicMock(side_effect=AssertionError("local streaming ran while a peer served the turn"))
        with patch("runtime_safety.load_config", return_value=_STREAM_CFG_ON), \
             patch.object(ir, "try_cluster_offload_first", return_value=GOOD), \
             patch.object(ir, "run_completion", local):
            gen = gw.run_completion("hello", max_tokens=64, temperature=0.2, stream=True)
            chunks = list(gen)
        assert chunks == ["answer from the gaming PC"], "peer answer was not delivered as one clean chunk"
        local.assert_not_called()

    def test_b_peer_failure_mid_offload_falls_back_to_local_cleanly(self):
        """(b) The offload blows up mid-turn; the turn still completes LOCALLY, delivering the FULL
        answer with no leaked peer fragment — never a half-stream with no fallback."""
        local = _local_stream_mock("loc", "al ", "answer")
        with patch("runtime_safety.load_config", return_value=_STREAM_CFG_ON), \
             patch.object(ir, "try_cluster_offload_first", side_effect=OSError("peer stream died mid-way")), \
             patch.object(ir, "run_completion", local):
            gen = gw.run_completion("hello", max_tokens=64, temperature=0.2, stream=True)
            out = "".join(list(gen))
        assert local.called, "local streaming fallback never ran after the peer failed"
        assert out == "local answer", "local fallback did not deliver the full, uncorrupted answer"
        assert "gaming PC" not in out, "a peer fragment leaked into the fallback stream"

    def test_c_clustering_off_is_a_noop_peer_layer_never_consulted(self):
        """(c) Clustering off → the local streaming path is byte-identical and the peer layer is
        never consulted (the real try_cluster_offload_first returns at its enabled-gate)."""
        cluster_call = MagicMock(name="run_completion_cluster")
        local = _local_stream_mock("hello ", "from ", "local")
        with patch("runtime_safety.load_config", return_value=_STREAM_CFG_OFF), \
             patch.object(ir, "run_completion_cluster", cluster_call), \
             patch("services.cluster.mdns_discovery.get_best_peer_for_inference") as best_peer, \
             patch.object(ir, "run_completion", local):
            gen = gw.run_completion("hi", max_tokens=64, temperature=0.2, stream=True)
            chunks = list(gen)
        assert "".join(chunks) == "hello from local"
        assert chunks == ["hello ", "from ", "local"], "local chunk boundaries were altered when offload is off"
        assert local.called
        cluster_call.assert_not_called()
        best_peer.assert_not_called()
