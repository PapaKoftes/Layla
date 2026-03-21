"""Risk-weighted geometry security tests: bridge URL policy and sandbox (no CAD deps, no network)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from layla.geometry.bridges import http_cad_bridge as bridge
from layla.geometry.executor import execute_program
from layla.geometry.schema import parse_program


def test_fetch_program_rejects_missing_bridge_url():
    r = bridge.fetch_program({}, path="v1/compile", body={})
    assert r["ok"] is False
    assert "geometry_external_bridge_url" in (r.get("error") or "")


def test_fetch_program_rejects_cross_host_url():
    """urljoin replaces base when path is absolute http(s); must not HTTP."""
    r = bridge.fetch_program(
        {"geometry_external_bridge_url": "http://example.com/api/"},
        path="http://evil.example/x",
        body={},
    )
    assert r["ok"] is False
    assert "allowlisted" in (r.get("error") or "").lower()


def test_fetch_program_rejects_localhost_without_explicit_flag():
    r = bridge.fetch_program(
        {
            "geometry_external_bridge_url": "http://127.0.0.1:9000/",
            "geometry_external_bridge_allow_insecure_localhost": False,
        },
        path="x",
        body={},
    )
    assert r["ok"] is False


def test_execute_program_rejects_workspace_outside_sandbox():
    with tempfile.TemporaryDirectory() as tmp:
        sand = Path(tmp) / "sandbox"
        sand.mkdir()
        outside = Path(tmp) / "outside"
        outside.mkdir()
        prog = parse_program({"version": "1", "ops": []})
        cfg = {"sandbox_root": str(sand)}
        r = execute_program(prog, str(outside), "out", cfg=cfg)
        assert r.get("ok") is False
        assert "sandbox" in (r.get("error") or "").lower()
