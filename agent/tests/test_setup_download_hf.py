"""BL-159: /setup/download-hf — pull a GGUF from HuggingFace Hub by repo id."""
from __future__ import annotations


def _setup(monkeypatch, tmp_path):
    import huggingface_hub

    import routers.settings as st
    monkeypatch.setattr(st._rs, "load_config", lambda: {"models_dir": str(tmp_path)})

    def _fake_dl(repo_id, filename, local_dir):
        p = tmp_path / filename
        p.write_bytes(b"GGUF\x00\x00")
        return str(p)

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _fake_dl)
    return st


def test_download_hf_ok(monkeypatch, tmp_path):
    st = _setup(monkeypatch, tmp_path)
    r = st.setup_download_hf({"repo_id": "TheBloke/Mistral-GGUF", "filename": "mistral.Q4_K_M.gguf"})
    assert r["ok"] is True
    assert r["filename"] == "mistral.Q4_K_M.gguf"
    assert (tmp_path / "mistral.Q4_K_M.gguf").exists()


def test_download_hf_validation(monkeypatch, tmp_path):
    st = _setup(monkeypatch, tmp_path)
    assert st.setup_download_hf({"repo_id": "noslash", "filename": "x.gguf"})["ok"] is False
    assert st.setup_download_hf({"repo_id": "a/b", "filename": "x.txt"})["ok"] is False   # not .gguf
    assert st.setup_download_hf({"repo_id": "a/b", "filename": ""})["ok"] is False          # missing


def test_download_hf_traversal_is_sanitized(monkeypatch, tmp_path):
    # A path-y filename collapses to its basename — the file can only land in the models dir.
    st = _setup(monkeypatch, tmp_path)
    r = st.setup_download_hf({"repo_id": "a/b", "filename": "../../evil.gguf"})
    assert r["ok"] is True and r["filename"] == "evil.gguf"
    assert (tmp_path / "evil.gguf").exists()
