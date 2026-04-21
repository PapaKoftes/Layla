window.__laylaHealth = window.__laylaHealth || {
  payload: null,
  lastFetch: 0,
  lastDeepFetch: 0,
  deepIntervalMs: 60000,
  inFlight: false,
  agentRequestActive: false,
  _inFlightPromise: null,
};
let currentAspect = 'morrigan';
var currentConversationId = localStorage.getItem('layla_current_conversation_id') || '';
const sessionStart = Date.now();

// Debug: localStorage.setItem('layla_debug','1') and reload; or ?layla_debug=1 in URL; or in console: window.LAYLA_DEBUG = true
var LAYLA_DEBUG = (typeof localStorage !== 'undefined' && localStorage.getItem('layla_debug') === '1') || (typeof location !== 'undefined' && location.search.indexOf('layla_debug') !== -1);
window.LAYLA_DEBUG = LAYLA_DEBUG; // allow toggling in console without reload
function _dbg() {
  if (!window.LAYLA_DEBUG && !LAYLA_DEBUG) return;
  try { console.log.apply(console, ['[Layla]'].concat(Array.prototype.slice.call(arguments))); } catch (_) {}
}
_dbg('script started');

// triggerSend and Enter listener already registered by bootstrap script above; ensure window.send wrapper can delegate to full send()
try {
function formatAgentError(res, body) {
  if (!res) return "Can't reach Layla. Is the server running at http://127.0.0.1:8000?";
  if (res.status === 500) return 'Something went wrong. Check the server logs or try again.';
  if (res.status === 503) return (body && body.detail) || 'Service temporarily unavailable.';
  const err = (body && (body.detail || body.response || body.message)) || res.statusText;
  return err && String(err).length < 200 ? String(err) : 'Request failed: ' + res.status;
}

// Per-aspect color palette — shifts the whole UI on switch
const ASPECT_COLORS = {
  morrigan: { asp: '#8b0000', glow: 'rgba(139,0,0,0.28)',   mid: 'rgba(139,0,0,0.10)' },
  nyx:      { asp: '#3a1f9a', glow: 'rgba(58,31,154,0.28)', mid: 'rgba(58,31,154,0.10)' },
  echo:     { asp: '#006878', glow: 'rgba(0,104,120,0.28)', mid: 'rgba(0,104,120,0.10)' },
  eris:     { asp: '#8a4000', glow: 'rgba(138,64,0,0.28)',  mid: 'rgba(138,64,0,0.10)' },
  cassandra: { asp: '#4a1a7a', glow: 'rgba(74,26,122,0.28)', mid: 'rgba(74,26,122,0.10)' },
  lilith:   { asp: '#6a0070', glow: 'rgba(106,0,112,0.28)', mid: 'rgba(106,0,112,0.10)' },
};

let _lastAspectSwitchTime = 0;
function setAspect(id, force) {
  if (_aspectLocked && !force) return; // locked — ignore sidebar clicks unless forced
  currentAspect = id;
  document.querySelectorAll('.aspect-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + id)?.classList.add('active');
  const badge = document.getElementById('aspect-badge');
  const ASPECT_SYMBOLS = { morrigan:'⚔', nyx:'✦', echo:'◎', eris:'⚡', cassandra:'⌖', lilith:'⊛' };
  const sym = ASPECT_SYMBOLS[id] || '∴';
  if (badge) { badge.textContent = sym + ' ' + id.toUpperCase(); badge.style.animation = 'none'; void badge.offsetWidth; badge.style.animation = ''; }
  const c = ASPECT_COLORS[id] || ASPECT_COLORS.morrigan;
  const root = document.documentElement.style;
  document.body?.setAttribute('data-aspect', id);
  root.setProperty('--asp',      c.asp);
  root.setProperty('--asp-glow', c.glow);
  root.setProperty('--asp-mid',  c.mid);
  if (Date.now() - _lastAspectSwitchTime > 300) {
    _lastAspectSwitchTime = Date.now();
    const name = (typeof ASPECTS !== 'undefined' && ASPECTS.find) ? ASPECTS.find(a => a.id === id)?.name : null;
    showToast('Now talking to ' + (name || id));
  }
  try { updateContextChip(); } catch (_) {}
  try {
    const doodles = {
      morrigan: '⚔ ⟁ ⚔ ⎔ ⚔ ◈\n/\\\\==/\\\\  ─┼─  /\\\\==/\\\\\n⎔  ◈  ⟁  ⚔  ⟁  ◈',
      nyx: '✦ ⊛ ∴ ✦ ⌁ ✦\n..✦..::..✦..::..\n⌁  ✦  ⊛  ∴  ✦  ⌁',
      echo: '◎ ∞ ◎ ⟡ ◎ ∞\n====  ~~~  ====\n⟡  ◎  ∞  ◎  ⟡',
      eris: '⚡ ⊘ ⚡ ⌇ ⚡ ⊘\n/\\/\\/\\/\\  ╱╲  /\\/\\/\\/\\\n⌇  ⚡  ⊘  ⚡  ⌇',
      cassandra: '⌖ △ ⌖ ⟟ ⌖ △\n<>  /\\  <>  /\\  <>\n⟟  ⌖  △  ⌖  ⟟',
      lilith: '⊛ ♾ ✶ ⊛ ⟁ ⊛\n###  ╳  ###  ╳  ###\n✶  ⊛  ♾  ⊛  ✶',
    };
    const ov = document.getElementById('doodle-overlay');
    if (ov) ov.textContent = (doodles[id] || doodles.morrigan).repeat(180);
  } catch (_) {}
  try {
    if (typeof window.laylaSetAspectSprite === 'function') window.laylaSetAspectSprite(id);
  } catch (_) {}
}
window.setAspect = setAspect;

// ── Layla v3: Maturity / Mastery rank UI ────────────────────────────────────
async function refreshMaturityCard(showCeremony) {
  try {
    const r = await fetch('/operator/profile');
    const d = await r.json();
    if (!d || !d.ok) return;
    const rank = (d.maturity && d.maturity.rank != null) ? Number(d.maturity.rank) : 0;
    const xp = (d.maturity && d.maturity.xp != null) ? Number(d.maturity.xp) : 0;
    const phaseRaw = String((d.maturity && d.maturity.phase) || 'awakening').trim().toLowerCase() || 'awakening';
    const phase = phaseRaw.toUpperCase();
    const xpToNext = (d.maturity && d.maturity.xp_to_next != null) ? Number(d.maturity.xp_to_next) : null;
    const milestones = (d.maturity && Array.isArray(d.maturity.milestones)) ? d.maturity.milestones : [];
    const elRank = document.getElementById('maturity-rank');
    const elPhase = document.getElementById('maturity-phase');
    const elXp = document.getElementById('maturity-xp');
    const fill = document.getElementById('maturity-bar-fill');
    const sigil = document.getElementById('maturity-sigil');
    const msList = document.getElementById('maturity-milestones-list');
    if (elRank) elRank.textContent = isFinite(rank) ? String(rank) : '0';
    if (elPhase) elPhase.textContent = phase;
    const need = (xpToNext != null && isFinite(xpToNext) && xpToNext > 0) ? xpToNext : null;
    if (elXp) elXp.textContent = need ? (xp + ' / ' + need) : (String(xp) + ' / —');
    if (fill) fill.style.width = need ? (Math.max(0, Math.min(100, Math.floor((xp / need) * 100))) + '%') : '0%';

    try {
      if (sigil) {
        // Phase sigils are optional assets; show a subtle ring when missing.
        sigil.setAttribute('data-phase', phaseRaw);
        const src = '/layla-ui/assets/sigils/' + encodeURIComponent(phaseRaw) + '.svg';
        sigil.innerHTML = '<img src="' + src + '" alt="" onerror="this.remove()" />';
      }
    } catch (_) {}

    try {
      if (msList) {
        if (!milestones.length) {
          msList.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">No milestones yet.</span>';
        } else {
          msList.innerHTML = milestones.slice(0, 8).map(function (m) {
            const done = !!(m && m.completed);
            const label = escapeHtml(String((m && (m.label || m.id)) || ''));
            const prog = escapeHtml(String((m && (m.progress || '')) || ''));
            return '<div class="maturity-milestone-row' + (done ? ' completed' : '') + '">' +
              '<div class="maturity-milestone-label">' + (done ? '✓ ' : '○ ') + label + '</div>' +
              '<div class="maturity-milestone-progress">' + prog + '</div>' +
              '</div>';
          }).join('');
        }
      }
    } catch (_) {}

    try {
      const lastRank = Number(localStorage.getItem('layla_last_maturity_rank') || '0');
      localStorage.setItem('layla_last_maturity_rank', String(rank));
      if (showCeremony && isFinite(lastRank) && rank > lastRank) {
        const ov = document.getElementById('rankup-overlay');
        const detail = document.getElementById('rankup-detail');
        if (detail) detail.textContent = 'Mastery Rank increased to ' + rank + ' (' + phase + ').';
        if (ov) {
          ov.classList.add('visible');
          setTimeout(function () { ov.classList.remove('visible'); }, 2200);
        }
        if (typeof showToast === 'function') showToast('Rank up: MR ' + rank);
      }
    } catch (_) {}
  } catch (_) {}
}
window.refreshMaturityCard = refreshMaturityCard;

function toggleAspectDescription(id) {
  const all = document.querySelectorAll('.aspect-option.expandable');
  all.forEach(el => {
    const isTarget = el.id === ('aspect-opt-' + id);
    el.classList.toggle('expanded', isTarget ? !el.classList.contains('expanded') : false);
  });
}
window.toggleAspectDescription = toggleAspectDescription;

function expandAspectDescription(id) {
  // Expand exactly one aspect description, collapse all others (no toggle — always show)
  document.querySelectorAll('.aspect-option.expandable').forEach(el => {
    el.classList.toggle('expanded', el.id === ('aspect-opt-' + id));
  });
}

function refreshOptionDependencies() {
  const showThinking = document.getElementById('show-thinking')?.checked ?? false;
  const reasoningRow = document.getElementById('reasoning-effort-row');
  const reasoningBox = document.getElementById('reasoning-effort');
  if (reasoningRow && reasoningBox) {
    const disabled = !showThinking;
    reasoningRow.classList.toggle('disabled', disabled);
    reasoningBox.disabled = disabled;
    if (disabled) reasoningBox.checked = false;
  }

  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  const addBtn = document.getElementById('workspace-add-btn');
  const removeBtn = document.getElementById('workspace-remove-btn');
  if (addBtn) {
    addBtn.disabled = !wp;
    addBtn.style.opacity = wp ? '1' : '0.45';
    addBtn.style.pointerEvents = wp ? 'auto' : 'none';
  }
  if (removeBtn) {
    removeBtn.disabled = !wp;
    removeBtn.style.opacity = wp ? '1' : '0.45';
    removeBtn.style.pointerEvents = wp ? 'auto' : 'none';
  }
}
window.refreshOptionDependencies = refreshOptionDependencies;

// ── First-run setup + onboarding (GET /setup_status, /setup/models, /setup/download SSE) ──
var _setupSelectedModel = null;
var _setupEventSource = null;

function stopModelDownloadStream() {
  try {
    if (_setupEventSource) {
      _setupEventSource.close();
      _setupEventSource = null;
    }
  } catch (_) {}
}

function _setupRefreshDownloadButton() {
  var btn = document.getElementById('setup-download-btn');
  if (!btn) return;
  var customEl = document.getElementById('setup-custom-url');
  var custom = (customEl && customEl.value || '').trim();
  btn.disabled = !((_setupSelectedModel && _setupSelectedModel.url) || custom);
}

async function saveSetupWorkspaceIfNeeded() {
  var inp = document.getElementById('setup-workspace-path');
  var path = (inp && inp.value || '').trim();
  if (!path) return;
  try {
    await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sandbox_root: path }),
    });
  } catch (_) {}
}

function renderSetupHardware(hw) {
  var el = document.getElementById('setup-hw');
  if (!el) return;
  if (!hw || !Object.keys(hw).length) {
    el.textContent = 'Hardware details unavailable — you can tune the model in Settings after setup.';
    return;
  }
  var lines = [];
  if (hw.ram_gb != null) lines.push('RAM: ~' + hw.ram_gb + ' GB');
  if (hw.gpu_vendor && hw.gpu_vendor !== 'none') {
    lines.push('GPU: ' + hw.gpu_vendor + (hw.vram_gb != null ? ' (~' + hw.vram_gb + ' GB VRAM)' : ''));
  } else lines.push('GPU: not detected (CPU inference)');
  if (hw.suggestion) lines.push('Hint: ' + hw.suggestion);
  el.innerHTML = lines.map(function (l) { return escapeHtml(l); }).join('<br>');
}

function renderSetupExistingModels(list) {
  var wrap = document.getElementById('setup-existing-models');
  var lst = document.getElementById('setup-existing-list');
  if (!wrap || !lst) return;
  if (!list || !list.length) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = 'block';
  lst.innerHTML = list.map(function (name) {
    return '<button type="button" class="tab-btn setup-model-pick" style="margin:4px 4px 4px 0" data-filename="' + String(name).replace(/"/g, '&quot;') + '">Use ' + escapeHtml(String(name)) + '</button>';
  }).join(' ');
  lst.querySelectorAll('.setup-model-pick').forEach(function (btn) {
    btn.onclick = function () { useExistingSetupModel(btn.getAttribute('data-filename')); };
  });
}

async function useExistingSetupModel(filename) {
  await saveSetupWorkspaceIfNeeded();
  stopModelDownloadStream();
  try {
    var res = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_filename: filename }),
    });
    if (res.ok) {
      var o = document.getElementById('setup-overlay');
      if (o) o.classList.remove('visible');
      showToast('Model selected');
      await checkSetupStatus();
    } else showToast('Could not save model setting');
  } catch (_) {
    showToast('Save failed');
  }
}

function _renderSetupCatalogError(container, message) {
  if (!container) return;
  var msg = message || 'Could not load catalog';
  container.innerHTML =
    '<div style="color:var(--text-dim);font-size:0.8rem;line-height:1.45">' + escapeHtml(msg) + '</div>' +
    '<button type="button" class="tab-btn" style="margin-top:10px" onclick="loadSetupCatalog()">Retry</button>';
}
async function loadSetupCatalog() {
  var container = document.getElementById('setup-model-list');
  if (!container) return;
  container.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem">Loading catalog…</div>';
  try {
    var res = await fetchWithTimeout('/setup/models', {}, 20000);
    var data = await res.json().catch(function () { return null; });
    if (!res.ok || !data || !data.ok || !Array.isArray(data.catalog)) {
      _renderSetupCatalogError(container, (data && data.error) || formatAgentError(res, data || {}));
      return;
    }
    container.innerHTML = '';
    data.catalog.forEach(function (m) {
      var div = document.createElement('div');
      div.className = 'setup-catalog-row';
      div.setAttribute('data-match-name', String(m.name || '').toLowerCase());
      div.setAttribute('data-match-key', String(m.key || '').toLowerCase());
      div.setAttribute('data-match-file', String(m.filename || m.gguf_filename || '').toLowerCase());
      div.style.cssText = 'margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:6px;cursor:pointer;opacity:' + (m.viable ? '1' : '0.55');
      div.innerHTML = '<strong>' + escapeHtml(m.name || '') + '</strong> <span style="font-size:0.7rem;color:var(--text-dim)">' + (m.recommended ? '(recommended) ' : '') + (m.viable ? '' : ' — may need more RAM') + '</span><br><span style="font-size:0.72rem;color:var(--text-dim)">' + escapeHtml(m.desc || '') + '</span>';
      div.onclick = function () {
        if (!m.viable && !confirm('This model may exceed your detected RAM. Download anyway?')) return;
        _setupSelectedModel = m;
        container.querySelectorAll('.setup-catalog-row').forEach(function (el) { el.style.outline = ''; });
        div.style.outline = '2px solid var(--asp)';
        _setupRefreshDownloadButton();
      };
      container.appendChild(div);
    });
    _setupRefreshDownloadButton();
  } catch (e) {
    var timedOut = e && e.name === 'AbortError';
    _renderSetupCatalogError(container, timedOut ? 'Catalog request timed out.' : 'Failed to load catalog');
  }
}
window.loadSetupCatalog = loadSetupCatalog;

async function prefillSetupWorkspaceFromSettings(statusPayload) {
  var inp = document.getElementById('setup-workspace-path');
  if (!inp || inp.getAttribute('data-user-edited') === '1') return;
  var sr = '';
  if (statusPayload && (statusPayload.sandbox_root || '').trim()) {
    sr = String(statusPayload.sandbox_root || '').trim();
  }
  if (!sr) {
    try {
      var r = await fetch('/settings');
      if (r.ok) {
        var cfg = await r.json();
        sr = (cfg.sandbox_root || '').trim();
      }
    } catch (_) {}
  }
  if (sr && !inp.value) inp.value = sr;
}

function trySelectSetupCatalogMatch(statusPayload) {
  if (!statusPayload) return;
  var want = String(statusPayload.resolved_model || statusPayload.model_filename || '').trim().toLowerCase();
  if (!want) return;
  var container = document.getElementById('setup-model-list');
  if (!container) return;
  var rows = container.querySelectorAll('.setup-catalog-row');
  rows.forEach(function (div) {
    var fn = String(div.getAttribute('data-match-file') || '').toLowerCase();
    var nm = String(div.getAttribute('data-match-name') || '').toLowerCase();
    var key = String(div.getAttribute('data-match-key') || '').toLowerCase();
    if (!want) return;
    if (fn === want || fn.indexOf(want) >= 0 || want.indexOf(fn) >= 0 || nm.indexOf(want) >= 0 || key === want) {
      div.click();
    }
  });
}

function _renderSetupStatusError(res, body, err) {
  var overlay = document.getElementById('setup-overlay');
  if (overlay) overlay.classList.add('visible');
  var el = document.getElementById('setup-hw');
  if (!el) return;
  var msg =
    err && err.name === 'AbortError'
      ? 'Setup status timed out. Check that Layla is responding.'
      : res
        ? formatAgentError(res, body || {})
        : 'Could not reach Layla. Is the server running?';
  el.innerHTML =
    '<span style="color:var(--text-dim)">' + escapeHtml(msg) + '</span><br>' +
    '<button type="button" class="tab-btn" style="margin-top:8px" onclick="checkSetupStatus()">Retry</button>';
}
async function checkSetupStatus() {
  var overlay = document.getElementById('setup-overlay');
  try {
    var res = await fetchWithTimeout('/setup_status', {}, 15000);
    var s = await res.json().catch(function () { return null; });
    if (!res.ok || !s) {
      _renderSetupStatusError(res, s, null);
      return;
    }
    if (s.ready && s.model_found) {
      if (overlay) overlay.classList.remove('visible');
      maybeStartOnboarding();
      return;
    }
    if (overlay) overlay.classList.add('visible');
    await prefillSetupWorkspaceFromSettings(s);
    renderSetupHardware(s.hardware || {});
    renderSetupExistingModels(s.available_models || []);
    await loadSetupCatalog();
    trySelectSetupCatalogMatch(s);
    _setupRefreshDownloadButton();
  } catch (e) {
    _dbg('checkSetupStatus failed', e);
    _renderSetupStatusError(null, null, e);
    if (typeof showToast === 'function') showToast('Setup check failed — is Layla running?');
  }
}
window.checkSetupStatus = checkSetupStatus;

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
          html += '<div class="settings-row settings-section"><label style="display:flex;align-items:center;gap:8px;font-size:0.8rem;text-transform:none;color:var(--text)"><input type="checkbox" id="' + id + '" ' + (v ? 'checked' : '') + '/> ' + escapeHtml(k) + '</label><div class="hint">' + hint + '</div></div>';
        } else if (f.type === 'number') {
          html += '<div class="settings-row settings-section"><label>' + escapeHtml(k) + '</label><input type="number" id="' + id + '" value="' + (v != null ? String(v) : '') + '" step="any"/><div class="hint">' + hint + '</div></div>';
        } else {
          html += '<div class="settings-row settings-section"><label>' + escapeHtml(k) + '</label><input type="text" id="' + id + '" value="' + escapeHtml(String(v != null ? v : '')) + '"/><div class="hint">' + hint + '</div></div>';
        }
      });
      formEl.innerHTML = html;
    }
  } catch (e) {
    if (loadEl) { loadEl.style.display = 'none'; }
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
function closeSettings() {
  var ov = document.getElementById('settings-overlay');
  if (ov) ov.classList.remove('visible');
}
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
      if (typeof showToast === 'function') showToast('Settings saved');
    } else if (typeof showToast === 'function') showToast('Save failed');
  } catch (e) {
    if (typeof showToast === 'function') showToast('Save failed');
  }
}
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
      return '<div style="margin:4px 0;padding:4px;border-bottom:1px solid rgba(255,255,255,0.08)">' + st + ' <strong>' + escapeHtml(f.id) + '</strong> — ' + escapeHtml(f.label) +
        (!f.installed ? ' <button type="button" class="settings-save" style="padding:2px 8px;font-size:0.65rem" data-fid="' + escapeHtml(f.id) + '">Install</button>' : '') + '</div>';
    }).join('');
    box.querySelectorAll('button[data-fid]').forEach(function (btn) {
      btn.onclick = function () { laylaInstallFeature(btn.getAttribute('data-fid')); };
    });
  } catch (e) { box.textContent = 'Error'; }
}
async function laylaInstallFeature(fid) {
  if (!fid || !confirm('Install feature ' + fid + ' via pip (allowlisted packages)?')) return;
  try {
    var r = await fetch('/settings/install_feature', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ feature_id: fid }) });
    var d = await r.json();
    var note = d.ok ? 'Install finished' : ((d.pip_attempt && d.pip_attempt.error) || d.error || 'failed');
    if (typeof showToast === 'function') showToast(note);
    laylaLoadOptionalFeatures();
  } catch (e) { if (typeof showToast === 'function') showToast('Install failed'); }
}
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
window.openSettings = openSettings;
window.closeSettings = closeSettings;
window.saveSettings = saveSettings;
window.laylaLoadOptionalFeatures = laylaLoadOptionalFeatures;
window.laylaInstallFeature = laylaInstallFeature;
window.laylaImportChat = laylaImportChat;
window.laylaGitUndoCheckpoint = laylaGitUndoCheckpoint;

function startModelDownload() {
  var url = '';
  var filename = '';
  if (_setupSelectedModel && _setupSelectedModel.url) {
    url = _setupSelectedModel.url;
    filename = _setupSelectedModel.filename || '';
  } else {
    var customEl = document.getElementById('setup-custom-url');
    url = (customEl && customEl.value || '').trim();
  }
  if (!url) {
    showToast('Select a model or paste a .gguf URL');
    return;
  }
  stopModelDownloadStream();
  var bar = document.getElementById('setup-progress-bar');
  var label = document.getElementById('setup-progress-label');
  var doneMsg = document.getElementById('setup-done-msg');
  var retryBtn = document.getElementById('setup-retry-btn');
  if (bar) bar.style.width = '0%';
  if (label) label.textContent = 'Starting download…';
  if (doneMsg) doneMsg.textContent = '';
  if (retryBtn) retryBtn.style.display = 'none';

  saveSetupWorkspaceIfNeeded().then(function () {
    var qs = '/setup/download?url=' + encodeURIComponent(url);
    if (filename) qs += '&filename=' + encodeURIComponent(filename);
    try {
      _setupEventSource = new EventSource(qs);
    } catch (err) {
      showToast('Download could not start');
      return;
    }
    _setupEventSource.onmessage = function (ev) {
      try {
        var d = JSON.parse(ev.data);
        if (d.error) {
          stopModelDownloadStream();
          if (label) label.textContent = 'Error: ' + d.error;
          if (retryBtn) retryBtn.style.display = '';
          showToast('Download failed');
          return;
        }
        if (typeof d.pct === 'number' && bar) bar.style.width = d.pct + '%';
        if (label && typeof d.dl_mb === 'number' && typeof d.tot_mb === 'number') {
          label.textContent = 'Downloading… ' + d.pct + '% (' + d.dl_mb + ' / ' + d.tot_mb + ' MB)';
        } else if (label) label.textContent = 'Downloading…';
        if (d.done) {
          stopModelDownloadStream();
          if (doneMsg) doneMsg.textContent = 'Done — ' + (d.filename || 'model saved');
          showToast('Model ready');
          setTimeout(function () {
            var o = document.getElementById('setup-overlay');
            if (o) o.classList.remove('visible');
            checkSetupStatus();
          }, 400);
        }
      } catch (_) {}
    };
    _setupEventSource.onerror = function () {
      stopModelDownloadStream();
      if (label) label.textContent = 'Connection lost — try Retry';
      if (retryBtn) retryBtn.style.display = '';
    };
  });
}
window.startModelDownload = startModelDownload;

function retryModelDownload() {
  var retryBtn = document.getElementById('setup-retry-btn');
  if (retryBtn) retryBtn.style.display = 'none';
  startModelDownload();
}
window.retryModelDownload = retryModelDownload;

function dismissSetupOverlay(isSkip) {
  var o = document.getElementById('setup-overlay');
  if (o) o.classList.remove('visible');
  if (isSkip === true) saveSetupWorkspaceIfNeeded();
  maybeStartOnboarding();
}
window.dismissSetupOverlay = dismissSetupOverlay;

var _onboardingStep = 0;

function highlightAspectSidebar(on) {
  var el = document.querySelector('.layout .sidebar');
  if (!el) return;
  el.classList.toggle('onboarding-highlight', !!on);
}

function renderOnboardingStep() {
  var text = document.getElementById('onboarding-text');
  var nextBtn = document.getElementById('onboarding-next');
  var doneBtn = document.getElementById('onboarding-done');
  if (!text) return;
  highlightAspectSidebar(false);
  if (_onboardingStep <= 0) {
    text.textContent = 'Layla only reads and writes inside your workspace folder (set in First Setup or Prefs). File changes and shell commands stay behind approval gates.';
    if (doneBtn) doneBtn.style.display = 'none';
    if (nextBtn) nextBtn.style.display = '';
    return;
  }
  if (_onboardingStep === 1) {
    text.textContent = 'Pick a voice (facet) in the sidebar — Morrigan for engineering, Nyx for research, Echo for continuity, and more.';
    highlightAspectSidebar(true);
    if (doneBtn) doneBtn.style.display = 'none';
    if (nextBtn) nextBtn.style.display = '';
    return;
  }
  text.textContent = 'Use the padlock next to the aspect badge to lock routing. You can revisit VALUES.md and ethics from Help anytime.';
  if (nextBtn) nextBtn.style.display = 'none';
  if (doneBtn) doneBtn.style.display = '';
}

function maybeStartOnboarding() {
  try {
    if (localStorage.getItem('layla_onboarding_v1_done') === '1') return;
    var ov = document.getElementById('onboarding-overlay');
    if (!ov) return;
    _onboardingStep = 0;
    renderOnboardingStep();
    ov.classList.add('visible');
  } catch (_) {}
}

function onboardingNext() {
  _onboardingStep++;
  if (_onboardingStep > 2) _onboardingStep = 2;
  renderOnboardingStep();
}
window.onboardingNext = onboardingNext;

function dismissOnboarding() {
  var ov = document.getElementById('onboarding-overlay');
  if (ov) ov.classList.remove('visible');
  try { localStorage.setItem('layla_onboarding_v1_done', '1'); } catch (_) {}
  highlightAspectSidebar(false);
}
window.dismissOnboarding = dismissOnboarding;

function cleanLaylaText(s) {
  if (typeof s !== 'string') return (s == null || s === undefined) ? '' : String(s);
  return s.replace(/\s*\[EARNED_TITLE:\s*[^\]]+\]\s*$/gi, '').trim();
}
function sanitizeHtml(html) {
  if (typeof html !== 'string') return '';
  if (typeof DOMPurify !== 'undefined') return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['p','br','strong','em','code','pre','ul','ol','li','a','h1','h2','h3','blockquote','span','div'], ALLOWED_ATTR: ['href','class'] });
  return html.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '').replace(/on\w+\s*=\s*["'][^"']*["']/gi, '').replace(/javascript:/gi, '');
}

// Aspect → TTS voice style (rate, pitch) for browser SpeechSynthesis fallback
// rate: speaking speed multiplier; pitch: voice pitch (1=neutral, >1=higher, <1=lower)
// Morrigan: fast/clipped/authoritative | Nyx: slow/measured | Echo: warm/rounded
// Eris: playful/varied | Cassandra: rapid-fire | Lilith: slow/deliberate/weighted
const TTS_VOICE_STYLES = {
  morrigan:  { rate: 1.05, pitch: 0.90 },  // fast, lower pitch = authority
  nyx:       { rate: 0.82, pitch: 0.88 },  // slow, low = thoughtful depth
  eris:      { rate: 1.20, pitch: 1.12 },  // fast, high = playful energy
  echo:      { rate: 0.90, pitch: 1.10 },  // medium-slow, higher = warmth
  cassandra: { rate: 1.15, pitch: 1.05 },  // rapid, slightly elevated
  lilith:    { rate: 0.78, pitch: 0.88 },  // very slow, low = deliberate weight
};
const UX_STATE_LABELS = {
  connecting: 'Connecting',
  waiting_first_token: 'Waiting for first token',
  streaming: 'Streaming response',
  tool_running: 'Running tool',
  verifying: 'Verifying',
  thinking: 'Thinking',
  stalled: 'Stalled',
  retry_hint: 'Retry suggested',
  changing_approach: 'Changing approach',
  reframing_objective: 'Reframing objective',
  preparing_reply: 'Preparing reply…',
  still_working: 'Still working…',
  approaching_context_limit: 'Context ~70%+ full',
  context_critical: 'Context critical — compact',
};

function laylaNotifyStreamPhase(row, uxKey) {
  try {
    if (window.LaylaUI && typeof window.LaylaUI.syncStreamRowPhase === 'function')
      window.LaylaUI.syncStreamRowPhase(row, uxKey);
  } catch (_) {}
}

function laylaApplyUiTimeoutsFromHealth(d) {
  if (!d) return;
  try {
    const lim = d.effective_limits || {};
    const ec = d.effective_config || {};
    const streamSec = Number(lim.ui_agent_stream_timeout_seconds ?? ec.ui_agent_stream_timeout_seconds);
    const jsonSec = Number(lim.ui_agent_json_timeout_seconds ?? ec.ui_agent_json_timeout_seconds);
    const stalledOverride = Number(lim.ui_stalled_silence_ms ?? ec.ui_stalled_silence_ms);
    window.__laylaUiTimeouts = {
      streamMs: Number.isFinite(streamSec) && streamSec > 0 ? Math.round(streamSec * 1000) : 900000,
      jsonMs: Number.isFinite(jsonSec) && jsonSec > 0 ? Math.round(jsonSec * 1000) : 720000,
      stalledMs: Number.isFinite(stalledOverride) && stalledOverride > 0 ? Math.round(stalledOverride) : 0,
      maxRuntimeSeconds: Number(lim.max_runtime_seconds) > 0 ? Number(lim.max_runtime_seconds) : 900,
      performanceMode: String(lim.performance_mode || ec.performance_mode || 'auto').toLowerCase(),
    };
  } catch (_) {}
}
function laylaAgentStreamTimeoutMs() {
  const t = window.__laylaUiTimeouts;
  return t && t.streamMs > 0 ? t.streamMs : 900000;
}
function laylaAgentJsonTimeoutMs() {
  const t = window.__laylaUiTimeouts;
  return t && t.jsonMs > 0 ? t.jsonMs : 720000;
}
function laylaStalledSilenceMs() {
  const t = window.__laylaUiTimeouts || {};
  if (t.stalledMs > 0) return t.stalledMs;
  const mrs = Number(t.maxRuntimeSeconds) > 0 ? Number(t.maxRuntimeSeconds) : 900;
  const pm = t.performanceMode || 'auto';
  const mult = pm === 'low' ? 2.5 : pm === 'mid' ? 1.65 : 1;
  return Math.min(240000, Math.max(38000, Math.round(mrs * 1000 * 0.42 * mult)));
}
function laylaHeaderProgressStart() {
  const row = document.getElementById('header-progress-row');
  const fill = document.getElementById('header-progress-fill');
  if (!row || !fill) return;
  row.style.display = 'block';
  row.classList.add('active', 'indeterminate');
  fill.style.width = '42%';
}
function laylaHeaderProgressStop() {
  const row = document.getElementById('header-progress-row');
  const fill = document.getElementById('header-progress-fill');
  if (row) {
    row.classList.remove('active', 'indeterminate');
    row.style.display = 'none';
  }
  if (fill) fill.style.width = '0%';
}
function operatorTraceClear() {
  const b = document.getElementById('operator-trace-log');
  if (b) b.innerHTML = '';
}
function operatorTraceLine(kind, text) {
  const b = document.getElementById('operator-trace-log');
  if (!b) return;
  const t = new Date().toISOString().slice(11, 19);
  const line = document.createElement('div');
  line.className = 'operator-trace-line';
  line.textContent = '[' + t + '] ' + kind + ': ' + String(text || '').replace(/\s+/g, ' ').slice(0, 800);
  b.appendChild(line);
  while (b.children.length > 80) b.removeChild(b.firstChild);
  b.scrollTop = b.scrollHeight;
}

// ─── Phase 1.6: Stream stats dock ─────────────────────────────────────────────
let _streamStatsActive = false;
let _streamStepCount = 0;
let _streamStartTs = 0;
let _streamElapsedTimer = null;

function laylaStreamStatsStart(modelName) {
  _streamStatsActive = true;
  _streamStepCount = 0;
  _streamStartTs = Date.now();
  const row = document.getElementById('stream-stats-row');
  if (row) row.style.display = 'flex';
  const badge = document.getElementById('stream-step-badge');
  if (badge) { badge.textContent = ''; badge.style.display = 'inline'; }
  const modelEl = document.getElementById('stream-model-badge');
  if (modelEl) modelEl.textContent = modelName ? '⬡ ' + modelName : '';
  _updateStreamStepEl();
  clearInterval(_streamElapsedTimer);
  _streamElapsedTimer = setInterval(_updateStreamElapsed, 1000);
}

function laylaStreamStatsStep(label) {
  if (!_streamStatsActive) return;
  _streamStepCount++;
  _updateStreamStepEl();
  if (label) operatorTraceLine('step', label);
}

function laylaStreamStatsChars(n) {
  if (!_streamStatsActive) return;
  const el = document.getElementById('stream-token-counter');
  if (el) el.textContent = n + ' chars';
}

function laylaStreamStatsStop() {
  _streamStatsActive = false;
  clearInterval(_streamElapsedTimer);
  _streamElapsedTimer = null;
  const badge = document.getElementById('stream-step-badge');
  if (badge) badge.style.display = 'none';
  setTimeout(() => {
    const row = document.getElementById('stream-stats-row');
    if (row) row.style.display = 'none';
  }, 3000);
}

function _updateStreamStepEl() {
  const el = document.getElementById('stream-step-counter');
  if (el) el.textContent = 'step ' + _streamStepCount;
  const badge = document.getElementById('stream-step-badge');
  if (badge && _streamStepCount > 0) badge.textContent = '· ' + _streamStepCount + ' steps';
}

function _updateStreamElapsed() {
  if (!_streamStatsActive) return;
  const el = document.getElementById('stream-elapsed-counter');
  if (el) el.textContent = Math.round((Date.now() - _streamStartTs) / 1000) + 's';
}
function toggleComposePanel(force) {
  const p = document.getElementById('compose-panel');
  if (!p) return;
  let on;
  if (force === true) on = true;
  else if (force === false) on = false;
  else on = !p.classList.contains('visible');
  p.classList.toggle('visible', on);
  try { localStorage.setItem('layla_compose_open', on ? '1' : '0'); } catch (_) {}
}
function laylaRunPlanFromElement(el) {
  if (!el) return;
  const ta = el.querySelector('.layla-plan-json');
  const goal = el.dataset.planGoal || '';
  if (!ta) return;
  let plan;
  try {
    plan = JSON.parse(ta.value);
  } catch (e) {
    if (typeof showToast === 'function') showToast('Invalid JSON — fix the plan text');
    return;
  }
  if (!Array.isArray(plan)) {
    if (typeof showToast === 'function') showToast('Plan must be a JSON array of steps');
    return;
  }
  executePlan(plan, goal);
}
function laylaFormatPlanJson(btn) {
  const el = btn && btn.closest && btn.closest('.plan-review-msg');
  const ta = el && el.querySelector('.layla-plan-json');
  if (!ta) return;
  try {
    const p = JSON.parse(ta.value);
    ta.value = JSON.stringify(p, null, 2);
    if (typeof showToast === 'function') showToast('Plan reformatted');
  } catch (e) {
    if (typeof showToast === 'function') showToast('Invalid JSON');
  }
}

/** POST /execute_plan — runs stored plan steps on the server (blocking until done). */
async function executePlan(plan, goal) {
  const workspacePath = (document.getElementById('workspace-path')?.value || '').trim();
  const allowWrite = document.getElementById('allow-write')?.checked ?? false;
  const allowRun = document.getElementById('allow-run')?.checked ?? false;
  try { ensureLaylaConversationId(); } catch (_) {}
  try { laylaHeaderProgressStart(); } catch (_) {}
  try {
    const res = await fetchWithTimeout(
      '/execute_plan',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan,
          goal: goal || '',
          workspace_root: workspacePath,
          aspect_id: typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan',
          conversation_id: typeof currentConversationId !== 'undefined' ? currentConversationId : '',
          allow_write: !!allowWrite,
          allow_run: !!allowRun,
        }),
      },
      600000
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const err = (data && (data.error || data.detail)) ? String(data.error || data.detail) : ('HTTP ' + res.status);
      if (typeof showToast === 'function') showToast(err);
      else _dbg('executePlan failed', err);
      return;
    }
    const okAll = !!data.all_steps_ok;
    if (typeof showToast === 'function') showToast(okAll ? 'Plan finished' : 'Plan finished (some steps reported issues)');
    try {
      const summary = JSON.stringify(data.results || {}, null, 2);
      addMsg('layla', '**Plan executed**\n```json\n' + summary.slice(0, 12000) + (summary.length > 12000 ? '\n…' : '') + '\n```');
    } catch (_) {}
  } catch (e) {
    const msg = (e && e.message) ? String(e.message) : String(e);
    if (typeof showToast === 'function') showToast('executePlan: ' + msg);
    else _dbg('executePlan', e);
  } finally {
    try { laylaHeaderProgressStop(); } catch (_) {}
  }
}

/** POST /compact — summarize in-memory history (shows remaining message count). */
async function compactConversation() {
  try {
    const res = await fetchWithTimeout(
      '/compact',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: typeof currentConversationId !== 'undefined' ? currentConversationId : '' }),
      },
      120000
    );
    const data = await res.json().catch(() => ({}));
    const n = data && typeof data.messages_remaining === 'number' ? data.messages_remaining : null;
    const tok = n != null ? String(n) : '?';
    if (typeof showToast === 'function') showToast('Compacted · messages in buffer: ~' + tok);
    try { if (typeof updateContextChip === 'function') updateContextChip(); } catch (_) {}
  } catch (e) {
    if (typeof showToast === 'function') showToast('Compact failed: ' + ((e && e.message) || e));
  }
}

function _guessPathFromCodeBlock(text) {
  const lines = String(text || '').split(/\r?\n/).slice(0, 8);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const m = line.match(/(?:file|path)\s*[:=]\s*[`'"]?([^\s`'")\]]+)/i);
    if (m && m[1]) return m[1].trim();
  }
  return '';
}

async function _laylaApprovePendingForCodeBlock(codeText) {
  const res = await fetchWithTimeout('/pending', {}, 8000);
  const data = await res.json().catch(() => ({}));
  const pending = Array.isArray(data.pending) ? data.pending : [];
  const todo = pending.filter(e => e && e.status === 'pending');
  if (!todo.length) {
    if (typeof showToast === 'function') showToast('No pending approvals — use the Approvals panel');
    return;
  }
  let id = '';
  if (todo.length === 1) {
    id = String(todo[0].id || '');
  } else {
    const hint = _guessPathFromCodeBlock(codeText);
    for (let i = 0; i < todo.length; i++) {
      const e = todo[i];
      const args = e.args || {};
      const paths = [args.path, args.file, args.file_path, args.target_file].filter(function (x) { return x && String(x).trim(); }).map(function (x) { return String(x); });
      for (let j = 0; j < paths.length; j++) {
        const p = paths[j];
        if (hint && (p === hint || p.endsWith(hint) || p.includes(hint))) {
          id = String(e.id || '');
          break;
        }
      }
      if (id) break;
    }
    if (!id) id = String(todo[0].id || '');
  }
  if (!id) return;
  const r = await fetchWithTimeout('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id }) }, 15000);
  const body = await r.json().catch(() => ({}));
  if (!r.ok || !body.ok) {
    if (typeof showToast === 'function') showToast((body && body.error) ? String(body.error) : ('Approve failed: ' + r.status));
    return;
  }
  if (typeof showToast === 'function') showToast('Applied');
  try { refreshApprovals(); } catch (_) {}
}

/** Per-code-block quick approve using GET /pending + POST /approve (matches path hint when multiple). */
function _addApplyBtnToCodeBlock(wrap, codeEl) {
  if (!wrap || !codeEl) return;
  const applyBtn = document.createElement('button');
  applyBtn.type = 'button';
  applyBtn.className = 'copy-btn';
  applyBtn.style.marginLeft = '4px';
  applyBtn.textContent = 'apply';
  applyBtn.title = 'Approve matching pending tool call (see Approvals panel for diff)';
  applyBtn.onclick = function (ev) {
    ev.stopPropagation();
    const txt = (codeEl.innerText || codeEl.textContent || '').trim();
    _laylaApprovePendingForCodeBlock(txt).catch(function (e) {
      if (typeof showToast === 'function') showToast(String((e && e.message) || e));
    });
  };
  wrap.appendChild(applyBtn);
}

function _workspacePresetStorageKey() {
  try {
    return 'layla_workspace_presets_' + String(location.origin || 'local');
  } catch (_) {
    return 'layla_workspace_presets_local';
  }
}
function _loadWorkspacePresets() {
  try {
    const raw = localStorage.getItem(_workspacePresetStorageKey());
    const a = raw ? JSON.parse(raw) : [];
    return Array.isArray(a) ? a.filter(function (x) { return typeof x === 'string' && x.trim(); }) : [];
  } catch (_) {
    return [];
  }
}
function _saveWorkspacePresets(paths) {
  try {
    localStorage.setItem(_workspacePresetStorageKey(), JSON.stringify(paths));
  } catch (_) {}
}
function refreshWorkspacePresetsDropdown() {
  const sel = document.getElementById('workspace-presets');
  if (!sel) return;
  const paths = _loadWorkspacePresets();
  sel.innerHTML = '';
  const opt0 = document.createElement('option');
  opt0.value = '';
  opt0.textContent = paths.length ? 'Presets…' : 'No presets';
  sel.appendChild(opt0);
  paths.forEach(function (p) {
    const o = document.createElement('option');
    o.value = p;
    o.textContent = p.length > 52 ? '…' + p.slice(-48) : p;
    sel.appendChild(o);
  });
}
function addWorkspacePreset() {
  const inp = document.getElementById('workspace-path');
  const p = (inp && inp.value || '').trim();
  if (!p) {
    if (typeof showToast === 'function') showToast('Set workspace path first');
    return;
  }
  let paths = _loadWorkspacePresets();
  if (paths.indexOf(p) >= 0) {
    if (typeof showToast === 'function') showToast('Already in list');
    return;
  }
  paths.push(p);
  _saveWorkspacePresets(paths);
  refreshWorkspacePresetsDropdown();
  if (typeof showToast === 'function') showToast('Preset saved');
}
function removeWorkspacePreset() {
  const sel = document.getElementById('workspace-presets');
  if (!sel || !sel.value) {
    if (typeof showToast === 'function') showToast('Select a preset to remove');
    return;
  }
  const p = sel.value;
  const paths = _loadWorkspacePresets().filter(function (x) { return x !== p; });
  _saveWorkspacePresets(paths);
  refreshWorkspacePresetsDropdown();
  if (typeof showToast === 'function') showToast('Removed preset');
}
function onWorkspacePresetSelect() {
  const sel = document.getElementById('workspace-presets');
  const inp = document.getElementById('workspace-path');
  if (!sel || !inp || !sel.value) return;
  inp.value = sel.value;
  try {
    inp.dispatchEvent(new Event('input', { bubbles: true }));
  } catch (_) {}
}

async function refreshRelationshipCodex() {
  const st = document.getElementById('relationship-codex-status');
  const ta = document.getElementById('relationship-codex-json');
  const workspacePath = (document.getElementById('workspace-path')?.value || '').trim();
  if (!ta) return;
  if (!workspacePath) {
    if (st) st.textContent = 'Set workspace path first.';
    if (typeof showToast === 'function') showToast('Set workspace first');
    return;
  }
  if (st) st.textContent = 'Loading…';
  try {
    const url = '/codex/relationship?workspace_root=' + encodeURIComponent(workspacePath);
    const res = await fetchWithTimeout(url, {}, 15000);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      const err = (data && data.error) ? String(data.error) : 'Not available';
      if (st) st.textContent = err.length > 120 ? err.slice(0, 120) + '…' : err;
      return;
    }
    ta.value = JSON.stringify(data.data != null ? data.data : {}, null, 2);
    if (st) st.textContent = 'Loaded';
  } catch (_) {
    if (st) st.textContent = 'Not available';
  }
}

async function saveRelationshipCodex() {
  const ta = document.getElementById('relationship-codex-json');
  const workspacePath = (document.getElementById('workspace-path')?.value || '').trim();
  if (!ta || !workspacePath) {
    if (typeof showToast === 'function') showToast('Workspace path required');
    return;
  }
  let body;
  try {
    body = JSON.parse(ta.value || '{}');
  } catch (_) {
    if (typeof showToast === 'function') showToast('Invalid JSON');
    return;
  }
  try {
    const res = await fetchWithTimeout(
      '/codex/relationship?workspace_root=' + encodeURIComponent(workspacePath),
      { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      20000
    );
    const data = await res.json().catch(() => ({}));
    if (typeof showToast === 'function') showToast((data && data.ok) ? 'Saved codex' : ('Save failed: ' + ((data && data.error) || res.status)));
  } catch (e) {
    if (typeof showToast === 'function') showToast('Save error: ' + ((e && e.message) || e));
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 12000) {
  const tCtrl = new AbortController();
  const timer = setTimeout(() => {
    try { tCtrl.abort(); } catch (_) {}
  }, timeoutMs);
  const userSig = options && options.signal;
  const linked = new AbortController();
  function abortLinked() {
    try { linked.abort(); } catch (_) {}
  }
  tCtrl.signal.addEventListener('abort', abortLinked);
  if (userSig) {
    if (userSig.aborted) abortLinked();
    else userSig.addEventListener('abort', abortLinked);
  }
  try {
    const merged = { ...options, signal: linked.signal };
    return await fetch(url, merged);
  } finally {
    clearTimeout(timer);
    try { tCtrl.signal.removeEventListener('abort', abortLinked); } catch (_) {}
    if (userSig) try { userSig.removeEventListener('abort', abortLinked); } catch (_) {}
  }
}

function speakReply(text, aspectId) {
  if (!text || typeof speechSynthesis === 'undefined') return;
  const style = TTS_VOICE_STYLES[aspectId] || { rate: 1, pitch: 1 };
  const u = new SpeechSynthesisUtterance(text.slice(0, 4000));
  u.rate = style.rate;
  u.pitch = style.pitch;
  speechSynthesis.speak(u);
}

function hideEmpty() {
  const e = document.getElementById('chat-empty');
  if (e) e.style.display = 'none';
}

function renderPromptTilesAndEmptyState() {
  return `<div class="sigil">∴</div><div class="hint">she is waiting</div>
      <div class="prompt-tiles" id="prompt-tiles">
        <button class="prompt-tile" onclick="fillPrompt('Explain how ')"><span class="tile-icon">✦</span><span class="tile-text">Explain something</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Write Python code to ')"><span class="tile-icon">⚔</span><span class="tile-text">Write code for me</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Research and summarize: ')"><span class="tile-icon">🔬</span><span class="tile-text">Research a topic</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Help me debug this error: ')"><span class="tile-icon">🔧</span><span class="tile-text">Debug an error</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Summarize this text: ')"><span class="tile-icon">◎</span><span class="tile-text">Summarize text</span></button>
        <button class="prompt-tile" onclick="fillPrompt('What should I do about ')"><span class="tile-icon">⌖</span><span class="tile-text">Get advice</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Refactor this code: ')"><span class="tile-icon">⚔</span><span class="tile-text">Refactor</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Add tests for ')"><span class="tile-icon">🧪</span><span class="tile-text">Add tests</span></button>
      </div>
      <div class="try-this-chips" style="margin-top:16px;display:flex;flex-wrap:wrap;gap:8px;justify-content:center">
        <button class="try-this-chip" onclick="fillPrompt('Explain quantum entanglement')" style="padding:6px 12px;font-size:0.75rem;background:var(--asp-mid);border:1px solid var(--asp);color:var(--text);border-radius:4px;cursor:pointer">Explain quantum entanglement</button>
        <button class="try-this-chip" onclick="fillPrompt('Write a Python hello world')" style="padding:6px 12px;font-size:0.75rem;background:var(--asp-mid);border:1px solid var(--asp);color:var(--text);border-radius:4px;cursor:pointer">Write a Python hello world</button>
      </div>`;
}

function _renderReasoningTreeSummary(container, summary) {
  if (!summary || !Array.isArray(summary.nodes) || summary.nodes.length === 0) return;
  const wrap = document.createElement('details');
  wrap.className = 'tool-trace';
  const mode = summary.reasoning_mode ? (' • ' + summary.reasoning_mode) : '';
  wrap.innerHTML = '<summary>Reasoning summary (' + summary.nodes.length + mode + ')</summary>';
  const body = document.createElement('div');
  body.className = 'tool-trace-content';
  const lines = [];
  if (summary.goal) lines.push('Goal: ' + summary.goal);
  summary.nodes.forEach((n, i) => {
    lines.push((i + 1) + '. [' + (n.phase || 'step') + '] ' + (n.action || 'reason') + ' -> ' + (n.outcome_summary || 'ok'));
  });
  if (summary.final_summary) lines.push('Final: ' + summary.final_summary);
  body.textContent = lines.join('\n');
  wrap.appendChild(body);
  container.appendChild(wrap);
}

async function rememberLaylaBubble(bubble, btn) {
  const txt = (bubble && (bubble.innerText || bubble.textContent) || '').trim();
  if (!txt) {
    showToast('Nothing to remember');
    return;
  }
  if (txt.length > 12000) {
    showToast('Message too long; copy a shorter excerpt');
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/learn/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: txt, type: 'fact', tags: 'ui:remember' }),
    });
    const d = await res.json();
    if (d.ok) {
      showToast('Saved to learnings');
      if (btn) {
        btn.textContent = 'saved';
        setTimeout(function() { btn.textContent = 'remember'; btn.disabled = false; }, 2000);
      }
    } else {
      showToast(d.error || 'Save failed');
      if (btn) btn.disabled = false;
    }
  } catch (e) {
    showToast('Error: ' + (e && e.message || e));
    if (btn) btn.disabled = false;
  }
}

function addMsg(role, text, aspectName, deliberated, steps, uxStates, memoryInfluenced, reasoningTreeSummary) {
  hideEmpty();
  const chat = document.getElementById('chat');
  if (!chat) return;
  const div = document.createElement('div');
  div.className = 'msg msg-' + (role === 'you' ? 'you' : 'layla');
  const label = document.createElement('div');
  label.className = 'msg-label' + (role === 'layla' ? ' msg-label-layla' : '');
  if (role === 'you') {
    const nameSpan = document.createElement('span');
    nameSpan.textContent = 'You';
    label.appendChild(nameSpan);
  } else {
    const brand = document.createElement('span');
    brand.className = 'msg-brand';
    brand.textContent = 'Layla';
    label.appendChild(brand);
    const facet = facetMetaFromNameOrId(aspectName || currentAspect);
    if (facet) {
      const chip = document.createElement('span');
      chip.className = 'msg-facet-chip';
      chip.textContent = facet.sym + ' ' + facet.name;
      chip.title = 'Facet (voice)';
      label.appendChild(chip);
    } else if (aspectName) {
      const chip = document.createElement('span');
      chip.className = 'msg-facet-chip msg-facet-unknown';
      chip.textContent = String(aspectName);
      label.appendChild(chip);
    } else {
      const chip = document.createElement('span');
      chip.className = 'msg-facet-chip msg-facet-unknown';
      chip.textContent = '◇ facet';
      chip.title = 'Session aspect: ' + (currentAspect || 'morrigan');
      label.appendChild(chip);
    }
  }
  const ts = document.createElement('span');
  ts.className = 'msg-ts';
  const now = new Date();
  ts.textContent = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
  label.appendChild(ts);
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.title = 'Click to copy';
  if (role === 'layla') {
    text = cleanLaylaText(text || '');
    if (typeof marked !== 'undefined') {
      const md = document.createElement('div');
      md.className = 'md-content';
      let parsed = '';
      try { parsed = marked.parse(text || ''); } catch (_) { parsed = (text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
      md.innerHTML = sanitizeHtml(parsed);
      // Syntax highlight + copy buttons on code blocks
      md.querySelectorAll('pre').forEach((pre) => {
        const code = pre.querySelector('code');
        if (code && window.hljs) hljs.highlightElement(code);
        const wrap = document.createElement('div');
        wrap.className = 'code-wrap';
        pre.parentNode.insertBefore(wrap, pre);
        wrap.appendChild(pre);
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.textContent = 'copy';
        copyBtn.onclick = () => {
          navigator.clipboard?.writeText(code ? code.innerText : pre.innerText).then(() => {
            copyBtn.textContent = 'copied';
            copyBtn.classList.add('copied');
            setTimeout(() => { copyBtn.textContent = 'copy'; copyBtn.classList.remove('copied'); }, 1800);
          });
        };
        wrap.appendChild(copyBtn);
        // Apply-to-file button (if filename detectable)
        if (code) _addApplyBtnToCodeBlock(wrap, code);
      });
      bubble.appendChild(md);
    } else {
      bubble.textContent = text;
    }
    // TTS is handled by send() and other entry points via tts-toggle checkbox
  } else {
    bubble.textContent = text;
  }
  if (role === 'layla') {
    const copyBtn = document.createElement('button');
    copyBtn.className = 'msg-copy-btn';
    copyBtn.textContent = 'copy';
    copyBtn.title = 'Copy response'; copyBtn.setAttribute('aria-label', 'Copy response');
    copyBtn.onclick = (ev) => {
      ev.stopPropagation();
      const txt = (bubble.innerText || bubble.textContent || '').trim();
      if (txt) navigator.clipboard?.writeText(txt).then(() => { copyBtn.textContent = 'copied'; copyBtn.classList.add('copied'); setTimeout(() => { copyBtn.textContent = 'copy'; copyBtn.classList.remove('copied'); }, 1500); }).catch(() => {});
    };
    label.appendChild(copyBtn);
    const rememberBtn = document.createElement('button');
    rememberBtn.className = 'msg-remember-btn';
    rememberBtn.type = 'button';
    rememberBtn.textContent = 'remember';
    rememberBtn.title = 'Save this reply as a learning';
    rememberBtn.setAttribute('aria-label', 'Remember this message');
    rememberBtn.onclick = (ev) => {
      ev.stopPropagation();
      rememberLaylaBubble(bubble, rememberBtn);
    };
    label.appendChild(rememberBtn);
  }
  div.appendChild(label);
  div.appendChild(bubble);
  if (Array.isArray(uxStates) && uxStates.length > 0) {
    const badges = document.createElement('div');
    badges.className = 'ux-state-badges';
    uxStates.forEach(s => {
      const b = document.createElement('span');
      b.className = 'ux-state-badge';
      b.textContent = UX_STATE_LABELS[s] || s;
      badges.appendChild(b);
    });
    div.appendChild(badges);
  }
  if (Array.isArray(memoryInfluenced) && memoryInfluenced.length > 0) {
    const mem = document.createElement('div');
    mem.className = 'memory-attribution';
    mem.textContent = 'Used memory: ' + (memoryInfluenced.includes('learnings') && memoryInfluenced.includes('semantic_recall') ? 'learnings & recall' : memoryInfluenced.includes('learnings') ? 'learnings' : 'recall');
    div.appendChild(mem);
  }
  if (steps && steps.length > 0) {
    const trace = document.createElement('details');
    trace.className = 'tool-trace';
    trace.innerHTML = '<summary>What she did (' + steps.length + ')</summary>';
    const pre = document.createElement('div');
    pre.className = 'tool-trace-content';
    pre.textContent = steps.map(s => {
      const act = (s && (s.action || s.tool)) ? String(s.action || s.tool) : '?';
      const r = (s && s.result != null) ? s.result : null;
      try {
        if (r && typeof r === 'object' && !Array.isArray(r)) {
          const ok = (typeof r.ok === 'boolean') ? (r.ok ? 'ok' : 'fail') : '';
          const msg = (r.message || r.error || r.reason || r.status || '');
          const m = (typeof msg === 'string') ? msg : String(msg || '');
          const tail = m ? (' — ' + m.replace(/\s+/g, ' ').trim().slice(0, 180)) : '';
          return act + (ok ? (' [' + ok + ']') : '') + tail;
        }
        const txt = (typeof r === 'string') ? r : JSON.stringify(r);
        return act + ': ' + String(txt || '').slice(0, 200);
      } catch (_) {
        return act + ': [unserializable]';
      }
    }).join('\n');
    trace.appendChild(pre);
    div.appendChild(trace);
  }
  if (deliberated) {
    const d = document.createElement('details');
    d.className = 'tool-trace';
    d.style.borderLeft = '2px solid var(--violet,#8844cc)';
    d.innerHTML = '<summary style="color:var(--violet,#8844cc);font-size:0.68rem">✦ She deliberated</summary><div class="think-bubble">She weighed this with her inner voices before answering.</div>';
    div.appendChild(d);
  }
  _renderReasoningTreeSummary(div, reasoningTreeSummary);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function addSeparator() {
  const chat = document.getElementById('chat');
  if (!chat) return;
  const sep = document.createElement('div');
  sep.className = 'separator';
  sep.textContent = '✦';
  chat.appendChild(sep);
}

function getMissionDepth() {
  const r = document.querySelector('input[name="mission-depth"]:checked');
  return (r && r.value) ? r.value : 'deep';
}

const _LEGACY_PANEL_TO_RTA = {
  approvals: ['prefs'],
  health: ['status'],
  models: ['workspace', 'models'],
  knowledge: ['workspace', 'knowledge'],
  plugins: ['workspace', 'plugins'],
  study: ['workspace', 'study'],
  memory: ['workspace', 'memory'],
  research: ['research'],
};

/* Panel DOM is handled in bootstrap (window.showMainPanel). Main script only registers data refresh hooks. */
window.__laylaRefreshAfterShowMainPanel = function (main) {
  if (main === 'status') {
    refreshPlatformHealth();
    refreshVersionInfo();
    refreshRuntimeOptions();
  }
  if (main === 'prefs') {
    if (typeof refreshContentPolicyToggles === 'function') refreshContentPolicyToggles();
    try { refreshApprovals(); } catch (_) {}
    try { loadProjectsIntoSelect(); } catch (_) {}
  }
  if (main === 'workspace') {
    /* Subtab refresh only ran on subtab click; opening Workspace left default "Models" stuck on "Loading…" */
    var wsRoot = document.querySelector('#layla-right-panel .rcp-page[data-rcp="workspace"]');
    var subEl = wsRoot && wsRoot.querySelector('.rcp-subtab.active');
    var sub = (subEl && subEl.getAttribute('data-rcp-sub')) || 'models';
    if (typeof window.__laylaRefreshAfterWorkspaceSubtab === 'function') {
      window.__laylaRefreshAfterWorkspaceSubtab(sub);
    }
  }
  if (main === 'research') {
    refreshMissionStatus().then(function () {
      const t = document.querySelector('#research-mission-panel .tab-btn.active');
      if (t) showResearchTab(t.getAttribute('data-tab'));
    });
  }
};
window.__laylaRefreshAfterWorkspaceSubtab = function (sub) {
  const refreshers = {
    models: refreshPlatformModels,
    knowledge: refreshPlatformKnowledge,
    study: function () { refreshStudyPlans(); loadStudyPresetsAndSuggestions(); try { refreshLaylaPlansPanel(); } catch (_) {} },
    memory: function () {
      if (typeof refreshFileCheckpointsPanel === 'function') refreshFileCheckpointsPanel();
    },
    plugins: function () {
      refreshPlatformPlugins();
      try { if (typeof refreshRelationshipCodex === 'function') refreshRelationshipCodex(); } catch (_) {}
      try { refreshSkillsList(); } catch (_) {}
    },
  };
  const fn = refreshers[sub];
  if (typeof fn === 'function') fn();
};

// ── Workspace → Library refreshers (minimal, no frameworks) ─────────────────
async function refreshPlatformModels() {
  const box = document.getElementById('platform-models');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/platform/models');
    const d = await r.json();
    const active = (d && d.active) ? String(d.active) : '';
    const models = Array.isArray(d && d.models) ? d.models : [];
    box.innerHTML =
      '<div><strong>Active</strong>: ' + escapeHtml(active || '—') + '</div>' +
      '<div style="margin-top:6px"><strong>Available</strong>: ' + escapeHtml(models.slice(0, 10).join(', ') || '—') + '</div>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load models</span>';
  }
}

async function refreshPlatformKnowledge() {
  const box = document.getElementById('platform-knowledge');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/platform/knowledge');
    const d = await r.json();
    const learnings = Array.isArray(d && d.learnings) ? d.learnings : [];
    const summaries = Array.isArray(d && d.summaries) ? d.summaries : [];
    box.innerHTML =
      '<div><strong>Recent learnings</strong>:</div>' +
      '<div style="margin-top:4px;color:var(--text-dim)">' + escapeHtml(learnings.map(x => x.content || '').slice(0, 5).join(' · ') || '—') + '</div>' +
      '<div style="margin-top:10px"><strong>Conversation summaries</strong>:</div>' +
      '<div style="margin-top:4px;color:var(--text-dim)">' + escapeHtml(summaries.map(x => x.summary || '').slice(0, 3).join(' · ') || '—') + '</div>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load knowledge</span>';
  }
}

async function refreshPlatformPlugins() {
  const box = document.getElementById('platform-plugins');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/platform/plugins');
    const d = await r.json();
    box.innerHTML =
      '<div><strong>Skills</strong>: ' + escapeHtml(String((d && d.skills_added) || 0)) + '</div>' +
      '<div><strong>Tools</strong>: ' + escapeHtml(String((d && d.tools_added) || 0)) + '</div>' +
      '<div><strong>Capabilities</strong>: ' + escapeHtml(String((d && d.capabilities_added) || 0)) + '</div>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load plugins</span>';
  }
}

async function refreshPlatformProjects() {
  const box = document.getElementById('platform-projects');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  let ctx = null;
  try {
    const r = await fetch('/platform/projects');
    ctx = await r.json();
  } catch (_) { ctx = null; }

  let preset = null;
  const pid = (typeof localStorage !== 'undefined' ? (localStorage.getItem('layla_active_project_id') || '') : '').trim();
  if (pid) {
    try {
      const r2 = await fetch('/projects/' + encodeURIComponent(pid));
      const d2 = await r2.json();
      if (d2 && d2.ok && d2.project) preset = d2.project;
    } catch (_) {}
  }

  const html = [];
  html.push('<div class="panel-title">Project context</div>');
  if (ctx && (ctx.project_name || ctx.goals || ctx.lifecycle_stage || ctx.progress || ctx.blockers)) {
    html.push('<div><strong>Name</strong>: ' + escapeHtml(String(ctx.project_name || '—')) + '</div>');
    html.push('<div><strong>Stage</strong>: ' + escapeHtml(String(ctx.lifecycle_stage || '—')) + '</div>');
    html.push('<div style="margin-top:6px"><strong>Goals</strong>: <span style="color:var(--text-dim)">' + escapeHtml(String(ctx.goals || '')) + '</span></div>');
    html.push('<div style="margin-top:6px"><strong>Progress</strong>: <span style="color:var(--text-dim)">' + escapeHtml(String(ctx.progress || '')) + '</span></div>');
    html.push('<div style="margin-top:6px"><strong>Blockers</strong>: <span style="color:var(--text-dim)">' + escapeHtml(String(ctx.blockers || '')) + '</span></div>');
  } else {
    html.push('<div style="color:var(--text-dim)">No project context set yet.</div>');
  }

  html.push('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:10px 0">');
  html.push('<div><strong>Active preset</strong>: ' + escapeHtml(preset ? (preset.name || preset.id || '—') : (pid || '—')) + '</div>');
  if (preset) {
    html.push('<div style="color:var(--text-dim);margin-top:4px">WS: ' + escapeHtml(String(preset.workspace_root || '')) + '</div>');
    html.push('<div style="color:var(--text-dim)">Aspect default: ' + escapeHtml(String(preset.aspect_default || '')) + '</div>');
  } else {
    html.push('<div style="color:var(--text-dim);margin-top:4px">Select a preset in Prefs → Project preset.</div>');
  }

  // Minimal editor for project_context (uses existing POST /project_context)
  html.push('<div style="margin-top:10px"><strong>Edit project context</strong></div>');
  html.push('<div style="display:flex;flex-direction:column;gap:6px;margin-top:6px">');
  html.push('<input id="pc_name" placeholder="Project name" value="' + escapeHtml(String((ctx && ctx.project_name) || '')) + '" />');
  html.push('<input id="pc_stage" placeholder="Lifecycle stage (idea/planning/prototype/iteration/execution/reflection)" value="' + escapeHtml(String((ctx && ctx.lifecycle_stage) || '')) + '" />');
  html.push('<textarea id="pc_goals" placeholder="Goals" style="min-height:60px">' + escapeHtml(String((ctx && ctx.goals) || '')) + '</textarea>');
  html.push('<textarea id="pc_progress" placeholder="Progress" style="min-height:50px">' + escapeHtml(String((ctx && ctx.progress) || '')) + '</textarea>');
  html.push('<textarea id="pc_blockers" placeholder="Blockers" style="min-height:50px">' + escapeHtml(String((ctx && ctx.blockers) || '')) + '</textarea>');
  html.push('<button type="button" class="tab-btn" id="pc_save_btn" style="margin-top:4px">Save</button>');
  html.push('<span id="pc_save_msg" style="color:var(--text-dim);font-size:0.7rem"></span>');
  html.push('</div>');

  box.innerHTML = html.join('');
  try {
    const btn = document.getElementById('pc_save_btn');
    if (btn) btn.onclick = async function() {
      const body = {
        project_name: (document.getElementById('pc_name')?.value || '').trim(),
        lifecycle_stage: (document.getElementById('pc_stage')?.value || '').trim(),
        goals: (document.getElementById('pc_goals')?.value || '').trim(),
        progress: (document.getElementById('pc_progress')?.value || '').trim(),
        blockers: (document.getElementById('pc_blockers')?.value || '').trim(),
      };
      const msgEl = document.getElementById('pc_save_msg');
      if (msgEl) msgEl.textContent = 'Saving…';
      try {
        const r3 = await fetch('/project_context', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const d3 = await r3.json().catch(() => ({}));
        if (msgEl) msgEl.textContent = (d3 && d3.ok) ? 'Saved' : ('Save failed');
        try { updateContextChip(); } catch (_) {}
      } catch (_) {
        if (msgEl) msgEl.textContent = 'Save failed';
      }
    };
  } catch (_) {}
}

async function refreshPlatformTimeline() {
  const box = document.getElementById('platform-timeline');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/platform/knowledge');
    const d = await r.json();
    const tl = Array.isArray(d && d.timeline) ? d.timeline : [];
    box.innerHTML = tl.length
      ? tl.slice(0, 8).map(t => '<div style=\"margin:4px 0\"><span style=\"color:var(--text-dim)\">' + escapeHtml(String(t.event_type || '')) + '</span> ' + escapeHtml(String(t.content || '')) + '</div>').join('')
      : '<span style=\"color:var(--text-dim)\">No timeline yet.</span>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load timeline</span>';
  }
}

window.refreshPlatformModels = refreshPlatformModels;
window.refreshPlatformKnowledge = refreshPlatformKnowledge;
window.refreshPlatformPlugins = refreshPlatformPlugins;
window.refreshPlatformProjects = refreshPlatformProjects;
window.refreshPlatformTimeline = refreshPlatformTimeline;

/** Back-compat for shortcuts and old links: maps old tab id → new UI. */
function showPanelTab(tab) {
  const m = _LEGACY_PANEL_TO_RTA[tab];
  if (m) {
    if (m[1]) window.showWorkspaceSubtab(m[1]);
    else window.showMainPanel(m[0]);
    return;
  }
  window.showMainPanel('prefs');
}
window.showPanelTab = showPanelTab;

function focusResearchPanel() {
  window.showMainPanel('research');
  const panel = document.getElementById('research-mission-panel');
  if (panel) {
    panel.scrollIntoView({ behavior: 'smooth' });
    refreshMissionStatus().then(function() { showResearchTab('summary'); });
  }
}

function toggleSendButton() {
  const input = document.getElementById('msg-input');
  const btn = document.getElementById('send-btn');
  if (input && btn) {
    // Always leave button clickable so Send works even if input listener misses; send() no-ops when empty
    btn.disabled = false;
    btn.classList.toggle('send-empty', !(input.value && input.value.trim()));
  }
}

function laylaSyncChatChromeFromFSM(state) {
  try {
    const st = String(state || (window.laylaChatFSM && window.laylaChatFSM.getState && window.laylaChatFSM.getState()) || '');
    const canSend = !(window.laylaChatFSM && window.laylaChatFSM.canSend) ? true : !!window.laylaChatFSM.canSend();
    const inFlight = st === 'sending' || st === 'streaming';
    setCancelSendVisible(!!inFlight);
    toggleSendButton();
    if (!canSend && st !== 'sending' && st !== 'streaming') {
      window._laylaSendBusy = false;
    }
  } catch (_) {}
}
window.laylaSyncChatChromeFromFSM = laylaSyncChatChromeFromFSM;
window.laylaOnChatState = function (st) {
  laylaSyncChatChromeFromFSM(st);
  try {
    if (typeof localStorage !== 'undefined' && localStorage.getItem('layla_debug_fsm') === '1') {
      try { sessionStorage.setItem('layla_chat_fsm_state', String(st || '')); } catch (_) {}
    }
  } catch (_) {}
};

// ── Aspect registry for @mention ────────────────────────────────────────────
const ASPECTS = [
  { id: 'morrigan', sym: '⚔', name: 'Morrigan', desc: 'Code, debug, architecture — the blade' },
  { id: 'nyx',      sym: '✦', name: 'Nyx',      desc: 'Research, depth, synthesis' },
  { id: 'echo',     sym: '◎', name: 'Echo',     desc: 'Reflection, patterns, memory' },
  { id: 'eris',     sym: '⚡', name: 'Eris',     desc: 'Creative chaos, banter, lateral leaps' },
  { id: 'cassandra',sym: '⌖', name: 'Cassandra',desc: 'Unfiltered oracle — sees it first' },
  { id: 'lilith',   sym: '⊛', name: 'Lilith',   desc: 'Sovereign will, ethics, full honesty' },
];

function facetMetaFromNameOrId(aspectNameOrId) {
  if (!aspectNameOrId) return null;
  const s = String(aspectNameOrId).trim().toLowerCase();
  return ASPECTS.find(a => a.id === s || a.name.toLowerCase() === s) || null;
}

/** Label row HTML: Layla + facet chip (for typing / stream bootstrap). */
function formatLaylaLabelHtml(aspectId) {
  const aid = String(aspectId || 'morrigan').toLowerCase();
  const a = ASPECTS.find(x => x.id === aid) || ASPECTS[0];
  const sym = String(a.sym || '').replace(/</g, '&lt;');
  const name = String(a.name || '').replace(/</g, '&lt;');
  return '<span class="msg-brand">Layla</span><span class="msg-facet-chip" title="Facet (voice)">' + sym + ' ' + name + '</span>';
}

// ── Shared “Layla is working” row: one implementation for send(), sendResearch(), etc. ──
let _laylaTypingMetaTimer = null;
let _laylaTypingStartedAt = 0;
let _laylaTypingPhaseTimers = [];

function laylaClearTypingPhases() {
  _laylaTypingPhaseTimers.forEach((tid) => { try { clearTimeout(tid); } catch (_) {} });
  _laylaTypingPhaseTimers = [];
}

/** Client-side phases when the server sends no ux_state (non-stream JSON wait). */
function laylaStartNonStreamTypingPhases() {
  laylaClearTypingPhases();
  [
    { delay: 1200, key: 'thinking' },
    { delay: 8000, key: 'still_working' },
    { delay: 25000, key: 'preparing_reply' },
  ].forEach(({ delay, key }) => {
    _laylaTypingPhaseTimers.push(setTimeout(() => {
      if (document.getElementById('typing-wrap')) laylaUpdateTypingUx(key);
    }, delay));
  });
}

function laylaUpdateTypingUx(uxKey) {
  const wrap = document.getElementById('typing-wrap');
  if (!wrap) return;
  const labelText = UX_STATE_LABELS[uxKey] || uxKey;
  let statusEl = wrap.querySelector('.tool-status-label');
  if (!statusEl) {
    statusEl = document.createElement('div');
    statusEl.className = 'tool-status-label';
    wrap.querySelector('.msg-bubble')?.appendChild(statusEl);
  }
  statusEl.textContent = labelText;
  let metaEl = wrap.querySelector('.memory-attribution');
  if (!metaEl) {
    metaEl = document.createElement('div');
    metaEl.className = 'memory-attribution';
    wrap.querySelector('.msg-bubble')?.appendChild(metaEl);
  }
  if (!_laylaTypingStartedAt) _laylaTypingStartedAt = Date.now();
  const secs = Math.max(0, Math.floor((Date.now() - _laylaTypingStartedAt) / 1000));
  metaEl.textContent = 'Status: ' + labelText + ' | elapsed: ' + secs + 's';
  try {
    if (window.LaylaUI && typeof window.LaylaUI.applyToTypingWrap === 'function')
      window.LaylaUI.applyToTypingWrap(wrap, uxKey);
  } catch (_) {}
}

function laylaRemoveTypingIndicator() {
  const w = document.getElementById('typing-wrap');
  if (w) w.remove();
  if (_laylaTypingMetaTimer) {
    clearInterval(_laylaTypingMetaTimer);
    _laylaTypingMetaTimer = null;
  }
  laylaClearTypingPhases();
  _laylaTypingStartedAt = 0;
  try {
    if (window.LaylaUI && typeof window.LaylaUI.clearBodyPhase === 'function') window.LaylaUI.clearBodyPhase();
  } catch (_) {}
}

function laylaShowTypingIndicator(aspectId, initialUxKey) {
  hideEmpty();
  const chatEl = document.getElementById('chat');
  if (!chatEl) return;
  const key = initialUxKey || 'connecting';
  const existing = document.getElementById('typing-wrap');
  if (existing) {
    laylaUpdateTypingUx(key);
    return;
  }
  const w = document.createElement('div');
  w.className = 'msg msg-layla';
  w.id = 'typing-wrap';
  _laylaTypingStartedAt = Date.now();
  const labelText = UX_STATE_LABELS[key] || key;
  w.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(aspectId) + '</div><div class="msg-bubble typing-indicator"><div class="typing-dots"><span></span><span></span><span></span></div><div class="tool-status-label">' + labelText + '</div><div class="memory-attribution">Status: ' + labelText + ' | elapsed: 0s</div></div>';
  chatEl.appendChild(w);
  if (_laylaTypingMetaTimer) clearInterval(_laylaTypingMetaTimer);
  _laylaTypingMetaTimer = setInterval(() => {
    const active = document.getElementById('typing-wrap');
    if (!active) return;
    const metaEl = active.querySelector('.memory-attribution');
    const status = (active.querySelector('.tool-status-label') && active.querySelector('.tool-status-label').textContent) || 'Thinking';
    if (metaEl) {
      const secs = Math.max(0, Math.floor((Date.now() - _laylaTypingStartedAt) / 1000));
      metaEl.textContent = 'Status: ' + status + ' | elapsed: ' + secs + 's';
    }
  }, 500);
  try {
    if (window.LaylaUI && typeof window.LaylaUI.applyToTypingWrap === 'function')
      window.LaylaUI.applyToTypingWrap(w, key);
  } catch (_) {}
  chatEl.scrollTop = chatEl.scrollHeight;
}

let _mentionActive = false;   // dropdown is open
window._mentionActive = false; // for listeners that run in finally (may run before this line)
let _mentionIdx = 0;          // selected item index
let _mentionAspectOverride = null; // one-shot aspect for next send
let _aspectLocked = false;    // lock prevents auto-route

// ── Aspect lock ──────────────────────────────────────────────────────────────
function toggleAspectLock() {
  _aspectLocked = !_aspectLocked;
  const btn = document.getElementById('aspect-lock-btn');
  if (btn) {
    btn.textContent = _aspectLocked ? '🔒' : '🔓';
    btn.classList.toggle('locked', _aspectLocked);
    btn.title = _aspectLocked
      ? `Locked to ${currentAspect.toUpperCase()} — click to unlock`
      : 'Lock this aspect (prevent auto-routing)';
  }
}

// ── Mention dropdown ─────────────────────────────────────────────────────────
function _getMentionQuery(val) {
  // Returns the @word being typed if cursor is in it, else null
  const m = val.match(/(?:^|\s)@(\w*)$/);
  return m ? m[1].toLowerCase() : null;
}

function _showMentionDropdown(query) {
  const dd = document.getElementById('mention-dropdown');
  if (!dd) return;
  const filtered = query === ''
    ? ASPECTS
    : ASPECTS.filter(a => a.id.startsWith(query) || a.name.toLowerCase().startsWith(query));
  if (!filtered.length) { _hideMentionDropdown(); return; }
  _mentionActive = true;
  window._mentionActive = true;
  _mentionIdx = 0;
  dd.innerHTML = filtered.map((a, i) =>
    `<div class="mention-item${i === 0 ? ' active' : ''}" data-id="${a.id}" onmousedown="event.preventDefault();_pickMention('${a.id}')">
      <span class="mention-sym">${a.sym}</span>
      <span class="mention-name">${a.name}</span>
      <span class="mention-desc">${a.desc}</span>
    </div>`
  ).join('');
  dd.classList.add('open');
  dd._filtered = filtered;
}

function _hideMentionDropdown() {
  const dd = document.getElementById('mention-dropdown');
  if (dd) { dd.classList.remove('open'); dd.innerHTML = ''; }
  _mentionActive = false;
  window._mentionActive = false;
  _mentionIdx = 0;
}

function _moveMentionDropdown(dir) {
  const dd = document.getElementById('mention-dropdown');
  if (!dd || !_mentionActive) return;
  const items = dd.querySelectorAll('.mention-item');
  if (!items.length) return;
  items[_mentionIdx]?.classList.remove('active');
  _mentionIdx = (_mentionIdx + dir + items.length) % items.length;
  items[_mentionIdx]?.classList.add('active');
  items[_mentionIdx]?.scrollIntoView({ block: 'nearest' });
}

function _pickMention(aspectId) {
  const input = document.getElementById('msg-input');
  if (!input) return;
  // Replace the trailing @word with @aspectId + space
  input.value = input.value.replace(/(?:^|\s)@\w*$/, m => {
    const prefix = m.startsWith('@') ? '' : m[0];
    return prefix + '@' + aspectId + ' ';
  });
  _hideMentionDropdown();
  input.focus();
  toggleSendButton();
}

function onInputChange(e) {
  toggleSendButton();
  const val = e.target.value;
  _checkUrlInInput(val);
  const query = _getMentionQuery(val);
  if (query !== null) {
    _showMentionDropdown(query);
  } else {
    _hideMentionDropdown();
  }
}

function _isEnterKey(e) {
  return e.key === 'Enter' || e.keyCode === 13;
}

function onInputKeydown(e) {
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'k') { e.preventDefault(); const inp = document.getElementById('msg-input'); if (inp) { inp.value = ''; toggleSendButton(); } return; }
    if (e.key === 'r') { e.preventDefault(); retryLastMessage(); return; }
    if (e.key === '/') { e.preventDefault(); showPanelTab('help'); return; }
    if (e.key === 'f') { e.preventDefault(); openChatSearch(); return; }
  }
  if (!_mentionActive && e.key === 'ArrowUp' && !e.shiftKey) {
    const inp = document.getElementById('msg-input');
    if (inp && (inp.selectionStart || 0) === 0) {
      e.preventDefault();
      _ensurePromptHistory().then(() => {
        if (!_promptHistoryList || !_promptHistoryList.length) return;
        _promptHistoryIdx = _promptHistoryIdx < 0 ? 0 : Math.min(_promptHistoryList.length - 1, _promptHistoryIdx + 1);
        inp.value = _promptHistoryList[_promptHistoryIdx] || '';
        toggleSendButton();
      });
      return;
    }
  }
  if (!_mentionActive && e.key === 'ArrowDown' && !e.shiftKey) {
    const inp = document.getElementById('msg-input');
    if (inp && _promptHistoryIdx >= 0 && (inp.selectionStart || 0) === (inp.value || '').length) {
      e.preventDefault();
      _promptHistoryIdx--;
      if (_promptHistoryIdx < 0) {
        inp.value = '';
        _promptHistoryIdx = -1;
        toggleSendButton();
        return;
      }
      inp.value = _promptHistoryList[_promptHistoryIdx] || '';
      toggleSendButton();
      return;
    }
  }
  if (_mentionActive) {
    if (e.key === 'ArrowDown') { e.preventDefault(); _moveMentionDropdown(1); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); _moveMentionDropdown(-1); return; }
    if (e.key === 'Tab' || _isEnterKey(e)) {
      const dd = document.getElementById('mention-dropdown');
      if (dd && _mentionActive) {
        e.preventDefault();
        const items = dd.querySelectorAll('.mention-item');
        const id = items[_mentionIdx]?.dataset?.id;
        if (id) _pickMention(id);
        return;
      }
    }
    if (e.key === 'Escape') { _hideMentionDropdown(); return; }
  }
  // Enter-to-send is handled solely by document keydown (bootstrap); do not duplicate here.
}

// ── URL chip, attachments, theme, sidebar, chat export/search (index.html onclick) ──
var _laylaPendingUrl = null;
function _checkUrlInInput(val) {
  var chip = document.getElementById('url-detect-chip');
  if (!chip) return;
  var s = String(val || '');
  var m = s.match(/https?:\/\/[^\s<>"']{4,}/i);
  if (m) {
    _laylaPendingUrl = m[0];
    try {
      var u = new URL(m[0]);
      var d = document.getElementById('url-chip-domain');
      if (d) d.textContent = u.hostname;
    } catch (_) {}
    chip.style.display = 'flex';
  } else {
    _laylaPendingUrl = null;
    chip.style.display = 'none';
  }
}
function dismissUrlChip() {
  var chip = document.getElementById('url-detect-chip');
  if (chip) chip.style.display = 'none';
  _laylaPendingUrl = null;
}
function acceptUrlFetch() {
  if (!_laylaPendingUrl) {
    if (typeof showToast === 'function') showToast('No URL detected in the input');
    return;
  }
  var input = document.getElementById('msg-input');
  if (input) {
    var pre = String(input.value || '').replace(/https?:\/\/[^\s<>"']+/i, '').trim();
    input.value = (pre ? pre + '\n\n' : '') + 'Fetch and summarize this URL:\n' + _laylaPendingUrl;
    try { toggleSendButton(); } catch (_) {}
  }
  dismissUrlChip();
  if (typeof showToast === 'function') showToast('URL added to message — press Send');
}

function attachFile(inp) {
  var f = inp && inp.files && inp.files[0];
  if (!f) return;
  var r = new FileReader();
  r.onload = function () {
    var text = String(r.result || '').slice(0, 120000);
    var mi = document.getElementById('msg-input');
    if (mi) {
      mi.value = (mi.value ? mi.value + '\n\n' : '') + '--- file: ' + f.name + ' ---\n' + text;
      try { toggleSendButton(); } catch (_) {}
    }
    if (typeof showToast === 'function') showToast('Attached ' + f.name);
  };
  r.readAsText(f);
  inp.value = '';
}

function handleFileDrop(ev) {
  try { ev.preventDefault(); } catch (_) {}
  var area = document.getElementById('input-area-drop');
  if (area) area.style.borderColor = '';
  var fl = ev.dataTransfer && ev.dataTransfer.files;
  if (!fl || !fl.length) return;
  var f = fl[0];
  var r = new FileReader();
  r.onload = function () {
    var text = String(r.result || '').slice(0, 120000);
    var mi = document.getElementById('msg-input');
    if (mi) {
      mi.value = (mi.value ? mi.value + '\n\n' : '') + '--- file: ' + f.name + ' ---\n' + text;
      try { toggleSendButton(); } catch (_) {}
    }
    if (typeof showToast === 'function') showToast('Dropped ' + f.name);
  };
  r.readAsText(f);
}

function toggleTheme() {
  document.body.classList.toggle('theme-light');
  try {
    localStorage.setItem('layla_theme', document.body.classList.contains('theme-light') ? 'light' : 'dark');
  } catch (_) {}
}

function toggleSidebarCompact() {
  var sb = document.querySelector('.sidebar');
  if (sb) sb.classList.toggle('compact');
}

function toggleMobileSidebar() {
  var sb = document.querySelector('.sidebar');
  if (sb) sb.classList.toggle('mobile-sidebar-hidden');
}

function exportChat() {
  var chat = document.getElementById('chat');
  if (!chat) return;
  var md = '# Layla chat export\n\n';
  chat.querySelectorAll('.msg').forEach(function (row) {
    var lab = row.querySelector('.msg-label');
    var bub = row.querySelector('.msg-bubble');
    var role = (lab && lab.textContent && lab.textContent.indexOf('You') >= 0) ? 'You' : 'Layla';
    md += '## ' + role + '\n\n' + (bub ? String(bub.innerText || '').trim() : '') + '\n\n';
  });
  try {
    var blob = new Blob([md], { type: 'text/markdown' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'layla-chat-export.md';
    a.click();
    URL.revokeObjectURL(a.href);
    if (typeof showToast === 'function') showToast('Export downloaded');
  } catch (e) {
    if (typeof showToast === 'function') showToast('Export failed');
  }
}

function clearChat() {
  if (!confirm('Clear the chat panel?')) return;
  var chat = document.getElementById('chat');
  if (chat) {
    chat.innerHTML = '<div id="chat-empty">' + renderPromptTilesAndEmptyState() + '</div>';
  }
}

function fillPrompt(prefix) {
  var inp = document.getElementById('msg-input');
  if (!inp) return;
  inp.value = String(prefix || '');
  try {
    inp.focus();
    toggleSendButton();
  } catch (_) {}
}

function openCliHelp() {
  var t = 'Open a terminal in the Layla repo and start the server (see README Quick start). UI: Settings use /settings.';
  if (typeof showToast === 'function') showToast(t);
  else try { alert(t); } catch (_) {}
}

var _laylaChatSearchMatches = [];
var _laylaChatSearchIdx = -1;
function _clearSearchHighlights() {
  document.querySelectorAll('.msg-bubble.search-hit').forEach(function (e) {
    e.classList.remove('search-hit');
  });
}
function openChatSearch() {
  var o = document.getElementById('chat-search-overlay');
  if (o) o.style.display = 'flex';
  var inp = document.getElementById('chat-search-input');
  if (inp) {
    inp.value = '';
    inp.focus();
  }
  _laylaChatSearchMatches = [];
  _laylaChatSearchIdx = -1;
  _clearSearchHighlights();
}
function closeChatSearch() {
  var o = document.getElementById('chat-search-overlay');
  if (o) o.style.display = 'none';
  _clearSearchHighlights();
}
function onChatSearchInput(q) {
  _laylaChatSearchMatches = [];
  _laylaChatSearchIdx = -1;
  _clearSearchHighlights();
  var chat = document.getElementById('chat');
  if (!chat) return;
  var Q = String(q || '').trim().toLowerCase();
  if (!Q) return;
  var els = chat.querySelectorAll('.msg-bubble');
  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    if ((el.textContent || '').toLowerCase().indexOf(Q) >= 0) _laylaChatSearchMatches.push(el);
  }
  if (_laylaChatSearchMatches.length) {
    _laylaChatSearchIdx = 0;
    var cur = _laylaChatSearchMatches[_laylaChatSearchIdx];
    if (cur) {
      cur.classList.add('search-hit');
      cur.scrollIntoView({ block: 'center' });
    }
  }
}
function chatSearchNext() {
  if (!_laylaChatSearchMatches.length) return;
  _clearSearchHighlights();
  _laylaChatSearchIdx = (_laylaChatSearchIdx + 1) % _laylaChatSearchMatches.length;
  var cur = _laylaChatSearchMatches[_laylaChatSearchIdx];
  if (cur) {
    cur.classList.add('search-hit');
    cur.scrollIntoView({ block: 'center' });
  }
}

var _laylaDiffApprovalId = '';
function closeDiffViewer() {
  var o = document.getElementById('diff-overlay');
  if (o) o.style.display = 'none';
  _laylaDiffApprovalId = '';
}
function confirmApplyFile() {
  if (!_laylaDiffApprovalId) {
    if (typeof showToast === 'function') showToast('Use Approvals panel — no preview approval id bound');
    closeDiffViewer();
    return;
  }
  fetchWithTimeout('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: _laylaDiffApprovalId }) }, 20000)
    .then(function (r) { return r.json().then(function (d) { return { r: r, d: d }; }); })
    .then(function (x) {
      if (x.r.ok && x.d && x.d.ok) {
        if (typeof showToast === 'function') showToast('Applied');
        closeDiffViewer();
        try { refreshApprovals(); } catch (_) {}
      } else if (typeof showToast === 'function') showToast((x.d && x.d.error) || 'Approve failed');
    })
    .catch(function () { if (typeof showToast === 'function') showToast('Approve failed'); });
}

function closeBatchDiffViewer() {
  var o = document.getElementById('batch-diff-overlay');
  if (o) o.style.display = 'none';
}

function confirmApplyBatch() {
  if (typeof showToast === 'function') showToast('Approve each pending item in the Approvals panel (batch id wiring is server-side)');
  closeBatchDiffViewer();
}

async function applySettingsPreset(name) {
  try {
    var r = await fetch('/settings/preset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: String(name || 'potato') }),
    });
    var d = await r.json().catch(function () { return {}; });
    if (typeof showToast === 'function') showToast(d.ok ? ('Preset applied: ' + String(name)) : String(d.error || 'failed'));
  } catch (e) {
    if (typeof showToast === 'function') showToast('Preset request failed');
  }
}

async function saveAppearanceLite() {
  var body = {
    ui_avatar_seed: (document.getElementById('ui_avatar_seed') || {}).value || '',
    ui_avatar_style: (document.getElementById('ui_avatar_style') || {}).value || '',
    chat_lite_mode: !!(document.getElementById('chat_lite_mode') && document.getElementById('chat_lite_mode').checked),
    ui_decision_trace_enabled: !!(document.getElementById('ui_decision_trace_enabled') && document.getElementById('ui_decision_trace_enabled').checked),
  };
  var msg = document.getElementById('appearance-save-msg');
  try {
    var r = await fetch('/settings/appearance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    var d = await r.json().catch(function () { return {}; });
    if (msg) msg.textContent = d.ok ? '✓ Saved' : String(d.error || 'failed');
    if (typeof showToast === 'function') showToast(d.ok ? 'Appearance saved' : 'Save failed');
  } catch (e) {
    if (msg) msg.textContent = 'failed';
    if (typeof showToast === 'function') showToast('Save failed');
  }
}

async function runKnowledgeIngest() {
  var srcEl = document.getElementById('km-source');
  var labEl = document.getElementById('km-label');
  var src = (srcEl && srcEl.value || '').trim();
  var lab = (labEl && labEl.value || '').trim();
  if (!src) {
    if (typeof showToast === 'function') showToast('Enter a source URL or path');
    return;
  }
  try {
    var r = await fetch('/knowledge/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: src, label: lab }),
    });
    var d = await r.json().catch(function () { return {}; });
    var box = document.getElementById('km-ingest-list');
    if (box) {
      try {
        box.textContent = JSON.stringify(d, null, 2).slice(0, 3000);
      } catch (_) {
        box.textContent = String(d);
      }
    }
    if (typeof showToast === 'function') showToast(d && d.ok !== false ? 'Ingest complete' : String(d.error || 'Ingest failed'));
  } catch (e) {
    if (typeof showToast === 'function') showToast('Ingest request failed');
  }
}

async function checkForUpdates() {
  var el = document.getElementById('update-status');
  if (el) el.textContent = 'Checking…';
  try {
    var r = await fetch('/version');
    var d = await r.json().catch(function () { return {}; });
    var v = d && d.version ? String(d.version) : '?';
    if (el) el.textContent = 'Server version: ' + v;
  } catch (e) {
    if (el) el.textContent = 'Could not reach /version';
  }
}

// ── Voice I/O ──────────────────────────────────────────────────────────────
let _micActive = false;
let _mediaRecorder = null;
let _audioChunks = [];
let _ttsEnabled = localStorage.getItem('layla_tts') !== 'false';
/** Default on: live progress + keepalive-friendly stall timer for long turns. */
let _streamEnabled = localStorage.getItem('layla_stream') !== 'false';
// Sync checkbox to persisted value on load
document.addEventListener('DOMContentLoaded', () => {
  const streamCb = document.getElementById('stream-toggle');
  if (streamCb) {
    streamCb.checked = _streamEnabled;
    streamCb.addEventListener('change', function () {
      _streamEnabled = !!this.checked;
      localStorage.setItem('layla_stream', _streamEnabled ? 'true' : 'false');
    });
  }
  const ttsCb = document.getElementById('tts-toggle');
  if (ttsCb) ttsCb.checked = _ttsEnabled;
  try {
    const asp = typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan';
    if (typeof window.laylaSetAspectSprite === 'function') window.laylaSetAspectSprite(asp);
  } catch (_) {}
  try { refreshMaturityCard(false); } catch (_) {}
});

async function toggleMic() {
  if (_micActive) {
    stopMic();
  } else {
    await startMic();
  }
}

async function startMic() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _audioChunks.push(e.data); };
    _mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(_audioChunks, { type: 'audio/webm' });
      await transcribeAndSend(blob);
    };
    _mediaRecorder.start();
    _micActive = true;
    const micBtn = document.getElementById('mic-btn');
    if (micBtn) {
      micBtn.textContent = '⏹';
      micBtn.classList.add('recording');
      micBtn.title = 'Click to stop recording';
    }
  } catch(e) {
    console.error('Mic access denied:', e);
    showToast('Microphone access denied');
  }
}

function stopMic() {
  if (_mediaRecorder && _micActive) {
    _mediaRecorder.stop();
    _micActive = false;
    const micBtn = document.getElementById('mic-btn');
    if (micBtn) {
      micBtn.textContent = '🎤';
      micBtn.classList.remove('recording');
      micBtn.title = 'Click to record voice';
    }
  }
}

async function transcribeAndSend(blob) {
  const micBtn = document.getElementById('mic-btn');
  if (micBtn) { micBtn.textContent = '⌛'; micBtn.classList.remove('recording'); }
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const resp = await fetch('/voice/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'audio/webm' },
      body: arrayBuffer,
    });
    const data = await resp.json();
    if (data.ok && data.text && data.text.trim()) {
      const input = document.getElementById('msg-input');
      if (input) {
        input.value = data.text.trim();
        toggleSendButton();
        // Auto-send after transcription
        send();
      }
    } else {
      showToast('Could not transcribe audio');
    }
  } catch(e) {
    console.error('Transcription error:', e);
    showToast('Transcription failed');
  } finally {
    if (micBtn) { micBtn.textContent = '🎤'; micBtn.style.color = 'var(--text-dim)'; }
  }
}

async function speakText(text) {
  if (!_ttsEnabled || !text) return;
  // Try server-side TTS (kokoro-onnx) first; fall back to browser SpeechSynthesis
  try {
    const _asp = (typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan') || 'morrigan';
    const resp = await fetch('/voice/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, aspect_id: _asp }),
    });
    if (resp.ok) {
      const arrayBuffer = await resp.arrayBuffer();
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      const source = audioCtx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioCtx.destination);
      source.start();
      return;
    }
    // 503 = kokoro-onnx not installed; fall through to browser fallback
  } catch(e) { /* network error; fall through */ }
  // Browser SpeechSynthesis fallback (always available, lower quality)
  if (typeof speechSynthesis !== 'undefined') {
    try { speakReply(text.slice(0, 500), currentAspect); } catch (_) {}
  }
}

function showToast(msg, opts) {
  const t = document.createElement('div');
  t.className = 'toast';
  if (opts && opts.html) { t.innerHTML = msg; } else { t.textContent = msg; }
  document.body.appendChild(t);
  const duration = (opts && opts.duration) || 2200;
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; setTimeout(() => t.remove(), 300); }, duration);
}

async function startResearchMission(isResume) {
  const workspacePath = (document.getElementById('workspace-path')?.value || '').trim();
  const missionDepth = getMissionDepth();
  const nextStage = document.getElementById('next-stage')?.checked || false;
  addMsg('you', (isResume ? '&#9208; Resume' : '&#9654; Start') + ' research mission: depth=' + missionDepth + (nextStage ? ', next_stage' : '') + (workspacePath ? ' · ' + workspacePath : ''));
  addSeparator();
  const chatEl = document.getElementById('chat');
  const wrap = document.createElement('div');
  wrap.className = 'msg msg-layla';
  wrap.id = 'typing-wrap';
  wrap.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan') + '</div><div class="msg-bubble typing-indicator"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
  chatEl.appendChild(wrap);
  chatEl.scrollTop = chatEl.scrollHeight;
  try {
    const res = await fetch('/research_mission', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_root: workspacePath || undefined,
        mission_depth: missionDepth,
        next_stage: nextStage,
        mission_type: 'repo_analysis',
      }),
    });
    wrap.remove();
    if (!res.ok) {
      let errMsg = 'Research mission failed: ' + res.status;
      try {
        const errBody = await res.json();
        if (errBody && (errBody.error || errBody.response || errBody.detail)) errMsg = errBody.response || errBody.error || (typeof errBody.detail === 'string' ? errBody.detail : errMsg);
      } catch (_) {}
      addMsg('layla', errMsg);
      await refreshMissionStatus();
      refreshApprovals();
      return;
    }
    const data = await res.json().catch(() => ({}));
    const resp = (data && data.response) || '(no output)';
    addMsg('layla', resp, data?.state?.aspect_name, data?.state?.steps?.some(s => s.deliberated), data?.state?.steps, data?.state?.ux_states, data?.state?.memory_influenced);
    if (data && data.mission_depth) addMsg('layla', 'Mission depth: ' + data.mission_depth + (data.stages_run?.length ? ', stages run: ' + data.stages_run.join(', ') : ''));
    if (_ttsEnabled && resp && resp !== '(no output)') { speakText(resp).catch(() => {}); }
    await refreshMissionStatus();
    const activeTab = document.querySelector('#research-mission-panel .tab-btn.active')?.getAttribute('data-tab') || 'summary';
    await showResearchTab(activeTab);
  } catch (e) {
    wrap.remove();
    addMsg('layla', 'Error: ' + e.message);
    await refreshMissionStatus();
  }
  refreshApprovals();
}

async function refreshMissionStatus() {
  const lineEl = document.getElementById('mission-status-line');
  const detailEl = document.getElementById('mission-status-detail');
  const liveEl = document.getElementById('mission-status-live');
  const warnEl = document.getElementById('mission-status-warning');
  const resumableEl = document.getElementById('mission-status-resumable');
  if (!lineEl) return;
  try {
    const res = await fetchWithTimeout('/research_mission/state', {}, 12000);
    let data = {};
    if (res.ok) try { data = await res.json(); } catch (_) {}
    const status = data.status ?? (Array.isArray(data.completed) && data.completed.length ? 'partial' : null);
    const completed = Array.isArray(data.completed) ? data.completed : [];
    const stage = data.stage ?? null;
    const lastRun = data.last_run ?? null;
    lineEl.textContent = 'Status: ' + (status || '—');
    const completedStr = completed.length ? '✔ ' + completed.join(', ') : '';
    if (detailEl) detailEl.innerHTML = (lastRun ? 'Last run: ' + escapeHtml(String(lastRun)) + '<br>' : '') + (stage ? '⏳ Current: ' + escapeHtml(String(stage)) + '<br>' : '') + (completedStr ? escapeHtml(completedStr) : '');
    if (liveEl) {
      const now = new Date();
      liveEl.textContent = 'Updated ' + now.toLocaleTimeString();
      liveEl.style.animation = status !== 'complete' ? 'mission-pulse 2s ease-in-out infinite' : 'none';
    }
    if (warnEl) warnEl.style.display = (status === 'partial' || status === 'stopped') ? 'block' : 'none';
    if (resumableEl) resumableEl.style.display = (status && status !== 'complete') ? 'block' : 'none';
  } catch (_) {
    lineEl.textContent = 'Status: —';
    if (detailEl) detailEl.textContent = '';
    if (liveEl) liveEl.textContent = 'Update failed';
    if (warnEl) warnEl.style.display = 'none';
    if (resumableEl) resumableEl.style.display = 'none';
  }
}
function escapeHtml(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

async function refreshApprovals() {
  const box = document.getElementById('approvals-list');
  if (!box) return;
  try {
    const res = await fetchWithTimeout('/pending', {}, 8000);
    let data = {};
    if (res && res.ok) {
      try { data = await res.json(); } catch (_) {}
    }
    const pending = Array.isArray(data && data.pending) ? data.pending : [];
    const todo = pending.filter(e => (e && e.status) === 'pending');
    if (!todo.length) {
      box.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">No pending approvals</span>';
      return;
    }
    const html = [];
    todo.forEach(function (e) {
      const id = String(e.id || '');
      const tool = String(e.tool || '');
      const args = e.args || {};
      const argsPreview = (() => { try { return JSON.stringify(args, null, 2); } catch (_) { return String(args); } })();
      const diffBlock = args && args.diff
        ? ('<pre style="margin:6px 0 8px;white-space:pre-wrap;word-break:break-word;font-size:0.62rem;background:var(--bg);padding:6px;border-radius:4px;border:1px solid rgba(255,255,255,0.06);max-height:140px;overflow:auto">' + escapeHtml(String(args.diff)) + '</pre>')
        : '';
      html.push(
        '<div class="approval-card" style="margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:6px;background:rgba(0,0,0,0.12)">' +
          '<div style="font-size:0.72rem"><strong>' + escapeHtml(tool || 'tool') + '</strong> <span style="color:var(--text-dim)">(' + escapeHtml(id.slice(0, 8) || 'id') + '…)</span></div>' +
          diffBlock +
          '<pre style="margin:6px 0 8px;white-space:pre-wrap;word-break:break-word;font-size:0.65rem;background:var(--code-bg);padding:6px;border-radius:4px;border:1px solid rgba(255,255,255,0.06);max-height:160px;overflow:auto">' + escapeHtml(argsPreview) + '</pre>' +
          '<label style="font-size:0.62rem;display:flex;gap:6px;align-items:center;margin:4px 0;color:var(--text-dim)"><input type="checkbox" class="grant-session-cb" /> Grant for session (same tool)</label>' +
          '<label style="font-size:0.62rem;display:block;margin:4px 0;color:var(--text-dim)">grant_pattern <input type="text" class="grant-pattern-inp" style="width:100%;padding:4px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px;font-size:0.62rem" placeholder="optional path glob" /></label>' +
          '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">' +
            '<button type="button" class="approve-btn" data-approve-id="' + escapeHtml(id) + '">Approve</button>' +
            '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--border);color:var(--text-dim)" data-deny-id="' + escapeHtml(id) + '">Deny</button>' +
          '</div>' +
        '</div>'
      );
    });
    box.innerHTML = html.join('');
    box.querySelectorAll('button[data-approve-id]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const id = btn.getAttribute('data-approve-id') || '';
        btn.disabled = true;
        try {
          const card = btn.closest('.approval-card');
          const sess = card && card.querySelector('.grant-session-cb');
          const gpi = card && card.querySelector('.grant-pattern-inp');
          const payload = { id: id };
          if (sess && sess.checked) payload.save_for_session = true;
          if (gpi && (gpi.value || '').trim()) payload.grant_pattern = (gpi.value || '').trim();
          const r = await fetchWithTimeout('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, 15000);
          let body = {};
          try { body = await r.json(); } catch (_) {}
          if (!r.ok || !body.ok) showToast((body && body.error) ? ('Approve failed: ' + body.error) : ('Approve failed: ' + r.status));
          else showToast('Approved');
        } catch (e) {
          showToast('Approve error: ' + (e && e.message || e));
        } finally {
          btn.disabled = false;
          refreshApprovals();
        }
      });
    });
    box.querySelectorAll('button[data-deny-id]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const id = btn.getAttribute('data-deny-id') || '';
        btn.disabled = true;
        try {
          const r = await fetchWithTimeout('/deny', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id }) }, 15000);
          let body = {};
          try { body = await r.json(); } catch (_) {}
          if (!r.ok || !body.ok) showToast((body && body.error) ? ('Deny failed: ' + body.error) : ('Deny failed: ' + r.status));
          else showToast('Denied');
        } catch (e) {
          showToast('Deny error: ' + (e && e.message || e));
        } finally {
          btn.disabled = false;
          refreshApprovals();
        }
      });
    });
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">Could not load approvals</span>';
  }
}

const RESEARCH_BRAIN_PATHS = { summary: 'summaries/24h_summary.md', actions: 'actions/action_queue.md', patterns: 'patterns/patterns.md', risks: 'risk/risk_model.md' };

async function showResearchTab(tab) {
  const panel = document.getElementById('research-mission-panel');
  if (panel) {
    panel.querySelectorAll('.tab-btn').forEach(b => { b.classList.remove('active'); });
    const btn = panel.querySelector('.tab-btn[data-tab="' + tab + '"]');
    if (btn) btn.classList.add('active');
  }
  const contentEl = document.getElementById('research-tab-content');
  if (!contentEl) return;
  if (tab === 'last') {
    try {
      const res = await fetchWithTimeout('/research_output/last', {}, 12000);
      const data = await res.ok ? res.json() : {};
      contentEl.textContent = data.content || '(no output yet)';
    } catch (_) { contentEl.textContent = '(failed to load)'; }
    return;
  }
  const path = RESEARCH_BRAIN_PATHS[tab];
  if (!path) { contentEl.textContent = ''; return; }
  try {
    const res = await fetchWithTimeout('/research_brain/file?path=' + encodeURIComponent(path), {}, 12000);
    const data = await res.ok ? res.json() : {};
    contentEl.textContent = data.content || '(no content yet)';
  } catch (_) { contentEl.textContent = '(failed to load)'; }
}

setInterval(refreshMissionStatus, 5000);
document.addEventListener('DOMContentLoaded', function() {
  try {
    var th = localStorage.getItem('layla_theme');
    if (th === 'light') document.body.classList.add('theme-light');
    else document.body.classList.remove('theme-light');
  } catch (_) {}
  refreshMissionStatus();
  showResearchTab('summary');
  try { refreshWorkspacePresetsDropdown(); } catch (_) {}
  toggleSendButton();
  try {
    function laylaBasenameDisplay(p) {
      if (!p) return '';
      var s = String(p).trim();
      var i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
      return i >= 0 ? s.slice(i + 1) : s;
    }
    function laylaPollHeaderDeep() {
      var el = document.getElementById('header-system-status');
      if (!el) return;
      fetch('/health?deep=true', { cache: 'no-store' }).then(function (r) {
        return r.json().then(function (d) { return { r: r, d: d }; });
      }).then(function (x) {
        if (!x.r.ok) { el.textContent = 'degraded'; return; }
        var d = x.d || {};
        var mode = (d.remote_mode ? 'remote' : 'local');
        var raw = String(d.active_model || d.model_path || d.model || d.model_filename || '').trim();
        var tail = laylaBasenameDisplay(raw);
        el.title = raw ? raw : '';
        if (tail.length > 28) tail = tail.slice(0, 28);
        el.textContent = mode + (tail ? ' · ' + tail : '');
      }).catch(function () { el.textContent = 'offline'; });
    }
    laylaPollHeaderDeep();
    setInterval(laylaPollHeaderDeep, 20000);
    var ban = document.getElementById('connection-banner');
    function laylaPingConn() {
      fetch('/health', { cache: 'no-store' }).then(function () {
        if (navigator.onLine && ban) ban.style.display = 'none';
      }).catch(function () {
        if (ban) ban.style.display = 'block';
      });
    }
    window.addEventListener('online', function () { if (ban) ban.style.display = 'none'; });
    window.addEventListener('offline', function () { if (ban) ban.style.display = 'block'; });
    setInterval(laylaPingConn, 15000);
    laylaPingConn();
  } catch (_) {}
  try {
    laylaRefreshHeaderContextRow();
    setInterval(function () { try { laylaRefreshHeaderContextRow(); } catch (_) {} }, 12000);
  } catch (_) {}
  try {
    var sw = document.getElementById('setup-workspace-path');
    if (sw) {
      sw.addEventListener('input', function () { sw.setAttribute('data-user-edited', '1'); });
    }
    var cu = document.getElementById('setup-custom-url');
    if (cu) {
      cu.addEventListener('input', _setupRefreshDownloadButton);
    }
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      var so = document.getElementById('setup-overlay');
      if (so && so.classList.contains('visible')) {
        if (typeof dismissSetupOverlay === 'function') dismissSetupOverlay(true);
        else so.classList.remove('visible');
        ev.preventDefault();
        return;
      }
      var ob = document.getElementById('onboarding-overlay');
      if (ob && ob.classList.contains('visible')) {
        if (typeof dismissOnboarding === 'function') dismissOnboarding();
        ev.preventDefault();
      }
    });
  } catch (_) {}
  if (typeof checkSetupStatus === 'function') checkSetupStatus();
});

async function sendResearch(customMessage) {
  const workspacePath = (document.getElementById('workspace-path')?.value || '').trim();
  const researchMsg = (typeof customMessage === 'string' && customMessage.trim()) ? customMessage.trim() : 'Research this repo and tell me if the implementation is optimal. Do not modify anything.';
  addMsg('you', '🔬 ' + (researchMsg.length > 120 ? researchMsg.slice(0, 120) + '…' : researchMsg) + (workspacePath ? ' (Repo: ' + workspacePath + ')' : ''));
  addSeparator();
  try {
    const rmBadge = document.getElementById('reasoning-mode-badge');
    if (rmBadge) rmBadge.textContent = '';
  } catch (_) {}

  const streamMode = document.getElementById('stream-toggle')?.checked || false;
  const payload = {
    message: researchMsg,
    repo_path: workspacePath || undefined,
    aspect_id: currentAspect,
    show_thinking: document.getElementById('show-thinking')?.checked ?? false,
    stream: streamMode,
  };

  const chatEl = document.getElementById('chat');
  const ra = typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan';

  try {
    if (streamMode) {
      const res = await fetchWithTimeout('/research', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, Math.max(laylaAgentStreamTimeoutMs(), 720000));
      if (!res.ok || !res.body) {
        let body = {};
        try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) {} } catch(_) {}
        addMsg('layla', formatAgentError(res, body));
        refreshApprovals();
        return;
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = '';
      hideEmpty();
      const div = document.createElement('div');
      div.className = 'msg msg-layla';
      div.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(ra) + '</div><div class="msg-bubble" title="Click to copy"><div class="md-content stream-md-placeholder"><div class="typing-indicator" style="min-height:36px"><div class="typing-dots"><span></span><span></span><span></span></div></div><div class="tool-status-label">' + (UX_STATE_LABELS.connecting || 'Connecting') + '</div></div></div>';
      chatEl.appendChild(div);
      const bubble = div.querySelector('.md-content');
      const streamMeta = document.createElement('div');
      streamMeta.className = 'memory-attribution';
      streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS.connecting || 'Connecting') + ' · 0s · 0 chars';
      div.appendChild(streamMeta);
      const streamStartedAt = Date.now();
      let liveStatus = 'connecting';
      laylaNotifyStreamPhase(div, 'connecting');
      const metaTimer = setInterval(() => {
        const secs = Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000));
        streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS[liveStatus] || liveStatus) + ' · ' + secs + 's · ' + (full || '').length + ' chars';
      }, 500);
      let researchStreamGotToken = false;
      let firstTokenTimer = setTimeout(() => {
        liveStatus = 'waiting_first_token';
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
        statusEl.textContent = UX_STATE_LABELS.waiting_first_token;
        laylaNotifyStreamPhase(div, liveStatus);
      }, 1200);
      const researchStallMs = laylaStalledSilenceMs();
      let stalledTimer = setTimeout(() => {
        liveStatus = 'stalled';
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
        statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
        laylaNotifyStreamPhase(div, 'stalled');
      }, researchStallMs);
      let gotDone = false;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = dec.decode(value, { stream: true });
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const obj = JSON.parse(line.slice(6));
              if (obj.pulse === true) {
                clearTimeout(stalledTimer);
                stalledTimer = setTimeout(() => {
                  liveStatus = 'stalled';
                  let statusEl = div.querySelector('.tool-status-label');
                  if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
                  statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
                  laylaNotifyStreamPhase(div, 'stalled');
                }, researchStallMs);
              }
              if (obj.error) {
                clearTimeout(firstTokenTimer);
                clearTimeout(stalledTimer);
                clearInterval(metaTimer);
                try { div.remove(); } catch (_) {}
                addMsg('layla', 'Research stream error: ' + String(obj.error));
                refreshApprovals();
                return;
              }
              if (obj.token) {
                liveStatus = 'streaming';
                laylaNotifyStreamPhase(div, 'streaming');
                if (!researchStreamGotToken) {
                  researchStreamGotToken = true;
                  clearTimeout(firstTokenTimer);
                  if (bubble && bubble.classList.contains('stream-md-placeholder')) {
                    bubble.classList.remove('stream-md-placeholder');
                    bubble.innerHTML = '';
                  }
                }
                clearTimeout(stalledTimer);
                stalledTimer = setTimeout(() => {
                  liveStatus = 'stalled';
                  let statusEl = div.querySelector('.tool-status-label');
                  if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
                  statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
                  laylaNotifyStreamPhase(div, 'stalled');
                }, researchStallMs);
                full += obj.token;
                let parsed = full;
                try { if (typeof marked !== 'undefined') parsed = sanitizeHtml(marked.parse(full)); } catch (_) {}
                bubble.innerHTML = parsed;
                bubble.querySelectorAll('pre code').forEach(el => { if (window.hljs) hljs.highlightElement(el); });
                chatEl.scrollTop = chatEl.scrollHeight;
              }
              if (obj.done) {
                clearTimeout(firstTokenTimer);
                clearTimeout(stalledTimer);
                if (obj.content != null && String(obj.content).trim() !== '') full = String(obj.content).trim();
                try {
                  const rmBadge = document.getElementById('reasoning-mode-badge');
                  if (rmBadge && obj.reasoning_mode) rmBadge.textContent = 'Thinking: ' + obj.reasoning_mode;
                } catch (_) {}
                gotDone = true;
                break;
              }
            } catch (_) {}
          }
        }
        if (gotDone) break;
      }
      clearInterval(metaTimer);
      clearTimeout(firstTokenTimer);
      clearTimeout(stalledTimer);
      streamMeta.textContent = 'Done · ' + Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000)) + 's · ' + (full || '').length + ' chars';
      full = cleanLaylaText(full);
      let parsed = full;
      try { if (typeof marked !== 'undefined') parsed = sanitizeHtml(marked.parse(full)); } catch (_) {}
      bubble.innerHTML = parsed;
      try {
        div.querySelector('.msg-bubble')?.removeAttribute('data-layla-phase');
        if (window.LaylaUI && typeof window.LaylaUI.clearBodyPhase === 'function') window.LaylaUI.clearBodyPhase();
      } catch (_) {}
      bubble.querySelectorAll('pre code').forEach(el => { if (window.hljs) hljs.highlightElement(el); });
      chatEl.scrollTop = chatEl.scrollHeight;
      if (_ttsEnabled && full) { speakText(full).catch(() => {}); }
      refreshApprovals();
      return;
    }
    laylaShowTypingIndicator(ra, 'connecting');
    laylaStartNonStreamTypingPhases();
    const res = await fetchWithTimeout('/research', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, Math.max(laylaAgentStreamTimeoutMs(), 720000));
    laylaRemoveTypingIndicator();
    if (!res.ok) { let body = {}; try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) {} } catch(_) {} addMsg('layla', formatAgentError(res, body)); refreshApprovals(); return; }
    const data = await res.json();
    try {
      const rmBadge = document.getElementById('reasoning-mode-badge');
      const rm = data.reasoning_mode || data.state?.reasoning_mode;
      if (rmBadge) rmBadge.textContent = rm ? ('Thinking: ' + rm) : '';
    } catch (_) {}
    addMsg('layla', data.response || '', data.aspect_name, data.state?.steps?.some(s => s.deliberated), data.state?.steps, data.ux_states, data.memory_influenced);
    if (_ttsEnabled && (data.response || '').trim()) { speakText(data.response).catch(() => {}); }
  } catch (e) {
    laylaRemoveTypingIndicator();
    addMsg('layla', ((e && (e.message||'')).toLowerCase().includes('fetch') || (e && (e.message||'')).toLowerCase().includes('network') || (e && (e.message||'')).toLowerCase().includes('abort')) ? formatAgentError(null, null) : ('Error: ' + (e && e.message || 'unknown')));
  }
  refreshApprovals();
}

let _lastDisplayMsg = null;
let _activeAgentAbort = null;

function cancelActiveSend() {
  try {
    if (_activeAgentAbort) _activeAgentAbort.abort();
  } catch (_) {}
  try { laylaHeaderProgressStop(); } catch (_) {}
}

function setCancelSendVisible(visible) {
  const b = document.getElementById('cancel-send-btn');
  if (b) b.style.display = visible ? 'inline-block' : 'none';
}

function laylaRefreshHeaderContextRow() {
  try {
    var cid = typeof currentConversationId !== 'undefined' ? String(currentConversationId || '').trim() : '';
    var el = document.getElementById('header-conv-id');
    if (el) {
      el.textContent = cid ? ('conv ' + cid.slice(0, 8)) : 'new chat';
      el.title = cid ? ('conversation_id: ' + cid) : 'No conversation id yet';
    }
  } catch (_) {}
  fetch('/session/stats', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
    var t = document.getElementById('header-session-tokens');
    if (!t || !d || d.error) return;
    var tt = d.total_tokens != null ? Number(d.total_tokens) : 0;
    var tc = d.tool_calls != null ? Number(d.tool_calls) : 0;
    var elapsed = d.elapsed_seconds != null ? Number(d.elapsed_seconds) : 0;
    t.textContent = '\u03a3 ' + tt + ' tok \u00b7 ' + tc + ' tools \u00b7 ' + elapsed + 's';
    t.title = 'GET /session/stats — prompt:' + (d.prompt_tokens != null ? d.prompt_tokens : '?') + ' completion:' + (d.completion_tokens != null ? d.completion_tokens : '?');
  }).catch(function () {
    var t = document.getElementById('header-session-tokens');
    if (t) t.textContent = '';
  });
}
window.laylaRefreshHeaderContextRow = laylaRefreshHeaderContextRow;

function ensureLaylaConversationId() {
  if (typeof currentConversationId === 'string' && String(currentConversationId).trim()) {
    try { laylaRefreshHeaderContextRow(); } catch (_) {}
    return String(currentConversationId).trim();
  }
  let id = '';
  try {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) id = crypto.randomUUID();
    else id = 'lc-' + Date.now() + '-' + Math.random().toString(36).slice(2, 9);
  } catch (_) {
    id = 'lc-' + Date.now();
  }
  currentConversationId = id;
  try { localStorage.setItem('layla_current_conversation_id', id); } catch (_) {}
  try { if (typeof updateContextChip === 'function') updateContextChip(); } catch (_) {}
  try { laylaRefreshHeaderContextRow(); } catch (_) {}
  return id;
}

function laylaEnsureReasoningChain(msgLaylaDiv) {
  const msgBub = msgLaylaDiv.querySelector('.msg-bubble');
  if (!msgBub) return null;
  let chain = msgBub.querySelector('.layla-reasoning-chain');
  if (!chain) {
    chain = document.createElement('details');
    chain.className = 'layla-reasoning-chain tool-trace';
    chain.open = true;
    chain.innerHTML = '<summary class="layla-reasoning-summary">Reasoning</summary><div class="layla-reasoning-steps"></div>';
    const md = msgBub.querySelector('.md-content');
    if (md) msgBub.insertBefore(chain, md);
    else msgBub.insertBefore(chain, msgBub.firstChild);
  }
  return chain;
}

function laylaAppendReasoningStep(msgLaylaDiv, text, stepNum) {
  const chain = laylaEnsureReasoningChain(msgLaylaDiv);
  if (!chain) return;
  const steps = chain.querySelector('.layla-reasoning-steps');
  if (!steps) return;
  const n = stepNum && Number(stepNum) > 0 ? Number(stepNum) : (steps.children.length + 1);
  const row = document.createElement('div');
  row.className = 'layla-reasoning-step';
  row.innerHTML = '<span class="layla-reasoning-step-n">' + n + '.</span><div class="layla-reasoning-step-body"></div>';
  row.querySelector('.layla-reasoning-step-body').textContent = String(text || '');
  steps.appendChild(row);
  const sum = chain.querySelector('.layla-reasoning-summary');
  if (sum) sum.textContent = 'Reasoning · ' + steps.children.length + ' steps';
}

function retryLastMessage() {
  if (!_lastDisplayMsg) return;
  if (window.laylaChatFSM && !window.laylaChatFSM.canSend()) return;
  const chat = document.getElementById('chat');
  const input = document.getElementById('msg-input');
  if (!chat || !input) return;
  const nodes = [...chat.children];
  const toRemove = [];
  let foundLayla = false, foundSep = false, foundYou = false;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (n.id === 'typing-wrap') { toRemove.push(n); continue; }
    if (!foundLayla && n.classList.contains('msg-layla')) { foundLayla = true; toRemove.push(n); continue; }
    if (foundLayla && !foundSep && n.classList.contains('separator')) { foundSep = true; toRemove.push(n); continue; }
    if (foundSep && !foundYou && n.classList.contains('msg-you')) { foundYou = true; toRemove.push(n); break; }
  }
  toRemove.forEach(el => el.remove());
  input.value = _lastDisplayMsg;
  toggleSendButton();
  send();
}

async function send() {
  _dbg('send() called');
  _hideMentionDropdown();
  const input = document.getElementById('msg-input');
  if (!input) return;
  let msg = (input.value || '').trim();
  if (!msg) return;
  if (window._laylaSendBusy) return;
  window._laylaSendBusy = true;
  if (window.laylaChatFSM && !window.laylaChatFSM.beginSend()) {
    window._laylaSendBusy = false;
    return;
  }

  const ac = new AbortController();
  _activeAgentAbort = ac;
  let metaTimer = null;
  let firstTokenTimer = null;
  let stalledTimer = null;
  // Chat chrome is rendered from FSM state via window.laylaOnChatState.
  try { laylaHeaderProgressStart(); } catch (_) {}
  try { operatorTraceClear(); } catch (_) {}
  try { laylaStreamStatsStart(''); } catch (_) {}

  let msgAspect = currentAspect;
  const mentionMatch = msg.match(/^@([a-z]+)\s*/i);
  if (mentionMatch) {
    try {
      const mentioned = mentionMatch[1].toLowerCase();
      const found = (typeof ASPECTS !== 'undefined' && ASPECTS.find)
        ? ASPECTS.find(a => a.id === mentioned || (a.name || '').toLowerCase() === mentioned)
        : null;
      if (found) {
        msgAspect = found.id;
        msg = msg.slice(mentionMatch[0].length).trim() || msg;
      }
    } catch (_) {}
  }
  if (_aspectLocked) msgAspect = currentAspect;

  input.value = '';
  toggleSendButton();
  const displayMsg = mentionMatch && msgAspect !== currentAspect ? ('@' + msgAspect + ' ' + msg) : msg;
  addMsg('you', displayMsg);
  addSeparator();
  _lastDisplayMsg = displayMsg;

  ensureLaylaConversationId();

  const chatEl = document.getElementById('chat');
  const streamMode = document.getElementById('stream-toggle')?.checked || false;
  const modelOverride = (document.getElementById('model-override')?.value || '').trim();
  const workspacePath = (document.getElementById('workspace-path')?.value || '').trim();
  const projectId = (typeof localStorage !== 'undefined' ? (localStorage.getItem('layla_active_project_id') || '') : '').trim();
  const composeDraft = (document.getElementById('compose-draft')?.value || '').trim();

  const payload = {
    message: msg,
    context: composeDraft || '',
    workspace_root: workspacePath || '',
    project_id: projectId || '',
    aspect_id: msgAspect,
    conversation_id: currentConversationId,
    show_thinking: document.getElementById('show-thinking')?.checked ?? false,
    allow_write: document.getElementById('allow-write')?.checked ?? false,
    allow_run: document.getElementById('allow-run')?.checked ?? false,
    stream: !!streamMode,
  };
  if (modelOverride) payload.model_override = modelOverride;
  const _epSel = document.getElementById('engineering-pipeline-mode');
  if (_epSel && _epSel.value && _epSel.value !== 'chat') payload.engineering_pipeline_mode = _epSel.value;
  const _clarTa = document.getElementById('pipeline-clarify-answers');
  if (_clarTa && _clarTa.value.trim()) {
    payload.clarification_reply = _clarTa.value.trim();
    _clarTa.value = '';
    const _cp = document.getElementById('pipeline-clarify-panel');
    if (_cp) _cp.style.display = 'none';
  }

  try { laylaShowTypingIndicator(msgAspect, streamMode ? 'connecting' : 'preparing_reply'); } catch (_) {}

  try {
    if (streamMode) {
      const res = await fetchWithTimeout(
        '/agent',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: ac.signal },
        Math.max(laylaAgentStreamTimeoutMs(), 300000)
      );
      if (!res.ok || !res.body) {
        let body = {};
        try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) {} } catch(_) {}
        try { laylaRemoveTypingIndicator(); } catch (_) {}
        addMsg('layla', formatAgentError(res, body));
        try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_) {}
        return;
      }
      try { laylaRemoveTypingIndicator(); } catch (_) {}
      try { if (window.laylaChatFSM) window.laylaChatFSM.beginStream(); } catch (_) {}
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = '';
      hideEmpty();
      const div = document.createElement('div');
      div.className = 'msg msg-layla';
      div.innerHTML = '<div class=\"msg-label msg-label-layla\">' + formatLaylaLabelHtml(msgAspect) + '</div><div class=\"msg-bubble\" title=\"Click to copy\"><div class=\"md-content stream-md-placeholder\"><div class=\"typing-indicator\" style=\"min-height:36px\"><div class=\"typing-dots\"><span></span><span></span><span></span></div></div><div class=\"tool-status-label\">' + (UX_STATE_LABELS.connecting || 'Connecting') + '</div></div></div>';
      if (chatEl) chatEl.appendChild(div);
      const bubble = div.querySelector('.md-content');
      let thinkBox = null;
      let thinkContent = null;
      let thinkCount = 0;
      function ensureThinkBox() {
        if (thinkBox) return;
        thinkBox = document.createElement('details');
        thinkBox.className = 'tool-trace';
        thinkBox.style.borderLeft = '2px solid var(--asp)';
        thinkBox.open = true;
        thinkBox.innerHTML = '<summary>Thinking (live)</summary>';
        thinkContent = document.createElement('div');
        thinkContent.className = 'tool-trace-content';
        thinkContent.style.whiteSpace = 'pre-wrap';
        thinkContent.style.maxHeight = '180px';
        thinkContent.style.overflow = 'auto';
        thinkBox.appendChild(thinkContent);
        div.appendChild(thinkBox);
      }
      function appendThinkLine(txt) {
        if (!txt) return;
        ensureThinkBox();
        thinkCount += 1;
        if (thinkBox && thinkBox.querySelector('summary')) {
          thinkBox.querySelector('summary').textContent = 'Thinking (live) · ' + thinkCount;
        }
        if (thinkContent) {
          thinkContent.textContent += (thinkContent.textContent ? '\n' : '') + txt;
          thinkContent.scrollTop = thinkContent.scrollHeight;
        }
      }
      const streamMeta = document.createElement('div');
      streamMeta.className = 'memory-attribution';
      streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS.connecting || 'Connecting') + ' · 0s · 0 chars';
      div.appendChild(streamMeta);
      const streamStartedAt = Date.now();
      let liveStatus = 'connecting';
      laylaNotifyStreamPhase(div, 'connecting');
      metaTimer = setInterval(() => {
        const secs = Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000));
        streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS[liveStatus] || liveStatus) + ' · ' + secs + 's · ' + (full || '').length + ' chars';
      }, 500);
      let gotToken = false;
      firstTokenTimer = setTimeout(() => {
        liveStatus = 'waiting_first_token';
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
        statusEl.textContent = UX_STATE_LABELS.waiting_first_token;
        laylaNotifyStreamPhase(div, liveStatus);
      }, 1800);
      const stallMs = laylaStalledSilenceMs();
      stalledTimer = setTimeout(() => {
        liveStatus = 'stalled';
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
        statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
        laylaNotifyStreamPhase(div, 'stalled');
      }, stallMs);
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = dec.decode(value, { stream: true });
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          let obj = null;
          try { obj = JSON.parse(line.slice(6)); } catch (_) { obj = null; }
          if (!obj) continue;
          if (obj.pulse === true) {
            clearTimeout(stalledTimer);
            stalledTimer = setTimeout(() => {
              liveStatus = 'stalled';
              let statusEl = div.querySelector('.tool-status-label');
              if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
              statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
              laylaNotifyStreamPhase(div, 'stalled');
            }, stallMs);
          }
          if (obj.error) {
            clearTimeout(firstTokenTimer);
            clearTimeout(stalledTimer);
            clearInterval(metaTimer);
            try { div.remove(); } catch (_) {}
            try { laylaRemoveTypingIndicator(); } catch (_) {}
            addMsg('layla', String(obj.error));
            try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_) {}
            return;
          }
          if (obj.ux_state) {
            liveStatus = String(obj.ux_state);
            laylaNotifyStreamPhase(div, liveStatus);
            const statusEl = div.querySelector('.tool-status-label');
            if (statusEl) statusEl.textContent = UX_STATE_LABELS[liveStatus] || liveStatus;
          }
          if (obj.type === 'thinking' || obj.think) {
            const t = String(obj.text || obj.think || '').trim();
            if (t) appendThinkLine('✦ ' + t);
          }
          if (obj.type === 'tool_step' || obj.tool_start) {
            const tool = String(obj.tool || obj.tool_start || '').trim();
            const phase = String(obj.phase || (obj.tool_start ? 'start' : 'end'));
            const ok = (obj.ok === true ? 'ok' : obj.ok === false ? 'fail' : '');
            const summary = String(obj.summary || '').trim();
            const line = '▸ ' + tool + (phase ? (' [' + phase + ']') : '') + (ok ? (' ' + ok) : '') + (summary ? (' — ' + summary) : '');
            if (tool) { appendThinkLine(line); try { laylaStreamStatsStep(tool); } catch (_) {} }
          }
          if (obj.type === 'model_selection' || obj.model_selection) {
            const ms = obj.model_selection || obj;
            const mdl = String(ms.model || '').replace(/^claude-/i, '').replace(/-\d{8}$/, '');
            try { const el = document.getElementById('stream-model-badge'); if (el && mdl) el.textContent = '⬡ ' + mdl; } catch (_) {}
          }
          if (obj.token) {
            liveStatus = 'streaming';
            laylaNotifyStreamPhase(div, 'streaming');
            if (!gotToken) {
              gotToken = true;
              clearTimeout(firstTokenTimer);
              if (bubble && bubble.classList.contains('stream-md-placeholder')) {
                bubble.classList.remove('stream-md-placeholder');
                bubble.innerHTML = '';
              }
            }
            clearTimeout(stalledTimer);
            stalledTimer = setTimeout(() => {
              liveStatus = 'stalled';
              let statusEl = div.querySelector('.tool-status-label');
              if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
              statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
              laylaNotifyStreamPhase(div, 'stalled');
            }, stallMs);
            full += String(obj.token);
            if (bubble) bubble.textContent = full;
            try { if (full.length % 200 === 0) laylaStreamStatsChars(full.length); } catch (_) {}
          }
          if (obj.done) {
            clearTimeout(firstTokenTimer);
            clearTimeout(stalledTimer);
            clearInterval(metaTimer);
            liveStatus = 'done';
            laylaNotifyStreamPhase(div, 'done');
            if (bubble) bubble.textContent = full;
            if (thinkBox) {
              try { thinkBox.open = false; } catch (_) {}
            }
            if (_ttsEnabled && full) { try { speakText(full).catch(() => {}); } catch (_) {} }
            try { refreshMaturityCard(true); } catch (_) {}
            try { laylaStreamStatsChars(full.length); laylaStreamStatsStop(); } catch (_) {}
            try { if (typeof laylaIngestArtifacts === 'function') laylaIngestArtifacts(full); } catch (_) {}
          }
        }
      }
    } else {
      const res = await fetchWithTimeout(
        '/agent',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: ac.signal },
        Math.max(laylaAgentTimeoutMs(), 120000)
      );
      let data = {};
      try { data = await res.json(); } catch (_) { data = {}; }
      if (!res.ok || !data || data.ok === false) {
        try { laylaRemoveTypingIndicator(); } catch (_) {}
        addMsg('layla', formatAgentError(res, data || {}));
        try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_) {}
        return;
      }
      try { laylaRemoveTypingIndicator(); } catch (_) {}
      const resp = (data && (data.response || data.reply)) || '(no output)';
      const replyAspect = (data && (data.aspect || (data.state && data.state.aspect))) || msgAspect;
      addMsg('layla', resp, replyAspect, data?.state?.steps?.some(s => s.deliberated), data?.state?.steps, data?.state?.ux_states, data?.state?.memory_influenced);
      if (_ttsEnabled && resp && resp !== '(no output)') { speakText(resp).catch(() => {}); }
      try { refreshMaturityCard(true); } catch (_) {}
      try { laylaStreamStatsStop(); } catch (_) {}
      try { if (typeof laylaIngestArtifacts === 'function') laylaIngestArtifacts(resp); } catch (_) {}
    }
  } catch (e) {
    try { laylaRemoveTypingIndicator(); } catch (_) {}
    addMsg('layla', 'Error: ' + (e && e.message ? e.message : String(e)));
    try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_) {}
  } finally {
    window._laylaSendBusy = false;
    try { if (firstTokenTimer) clearTimeout(firstTokenTimer); } catch (_) {}
    try { if (stalledTimer) clearTimeout(stalledTimer); } catch (_) {}
    try { if (metaTimer) clearInterval(metaTimer); } catch (_) {}
    try { laylaRemoveTypingIndicator(); } catch (_) {}
    try { if (window.laylaChatFSM) window.laylaChatFSM.finishOk(); } catch (_) {}
    try { laylaHeaderProgressStop(); } catch (_) {}
    try { laylaStreamStatsStop(); } catch (_) {}
    try { refreshApprovals(); } catch (_) {}
    try { updateContextChip(); } catch (_) {}
    try { if (typeof laylaScrollActiveConversationIntoView === 'function') laylaScrollActiveConversationIntoView(); } catch (_) {}
  }
}

window.send = send;

} catch (_) {
  // UI script should fail soft; server still usable.
}

// ── UI repair shims: prevent permanent "Loading…" states ─────────────────────
//
// The HTML template references some functions that may not exist in older
// bundles. Provide minimal implementations so panels settle into either real
// data or a clear "not available" message.

const __esc = (typeof window.escapeHtml === 'function')
  ? window.escapeHtml
  : function (s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  };
const __toast = (typeof window.showToast === 'function')
  ? window.showToast
  : function (t) { try { console.log('[Layla UI]', t); } catch (_) {} };

function _setBoxHtml(id, html) {
  const el = document.getElementById(id);
  if (!el) return null;
  el.innerHTML = html;
  return el;
}

async function refreshVersionInfo() {
  const el = document.getElementById('app-version');
  if (!el) return;
  el.textContent = 'Version: loading…';
  try {
    const r = await fetch('/version');
    const d = await r.json().catch(() => ({}));
    const v = (d && d.ok && d.version) ? String(d.version) : '';
    el.textContent = 'Version: ' + (v || '—');
  } catch (_) {
    el.textContent = 'Version: (could not load)';
  }
}
window.refreshVersionInfo = refreshVersionInfo;

async function refreshPlatformHealth() {
  const box = document.getElementById('platform-health');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/health');
    const d = await r.json().catch(() => ({}));
    const status = String((d && d.status) || 'unknown');
    const html = [];
    html.push('<div><strong>Status</strong>: ' + __esc(status) + '</div>');
    html.push('<div><strong>Uptime</strong>: ' + __esc(String(Math.round((d && d.uptime_seconds) || 0))) + 's</div>');
    html.push('<div><strong>Model</strong>: ' + __esc((d && d.model_loaded) ? 'loaded' : 'not loaded') + '</div>');
    html.push('<div><strong>Tools</strong>: ' + __esc(String((d && d.tools_registered) || 0)) + '</div>');
    html.push('<div><strong>Learnings</strong>: ' + __esc(String((d && d.learnings) || 0)) + '</div>');
    html.push('<div><strong>Study plans</strong>: ' + __esc(String((d && d.study_plans) || 0)) + '</div>');
    html.push('<div><strong>Vector store</strong>: ' + __esc(String((d && d.vector_store) || 'unknown')) + '</div>');
    box.innerHTML = html.join('');
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load health</span>';
  }
}
window.refreshPlatformHealth = refreshPlatformHealth;

async function refreshRuntimeOptions() {
  const box = document.getElementById('runtime-options-panel');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Loading…</span>';
  try {
    const r = await fetch('/health?deep=true');
    const d = await r.json().catch(() => ({}));
    const html = [];
    html.push('<div style="display:flex;flex-wrap:wrap;gap:6px">');
    html.push('<span class="option-pill">safe_mode: ' + __esc(String(!!(d && d.safe_mode))) + '</span>');
    html.push('<span class="option-pill">uncensored: ' + __esc(String(!!(d && d.uncensored))) + '</span>');
    html.push('<span class="option-pill">nsfw_allowed: ' + __esc(String(!!(d && d.nsfw_allowed))) + '</span>');
    html.push('<span class="option-pill">use_chroma: ' + __esc(String(!!(d && d.use_chroma))) + '</span>');
    html.push('</div>');
    if (d && d.limits) {
      html.push('<div style="margin-top:8px"><strong>Limits</strong></div>');
      html.push('<div style="color:var(--text-dim);font-size:0.7rem;line-height:1.5">');
      html.push('max_active_runs: ' + __esc(String(d.limits.max_active_runs ?? '—')) + '<br>');
      html.push('max_cpu_percent: ' + __esc(String(d.limits.max_cpu_percent ?? '—')) + '<br>');
      html.push('max_ram_percent: ' + __esc(String(d.limits.max_ram_percent ?? '—')) + '<br>');
      html.push('</div>');
    }
    box.innerHTML = html.join('');
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load runtime options</span>';
  }
}
window.refreshRuntimeOptions = refreshRuntimeOptions;

window.saveContentPolicySettings = async function saveContentPolicySettings() {
  const btn = document.querySelector('button[onclick*="saveContentPolicySettings"]');
  const unc = !!document.getElementById('opt-uncensored')?.checked;
  const nsfw = !!document.getElementById('opt-nsfw-allowed')?.checked;
  if (btn) btn.disabled = true;
  try {
    const r = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uncensored: unc, nsfw_allowed: nsfw }),
    });
    const d = await r.json().catch(() => ({}));
    __toast((d && d.ok) ? 'Saved content policy' : 'Save failed');
  } catch (_) {
    __toast('Save failed');
  } finally {
    if (btn) btn.disabled = false;
  }
};

window.loadPhoneAccess = async function loadPhoneAccess() {
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
};

window.copyPhoneUrl = async function copyPhoneUrl() {
  const url = (document.getElementById('phone-access-url')?.textContent || '').trim();
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    __toast('Copied');
  } catch (_) {
    try {
      const ta = document.createElement('textarea');
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

window.refreshAgentsPanel = async function refreshAgentsPanel() {
  const box = document.getElementById('agents-resource-panel');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/health?deep=true');
    const d = await r.json().catch(() => ({}));
    const lim = d && d.limits ? d.limits : {};
    box.innerHTML =
      '<div><strong>max_active_runs</strong>: ' + __esc(String(lim.max_active_runs ?? '—')) + '</div>' +
      '<div><strong>performance_mode</strong>: ' + __esc(String(lim.performance_mode ?? d.performance_mode ?? '—')) + '</div>' +
      '<div><strong>CPU cap</strong>: ' + __esc(String(lim.max_cpu_percent ?? '—')) + '%</div>' +
      '<div><strong>RAM cap</strong>: ' + __esc(String(lim.max_ram_percent ?? '—')) + '%</div>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load</span>';
  }
};

window.refreshStudyPlans = async function refreshStudyPlans() {
  const box = document.getElementById('study-list');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/study_plans');
    const d = await r.json().catch(() => ({}));
    const plans = Array.isArray(d && d.plans) ? d.plans : [];
    if (!plans.length) {
      box.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">No active study plans yet.</span>';
      return;
    }
    box.innerHTML = plans.slice(0, 20).map(p => {
      const topic = __esc(String(p.topic || ''));
      const sessions = __esc(String(p.study_sessions ?? 0));
      const last = __esc(String(p.last_studied || ''));
      return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06)">' +
        '<div><strong>' + topic + '</strong></div>' +
        '<div style="color:var(--text-dim);font-size:0.68rem">sessions: ' + sessions + (last ? (' · last: ' + last) : '') + '</div>' +
        '</div>';
    }).join('');
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load study plans</span>';
  }
};

window.loadStudyPresetsAndSuggestions = async function loadStudyPresetsAndSuggestions() {
  const presets = document.getElementById('study-presets');
  const sug = document.getElementById('study-suggestions');
  if (presets) presets.innerHTML = '';
  if (sug) sug.innerHTML = '';
  try {
    const r1 = await fetch('/study_plans/presets');
    const d1 = await r1.json().catch(() => ({}));
    const topics = Array.isArray(d1 && d1.topics) ? d1.topics : [];
    if (presets) presets.innerHTML = topics.slice(0, 16).map(t => '<button type="button" class="approve-btn" style="font-size:0.62rem" onclick="addStudyPlan(' + JSON.stringify(String(t)) + ')">' + __esc(String(t)) + '</button>').join('');
  } catch (_) {}
  try {
    const r2 = await fetch('/study_plans/suggestions');
    const d2 = await r2.json().catch(() => ({}));
    const suggestions = Array.isArray(d2 && d2.suggestions) ? d2.suggestions : [];
    if (sug) sug.innerHTML = suggestions.slice(0, 16).map(t => '<button type="button" class="approve-btn" style="font-size:0.62rem" onclick="addStudyPlan(' + JSON.stringify(String(t)) + ')">' + __esc(String(t)) + '</button>').join('');
  } catch (_) {}
};

window.addStudyPlan = async function addStudyPlan(topicOverride) {
  const inp = document.getElementById('study-input');
  const topic = String(topicOverride || (inp && inp.value) || '').trim();
  if (!topic) return;
  if (inp) inp.value = '';
  try {
    const r = await fetch('/study_plans', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic }) });
    const d = await r.json().catch(() => ({}));
    __toast((d && d.ok) ? 'Added' : 'Add failed');
    try { refreshStudyPlans(); } catch (_) {}
  } catch (_) {
    __toast('Add failed');
  }
};

window.studyTopicFromChatInput = async function studyTopicFromChatInput() {
  const text = (document.getElementById('msg-input')?.value || '').trim();
  if (!text) return;
  try {
    const r = await fetch('/study_plans/derive_topic', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text }) });
    const d = await r.json().catch(() => ({}));
    if (d && d.ok && d.topic) addStudyPlan(String(d.topic));
  } catch (_) {}
};

window.studyTopicFromLastUserMessage = function studyTopicFromLastUserMessage() {
  try {
    const chat = document.getElementById('chat');
    if (!chat) return;
    const rows = chat.querySelectorAll('.msg.msg-you .msg-bubble');
    const last = rows && rows.length ? String(rows[rows.length - 1].textContent || '').trim() : '';
    if (!last) return;
    fetch('/study_plans/derive_topic', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: last }) })
      .then(r => r.json()).then(d => { if (d && d.ok && d.topic) addStudyPlan(String(d.topic)); })
      .catch(() => {});
  } catch (_) {}
};

window.refreshSkillsList = async function refreshSkillsList() {
  const box = document.getElementById('platform-skills');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/skills');
    const d = await r.json().catch(() => ({}));
    const skills = Array.isArray(d && d.skills) ? d.skills : [];
    box.innerHTML = skills.length
      ? skills.slice(0, 40).map(s => '<div style="margin:4px 0"><strong>' + __esc(String(s.name || '')) + '</strong><div style="color:var(--text-dim);font-size:0.68rem">' + __esc(String(s.description || '')) + '</div></div>').join('')
      : '<span style="color:var(--text-dim)">No skills found.</span>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load skills</span>';
  }
};

window.refreshLaylaPlansPanel = async function refreshLaylaPlansPanel() {
  const listEl = document.getElementById('layla-plans-list');
  if (!listEl) return;
  listEl.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const wr = (document.getElementById('workspace-path')?.value || '').trim();
    const q = wr ? ('?workspace_root=' + encodeURIComponent(wr) + '&limit=30') : '?limit=30';
    const r = await fetch('/plans' + q);
    const d = await r.json().catch(() => ({}));
    const plans = Array.isArray(d && d.plans) ? d.plans : [];
    if (!plans.length) {
      listEl.innerHTML = '<span style="color:var(--text-dim)">No plans for this workspace filter.</span>';
      return;
    }
    listEl.innerHTML = plans.slice(0, 24).map(function (p) {
      const id = String(p.id || '');
      const g = __esc(String(p.goal || '').slice(0, 120));
      const st = __esc(String(p.status || ''));
      const sid = id.replace(/[^a-zA-Z0-9_-]/g, '_');
      return '<div style="margin:6px 0;padding:8px;border:1px solid rgba(255,255,255,0.06);border-radius:6px;background:rgba(0,0,0,0.15)">' +
        '<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><strong>' + g + '</strong>' +
        '<span style="color:var(--text-dim);font-size:0.68rem">' + st + '</span></div>' +
        '<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px">' +
        '<button type="button" class="approve-btn" onclick="laylaApprovePlan(' + JSON.stringify(id) + ')">Approve</button>' +
        '<button type="button" class="approve-btn" onclick="laylaExecutePlan(' + JSON.stringify(id) + ')">Execute</button>' +
        '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--asp);color:var(--asp)" onclick="typeof laylaShowPlanViz===\'function\'&&laylaShowPlanViz(' + JSON.stringify(id) + ')">⬡ Gantt</button>' +
        '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--border);color:var(--text-dim)" onclick="laylaExpandPlan(' + JSON.stringify(id) + ', ' + JSON.stringify(sid) + ')">Detail</button>' +
        '</div>' +
        '<pre id="plan-detail-' + sid + '" style="display:none;margin-top:8px;font-size:0.62rem;max-height:200px;overflow:auto;white-space:pre-wrap"></pre>' +
        '</div>';
    }).join('');
  } catch (_) {
    listEl.innerHTML = '<span style="color:var(--text-dim)">Could not load plans</span>';
  }
};

window.laylaApprovePlan = async function laylaApprovePlan(planId) {
  try {
    const r = await fetch('/plans/' + encodeURIComponent(planId) + '/approve', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (typeof showToast === 'function') showToast(d.ok ? 'Plan approved' : (d.error || 'failed'));
    refreshLaylaPlansPanel();
  } catch (e) {
    if (typeof showToast === 'function') showToast('Approve failed');
  }
};

window.laylaExecutePlan = async function laylaExecutePlan(planId) {
  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  const allowWrite = document.getElementById('allow-write')?.checked ?? false;
  const allowRun = document.getElementById('allow-run')?.checked ?? false;
  try { ensureLaylaConversationId(); } catch (_) {}
  try { laylaHeaderProgressStart(); } catch (_) {}
  try {
    const r = await fetch('/plans/' + encodeURIComponent(planId) + '/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_root: wp,
        allow_write: allowWrite,
        allow_run: allowRun,
        aspect_id: typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan',
        conversation_id: typeof currentConversationId !== 'undefined' ? currentConversationId : '',
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (typeof showToast === 'function') showToast(d.ok ? 'Execution finished' : (d.error || 'execute failed'));
    refreshLaylaPlansPanel();
  } catch (e) {
    if (typeof showToast === 'function') showToast('Execute failed');
  } finally {
    try { laylaHeaderProgressStop(); } catch (_) {}
  }
};

window.laylaExpandPlan = async function laylaExpandPlan(planId, sid) {
  const pre = document.getElementById('plan-detail-' + sid);
  if (!pre) return;
  const on = pre.style.display !== 'block';
  pre.style.display = on ? 'block' : 'none';
  if (!on) return;
  pre.textContent = 'Loading…';
  try {
    const r = await fetch('/plans/' + encodeURIComponent(planId));
    const d = await r.json().catch(() => ({}));
    const p = d && d.plan;
    pre.textContent = p ? JSON.stringify(p, null, 2) : JSON.stringify(d, null, 2);
  } catch (_) {
    pre.textContent = 'Failed to load';
  }
};

window.laylaGitUndo = async function laylaGitUndo() {
  try {
    const r = await fetch('/undo', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (typeof showToast === 'function') showToast(d.ok ? (d.message || 'Undone') : (d.error || 'undo failed'));
  } catch (_) {
    if (typeof showToast === 'function') showToast('Undo failed');
  }
};

window.laylaRunSetupAuto = async function laylaRunSetupAuto() {
  try {
    const r = await fetch('/setup/auto', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (typeof showToast === 'function') showToast((d && d.ok) ? 'Auto-setup finished' : String((d && d.error) || 'failed'));
  } catch (_) {
    if (typeof showToast === 'function') showToast('Auto-setup failed');
  }
};

window.laylaRunDoctor = async function laylaRunDoctor() {
  try {
    const r = await fetch('/doctor');
    const d = await r.json().catch(() => ({}));
    addMsg('layla', '**Doctor snapshot**\n```json\n' + JSON.stringify(d, null, 2).slice(0, 8000) + '\n```');
  } catch (_) {
    if (typeof showToast === 'function') showToast('Doctor failed');
  }
};

window.laylaRefreshWorkspaceAwareness = async function laylaRefreshWorkspaceAwareness() {
  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  const pulse = document.getElementById('workspace-awareness-pulse');
  const pulseTab = document.getElementById('workspace-awareness-tab-pulse');
  if (!wp) {
    if (typeof showToast === 'function') showToast('Set workspace path first');
    return;
  }
  if (pulse) pulse.style.display = 'inline';
  if (pulseTab) pulseTab.style.display = 'inline';
  try {
    const r = await fetch('/workspace/awareness/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_root: wp }),
    });
    const d = await r.json().catch(() => ({}));
    if (typeof showToast === 'function') showToast(d.ok ? 'Awareness refresh started' : String(d.error || 'failed'));
  } catch (_) {
    if (typeof showToast === 'function') showToast('Awareness refresh failed');
  } finally {
    if (pulse) pulse.style.display = 'none';
    if (pulseTab) pulseTab.style.display = 'none';
  }
};

window.laylaLoadProjectMemoryInspector = async function laylaLoadProjectMemoryInspector() {
  const pre = document.getElementById('project-memory-inspector');
  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  if (!wp) {
    if (typeof showToast === 'function') showToast('Set workspace path first');
    return;
  }
  if (pre) pre.textContent = 'Loading…';
  try {
    const r = await fetch('/workspace/project_memory?workspace_root=' + encodeURIComponent(wp));
    const d = await r.json().catch(() => ({}));
    const sec = (d && d.project_memory) || {};
    const pick = ['modules', 'issues', 'plans', 'todos'];
    let out = '';
    for (var i = 0; i < pick.length; i++) {
      var k = pick[i];
      out += '## ' + k + '\n' + JSON.stringify(sec[k] != null ? sec[k] : (d[k] != null ? d[k] : null), null, 2).slice(0, 6000) + '\n\n';
    }
    if (pre) pre.textContent = out.trim() || JSON.stringify(d, null, 2).slice(0, 12000);
  } catch (e) {
    if (pre) pre.textContent = String(e);
  }
};

window.laylaWorkspaceSymbolSearch = async function laylaWorkspaceSymbolSearch() {
  const q = String(document.getElementById('workspace-symbol-query')?.value || '').trim();
  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  const box = document.getElementById('workspace-symbol-results');
  if (!q) {
    if (typeof showToast === 'function') showToast('Enter a symbol or phrase');
    return;
  }
  if (box) box.textContent = 'Searching…';
  try {
    const url = '/workspace/symbol_search?q=' + encodeURIComponent(q) + (wp ? '&workspace_root=' + encodeURIComponent(wp) : '');
    const r = await fetch(url);
    const d = await r.json().catch(() => ({}));
    if (box) box.textContent = JSON.stringify(d, null, 2).slice(0, 12000);
  } catch (e) {
    if (box) box.textContent = String(e);
  }
};

window.laylaRunInvestigation = function laylaRunInvestigation() {
  var g = document.getElementById('autonomous-goal');
  if (g) {
    g.value = 'Investigate this workspace for bugs, risky patterns, and inconsistencies. Trace logic across files where needed. Summarize root causes and cite paths/lines. Do not modify any files.';
  }
  var rm = document.getElementById('autonomous-research-mode');
  if (rm) rm.checked = true;
  var cf = document.getElementById('autonomous-confirm');
  if (cf) cf.checked = true;
  return laylaRunAutonomousResearch();
};

function _laylaAutonomousInvestigationPreset(goalText) {
  var g = document.getElementById('autonomous-goal');
  if (g) g.value = goalText;
  var rm = document.getElementById('autonomous-research-mode');
  if (rm) rm.checked = true;
  var cf = document.getElementById('autonomous-confirm');
  if (cf) cf.checked = true;
}

window.laylaInvestigationTemplateTrace = function laylaInvestigationTemplateTrace() {
  _laylaAutonomousInvestigationPreset(
    'Trace where the selected symbol, function, or public API is defined and used across this repository. Map call sites, key modules, and data flow between files. Summarize findings with file:line evidence. Do not modify any files.'
  );
  return laylaRunAutonomousResearch();
};

window.laylaInvestigationTemplateStructure = function laylaInvestigationTemplateStructure() {
  _laylaAutonomousInvestigationPreset(
    'Analyze the repository structure: top-level layout, main packages, entry points, configuration and CI workflows. Identify coupling risks and ambiguous boundaries across multiple directories. Summarize with cited paths. Do not modify any files.'
  );
  return laylaRunAutonomousResearch();
};

window.laylaInvestigationTemplateBug = function laylaInvestigationTemplateBug() {
  _laylaAutonomousInvestigationPreset(
    'Investigate likely sources of incorrect behavior: trace error paths, suspicious hotspots, and inconsistent assumptions across modules. Hypothesize root causes with evidence from code reads and search; propose verification steps only (no execution). Do not modify any files.'
  );
  return laylaRunAutonomousResearch();
};

window.laylaRunAutonomousResearch = async function laylaRunAutonomousResearch() {
  const goal = String(document.getElementById('autonomous-goal')?.value || '').trim();
  const confirmCb = document.getElementById('autonomous-confirm');
  const out = document.getElementById('autonomous-result');
  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  if (!goal) {
    if (typeof showToast === 'function') showToast('Enter a goal');
    return;
  }
  if (!confirmCb || !confirmCb.checked) {
    if (typeof showToast === 'function') showToast('Check confirm_autonomous');
    return;
  }
  var maxSteps = parseInt(String(document.getElementById('autonomous-max-steps')?.value || '30'), 10);
  var timeoutS = parseInt(String(document.getElementById('autonomous-timeout')?.value || '120'), 10);
  if (!(maxSteps >= 1 && maxSteps <= 500)) maxSteps = 30;
  if (!(timeoutS >= 5 && timeoutS <= 7200)) timeoutS = 120;
  const taskId = (window.crypto && typeof window.crypto.randomUUID === 'function')
    ? window.crypto.randomUUID()
    : ('au-' + String(Date.now()));
  var sumOut = document.getElementById('autonomous-result-summary');
  if (sumOut) sumOut.textContent = 'Running… (task ' + taskId.slice(0, 8) + ')';
  if (out) out.textContent = 'Running (task ' + taskId.slice(0, 8) + '…)…\nPoll /agent/tasks for tool progress.';
  var poll = setInterval(async function () {
    try {
      var r = await fetch('/agent/tasks/' + encodeURIComponent(taskId));
      var d = await r.json().catch(function () { return {}; });
      if (d && d.ok && d.task && Array.isArray(d.task.progress_tail) && d.task.progress_tail.length && out) {
        var tail = d.task.progress_tail;
        var last = tail[tail.length - 1];
        out.textContent = 'progress: ' + JSON.stringify(last).slice(0, 1500) + '\n…';
      }
    } catch (_) {}
  }, 500);
  try {
    var r = await fetch('/autonomous/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        goal: goal,
        workspace_root: wp || '',
        max_steps: maxSteps,
        timeout_seconds: timeoutS,
        research_mode: !!(document.getElementById('autonomous-research-mode') && document.getElementById('autonomous-research-mode').checked),
        confirm_autonomous: true,
        progress_task_id: taskId,
      }),
    });
    clearInterval(poll);
    var raw = await r.text();
    var d = {};
    try { d = JSON.parse(raw); } catch (_) { d = { _raw: raw }; }
    if (sumOut && d && typeof d === 'object') {
      var lines = [];
      lines.push('Steps: ' + (d.steps_used != null ? d.steps_used : '—') + ' · Stopped: ' + (d.stopped_reason || '—'));
      if (d.budget_detail) lines[lines.length - 1] += ' · budget: ' + d.budget_detail;
      lines.push('Confidence: ' + (d.confidence != null ? d.confidence : '—'));
      var src = String(d.source || '').trim();
      if (src === 'reuse') lines.push('Source: reused knowledge (investigation_reuse.jsonl)');
      else if (src === 'wiki') lines.push('Source: wiki markdown (prefetch)');
      else if (src === 'fresh') lines.push('Source: fresh investigation');
      else if (src === 'blocked') lines.push('Source: blocked (value gate)');
      else if (src) lines.push('Source: ' + src);
      if (d.reused === true) lines.push('Reused: yes');
      else if (d.reused === false) lines.push('Reused: no');
      var files = Array.isArray(d.files_accessed) ? d.files_accessed : [];
      var show = files.slice(0, 12);
      var more = files.length - show.length;
      lines.push('Files accessed (' + files.length + '): ' + (show.length ? show.join(', ') : '—') + (more > 0 ? ' … +' + more + ' more' : ''));
      var rs = String(d.investigation_trace || d.reasoning_summary || d.reasoning || '').trim();
      if (rs) lines.push('Trace: ' + rs.slice(0, 1200) + (rs.length > 1200 ? '…' : ''));
      sumOut.textContent = lines.join('\n');
    } else if (sumOut) {
      sumOut.textContent = '';
    }
    if (out) {
      const pretty = typeof d === 'object' ? JSON.stringify(d, null, 2) : String(d);
      out.textContent = pretty.slice(0, 16000);
    }
    if (typeof showToast === 'function') showToast(r.ok ? 'Autonomous run finished' : 'Autonomous run error');
  } catch (e) {
    clearInterval(poll);
    if (out) out.textContent = String(e);
  }
};

window.onMemorySearch = async function onMemorySearch(q) {
  const box = document.getElementById('memory-search-results');
  const query = String(q || '').trim();
  if (!box) return;
  if (!query) {
    box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Type to search learnings (semantic / FTS)</span>';
    return;
  }
  box.innerHTML = '<span style="color:var(--text-dim)">Searching…</span>';
  try {
    const r = await fetch('/memories?q=' + encodeURIComponent(query) + '&n=8');
    const d = await r.json().catch(() => ({}));
    const items = Array.isArray(d && d.memories) ? d.memories : [];
    box.innerHTML = items.length
      ? items.map(m => '<div style="margin:6px 0;padding:6px;border-left:2px solid var(--asp);background:rgba(0,0,0,0.12)">' + __esc(String(m || '')) + '</div>').join('')
      : '<span style="color:var(--text-dim)">No matches.</span>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Search failed</span>';
  }
};

window.runElasticsearchLearningSearch = async function runElasticsearchLearningSearch() {
  const q = String(document.getElementById('es-learning-search')?.value || '').trim();
  const box = document.getElementById('es-learning-results');
  if (!box) return;
  if (!q) { box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Enter a keyword query.</span>'; return; }
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/elasticsearch/search?q=' + encodeURIComponent(q) + '&limit=20');
    const d = await r.json().catch(() => ({}));
    const hits = Array.isArray(d && d.hits) ? d.hits : [];
    box.innerHTML = hits.length
      ? hits.map(h => '<div style="margin:6px 0"><strong>' + __esc(String(h.title || h.id || 'hit')) + '</strong><div style="color:var(--text-dim);font-size:0.68rem">' + __esc(String(h.snippet || h.content || '')) + '</div></div>').join('')
      : '<span style="color:var(--text-dim)">' + __esc(String((d && d.error) || 'No hits')) + '</span>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Search failed</span>';
  }
};

window.refreshFileCheckpointsPanel = async function refreshFileCheckpointsPanel() {
  const box = document.getElementById('file-checkpoints-list');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/file_checkpoints?limit=40');
    const d = await r.json().catch(() => ({}));
    const items = Array.isArray(d && d.items) ? d.items : (Array.isArray(d && d.checkpoints) ? d.checkpoints : []);
    box.innerHTML = items.length
      ? items.slice(0, 40).map(c => {
        const id = __esc(String(c.id || c.checkpoint_id || ''));
        const p = __esc(String(c.path || c.filepath || ''));
        const ts = __esc(String(c.timestamp || c.created_at || ''));
        return '<div style="margin:6px 0;padding:6px;border:1px solid rgba(255,255,255,0.06);border-radius:6px;background:rgba(0,0,0,0.12)">' +
          '<div style="font-size:0.68rem;color:var(--text-dim)">' + ts + '</div>' +
          '<div style="font-size:0.72rem"><strong>' + p + '</strong></div>' +
          '<div style="font-size:0.62rem;color:var(--text-dim)">' + id + '</div>' +
          '</div>';
      }).join('')
      : '<span style="color:var(--text-dim)">No checkpoints yet.</span>';
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load checkpoints</span>';
  }
};

window.laylaRefreshExecutionPanels = async function laylaRefreshExecutionPanels() {
  // Exec trace
  try {
    const pre = document.getElementById('exec-trace-json');
    if (pre) pre.textContent = 'Loading…';
    const r = await fetch('/debug/state');
    const d = await r.json().catch(() => ({}));
    if (pre) pre.textContent = JSON.stringify(d && (d.snapshot || d), null, 2);
  } catch (_) {
    try { const pre = document.getElementById('exec-trace-json'); if (pre) pre.textContent = 'Could not load'; } catch (_) {}
  }
  // Coordinator + background tasks
  try {
    const box = document.getElementById('tasks-list-json');
    if (box) box.textContent = 'Loading…';
    const [r1, r2] = await Promise.all([
      fetch('/debug/tasks?limit=40').then(x => x.json().catch(() => ({}))),
      fetch('/agent/tasks').then(x => x.json().catch(() => ({}))),
    ]);
    const persisted = Array.isArray(r1 && r1.tasks) ? r1.tasks : [];
    const bg = Array.isArray(r2 && r2.tasks) ? r2.tasks : [];
    if (!box) return;
    const rows = [];
    if (bg.length) {
      rows.push('<div style="margin-bottom:6px"><strong>Background tasks</strong></div>');
      rows.push(bg.slice(0, 25).map(t => {
        const id = __esc(String(t.task_id || t.id || ''));
        const st = __esc(String(t.status || ''));
        const goal = __esc(String(t.goal || '').slice(0, 140));
        const canCancel = (String(t.status || '').toLowerCase() === 'running' || String(t.status || '').toLowerCase() === 'queued');
        return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06)">' +
          '<div><strong>' + st + '</strong> <span style="color:var(--text-dim)">' + id.slice(0, 10) + '</span></div>' +
          (goal ? ('<div style="color:var(--text-dim)">' + goal + '</div>') : '') +
          (canCancel ? ('<button type="button" class="approve-btn" style="margin-top:4px" onclick="cancelBackgroundTask(' + JSON.stringify(String(t.task_id || t.id || '')) + ')">Cancel</button>') : '') +
          '</div>';
      }).join(''));
    }
    if (persisted.length) {
      rows.push('<div style="margin:10px 0 6px"><strong>Persisted coordinator tasks</strong></div>');
      rows.push('<div style="color:var(--text-dim)">' + __esc(JSON.stringify(persisted.slice(0, 20), null, 2)).replace(/\\n/g, '<br/>') + '</div>');
    }
    box.innerHTML = rows.length ? rows.join('') : '<span style="color:var(--text-dim)">No tasks</span>';
  } catch (_) {
    try { const box = document.getElementById('tasks-list-json'); if (box) box.textContent = 'Could not load'; } catch (_) {}
  }
};

window.cancelBackgroundTask = async function cancelBackgroundTask(taskId) {
  const tid = String(taskId || '').trim();
  if (!tid) return;
  try {
    await fetch('/agent/tasks/' + encodeURIComponent(tid), { method: 'DELETE' });
  } catch (_) {}
  try { laylaRefreshExecutionPanels(); } catch (_) {}
};
