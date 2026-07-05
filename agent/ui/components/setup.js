/**
 * components/setup.js — First-run setup overlay (model download, workspace).
 *
 * Converted from js/layla-setup.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast, _dbg, laylaConfirm),
 *             components/aspect.js (highlightAspectSidebar),
 *             services/api.js (fetchWithTimeout via window compat)
 */

import { escapeHtml, showToast, _dbg, laylaConfirm } from '../services/utils.js';
import { highlightAspectSidebar } from './aspect.js';

// ── State ───────────────────────────────────────────────────────────────────
let _setupSelectedModel = null;
let _setupEventSource = null;

function stopModelDownloadStream() {
  try {
    if (_setupEventSource) { _setupEventSource.close(); _setupEventSource = null; }
  } catch (_) {}
}

function _setupRefreshDownloadButton() {
  const btn = document.getElementById('setup-download-btn');
  if (!btn) return;
  const customEl = document.getElementById('setup-custom-url');
  const custom = (customEl && customEl.value || '').trim();
  btn.disabled = !((_setupSelectedModel && _setupSelectedModel.url) || custom);
}

export async function saveSetupWorkspaceIfNeeded() {
  const inp = document.getElementById('setup-workspace-path');
  const path = (inp && inp.value || '').trim();
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
  const el = document.getElementById('setup-hw');
  if (!el) return;
  if (!hw || !Object.keys(hw).length) {
    el.textContent = 'Hardware details unavailable — you can tune the model in Settings after setup.';
    return;
  }
  const lines = [];
  if (hw.ram_gb != null) lines.push('RAM: ~' + hw.ram_gb + ' GB');
  if (hw.gpu_vendor && hw.gpu_vendor !== 'none') {
    lines.push('GPU: ' + hw.gpu_vendor + (hw.vram_gb != null ? ' (~' + hw.vram_gb + ' GB VRAM)' : ''));
  } else lines.push('GPU: not detected (CPU inference)');
  if (hw.suggestion) lines.push('Hint: ' + hw.suggestion);
  el.innerHTML = lines.map(l => escapeHtml(l)).join('<br>');
}

function renderSetupExistingModels(list) {
  const wrap = document.getElementById('setup-existing-models');
  const lst = document.getElementById('setup-existing-list');
  if (!wrap || !lst) return;
  if (!list || !list.length) { wrap.style.display = 'none'; return; }
  wrap.style.display = 'block';
  lst.innerHTML = list.map(name => {
    return '<button type="button" class="tab-btn setup-model-pick" style="margin:4px 4px 4px 0" data-filename="' + String(name).replace(/"/g, '&quot;') + '">Use ' + escapeHtml(String(name)) + '</button>';
  }).join(' ');
  lst.querySelectorAll('.setup-model-pick').forEach(btn => {
    btn.onclick = () => useExistingSetupModel(btn.getAttribute('data-filename'));
  });
}

async function useExistingSetupModel(filename) {
  await saveSetupWorkspaceIfNeeded();
  stopModelDownloadStream();
  try {
    const res = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_filename: filename }),
    });
    if (res.ok) {
      const o = document.getElementById('setup-overlay');
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
  const msg = message || 'Could not load catalog';
  container.innerHTML =
    '<div style="color:var(--text-dim);font-size:0.8rem;line-height:1.45">' + escapeHtml(msg) + '</div>' +
    '<button type="button" class="tab-btn" style="margin-top:10px" onclick="loadSetupCatalog()">Retry</button>';
}

export async function loadSetupCatalog() {
  const container = document.getElementById('setup-model-list');
  if (!container) return;
  container.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem">Loading catalog…</div>';
  try {
    const res = await window.fetchWithTimeout('/setup/models', {}, 20000);
    const data = await res.json().catch(() => null);
    if (!res.ok || !data || !data.ok || !Array.isArray(data.catalog)) {
      _renderSetupCatalogError(container, (data && data.error) || window.formatAgentError(res, data || {}));
      return;
    }
    container.innerHTML = '';
    data.catalog.forEach(m => {
      const div = document.createElement('div');
      div.className = 'setup-catalog-row';
      div.setAttribute('data-match-name', String(m.name || '').toLowerCase());
      div.setAttribute('data-match-key', String(m.key || '').toLowerCase());
      div.setAttribute('data-match-file', String(m.filename || m.gguf_filename || '').toLowerCase());
      div.style.cssText = 'margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:6px;cursor:pointer;opacity:' + (m.viable ? '1' : '0.55');
      div.innerHTML = '<strong>' + escapeHtml(m.name || '') + '</strong> <span style="font-size:0.7rem;color:var(--text-dim)">' + (m.recommended ? '(recommended) ' : '') + (m.viable ? '' : ' — may need more RAM') + '</span><br><span style="font-size:0.72rem;color:var(--text-dim)">' + escapeHtml(m.desc || '') + '</span>';
      div.onclick = async () => {
        if (!m.viable && !(await laylaConfirm('This model may exceed your detected RAM. Download anyway?'))) return;
        _setupSelectedModel = m;
        container.querySelectorAll('.setup-catalog-row').forEach(el => { el.style.outline = ''; });
        div.style.outline = '2px solid var(--asp)';
        _setupRefreshDownloadButton();
      };
      container.appendChild(div);
    });
    _setupRefreshDownloadButton();
  } catch (e) {
    const timedOut = e && e.name === 'AbortError';
    _renderSetupCatalogError(container, timedOut ? 'Catalog request timed out.' : 'Failed to load catalog');
  }
}

async function prefillSetupWorkspaceFromSettings(statusPayload) {
  const inp = document.getElementById('setup-workspace-path');
  if (!inp || inp.getAttribute('data-user-edited') === '1') return;
  let sr = '';
  if (statusPayload && (statusPayload.sandbox_root || '').trim()) {
    sr = String(statusPayload.sandbox_root || '').trim();
  }
  if (!sr) {
    try {
      const r = await fetch('/settings');
      if (r.ok) {
        const cfg = await r.json();
        sr = (cfg.sandbox_root || '').trim();
      }
    } catch (_) {}
  }
  if (sr && !inp.value) inp.value = sr;
}

function trySelectSetupCatalogMatch(statusPayload) {
  if (!statusPayload) return;
  const want = String(statusPayload.resolved_model || statusPayload.model_filename || '').trim().toLowerCase();
  if (!want) return;
  const container = document.getElementById('setup-model-list');
  if (!container) return;
  container.querySelectorAll('.setup-catalog-row').forEach(div => {
    const fn = String(div.getAttribute('data-match-file') || '').toLowerCase();
    const nm = String(div.getAttribute('data-match-name') || '').toLowerCase();
    const key = String(div.getAttribute('data-match-key') || '').toLowerCase();
    if (fn === want || fn.indexOf(want) >= 0 || want.indexOf(fn) >= 0 || nm.indexOf(want) >= 0 || key === want) {
      div.click();
    }
  });
}

function _renderSetupStatusError(res, body, err) {
  const overlay = document.getElementById('setup-overlay');
  if (overlay) overlay.classList.add('visible');
  const el = document.getElementById('setup-hw');
  if (!el) return;
  const msg = err && err.name === 'AbortError'
    ? 'Setup status timed out. Check that Layla is responding.'
    : res
      ? window.formatAgentError(res, body || {})
      : 'Could not reach Layla. Is the server running?';
  el.innerHTML =
    '<span style="color:var(--text-dim)">' + escapeHtml(msg) + '</span><br>' +
    '<button type="button" class="tab-btn" style="margin-top:8px" onclick="checkSetupStatus()">Retry</button>';
}

export async function checkSetupStatus() {
  const overlay = document.getElementById('setup-overlay');
  try {
    const res = await window.fetchWithTimeout('/setup_status', {}, 15000);
    const s = await res.json().catch(() => null);
    if (!res.ok || !s) { _renderSetupStatusError(res, s, null); return; }
    if (s.ready && s.model_found) {
      if (overlay) overlay.classList.remove('visible');
      maybeStartSetupProfiles();
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
    showToast('Setup check failed — is Layla running?');
  }
}

// ── Model download ──────────────────────────────────────────────────────────
export function startModelDownload() {
  let url = '';
  let filename = '';
  if (_setupSelectedModel && _setupSelectedModel.url) {
    url = _setupSelectedModel.url;
    filename = _setupSelectedModel.filename || '';
  } else {
    const customEl = document.getElementById('setup-custom-url');
    url = (customEl && customEl.value || '').trim();
  }
  if (!url) { showToast('Select a model or paste a .gguf URL'); return; }
  stopModelDownloadStream();
  const bar = document.getElementById('setup-progress-bar');
  const label = document.getElementById('setup-progress-label');
  const doneMsg = document.getElementById('setup-done-msg');
  const retryBtn = document.getElementById('setup-retry-btn');
  if (bar) bar.style.width = '0%';
  if (label) label.textContent = 'Starting download…';
  if (doneMsg) doneMsg.textContent = '';
  if (retryBtn) retryBtn.style.display = 'none';

  saveSetupWorkspaceIfNeeded().then(() => {
    let qs = '/setup/download?url=' + encodeURIComponent(url);
    if (filename) qs += '&filename=' + encodeURIComponent(filename);
    try {
      _setupEventSource = new EventSource(qs);
    } catch (_) { showToast('Download could not start'); return; }
    _setupEventSource.onmessage = ev => {
      try {
        const d = JSON.parse(ev.data);
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
          setTimeout(() => {
            const o = document.getElementById('setup-overlay');
            if (o) o.classList.remove('visible');
            checkSetupStatus();
          }, 400);
        }
      } catch (_) {}
    };
    _setupEventSource.onerror = () => {
      stopModelDownloadStream();
      if (label) label.textContent = 'Connection lost — try Retry';
      if (retryBtn) retryBtn.style.display = '';
    };
  });
}

export function retryModelDownload() {
  const retryBtn = document.getElementById('setup-retry-btn');
  if (retryBtn) retryBtn.style.display = 'none';
  startModelDownload();
}

export function dismissSetupOverlay(isSkip) {
  const o = document.getElementById('setup-overlay');
  if (o) o.classList.remove('visible');
  if (isSkip === true) saveSetupWorkspaceIfNeeded();
  maybeStartSetupProfiles();
}

/**
 * First-run: present the intent-driven profile wizard (pick a use-case → enable only the
 * features you need → write a fitting startup default) BEFORE the mini onboarding tour.
 * Shown once (localStorage marker); reconfigure later via ⌘K → "Set up / reconfigure".
 * Falls through to the tour if already configured or the wizard isn't available.
 */
function maybeStartSetupProfiles() {
  let done = false;
  try { done = localStorage.getItem('layla_setup_profiles_v1_done') === '1'; } catch (_) {}
  if (done || typeof window.openSetupProfiles !== 'function') { maybeStartOnboarding(); return; }
  const onClosed = () => {
    window.removeEventListener('layla:setup-closed', onClosed);
    maybeStartOnboarding();
  };
  window.addEventListener('layla:setup-closed', onClosed);
  // BL-091: on the very first run, show the welcome + honesty card first — it hands off to the
  // profile wizard itself (its "set me up" button calls window.openSetupProfiles). If the welcome
  // was already seen, go straight to the wizard.
  try {
    if (typeof window.maybeShowWelcome === 'function' && window.maybeShowWelcome()) return;
  } catch (_) {}
  try { window.openSetupProfiles(); } catch (_) { window.removeEventListener('layla:setup-closed', onClosed); maybeStartOnboarding(); }
}

// ── Onboarding ──────────────────────────────────────────────────────────────
let _onboardingStep = 0;

function renderOnboardingStep() {
  const text = document.getElementById('onboarding-text');
  const nextBtn = document.getElementById('onboarding-next');
  const doneBtn = document.getElementById('onboarding-done');
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
    const ov = document.getElementById('onboarding-overlay');
    if (!ov) return;
    _onboardingStep = 0;
    renderOnboardingStep();
    ov.classList.add('visible');
  } catch (_) {}
}

export function onboardingNext() {
  _onboardingStep++;
  if (_onboardingStep > 2) _onboardingStep = 2;
  renderOnboardingStep();
}

export function dismissOnboarding() {
  const ov = document.getElementById('onboarding-overlay');
  if (ov) ov.classList.remove('visible');
  try { localStorage.setItem('layla_onboarding_v1_done', '1'); } catch (_) {}
  highlightAspectSidebar(false);
}
