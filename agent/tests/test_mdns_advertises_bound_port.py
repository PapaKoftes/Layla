"""mDNS must advertise the port the server actually BOUND, not the config request.

serve.py relocates off a busy 8000 and the desktop launcher takes --port; both now export LAYLA_PORT. Before,
start_service read only cfg["port"], so a relocated instance told LAN peers to call a dead port.
"""
import sys
import types
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_advertised_port_is_the_bound_port(monkeypatch):
    from services.cluster import mdns_discovery as md

    seen = {}

    class _Info:
        def __init__(self, *a, port=None, properties=None, **kw):
            seen["port"], seen["api_port"] = port, (properties or {}).get("api_port")

    class _ZC:
        def register_service(self, info):
            pass

        def close(self):
            pass

    fake = types.SimpleNamespace(ServiceInfo=_Info, Zeroconf=_ZC, ServiceBrowser=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "zeroconf", fake)
    monkeypatch.setattr(md, "_zeroconf_instance", None)
    monkeypatch.setattr(md, "_get_or_create_instance_id", lambda: "abcdef0123456789")
    monkeypatch.setattr(md, "_get_lan_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(md, "_get_available_models", lambda cfg: [])
    monkeypatch.setenv("LAYLA_PORT", "8123")
    try:
        md.start_service({"mdns_enabled": True, "port": 8000, "hardware_tier": "cpu"})
    finally:
        monkeypatch.setattr(md, "_zeroconf_instance", None)
        monkeypatch.setattr(md, "_browser", None, raising=False)
    assert seen, "PROBE BROKEN: ServiceInfo was never built"
    assert seen["port"] == 8123 and seen["api_port"] == "8123", seen


def test_serve_exports_the_bound_port():
    import ast

    tree = ast.parse((AGENT_DIR / "serve.py").read_text(encoding="utf-8"))
    sets = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Subscript) and ast.unparse(t) == "os.environ['LAYLA_PORT']" for t in n.targets)
            and ast.unparse(n.value) == "str(serve_port)"]
    assert sets, "serve.py must export the bound serve_port as LAYLA_PORT before uvicorn.run"
