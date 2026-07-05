"""BL-232: cross-project reasoning — networkx graph over projects by shared terms."""
from __future__ import annotations

import pytest

from services.memory import cross_project as cp

# three projects: A + B share a stack (fastapi, sqlite); C is unrelated (arduino, firmware)
_PROJECTS = [
    {"name": "webapp", "workspace_root": "/p/webapp"},
    {"name": "api", "workspace_root": "/p/api"},
    {"name": "robot", "workspace_root": "/p/robot"},
]
_MEM = {
    "/p/webapp": {"modules": {"fastapi_server": {}, "sqlite_store": {}}, "plan": {"goal": "build a fastapi webapp with sqlite"}, "files": {"server.py": {}, "database.py": {}}},
    "/p/api": {"modules": {"fastapi_routes": {}, "sqlite_models": {}}, "plan": {"goal": "a fastapi rest api backed by sqlite"}, "files": {"routes.py": {}, "models.py": {}}},
    "/p/robot": {"modules": {"arduino_firmware": {}, "servo_driver": {}}, "plan": {"goal": "control servos from arduino firmware"}, "files": {"firmware.ino": {}}},
}


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(cp, "_iter_projects", lambda: _PROJECTS)
    monkeypatch.setattr("services.memory.project_memory.load_project_memory",
                        lambda root: _MEM.get(Path(root).as_posix()), raising=False)


def test_graph_links_shared_stack():
    g = cp.build_project_graph(min_shared=2)
    assert g.number_of_nodes() == 3
    assert g.has_edge("webapp", "api")           # share fastapi + sqlite
    assert not g.has_edge("webapp", "robot")     # nothing in common


def test_related_projects():
    r = cp.related_projects("webapp", min_shared=2)
    assert r["ok"] is True and r["project"] == "webapp"
    assert r["related"] and r["related"][0]["project"] == "api"
    assert "fastapi" in r["related"][0]["shared_terms"] and "sqlite" in r["related"][0]["shared_terms"]


def test_clusters():
    c = cp.project_clusters(min_shared=2)
    assert c["project_count"] == 3
    assert any(set(cl) == {"webapp", "api"} for cl in c["clusters"])


def test_router():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import cross_project as cpr
    app = FastAPI(); app.include_router(cpr.router)
    client = TestClient(app)
    assert client.get("/intelligence/cross-project/related", params={"project": "api"}).json()["related"][0]["project"] == "webapp"
    assert client.get("/intelligence/cross-project/graph", params={"min_shared": 2}).json()["project_count"] == 3
