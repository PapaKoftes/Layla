/**
 * layla-settings-full.js — Settings, workspace presets, relationship codex, content policy.
 * Depends on: layla-utils.js (escapeHtml, showToast, fetchWithTimeout)
 */
(function () {
  'use strict';

  var __esc = (typeof window.escapeHtml === 'function') ? window.escapeHtml : function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
  var __toast = (typeof window.showToast === 'function') ? window.showToast : function (t) { try { console.log('[Layla UI]', t); } catch (_) {} };

  // ── Settings overlay ───────────────────────────────────────────────────────
  async function openSettings() {
    var ov = document.getElementById('settings-overlay');
    if (!ov) return;
    ov.classList.add('visible');
    var loadEl = document.getElementById('settings-loading');
    var formEl = document.getElementById('settings-form');
    if (loadEl) { loadEl.style.display = 'block'; loadEl.textContent = 'Loading…'; }
    if (formEl) formEl.style.display = 'none';
    try {
      var res = await fetch('/settings/schema');
      var schema = await res.json();
      var r2 = await fetch('/settings');
      var cfg = await r2.json();
      if (loadEl) loadEl.style.display = 'none';
      if (formEl) {
        formEl.style.display = 'block';
        var fields = schema.fields || [];
        var html = '';
        fields.forEach(function (f) {
          var k = f.key;
          var v = cfg[k];
          var id = 'cfg_' + String(k).replace(/[^a-zA-Z0-9_]/g, '_');
          var hint = String(f.hint || '').replace(/</g, '&lt;');
          if (f.type === 'boolean') {
            html += '<div class="settings-row settings-section"><label style="display:flex;align-items:center;gap:8px;font-size:0.8rem;text-transform:none;color:var(--text)"><input type="checkbox" id="' + id + '" ' + (v ? 'checked' : '') + '/> ' + __esc(k) + '</label><div class="hint">' + hint + '</div></div>';
          } else if (f.type === 'number') {
            html += '<div class="settings-row settings-section"><label>' + __esc(k) + '</label><input type="number" id="' + id + '" value="' + (v != null ? String(v) : '') + '" step="any"/><div class="hint">' + hint + '</div></div>';
          } else {
            html += '<div class="settings-row settings-section"><label>' + __esc(k) + '</label><input type="text" id="' + id + '" value="' + __esc(String(v != null ? v : '')) + '"/><div class="hint">' + hint + '</div></div>';
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
  window.openSettings = openSettings;

  function closeSettings() {
    var ov = document.getElementById('settings-overlay');
    if (ov) ov.classList.remove('visible');
  }
  window.closeSettings = closeSettings;

  async function saveSettings() {
    var schemaRes = await fetch('/settings/schema');
    var schema = await schemaRes.json();
    var body = {};
    (schema.fields || []).forEach(function (f) {
      var id = 'cfg_' + String(f.key).replace(/[^a-zA-Z0-9_]/g, '_');
      var el = document.getElementById(id);
      if (!el) return;
      if (f.type === 'boolean') body[f.key] = el.checked;
      else if (f.type === 'number') body[f.key] = parseFloat(el.value);
      else body[f.key] = el.value;
    });
    try {
      var res = await fetch('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      var msg = document.getElementById('settings-save-msg');
      if (res.ok) {
        if (msg) { msg.style.display = 'inline'; setTimeout(function () { msg.style.display = 'none'; }, 2200); }
        __toast('Settings saved');
      } else __toast('Save failed');
    } catch (e) {
      __toast('Save failed');
    }
  }
  window.saveSettings = saveSettings;

  async function laylaLoadOptionalFeatures() {
    var box = document.getElementById('optional-features-list');
    if (!box) return;
    box.textContent = 'Loading…';
    try {
      var r = await fetch('/settings/optional_features');
      var d = await r.json();
      if (!d.ok || !d.features) { box.textContent = 'Could not load'; return; }
      box.innerHTML = d.features.map(function (f) {
        var st = f.installed ? 'ok' : '—';
        return '<div style="margin:4px 0;padding:4px;border-bottom:1px solid rgba(255,255,255,0.08)">' + st + ' <strong>' + __esc(f.id) + '</strong> — ' + __esc(f.label) +
          (!f.installed ? ' <button type="button" class="settings-save" style="padding:2px 8px;font-size:0.65rem" data-fid="' + __esc(f.id) + '">Install</button>' : '') + '</div>';
      }).join('');
      box.querySelectorAll('button[data-fid]').forEach(function (btn) {
        btn.onclick = function () { laylaInstallFeature(btn.getAttribute('data-fid')); };
      });
    } catch (e) { box.textContent = 'Error'; }
  }
  window.laylaLoadOptionalFeatures = laylaLoadOptionalFeatures;

  async function laylaInstallFeature(fid) {
    if (!fid || !confirm('Install feature ' + fid + ' via pip (allowlisted packages)?')) return;
    try {
      var r = await fetch('/settings/install_feature', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ feature_id: fid }) });
      var d = await r.json();
      var note = d.ok ? 'Install finished' : ((d.pip_attempt && d.pip_attempt.error) || d.error || 'failed');
      __toast(note);
      laylaLoadOptionalFeatures();
    } catch (e) { __toast('Install failed'); }
  }
  window.laylaInstallFeature = laylaInstallFeature;

  async function laylaImportChat() {
    var ta = document.getElementById('import-chat-text');
    var title = document.getElementById('import-chat-title');
    var msg = document.getElementById('import-chat-msg');
    var text = (ta && ta.value || '').trim();
    if (!text) { if (msg) msg.textContent = 'Paste export text first'; return; }
    try {
      var r = await fetch('/knowledge/import_chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ format: 'whatsapp', text: text, title: (title && title.value) || 'import' }) });
      var d = await r.json();
      if (msg) msg.textContent = d.ok ? ('Saved ' + d.path) : (d.error || 'failed');
      if (d.ok && ta) ta.value = '';
    } catch (e) { if (msg) msg.textContent = 'Request failed'; }
  }
  window.laylaImportChat = laylaImportChat;

  async function laylaGitUndoCheckpoint() {
    var winp = document.getElementById('admin-undo-workspace');
    var ws = (winp && winp.value || '').trim();
    var msg = document.getElementById('admin-undo-msg');
    if (!ws) { if (msg) msg.textContent = 'Set workspace path'; return; }
    if (!confirm('Revert the last Layla checkpoint commit in this repo?')) return;
    try {
      var r = await fetch('/settings/git_undo_checkpoint', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_root: ws }) });
      var d = await r.json();
      if (msg) msg.textContent = d.ok ? 'Reverted' : (d.error || 'failed');
    } catch (e) { if (msg) msg.textContent = 'Request failed'; }
  }
  window.laylaGitUndoCheckpoint = laylaGitUndoCheckpoint;

  // ── Workspace presets ──────────────────────────────────────────────────────
  function _workspacePresetStorageKey() {
    try {
      var h = (typeof location !== 'undefined' && location.host) ? String(location.host).replace(/[^a-z0-9]/gi, '_') : '';
      return 'layla_workspace_presets' + (h ? ('_' + h) : '');
    } catch (_) { return 'layla_workspace_presets'; }
  }

  function _loadWorkspacePresets() {
    try {
      var raw = localStorage.getItem(_workspacePresetStorageKey());
      if (raw) {
        var arr = JSON.parse(raw);
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

  function refreshWorkspacePresetsDropdown() {
    var sel = document.getElementById('workspace-presets');
    if (!sel) return;
    var presets = _loadWorkspacePresets();
    var inp = document.getElementById('workspace-path');
    var cur = inp ? (inp.value || '').trim() : '';
    sel.innerHTML = '<option value="">— saved paths —</option>';
    presets.forEach(function (p) {
      var opt = document.createElement('option');
      opt.value = p;
      opt.textContent = p;
      if (p === cur) opt.selected = true;
      sel.appendChild(opt);
    });
  }
  window.refreshWorkspacePresetsDropdown = refreshWorkspacePresetsDropdown;

  function addWorkspacePreset() {
    var inp = document.getElementById('workspace-path');
    var v = inp ? (inp.value || '').trim() : '';
    if (!v) return;
    var presets = _loadWorkspacePresets();
    if (presets.indexOf(v) < 0) {
      presets.push(v);
      _saveWorkspacePresets(presets);
      refreshWorkspacePresetsDropdown();
      __toast('Saved preset');
    }
  }
  window.addWorkspacePreset = addWorkspacePreset;

  function removeWorkspacePreset() {
    var inp = document.getElementById('workspace-path');
    var v = inp ? (inp.value || '').trim() : '';
    if (!v) return;
    var presets = _loadWorkspacePresets();
    var idx = presets.indexOf(v);
    if (idx >= 0) {
      presets.splice(idx, 1);
      _saveWorkspacePresets(presets);
      refreshWorkspacePresetsDropdown();
      __toast('Removed preset');
    }
  }
  window.removeWorkspacePreset = removeWorkspacePreset;

  function onWorkspacePresetSelect() {
    var sel = document.getElementById('workspace-presets');
    var inp = document.getElementById('workspace-path');
    if (!sel || !inp) return;
    var v = sel.value;
    if (v) {
      inp.value = v;
      try { if (typeof refreshOptionDependencies === 'function') refreshOptionDependencies(); } catch (_) {}
    }
  }
  window.onWorkspacePresetSelect = onWorkspacePresetSelect;

  // ── Relationship codex ─────────────────────────────────────────────────────
  async function refreshRelationshipCodex() {
    var pre = document.getElementById('codex-user-data');
    if (!pre) return;
    pre.textContent = 'Loading…';
    try {
      var r = await fetch('/codex/user');
      var d = await r.json();
      if (d && d.ok && d.user) {
        pre.textContent = JSON.stringify(d.user, null, 2);
      } else {
        pre.textContent = d ? JSON.stringify(d, null, 2) : '(no data)';
      }
    } catch (e) {
      pre.textContent = 'Error: ' + (e && e.message ? e.message : e);
    }
  }
  window.refreshRelationshipCodex = refreshRelationshipCodex;

  async function saveRelationshipCodex() {
    var pre = document.getElementById('codex-user-data');
    if (!pre) return;
    var raw = (pre.textContent || '').trim();
    if (!raw) return;
    var payload;
    try { payload = JSON.parse(raw); } catch (_) {
      __toast('Invalid JSON');
      return;
    }
    try {
      var res = await fetch('/codex/user', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      var data = await res.json().catch(function () { return {}; });
      __toast((data && data.ok) ? 'Saved codex' : ('Save failed: ' + ((data && data.error) || res.status)));
    } catch (e) {
      __toast('Save error: ' + ((e && e.message) || e));
    }
  }
  window.saveRelationshipCodex = saveRelationshipCodex;

  // ── Settings presets + appearance ──────────────────────────────────────────
  async function applySettingsPreset(name) {
    try {
      var r = await fetch('/settings/preset/' + encodeURIComponent(name), { method: 'POST' });
      var d = await r.json().catch(function () { return {}; });
      __toast(d.ok ? 'Preset applied: ' + name : (d.error || 'failed'));
    } catch (_) {
      __toast('Preset failed');
    }
  }
  window.applySettingsPreset = applySettingsPreset;

  async function saveAppearanceLite() {
    var fontSize = (document.getElementById('app-font-size') || {}).value;
    var animLevel = (document.getElementById('app-anim-level') || {}).value;
    var body = {};
    if (fontSize) body.ui_font_size = fontSize;
    if (animLevel) body.ui_animation_level = animLevel;
    try {
      var r = await fetch('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      var d = await r.json().catch(function () { return {}; });
      __toast(d.ok ? 'Appearance saved' : 'Save failed');
    } catch (_) {
      __toast('Save failed');
    }
  }
  window.saveAppearanceLite = saveAppearanceLite;

  async function runKnowledgeIngest() {
    var inp = document.getElementById('ingest-path');
    var msg = document.getElementById('ingest-msg');
    var path = inp ? (inp.value || '').trim() : '';
    if (!path) {
      if (msg) msg.textContent = 'Enter a file or directory path';
      return;
    }
    if (msg) msg.textContent = 'Ingesting…';
    try {
      var r = await fetch('/intelligence/kb/build/directory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ directory: path }),
      });
      var d = await r.json().catch(function () { return {}; });
      if (msg) msg.textContent = d.ok ? ('Done — ' + (d.articles_count || 0) + ' articles') : (d.error || 'failed');
    } catch (e) {
      if (msg) msg.textContent = 'Ingest failed';
    }
  }
  window.runKnowledgeIngest = runKnowledgeIngest;

  async function checkForUpdates() {
    var el = document.getElementById('update-status');
    if (el) el.textContent = 'Checking…';
    try {
      var r = await fetch('/version/check_update');
      var d = await r.json().catch(function () { return {}; });
      if (el) el.textContent = d.update_available ? ('Update available: ' + (d.latest || '')) : 'Up to date';
    } catch (_) {
      if (el) el.textContent = 'Could not check';
    }
  }
  window.checkForUpdates = checkForUpdates;

  // ── Content policy ─────────────────────────────────────────────────────────
  window.saveContentPolicySettings = async function saveContentPolicySettings() {
    var btn = document.querySelector('button[onclick*="saveContentPolicySettings"]');
    var uncEl = document.getElementById('opt-uncensored');
    var nsfwEl = document.getElementById('opt-nsfw-allowed');
    var unc = !!(uncEl && uncEl.checked);
    var nsfw = !!(nsfwEl && nsfwEl.checked);
    if (btn) btn.disabled = true;
    try {
      var r = await fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uncensored: unc, nsfw_allowed: nsfw }),
      });
      var d = await r.json().catch(function () { return {}; });
      __toast((d && d.ok) ? 'Saved content policy' : 'Save failed');
    } catch (_) {
      __toast('Save failed');
    } finally {
      if (btn) btn.disabled = false;
    }
  };

  // ── Phone access ───────────────────────────────────────────────────────────
  window.loadPhoneAccess = async function loadPhoneAccess() {
    var urlEl = document.getElementById('phone-access-url');
    var stEl = document.getElementById('phone-access-status');
    if (urlEl) urlEl.textContent = 'Loading…';
    if (stEl) stEl.textContent = '';
    try {
      var proto = location.protocol || 'http:';
      var host = location.hostname || '127.0.0.1';
      var port = location.port ? (':' + location.port) : '';
      var url = proto + '//' + host + port + '/ui';
      if (urlEl) urlEl.textContent = url;
      if (stEl) stEl.textContent = (host === '127.0.0.1' || host === 'localhost')
        ? 'Tip: for LAN access, start Layla with --host 0.0.0.0 and use your PC IP address.'
        : 'If this is your LAN IP, open it on your phone (same WiFi).';
    } catch (e) {
      if (urlEl) urlEl.textContent = '(could not compute URL)';
      if (stEl) stEl.textContent = String(e && e.message ? e.message : e);
    }
  };

  window.copyPhoneUrl = async function copyPhoneUrl() {
    var url = (document.getElementById('phone-access-url') || {}).textContent || '';
    url = url.trim();
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      __toast('Copied');
    } catch (_) {
      try {
        var ta = document.createElement('textarea');
        ta.value = url;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        __toast('Copied');
      } catch (_) {
        __toast('Copy failed');
      }
    }
  };

  window.laylaSettingsModuleLoaded = true;
})();
