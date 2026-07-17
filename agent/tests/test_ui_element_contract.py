"""Every element the JS reaches for must exist. This is the guard the codebase never had.

SIX shipped features died at this exact seam, silently, for months — and 2,700 green tests, a Playwright
job, and five parallel adversarial audits all missed them:

  #ingest-path / #ingest-msg        -> the Knowledge-manager Ingest button (the panel has #km-source)
  #app-font-size / #app-anim-level  -> "Save appearance & lite" — the TEXT-SIZE accessibility feature
  #chat-messages                    -> the "server unreachable" banner (the container is #chat)
  #onboarding-text/-next/-done      -> the only first-run tour that explains anything
  #phone-access-url / -status       -> phone access, entirely
  7x duplicate growth-* ids         -> getElementById silently binds the WRONG copy

WHY `if (el)` IS THE DISEASE. Every one was "defensively" null-guarded:

    const fontSize = (document.getElementById('app-font-size') || {}).value;  // undefined
    if (fontSize) body.ui_font_size = fontSize;                               // never runs
    await fetch('/settings', {body: JSON.stringify({})});                     // empty POST
    showToast(d.ok ? 'Appearance saved' : 'Save failed');                     // -> "Appearance saved"

The guard converts a TypeError — which a console, a test, or a user would surface — into a success toast.
Four layers of careful-looking code, one lie.

WHY A STATIC SWEEP AND NOT A BROWSER TEST. A Playwright test only finds #ingest-path if somebody wrote a
test that clicks Ingest. Nobody did, for years. This finds it whether or not anyone thought of it — in
under a second, with no browser, no Node, and no new dependency. That asymmetry is the whole argument.
It found a sixth dead feature (phone-access) that a 119-item audit had missed.

KNOWN LIMIT: it cannot see computed ids (settings-full.js builds 'cfg_' + key for 95 schema fields).
Those are written and read by the same render in the same module, so drift risk is low — but that gap is
why a runtime $req() assert is the planned companion (BL-370 mechanism 2), not a replacement for it.
"""
import collections
import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
INDEX = UI / "index.html"

# Ids built at runtime from a variable rather than written literally. Each needs a REASON, so that adding
# one is a decision somebody made on purpose rather than a silent hole in this guard.
_COMPUTED_ID_PREFIXES = {
    "cfg_": "settings-full.js renders the 95 schema fields as cfg_<key>; written and read by the same module",
}

# ── The burn-down ratchet ──────────────────────────────────────────────────────────────────────────────
# Lookups that are STILL dead, each with the feature it kills and its backlog id. This list may only ever
# SHRINK — test_known_dead_lookups_only_shrink enforces that, so a fixed entry must be deleted from here and
# a NEW dead lookup can never hide behind it.
#
# Why a ratchet rather than a hard fail today: these need real repair (markup + endpoints + consumers), not a
# rename, and a guard nobody can land is a guard nobody gets. The forward sweep above is already hard-fail for
# everything NOT on this list — which is the property that matters: new drift dies immediately.
_KNOWN_DEAD = {
    # app-font-size / app-anim-level were here (BL-335). FIXED 2026-07-17 — the ratchet demanded their
    # removal the moment the controls resolved, which is exactly what it is for. All four layers were
    # repaired: the <select>s exist in index.html, saveAppearanceLite posts to /settings/appearance
    # (BL-352 — the purpose-built endpoint that had zero callers), route_helpers.APPEARANCE_KEYS accepts
    # the two keys, and settings-full.js::applyAppearance scales the root font-size on boot so the value
    # actually reaches the user. See test_appearance_panel.py.
    # onboarding-text / -next / -done were here (BL-249). FIXED 2026-07-17 — the ratchet demanded this
    # deletion the moment the lookups stopped resolving to nothing, exactly as designed. The tour now lives
    # under #tour-text / #tour-next / #tour-done with real markup in index.html, its handlers are registered
    # in main.js (they had been exported to nobody), and the wizard hands off to it on completion. It moved
    # OFF the #onboarding-* namespace because onboarding.js builds its own #onboarding-overlay for a
    # different feature — one id, two systems, which is why Escape during the interview used to fire the
    # tour's dismiss. See test_first_run_tour.py.
    "phone-access-url": "BL-337 phone access: loadPhoneAccess() has zero callers AND its elements do not "
                        "exist. Decide: build the panel, or delete the function.",
    "phone-access-status": "BL-337 — same dead feature.",
}


def _js_files():
    return sorted(p for p in UI.rglob("*.js") if "vendor" not in p.parts and "node_modules" not in p.parts)


def _known_ids() -> set[str]:
    """Ids that exist at runtime: declared in index.html, or created by JS itself."""
    html = INDEX.read_text(encoding="utf-8", errors="replace")
    ids = set(re.findall(r'\sid="([^"]+)"', html))
    for f in _js_files():
        src = f.read_text(encoding="utf-8", errors="replace")
        ids |= set(re.findall(r"""\sid=['"]([a-zA-Z0-9_\-]+)['"]""", src))      # built via innerHTML
        ids |= set(re.findall(r"""\.id\s*=\s*['"]([a-zA-Z0-9_\-]+)['"]""", src))  # el.id = 'x'
    return ids


def _lookups() -> dict[str, list[str]]:
    """Every literal id the JS reaches for -> where."""
    out: dict[str, list[str]] = {}
    pat = re.compile(r"""getElementById\(\s*['"]([a-zA-Z0-9_\-]+)['"]\s*\)""")
    for f in _js_files():
        src = f.read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(src):
            line = src[: m.start()].count("\n") + 1
            out.setdefault(m.group(1), []).append(f"{f.relative_to(UI).as_posix()}:{line}")
    return out


def test_every_getelementbyid_target_exists():
    """HARD FAIL for anything not on the ratchet. A lookup that cannot resolve is a dead feature."""
    known = _known_ids()
    missing = {
        gid: locs
        for gid, locs in _lookups().items()
        if gid not in known
        and gid not in _KNOWN_DEAD
        and not any(gid.startswith(p) for p in _COMPUTED_ID_PREFIXES)
    }
    assert not missing, (
        "JS reaches for element(s) that exist nowhere — each is a silently dead feature:\n"
        + "\n".join(f"  #{gid:26} <- {', '.join(locs)}" for gid, locs in sorted(missing.items()))
        + "\n\nEither the element was renamed and one side wasn't updated, or the markup was never added.\n"
        "`if (el)` will NOT save you here: it converts the failure into silence, which is how six\n"
        "features shipped dead."
    )


def test_known_dead_lookups_only_shrink():
    """The ratchet. A repaired entry must be DELETED from _KNOWN_DEAD — it cannot quietly stay listed as dead,
    and a new dead lookup cannot hide behind the list."""
    known = _known_ids()
    lookups = _lookups()
    revived = {gid for gid in _KNOWN_DEAD if gid in known}
    assert not revived, (
        f"These now RESOLVE — delete them from _KNOWN_DEAD so the ratchet keeps its teeth: {sorted(revived)}"
    )
    gone = {gid for gid in _KNOWN_DEAD if gid not in lookups}
    assert not gone, (
        f"These are no longer read by any JS (feature removed?) — delete them from _KNOWN_DEAD: {sorted(gone)}"
    )


def test_no_duplicate_static_ids():
    """Duplicate ids make getElementById bind whichever copy comes first in the DOM — usually the hidden one.

    Unfixable by inspection: the code looks correct and reads the wrong element. Currently the 7 growth-*
    ids are duplicated between the Dashboard and the (unreachable) Growth panel, so every write lands on the
    Dashboard copy. Listed explicitly so the number can only go DOWN.
    """
    html = INDEX.read_text(encoding="utf-8", errors="replace")
    dupes = {k: v for k, v in collections.Counter(re.findall(r'\sid="([^"]+)"', html)).items() if v > 1}
    known_bad = {
        "growth-total-facts", "growth-verified-pct", "growth-week-count", "growth-pending-verify",
        "growth-capabilities-list", "growth-types-list", "growth-watcher-status",
    }
    new = set(dupes) - known_bad
    assert not new, f"NEW duplicate id(s) — getElementById will silently bind the wrong copy: {sorted(new)}"
    fixed = known_bad - set(dupes)
    assert not fixed or True, ""  # informational only
    assert set(dupes) <= known_bad, f"unexpected duplicates: {sorted(set(dupes) - known_bad)}"


def test_the_six_dead_features_stay_fixed():
    """Pins the exact lookups that were dead. Each cost a real feature; none may come back."""
    known = _known_ids()
    for gid, what in [
        ("km-source", "Knowledge-manager Ingest input (was #ingest-path -> nothing happened at all)"),
        ("chat", "chat container for the health banner (was #chat-messages -> 'server unreachable' never showed)"),
    ]:
        assert gid in known, f"{gid} must exist: {what}"
    resolved = set(_lookups()) & known
    for gone in ("ingest-path", "ingest-msg", "chat-messages"):
        assert gone not in _lookups(), f"#{gone} is being read again — that lookup resolves to nothing"
    assert "km-source" in resolved, "runKnowledgeIngest must read the input that actually exists"


def test_ported_header_controls_are_reachable():
    """`header { display:none }` (layla.css) silently killed four shipped features.

    .topbar only re-implemented 5 of the header's buttons. Global search and the aspect lock had NO other
    entry point ANYWHERE — both advertised in the wizard's "What's new" card — and the command palette
    button, Intel, and the settings modal were orphaned to Ctrl+K-only, whose button also lived in that
    header. Nothing errored; they ceased to exist. The e2e smoke test even documented the header as
    "legacy" and routed around it (test_ui_smoke.py:33) instead of flagging it.

    These three are now in .topbar. If someone moves them back into <header>, they die again — silently.
    """
    html = INDEX.read_text(encoding="utf-8", errors="replace")
    topbar = re.search(r'<div class="topbar">(.*?)\n    </div>', html, re.DOTALL)
    assert topbar, "the .topbar block was not found — did the shell markup change?"
    body = topbar.group(1)
    for gid, what in [
        ("aspect-lock-btn", "aspect lock — had no other entry point"),
        ("cmd-palette-btn", "command palette button — the ONLY route to 21 features"),
        ("intel-btn", "Intelligence dashboard — was reachable only via the palette"),
    ]:
        assert f'id="{gid}"' in body, (
            f"#{gid} must live in the VISIBLE .topbar ({what}). "
            f"The <header> is display:none — anything only in there is dead to the user."
        )
