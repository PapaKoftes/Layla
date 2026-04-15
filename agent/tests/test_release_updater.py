"""Release ZIP layout helper tests."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from services.release_updater import assert_zip_extract_safe, find_agent_package_in_extract


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
