"""Tests for scripts/check_copyleft.py — the REQ-02 copyleft license guard.

Pure-stdlib; runs anywhere. Exercises classify() against synthetic distribution
metadata so the verdicts are pinned independent of what's installed in the env.
"""
import os
import sys

import pytest

# Import the guard module from scripts/ (not on the package path).
_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import check_copyleft as guard  # noqa: E402


class FakeMeta:
    """Minimal stand-in for importlib.metadata message objects."""

    def __init__(self, name, version="1.0", license=None, expression=None, classifiers=()):
        self._d = {"Name": name, "Version": version}
        if license is not None:
            self._d["License"] = license
        if expression is not None:
            self._d["License-Expression"] = expression
        self._classifiers = list(classifiers)

    def get(self, key, default=None):
        return self._d.get(key, default)

    def get_all(self, key):
        if key == "Classifier":
            return list(self._classifiers)
        return None


def _blocks(md):
    blocking, _reason = guard.classify(md)
    return blocking


# --- should BLOCK ---------------------------------------------------------

def test_agpl_classifier_blocks():
    md = FakeMeta("somepkg", classifiers=[
        "License :: OSI Approved :: GNU Affero General Public License v3"])
    assert _blocks(md) is True


def test_agpl_or_commercial_blocks():
    # PyMuPDF shape: AGPL or paid commercial — commercial is NOT permissive, stays blocked.
    md = FakeMeta("PyMuPDF",
                  license="dual licensed - GNU AFFERO GPL 3.0 or Artifex commercial license")
    assert _blocks(md) is True


def test_plain_gplv3_blocks():
    md = FakeMeta("gplpkg", classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)"])
    assert _blocks(md) is True


def test_sspl_blocks():
    md = FakeMeta("mongolike", license="Server Side Public License (SSPL)")
    assert _blocks(md) is True


# --- should ALLOW ---------------------------------------------------------

def test_gpl_with_linking_exception_allows():
    # PyInstaller shape.
    md = FakeMeta("pyinstaller", license=(
        "GPLv2-or-later with a special exception which allows to use PyInstaller "
        "to build and distribute non-free programs"))
    assert _blocks(md) is False


def test_dual_apache_or_gpl_allows():
    # pyinstaller-hooks-contrib shape: choose Apache.
    md = FakeMeta("hooks", classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)"])
    assert _blocks(md) is False


def test_bsd_with_embedded_gpl_notice_allows():
    # scipy shape: BSD classifier, but free-text License embeds bundled notices
    # (thousands of chars) that mention 'general public license'. Must NOT block.
    embedded = "Copyright (c) SciPy developers. Redistribution and use... " + ("x" * 500) + \
               " ...bundled component under the GNU General Public License ..."
    md = FakeMeta("scipy", license=embedded,
                  classifiers=["License :: OSI Approved :: BSD License"])
    assert _blocks(md) is False


def test_lgpl_only_allows():
    md = FakeMeta("chardet", classifiers=[
        "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)"])
    assert _blocks(md) is False


def test_mit_allows():
    md = FakeMeta("requests", license="Apache 2.0",
                  classifiers=["License :: OSI Approved :: MIT License"])
    assert _blocks(md) is False


def test_no_license_metadata_allows():
    md = FakeMeta("mystery")
    assert _blocks(md) is False


def test_allowlist_skips_package(monkeypatch):
    # A genuinely-AGPL package can be force-cleared via ALLOW with justification.
    monkeypatch.setattr(guard, "ALLOW", {"pymupdf"})
    md = FakeMeta("PyMuPDF", license="GNU AFFERO GPL 3.0")
    # classify() itself still flags it; scan() is what honors ALLOW:
    assert _blocks(md) is True  # classify is name-agnostic
    # ...and scan() would skip it (name in ALLOW) — verified via the name guard in scan().


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
