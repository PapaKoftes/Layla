"""runtime_safety.is_valid_gguf guards against a truncated download or an HTML error
page saved as .gguf being treated as a ready model (UPG-35 robustness)."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import runtime_safety  # noqa: E402


def test_real_gguf_magic_accepted(tmp_path):
    p = tmp_path / "model.gguf"
    p.write_bytes(b"GGUF" + b"\x00" * 8192)  # magic + bulk (> size floor)
    assert runtime_safety.is_valid_gguf(p) is True


def test_html_error_page_rejected(tmp_path):
    p = tmp_path / "model.gguf"
    p.write_bytes(b"<!DOCTYPE html><html><body>404 Not Found</body></html>" + b" " * 4096)
    assert runtime_safety.is_valid_gguf(p) is False


def test_empty_and_tiny_rejected(tmp_path):
    empty = tmp_path / "e.gguf"
    empty.write_bytes(b"")
    tiny = tmp_path / "t.gguf"
    tiny.write_bytes(b"GGUF")  # correct magic but far too small to be a real model
    assert runtime_safety.is_valid_gguf(empty) is False
    assert runtime_safety.is_valid_gguf(tiny) is False


def test_missing_file_rejected(tmp_path):
    assert runtime_safety.is_valid_gguf(tmp_path / "nope.gguf") is False
