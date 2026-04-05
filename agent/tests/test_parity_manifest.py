"""Verify docs/parity_manifest.yaml anchors still exist (guards doc drift vs code)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = REPO_ROOT / "docs" / "parity_manifest.yaml"
AGENT_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module", autouse=True)
def _agent_path():
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    yield


def test_parity_manifest_file_exists():
    assert MANIFEST.is_file(), f"Missing {MANIFEST}"


def test_parity_manifest_paths_exist():
    raw = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    for entry in raw.get("paths") or []:
        rel = entry.get("relpath")
        assert rel, entry
        p = REPO_ROOT / rel
        assert p.is_file(), f"parity_manifest path missing: {rel}"


def test_parity_manifest_symbols_importable():
    raw = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    for entry in raw.get("symbols") or []:
        mod = entry.get("module")
        attr = entry.get("attr")
        assert mod and attr, entry
        m = importlib.import_module(mod)
        assert hasattr(m, attr), f"{mod}.{attr} missing"
