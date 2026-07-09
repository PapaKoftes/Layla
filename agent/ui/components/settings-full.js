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

export async function laylaToggleFeatureTheme(key, enabled) {
  try {
    const r = await fetch('/settings/themes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key, enabled: !!enabled }),
    });
    const d = await r.json();
    if (d && d.ok) showToast((enabled ? 'Enabled: ' : 'Disabled: ') + key.replace(/_/g, ' '));
    else showToast('Could not update feature area');
  } catch (_e) { showToast('Could not update feature area'); }
}
try { window.laylaToggleFeatureTheme = laylaToggleFeatureTheme; } catch (_e) { /* no-op */ }

// ── Settings overlay ────────────────────────────────────────────────────────
export async function openSettings() {
  const ov = document.getElementById('settings-overlay');
  if (!ov) return;
  ov.classList.add('visible');
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
        if (f.type === 'boolean') {
          html += '<div class="settings-row settings-section"><label style="display:flex;align-items:center;gap:8px;font-size:0.8rem;text-transform:none;color:var(--text)"><input type="checkbox" id="' + id + '" ' + (v ? 'checked' : '') + '/> ' + lbl + '</label><div class="hint">' + hint + '</div></div>';
        } else if (f.type === 'number') {
          html += '<div class="settings-row settings-section"><label>' + lbl + '</label><input type="number" id="' + id + '" value="' + (v != null ? String(v) : '') + '" step="any"/><div class="hint">' + hint + '</div></div>';
        } else {
          html += '<div class="settings-row settings-section"><label>' + lbl + '</label><input type="text" id="' + id + '" value="' + escapeHtml(String(v != null ? v : '')) + '"/><div class="hint">' + hint + '</div></div>';
        }
      });
      formEl.innerHTML = html;
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

export async function saveSettings() {
  const schemaRes = await fetch('/settings/schema');
  const schema = await schemaRes.json();
  const body = {};
  (schema.fields || []).forEach(function (f) {
    const id = 'cfg_' + String(f.key).replace(/[^a-zA-Z0-9_]/g, '_');
    const el = document.getElementById(id);
    if (!el) return;
    if (f.type === 'boolean') body[f.key] = el.checked;
    else if (f.type === 'number') body[f.key] = parseFloat(el.value);
    else body[f.key] = el.value;
  });
  try {
    const res = await fetch('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const msg = document.getElementById('settings-save-msg');
    if (res.ok) {
      if (msg) { msg.style.display = 'inline'; setTimeout(function () { msg.style.display = 'none'; }, 2200); }
      showToast('Settings saved');
    } else showToast('Save failed');
  } catch (e) {
    showToast('Save failed');
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
export async function applySettingsPreset(name) {
  try {
    const r = await fetch('/settings/preset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: name }),
    });
    const d = await r.json().catch(function () { return {}; });
    showToast(d.ok ? 'Preset applied: ' + name : (d.error || 'failed'));
  } catch (_) {
    showToast('Preset failed');
  }
}

export async function saveAppearanceLite() {
  const fontSize = (document.getElementById('app-font-size') || {}).value;
  const animLevel = (document.getElementById('app-anim-level') || {}).value;
  const body = {};
  if (fontSize) body.ui_font_size = fontSize;
  if (animLevel) body.ui_animation_level = animLevel;
  try {
    const r = await fetch('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json().catch(function () { return {}; });
    showToast(d.ok ? 'Appearance saved' : 'Save failed');
  } catch (_) {
    showToast('Save failed');
  }
}

export async function runKnowledgeIngest() {
  const inp = document.getElementById('ingest-path');
  const msg = document.getElementById('ingest-msg');
  const path = inp ? (inp.value || '').trim() : '';
  if (!path) {
    if (msg) msg.textContent = 'Enter a file or directory path';
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
}
