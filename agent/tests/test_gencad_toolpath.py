"""gencad_generate_toolpath: localhost policy and HTTP bridge (mocked)."""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_gencad_rejects_localhost_without_flag(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {
            "geometry_external_bridge_url": "http://127.0.0.1:9000/cam",
            "geometry_external_bridge_allow_insecure_localhost": False,
        },
    )
    from layla.tools import registry as reg

    r = reg.gencad_generate_toolpath(file="x.dxf")
    assert r.get("ok") is False
    assert "localhost" in (r.get("error") or "").lower() or "geometry_bridge" in (r.get("error") or "")


def test_gencad_posts_json_to_bridge(monkeypatch):
    import runtime_safety

    posted: list[tuple[str, dict]] = []

    class _Resp:
        status_code = 200
        text = '{"ok":true,"output_path":"/tmp/x.nc"}'

        def json(self):
            return {"ok": True, "output_path": "/tmp/x.nc"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            posted.append((str(url), dict(json or {})))
            return _Resp()

    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {
            "geometry_external_bridge_url": "https://example.com/api/cam/",
            "geometry_external_bridge_allow_insecure_localhost": False,
        },
    )
    import httpx

    monkeypatch.setattr(httpx, "Client", _Client)

    from layla.tools import registry as reg

    r = reg.gencad_generate_toolpath(file="part.dxf", strategy="contour", workspace_root="")
    assert r.get("ok") is True
    assert r.get("output_path") == "/tmp/x.nc"
    assert len(posted) == 1
    assert posted[0][1].get("op") == "gencad_generate_toolpath"
    assert posted[0][1].get("file") == "part.dxf"
    assert posted[0][1].get("strategy") == "contour"
