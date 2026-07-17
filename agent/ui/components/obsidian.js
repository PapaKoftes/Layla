/**
 * components/obsidian.js — Obsidian vault integration UI helpers.
 *
 * Converted from inline <script> block in index.html.
 */

import { readTtsPref } from './voice.js';

function _obsStatus(msg, isErr) {
  var el = document.getElementById('obsidian-status');
  if (el) { el.textContent = msg; el.style.color = isErr ? 'var(--error,#e74c3c)' : 'var(--asp)'; }
}

export async function laylaObsidianConnect() {
  var vp = (document.getElementById('obsidian-vault-path') || {}).value || '';
  if (!vp.trim()) { _obsStatus('Enter a vault path first.', true); return; }
  try {
    _obsStatus('Connecting…');
    var res = await fetch('/obsidian/connect', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({vault_path: vp}) });
    var data = await res.json();
    if (data.ok) {
      localStorage.setItem('layla_obsidian_vault_path', vp);
      _obsStatus('Connected: ' + data.vault_path);
      laylaObsidianStatus();
    } else { _obsStatus('Error: ' + (data.error || 'unknown'), true); }
  } catch(e) { _obsStatus('Network error: ' + e.message, true); }
}

export async function laylaObsidianSync() {
  try {
    _obsStatus('Syncing…');
    var res = await fetch('/obsidian/sync', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
    var data = await res.json();
    if (data.ok) {
      _obsStatus('Synced: ' + data.copied + ' copied, ' + data.skipped_conflicts + ' conflicts skipped');
    } else { _obsStatus('Error: ' + (data.error || 'unknown'), true); }
  } catch(e) { _obsStatus('Network error: ' + e.message, true); }
}

function _obsEsc(s) {
  var d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function _obsList(label, arr, color) {
  if (!arr || !arr.length) return '';
  var items = arr.slice(0, 40).map(function (p) { return '<li>' + _obsEsc(p) + '</li>'; }).join('');
  var more = arr.length > 40 ? '<li>… +' + (arr.length - 40) + ' more</li>' : '';
  return '<div class="obs-diff-sec"><div class="obs-diff-h" style="color:' + color + '">' +
    _obsEsc(label) + ' (' + arr.length + ')</div><ul class="obs-diff-ul">' + items + more + '</ul></div>';
}

/** GET /obsidian/status — connection + pending-change counts. */
export async function laylaObsidianStatus() {
  try {
    var res = await fetch('/obsidian/status');
    var d = await res.json();
    if (d && d.connected === false) { _obsStatus('Not connected'); return; }
    if (d && d.ok === false) { _obsStatus('Error: ' + (d.error || 'unknown'), true); return; }
    _obsStatus('Connected: ' + d.vault_path + ' — ' + (d.new || 0) + ' new · ' +
      (d.updated || 0) + ' updated · ' + (d.conflicts || 0) + ' conflicts (' + (d.total_vault_files || 0) + ' files)');
  } catch (e) { _obsStatus('Network error: ' + e.message, true); }
}

/** GET /obsidian/diff — dry-run preview of what the next sync would change. */
export async function laylaObsidianDiff() {
  var box = document.getElementById('obsidian-diff');
  if (box) box.innerHTML = '<span class="settings-hint">Computing diff…</span>';
  try {
    var res = await fetch('/obsidian/diff');
    var d = await res.json();
    if (d && d.ok === false) {
      if (box) box.innerHTML = '<span class="settings-hint" style="color:var(--error,#e74c3c)">Error: ' + _obsEsc(d.error || 'unknown') + '</span>';
      return;
    }
    var html = _obsList('New', d.new, 'var(--success,#3fae6b)') +
      _obsList('Updated', d.updated, 'var(--asp)') +
      _obsList('Conflicts', d.conflicts, 'var(--danger,#e74c3c)');
    var unchanged = (d.unchanged || []).length;
    if (!html) html = '<span class="settings-hint">Nothing to sync — vault is up to date (' + unchanged + ' unchanged).</span>';
    else html += '<div class="settings-hint" style="margin-top:4px">' + unchanged + ' unchanged · ' + (d.total_vault_files || 0) + ' vault files</div>';
    if (box) box.innerHTML = html;
  } catch (e) {
    if (box) box.innerHTML = '<span class="settings-hint">Network error: ' + _obsEsc(e.message) + '</span>';
  }
}

export async function laylaObsidianSuggest() {
  try {
    _obsStatus('Loading suggestions…');
    var res = await fetch('/obsidian/suggest?n=5');
    var data = await res.json();
    if (!data.ok) { _obsStatus('Error: ' + (data.error || 'unknown'), true); return; }
    var count = data.count || 0;
    if (!count) { _obsStatus('No high-confidence learnings to suggest yet.'); return; }
    _obsStatus(count + ' learnings ready to export → use /obsidian/export API or approve in memory browser');
  } catch(e) { _obsStatus('Network error: ' + e.message, true); }
}

/**
 * Restore persisted Performance & UI settings on load.
 * (Was an inline IIFE at the bottom of index.html.)
 */
export function restorePersistedSettings() {
  try {
    if (localStorage.getItem('layla_low_fx') === 'true') {
      document.documentElement.style.setProperty('--fx-strength', '0.4');
      var cb = document.getElementById('low-fx-toggle');
      if (cb) cb.checked = true;
    }
    if (localStorage.getItem('layla_idb_cache') === 'false') {
      var cb2 = document.getElementById('idb-cache-toggle');
      if (cb2) cb2.checked = false;
    }
    if (localStorage.getItem('layla_artifacts_autoscan') === 'false') {
      var cb3 = document.getElementById('artifacts-autoscan-toggle');
      if (cb3) cb3.checked = false;
    }
    // Sync tts-toggle2 with tts-toggle state.
    // BL-271: this read `!== 'false'` (unset -> ON) while voice.js read `=== 'true'` (unset -> OFF), so
    // on a fresh profile this box rendered CHECKED while the engine was OFF. Both files were reasonable
    // alone; the disagreement was the bug. readTtsPref() is now the one place that decides.
    var tts2 = document.getElementById('tts-toggle2');
    if (tts2) tts2.checked = readTtsPref();
    // Restore Obsidian vault path
    var obsPath = localStorage.getItem('layla_obsidian_vault_path');
    if (obsPath) {
      var obsEl = document.getElementById('obsidian-vault-path');
      if (obsEl) obsEl.value = obsPath;
    }
  } catch(_) {}
}

export function initObsidian() {
  restorePersistedSettings();
}
