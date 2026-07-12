"""Regression: document-reader tools must enforce sandbox containment.

read_pptx historically used Path(path)+exists() only, missing the inside_sandbox()
gate its siblings read_pdf/read_docx/read_excel all have — allowing arbitrary
.pptx reads outside the configured sandbox_root. See audit finding #2.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _sandbox_at(root: Path):
    """Patch both the sandbox_core resolver and file_ops' effective-sandbox base."""
    from layla.tools import sandbox_core
    from layla.tools.impl import file_ops
    root = root.resolve()
    # inside_sandbox() consults sandbox_core._get_sandbox; _resolve_sandboxed_path
    # consults _effective_sandbox.path (falling back to _get_sandbox).
    return patch.multiple(
        sandbox_core,
        _get_sandbox=lambda: root,
    ), patch.object(file_ops._effective_sandbox, "path", str(root), create=True)


def test_read_pptx_rejects_path_outside_sandbox(tmp_path):
    from layla.tools.impl import file_ops

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "secrets" / "board.pptx"
    outside.parent.mkdir()
    outside.write_bytes(b"PK\x03\x04 not-a-real-deck")  # content is irrelevant; must be gated first

    core_patch, base_patch = _sandbox_at(sandbox)
    with core_patch, base_patch:
        res = file_ops.read_pptx(path=str(outside))

    assert res["ok"] is False
    assert "sandbox" in res["error"].lower()


def test_read_pptx_traversal_outside_sandbox(tmp_path):
    from layla.tools.impl import file_ops

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (tmp_path / "confidential.pptx").write_bytes(b"secret")

    core_patch, base_patch = _sandbox_at(sandbox)
    with core_patch, base_patch:
        res = file_ops.read_pptx(path="../confidential.pptx")

    assert res["ok"] is False
    assert "sandbox" in res["error"].lower()
