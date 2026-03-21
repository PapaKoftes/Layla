"""dependency_recovery: allowlist and structured payloads."""

from services.dependency_recovery import (
    missing_gguf_recovery,
    pip_install_command,
    try_pip_install,
)


def test_try_pip_install_rejects_non_allowlisted():
    r = try_pip_install(["definitely-not-a-real-layla-package-xyz"])
    assert r["ok"] is False
    assert "Refused" in (r.get("error") or "")


def test_pip_install_command_uses_python_m():
    s = pip_install_command(["faster-whisper"])
    assert "-m pip install" in s
    assert "faster-whisper" in s


def test_missing_gguf_recovery_structure(tmp_path):
    (tmp_path / "a.gguf").write_bytes(b"x")
    r = missing_gguf_recovery("missing.gguf", tmp_path)
    assert r["what_failed"]
    assert "missing.gguf" in r["model_filename_config"] or "missing" in r["model_filename_config"]
    assert "a.gguf" in (r.get("gguf_files_found") or [])
