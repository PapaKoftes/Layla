"""
Locks the inference thread-count contract — services/llm/llm_gateway._auto_threads.

The potato thesis depends on using **physical** cores (not logical/HT) for llama.cpp,
leaving one free for the OS + FastAPI, capped where returns diminish. These tests pin
that behaviour so a future refactor can't silently regress to logical-core counts.
"""
from __future__ import annotations

import psutil

from services.llm import llm_gateway


def _patch_physical(monkeypatch, physical):
    # _auto_threads only calls psutil.cpu_count(logical=False); return `physical` for it.
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: physical)


def test_uses_physical_cores_and_leaves_one_free(monkeypatch):
    _patch_physical(monkeypatch, 8)
    assert llm_gateway._auto_threads() == 7  # 8 physical - 1


def test_caps_at_16(monkeypatch):
    _patch_physical(monkeypatch, 32)
    assert llm_gateway._auto_threads() == 16  # min(32 - 1, 16)


def test_never_below_one_on_single_core(monkeypatch):
    _patch_physical(monkeypatch, 1)
    assert llm_gateway._auto_threads() == 1  # max(1, min(0, 16))


def test_survives_psutil_returning_none(monkeypatch):
    _patch_physical(monkeypatch, None)  # can't detect -> falls back to os.cpu_count()
    assert llm_gateway._auto_threads() >= 1


def test_survives_psutil_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no psutil")

    monkeypatch.setattr(psutil, "cpu_count", boom)
    assert llm_gateway._auto_threads() >= 1
