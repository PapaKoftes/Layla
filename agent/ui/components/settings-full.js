/**
 * components/settings-full.js — Settings, workspace presets, relationship codex, content policy.
 *
 * Converted from js/layla-settings-full.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast, laylaConfirm)
 */

import { escapeHtml, showToast, laylaConfirm } from '../services/utils.js';

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
    '<div style="font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-faint);margin-bottom:6px">Feature areas</div>' +
    '<div class="hint" style="margin-bottom:8px">Turn whole capability areas on or off — Layla only carries what you switch on.</div>' +
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
        ? 'Refused: ' + key.replace(/_/g, ' ') + ' — ' + (d.error || 'a security policy declined this change')
        : 'Could not update feature area — ' + ((d && d.error) || ('HTTP ' + r.status)));
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
      const base = (enabled ? 'Enabled: ' : 'Disabled: ') + label;
      showToast(enabled && locked.length
        ? base + ' — locked ' + locked.join(', ') + ' so hardware auto-tune cannot revert it'
        : base);
    } else {
      const why = d.not_in_force_note ||
        ((d.missing_packages || []).length
          ? 'needs packages that are not installed: ' + d.missing_packages.join(', ')
          : 'an owner is holding its settings');
      showToast('NOT in force: ' + label + ' — ' + why);
    }
    // Whatever happened, the panel's not-in-force state may have changed. Re-read it from the
    // server rather than inferring it from this one response.
    await _loadNotInForce();
  } catch (_e) {
    showToast('Could not update feature area');
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
  ov.classList.add('visible');
  // Populate the appearance controls from the server. Without this the panel renders its defaults over
  // whatever is actually stored, so a saved text size looks unsaved and re-saving silently reverts it.
  loadAppearance();
  const loadEl = document.getElementById('settings-loading');
  const formEl = document.getElementById('settings-form');
  if (loadEl) { loadEl.style.display = 'block'; loadEl.textContent = 'Loading…'; }
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
            (f.auto_tune_active
              ? 'Hardware auto-tune sets this on every config load and will overwrite your value.'
              : 'You have locked this key — auto-tune will leave your value alone.') + '">' +
            (f.auto_tune_active ? 'auto-tune owns this' : 'locked — your value wins') + '</span>'
          : '';
        const ownHint = (owned && f.auto_tune_active)
          ? '<div class="hint cfg-owner-hint">Auto-tune re-derives this from your hardware on every load, so a value set here does not stick. ' +
            'Add <code>' + escapeHtml(k) + '</code> to <em>Auto tune locked keys</em> below (or turn off <em>Auto tune enabled</em>) to keep your own value.</div>'
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
        'Could not load settings. Is Layla running?<br>' +
        '<button type="button" class="tab-btn" style="margin-top:10px" onclick="openSettings()">Retry</button>' +
        '</div>';
    }
  }
}

export function closeSettings() {
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
  const head = anyRefused && anyOther ? 'Refused, or saved but NOT in force'
    : (anyRefused ? 'Refused — not saved' : 'Saved to disk, but NOT in force');
  box.innerHTML =
    '<div class="nif-head">⚠ ' + head + ' — ' + bad.length +
    (bad.length === 1 ? ' setting' : ' settings') + '</div>' +
    bad.map(function (r) {
      const el = document.getElementById('cfg_' + String(r.key).replace(/[^a-zA-Z0-9_]/g, '_'));
      const row = el && el.closest ? el.closest('.settings-row') : null;
      if (row) row.classList.add('is-not-in-force');
      const owner = r.owner ? String(r.owner) : 'unknown';
      const eff = Object.prototype.hasOwnProperty.call(r, 'effective')
        ? ' <span class="nif-eff">in force: ' + escapeHtml(JSON.stringify(r.effective)) + '</span>' : '';
      const label = r.outcome === 'refused' ? 'refused by ' : 'owned by ';
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
  if (!changedKeys.length) { say('No changes to save', false); return; }
  try {
    const res = await fetch('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await res.json().catch(function () { return {}; });
    if (!res.ok) { say('Save failed — ' + (d.error || ('HTTP ' + res.status)), true); return; }

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
      say('Refused: ' + refusedRows.map(function (r) { return r.key; }).join(', ') + ' — ' +
          refusedRows.map(function (r) { return r.reason; }).join(' · '), true);
    } else if (badLocks.length) {
      say('Cannot lock (not auto-tune settings): ' + badLocks.join(', '), true);
    } else if (rejected.length) {
      say('Saved ' + saved.length + ', REJECTED: ' + rejected.join(', '), true);
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
        bits.push('NOT in force: ' + notInForce.map(function (r) { return r.key; }).join(', ') +
                  ' — held by ' + owners.join(', '));
      }
      if (adjusted.length) {
        bits.push(adjusted.map(function (a) {
          return a.key + ' was ' + a.reason + ' to ' + JSON.stringify(a.stored) +
                 ' (you entered ' + JSON.stringify(a.requested) + ')';
        }).join('; '));
      }
      say('Saved, but ' + bits.join(' · ') + '. See the details below the buttons.', true);
    } else if (saved.length) {
      say('Saved ' + saved.length + ' change' + (saved.length === 1 ? '' : 's') + ': ' + saved.join(', '), false);
    } else {
      say('Nothing was saved', true);
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
      if (newlyLocked.length) bits.push('locked ' + newlyLocked.join(', ') + ' — auto-tune will leave your value alone');
      if (unlocked.length) bits.push('unlocked ' + unlocked.join(', ') + ' — auto-tune owns it again');
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
    say('Save failed', true);
  }
}

export async function laylaLoadOptionalFeatures() {
  const box = document.getElementById('optional-features-list');
  if (!box) return;
  box.textContent = 'Loading…';
  try {
    const r = await fetch('/settings/optional_features');
    const d = await r.json();
    if (!d.ok || !d.features) { box.textContent = 'Could not load'; return; }
    box.innerHTML = d.features.map(function (f) {
      const st = f.installed ? 'ok' : '—';
      return '<div style="margin:4px 0;padding:4px;border-bottom:1px solid rgba(255,255,255,0.08)">' + st + ' <strong>' + escapeHtml(f.id) + '</strong> — ' + escapeHtml(f.label) +
        (!f.installed ? ' <button type="button" class="settings-save" style="padding:2px 8px;font-size:0.65rem" data-fid="' + escapeHtml(f.id) + '">Install</button>' : '') + '</div>';
    }).join('');
    box.querySelectorAll('button[data-fid]').forEach(function (btn) {
      btn.onclick = function () { laylaInstallFeature(btn.getAttribute('data-fid')); };
    });
  } catch (e) { box.textContent = 'Error'; }
}

export async function laylaInstallFeature(fid) {
  if (!fid || !(await laylaConfirm('Install feature ' + fid + ' via pip (allowlisted packages)?'))) return;
  try {
    const r = await fetch('/settings/install_feature', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ feature_id: fid }) });
    const d = await r.json();
    const note = d.ok ? 'Install finished' : ((d.pip_attempt && d.pip_attempt.error) || d.error || 'failed');
    showToast(note);
    laylaLoadOptionalFeatures();
  } catch (e) { showToast('Install failed'); }
}

export async function laylaImportChat() {
  const ta = document.getElementById('import-chat-text');
  const title = document.getElementById('import-chat-title');
  const msg = document.getElementById('import-chat-msg');
  const text = (ta && ta.value || '').trim();
  if (!text) { if (msg) msg.textContent = 'Paste export text first'; return; }
  try {
    const r = await fetch('/knowledge/import_chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format: 'whatsapp', text: text, title: (title && title.value) || 'import' }) });
    const d = await r.json();
    if (msg) msg.textContent = d.ok ? ('Saved ' + d.path) : (d.error || 'failed');
    if (d.ok && ta) ta.value = '';
  } catch (e) { if (msg) msg.textContent = 'Request failed'; }
}

export async function laylaGitUndoCheckpoint() {
  const winp = document.getElementById('admin-undo-workspace');
  const ws = (winp && winp.value || '').trim();
  const msg = document.getElementById('admin-undo-msg');
  if (!ws) { if (msg) msg.textContent = 'Set workspace path'; return; }
  if (!(await laylaConfirm('Revert the last Layla checkpoint commit in this repo?'))) return;
  try {
    const r = await fetch('/settings/git_undo_checkpoint', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_root: ws }) });
    const d = await r.json();
    if (msg) msg.textContent = d.ok ? 'Reverted' : (d.error || 'failed');
  } catch (e) { if (msg) msg.textContent = 'Request failed'; }
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
  sel.innerHTML = '<option value="">— saved paths —</option>';
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
    showToast('Saved preset');
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
    showToast('Removed preset');
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
    if (status) status.textContent = 'Set a workspace path in Library → Workspace first, then Load.';
    return;
  }
  if (status) status.textContent = 'Loading…';
  try {
    const r = await fetch('/codex/relationship?workspace_root=' + encodeURIComponent(ws));
    const d = await r.json();
    if (d && d.ok) {
      ta.value = JSON.stringify(d.data || { entities: {} }, null, 2);
      if (status) status.textContent = 'Loaded from ' + (d.path || ws);
    } else {
      if (status) status.textContent = 'Error: ' + ((d && d.error) || r.status);
    }
  } catch (e) {
    if (status) status.textContent = 'Error: ' + (e && e.message ? e.message : e);
  }
}

export async function saveRelationshipCodex() {
  const ta = document.getElementById('relationship-codex-json');
  const status = document.getElementById('relationship-codex-status');
  if (!ta) return;
  const ws = _codexWorkspace();
  if (!ws) {
    if (status) status.textContent = 'Set a workspace path in Library → Workspace first.';
    return;
  }
  const raw = (ta.value || '').trim();
  if (!raw) return;
  let payload;
  try { payload = JSON.parse(raw); } catch (_) {
    if (status) status.textContent = 'Invalid JSON — fix and try again.';
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
    if (status) status.textContent = (data && data.ok) ? 'Saved' : ('Save failed: ' + ((data && data.error) || res.status));
    if (data && data.ok && typeof showToast === 'function') showToast('Saved codex');
  } catch (e) {
    if (status) status.textContent = 'Save error: ' + ((e && e.message) || e);
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
    if (!r.ok || !d.ok) { showToast(d.error || 'Preset failed'); return; }
    const nif = d.not_in_force || [];
    if (nif.length) {
      const owners = [];
      (d.report || []).forEach(function (row) {
        if (nif.indexOf(row.key) === -1) return;
        const o = row.owner || 'unknown';
        if (owners.indexOf(o) === -1) owners.push(o);
      });
      showToast('Preset ' + name + ': ' + (d.applied || []).length + ' of ' +
                ((d.applied || []).length + nif.length) + ' settings in force — ' +
                nif.join(', ') + ' held by ' + owners.join(', '));
    } else {
      showToast('Preset applied: ' + name + ' (' + (d.applied || []).length + ' settings)');
    }
    // The preset just wrote a large slice of the config; whatever it could not put in force
    // belongs in the panel, not only in a toast that fades.
    await _loadNotInForce();
  } catch (_) {
    showToast('Preset failed');
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
    if (msg) msg.textContent = 'Nothing to save — appearance controls are missing.';
    showToast('Appearance controls are missing — nothing was saved');
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
      const t = 'Saved ' + saved.length + ', REJECTED: ' + rejected.join(', ');
      if (msg) msg.textContent = t;
      showToast(t);
    } else if (saved.length) {
      applyAppearance(body.ui_font_size, body.ui_animation_level);
      const t = 'Appearance saved (' + saved.length + ' setting' + (saved.length === 1 ? '' : 's') + ')';
      if (msg) msg.textContent = t;
      showToast(t);
    } else {
      const t = d.error ? ('Save failed: ' + d.error) : 'Save failed — nothing was written';
      if (msg) msg.textContent = t;
      showToast(t);
    }
  } catch (e) {
    if (msg) msg.textContent = 'Save failed: ' + e;
    showToast('Save failed');
  }
}

export async function runKnowledgeIngest() {
  // #km-source / #km-ingest-list — NOT #ingest-path / #ingest-msg, which exist nowhere. This read null,
  // bailed at the empty-path guard, and wrote its own error message to a null element: nothing happened at
  // all, not even the error. Knowledge could not be added through the UI by any route.
  const inp = document.getElementById('km-source');
  const msg = document.getElementById('km-ingest-list');
  const path = inp ? (inp.value || '').trim() : '';
  if (!path) {
    if (msg) msg.textContent = 'Enter a folder path inside your workspace';
    return;
  }
  if (msg) msg.textContent = 'Ingesting…';
  try {
    const r = await fetch('/intelligence/kb/build/directory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directory: path }),
    });
    const d = await r.json().catch(function () { return {}; });
    if (msg) msg.textContent = d.ok ? ('Done — ' + (d.articles_count || 0) + ' articles') : (d.error || 'failed');
  } catch (e) {
    if (msg) msg.textContent = 'Ingest failed';
  }
}

export async function checkForUpdates() {
  const el = document.getElementById('update-status');
  if (el) el.textContent = 'Checking…';
  try {
    const r = await fetch('/update/check');
    const d = await r.json().catch(function () { return {}; });
    if (el) el.textContent = d.update_available ? ('Update available: ' + (d.latest_version || d.latest || '')) : 'Up to date';
  } catch (_) {
    if (el) el.textContent = 'Could not check';
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
    showToast((d && d.ok) ? 'Saved content policy' : 'Save failed');
  } catch (_) {
    showToast('Save failed');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Deliberation mode selector ──────────────────────────────────────────────
export async function setDeliberationMode(mode) {
  const valid = ['solo', 'auto', 'debate', 'council', 'tribunal'];
  if (valid.indexOf(mode) < 0) mode = 'auto';
  try {
    const r = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deliberation_mode: mode }),
    });
    const d = await r.json().catch(function () { return {}; });
    showToast((d && d.ok) ? ('Deliberation: ' + mode) : 'Setting failed — check server logs');
  } catch (_) {
    showToast('Could not save deliberation mode');
  }
}

// ── Phone access ────────────────────────────────────────────────────────────
export async function loadPhoneAccess() {
  const urlEl = document.getElementById('phone-access-url');
  const stEl = document.getElementById('phone-access-status');
  if (urlEl) urlEl.textContent = 'Loading…';
  if (stEl) stEl.textContent = '';
  try {
    const proto = location.protocol || 'http:';
    const host = location.hostname || '127.0.0.1';
    const port = location.port ? (':' + location.port) : '';
    const url = proto + '//' + host + port + '/ui';
    if (urlEl) urlEl.textContent = url;
    if (stEl) stEl.textContent = (host === '127.0.0.1' || host === 'localhost')
      ? 'Tip: for LAN access, start Layla with --host 0.0.0.0 and use your PC IP address.'
      : 'If this is your LAN IP, open it on your phone (same WiFi).';
  } catch (e) {
    if (urlEl) urlEl.textContent = '(could not compute URL)';
    if (stEl) stEl.textContent = String(e && e.message ? e.message : e);
  }
}

export async function copyPhoneUrl() {
  const url = (document.getElementById('phone-access-url') || {}).textContent || '';
  const trimmed = url.trim();
  if (!trimmed) return;
  try {
    await navigator.clipboard.writeText(trimmed);
    showToast('Copied');
  } catch (_) {
    try {
      const ta = document.createElement('textarea');
      ta.value = trimmed;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast('Copied');
    } catch (_2) {
      showToast('Copy failed');
    }
  }
}

// ── Init: load current deliberation mode from server ────────────────────────
export function initSettings() {
  try {
    fetch('/health').then(function (r) { return r.json(); }).then(function (d) {
      const cfg = (d && d.config) || {};
      const mode = cfg.deliberation_mode || 'auto';
      const sel = document.getElementById('deliberation-mode-select');
      if (sel) sel.value = mode;
    }).catch(function () {});
  } catch (_) {}
  // Apply the saved text size at BOOT, not just when the settings panel is opened. Someone who needs
  // large text needs it on the chat they are reading now — a setting that only takes effect after you
  // go and open Settings is not an accessibility feature.
  loadAppearance();
}
