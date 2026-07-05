"""BL-156: kit marketplace — catalog, installed-status, install (plan/confirm), router."""
from __future__ import annotations

from services.skills import kit_catalog as kc


def test_catalog_shape():
    cat = kc.list_catalog()
    assert len(cat) >= 7
    ids = [k["id"] for k in cat]
    assert len(ids) == len(set(ids))
    for k in cat:
        assert k.get("name") and k.get("category")
        assert k.get("features") or k.get("git_url")


def test_installed_status_reads_flags():
    assert kc.installed_status({}) == {k["id"]: False for k in kc.list_catalog()}
    st = kc.installed_status({"mcp_client_enabled": True, "engineering_pipeline_enabled": True})
    assert st["coding-pro"] is True      # both its features enabled
    assert st["voice-companion"] is False


def test_install_plan_then_confirm(monkeypatch):
    # Plan by default — no config write.
    plan = kc.install_kit("voice-companion")
    assert plan["ok"] is True and plan["confirmed"] is False
    assert "voice" in plan["features"]
    assert any("faster-whisper" in (p.get("deps") or []) for p in plan["to_install"])

    # Confirm → applies (stub apply_setup so no real config write).
    import install.setup_profiles as sp
    monkeypatch.setattr(sp, "apply_setup", lambda p, f, save=True: {"setup_features": list(f)})
    done = kc.install_kit("voice-companion", confirm=True)
    assert done["ok"] is True and done["confirmed"] is True and "voice" in done["features"]


def test_unknown_kit():
    assert kc.install_kit("nope")["ok"] is False


def test_router():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import kits as kr
    app = FastAPI(); app.include_router(kr.router)
    client = TestClient(app)
    d = client.get("/kits/catalog").json()
    assert d["ok"] is True and len(d["kits"]) >= 7 and "installed" in d
    r = client.post("/kits/install", json={"kit_id": "privacy"}).json()
    assert r["ok"] is True and r["confirmed"] is False and "encryption" in r["features"]
