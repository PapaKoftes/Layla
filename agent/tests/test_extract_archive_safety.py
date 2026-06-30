"""Security tests for extract_archive (layla/tools/impl/file_ops.py).

Ensures archive extraction cannot escape the sandbox via path traversal or via
symlink members (a link pointing outside, with a later member written through
it). Uses the thread-local effective sandbox so no config is needed.
Pure stdlib (tarfile/zipfile) — runs on 3.14.
"""
import io
import sys
import tarfile
import zipfile
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.tools.impl.file_ops import extract_archive  # noqa: E402
from layla.tools.sandbox_core import set_effective_sandbox  # noqa: E402


def _make_tar(tar_path: Path, outside: Path):
    with tarfile.open(tar_path, "w") as t:
        data = b"safe content"
        ti = tarfile.TarInfo("safe.txt")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
        # symlink member pointing outside the extraction dir
        ln = tarfile.TarInfo("evil_link")
        ln.type = tarfile.SYMTYPE
        ln.linkname = str(outside)
        t.addfile(ln)
        # path-traversal member
        tv = tarfile.TarInfo("../escape.txt")
        tv.size = 4
        t.addfile(tv, io.BytesIO(b"pwn!"))


def test_tar_blocks_symlink_and_traversal(tmp_path):
    set_effective_sandbox(str(tmp_path))
    try:
        outside = tmp_path / "OUTSIDE"
        outside.mkdir()
        tarp = tmp_path / "mal.tar"
        _make_tar(tarp, outside)
        out = tmp_path / "out"
        res = extract_archive(str(tarp), str(out))
        assert res.get("ok") is True
        # benign file is extracted
        assert (out / "safe.txt").exists()
        # symlink member is NOT created (would be a sandbox-escape primitive)
        assert not (out / "evil_link").exists()
        assert not (out / "evil_link").is_symlink()
        # traversal member never escapes above `out`
        assert not (tmp_path / "escape.txt").exists()
    finally:
        set_effective_sandbox(None)


def test_zip_blocks_traversal(tmp_path):
    set_effective_sandbox(str(tmp_path))
    try:
        zp = tmp_path / "mal.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("ok.txt", "fine")
            z.writestr("../escape.txt", "pwn")
        out = tmp_path / "z"
        res = extract_archive(str(zp), str(out))
        assert res.get("ok") is True
        assert (out / "ok.txt").exists()
        assert not (tmp_path / "escape.txt").exists()
    finally:
        set_effective_sandbox(None)


def test_outside_sandbox_rejected(tmp_path):
    # An archive path outside the sandbox is refused before extraction.
    set_effective_sandbox(str(tmp_path / "sandbox"))
    (tmp_path / "sandbox").mkdir()
    try:
        elsewhere = tmp_path / "elsewhere.tar"
        with tarfile.open(elsewhere, "w") as t:
            ti = tarfile.TarInfo("a.txt")
            ti.size = 1
            t.addfile(ti, io.BytesIO(b"x"))
        res = extract_archive(str(elsewhere), str(tmp_path / "sandbox" / "out"))
        assert res.get("ok") is False
        assert "sandbox" in str(res.get("error", "")).lower()
    finally:
        set_effective_sandbox(None)
