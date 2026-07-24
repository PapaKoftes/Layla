"""The embedding model must be fetched AT INSTALL TIME, and its absence must be LOUD.

Before this, the embedder (model2vec potion-base-8M / nomic / all-MiniLM) was downloaded from
HuggingFace on FIRST USE. So whether semantic search worked was decided by whether the user happened to
be online the first time a memory operation ran — weeks after the install, with no message either way.
Install-then-go-offline (the advertised way to run Layla) produced permanent, silent keyword-only
retrieval.

The fix has three parts, and each is pinned here:
  1. `vector_store.prefetch_embedder()` — downloads + loads + PROVES (it embeds) the model the runtime
     will actually use; returns ok/failed instead of raising; idempotent.
  2. the installer calls it (`provision_model.prefetch_embedding_model`, `--embedder-only`) and treats a
     failure as non-fatal-but-loud, so a 4 GB GGUF download is never thrown away over a 30 MB embedder.
  3. `scripts/selftest.py` reports it as its own named check, so "degraded" is visible by name.

NOTHING HERE TOUCHES THE NETWORK. Every model load is a stubbed `model2vec` / `sentence_transformers`
module; the real ones would try to reach huggingface.co.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent


# ── stubs ─────────────────────────────────────────────────────────────────────

class _FakeStaticModel:
    """Stands in for a model2vec StaticModel: encodes without a model or a network."""

    def __init__(self) -> None:
        self.encode_calls = 0

    def encode(self, texts, batch_size=256, **_kw):
        self.encode_calls += 1
        return [[0.1, 0.2, 0.3, 0.4] for _ in list(texts)]


class _FakeSentenceTransformer:
    def __init__(self, name, **_kw):
        self.name = name

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True, **_kw):
        import numpy as np

        n = 1 if isinstance(texts, str) else len(list(texts))
        return np.ones((n, 8), dtype="float32")


def _fake_model2vec(loads: list, *, error: Exception | None = None) -> types.ModuleType:
    mod = types.ModuleType("model2vec")

    class StaticModel:
        @staticmethod
        def from_pretrained(name, *_a, **_kw):
            loads.append(name)
            if error is not None:
                raise error
            return _FakeStaticModel()

    mod.StaticModel = StaticModel  # type: ignore[attr-defined]
    return mod


def _fake_sentence_transformers(loads: list, *, error: Exception | None = None) -> types.ModuleType:
    mod = types.ModuleType("sentence_transformers")

    def SentenceTransformer(name, *_a, **_kw):  # noqa: N802 — mirrors the real class name
        loads.append(name)
        if error is not None:
            raise error
        return _FakeSentenceTransformer(name)

    mod.SentenceTransformer = SentenceTransformer  # type: ignore[attr-defined]
    return mod


@pytest.fixture()
def vs(monkeypatch):
    """A vector_store with pristine embedder globals, restored afterwards.

    Embedder state is module-global (`_embedder`, `_embedder_error`, `_current_model_name`), so a test
    that loads a stub must not leak it into the rest of the suite.
    """
    import layla.memory.vector_store as _vs

    saved = (_vs._embedder, _vs._embedder_error, _vs._embedder_error_logged,
             _vs._current_model_name, _vs.CHROMA_PATH)
    _vs._embedder = None
    _vs._embedder_error = None
    _vs._embedder_error_logged = False
    _vs._current_model_name = ""
    _vs._embed_cached.cache_clear()

    # Deterministic preference: model2vec first (the shipped default), not whatever this box's
    # runtime_config.json happens to say.
    import runtime_safety as rs
    monkeypatch.setattr(rs, "load_config", lambda *a, **k: {"embedder_prefer_quality": False})

    yield _vs

    (_vs._embedder, _vs._embedder_error, _vs._embedder_error_logged,
     _vs._current_model_name, _vs.CHROMA_PATH) = saved
    _vs._embed_cached.cache_clear()


# ── 1. prefetch_embedder() ────────────────────────────────────────────────────

def test_prefetch_success_reports_ok_with_the_model_name(vs, monkeypatch):
    loads: list[str] = []
    monkeypatch.setitem(sys.modules, "model2vec", _fake_model2vec(loads))

    res = vs.prefetch_embedder()

    assert res["ok"] is True, res
    assert res["model"] == vs.EMBED_MODEL_STATIC, res
    assert res["already_loaded"] is False
    # It fetched the model the RUNTIME prefers — a prefetch of a different repo id would look like a
    # success and still leave the first offline run with a cold cache.
    assert loads == [vs.EMBED_MODEL_STATIC], loads


def test_prefetch_success_makes_status_ok(vs, monkeypatch):
    monkeypatch.setitem(sys.modules, "model2vec", _fake_model2vec([]))

    vs.prefetch_embedder()

    st = vs.embedder_status()
    assert st["status"] == "ok", st
    assert st["model"] == vs.EMBED_MODEL_STATIC


def test_prefetch_honours_embedder_prefer_quality(vs, monkeypatch):
    """With prefer_quality set, the warmed model must be the sentence-transformers one."""
    import runtime_safety as rs

    monkeypatch.setattr(rs, "load_config", lambda *a, **k: {"embedder_prefer_quality": True})
    m2v_loads: list[str] = []
    st_loads: list[str] = []
    monkeypatch.setitem(sys.modules, "model2vec", _fake_model2vec(m2v_loads))
    monkeypatch.setitem(sys.modules, "sentence_transformers", _fake_sentence_transformers(st_loads))

    res = vs.prefetch_embedder()

    assert res["ok"] is True, res
    assert res["model"] == vs.EMBED_MODEL_QUALITY, res
    assert st_loads == [vs.EMBED_MODEL_QUALITY]
    assert m2v_loads == [], "prefer_quality=True must not warm the static model"


def test_prefetch_failure_is_not_fatal_and_reports_the_reason(vs, monkeypatch):
    """The offline case: every backend raises. prefetch must RETURN, never raise."""
    offline = OSError("We couldn't connect to huggingface.co to download the model")
    monkeypatch.setitem(sys.modules, "model2vec", _fake_model2vec([], error=offline))
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        _fake_sentence_transformers([], error=offline))

    res = vs.prefetch_embedder()  # must not raise

    assert res["ok"] is False, res
    assert res["model"] == ""
    assert "huggingface" in res["detail"].lower(), res

    st = vs.embedder_status()
    assert st["status"] == "unavailable", st
    assert "huggingface" in st["detail"].lower()
    # Degraded state must be ACTIONABLE, not just observable.
    assert "--embedder-only" in st["remedy"], st
    assert "keyword-only" in st["impact"].lower(), st


def test_prefetch_failure_when_no_backend_is_installed(vs, monkeypatch):
    """Neither library present (a --skip-model / minimal env): still a clean failed result."""
    def _blocked(name, *a, **k):
        if name in ("model2vec", "sentence_transformers"):
            raise ImportError(f"No module named {name!r}")
        return _real_import(name, *a, **k)

    import builtins
    _real_import = builtins.__import__
    monkeypatch.delitem(sys.modules, "model2vec", raising=False)
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    monkeypatch.setattr(builtins, "__import__", _blocked)

    res = vs.prefetch_embedder()

    monkeypatch.setattr(builtins, "__import__", _real_import)
    assert res["ok"] is False, res
    assert "model2vec" in res["detail"] or "sentence_transformers" in res["detail"], res
    assert vs.embedder_status()["status"] == "unavailable"


def test_prefetch_failure_logs_the_loud_error_once(vs, monkeypatch, caplog):
    import logging

    offline = OSError("We couldn't connect to huggingface.co")
    monkeypatch.setitem(sys.modules, "model2vec", _fake_model2vec([], error=offline))
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        _fake_sentence_transformers([], error=offline))

    with caplog.at_level(logging.ERROR, logger="layla"):
        vs.prefetch_embedder()
        vs.prefetch_embedder()

    errs = [r for r in caplog.records if "EMBEDDER UNAVAILABLE" in r.getMessage()]
    assert len(errs) == 1, f"expected exactly one loud ERROR, got {len(errs)}"
    assert "--embedder-only" in errs[0].getMessage()


def test_prefetch_is_idempotent_and_downloads_once(vs, monkeypatch):
    loads: list[str] = []
    monkeypatch.setitem(sys.modules, "model2vec", _fake_model2vec(loads))

    first = vs.prefetch_embedder()
    second = vs.prefetch_embedder()
    third = vs.prefetch_embedder()

    assert first["ok"] and second["ok"] and third["ok"]
    assert first["already_loaded"] is False
    assert second["already_loaded"] is True and third["already_loaded"] is True
    assert loads == [vs.EMBED_MODEL_STATIC], f"re-downloaded on repeat calls: {loads}"
    assert second["model"] == third["model"] == vs.EMBED_MODEL_STATIC


def test_prefetch_force_retries_after_a_failure(vs, monkeypatch):
    """The 'you were offline, now you're online' path: a retry must actually retry."""
    offline = OSError("We couldn't connect to huggingface.co")
    monkeypatch.setitem(sys.modules, "model2vec", _fake_model2vec([], error=offline))
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        _fake_sentence_transformers([], error=offline))
    assert vs.prefetch_embedder()["ok"] is False

    loads: list[str] = []
    monkeypatch.setitem(sys.modules, "model2vec", _fake_model2vec(loads))

    res = vs.prefetch_embedder(force=True)

    assert res["ok"] is True, res
    assert loads == [vs.EMBED_MODEL_STATIC]
    st = vs.embedder_status()
    assert st["status"] == "ok" and not st["detail"], st  # the stale failure is cleared


def test_prefetch_rejects_a_model_that_loads_but_cannot_embed(vs, monkeypatch):
    """'ok' has to mean usable. A loader that returns a broken object is a failure, not a success."""
    mod = types.ModuleType("model2vec")

    class _Broken:
        def encode(self, *_a, **_kw):
            raise RuntimeError("weights are corrupt")

    class StaticModel:
        @staticmethod
        def from_pretrained(*_a, **_kw):
            return _Broken()

    mod.StaticModel = StaticModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "model2vec", mod)
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        _fake_sentence_transformers([], error=OSError("offline")))

    res = vs.prefetch_embedder()

    assert res["ok"] is False, res
    assert vs.embedder_status()["status"] == "unavailable"


# ── 2. the installer ──────────────────────────────────────────────────────────

@pytest.fixture()
def pm():
    from install import provision_model as _pm

    return _pm


def test_installer_prefetch_prints_progress_and_done(pm, vs, monkeypatch, capsys):
    monkeypatch.setattr(vs, "prefetch_embedder",
                        lambda **_kw: {"ok": True, "model": vs.EMBED_MODEL_STATIC,
                                       "detail": "", "already_loaded": False})

    assert pm.prefetch_embedding_model() is True

    out = capsys.readouterr().out
    assert "Fetching embedding model" in out
    assert "done" in out and vs.EMBED_MODEL_STATIC in out


def test_installer_prefetch_failure_is_non_fatal_but_loud(pm, vs, monkeypatch, capsys):
    monkeypatch.setattr(vs, "prefetch_embedder",
                        lambda **_kw: {"ok": False, "model": "",
                                       "detail": "OSError: We couldn't connect to huggingface.co",
                                       "already_loaded": False})

    ok = pm.prefetch_embedding_model()  # must not raise: the GGUF is already downloaded

    assert ok is False
    err = capsys.readouterr().err
    assert "KEYWORD-ONLY" in err, err
    assert "huggingface" in err.lower(), err
    assert "--embedder-only" in err, "the warning must carry the command that fixes it"
    assert "still fully installed" in err, "must not read as a failed install"


def test_installer_prefetch_survives_prefetch_raising(pm, vs, monkeypatch, capsys):
    def _boom(**_kw):
        raise RuntimeError("something exploded inside the embedder stack")

    monkeypatch.setattr(vs, "prefetch_embedder", _boom)

    assert pm.prefetch_embedding_model() is False
    assert "KEYWORD-ONLY" in capsys.readouterr().err


def test_embedder_only_flag_skips_hardware_and_model_download(pm, vs, monkeypatch, capsys):
    """`--embedder-only` must work on a box with no GGUF and no config at all."""
    from install import hardware_probe

    def _must_not_run(*_a, **_kw):
        raise AssertionError("--embedder-only probed hardware / touched the model path")

    monkeypatch.setattr(hardware_probe, "probe_hardware", _must_not_run)
    monkeypatch.setattr(vs, "prefetch_embedder",
                        lambda **_kw: {"ok": True, "model": vs.EMBED_MODEL_STATIC,
                                       "detail": "", "already_loaded": False})

    assert pm.main(["--embedder-only"]) == 0
    assert "done" in capsys.readouterr().out


def test_embedder_only_exit_code_is_nonzero_on_failure(pm, vs, monkeypatch, capsys):
    """Honest exit code for scripts — the bootstraps ignore it on purpose, but it must not lie."""
    monkeypatch.setattr(vs, "prefetch_embedder",
                        lambda **_kw: {"ok": False, "model": "", "detail": "offline",
                                       "already_loaded": False})

    assert pm.main(["--embedder-only"]) != 0
    capsys.readouterr()


def test_provisioning_calls_the_prefetch_after_writing_config(pm, monkeypatch, tmp_path):
    """The call site: it runs AFTER the config write, because the config decides WHICH embedder."""
    import runtime_safety as rs

    calls: list[str] = []
    cfg_path = tmp_path / "runtime_config.json"
    monkeypatch.setattr(rs, "CONFIG_FILE", cfg_path)
    monkeypatch.setattr(rs, "default_models_dir", lambda: tmp_path / "models")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "fake-model.gguf").write_bytes(b"GGUF")

    from install import hardware_probe, model_selector

    monkeypatch.setattr(hardware_probe, "probe_hardware", lambda: {
        "cpu_model": "test", "cpu_cores": 4, "cpu_physical": 4, "ram_gb": 16,
        "vram_gb": 0, "acceleration_backend": "none", "gpu_name": "none", "machine_tier": "potato",
    })
    monkeypatch.setattr(model_selector, "recommend_kit", lambda *a, **k: {
        "primary": {"name": "fake", "filename": "fake-model.gguf"},
        "aspect": "", "rationale": "test", "draft": None,
        "settings": {"n_ctx": 4096, "n_gpu_layers": 0, "n_threads": 4},
    })

    def _spy() -> bool:
        calls.append("prefetch")
        assert cfg_path.exists(), "prefetch ran BEFORE the config was written"
        return True

    monkeypatch.setattr(pm, "prefetch_embedding_model", _spy)

    assert pm.main([]) == 0
    assert calls == ["prefetch"], "the installer did not pre-fetch the embedding model"


def test_skip_embedder_flag_opts_out(pm, monkeypatch, tmp_path, capsys):
    import runtime_safety as rs

    cfg_path = tmp_path / "runtime_config.json"
    monkeypatch.setattr(rs, "CONFIG_FILE", cfg_path)
    monkeypatch.setattr(rs, "default_models_dir", lambda: tmp_path / "models")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "fake-model.gguf").write_bytes(b"GGUF")

    from install import hardware_probe, model_selector

    monkeypatch.setattr(hardware_probe, "probe_hardware", lambda: {
        "cpu_model": "test", "cpu_cores": 4, "cpu_physical": 4, "ram_gb": 16,
        "vram_gb": 0, "acceleration_backend": "none", "gpu_name": "none", "machine_tier": "potato",
    })
    monkeypatch.setattr(model_selector, "recommend_kit", lambda *a, **k: {
        "primary": {"name": "fake", "filename": "fake-model.gguf"},
        "aspect": "", "rationale": "test", "draft": None,
        "settings": {"n_ctx": 4096, "n_gpu_layers": 0, "n_threads": 4},
    })
    monkeypatch.setattr(pm, "prefetch_embedding_model",
                        lambda: pytest.fail("--skip-embedder still fetched the embedder"))

    assert pm.main(["--skip-embedder"]) == 0
    assert "--embedder-only" in capsys.readouterr().out  # tells the user how to get it later


# ── 3. the bootstrap scripts ──────────────────────────────────────────────────

@pytest.mark.parametrize("script", ["bootstrap.ps1", "bootstrap.sh"])
def test_bootstrap_has_an_explicit_embedder_step(script):
    """Both installers must fetch the embedder as a visible, named step — including --skip-model runs."""
    text = (REPO_ROOT / "install" / script).read_text(encoding="utf-8")
    assert "--embedder-only" in text, f"{script} never fetches the embedding model"
    assert "--skip-embedder" in text, f"{script} would fetch the embedder twice"
    assert "embedding model" in text.lower()
    assert "KEYWORD-ONLY" in text, f"{script} does not warn when the fetch fails"


# ── 4. the self-test ──────────────────────────────────────────────────────────

@pytest.fixture()
def selftest():
    """Load scripts/selftest.py by path (it is not an importable package)."""
    path = REPO_ROOT / "scripts" / "selftest.py"
    spec = importlib.util.spec_from_file_location("_layla_selftest_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod._RESULTS.clear()
    return mod


def test_selftest_reports_embedder_as_a_named_ok_check(selftest, vs, monkeypatch):
    monkeypatch.setattr(vs, "prefetch_embedder",
                        lambda **_kw: {"ok": True, "model": vs.EMBED_MODEL_STATIC,
                                       "detail": "", "already_loaded": False})

    selftest.check_embedder()

    named = [r for r in selftest._RESULTS if r[0] == "embedding model"]
    assert len(named) == 1, selftest._RESULTS
    assert named[0][1] == "ok"
    assert vs.EMBED_MODEL_STATIC in named[0][2]


def test_selftest_warns_loudly_when_the_embedder_is_missing(selftest, vs, monkeypatch):
    monkeypatch.setattr(vs, "prefetch_embedder",
                        lambda **_kw: {"ok": False, "model": "",
                                       "detail": "OSError: couldn't connect to huggingface.co",
                                       "already_loaded": False})

    selftest.check_embedder()

    named = [r for r in selftest._RESULTS if r[0] == "embedding model"]
    assert len(named) == 1, selftest._RESULTS
    name, status, detail = named[0]
    assert status == "warn", "a missing embedder must not fail the install, only warn"
    assert "KEYWORD-ONLY" in detail
    assert "--embedder-only" in detail, "the self-test must name the fix"
    # Degraded, not broken: warnings never fail the run.
    assert selftest._print_report() == 0


def test_selftest_does_not_blame_chroma_for_a_dead_embedder(selftest, vs, monkeypatch):
    monkeypatch.setattr(vs, "embedder_status",
                        lambda: {"status": "unavailable", "model": "", "detail": "offline"})
    monkeypatch.setattr(vs, "embed", lambda _t: pytest.fail("embed() called with a dead embedder"))

    selftest.check_rag()

    rag = [r for r in selftest._RESULTS if r[0] == "RAG / memory"]
    assert len(rag) == 1 and rag[0][1] == "warn", selftest._RESULTS
    assert "embedding model" in rag[0][2]
