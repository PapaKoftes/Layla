"""Tests for inference_router (multi-backend LLM routing)."""

from services.llm.inference_router import (
    _BACKENDS,
    _detect_backend,
    effective_inference_backend,
    inference_backend_uses_local_gguf,
)


def test_detect_backend_no_url_uses_llama_cpp():
    cfg = {"llama_server_url": "", "inference_backend": "auto"}
    assert _detect_backend(cfg) == "llama_cpp"


def test_detect_backend_ollama_port():
    cfg = {"llama_server_url": "http://localhost:11434", "inference_backend": "auto"}
    assert _detect_backend(cfg) == "ollama"


def test_detect_backend_ollama_hostname():
    cfg = {"llama_server_url": "http://ollama:11434", "inference_backend": "auto"}
    assert _detect_backend(cfg) == "ollama"


def test_detect_backend_openai_compatible():
    cfg = {"llama_server_url": "http://localhost:8000", "inference_backend": "auto"}
    assert _detect_backend(cfg) == "openai_compatible"


def test_detect_backend_explicit_override():
    cfg = {"llama_server_url": "http://localhost:11434", "inference_backend": "openai_compatible"}
    assert _detect_backend(cfg) == "openai_compatible"


def test_detect_backend_explicit_llama_cpp():
    cfg = {"llama_server_url": "http://localhost:8000", "inference_backend": "llama_cpp"}
    assert _detect_backend(cfg) == "llama_cpp"


def test_backends_constant():
    assert "llama_cpp" in _BACKENDS
    assert "openai_compatible" in _BACKENDS
    assert "ollama" in _BACKENDS


def test_effective_inference_backend_alias():
    cfg = {"llama_server_url": "", "inference_backend": "auto"}
    assert effective_inference_backend(cfg) == "llama_cpp"


def test_inference_backend_uses_local_gguf():
    assert inference_backend_uses_local_gguf({"llama_server_url": "", "inference_backend": "auto"}) is True
    assert (
        inference_backend_uses_local_gguf(
            {"llama_server_url": "http://localhost:8000", "inference_backend": "auto"}
        )
        is False
    )


class TestPrefixReuseIsNotThrownAway:
    """The KV cache must NOT be reset before every completion.

    `_call_create_completion` used to unconditionally call `llm._ctx.kv_cache_clear()` and
    `llm.reset()` before every single completion. `reset()` sets n_tokens = 0, so llama-cpp had
    nothing to match the incoming prompt against and re-prefilled the entire system head from
    scratch on 4 CPU threads, every turn, forever.

    MEASURED on this box (Qwen2.5-3B-Q4_K_M, n_ctx 2048, 827-token head), driven through the real
    `run_completion_llama_cpp` with a stable head and a DIFFERENT goal and memory line each turn —
    the real shape of a conversation, not an artificial identical prompt:

        with the reset:  14.00s  14.36s          (every turn pays the full prefill)
        without:         18.02s   0.69s   0.54s

    Output is byte-identical at temperature 0 across five prompts, fresh instance vs reused
    context, so this buys latency and changes nothing the model says.

    These tests use a fake Llama so they run in CI without a 1.8 GB model. That means they pin the
    CONTRACT (are the reset calls made?) and not the latency — the latency is recorded above and in
    the commit, because a timing assertion in a merge gate is a flake, not a guard.
    """

    class _FakeCtx:
        def __init__(self, log):
            self._log = log

        def kv_cache_clear(self):
            self._log.append("kv_cache_clear")

    class _FakeLlama:
        def __init__(self, log):
            self._log = log
            self._ctx = TestPrefixReuseIsNotThrownAway._FakeCtx(log)

        def reset(self):
            self._log.append("reset")

        def create_completion(self, prompt, stream=False, **kw):
            self._log.append("create_completion")
            if stream:
                return iter([{"choices": [{"text": "ok"}]}])
            return {"choices": [{"text": "ok"}]}

    def _drive(self, cfg):
        import threading

        from services.llm.inference_router import run_completion_llama_cpp

        log: list[str] = []
        llm = self._FakeLlama(log)
        out = run_completion_llama_cpp(
            cfg, "hello", 8, 0.0, 1.0, 1.1, 40, [], False, lambda: llm, threading.Lock(),
        )
        if hasattr(out, "__next__"):
            list(out)
        return log

    def test_the_default_does_not_reset_the_kv_cache(self):
        """THE FIX. A reset here costs ~14-22s of first-token latency on every turn after the
        first, because it destroys the prefix llama-cpp would otherwise reuse."""
        log = self._drive({})
        assert "create_completion" in log, "the completion never ran; this test proves nothing"
        assert "reset" not in log, (
            "llm.reset() was called before the completion — that sets n_tokens = 0, so llama-cpp "
            "has nothing to match the incoming prompt against and re-prefills the whole system "
            "head. Measured cost: first token 0.69s -> 14.36s on turn 2."
        )
        assert "kv_cache_clear" not in log, (
            "kv_cache_clear() was called before the completion, discarding the reusable prefix"
        )

    def test_the_escape_hatch_restores_the_old_behaviour(self):
        """The knob has to actually work, or it is the fake control this project keeps finding.

        Both calls are required together: the original comment records that reset() alone leaves
        the C-level cache stale, and kv_cache_clear() alone leaves n_tokens > 0 and mis-scores the
        next eval. So if the hatch is on, it must do both.
        """
        log = self._drive({"llm_reset_kv_each_call": True})
        assert "kv_cache_clear" in log and "reset" in log, (
            "llm_reset_kv_each_call=True did not restore the reset — a config key that changes "
            "nothing is the same defect as a gate that cannot be cleared: %r" % (log,)
        )
        assert log.index("kv_cache_clear") < log.index("create_completion"), (
            "the reset must happen BEFORE the completion to have any effect"
        )

    def test_the_reset_is_off_unless_explicitly_asked_for(self):
        """A falsy value must not turn it on — the expensive path needs a deliberate choice."""
        for falsy in ({}, {"llm_reset_kv_each_call": False}, {"llm_reset_kv_each_call": 0},
                      {"llm_reset_kv_each_call": ""}, {"llm_reset_kv_each_call": None}):
            log = self._drive(falsy)
            assert "reset" not in log, "reset fired for cfg %r" % (falsy,)
