/**
 * components/models.js — Models & Kits manager (persistent control surface).
 *
 * Surfaces the model capability that previously lived ONLY in the first-run
 * setup wizard, so a model/kit can be browsed, downloaded, and switched at any
 * time from the running app. Reuses the existing backend endpoints — no new
 * server code:
 *   GET  /setup_status   → installed models (available_models) + active + hardware
 *   GET  /setup/models   → downloadable catalog + hardware recommendation
 *   GET  /setup/download → SSE download progress (also writes model_filename)
 *   POST /settings       → { model_filename } switches the active model
 *
 * Buttons use the data-action delegation router (core/actions.js); rows are
 * rendered dynamically and resolved by index against module-local arrays so no
 * filename ever has to round-trip through a data-arg attribute.
 */

import { escapeHtml, showToast, laylaConfirm } from '../services/utils.js';

// ── State ─────────────────────────────────────────────────────────────────────
let _installed = [];   // installed .gguf filenames (from /setup_status)
let _catalog = [];     // downloadable catalog entries (from /setup/models)
let _active = '';      // currently-configured model filename
let _es = null;        // active download EventSource

function _basename(p) {
  return String(p || '').replace(/\\/g, '/').split('/').pop().trim();
}

function _stopStream() {
  try { if (_es) { _es.close(); _es = null; } } catch (_) {}
}

// ── Open / close ───────────────────────────────────────────────────────────────
export function openModelsPanel() {
  const ov = document.getElementById('models-overlay');
  if (!ov) return;
  ov.classList.add('visible');
  refreshModelsPanel();
}

export function closeModelsPanel() {
  _stopStream();
  const ov = document.getElementById('models-overlay');
  if (ov) ov.classList.remove('visible');
}

// ── Load + render ──────────────────────────────────────────────────────────────
export async function refreshModelsPanel() {
  const loadEl = document.getElementById('models-loading');
  const bodyEl = document.getElementById('models-body');
  if (loadEl) { loadEl.style.display = 'block'; loadEl.textContent = 'Loading…'; }
  if (bodyEl) bodyEl.style.display = 'none';

  let status = null, models = null;
  try {
    const [sRes, mRes] = await Promise.all([
      fetch('/setup_status').then(r => r.json()).catch(() => null),
      fetch('/setup/models').then(r => r.json()).catch(() => null),
    ]);
    status = sRes; models = mRes;
  } catch (_) { /* handled below */ }

  if (!status && !models) {
    if (loadEl) {
      loadEl.style.display = 'block';
      loadEl.innerHTML = 'Could not load models. Is Layla running?' +
        ' <button type="button" class="tab-btn" style="margin-left:8px" data-action="refreshModelsPanel">Retry</button>';
    }
    return;
  }

  _installed = (status && Array.isArray(status.available_models)) ? status.available_models : [];
  _active = _basename((status && (status.resolved_model || status.model_filename)) || '');
  _catalog = (models && Array.isArray(models.catalog)) ? models.catalog : [];

  _renderHardware(status, models);
  _renderInstalled();
  _renderCatalog(models);

  if (loadEl) loadEl.style.display = 'none';
  if (bodyEl) bodyEl.style.display = 'block';
}

function _renderHardware(status, models) {
  const el = document.getElementById('models-hw');
  if (!el) return;
  const hw = (status && status.hardware) || {};
  const lines = [];
  if (hw.ram_gb != null) lines.push('RAM ~' + hw.ram_gb + ' GB');
  if (hw.gpu_vendor && hw.gpu_vendor !== 'none') {
    lines.push('GPU ' + hw.gpu_vendor + (hw.vram_gb != null ? ' (~' + hw.vram_gb + ' GB VRAM)' : ''));
  } else {
    lines.push('CPU inference (no GPU detected)');
  }
  const rec = (models && models.recommended_key) ? models.recommended_key : '';
  const suggestion = (models && models.suggestion) || hw.suggestion || '';
  let html = '<span class="models-hw-chips">' +
    lines.map(l => '<span class="models-chip">' + escapeHtml(l) + '</span>').join('') + '</span>';
  if (rec) html += '<div class="hint" style="margin-top:6px">Recommended for your hardware: <strong>' + escapeHtml(rec) + '</strong></div>';
  if (suggestion) html += '<div class="hint">' + escapeHtml(suggestion) + '</div>';
  el.innerHTML = html;
}

function _renderInstalled() {
  const el = document.getElementById('models-installed');
  if (!el) return;
  if (!_installed.length) {
    el.innerHTML = '<div class="hint">No models installed yet — pick one to download below.</div>';
    return;
  }
  el.innerHTML = _installed.map((name, i) => {
    const base = _basename(name);
    const isActive = base.toLowerCase() === _active.toLowerCase();
    return '<div class="models-row' + (isActive ? ' models-row-active' : '') + '">' +
      '<span class="models-row-name">' + escapeHtml(base) + '</span>' +
      (isActive
        ? '<span class="models-badge">active</span>'
        : '<button type="button" class="models-btn" data-action="switchActiveModel" data-arg="' + i + '">Use</button>') +
      '</div>';
  }).join('');
}

function _renderCatalog(models) {
  const el = document.getElementById('models-catalog');
  if (!el) return;
  if (!_catalog.length) {
    el.innerHTML = '<div class="hint">Catalog unavailable.</div>';
    return;
  }
  const ramCap = (models && typeof models.ram_gb === 'number') ? models.ram_gb : null;
  el.innerHTML = _catalog.map((m, i) => {
    const name = m.name || m.key || ('model ' + i);
    const viable = m.viable !== false;
    const flags = [];
    if (m.recommended) flags.push('<span class="models-badge">recommended</span>');
    if (!viable) flags.push('<span class="models-badge models-badge-warn">heavy</span>');
    const ram = (m.ram_gb != null) ? (' · needs ~' + m.ram_gb + ' GB') : '';
    const hasUrl = !!m.url;
    return '<div class="models-row models-catalog-row" style="opacity:' + (viable ? '1' : '0.6') + '">' +
      '<div class="models-row-main">' +
        '<span class="models-row-name">' + escapeHtml(name) + '</span> ' + flags.join('') +
        '<div class="hint">' + escapeHtml(m.desc || '') + escapeHtml(ram) + '</div>' +
      '</div>' +
      (hasUrl
        ? '<button type="button" class="models-btn" data-action="downloadCatalogModel" data-arg="' + i + '">Download</button>'
        : '<span class="hint">manual</span>') +
      '</div>';
  }).join('') +
  (ramCap != null ? '<div class="hint" style="margin-top:8px">Viability based on detected ~' + ramCap + ' GB RAM.</div>' : '');
}

// ── Switch active model ────────────────────────────────────────────────────────
export async function switchActiveModel(idx) {
  const name = _installed[idx];
  if (!name) return;
  try {
    const res = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_filename: _basename(name) }),
    });
    if (res.ok) {
      showToast('Active model set — restart inference if a model is loaded');
      _active = _basename(name);
      _renderInstalled();
    } else {
      showToast('Could not switch model');
    }
  } catch (_) {
    showToast('Switch failed');
  }
}

// ── Download from catalog (SSE) ────────────────────────────────────────────────
export async function downloadCatalogModel(idx) {
  const m = _catalog[idx];
  if (!m || !m.url) { showToast('No download URL for this model'); return; }
  if (m.viable === false &&
      !(await laylaConfirm('This model may exceed your detected RAM. Download anyway?'))) {
    return;
  }
  _stopStream();
  const prog = document.getElementById('models-progress');
  const bar = document.getElementById('models-progress-bar');
  const label = document.getElementById('models-progress-label');
  if (prog) prog.style.display = 'block';
  if (bar) bar.style.width = '0%';
  if (label) label.textContent = 'Starting download…';

  let qs = '/setup/download?url=' + encodeURIComponent(m.url);
  if (m.filename) qs += '&filename=' + encodeURIComponent(m.filename);
  try {
    _es = new EventSource(qs);
  } catch (_) { showToast('Download could not start'); return; }

  _es.onmessage = (ev) => {
    let d = null;
    try { d = JSON.parse(ev.data); } catch (_) { return; }
    if (d.error) {
      _stopStream();
      if (label) label.textContent = 'Error: ' + d.error;
      showToast('Download failed');
      return;
    }
    if (typeof d.pct === 'number' && bar) bar.style.width = d.pct + '%';
    if (label) {
      label.textContent = (typeof d.dl_mb === 'number' && typeof d.tot_mb === 'number')
        ? ('Downloading… ' + d.pct + '% (' + d.dl_mb + ' / ' + d.tot_mb + ' MB)')
        : 'Downloading…';
    }
    if (d.done) {
      _stopStream();
      if (label) label.textContent = 'Done — ' + (d.filename || 'model saved');
      showToast('Model ready');
      setTimeout(() => { refreshModelsPanel(); }, 500);
    }
  };
  _es.onerror = () => {
    _stopStream();
    if (label) label.textContent = 'Connection lost — press Refresh and retry';
  };
}

// ── Init (no-op; data loads lazily on open) ────────────────────────────────────
export function initModels() { /* lazy: refreshModelsPanel() runs on open */ }
