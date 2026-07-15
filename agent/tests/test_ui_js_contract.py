"""WATERTIGHT UI data-binding contract. These features have regressed repeatedly because an edit to a
JS file silently changed which field it reads (or dropped a wiring), and nothing failed. Each assertion
here pins a data-binding the UI depends on to the response field the backend actually returns. If an edit
breaks the binding, THIS test goes red instead of the user finding a blank/wrong panel.

Paired guards:
  • the backend side is locked by test_conversation_ui_contract.py (endpoints return these fields);
  • this file locks the UI side (the JS reads them). Both must agree or a test fails.

Deliberately substring-based so a normal refactor is fine but removing the binding is caught.
"""
import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"


def _read(rel: str) -> str:
    p = UI / rel
    assert p.exists(), f"UI file missing: {rel}"
    return p.read_text(encoding="utf-8")


def test_conversation_rail_reads_the_contract_fields():
    js = _read("components/conversations.js")
    # list: must read d.conversations (array) + s.title (+ fall back), and fetch /conversations
    assert "d.conversations" in js and "Array.isArray(d.conversations)" in js, "rail must read d.conversations[]"
    assert "s.title" in js, "rail render must read s.title (the chat name)"
    # load: must require d.ok + Array.isArray(d.messages), read m.role + m.content
    assert "/conversations/" in js and "/messages" in js
    assert "Array.isArray(d.messages)" in js, "load must guard on d.messages[]"
    assert "m.role" in js and "m.content" in js, "load must read m.role + m.content"
    # create: must read d.conversation.id
    assert "d.conversation" in js and ".conversation.id" in js.replace("d.conversation.id", ".conversation.id"), \
        "create must read d.conversation.id"


def test_reasoning_tree_summary_is_wired_into_addmsg():
    # The backend ships reasoning_tree_summary on every turn; addMsg's 8th param renders it. Both the
    # non-stream call and the streaming done-frame must pass it, or the collapsible silently never appears.
    app = _read("components/app.js")
    assert "_renderReasoningTreeSummary" in app, "app.js must import/use the reasoning-tree renderer"
    assert "reasoning_tree_summary" in app, "app.js must read reasoning_tree_summary from the payload"
    # non-stream addMsg call passes an 8th arg referencing reasoning_tree_summary
    assert re.search(r"addMsg\([^)]*reasoning_tree_summary", app, re.DOTALL), \
        "non-stream addMsg must pass reasoning_tree_summary as the 8th arg"
    # the renderer signature still has the 8th param
    cr = _read("components/chat-render.js")
    assert "reasoningTreeSummary" in cr, "addMsg signature must keep the reasoningTreeSummary param"


def test_cluster_status_reads_enabled_and_peer_count():
    # /cluster/status returns `enabled` + `peer_count` (NOT cluster_enabled / peers / node_role). All three
    # consumers must read `enabled` or the cluster card/badge shows Standalone/Disabled with a live cluster.
    for rel in ("core/compat.js", "components/cluster.js", "services/health.js"):
        js = _read(rel)
        assert "d.enabled" in js or "status.enabled" in js or "cluster.enabled" in js, \
            f"{rel} must read cluster `enabled` (not only cluster_enabled)"
    # The two consumers that take the peer COUNT from /cluster/status must read peer_count (cluster.js
    # gets its count from the separate /cluster/peers endpoint, so it's excluded here).
    for rel in ("core/compat.js", "services/health.js"):
        assert "peer_count" in _read(rel), f"{rel} must read cluster peer_count from /cluster/status"


def test_runtime_policy_pills_read_from_settings_not_health():
    # safe_mode/uncensored/nsfw_allowed/use_chroma live in /settings, not /health — reading them off health
    # rendered every pill 'false'. The runtime-options panel must fetch /settings.
    app = _read("components/app.js")
    m = re.search(r"runtime-options-panel[\s\S]{0,1200}", app)
    assert m, "runtime-options panel block not found"
    block = m.group(0)
    assert "/settings" in block, "runtime options must source policy flags from /settings"
    assert "s.safe_mode" in block, "policy pills must read safe_mode from the /settings response (var s)"


def test_models_panel_surfaces_coding_recommendation():
    # /setup/models returns recommended_coding_key + a per-entry recommended_coding flag; the panel must
    # render both so a coder isn't shown only the general recommendation.
    js = _read("components/models.js")
    assert "recommended_coding_key" in js, "models panel must render recommended_coding_key"
    assert "recommended_coding" in js, "models catalog must badge m.recommended_coding"


def test_message_render_uses_stored_aspect_on_reload():
    # A reloaded reply must keep the aspect chip of the aspect that produced it (m.aspect_id), not the
    # current session aspect — a past regression.
    js = _read("components/conversations.js")
    assert "m.aspect_id" in js, "reloaded messages must pass the stored m.aspect_id to addMsg"
