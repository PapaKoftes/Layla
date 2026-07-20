"""Every navigation entry must reach a panel that exists. The sibling guard to test_ui_element_contract.

WHY THIS FILE EXISTS. Before BL-390, 21 of the app's panels had exactly one door: the command palette.
This slice gave them a grouped home in the sidebar. That trade is only worth making if the new entries
actually arrive somewhere — and the dispatcher makes a broken entry INVISIBLE:

    // core/actions.js::_exec
    const fn = _actions[name];
    if (typeof fn === 'function') { ... return true; }
    if (typeof window[name] === 'function') { ... return true; }
    console.debug('[actions] unknown action:', name);   // <- a typo'd nav button lands HERE
    return false;

A `console.debug` and a `return false`. The button highlights on hover, depresses on click, and does
nothing, forever, with no error in the console anybody reads. That is precisely how the six features in
test_ui_element_contract.py died, one layer up: there the JS reached for markup that did not exist, here
the markup reaches for a handler that does not exist. Same failure, same silence, same test discipline.

The three cards that advertised "click to open Growth"/"click to open Cluster" are the proof this is not
hypothetical: `_rcpAliases` maps both onto `status`, so all three landed on the Dashboard while promising
a panel that is `display:none` and can never be activated.

WHAT IT PINS
  1. every data-action in the grouped nav resolves to a real registered action;
  2. that action is bound to a function its component genuinely exports;
  3. the panels DRIVEN AND FOUND BROKEN are not surfaced (rule: surfacing a dead panel converts a hidden
     defect into an advertised one);
  4. gated entries declare a gate the UI can render;
  5. no command-palette entry was removed — this slice adds a door, it never takes one away.
"""
import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
INDEX = UI / "index.html"
MAIN = UI / "main.js"


def _html() -> str:
    return INDEX.read_text(encoding="utf-8", errors="replace")


def _rendered_html() -> str:
    """index.html with <!-- comments --> stripped.

    Assertions about what the USER READS must not match prose in a comment — including a comment
    that quotes the very string it forbids, which is how this file's own explanation of the
    Autonomous fix first tripped its own guard.
    """
    return re.sub(r"<!--.*?-->", "", _html(), flags=re.DOTALL)


def _main() -> str:
    return MAIN.read_text(encoding="utf-8", errors="replace")


def _sidebar_groups_block() -> str:
    """The <nav id="sidebar-groups"> ... </nav> markup, isolated."""
    m = re.search(r'<nav class="sidebar-groups" id="sidebar-groups".*?</nav>', _html(), re.DOTALL)
    assert m, (
        "the grouped feature nav (<nav id=\"sidebar-groups\">) was not found in index.html. "
        "If it was renamed, update this test — if it was DELETED, 21 panels just lost their only "
        "non-keyboard door and went back to being palette-only."
    )
    return m.group(0)


def _registered_actions() -> dict[str, str]:
    """action name -> the expression it is bound to, from every registerActions({...}) in main.js."""
    src = _main()
    out: dict[str, str] = {}
    for block in re.finditer(r"registerActions\(\{(.*?)\n  \}\);", src, re.DOTALL):
        for name, expr in re.findall(r"^\s*([A-Za-z0-9_]+)\s*:\s*([^,\n]+),", block.group(1), re.M):
            out[name] = expr.strip()
    return out


def _window_actions() -> set[str]:
    """Compat fallback: _exec also accepts window.<name>. Anything assigned there is reachable."""
    names: set[str] = set()
    for f in UI.rglob("*.js"):
        if "vendor" in f.parts or "node_modules" in f.parts:
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        names |= set(re.findall(r"window\.([A-Za-z0-9_]+)\s*=", src))
    return names


def _nav_entries() -> list[tuple[str, str]]:
    """[(action, full button markup)] for every button in the grouped nav."""
    return [
        (m.group(1), m.group(0))
        for m in re.finditer(r'<button[^>]*data-action="([^"]+)"[^>]*>', _sidebar_groups_block())
    ]


# ── 1. every entry resolves ────────────────────────────────────────────────────────────────────────
def test_every_grouped_nav_entry_resolves_to_a_registered_action():
    """A nav button whose action is not registered is a button that silently does nothing."""
    registered = set(_registered_actions())
    windowed = _window_actions()
    entries = _nav_entries()
    assert entries, "the grouped nav rendered no buttons — the navigation is empty"
    dead = []
    for action, _markup in entries:
        for name in action.split():
            if name not in registered and name not in windowed:
                dead.append(name)
    assert not dead, (
        "grouped-nav entr(ies) point at action(s) that are registered NOWHERE:\n"
        + "\n".join(f"  data-action=\"{n}\"" for n in sorted(set(dead)))
        + "\n\ncore/actions.js::_exec will console.debug and return false — the button will look "
        "alive and do nothing. Register the action in main.js, or fix the name."
    )


# ── 2. the action reaches a function its component exports ─────────────────────────────────────────
def test_grouped_nav_actions_are_bound_to_functions_that_exist():
    """`openFoo: foo.openFoo` is only real if components/foo.js actually exports openFoo."""
    registered = _registered_actions()
    src = _main()
    # import * as <alias> from './components/<file>.js'
    aliases = dict(re.findall(r"import \* as ([A-Za-z0-9_]+) from '\./components/([A-Za-z0-9_\-]+)\.js'", src))
    broken = []
    for action, _markup in _nav_entries():
        for name in action.split():
            expr = registered.get(name)
            if not expr:
                continue  # covered by the previous test (window.* fallback)
            m = re.fullmatch(r"([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)", expr)
            if not m:
                continue  # inline arrow / non-module binding — nothing static to verify
            alias, fn = m.group(1), m.group(2)
            comp = aliases.get(alias)
            if not comp:
                broken.append(f"{name} -> {expr} (no import alias '{alias}')")
                continue
            path = UI / "components" / f"{comp}.js"
            if not path.exists():
                broken.append(f"{name} -> {expr} (components/{comp}.js does not exist)")
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            if not re.search(rf"export\s+(async\s+)?function\s+{re.escape(fn)}\b", body) and not re.search(
                rf"export\s*\{{[^}}]*\b{re.escape(fn)}\b", body, re.DOTALL
            ):
                broken.append(f"{name} -> {expr} (components/{comp}.js does not export {fn})")
    assert not broken, (
        "grouped-nav action(s) bound to a function that does not exist:\n"
        + "\n".join(f"  {b}" for b in broken)
        + "\n\nThe import would throw at module load, taking the whole UI with it — or, if the alias "
        "resolves to undefined, the click silently no-ops."
    )


# ── 3. broken panels stay unsurfaced ───────────────────────────────────────────────────────────────
def test_panels_proven_broken_are_not_in_the_nav():
    """DO NOT SURFACE A FEATURE THAT DOES NOT WORK.

    Both were driven on an isolated instance before this slice shipped:

    * Missions — POST /mission returns 500 'mission creation failed (plan empty or planner error)'.
      create_mission is the ONLY producer of a mission, so the board can never hold a row on this
      configuration. It renders beautifully and stays empty forever.
    * German — POST /german/correct found 0 of 6 planted errors at the default B1 level and returns
      zero rules active at A1; its flashcard section reads a table no product code path can write
      (no caller anywhere POSTs /german/flashcards). The Language tutor, which works and whose
      '+ add card' actually writes, is surfaced in its place.

    Both remain reachable from the command palette — this test forbids PROMOTING them, not keeping
    them. If either is genuinely fixed, delete its entry here in the same commit as the fix.
    """
    block = _sidebar_groups_block()
    for action, why in [
        ("openMissions", "POST /mission 500s — the board can never be populated"),
        ("openGerman", "the corrector finds 0/6 real errors and the flashcard section has no writer"),
    ]:
        assert action not in block, (
            f"{action} was added to the grouped nav, but the panel is BROKEN: {why}. "
            "Surfacing it turns a hidden defect into an advertised one. Fix the panel first, then "
            "surface it and delete this assertion."
        )


# ── 4. gated entries carry a gate ──────────────────────────────────────────────────────────────────
def test_gated_nav_entries_declare_a_gate_the_ui_can_render():
    """A gated entry ships with the gate VISIBLE and a real path — never a bare feature name.

    SHAPE ONLY. This says a gate can be RENDERED, not that it is TRUE — see the mapping test
    below, which is the one with teeth.
    """
    block = _sidebar_groups_block()
    gated = re.findall(r'<button[^>]*class="[^"]*nav-gated[^"]*"[^>]*>.*?</button>', block, re.DOTALL)
    assert gated, (
        "no gated entries found. Sync is gated on syncthing_api_key — a credential for a separate "
        "program Layla cannot generate — so if it were surfaced ungated the user gets a dead click "
        "with no explanation. (Deliberate is deliberately UNGATED: it has no real gate. If Sync was "
        "genuinely fixed or removed, update this test in the same commit and say why.)"
    )
    for btn in gated:
        assert "data-gate-feature=" in btn or "data-gate-key=" in btn, (
            f"a .nav-gated entry declares no gate source, so nothing can explain why it is off:\n  {btn}"
        )
        assert "nav-gate-badge" in btn, f"a .nav-gated entry has no badge element to mark it locked:\n  {btn}"


# ── 4b. THE GATE TAG MUST NAME A FLAG THE PANEL'S OWN CODE PATH READS ──────────────────────────────
#
# WHY THIS EXISTS, AND WHY THE TESTS ABOVE ARE NOT ENOUGH.
# The first version of this file asserted only that a gated entry CARRIED a data-gate-feature and a
# badge, and that the copy was fetched rather than hardcoded — i.e. gate SHAPE. A verifier repointed
# Deliberate at data-gate-feature="fabrication", an unrelated CAD/geometry feature, and all eight
# tests still passed. Shape said nothing about truth, and two entries shipped with tags naming
# subsystems their panels never touch:
#
#   Deliberate  data-gate-feature="multi_agent"  -> /debate reads NO multi_agent flag.  Driven:
#               gate-status said multi_agent off, POST /debate returned ok:true with two aspects.
#               The rendered remedy (lock the key / disable auto_tune) was harmful on a CPU tier.
#   Sync        data-gate-feature="remote"       -> /sync/* reads NO remote_enabled.  Driven:
#               /sync/status said "syncthing_api_key not set" while the badge said "rotate a tunnel
#               token" — a real security side effect that does not enable sync.
#
# Inheriting the palette's `feature:` tag was the mechanism. There the tag only HID a row and claimed
# nothing; here it becomes a paragraph of confident, specific, actionable prose. That is what makes a
# wrong mapping load-bearing, and it is why the fix has to pin the MAPPING, not the markup.
#
# HOW IT PROVES THE MAPPING. For each gated entry it resolves, statically:
#     button -> data-action -> main.js registerActions -> components/<panel>.js
#           -> the route URLs that component fetches
#           -> the router module serving each route
#           -> that router's local-import closure
# and requires at least one flag the gate tag OWNS to be genuinely READ (`.get("k")` / `["k"]`)
# somewhere in that closure. A tag naming a flag no part of the panel reads FAILS. Nothing here is
# keyed to Deliberate or Sync by name, so a NEW mis-tagged entry is caught without editing this file.
#
# ON THE CLOSURE DEPTH, HONESTLY. Depth 2 = the router plus what it directly imports. Measured on
# this tree: at depth 2 syncthing_api_key resolves (syncthing_sync.py:49) and debate_max_workers
# resolves (debate_engine.py:193), while BOTH shipped mis-tags are correctly rejected. At depth 3 the
# `remote` mis-tag would start PASSING on a false hit — runtime_safety.py:216 reads remote_enabled in
# generic config-invariant machinery that every router transitively reaches. So the depth is not
# arbitrary: it is the point past which "reachable" stops meaning "used by this panel". The trade is
# deliberate — a false FAILURE here is loud and one comment away from resolution, a false PASS is the
# exact silent defect this test exists to catch.

ROUTERS = Path(__file__).resolve().parent.parent / "routers"
AGENT_ROOT = Path(__file__).resolve().parent.parent
_CLOSURE_DEPTH = 2

_IMPORT_RE = re.compile(
    r"^[ \t]*(?:from\s+([A-Za-z0-9_.]+)\s+import\s+([^\n#]+)|import\s+([A-Za-z0-9_.]+))", re.M)


def _local_module_path(mod: str) -> Path | None:
    """agent-local module -> file. Third-party/stdlib imports resolve to None and are skipped."""
    p = AGENT_ROOT / (mod.replace(".", "/") + ".py")
    if p.exists():
        return p
    pkg = AGENT_ROOT / mod.replace(".", "/") / "__init__.py"
    return pkg if pkg.exists() else None


def _imports_of(path: Path) -> set[str]:
    src = path.read_text(encoding="utf-8", errors="replace")
    out: set[str] = set()
    for m in _IMPORT_RE.finditer(src):
        mod = m.group(1) or m.group(3)
        if not mod or mod == "__future__":
            continue
        out.add(mod)
        # `from services.infrastructure import syncthing_sync` — the SUBMODULE is the real
        # dependency, and it is where the config key is read. Resolving only the package here
        # was why an early draft of this resolver found zero reads for the sync path.
        for name in re.split(r"[,\s()]+", m.group(2) or ""):
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
                out.add(f"{mod}.{name}")
    return out


def _module_closure(start: Path, depth: int = _CLOSURE_DEPTH) -> set[Path]:
    """`start` plus the agent-local modules reachable from it within `depth` import hops.

    Import-level, not call-level: this codebase imports lazily inside functions all over, so a
    function-precise graph would need a resolver far more fragile than the thing it guards.
    Module granularity OVER-approximates what the panel reaches, which biases toward passing —
    hence the bounded depth, and hence the teeth test below that pins the discrimination.

    BREADTH-first, deliberately. Depth-first would record a module at whatever depth it happened
    to be reached FIRST and never revisit it, so a module that is both a direct import (depth 1)
    and a grand-import (depth 2) could get filed at 2 and never expanded — silently truncating a
    branch and turning a real gate into a false failure. BFS reaches every module at its true
    minimum depth.
    """
    level = {start}
    seen = {start}
    for _ in range(depth):
        nxt: set[Path] = set()
        for path in level:
            for mod in _imports_of(path):
                p = _local_module_path(mod)
                if p and p not in seen:
                    seen.add(p)
                    nxt.add(p)
        if not nxt:
            break
        level = nxt
    return seen


def _route_table() -> dict[str, Path]:
    """'/sync/status' -> routers/sync.py, for every route the app declares.

    Every router is mounted in main.py with no extra prefix, so a router's own
    APIRouter(prefix=...) plus its decorator path IS the URL the browser calls.
    """
    table: dict[str, Path] = {}
    for f in sorted(ROUTERS.glob("*.py")):
        src = f.read_text(encoding="utf-8", errors="replace")
        pm = re.search(r"APIRouter\([^)]*prefix\s*=\s*['\"]([^'\"]*)['\"]", src, re.DOTALL)
        prefix = pm.group(1) if pm else ""
        for m in re.finditer(r"@router\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]", src):
            table.setdefault(prefix + m.group(2), f)
    return table


def _component_of_action(action: str) -> Path | None:
    """data-action -> the components/*.js file that implements it."""
    src = _main()
    aliases = dict(re.findall(
        r"import \* as ([A-Za-z0-9_]+) from '\./components/([A-Za-z0-9_\-]+)\.js'", src))
    expr = _registered_actions().get(action)
    if not expr:
        return None
    m = re.fullmatch(r"([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)", expr)
    if not m:
        return None
    comp = aliases.get(m.group(1))
    if not comp:
        return None
    path = UI / "components" / f"{comp}.js"
    return path if path.exists() else None


def _routes_called_by(component: Path) -> list[str]:
    """The declared routes this component fetches. Non-route '/...' literals are ignored."""
    src = component.read_text(encoding="utf-8", errors="replace")
    table = _route_table()
    found = []
    for lit in re.findall(r"['\"`](/[A-Za-z0-9_\-/]*)['\"`]", src):
        if lit in table and lit not in found:
            found.append(lit)
    return found


def _key_is_read_in(paths, key: str) -> list[str]:
    """Where `key` is READ as config — `.get("key")` or `["key"]` — in the given files.

    A bare mention is NOT a read, and the difference is load-bearing. Both mis-tagged flags
    appear as plain strings in modules the panels reach: auto_tune.py lists
    multi_agent_orchestration_enabled in PROFILE_KEYS and as a dict-literal default, and
    runtime_safety.py sets it in a defaults dict. Those are declarations ABOUT the key, not the
    panel consulting it. Matching them would have made this test agree with the mis-tag.
    """
    pat = re.compile(r"(?:\.get\(\s*|\[\s*)['\"]" + re.escape(key) + r"['\"]")
    hits = []
    for p in sorted(paths):
        src = p.read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(src):
            hits.append(f"{p.relative_to(AGENT_ROOT)}:{src[:m.start()].count(chr(10)) + 1}")
    return hits


def _flags_owned_by_gate(btn_markup: str) -> tuple[str, list[str]]:
    """(gate label, config keys the gate owns) for a gated button."""
    fid = re.search(r'data-gate-feature="([^"]+)"', btn_markup)
    kid = re.search(r'data-gate-key="([^"]+)"', btn_markup)
    if kid:
        return (f'data-gate-key="{kid.group(1)}"', [kid.group(1)])
    from install.setup_profiles import feature_by_id

    feat = feature_by_id(fid.group(1)) if fid else None
    assert feat, (
        f'data-gate-feature="{fid.group(1) if fid else "?"}" is not a feature in FEATURE_MANIFEST, '
        "so /setup/gate-status can never resolve it and the entry renders 'status unknown' forever."
    )
    return (f'data-gate-feature="{fid.group(1)}"', list((feat.get("flags") or {}).keys()))


def _gated_entries() -> list[tuple[str, str]]:
    """[(action, markup)] for every gated button in the grouped nav."""
    out = []
    for btn in re.findall(
        r'<button[^>]*class="[^"]*nav-gated[^"]*"[^>]*>.*?</button>', _sidebar_groups_block(), re.DOTALL
    ):
        m = re.search(r'data-action="([^"]+)"', btn)
        if m:
            out.append((m.group(1), btn))
    return out


def _resolve_gate(action: str, markup: str):
    """(gate_label, flags, routes, closure) — or raises with the reason it could not be checked."""
    component = _component_of_action(action)
    assert component, (
        f'gated nav entry data-action="{action}" does not resolve to a components/*.js file, so '
        "its gate CANNOT be verified against the code the panel runs. An unverifiable gate is not "
        "allowed to ship: either bind the action to a component module, or remove the gate tag."
    )
    routes = _routes_called_by(component)
    assert routes, (
        f"gated nav entry {action} -> {component.name} calls no route this app declares, so there "
        "is no backend path whose flags could justify a gate. If the panel is pure client-side it "
        "has no gate — remove the tag rather than describing a lock that cannot exist."
    )
    label, flags = _flags_owned_by_gate(markup)
    assert flags, f"{label} on {action} owns no config keys, so it can never be satisfied or explained."
    closure: set[Path] = set()
    table = _route_table()
    for r in routes:
        closure |= _module_closure(table[r])
    return label, flags, routes, closure


def test_every_gate_tag_names_a_flag_the_panel_actually_reads():
    """THE MAPPING TEST. A gate must name the subsystem the panel truly depends on.

    Generic over the DOM: add a new .nav-gated entry with a plausible-but-wrong tag and this fails
    without anyone editing this file.
    """
    entries = _gated_entries()
    assert entries, "no gated nav entries to verify — if gating was removed entirely, say so here."
    failures = []
    for action, markup in entries:
        label, flags, routes, closure = _resolve_gate(action, markup)
        read = {f: _key_is_read_in(closure, f) for f in flags}
        if not any(read.values()):
            failures.append(
                f"\n  {action} is tagged {label}, which owns {flags}.\n"
                f"    The panel calls: {routes}\n"
                f"    Reached modules ({len(closure)}, depth {_CLOSURE_DEPTH}) read NONE of those keys.\n"
                f"    => The lock names a subsystem this panel does not use. Either tag it with a "
                f"flag its own path reads, or — if it has no real gate — remove the gate tag and "
                f"ship it ungated. Softer copy is not the fix; the sign is on the wrong door."
            )
    assert not failures, (
        "gate tag(s) name a flag the panel's code path never reads:" + "".join(failures)
        + "\n\nThis is the defect that shipped 'locked' on a panel that ran fine, with a remedy that "
        "was harmful to follow. Verify by DRIVING: a panel marked locked must actually be blocked."
    )


def test_the_mapping_test_can_tell_a_wrong_tag_from_a_right_one():
    """TEETH. Proves the resolver above discriminates instead of passing everything.

    A reachability check that answers 'yes' for every key would make the mapping test decorative —
    which is precisely how the shape-only tests passed a Deliberate entry repointed at an unrelated
    CAD feature. So: pin that the two flags actually shipped as mis-tags are NOT found on the paths
    that carried them, and that a real flag on the same path IS.
    """
    table = _route_table()
    for route in ("/debate", "/sync/status"):
        assert route in table, (
            f"{route} is no longer a declared route, so this teeth check cannot run. It is the "
            "only thing proving the mapping test discriminates rather than passing everything — "
            "re-point it at the renamed route, do not delete it."
        )
    debate = _module_closure(table["/debate"])
    sync = _module_closure(table["/sync/status"])

    assert _key_is_read_in(debate, "debate_max_workers"), (
        "the resolver found no read of debate_max_workers on the /debate path, but debate_engine.py "
        "reads it. The closure has stopped finding genuine reads — every gate check is now vacuous."
    )
    assert _key_is_read_in(sync, "syncthing_api_key"), (
        "the resolver found no read of syncthing_api_key on the /sync path, but syncthing_sync.py "
        "reads it. The closure has stopped finding genuine reads."
    )
    for path, closure, key, story in [
        ("/debate", debate, "multi_agent_orchestration_enabled",
         "shipped as Deliberate's gate; /debate returned ok:true with the flag off"),
        ("/sync/status", sync, "remote_enabled",
         "shipped as Sync's gate; /sync/status blamed syncthing_api_key while the badge said "
         "rotate a tunnel token"),
        ("/debate", debate, "geometry_frameworks_enabled",
         "the unrelated CAD flag a verifier retagged Deliberate with, under which all 8 shape "
         "tests still passed"),
    ]:
        hits = _key_is_read_in(closure, key)
        assert not hits, (
            f"the resolver now reports '{key}' as read on the {path} path ({hits}) — {story}. "
            "Either the code genuinely changed (then this pin is stale: verify by driving the panel "
            "and update it), or the closure widened until it reaches everything and the mapping test "
            "lost its teeth. Do not relax this without checking which."
        )


def test_gate_copy_is_not_hardcoded_in_the_ui():
    """The reason text must come from install.feature_status via /setup/gate-status.

    Hardcoding it in JS creates a third owner list that drifts the moment a gate moves — the exact
    failure the feature_status registry was built to end. The old Autonomous panel copy ("Requires
    autonomous_mode") is the anti-pattern: a variable name, hardcoded, explaining nothing.
    """
    nav_js = (UI / "components" / "nav-groups.js").read_text(encoding="utf-8", errors="replace")
    assert "/setup/gate-status" in nav_js, "nav-groups.js must source its gate copy from /setup/gate-status"
    assert "Requires autonomous_mode" not in _rendered_html(), (
        "the Autonomous panel is back to naming a config variable instead of stating the gate. "
        "The key is a real setting now (it used to be rank-gated with no writer at all), so the "
        "server-rendered note can name the switch and where to find it — 'requires "
        "autonomous_mode' still tells the operator nothing they can act on."
    )
    note = re.search(r'data-gate-note="autonomous_mode"', _rendered_html())
    assert note, (
        "the Autonomous panel lost its gate note. Its five buttons all 403 with "
        "autonomous_mode_disabled; without the note the panel is five dead buttons and no reason."
    )


# ── 5. the palette keeps every door it had ─────────────────────────────────────────────────────────
# Captured at BL-390. This slice ADDS a way to find things; removing a palette entry is a regression.
# A new entry is fine — this set is a floor, not an equality check.
_PALETTE_FLOOR = {
    "agent-tasks", "approvals", "chat-clear", "chat-export", "chat-new", "chat-retry", "codex",
    "custom-aspect", "debate", "german", "go-artifacts", "go-dashboard", "go-lab", "go-library",
    "go-memories", "go-models", "go-research", "go-settings", "improvements", "intake-quiz",
    "intelligence", "journal", "kb", "macros", "marketplace", "missions", "plans", "self-test",
    "setup-wizard", "sync", "sys-diagnostics", "tools-history", "tutor", "verify", "view-panel",
    "view-shortcuts", "view-theme", "welcome",
}


def test_no_command_palette_entry_was_removed():
    """The palette is a power feature and it works. Losing an entry costs a destination."""
    present = set(re.findall(r"\{\s*id:\s*'([^']+)'\s*,\s*group:", _main()))
    missing = _PALETTE_FLOOR - present
    assert not missing, (
        f"command-palette entr(ies) disappeared: {sorted(missing)}.\n"
        "The grouped nav is an ADDITIONAL door, not a replacement. If a panel was genuinely retired, "
        "remove it from _PALETTE_FLOOR in the same commit and say why."
    )


def test_working_panels_are_browsable_not_only_searchable():
    """The point of the slice, stated as what it actually delivers: BROWSABILITY.

    NOT "reachable without a keyboard shortcut" — that claim was made and it is not earned. The
    command palette has a visible #cmd-palette-btn ("❯ Commands"), so every one of these panels was
    always reachable by mouse. What was missing is different and worth less hyperbole: you had to
    already KNOW what to look for, because 21 destinations sat behind one generic button in a single
    undifferentiated list. Four labelled groups, readable without a click, is the change.

    Two entries are a stronger claim than the rest: the palette filters by enabled_features, so with
    multi_agent and remote off, Deliberate and Sync had no palette row at all. Those two went from
    unreachable to visible. Everything else went from searchable to browsable.

    Each was driven and returned real data before being surfaced. If one is removed from the nav it
    reverts to palette-only, which is the defect this slice exists to fix.
    """
    block = _sidebar_groups_block()
    for action in [
        "openPlans", "openMacros", "openAgentTasks", "openKb",           # Work
        "openJournal", "openCodex", "openVerify", "openTutor",           # Memory & learning
        "openIntelligence", "openImprovements", "openCharacterLab",
        "openCustomAspect", "openIntakeQuiz", "openDebate",              # Layla herself
        "openSystemDiagnostics", "openSelfTest", "openToolsHistory",
        "openApprovals", "openMarketplace", "openSetupProfiles",
        "openSync", "openWelcome",                                       # System & trust
    ]:
        assert action in block, (
            f"{action} is no longer in the grouped nav — that panel is back to being findable only "
            "by opening the command palette and already knowing what to search for."
        )


def test_nav_groups_are_labelled_not_one_undifferentiated_list():
    """21 destinations behind one generic button was the defect. Dumping 21 into one list repeats it."""
    block = _sidebar_groups_block()
    summaries = re.findall(r'<summary class="sidebar-nav-title">([^<]+)</summary>', block)
    assert len(summaries) >= 3, (
        f"the nav collapsed into {len(summaries)} group(s): {summaries}. The group headings are the "
        "feature that makes this browsable — they answer 'what is in here?' without a click."
    )
    buttons = len(_nav_entries())
    assert buttons / max(len(summaries), 1) <= 10, (
        f"{buttons} entries across {len(summaries)} groups — the groups are no longer doing any work."
    )


# ---------------------------------------------------------------------------------------------
# THE PALETTE IS THE ORIGIN, AND IT WAS LEFT UNGUARDED.
#
# The mapping test above iterates `.nav-gated` inside the sidebar groups. When it caught the two
# mis-tagged sidebar entries, the SAME two mappings were still shipping in the command palette
# (`feature: 'remote'` on Sync, `feature: 'multi_agent'` on Deliberate) — the surface that
# nav-groups.js's own docstring names as where those tags came from. The derived surface was
# corrected; the origin was not, and nothing could see it.
#
# It is worse in the palette than in the sidebar. `command-palette._featureOn()` HIDES a tagged
# command whose feature is off, so a wrong tag does not mislabel a door — it removes one. Driven
# on a stock instance (enabled_features empty): querying "deliberate" and "debate" each returned
# ZERO rows, while POST /debate answered ok:true. Unreachable by any means, on a flag its own
# router never reads.
# ---------------------------------------------------------------------------------------------
def _palette_feature_tags() -> list[tuple[str, str, str]]:
    """[(command id, feature tag, component module)] for palette entries carrying a `feature:`."""
    src = (UI / "main.js").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(
        r"\{\s*id:\s*'([^']+)'[^}]*?feature:\s*'([^']+)'[^}]*?run:\s*\(\)\s*=>\s*([A-Za-z_$][\w$]*)\.",
        src,
    ):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def test_every_palette_feature_tag_names_a_flag_the_panel_actually_reads():
    """Same rule as the sidebar mapping test, applied to the surface that FEEDS it.

    Generic: tag any palette command with a feature its panel does not read and this fails
    without anyone editing this file. An untagged command is always shown, so having no tags at
    all is a valid — and currently correct — state.
    """
    entries = _palette_feature_tags()
    if not entries:
        return  # nothing tagged: _featureOn() shows every command, which cannot lie.

    table = _route_table()
    failures = []
    for cid, feature, module in entries:
        component = UI / "components" / f"{module}.js"
        if not component.exists():
            failures.append(
                f"\n  palette '{cid}' is feature-tagged '{feature}' but its run() targets "
                f"'{module}', which is not a components/*.js module — the tag cannot be verified "
                f"against the code the panel runs, and an unverifiable gate hides a panel for "
                f"reasons no one can check."
            )
            continue
        routes = _routes_called_by(component)
        if not routes:
            failures.append(
                f"\n  palette '{cid}' is feature-tagged '{feature}' but {component.name} calls no "
                f"declared route, so no backend flag could justify hiding it. A pure client-side "
                f"panel has no gate — drop the tag."
            )
            continue
        label, flags = _flags_owned_by_gate(f'data-gate-feature="{feature}"')
        if not flags:
            failures.append(
                f"\n  palette '{cid}' is tagged '{feature}', which owns no config keys, so the "
                f"condition for showing it can never be satisfied or explained."
            )
            continue
        closure: set = set()
        for r in routes:
            closure |= _module_closure(table[r])
        if not any(_key_is_read_in(closure, f) for f in flags):
            failures.append(
                f"\n  palette '{cid}' is tagged {label}, which owns {flags}.\n"
                f"    The panel calls: {routes}\n"
                f"    Reached modules ({len(closure)}, depth {_CLOSURE_DEPTH}) read NONE of those keys.\n"
                f"    => _featureOn() will HIDE this command whenever '{feature}' is off, on a flag "
                f"its own code path never consults. Removing the door is worse than mislabelling it: "
                f"tag it with a flag the panel actually reads, or ship it untagged."
            )
    assert not failures, (
        "command-palette feature tag(s) name a flag the panel's code path never reads:"
        + "".join(failures)
        + "\n\nThis is the origin of the false locks the sidebar mapping test caught. Fixing the "
        "derived surface and leaving this one is how the same defect shipped twice."
    )
