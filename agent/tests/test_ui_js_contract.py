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


def test_opening_right_panel_refreshes_the_active_tab():
    # REGRESSION: the Dashboard/Status tab is `active` by default in index.html, but its data-load hook
    # (refreshVersionInfo/refreshPlatformHealth/refreshRuntimeOptions via panelRefreshRouting) only fires
    # through showMainPanel(). toggleRightPanel() opened the panel WITHOUT calling showMainPanel, so the
    # default-active tab sat on "Version: loading..." / "Loading…" forever until the user clicked another
    # tab and back. The open branch must route the currently-active tab through showMainPanel.
    js = _read("components/input.js")
    m = re.search(r"function toggleRightPanel\(\)[\s\S]*?\n}", js)
    assert m, "toggleRightPanel not found"
    body = m.group(0)
    # the else/open branch must find the active page and route it through showMainPanel
    assert ".rcp-page.active" in body, "toggleRightPanel open branch must locate the active panel"
    assert "showMainPanel(main)" in body, "toggleRightPanel must refresh the active tab via showMainPanel on open"


def test_memory_hook_loads_the_pane_the_user_can_actually_see():
    # REGRESSION: workspaceSubtabRefresh.memory hardcoded refreshFileCheckpointsPanel() — the Checkpoints
    # pane, which is display:none by default. The default-VISIBLE pane ("About you") was never loaded, so
    # it sat on "Loading what Layla knows about you…" forever: it's already selected on arrival, so nothing
    # prompts the user to click it, and that click was its only loader. The hook must route to the ACTIVE
    # mem-subtab (showMemorySubTab owns per-subtab loading), defaulting to the visible 'about' pane.
    js = _read("components/workspace.js")
    m = re.search(r"memory:\s*function\s*\([\s\S]*?\n    \},", js)
    assert m, "workspaceSubtabRefresh.memory refresher not found"
    body = m.group(0)
    assert "showMemorySubTab" in body, "memory hook must route through showMemorySubTab, not hardcode one pane"
    assert "'about'" in body, "memory hook must default to the default-visible 'about' pane"
    assert "data-mem-sub" in body, "memory hook must read the ACTIVE mem-subtab"


def test_workspace_subtab_selectors_are_scoped_to_rcp_subs():
    # The memory sub-buttons reuse class .rcp-subtab but key off data-mem-sub, and they live INSIDE the
    # workspace page. An unscoped '.rcp-subtab' sweep matched them, read a null data-rcp-sub, and stripped
    # 'active' off "About you"; the same collision can make app.js resolve the workspace subtab to null and
    # route a refresh to nothing. Both selectors must be scoped with [data-rcp-sub].
    boot = _read("components/bootstrap.js")
    assert "querySelectorAll('.rcp-subtab[data-rcp-sub]')" in boot, \
        "_applyRcpWs must scope its subtab sweep to [data-rcp-sub] (memory sub-buttons collide otherwise)"
    app = _read("components/app.js")
    assert ".rcp-subtab[data-rcp-sub].active" in app, \
        "app.js workspace-subtab lookup must be scoped to [data-rcp-sub]"


# ── Structural guard for the "dead placeholder" bug class ───────────────────────────────────────────
# This class has now bitten three times (Status panel, Runtime & options, "About you"). The shape is
# always the same: a pane in the right control panel is VISIBLE by tab/subtab state, shows a spinner
# placeholder, and its loader is only reachable from a trigger that never fires for that pane. Tests
# that checked WHICH FIELDS a render fn reads all passed while the pane sat dead, because nothing
# checked that the loader is CALLED.
#
# Modals are excluded on principle, not convenience: a modal cannot become visible without its opener
# running, and the opener is its loader — so the failure mode is unreachable by construction.
#
# Every spinner pane in the right panel MUST be registered here with the loader that fills it and the
# route that fires it. Adding a new spinner pane without registering it FAILS this test — which is the
# point: the registration is where you're forced to answer "what actually loads this?"
_RIGHT_PANEL_SPINNER_PANES = {
    "platform-health":         ("refreshPlatformHealth",   "app.js panelRefreshRouting('status')"),
    "runtime-options-panel":   ("refreshRuntimeOptions",   "app.js panelRefreshRouting('status')"),
    "growth-capabilities-list": ("refreshGrowthDashboard", "app.js panelRefreshRouting('growth')"),
    "growth-types-list":       ("refreshGrowthDashboard",  "app.js panelRefreshRouting('growth')"),
    "growth-watcher-status":   ("refreshGrowthDashboard",  "app.js panelRefreshRouting('growth')"),
    "platform-models":         ("refreshPlatformModels",   "workspace.js workspaceSubtabRefresh.models"),
    "platform-knowledge":      ("refreshPlatformKnowledge", "workspace.js workspaceSubtabRefresh.knowledge"),
    "platform-plugins":        ("refreshPlatformPlugins",  "workspace.js workspaceSubtabRefresh.plugins"),
    "mem-about":               ("renderMemoryAbout",       "workspace.js workspaceSubtabRefresh.memory -> showMemorySubTab"),
    # The conversation rail is not tab-routed — it is always visible, so it must load at BOOT.
    "chat-rail-list":          ("_renderSessionList",      "conversations.js initConversations() at boot"),
}
# Loaders fired from a boot/init function rather than a tab route (always-visible panes).
_BOOT_LOADED = {"chat-rail-list"}
# Panes whose placeholder is deliberate instructional copy ("click to load"), NOT a promise that data
# is on its way. A user reading these knows to act; a spinner that never resolves lies to them.
_LAZY_BY_DESIGN = {"mem-browse-list", "file-checkpoints-list"}


def test_every_right_panel_spinner_pane_has_a_registered_loader():
    html = _read("index.html")
    # Any element in the right panel carrying a spinner-ish placeholder must be registered above.
    found = set()
    for m in re.finditer(r'id="([a-z0-9\-]+)"[^>]*>(?:\s*<span[^>]*>)?\s*Loading', html, re.IGNORECASE):
        found.add(m.group(1))
    # mem-about's placeholder lives on a child span with bespoke wording ("Loading what Layla knows
    # about you…") — exactly why the id-adjacent regex above missed it and the pane stayed dead.
    if 'id="mem-about"' in html:
        found.add("mem-about")
    unregistered = found - set(_RIGHT_PANEL_SPINNER_PANES) - _LAZY_BY_DESIGN - {
        # modals: visible only via their opener, which loads them (see rationale above)
        "settings-loading", "models-loading", "verify-review-body", "plan-viz-title",
    }
    assert not unregistered, (
        f"Spinner pane(s) {sorted(unregistered)} have no registered loader. A pane that shows "
        f"'Loading…' but is never loaded hangs forever. Register it in _RIGHT_PANEL_SPINNER_PANES "
        f"with the fn that fills it and the route that fires it, or mark it lazy-by-design."
    )


def test_registered_loaders_exist_and_are_reachable_from_a_route():
    # Each registered loader must (a) exist in the UI source, and (b) be referenced from the routing
    # table named in its registration — so the pane loads without the user having to guess a click.
    app = _read("components/app.js")
    ws = _read("components/workspace.js")
    routing = re.search(r"export function panelRefreshRouting[\s\S]*?\n}", app)
    assert routing, "panelRefreshRouting not found"
    subtab = re.search(r"export function workspaceSubtabRefresh[\s\S]*?\n}", ws)
    assert subtab, "workspaceSubtabRefresh not found"
    tables = routing.group(0) + subtab.group(0)
    all_js = "".join(_read(f"components/{n}") for n in
                     ("app.js", "workspace.js", "memory.js", "growth.js"))
    # Always-visible panes load at boot, not from a tab route. Pin that their init actually renders
    # them: initConversations() used to only bind search listeners, leaving the rail on "Loading…"
    # forever on a fresh page load, and tryLoadActiveConversationOnBoot() had zero callers so the
    # last conversation was never restored.
    conv = _read("components/conversations.js")
    init = re.search(r"export function initConversations\(\)[\s\S]*?\n}", conv)
    assert init, "initConversations not found"
    init_body = init.group(0)
    assert "_renderSessionList()" in init_body, \
        "initConversations must render the rail at boot, not only bind search listeners"
    assert "tryLoadActiveConversationOnBoot()" in init_body, \
        "initConversations must restore the active conversation at boot"
    assert "conversations.initConversations()" in _read("main.js"), "initConversations must run at boot"

    for pane, (loader, route) in _RIGHT_PANEL_SPINNER_PANES.items():
        assert loader in all_js + conv, f"{pane}: loader {loader}() does not exist"
        if pane in _BOOT_LOADED:
            continue  # asserted above against its init fn rather than a routing table
        if loader == "renderMemoryAbout":
            # routed indirectly: the memory hook calls showMemorySubTab, which owns per-subtab loading
            assert "showMemorySubTab" in tables, f"{pane}: memory route must reach {loader} ({route})"
        else:
            assert loader in tables, f"{pane}: {loader}() is not referenced from a routing table ({route})"


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
