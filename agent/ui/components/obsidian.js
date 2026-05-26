/**
 * components/obsidian.js — Obsidian vault integration UI helpers.
 *
 * Converted from inline <script> block in index.html.
 * Self-contained — no module imports needed.
 */

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
    // Sync tts-toggle2 with tts-toggle state
    var tts2 = document.getElementById('tts-toggle2');
    if (tts2) tts2.checked = localStorage.getItem('layla_tts') !== 'false';
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
