/**
 * components/settings-full.js — Settings, workspace presets, relationship codex, content policy.
 *
 * Converted from js/layla-settings-full.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast, laylaConfirm)
 */

import { escapeHtml, showToast, laylaConfirm } from '../services/utils.js';
import { overlayManager } from '../core/overlay.js';

// i18n: window.t is installed by ui/core/i18n.js init. Fall back to the key's default if it isn't
// ready yet (never render "undefined"). Keys live under settings.* in ui/locales/*.json.
function T(key, fallback, params) {
  try { if (window.t) { const v = window.t(key, params); if (v && v !== key) return v; } } catch (_) {}
  let s = fallback;
  if (params) for (const k in params) s = s.replace("{" + k + "}", params[k]);
  return s;
}

// Fallback client-side humanizer (backend normally supplies f.label). snake_case -> Title.
const _ACRONYMS = { ui: 'UI', api: 'API', cors: 'CORS', url: 'URL', ttl: 'TTL', id: 'ID', llm: 'LLM', gpu: 'GPU', cpu: 'CPU', tts: 'TTS', stt: 'STT', cot: 'CoT', rag: 'RAG', mcp: 'MCP', nsfw: 'NSFW', db: 'DB', os: 'OS' };
function humanizeKey(key) {
  return String(key || '').split('_').filter(Boolean).map(function (w, i) {
    if (_ACRONYMS[w]) return _ACRONYMS[w];
    return i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w;
  }).join(' ');
}

// ── Feature areas (grouped capabilities the user can switch on/off) ──────────
async function _renderFeatureThemes() {
  let themes = [];
  try {
    const d = await (await fetch('/settings/themes')).json();
    themes = (d && d.themes) || [];
  } catch (_e) { return ''; }
  if (!themes.length) return '';
  const rows = themes.map(function (t) {
    const id = 'theme_' + String(t.key).replace(/[^a-zA-Z0-9_]/g, '_');
    return '<div class="settings-row settings-section" style="border-left:3px solid var(--asp);padding-left:8px">' +
      '<label style="display:flex;align-items:center;gap:8px;font-size:0.82rem;text-transform:none;color:var(--text);font-weight:600">' +
      '<input type="checkbox" id="' + id + '" ' + (t.enabled ? 'checked' : '') +
      ' onchange="window.laylaToggleFeatureTheme(\'' + escapeHtml(t.key) + '\', this.checked)"/> ' +
      escapeHtml(t.label) + '</label>' +
      '<div class="hint">' + escapeHtml(t.desc) + '</div></div>';
  }).join('');
  return '<div class="settings-row" style="margin-bottom:10px">' +
    '<div style="font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-faint);margin-bottom:6px">' + escapeHtml(T('settings.feature_areas.heading', 'Feature areas')) + '</div>' +
    '<div class="hint" style="margin-bottom:8px">' + escapeHtml(T('settings.feature_areas.hint', 'Turn whole capability areas on or off — Layla only carries what you switch on.')) + '</div>' +
    rows +
    '<div style="border-bottom:1px solid var(--border);margin:12px 0 4px"></div>' +
    '</div>';
}

/**
 * Toggle a feature area — and render what the SERVER says is in force, not what we asked for.
 *
 * C2, the client half. This toasted "Enabled: external tools" off `d.ok` alone, and `d.ok`
 * was true the moment the write landed. The checkbox, however, renders from the EFFECTIVE
 * config, so a flag an owner reverts snapped back to unticked the next time the panel opened
 * — with the green success still the last thing the operator had been told. Now the response
 * carries the effective state (`d.enabled`) and the per-flag read-back, so the checkbox is
 * corrected in place and the reason goes in the amber panel with everything else.
 */
export async function laylaToggleFeatureTheme(key, enabled) {
  const box = document.getElementById('theme_' + String(key).replace(/[^a-zA-Z0-9_]/g, '_'));
  try {
    const r = await fetch('/settings/themes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key, enabled: !!enabled }),
    });
    const d = await r.json();
    if (!r.ok || !d || !d.ok) {
      // A REFUSAL is not a failure — the server understood, declined, and said why. Printing
      // "Could not update" over a security precondition sends the operator looking for a bug
      // instead of reading the one sentence that tells them what to do first (remote access
      // with no credential: rotate a token, then enable it).
      const refused = (d && d.refused) || [];
      showToast(refused.length
        ? T('settings.feature_areas.refused', 'Refused: {name} — {why}', { name: key.replace(/_/g, ' '), why: (d.error || T('settings.feature_areas.refused_default', 'a security policy declined this change')) })
        : T('settings.feature_areas.update_failed_reason', 'Could not update feature area — {why}', { why: ((d && d.error) || ('HTTP ' + r.status)) }));
      // The write did not happen, so the control must not keep showing that it did. The
      // server's effective state is authoritative when it sent one.
      if (box) box.checked = (d && typeof d.enabled === 'boolean') ? d.enabled : !enabled;
      // A refusal changes the not-in-force panel too — re-read it rather than assume.
      if (refused.length) { try { await _loadNotInForce(); } catch (_e2) { /* no-op */ } }
      return;
    }
    // The server's effective answer wins over the click. Silently leaving the box ticked for
    // a capability that is off is the whole defect.
    const effective = !!d.enabled;
    if (box) box.checked = effective;
    const label = key.replace(/_/g, ' ');
    if (effective === !!enabled && d.in_force !== false) {
      // "Advanced retrieval & search" needs hyde_enabled, which auto-tune forces OFF on every
      // CPU tier — so this toggle could never read back as ON until the server started locking
      // the key. Say when that lock was taken, rather than doing it invisibly.
      const locked = (d.auto_tune_locked_keys || []);
      const base = (enabled ? T('settings.feature_areas.enabled', 'Enabled: {name}', { name: label }) : T('settings.feature_areas.disabled', 'Disabled: {name}', { name: label }));
      showToast(enabled && locked.length
        ? T('settings.feature_areas.enabled_locked', '{base} — locked {keys} so hardware auto-tune cannot revert it', { base: base, keys: locked.join(', ') })
        : base);
    } else {
      const why = d.not_in_force_note ||
        ((d.missing_packages || []).length
          ? T('settings.feature_areas.needs_packages', 'needs packages that are not installed: {pkgs}', { pkgs: d.missing_packages.join(', ') })
          : T('settings.feature_areas.owner_holding', 'an owner is holding its settings'));
      showToast(T('settings.feature_areas.not_in_force', 'NOT in force: {name} — {why}', { name: label, why: why }));
    }
    // Whatever happened, the panel's not-in-force state may have changed. Re-read it from the
    // server rather than inferring it from this one response.
    await _loadNotInForce();
  } catch (_e) {
    showToast(T('settings.feature_areas.update_failed', 'Could not update feature area'));
    if (box) box.checked = !enabled;
  }
}
try { window.laylaToggleFeatureTheme = laylaToggleFeatureTheme; } catch (_e) { /* no-op */ }

// The field values as first rendered. Save diffs against this so it posts only what the
// operator actually edited — see saveSettings.
let _formSnapshot = {};

/** Read one schema field out of the DOM, in the type the API expects. */
function _readField(f) {
  const el = document.getElementById('cfg_' + String(f.key).replace(/[^a-zA-Z0-9_]/g, '_'));
  if (!el) return undefined;
  if (f.type === 'boolean') return el.checked;
  if (f.type === 'number') return parseFloat(el.value);
  if (f.type === 'list') {
    return String(el.value || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  }
  return el.value;
}

function _sameValue(a, b) {
  if (Array.isArray(a) || Array.isArray(b)) {
    return JSON.stringify(a || []) === JSON.stringify(b || []);
  }
  // An empty number input parses to NaN; NaN !== NaN would report every blank field as edited.
  if (typeof a === 'number' && typeof b === 'number' && isNaN(a) && isNaN(b)) return true;
  return a === b;
}

// ── Settings overlay ────────────────────────────────────────────────────────
export async function openSettings() {
  const ov = document.getElementById('settings-overlay');
  if (!ov) return;
  // Route through the unified overlay manager so Settings gets Escape-to-close, a focus trap,
  // scroll-lock and z-index tiering like every other modal (it used to bypass all of that).
  try { if (!overlayManager.open('settings')) ov.classList.add('visible'); }
  catch (_) { ov.classList.add('visible'); }
  // Populate the appearance controls from the server. Without this the panel renders its defaults over
  // whatever is actually stored, so a saved text size looks unsaved and re-saving silently reverts it.
  loadAppearance();
  // BL-337: populate the phone-access panel. loadPhoneAccess() was complete and exported to nobody,
  // so the feature was a caller and two elements short of working. It is pure local computation
  // (location.* → a LAN URL), no fetch, so it cannot slow the panel down.
  loadPhoneAccess();
  // v1.7.5 Knowledge packs. Fire-and-forget like the appearance/phone loaders above: it fetches
  // /knowledge/packs and populates its own panel, degrading to "unavailable" if the API is absent,
  // so it can never block or break the rest of the settings form from rendering.
  loadKnowledgePacks();
  // knowledge-presets-1.7.5 Approvals & safety. Same fire-and-forget shape as the loaders above:
  // it GETs /settings, derives the approval mode from three keys and paints the selector, degrading
  // to "leave the static markup as-is" if the read fails — so it can never block the rest of the form.
  loadApprovalsSafety();
  const loadEl = document.getElementById('settings-loading');
  const formEl = document.getElementById('settings-form');
  if (loadEl) { loadEl.style.display = 'block'; loadEl.textContent = T('settings.loading', 'Loading…'); }
  if (formEl) formEl.style.display = 'none';
  try {
    const res = await fetch('/settings/schema');
    const schema = await res.json();
    const r2 = await fetch('/settings');
    const cfg = await r2.json();
    if (loadEl) loadEl.style.display = 'none';
    if (formEl) {
      formEl.style.display = 'block';
      const fields = schema.fields || [];
      let html = await _renderFeatureThemes();
      fields.forEach(function (f) {
        const k = f.key;
        const v = cfg[k];
        // Human-readable label from the backend (falls back to a title-cased key).
        const lbl = escapeHtml(f.label || humanizeKey(k));
        const id = 'cfg_' + String(k).replace(/[^a-zA-Z0-9_]/g, '_');
        const hint = String(f.hint || '').replace(/</g, '&lt;');
        // WHO OWNS THIS CONTROL. Ten editable keys are overwritten by hardware auto-tune on
        // every config load; editing one used to return ok:true and silently revert, with a
        // warning on exactly one of the ten. Say it on the control itself, before the user
        // spends an edit on it — and offer the per-key lock that makes the edit stick.
        const owned = !!f.auto_tune_owned;
        const badge = owned
          ? '<span class="cfg-owner' + (f.auto_tune_active ? '' : ' is-locked') + '" title="' +
            escapeHtml(f.auto_tune_active
              ? T('settings.autotune.badge_owned_title', 'Hardware auto-tune sets this on every config load and will overwrite your value.')
              : T('settings.autotune.badge_locked_title', 'You have locked this key — auto-tune will leave your value alone.')) + '">' +
            escapeHtml(f.auto_tune_active ? T('settings.autotune.badge_owned', 'auto-tune owns this') : T('settings.autotune.badge_locked', 'locked — your value wins')) + '</span>'
          : '';
        const ownHint = (owned && f.auto_tune_active)
          ? '<div class="hint cfg-owner-hint">' + T('settings.autotune.own_hint', 'Auto-tune re-derives this from your hardware on every load, so a value set here does not stick. Add <code>{key}</code> to <em>Auto tune locked keys</em> below (or turn off <em>Auto tune enabled</em>) to keep your own value.', { key: escapeHtml(k) }) + '</div>'
          : '';
        const rowCls = 'settings-row settings-section' + (owned ? ' is-auto-tuned' : '');
        if (f.type === 'boolean') {
          html += '<div class="' + rowCls + '"><label style="display:flex;align-items:center;gap:8px;font-size:0.8rem;text-transform:none;color:var(--text)"><input type="checkbox" id="' + id + '" ' + (v ? 'checked' : '') + '/> ' + lbl + badge + '</label><div class="hint">' + hint + '</div>' + ownHint + '</div>';
        } else if (f.type === 'number') {
          html += '<div class="' + rowCls + '"><label>' + lbl + badge + '</label><input type="number" id="' + id + '" value="' + (v != null ? String(v) : '') + '" step="any"/><div class="hint">' + hint + '</div>' + ownHint + '</div>';
        } else if (f.type === 'list') {
          const txt = Array.isArray(v) ? v.join(', ') : String(v != null ? v : '');
          html += '<div class="' + rowCls + '"><label>' + lbl + badge + '</label><input type="text" id="' + id + '" data-list="1" value="' + escapeHtml(txt) + '" placeholder="n_ctx, hyde_enabled"/><div class="hint">' + hint + '</div>' + ownHint + '</div>';
        } else {
          html += '<div class="' + rowCls + '"><label>' + lbl + badge + '</label><input type="text" id="' + id + '" value="' + escapeHtml(String(v != null ? v : '')) + '"/><div class="hint">' + hint + '</div>' + ownHint + '</div>';
        }
      });
      formEl.innerHTML = html;
      // Snapshot AFTER render: this is the baseline "what the server gave us", so save can
      // tell an edit from one of the other eighty-nine untouched fields.
      _formSnapshot = {};
      fields.forEach(function (f) {
        const v = _readField(f);
        if (v !== undefined) _formSnapshot[f.key] = v;
      });
      // C3: the panel learns what is not in force ON LOAD, not only in response to a save
      // that happened to touch that key. Awaited so the markers are on screen with the form.
      await _loadNotInForce();
    }
  } catch (e) {
    if (loadEl) loadEl.style.display = 'none';
    if (formEl) {
      formEl.style.display = 'block';
      formEl.innerHTML =
        '<div style="color:var(--text-dim);font-size:0.8rem;line-height:1.5">' +
        escapeHtml(T('settings.load_error', 'Could not load settings. Is Layla running?')) + '<br>' +
        '<button type="button" class="tab-btn" style="margin-top:10px" onclick="openSettings()">' + escapeHtml(T('settings.retry', 'Retry')) + '</button>' +
        '</div>';
    }
  }
}

export function closeSettings() {
  try { if (overlayManager.close('settings')) return; } catch (_) {}
  const ov = document.getElementById('settings-overlay');
  if (ov) ov.classList.remove('visible');
}

/**
 * Render the server's per-key read-back for everything that did NOT take effect (S3).
 *
 * The last mile. The server can be perfectly honest and the operator still never learns
 * anything if the answer is compressed into one line of toast that fades in 2.2 seconds —
 * and a per-key report with an owner and a remedy does not fit in a toast. So the keys that
 * were saved-but-reverted get a persistent amber panel naming the owner and the reason, and
 * their control is marked in place, because the checkbox is rendered from the EFFECTIVE
 * config and will therefore snap back to the old value the moment the panel reopens. Without
 * the marker that snap-back is the only feedback, and it reads as "the save didn't happen".
 *
 * Amber, never green, and never the red reserved for "we know it failed": the write DID land
 * on disk. It is a third outcome and it gets a third colour.
 */
// The not-in-force set as the SERVER reports it for the whole config (GET
// /settings/not_in_force), independent of any one save. See _loadNotInForce.
let _notInForce = [];

// Rows from the LAST SAVE that GET /settings/not_in_force structurally cannot report, because
// its whole evidence is "the file asks for X and the effective config disagrees" — and a
// REFUSED write never reached the file at all. Without holding them here, the async
// _loadNotInForce() that follows every save re-rendered the panel from the config alone and
// erased the refusal a few hundred milliseconds after drawing it. That is the same retraction
// bug the persistent set was introduced to fix, arriving from the other direction: not "an old
// warning was dropped", but "the new one was". Replaced (not appended) on each save, so it
// tracks the latest outcome instead of accumulating into wallpaper.
let _saveOnlyRows = [];

/**
 * Load "which saved settings is the app not honouring?" from the server.
 *
 * C3 — THE BUG THIS DELETES. The amber warning was drawn only from the response to a save,
 * and _renderNotInForce cleared every marker whenever the CURRENT response was clean. Since
 * saveSettings deliberately posts only the fields that changed, the sequence was:
 *
 *   1. tick hyde_enabled, save   -> amber "NOT in force — held by auto_tune", row marked
 *   2. edit max_tool_calls, save -> GREEN "Saved 1 change", panel gone, hyde still ticked
 *
 * …a green success beside a ticked checkbox for a setting that is not in force. The fix is
 * NOT to post everything — that is what keeps the warning from becoming wallpaper. It is that
 * "not in force" is a property of the CONFIG, readable at any time, and not a property of the
 * save that happened to touch the key.
 */
async function _loadNotInForce() {
  try {
    const r = await fetch('/settings/not_in_force');
    const d = await r.json();
    // ONLY a successful answer may replace the set. `ok:false` means the server could not
    // read the config — that is UNKNOWN, and treating it as an empty list would clear the
    // amber panel on a failure, which is the retraction bug again by another route.
    if (d && d.ok && Array.isArray(d.not_in_force)) _notInForce = d.not_in_force;
  } catch (_e) {
    // Same reasoning for a transport failure: leave the last known set in place.
  }
  _renderNotInForce();
}

function _renderNotInForce(report) {
  const box = document.getElementById('settings-not-in-force');
  document.querySelectorAll('.settings-row.is-not-in-force').forEach(function (el) {
    el.classList.remove('is-not-in-force');
  });
  if (!box) return;
  // A save just answered: its refusals become the save-only set, replacing the previous one.
  // Called with no report (the async config reload), the existing set is kept — otherwise the
  // reload silently retracts the refusal this save just reported.
  if (report) {
    _saveOnlyRows = report.filter(function (r) { return r && r.outcome === 'refused'; });
  }
  // The persistent per-config set, PLUS anything this particular save reported that the
  // config cannot show (a rejected or refused key never reaches the file, so GET cannot see it).
  const bad = _notInForce.slice();
  const seen = {};
  bad.forEach(function (r) { seen[r.key] = 1; });
  _saveOnlyRows.concat(report || []).forEach(function (r) {
    if (!r || r.outcome === 'took_effect' || r.outcome === 'clamped') return;
    if (seen[r.key]) return;
    seen[r.key] = 1;
    bad.push(r);
  });
  if (!bad.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
  box.style.display = 'block';
  // "Saved to disk, but NOT in force" is the wrong sentence for a REFUSED write — that value
  // never reached the disk at all, and telling an operator it did sends them looking for it in
  // runtime_config.json. Both kinds share this panel, so the heading has to cover whichever
  // kinds are actually present rather than assert the common one.
  const anyRefused = bad.some(function (r) { return r && r.outcome === 'refused'; });
  const anyOther = bad.some(function (r) { return r && r.outcome !== 'refused'; });
  const head = anyRefused && anyOther ? T('settings.nif.head_mixed', 'Refused, or saved but NOT in force')
    : (anyRefused ? T('settings.nif.head_refused', 'Refused — not saved') : T('settings.nif.head_not_in_force', 'Saved to disk, but NOT in force'));
  const headCount = bad.length === 1
    ? T('settings.nif.count_one', '{n} setting', { n: bad.length })
    : T('settings.nif.count_many', '{n} settings', { n: bad.length });
  box.innerHTML =
    '<div class="nif-head">⚠ ' + escapeHtml(head) + ' — ' + escapeHtml(headCount) + '</div>' +
    bad.map(function (r) {
      const el = document.getElementById('cfg_' + String(r.key).replace(/[^a-zA-Z0-9_]/g, '_'));
      const row = el && el.closest ? el.closest('.settings-row') : null;
      if (row) row.classList.add('is-not-in-force');
      const owner = r.owner ? String(r.owner) : T('settings.nif.owner_unknown', 'unknown');
      const eff = Object.prototype.hasOwnProperty.call(r, 'effective')
        ? ' <span class="nif-eff">' + escapeHtml(T('settings.nif.in_force', 'in force:')) + ' ' + escapeHtml(JSON.stringify(r.effective)) + '</span>' : '';
      const label = r.outcome === 'refused' ? T('settings.nif.refused_by', 'refused by ') : T('settings.nif.owned_by', 'owned by ');
      return '<div class="nif-item"><code>' + escapeHtml(String(r.key)) + '</code>' +
        ' <span class="nif-owner">' + label + escapeHtml(owner) + '</span>' + eff +
        '<div class="nif-reason">' + escapeHtml(String(r.reason || '')) + '</div></div>';
    }).join('');
}

/**
 * Save the config editor — and report what the SERVER says happened.
 *
 * This used to toast "Settings saved" whenever the HTTP status was 2xx, without ever reading
 * the response body. Since POST /settings answered a blanket {"ok": true} for everything, a
 * write that was dropped (key not in the schema) or reverted (key owned by hardware auto-tune)
 * produced exactly the same confident success message as a write that landed. Now the body is
 * read, and `rejected` / `overridden` / `report` are shown instead of swallowed.
 */
export async function saveSettings() {
  const schemaRes = await fetch('/settings/schema');
  const schema = await schemaRes.json();
  // Post ONLY the fields that changed. Sending all ninety made the server's honest "auto-tune
  // will overwrite these" warning fire on every single save, naming nine keys the user never
  // touched — a warning that always appears is wallpaper, and it trained the operator to
  // dismiss the one case where it was real.
  const body = {};
  const changedKeys = [];
  (schema.fields || []).forEach(function (f) {
    const v = _readField(f);
    if (v === undefined) return;
    if (Object.prototype.hasOwnProperty.call(_formSnapshot, f.key) && _sameValue(v, _formSnapshot[f.key])) return;
    body[f.key] = v;
    changedKeys.push(f.key);
  });
  // Capture the lock baseline BEFORE the response handler refreshes _formSnapshot, or the
  // "locked X" report diffs the new value against itself and never fires.
  const prevLocked = (_formSnapshot.auto_tune_locked_keys || []).slice().sort();
  const msg = document.getElementById('settings-save-msg');
  const say = (text, isErr) => {
    if (msg) {
      msg.style.display = 'inline';
      msg.textContent = text;
      msg.setAttribute('data-kind', isErr ? 'warn' : 'ok');
      // A warning must stay put long enough to read; a plain success may fade.
      if (!isErr) setTimeout(function () { msg.style.display = 'none'; }, 2200);
    }
    showToast(text);
  };
  if (!changedKeys.length) { say(T('settings.save.no_changes', 'No changes to save'), false); return; }
  try {
    const res = await fetch('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await res.json().catch(function () { return {}; });
    if (!res.ok) { say(T('settings.save.failed_reason', 'Save failed — {why}', { why: (d.error || ('HTTP ' + res.status)) }), true); return; }

    const rejected = d.rejected || [];
    const badLocks = d.rejected_locks || [];
    const adjusted = d.adjusted || [];
    const saved = d.saved || [];
    const report = d.report || [];
    // S3: the per-key read-back goes on screen BEFORE any branch below picks a toast, so a
    // save that did not take effect can never leave the panel showing nothing. C3: re-read
    // the whole config's not-in-force set too, so keys held from EARLIER saves stay marked
    // instead of being retracted by this one.
    _renderNotInForce(report);
    _loadNotInForce();
    const notInForce = report.filter(function (r) {
      return r && r.outcome !== 'took_effect' && r.outcome !== 'clamped';
    });
    // What landed is the new baseline, so an immediate second Save correctly reports "no
    // changes" instead of re-posting values the server already has.
    saved.forEach(function (k) {
      if (Object.prototype.hasOwnProperty.call(body, k)) _formSnapshot[k] = body[k];
    });

    // A CONFIG INVARIANT declined the write (A1: remote access with no credential). Two things
    // have to happen and only one of them is the message: the control must stop showing the
    // value that did NOT land. Without this the checkbox stays ticked over a config that reads
    // false — the same "ticked box for a setting that is not in force" the amber panel exists
    // to end, reintroduced by the one branch that never resets a field.
    const refusedRows = report.filter(function (r) { return r && r.outcome === 'refused'; });
    refusedRows.forEach(function (r) {
      const el = document.getElementById('cfg_' + String(r.key).replace(/[^a-zA-Z0-9_]/g, '_'));
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!r.effective;
      else el.value = Array.isArray(r.effective) ? r.effective.join(', ') : String(r.effective == null ? '' : r.effective);
      _formSnapshot[r.key] = r.effective;
    });

    if (refusedRows.length) {
      // The reason is the product here — it names the precondition the operator has to meet.
      // "Refused", not "failed": nothing broke, the request was understood and declined.
      say(T('settings.save.refused', 'Refused: {keys} — {reasons}', {
        keys: refusedRows.map(function (r) { return r.key; }).join(', '),
        reasons: refusedRows.map(function (r) { return r.reason; }).join(' · '),
      }), true);
    } else if (badLocks.length) {
      say(T('settings.save.cannot_lock', 'Cannot lock (not auto-tune settings): {keys}', { keys: badLocks.join(', ') }), true);
    } else if (rejected.length) {
      say(T('settings.save.rejected', 'Saved {n}, REJECTED: {keys}', { n: saved.length, keys: rejected.join(', ') }), true);
    } else if (adjusted.length || notInForce.length) {
      // C4 — THE ORDER USED TO HIDE ONE BEHIND THE OTHER. `else if (adjusted.length)` came
      // first, so a save that clamped one key AND had another reverted reported only the
      // clamp. The amber panel did list both, so it was mitigated rather than silent — but
      // the toast reads as a complete account of the save and was not one. Both outcomes are
      // real, both are reported, and neither branch can swallow the other now.
      //
      // The value on disk is NOT the value that was typed. Green "Settings saved (90)" while
      // 500 became 50 is the defect this branch exists to end — name the key and both values,
      // and put the STORED value back in the field. Leaving 500 on screen next to 50 on disk
      // would just relocate the same lie into the control itself.
      adjusted.forEach(function (a) {
        const el = document.getElementById('cfg_' + String(a.key).replace(/[^a-zA-Z0-9_]/g, '_'));
        if (!el) return;
        if (el.type === 'checkbox') el.checked = !!a.stored;
        else el.value = Array.isArray(a.stored) ? a.stored.join(', ') : String(a.stored);
        _formSnapshot[a.key] = _readField({ key: a.key, type: el.type === 'checkbox' ? 'boolean' : (el.type === 'number' ? 'number' : (el.dataset.list ? 'list' : 'string')) });
      });
      const bits = [];
      if (notInForce.length) {
        // Saved to disk, and reverted before anything reads it — the exact case that used to
        // read as an unqualified success. Name the OWNER here rather than assuming auto-tune:
        // other owners revert keys too, and sending that operator to the auto-tune lock
        // list would be a confident, actionable, wrong instruction.
        const owners = [];
        notInForce.forEach(function (r) {
          const o = r.owner || 'unknown';
          if (owners.indexOf(o) === -1) owners.push(o);
        });
        bits.push(T('settings.save.not_in_force', 'NOT in force: {keys} — held by {owners}', {
          keys: notInForce.map(function (r) { return r.key; }).join(', '),
          owners: owners.join(', '),
        }));
      }
      if (adjusted.length) {
        bits.push(adjusted.map(function (a) {
          return T('settings.save.adjusted_item', '{key} was {reason} to {stored} (you entered {requested})', {
            key: a.key, reason: a.reason, stored: JSON.stringify(a.stored), requested: JSON.stringify(a.requested),
          });
        }).join('; '));
      }
      say(T('settings.save.saved_but', 'Saved, but {details}. See the details below the buttons.', { details: bits.join(' · ') }), true);
    } else if (saved.length) {
      say((saved.length === 1
        ? T('settings.save.saved_one', 'Saved {n} change: {keys}', { n: saved.length, keys: saved.join(', ') })
        : T('settings.save.saved_many', 'Saved {n} changes: {keys}', { n: saved.length, keys: saved.join(', ') })), false);
    } else {
      say(T('settings.save.nothing_saved', 'Nothing was saved'), true);
    }
    // Re-render when the lock set changed, so the ownership badges flip to "locked — your
    // value wins" immediately instead of lying until the next panel open. Report the locks
    // that were TAKEN as well as any refused — reporting only failures made a successful lock
    // look like nothing happened.
    const before = prevLocked;
    const after = (body.auto_tune_locked_keys || before).slice().sort();
    const newlyLocked = after.filter(function (k) { return before.indexOf(k) === -1; });
    const unlocked = before.filter(function (k) { return after.indexOf(k) === -1; });
    if (!badLocks.length && !rejected.length && (newlyLocked.length || unlocked.length)) {
      const bits = [];
      if (newlyLocked.length) bits.push(T('settings.save.locked', 'locked {keys} — auto-tune will leave your value alone', { keys: newlyLocked.join(', ') }));
      if (unlocked.length) bits.push(T('settings.save.unlocked', 'unlocked {keys} — auto-tune owns it again', { keys: unlocked.join(', ') }));
      // APPEND when a warning is already on screen. Overwriting it would trade one silence
      // (locks never reported) for another (the clamp warning wiped by the lock confirmation)
      // whenever the same save did both.
      const warned = adjusted.length || notInForce.length;
      say(warned ? (msg && msg.textContent ? msg.textContent + ' · ' + bits.join(' · ') : bits.join(' · ')) : bits.join(' · '),
          !!warned);
    }
    if (!badLocks.length && before.join(',') !== after.join(',')) {
      try { await openSettings(); } catch (_e) { /* panel stays as-is */ }
    }
  } catch (e) {
    say(T('settings.save_failed', 'Save failed'), true);
  }
}

export async function laylaLoadOptionalFeatures() {
  const box = document.getElementById('optional-features-list');
  if (!box) return;
  box.textContent = T('settings.loading', 'Loading…');
  try {
    const r = await fetch('/settings/optional_features');
    const d = await r.json();
    if (!d.ok || !d.features) { box.textContent = T('settings.could_not_load', 'Could not load'); return; }
    box.innerHTML = d.features.map(function (f) {
      const st = f.installed ? 'ok' : '—';
      return '<div style="margin:4px 0;padding:4px;border-bottom:1px solid rgba(255,255,255,0.08)">' + st + ' <strong>' + escapeHtml(f.id) + '</strong> — ' + escapeHtml(f.label) +
        (!f.installed ? ' <button type="button" class="settings-save" style="padding:2px 8px;font-size:0.65rem" data-fid="' + escapeHtml(f.id) + '">' + escapeHtml(T('settings.optional.install', 'Install')) + '</button>' : '') + '</div>';
    }).join('');
    box.querySelectorAll('button[data-fid]').forEach(function (btn) {
      btn.onclick = function () { laylaInstallFeature(btn.getAttribute('data-fid')); };
    });
  } catch (e) { box.textContent = T('settings.error', 'Error'); }
}

export async function laylaInstallFeature(fid) {
  if (!fid || !(await laylaConfirm(T('settings.optional.install_confirm', 'Install feature {id} via pip (allowlisted packages)?', { id: fid })))) return;
  try {
    const r = await fetch('/settings/install_feature', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ feature_id: fid }) });
    const d = await r.json();
    const note = d.ok ? T('settings.optional.install_finished', 'Install finished') : ((d.pip_attempt && d.pip_attempt.error) || d.error || T('settings.failed', 'failed'));
    showToast(note);
    laylaLoadOptionalFeatures();
  } catch (e) { showToast(T('settings.optional.install_failed', 'Install failed')); }
}

export async function laylaImportChat() {
  const ta = document.getElementById('import-chat-text');
  const title = document.getElementById('import-chat-title');
  const msg = document.getElementById('import-chat-msg');
  const text = (ta && ta.value || '').trim();
  if (!text) { if (msg) msg.textContent = T('settings.import.paste_first', 'Paste export text first'); return; }
  try {
    const r = await fetch('/knowledge/import_chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format: 'whatsapp', text: text, title: (title && title.value) || 'import' }) });
    const d = await r.json();
    if (msg) msg.textContent = d.ok ? T('settings.import.saved', 'Saved {path}', { path: d.path }) : (d.error || T('settings.failed', 'failed'));
    if (d.ok && ta) ta.value = '';
  } catch (e) { if (msg) msg.textContent = T('settings.request_failed', 'Request failed'); }
}

export async function laylaGitUndoCheckpoint() {
  const winp = document.getElementById('admin-undo-workspace');
  const ws = (winp && winp.value || '').trim();
  const msg = document.getElementById('admin-undo-msg');
  if (!ws) { if (msg) msg.textContent = T('settings.admin.set_workspace', 'Set workspace path'); return; }
  if (!(await laylaConfirm(T('settings.admin.undo_confirm', 'Revert the last Layla checkpoint commit in this repo?')))) return;
  try {
    const r = await fetch('/settings/git_undo_checkpoint', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_root: ws }) });
    const d = await r.json();
    if (msg) msg.textContent = d.ok ? T('settings.admin.reverted', 'Reverted') : (d.error || T('settings.failed', 'failed'));
  } catch (e) { if (msg) msg.textContent = T('settings.request_failed', 'Request failed'); }
}

// ── Workspace presets ───────────────────────────────────────────────────────
function _workspacePresetStorageKey() {
  try {
    const h = (typeof location !== 'undefined' && location.host) ? String(location.host).replace(/[^a-z0-9]/gi, '_') : '';
    return 'layla_workspace_presets' + (h ? ('_' + h) : '');
  } catch (_) { return 'layla_workspace_presets'; }
}

function _loadWorkspacePresets() {
  try {
    const raw = localStorage.getItem(_workspacePresetStorageKey());
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) return arr.filter(function (p) { return typeof p === 'string' && p.trim(); });
    }
  } catch (_) {}
  return [];
}

function _saveWorkspacePresets(paths) {
  try {
    localStorage.setItem(_workspacePresetStorageKey(), JSON.stringify(paths));
  } catch (_) {}
}

export function refreshWorkspacePresetsDropdown() {
  const sel = document.getElementById('workspace-presets');
  if (!sel) return;
  const presets = _loadWorkspacePresets();
  const inp = document.getElementById('workspace-path');
  const cur = inp ? (inp.value || '').trim() : '';
  sel.innerHTML = '<option value="">' + escapeHtml(T('settings.workspace.saved_paths', '— saved paths —')) + '</option>';
  presets.forEach(function (p) {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p;
    if (p === cur) opt.selected = true;
    sel.appendChild(opt);
  });
}

export function addWorkspacePreset() {
  const inp = document.getElementById('workspace-path');
  const v = inp ? (inp.value || '').trim() : '';
  if (!v) return;
  const presets = _loadWorkspacePresets();
  if (presets.indexOf(v) < 0) {
    presets.push(v);
    _saveWorkspacePresets(presets);
    refreshWorkspacePresetsDropdown();
    showToast(T('settings.workspace.saved_preset', 'Saved preset'));
  }
}

export function removeWorkspacePreset() {
  const inp = document.getElementById('workspace-path');
  const v = inp ? (inp.value || '').trim() : '';
  if (!v) return;
  const presets = _loadWorkspacePresets();
  const idx = presets.indexOf(v);
  if (idx >= 0) {
    presets.splice(idx, 1);
    _saveWorkspacePresets(presets);
    refreshWorkspacePresetsDropdown();
    showToast(T('settings.workspace.removed_preset', 'Removed preset'));
  }
}

export function onWorkspacePresetSelect() {
  const sel = document.getElementById('workspace-presets');
  const inp = document.getElementById('workspace-path');
  if (!sel || !inp) return;
  const v = sel.value;
  if (v) {
    inp.value = v;
    try { if (typeof window.refreshOptionDependencies === 'function') window.refreshOptionDependencies(); } catch (_) {}
  }
}

// ── Relationship codex ──────────────────────────────────────────────────────
// Relationship codex — per-workspace .layla/relationship_codex.json. The backend route is
// /codex/relationship (workspace-scoped, returns {ok, data}); this panel was wired to a
// non-existent /codex/user endpoint AND a non-existent #codex-user-data element, so Load did
// nothing. Now it targets the real textarea + endpoint and sources the Settings workspace path.
function _codexWorkspace() {
  const el = document.getElementById('workspace-path');
  return (el && el.value || '').trim();
}

export async function refreshRelationshipCodex() {
  const ta = document.getElementById('relationship-codex-json');
  const status = document.getElementById('relationship-codex-status');
  if (!ta) return;
  const ws = _codexWorkspace();
  if (!ws) {
    if (status) status.textContent = T('settings.codex.set_workspace_load', 'Set a workspace path in Library → Workspace first, then Load.');
    return;
  }
  if (status) status.textContent = T('settings.loading', 'Loading…');
  try {
    const r = await fetch('/codex/relationship?workspace_root=' + encodeURIComponent(ws));
    const d = await r.json();
    if (d && d.ok) {
      ta.value = JSON.stringify(d.data || { entities: {} }, null, 2);
      if (status) status.textContent = T('settings.codex.loaded_from', 'Loaded from {path}', { path: (d.path || ws) });
    } else {
      if (status) status.textContent = T('settings.error_reason', 'Error: {why}', { why: ((d && d.error) || r.status) });
    }
  } catch (e) {
    if (status) status.textContent = T('settings.error_reason', 'Error: {why}', { why: (e && e.message ? e.message : e) });
  }
}

export async function saveRelationshipCodex() {
  const ta = document.getElementById('relationship-codex-json');
  const status = document.getElementById('relationship-codex-status');
  if (!ta) return;
  const ws = _codexWorkspace();
  if (!ws) {
    if (status) status.textContent = T('settings.codex.set_workspace', 'Set a workspace path in Library → Workspace first.');
    return;
  }
  const raw = (ta.value || '').trim();
  if (!raw) return;
  let payload;
  try { payload = JSON.parse(raw); } catch (_) {
    if (status) status.textContent = T('settings.codex.invalid_json', 'Invalid JSON — fix and try again.');
    return;
  }
  if (payload && typeof payload === 'object' && !payload.entities) payload.entities = {};
  try {
    const res = await fetch('/codex/relationship?workspace_root=' + encodeURIComponent(ws), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(function () { return {}; });
    if (status) status.textContent = (data && data.ok) ? T('settings.saved', 'Saved') : T('settings.save_failed_reason', 'Save failed: {why}', { why: ((data && data.error) || res.status) });
    if (data && data.ok && typeof showToast === 'function') showToast(T('settings.codex.saved', 'Saved codex'));
  } catch (e) {
    if (status) status.textContent = T('settings.codex.save_error', 'Save error: {why}', { why: ((e && e.message) || e) });
  }
}

// ── Settings presets + appearance ───────────────────────────────────────────
/**
 * Apply a runtime preset — and say how much of it is actually in force.
 *
 * C1, the client half. This toasted "Preset applied: potato" in green off `d.ok`, and the
 * server answered ok:true with the preset's own key list regardless of what the config did
 * with those keys. Driven on a CPU box, "potato" reported 16 keys applied while n_batch,
 * max_runtime_seconds and completion_max_tokens were all reverted by auto-tune before
 * anything read them: the preset whose entire purpose is to make the box behave like a
 * potato could not, and the product said it had.
 */
export async function applySettingsPreset(name) {
  try {
    const r = await fetch('/settings/preset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: name }),
    });
    const d = await r.json().catch(function () { return {}; });
    if (!r.ok || !d.ok) { showToast(d.error || T('settings.preset.failed', 'Preset failed')); return; }
    const nif = d.not_in_force || [];
    if (nif.length) {
      const owners = [];
      (d.report || []).forEach(function (row) {
        if (nif.indexOf(row.key) === -1) return;
        const o = row.owner || T('settings.nif.owner_unknown', 'unknown');
        if (owners.indexOf(o) === -1) owners.push(o);
      });
      showToast(T('settings.preset.partial', 'Preset {name}: {applied} of {total} settings in force — {keys} held by {owners}', {
        name: name,
        applied: (d.applied || []).length,
        total: ((d.applied || []).length + nif.length),
        keys: nif.join(', '),
        owners: owners.join(', '),
      }));
    } else {
      showToast(T('settings.preset.applied', 'Preset applied: {name} ({n} settings)', { name: name, n: (d.applied || []).length }));
    }
    // The preset just wrote a large slice of the config; whatever it could not put in force
    // belongs in the panel, not only in a toast that fades.
    await _loadNotInForce();
  } catch (_) {
    showToast(T('settings.preset.failed', 'Preset failed'));
  }
}

// ── Appearance panel (BL-335 / BL-352 / BL-366) ──────────────────────────────────────────────────────
//
// This panel toasted "Appearance saved" and saved NOTHING, at four layers:
//   1. it read #app-font-size / #app-anim-level, which existed in no markup   -> undefined
//   2. `if (fontSize)` swallowed the undefined                                -> body = {}
//   3. it POSTed ui_font_size / ui_animation_level to /settings, and neither key is in
//      config_schema, so runtime_safety dropped them and still answered ok:true
//   4. nothing anywhere read either key back
// ...and it toasted success off `d.ok` regardless. Every layer looked careful. Together they were a lie,
// and the casualty was the TEXT-SIZE ACCESSIBILITY CONTROL.
//
// A fifth layer went unreported: the four controls that DID exist in the markup (avatar seed, avatar
// style, chat lite mode, decision trace) were read by NO javascript at all — the button never saved
// them either, and nothing populated them when the panel opened. Six controls, none wired.
//
// Now: /settings/appearance (BL-352 — purpose-built for non-schema UI keys, and had zero callers until
// now), all six controls, and the toast reports what the SERVER says it saved rather than assuming.

/** Apply appearance to the live document. Font size scales the ~259 rem-based sizes in layla.css off
 *  the root font-size, which is what makes this a real accessibility control and not a stored no-op. */
export function applyAppearance(fontSize, animLevel) {
  try {
    const px = parseInt(fontSize, 10);
    if (isFinite(px) && px >= 10 && px <= 32) document.documentElement.style.fontSize = px + 'px';
    if (animLevel) document.documentElement.setAttribute('data-anim', String(animLevel));
  } catch (_e) { console.debug('applyAppearance:', _e); }
}

/** Populate the panel from the server and apply the saved appearance. */
export async function loadAppearance() {
  try {
    const r = await fetch('/settings/appearance');
    const d = await r.json().catch(function () { return {}; });
    const set = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.value = String(val); };
    const check = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };
    set('app-font-size', d.ui_font_size || 16);
    set('app-anim-level', d.ui_animation_level || 'full');
    set('ui_avatar_seed', d.ui_avatar_seed);
    set('ui_avatar_style', d.ui_avatar_style);
    check('chat_lite_mode', d.chat_lite_mode);
    check('ui_decision_trace_enabled', d.ui_decision_trace_enabled);
    applyAppearance(d.ui_font_size || 16, d.ui_animation_level || 'full');
    return d;
  } catch (_e) {
    console.debug('loadAppearance:', _e);
    return {};
  }
}

export async function saveAppearanceLite() {
  const msg = document.getElementById('appearance-save-msg');
  const val = (id) => { const el = document.getElementById(id); return el ? el.value : undefined; };
  const chk = (id) => { const el = document.getElementById(id); return el ? !!el.checked : undefined; };

  const body = {};
  const fontSize = val('app-font-size');
  const animLevel = val('app-anim-level');
  const seed = val('ui_avatar_seed');
  const style = val('ui_avatar_style');
  const lite = chk('chat_lite_mode');
  const trace = chk('ui_decision_trace_enabled');
  if (fontSize !== undefined) body.ui_font_size = parseInt(fontSize, 10);
  if (animLevel !== undefined) body.ui_animation_level = animLevel;
  if (seed !== undefined) body.ui_avatar_seed = seed;
  if (style !== undefined) body.ui_avatar_style = style;
  if (lite !== undefined) body.chat_lite_mode = lite;
  if (trace !== undefined) body.ui_decision_trace_enabled = trace;

  if (!Object.keys(body).length) {
    // The old code's silent failure mode, made loud. If the controls vanish again, SAY so.
    if (msg) msg.textContent = T('settings.appearance.nothing_to_save', 'Nothing to save — appearance controls are missing.');
    showToast(T('settings.appearance.controls_missing', 'Appearance controls are missing — nothing was saved'));
    return;
  }

  try {
    const r = await fetch('/settings/appearance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json().catch(function () { return {}; });
    const saved = d.saved || [];
    const rejected = d.rejected || [];

    // Report what the SERVER saved. Never "saved" over a no-op again.
    if (rejected.length) {
      const t = T('settings.save.rejected', 'Saved {n}, REJECTED: {keys}', { n: saved.length, keys: rejected.join(', ') });
      if (msg) msg.textContent = t;
      showToast(t);
    } else if (saved.length) {
      applyAppearance(body.ui_font_size, body.ui_animation_level);
      const t = (saved.length === 1
        ? T('settings.appearance.saved_one', 'Appearance saved ({n} setting)', { n: saved.length })
        : T('settings.appearance.saved_many', 'Appearance saved ({n} settings)', { n: saved.length }));
      if (msg) msg.textContent = t;
      showToast(t);
    } else {
      const t = d.error ? T('settings.save_failed_reason', 'Save failed: {why}', { why: d.error }) : T('settings.appearance.save_failed_nothing', 'Save failed — nothing was written');
      if (msg) msg.textContent = t;
      showToast(t);
    }
  } catch (e) {
    if (msg) msg.textContent = T('settings.save_failed_reason', 'Save failed: {why}', { why: e });
    showToast(T('settings.save_failed', 'Save failed'));
  }
}

// ── Knowledge packs (v1.7.5) ─────────────────────────────────────────────────
// Domain knowledge packs Layla indexes for retrieval. GET /knowledge/packs lists the packs, the
// named presets, the current enabled preset and the indexed-chunk count; POST /knowledge/packs sets
// the enabled set (an explicit list OR a named preset) and re-indexes. `core` is always on and its
// checkbox is locked. The panel degrades to "Knowledge packs unavailable" if the API is not there —
// the endpoint ships in parallel, so a client that predates it must not throw.
let _knowledgePresets = {};

/** approx_bytes → a short human size, e.g. 34816 → "34 KB". */
function _fmtBytes(n) {
  const b = Number(n) || 0;
  if (b < 1024) return b + ' B';
  if (b < 1024 * 1024) return Math.round(b / 1024) + ' KB';
  return (b / (1024 * 1024)).toFixed(1) + ' MB';
}

/** "1,240 chunks indexed" — thousands-separated so a five-figure corpus is readable at a glance. */
function _fmtChunks(n) {
  return T('settings.knowledge.chunks_indexed', '{n} chunks indexed', { n: (Number(n) || 0).toLocaleString() });
}

/** The ticked pack ids, `core` always included (it is locked on, so its box may be disabled). */
function _selectedKnowledgePacks() {
  const out = [];
  document.querySelectorAll('#knowledge-packs-list input[type="checkbox"][data-pack]').forEach(function (cb) {
    const pid = cb.getAttribute('data-pack');
    if (cb.checked && out.indexOf(pid) === -1) out.push(pid);
  });
  if (out.indexOf('core') === -1) out.unshift('core');
  return out;
}

/**
 * Populate the Knowledge packs panel from the server. Called on panel open (openSettings) — same
 * fire-and-forget shape as loadAppearance()/loadPhoneAccess(). A failed GET renders a plain
 * "unavailable" line rather than throwing, so a client running against an older backend still opens.
 */
export async function loadKnowledgePacks() {
  const list = document.getElementById('knowledge-packs-list');
  const status = document.getElementById('knowledge-packs-status');
  const sel = document.getElementById('knowledge-preset');
  const btn = document.getElementById('knowledge-packs-save-btn');
  if (!list) return;
  list.textContent = T('settings.loading', 'Loading…');
  if (status) status.textContent = '';
  try {
    const r = await fetch('/knowledge/packs');
    const d = await r.json().catch(function () { return {}; });
    if (!r.ok || !d || !d.ok || !Array.isArray(d.packs)) {
      list.textContent = T('settings.knowledge.unavailable', 'Knowledge packs unavailable');
      if (btn) btn.disabled = true;
      return;
    }
    _knowledgePresets = d.presets || {};
    if (btn) btn.disabled = false;
    // Preset dropdown: one option per named preset the server offers, plus an explicit Custom for a
    // hand-picked set. Selecting the current preset (d.preset) if the server reported one, else Custom.
    if (sel) {
      const cur = d.preset || '';
      let opts = Object.keys(_knowledgePresets).map(function (name) {
        return '<option value="' + escapeHtml(name) + '"' + (name === cur ? ' selected' : '') + '>' + escapeHtml(humanizeKey(name)) + '</option>';
      }).join('');
      opts += '<option value="custom"' + (cur ? '' : ' selected') + '>' + escapeHtml(T('settings.knowledge.custom', 'Custom')) + '</option>';
      sel.innerHTML = opts;
    }
    // One labelled checkbox row per pack: bold title (+ "(always on)" for core), a one-line summary,
    // and a muted size · doc-count line. Checked = enabled; core is checked and disabled.
    list.innerHTML = d.packs.map(function (p) {
      const cid = 'kpack_' + String(p.id).replace(/[^a-zA-Z0-9_]/g, '_');
      const isCore = p.id === 'core';
      const checked = (isCore || p.enabled) ? 'checked' : '';
      const disabled = isCore ? 'disabled' : '';
      const meta = escapeHtml(_fmtBytes(p.approx_bytes)) + ' · ' +
        escapeHtml(T('settings.knowledge.doc_count', '{n} docs', { n: (p.doc_count || 0) }));
      return '<div class="settings-row settings-section" style="border-left:3px solid var(--asp);padding-left:8px">' +
        '<label for="' + cid + '" style="display:flex;align-items:flex-start;gap:8px;font-size:0.8rem;text-transform:none;color:var(--text);font-weight:600">' +
        '<input type="checkbox" id="' + cid + '" data-pack="' + escapeHtml(String(p.id)) + '" data-on-change="onKnowledgePackToggle" ' + checked + ' ' + disabled + '/>' +
        '<span>' + escapeHtml(p.title || p.id) +
        (isCore ? ' <span class="hint" style="font-weight:400">' + escapeHtml(T('settings.knowledge.always_on', '(always on)')) + '</span>' : '') +
        '</span></label>' +
        '<div class="hint" style="margin-left:24px">' + escapeHtml(p.summary || '') + '</div>' +
        '<div class="hint" style="margin-left:24px;color:var(--text-faint)">' + meta + '</div>' +
        '</div>';
    }).join('');
    if (status) status.textContent = _fmtChunks(d.indexed_chunks);
  } catch (_e) {
    list.textContent = T('settings.knowledge.unavailable', 'Knowledge packs unavailable');
    if (btn) btn.disabled = true;
  }
}
try { window.loadKnowledgePacks = loadKnowledgePacks; } catch (_e) { /* no-op */ }

/** Picking a preset checks exactly its packs (core stays on). 'custom' leaves the boxes as-is. */
export function onKnowledgePresetSelect(name) {
  if (!name || name === 'custom') return;
  const packs = _knowledgePresets[name] || [];
  document.querySelectorAll('#knowledge-packs-list input[type="checkbox"][data-pack]').forEach(function (cb) {
    const pid = cb.getAttribute('data-pack');
    if (pid === 'core') { cb.checked = true; return; }   // locked on regardless of the preset
    cb.checked = packs.indexOf(pid) !== -1;
  });
}
try { window.onKnowledgePresetSelect = onKnowledgePresetSelect; } catch (_e) { /* no-op */ }

/** Editing a checkbox by hand means the set no longer matches a named preset → show Custom. */
export function onKnowledgePackToggle() {
  const sel = document.getElementById('knowledge-preset');
  if (sel) sel.value = 'custom';   // programmatic .value does not fire change → no recursion
}
try { window.onKnowledgePackToggle = onKnowledgePackToggle; } catch (_e) { /* no-op */ }

// ── Approvals & safety (knowledge-presets-1.7.5) ──────────────────────────────
// A Claude-Code-style permission control so the user isn't approving every action, with a
// visible safety guardrail. A single mode selector maps to three config keys saved through the
// normal POST /settings path:
//   tool_approval_bypass (bool)  — auto-approve tools with no prompt
//   safe_mode (bool, default on) — HARD FLOOR: destructive tools (writes/shell/run_python/git/
//                                  sends) STILL require approval even when bypass is on
//   auto_approve_tools (list)    — auto-approve ONLY these named tools, subject to the same floors
// All three are remote-protected server-side, so a save from a remote client is rejected and this
// panel reports which keys were refused rather than claiming a silent success.
//
// The five tools offered for per-tool auto-approve are privacy/interaction tools — none of them
// write files, run code, or send messages — so trusting them cannot bypass the destructive floor.
const _APPROVAL_SAFE_TOOLS = ['browser_click', 'browser_fill', 'clipboard_read', 'clipboard_write', 'screenshot_desktop'];

// mode → the exact config combo it writes. `trusted` fills auto_approve_tools from the checklist
// at save time; the others set a fixed combo. See saveApprovalsSafety.
const _APPROVAL_MODE_COMBOS = {
  ask:     { tool_approval_bypass: false, safe_mode: true, auto_approve_tools: [] },
  trusted: { tool_approval_bypass: false, safe_mode: true },  // auto_approve_tools = checked tools
  guarded: { tool_approval_bypass: true,  safe_mode: true },
  full:    { tool_approval_bypass: true,  safe_mode: false },
};

/** Derive the selector mode from the three stored keys. `safe_mode` defaults ON (true) when unset. */
function _deriveApprovalMode(cfg) {
  const bypass = !!(cfg && cfg.tool_approval_bypass);
  const safe = !(cfg && cfg.safe_mode === false);   // default true
  const tools = Array.isArray(cfg && cfg.auto_approve_tools) ? cfg.auto_approve_tools : [];
  if (bypass && !safe) return 'full';
  if (bypass && safe) return 'guarded';
  if (!bypass && safe && tools.length) return 'trusted';
  if (!bypass && safe && !tools.length) return 'ask';
  return 'custom';   // e.g. bypass off + safe_mode off — not one of the four presets
}

/** The value of the checked mode radio, or 'ask' if none is checked. */
function _selectedApprovalMode() {
  const el = document.querySelector('input[name="approval-mode"]:checked');
  return el ? el.value : 'ask';
}

/** Check the radio for `mode`. 'custom' checks the disabled read-only Custom radio. */
function _setApprovalRadio(mode) {
  const el = document.querySelector('input[name="approval-mode"][value="' + mode + '"]');
  if (el) el.checked = true;
}

/** Show the trusted-tools checklist for trusted/custom, and the guarded/full notes for their modes. */
function _reflectApprovalMode(mode) {
  const show = function (id, on) { const el = document.getElementById(id); if (el) el.hidden = !on; };
  show('approval-trusted-tools', mode === 'trusted' || mode === 'custom');
  show('approval-guarded-note', mode === 'guarded');
  show('approval-full-note', mode === 'full');
}

/**
 * Populate the Approvals & safety panel from the server on panel open (openSettings) — same
 * fire-and-forget shape as loadKnowledgePacks()/loadAppearance(). GETs /settings, derives the
 * mode from the three keys, checks the matching radio, fills the tool checklist, and reveals the
 * right notes. A failed GET leaves the static markup as-is rather than throwing.
 */
export async function loadApprovalsSafety() {
  const wrap = document.getElementById('approvals-safety');
  if (!wrap) return;
  try {
    const r = await fetch('/settings');
    const cfg = await r.json().catch(function () { return {}; });
    const tools = Array.isArray(cfg && cfg.auto_approve_tools) ? cfg.auto_approve_tools : [];
    _APPROVAL_SAFE_TOOLS.forEach(function (name) {
      const cb = document.getElementById('approve_tool_' + name);
      if (cb) cb.checked = tools.indexOf(name) !== -1;
    });
    const mode = _deriveApprovalMode(cfg);
    _setApprovalRadio(mode);
    _reflectApprovalMode(mode);
  } catch (_e) {
    console.debug('loadApprovalsSafety:', _e);
  }
}
try { window.loadApprovalsSafety = loadApprovalsSafety; } catch (_e) { /* no-op */ }

/** A mode radio changed — reveal the checklist/notes for the newly chosen mode. */
export function onApprovalModeChange(mode) {
  _reflectApprovalMode(mode || _selectedApprovalMode());
}
try { window.onApprovalModeChange = onApprovalModeChange; } catch (_e) { /* no-op */ }

/**
 * Persist the chosen mode's config combo through POST /settings — the same save path the rest of
 * this file uses. Reports what the SERVER did: the three keys are remote-protected, so a save from
 * a remote client comes back with `rejected` and this says which keys were refused rather than
 * printing a green success over a write that never landed.
 */
export async function saveApprovalsSafety() {
  const msg = document.getElementById('approvals-save-msg');
  const say = function (text, isErr) {
    if (msg) {
      msg.style.display = 'inline';
      msg.textContent = text;
      msg.setAttribute('data-kind', isErr ? 'warn' : 'ok');
      if (!isErr) setTimeout(function () { msg.style.display = 'none'; }, 2200);
    }
    showToast(text);
  };
  const mode = _selectedApprovalMode();
  if (mode === 'custom') {
    // Custom is a read-only display of a config that matches no preset. There is no combo to write.
    say(T('settings.approvals.pick_mode', 'Pick a mode above to apply a preset.'), true);
    return;
  }
  const combo = _APPROVAL_MODE_COMBOS[mode];
  if (!combo) { say(T('settings.approvals.pick_mode', 'Pick a mode above to apply a preset.'), true); return; }
  const body = { tool_approval_bypass: combo.tool_approval_bypass, safe_mode: combo.safe_mode };
  if (mode === 'ask') {
    body.auto_approve_tools = [];
  } else if (mode === 'trusted') {
    const picked = [];
    _APPROVAL_SAFE_TOOLS.forEach(function (name) {
      const cb = document.getElementById('approve_tool_' + name);
      if (cb && cb.checked) picked.push(name);
    });
    body.auto_approve_tools = picked;
  }
  const btn = document.getElementById('approvals-save-btn');
  if (btn) btn.disabled = true;
  try {
    const r = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json().catch(function () { return {}; });
    const rejected = (d && d.rejected) || [];
    if (!r.ok || !d || !d.ok) {
      if (rejected.length) {
        say(T('settings.approvals.rejected', 'Rejected: {keys} — a remote client cannot change approval or safety settings.', { keys: rejected.join(', ') }), true);
      } else {
        say(T('settings.save.failed_reason', 'Save failed — {why}', { why: ((d && d.error) || ('HTTP ' + r.status)) }), true);
      }
      return;
    }
    const label = T('settings.approvals.mode_' + mode, mode);
    say(T('settings.approvals.saved', 'Saved — approval mode: {mode}', { mode: label }), false);
  } catch (_e) {
    say(T('settings.save_failed', 'Save failed'), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}
try { window.saveApprovalsSafety = saveApprovalsSafety; } catch (_e) { /* no-op */ }

/**
 * POST the selected packs, then reflect what the SERVER says is enabled + the fresh chunk count.
 * The button is disabled for the round-trip (re-indexing can take a moment), showing "Re-indexing…"
 * then "Saved — N chunks indexed". Same honesty rule as the rest of this file: render the effective
 * enabled set the server returns, not the boxes we posted.
 */
export async function saveKnowledgePacks() {
  const btn = document.getElementById('knowledge-packs-save-btn');
  const msg = document.getElementById('knowledge-packs-save-msg');
  const status = document.getElementById('knowledge-packs-status');
  const packs = _selectedKnowledgePacks();
  if (btn) btn.disabled = true;
  if (msg) msg.textContent = T('settings.knowledge.reindexing', 'Re-indexing…');
  try {
    const r = await fetch('/knowledge/packs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ packs: packs }),
    });
    const d = await r.json().catch(function () { return {}; });
    if (!r.ok || !d || !d.ok) {
      if (msg) msg.textContent = T('settings.save_failed_reason', 'Save failed: {why}', { why: ((d && d.error) || ('HTTP ' + r.status)) });
      return;
    }
    // The server's effective enabled set wins over the click, and core is always on.
    const enabled = Array.isArray(d.enabled) ? d.enabled : packs;
    document.querySelectorAll('#knowledge-packs-list input[type="checkbox"][data-pack]').forEach(function (cb) {
      const pid = cb.getAttribute('data-pack');
      cb.checked = pid === 'core' || enabled.indexOf(pid) !== -1;
    });
    if (status) status.textContent = _fmtChunks(d.indexed_chunks);
    if (msg) msg.textContent = T('settings.knowledge.saved', 'Saved — {n} chunks indexed', { n: (Number(d.indexed_chunks) || 0).toLocaleString() });
    showToast(T('settings.knowledge.saved_toast', 'Knowledge packs saved'));
  } catch (_e) {
    if (msg) msg.textContent = T('settings.save_failed', 'Save failed');
  } finally {
    if (btn) btn.disabled = false;
  }
}
try { window.saveKnowledgePacks = saveKnowledgePacks; } catch (_e) { /* no-op */ }

export async function runKnowledgeIngest() {
  // #km-source / #km-ingest-list — NOT #ingest-path / #ingest-msg, which exist nowhere. This read null,
  // bailed at the empty-path guard, and wrote its own error message to a null element: nothing happened at
  // all, not even the error. Knowledge could not be added through the UI by any route.
  const inp = document.getElementById('km-source');
  const msg = document.getElementById('km-ingest-list');
  const path = inp ? (inp.value || '').trim() : '';
  if (!path) {
    if (msg) msg.textContent = T('settings.ingest.enter_path', 'Enter a folder path inside your workspace');
    return;
  }
  if (msg) msg.textContent = T('settings.ingest.ingesting', 'Ingesting…');
  try {
    const r = await fetch('/intelligence/kb/build/directory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directory: path }),
    });
    const d = await r.json().catch(function () { return {}; });
    if (msg) msg.textContent = d.ok ? T('settings.ingest.done', 'Done — {n} articles', { n: (d.articles_count || 0) }) : (d.error || T('settings.failed', 'failed'));
  } catch (e) {
    if (msg) msg.textContent = T('settings.ingest.failed', 'Ingest failed');
  }
}

export async function checkForUpdates() {
  const el = document.getElementById('update-status');
  if (el) el.textContent = T('settings.update.checking', 'Checking…');
  try {
    const r = await fetch('/update/check');
    const d = await r.json().catch(function () { return {}; });
    if (el) el.textContent = d.update_available ? T('settings.update.available', 'Update available: {version}', { version: (d.latest_version || d.latest || '') }) : T('settings.update.up_to_date', 'Up to date');
  } catch (_) {
    if (el) el.textContent = T('settings.update.could_not_check', 'Could not check');
  }
}

// ── Content policy ──────────────────────────────────────────────────────────
export async function saveContentPolicySettings() {
  const btn = document.querySelector('button[onclick*="saveContentPolicySettings"]');
  const uncEl = document.getElementById('opt-uncensored');
  const nsfwEl = document.getElementById('opt-nsfw-allowed');
  const unc = !!(uncEl && uncEl.checked);
  const nsfw = !!(nsfwEl && nsfwEl.checked);
  if (btn) btn.disabled = true;
  try {
    const r = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uncensored: unc, nsfw_allowed: nsfw }),
    });
    const d = await r.json().catch(function () { return {}; });
    showToast((d && d.ok) ? T('settings.content_policy.saved', 'Saved content policy') : T('settings.save_failed', 'Save failed'));
  } catch (_) {
    showToast(T('settings.save_failed', 'Save failed'));
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Deliberation mode selector ──────────────────────────────────────────────
// The "on" state can be any depth EXCEPT solo. solo is the single-voice off state.
const _DELIB_DEPTHS = ['auto', 'debate', 'council', 'tribunal'];

/**
 * Reflect ONE deliberation mode across every control that shows it, so the prominent
 * Aspect-panel switch + depth select and the buried Settings <select> can never disagree.
 *
 * There are now two places to change deliberation (the Aspect panel, by design — the user
 * asked for it to be easy to reach — and the deep config editor). Whichever one the user
 * touches, this is the single function that repaints the others. Programmatic .value/.checked
 * assignments do NOT fire a 'change' event, so calling this from a change handler cannot recurse.
 */
export function _syncDeliberationControls(mode) {
  const on = mode !== 'solo';
  const sel = document.getElementById('deliberation-mode-select');
  if (sel) sel.value = mode;
  const sw = document.getElementById('delib-enable');
  if (sw) sw.checked = on;
  const depth = document.getElementById('deliberation-depth-select');
  // Only assign a depth the depth-select actually offers; it has no 'solo' option, so when
  // OFF we leave its last value so turning back on resumes the same depth.
  if (depth && _DELIB_DEPTHS.indexOf(mode) >= 0) depth.value = mode;
  const depthRow = document.getElementById('aspect-delib-depth');
  if (depthRow) depthRow.hidden = !on;
}

export async function setDeliberationMode(mode) {
  const valid = ['solo', 'auto', 'debate', 'council', 'tribunal'];
  if (valid.indexOf(mode) < 0) mode = 'auto';
  // Repaint every control up front so the switch, the depth select and the buried <select>
  // move together the instant the user acts — before the server has even answered.
  _syncDeliberationControls(mode);
  try {
    const r = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deliberation_mode: mode }),
    });
    const d = await r.json().catch(function () { return {}; });
    showToast((d && d.ok) ? T('settings.deliberation.set', 'Deliberation: {mode}', { mode: mode }) : T('settings.deliberation.failed', 'Setting failed — check server logs'));
  } catch (_) {
    showToast(T('settings.deliberation.save_failed', 'Could not save deliberation mode'));
  }
}

/**
 * The prominent Aspect-panel on/off switch. ON resumes the last-picked depth (or 'auto' the
 * first time); OFF is 'solo' — a single voice. It delegates to setDeliberationMode so there is
 * exactly one writer of deliberation_mode and one place that keeps every control in sync.
 */
export function toggleDeliberation(enabled) {
  let mode = 'solo';
  if (enabled) {
    const depth = document.getElementById('deliberation-depth-select');
    const chosen = depth && depth.value;
    mode = (_DELIB_DEPTHS.indexOf(chosen) >= 0) ? chosen : 'auto';
  }
  return setDeliberationMode(mode);
}

// ── Phone access ────────────────────────────────────────────────────────────
export async function loadPhoneAccess() {
  const urlEl = document.getElementById('phone-access-url');
  const stEl = document.getElementById('phone-access-status');
  if (urlEl) urlEl.textContent = T('settings.loading', 'Loading…');
  if (stEl) stEl.textContent = '';
  try {
    const proto = location.protocol || 'http:';
    const host = location.hostname || '127.0.0.1';
    const port = location.port ? (':' + location.port) : '';
    const url = proto + '//' + host + port + '/ui';
    if (urlEl) urlEl.textContent = url;
    if (stEl) stEl.textContent = (host === '127.0.0.1' || host === 'localhost')
      ? T('settings.phone.tip_lan', 'Tip: for LAN access, start Layla with --host 0.0.0.0 and use your PC IP address.')
      : T('settings.phone.tip_open', 'If this is your LAN IP, open it on your phone (same WiFi).');
  } catch (e) {
    if (urlEl) urlEl.textContent = T('settings.phone.no_url', '(could not compute URL)');
    if (stEl) stEl.textContent = String(e && e.message ? e.message : e);
  }
}

export async function copyPhoneUrl() {
  const url = (document.getElementById('phone-access-url') || {}).textContent || '';
  const trimmed = url.trim();
  if (!trimmed) return;
  try {
    await navigator.clipboard.writeText(trimmed);
    showToast(T('settings.copied', 'Copied'));
  } catch (_) {
    try {
      const ta = document.createElement('textarea');
      ta.value = trimmed;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast(T('settings.copied', 'Copied'));
    } catch (_2) {
      showToast(T('settings.copy_failed', 'Copy failed'));
    }
  }
}

// ── Init: load current deliberation mode from server ────────────────────────
export function initSettings() {
  try {
    fetch('/health').then(function (r) { return r.json(); }).then(function (d) {
      const cfg = (d && d.config) || {};
      const mode = cfg.deliberation_mode || 'auto';
      // Paint EVERY deliberation control from the saved value at boot — the buried <select>,
      // the Aspect-panel switch and its depth select — so the prominent toggle reflects reality
      // on first paint, not only after someone opens the deep Settings editor.
      _syncDeliberationControls(mode);
    }).catch(function () {});
  } catch (_) {}
  // Apply the saved text size at BOOT, not just when the settings panel is opened. Someone who needs
  // large text needs it on the chat they are reading now — a setting that only takes effect after you
  // go and open Settings is not an accessibility feature.
  loadAppearance();
}
