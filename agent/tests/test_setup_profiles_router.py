"""TestClient checks for the W-S onboarding router (routers/setup_profiles.py)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import setup_profiles as sp

_app = FastAPI()
_app.include_router(sp.router)
client = TestClient(_app)


def test_get_setup_profiles():
    r = client.get("/setup/profiles")
    assert r.status_code == 200
    d = r.json()
    assert len(d["profiles"]) >= 6 and len(d["features"]) >= 13
    assert any(p["id"] == "minimal" for p in d["profiles"])
    assert any(f["id"] == "encryption" for f in d["features"])


def test_install_plan_without_confirm_does_not_install():
    r = client.post("/setup/feature/install", json={"feature_id": "voice"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["confirmed"] is False
    assert "faster-whisper" in d["plan"]["deps"]


def test_install_unknown_feature():
    r = client.post("/setup/feature/install", json={"feature_id": "nope"})
    assert r.json()["ok"] is False


def test_apply_persists_selection(monkeypatch):
    # Avoid touching the real config file: stub apply_setup.
    import install.setup_profiles as spm
    import runtime_safety

    # **kw: /setup/apply now passes exclude_features (the features whose packages are missing
    # are deferred rather than switched on) — see test_setup_wizard_sequence.py.
    monkeypatch.setattr(
        spm, "apply_setup",
        lambda p, f, save=True, **kw: {"setup_profiles": list(p), "setup_features": ["mcp"] if "coding" in p else []},
    )
    # `features` is now READ BACK from the effective config rather than echoed out of
    # apply_setup's return value, so this must stub load_config too — otherwise the assertion
    # is really about the developer's own runtime_config.json.
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"mcp_client_enabled": True})
    r = client.post("/setup/apply", json={"profiles": ["coding"]})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["profiles"] == ["coding"] and "mcp" in d["features"]


def test_setup_state_reports_enabled_features(monkeypatch):
    # Stub the live config so the route reflects a known flag state.
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"mcp_client_enabled": True})
    r = client.get("/setup/state")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert "mcp" in d["enabled_features"]
    assert "voice" not in d["enabled_features"]  # flags not set
