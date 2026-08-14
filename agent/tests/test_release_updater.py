"""Release ZIP layout + verified no-admin update tests."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from services.infrastructure import release_updater as ru
from services.infrastructure.release_updater import assert_zip_extract_safe, find_agent_package_in_extract


def test_assert_zip_extract_safe_rejects_zip_slip(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "x")
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        with pytest.raises(ValueError, match="unsafe_zip_entry"):
            assert_zip_extract_safe(zf, tmp_path)


def test_find_agent_package_in_extract(tmp_path: Path) -> None:
    agent = tmp_path / "nested" / "Layla" / "agent"
    (agent / "services").mkdir(parents=True)
    (agent / "main.py").write_text("#", encoding="utf-8")
    (agent / "agent_loop.py").write_text("#", encoding="utf-8")
    found = find_agent_package_in_extract(tmp_path)
    assert found == agent.resolve()


# ── SHA256 verification (added 1.8.0) ─────────────────────────────────────────
class _FakeResp:
    def __init__(self, data: bytes):
        self._d = data
    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            d, self._d = self._d, b""
            return d
        d, self._d = self._d[:n], self._d[n:]
        return d
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _mock_urls(monkeypatch, url_to_bytes: dict[str, bytes]):
    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for key, data in url_to_bytes.items():
            if url.endswith(key):
                return _FakeResp(data)
        raise AssertionError(f"unexpected url {url}")
    monkeypatch.setattr(ru, "urlopen", fake_urlopen)


def test_verify_zip_sha256_matches(tmp_path, monkeypatch):
    z = tmp_path / "update-bundle-1.9.0.zip"
    z.write_bytes(b"payload-bytes")
    digest = hashlib.sha256(b"payload-bytes").hexdigest()
    assets = [{"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"}]
    _mock_urls(monkeypatch, {"SHA256SUMS.txt": f"{digest}  update-bundle-1.9.0.zip\n".encode()})
    assert ru._verify_zip_sha256(z, "update-bundle-1.9.0.zip", assets)["ok"] is True


def test_verify_zip_sha256_mismatch_refuses(tmp_path, monkeypatch):
    z = tmp_path / "update-bundle-1.9.0.zip"
    z.write_bytes(b"payload-bytes")
    assets = [{"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"}]
    _mock_urls(monkeypatch, {"SHA256SUMS.txt": b"deadbeef  update-bundle-1.9.0.zip\n"})
    r = ru._verify_zip_sha256(z, "update-bundle-1.9.0.zip", assets)
    assert not r["ok"] and "checksum_mismatch" in r["error"]


def test_verify_zip_sha256_no_sums_refuses(tmp_path, monkeypatch):
    z = tmp_path / "b.zip"; z.write_bytes(b"x")
    assert ru._verify_zip_sha256(z, "b.zip", [])["ok"] is False  # no SHA256SUMS.txt published -> refuse


def _bundle_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("agent/main.py", "# main\n")
        zf.writestr("agent/agent_loop.py", "# loop\n")
        zf.writestr("agent/services/__init__.py", "")
        zf.writestr("launcher/layla_launcher.py", "# launcher\n")
    return buf.getvalue()


def test_apply_update_installed_mode_writes_override_no_admin(tmp_path, monkeypatch):
    """Packaged update lands in <data>/app_override (no Program Files write), incl. the launcher."""
    data = tmp_path / "data"; data.mkdir()
    install = tmp_path / "ProgramFiles" / "Layla"; (install / "agent").mkdir(parents=True)
    bundle = _bundle_bytes()
    digest = hashlib.sha256(bundle).hexdigest()

    monkeypatch.setattr(ru, "is_installed_mode", lambda: True)
    monkeypatch.setattr(ru, "install_root", lambda: install)
    import runtime_safety as rs
    monkeypatch.setattr(rs, "load_config", lambda: {"github_repo": "PapaKoftes/Layla"})
    monkeypatch.setattr(rs, "resolve_layla_data_dir", lambda: data)
    from services.infrastructure import auto_updater
    monkeypatch.setattr(auto_updater, "check_update",
                        lambda *_a, **_k: {"ok": True, "update_available": True, "latest_version": "1.9.0"})
    monkeypatch.setattr(ru, "fetch_latest_release", lambda repo: {"assets": [
        {"name": "update-bundle-1.9.0.zip", "browser_download_url": "https://x/update-bundle-1.9.0.zip"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"},
    ]})
    _mock_urls(monkeypatch, {
        "update-bundle-1.9.0.zip": bundle,
        "SHA256SUMS.txt": f"{digest}  update-bundle-1.9.0.zip\n".encode(),
    })
    monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None, raising=False)

    r = ru.apply_release_update()
    assert r["ok"], r
    assert (data / "app_override" / "agent" / "main.py").read_text() == "# main\n"
    assert (data / "app_override" / "launcher" / "layla_launcher.py").is_file()
    assert not (install / "agent" / "main.py").exists()  # Program Files untouched (no admin needed)


def test_apply_update_aborts_on_bad_checksum(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    bundle = _bundle_bytes()
    monkeypatch.setattr(ru, "is_installed_mode", lambda: True)
    import runtime_safety as rs
    monkeypatch.setattr(rs, "load_config", lambda: {"github_repo": "PapaKoftes/Layla"})
    monkeypatch.setattr(rs, "resolve_layla_data_dir", lambda: data)
    from services.infrastructure import auto_updater
    monkeypatch.setattr(auto_updater, "check_update",
                        lambda *_a, **_k: {"ok": True, "update_available": True, "latest_version": "1.9.0"})
    monkeypatch.setattr(ru, "fetch_latest_release", lambda repo: {"assets": [
        {"name": "update-bundle-1.9.0.zip", "browser_download_url": "https://x/update-bundle-1.9.0.zip"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"},
    ]})
    _mock_urls(monkeypatch, {
        "update-bundle-1.9.0.zip": bundle,
        "SHA256SUMS.txt": b"0000000000000000000000000000000000000000000000000000000000000000  update-bundle-1.9.0.zip\n",
    })
    r = ru.apply_release_update()
    assert not r["ok"] and "checksum_mismatch" in r["error"]
    assert not (data / "app_override" / "agent" / "main.py").exists()  # nothing applied
