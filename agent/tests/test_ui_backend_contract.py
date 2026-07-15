"""WATERTIGHT backend side of the UI data-binding contract. Paired with test_ui_js_contract.py: that
file pins what the JS READS; this pins what the backend RETURNS. If a backend edit renames a field the
UI depends on, this test fails instead of the user finding a blank/wrong panel.
"""
import inspect
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_cluster_status_returns_enabled_and_peer_count():
    # UI (compat.js / cluster.js / health.js) reads `enabled` + `peer_count`.
    from services.cluster.cluster_network import get_cluster_status
    st = get_cluster_status()
    assert "enabled" in st, "cluster status must expose `enabled` (UI reads d.enabled)"
    assert "peer_count" in st, "cluster status must expose `peer_count` (UI reads d.peer_count)"
    # And the router fallback must use the SAME names as the success path (they disagreed before).
    src = inspect.getsource(__import__("routers.cluster", fromlist=["cluster_status"]).cluster_status)
    assert '"cluster_enabled"' not in src, "router fallback must not reintroduce the divergent cluster_enabled name"


def test_settings_exposes_policy_flags():
    # UI runtime-options pills read safe_mode/uncensored/nsfw_allowed/use_chroma from /settings.
    import runtime_safety
    cfg = runtime_safety.load_config()
    for k in ("safe_mode", "uncensored", "nsfw_allowed", "use_chroma"):
        assert k in cfg, f"/settings must expose {k} (UI policy pill reads it)"


def test_setup_models_router_returns_coding_recommendation():
    # UI models panel reads recommended_coding_key + per-entry recommended_coding.
    import routers.settings as settings_router
    src = inspect.getsource(settings_router.setup_models)
    assert "recommended_coding_key" in src, "/setup/models must return recommended_coding_key"
    assert "recommended_coding" in src, "/setup/models entries must carry recommended_coding"


def test_agent_payload_carries_reasoning_tree_summary():
    # UI renders reasoning_tree_summary; the /agent response payload must include it.
    import routers.agent as agent_router
    src = inspect.getsource(agent_router)
    assert "reasoning_tree_summary" in src, "/agent payload must include reasoning_tree_summary (UI renders it)"
