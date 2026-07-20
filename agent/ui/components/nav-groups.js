/**
 * nav-groups.js — gate copy for the grouped sidebar navigation (BL-390).
 *
 * The navigation surfaces panels that were previously palette-only. One of them is GATED (Sync),
 * and this slice's rule is that a gated entry ships with the gate visible AND a real path to
 * satisfy it — "Requires multi_agent" names a variable, which is not a path.
 *
 * A GATE TAG MUST NAME A FLAG THE PANEL'S OWN PATH READS. This started as two gated entries and
 * both tags were wrong: they were inherited from the command palette's `feature:` tags, where a
 * tag only HID a row and claimed nothing. Here the same tag becomes a paragraph of confident,
 * specific, actionable prose, so a wrong mapping stops being cosmetic. Deliberate was tagged
 * multi_agent and is now UNGATED — /debate reads no such flag and returned ok:true with the flag
 * off. Sync was tagged remote and now gates on syncthing_api_key, the key /sync/* actually reads.
 * The mapping is pinned by test_nav_entry_contract.py::test_every_gate_tag_names_a_flag_the_panel_
 * actually_reads, which resolves button -> action -> component -> routes -> router import closure
 * and fails any tag naming a flag that closure never reads. If a panel turns out to have no real
 * gate, the honest outcome is an ungated entry — not softer copy on a door that is not locked.
 *
 * WHERE THE TEXT COMES FROM. Nowhere in this file. Every reason string is fetched from
 * /setup/gate-status, which is a thin reuse of install.feature_status — the same engine the setup
 * wizard and the settings screen already explain themselves with. Writing the copy here would be
 * a third owner list that drifts the moment a gate moves, which is the exact failure the
 * feature_status registry was built to end.
 *
 * FAIL CLOSED, NOT SILENT. If the endpoint cannot be reached the badge says so rather than
 * rendering nothing: a gated entry that looks ungated is how "it just does nothing when I click
 * it" happens. An unreachable probe is reported as unknown, never as available.
 */

const GATE_ENDPOINT = '/setup/gate-status';

/** Collect the gated entries the markup declares. The DOM is the source of what needs a gate. */
function _gatedButtons() {
  return Array.from(document.querySelectorAll('.nav-gated[data-gate-feature], .nav-gated[data-gate-key]'));
}

/**
 * Standalone gate notes — a panel that is already surfaced but whose ACTION is gated, e.g. the
 * Autonomous investigation panel, whose five buttons all 403 with `autonomous_mode_disabled`.
 * Its previous copy read "Requires autonomous_mode": the name of a variable, which tells a user
 * neither what is wrong nor what to do. These render the same feature_status reason as the nav.
 */
function _gateNotes() {
  return Array.from(document.querySelectorAll('[data-gate-note]'));
}

function _badgeOf(btn) {
  return btn.querySelector('.nav-gate-badge');
}

/** The reason line lives AFTER the button so the button stays a clean click target. */
function _reasonOf(btn) {
  let el = btn.nextElementSibling;
  if (!el || !el.classList.contains('nav-gate-reason')) {
    el = document.createElement('div');
    el.className = 'nav-gate-reason';
    el.hidden = true;
    btn.insertAdjacentElement('afterend', el);
  }
  return el;
}

function _applyLocked(btn, reason) {
  const badge = _badgeOf(btn);
  const line = _reasonOf(btn);
  if (badge) {
    badge.textContent = 'locked';
    badge.hidden = false;
  }
  btn.setAttribute('data-gate-state', 'locked');
  // The full reason is on the button too, so a hover and a screen reader both get it.
  btn.setAttribute('title', reason);
  line.textContent = reason;
  line.hidden = false;
}

function _applyAvailable(btn) {
  const badge = _badgeOf(btn);
  const line = _reasonOf(btn);
  if (badge) {
    badge.textContent = '';
    badge.hidden = true;
  }
  btn.setAttribute('data-gate-state', 'on');
  btn.removeAttribute('title');
  line.textContent = '';
  line.hidden = true;
}

function _applyUnknown(btn, why) {
  const badge = _badgeOf(btn);
  const line = _reasonOf(btn);
  if (badge) {
    badge.textContent = 'status unknown';
    badge.hidden = false;
  }
  btn.setAttribute('data-gate-state', 'unknown');
  btn.setAttribute('title', why);
  line.textContent = why;
  line.hidden = false;
}

/**
 * Ask the backend about every gated entry in the nav and render the answer.
 * Returns the number of entries resolved — the tests and the console use it as proof it ran.
 */
export async function refreshNavGates() {
  const btns = _gatedButtons();
  const notes = _gateNotes();
  if (!btns.length && !notes.length) return 0;
  const features = [...new Set(btns.map((b) => b.getAttribute('data-gate-feature')).filter(Boolean))];
  const keys = [...new Set([
    ...btns.map((b) => b.getAttribute('data-gate-key')),
    ...notes.map((n) => n.getAttribute('data-gate-note')),
  ].filter(Boolean))];
  const qs = new URLSearchParams();
  if (features.length) qs.set('features', features.join(','));
  if (keys.length) qs.set('keys', keys.join(','));

  let data = null;
  try {
    const r = await fetch(`${GATE_ENDPOINT}?${qs.toString()}`, { headers: { Accept: 'application/json' } });
    if (r.ok) data = await r.json();
  } catch (_) {
    data = null;
  }
  if (!data) {
    const why = 'Could not reach the server to check whether this feature is available.';
    btns.forEach((b) => _applyUnknown(b, why));
    notes.forEach((n) => { n.textContent = why; });
    return btns.length + notes.length;
  }

  const byFeature = new Map((data.features || []).map((f) => [f.id, f]));
  const byKey = new Map((data.keys || []).map((k) => [k.key, k]));
  btns.forEach((btn) => {
    const fid = btn.getAttribute('data-gate-feature');
    const kid = btn.getAttribute('data-gate-key');
    const rec = fid ? byFeature.get(fid) : byKey.get(kid);
    if (!rec) {
      _applyUnknown(btn, 'The server did not report a status for this feature.');
    } else if (rec.on) {
      _applyAvailable(btn);
    } else {
      _applyLocked(btn, rec.reason || 'This feature is currently off, and the server gave no reason.');
    }
  });

  notes.forEach((note) => {
    const rec = byKey.get(note.getAttribute('data-gate-note'));
    if (!rec) {
      note.textContent = 'The server did not report a status for this feature.';
      note.setAttribute('data-gate-state', 'unknown');
    } else if (rec.on) {
      note.textContent = '';
      note.hidden = true;
      note.setAttribute('data-gate-state', 'on');
    } else {
      note.hidden = false;
      note.textContent = rec.reason || 'This feature is currently off, and the server gave no reason.';
      note.setAttribute('data-gate-state', 'locked');
    }
  });
  return btns.length + notes.length;
}

/** Wire up on boot, and re-check whenever the wizard applies a new selection. */
export function initNavGroups() {
  refreshNavGates();
  window.addEventListener('layla:profiles-applied', refreshNavGates);
}
