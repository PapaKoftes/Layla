/**
 * components/perf.js — Performance utilities: IndexedDB cache, lazy panel init,
 * idle prefetch, modal focus trap, voice settings, aspect flash.
 *
 * Converted from js/layla-perf.js (top-level -> ES module).
 * Depends on: services/utils.js (showToast), core/state.js (appState)
 */

import { showToast } from '../services/utils.js';
import { appState } from '../core/state.js';

// ══════════════════════════════════════════════════════════════════════════════
// IndexedDB conversation cache
// ══════════════════════════════════════════════════════════════════════════════
const LAYLA_IDB_NAME = 'layla-ui';
const LAYLA_IDB_VERSION = 1;
const CONV_STORE = 'conversations';

let _idb = null;

function _openIdb() {
  if (_idb) return Promise.resolve(_idb);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(LAYLA_IDB_NAME, LAYLA_IDB_VERSION);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(CONV_STORE)) {
        const store = db.createObjectStore(CONV_STORE, { keyPath: 'id' });
        store.createIndex('updated_at', 'updated_at', { unique: false });
      }
    };
    req.onsuccess = e => { _idb = e.target.result; resolve(_idb); };
    req.onerror = () => reject(req.error);
  });
}

export async function laylaIdbSaveConv(conv) {
  if (!conv || !conv.id) return;
  try {
    const db = await _openIdb();
    const tx = db.transaction(CONV_STORE, 'readwrite');
    tx.objectStore(CONV_STORE).put(conv);
  } catch (_) {}
}

export async function laylaIdbGetConvs(limit) {
  try {
    const db = await _openIdb();
    return new Promise((resolve) => {
      const tx = db.transaction(CONV_STORE, 'readonly');
      const index = tx.objectStore(CONV_STORE).index('updated_at');
      const results = [];
      const req = index.openCursor(null, 'prev');
      req.onsuccess = e => {
        const cursor = e.target.result;
        if (!cursor || results.length >= (limit || 50)) { resolve(results); return; }
        results.push(cursor.value);
        cursor.continue();
      };
      req.onerror = () => resolve([]);
    });
  } catch (_) { return []; }
}

export async function laylaIdbDeleteConv(id) {
  try {
    const db = await _openIdb();
    const tx = db.transaction(CONV_STORE, 'readwrite');
    tx.objectStore(CONV_STORE).delete(id);
  } catch (_) {}
}

// ══════════════════════════════════════════════════════════════════════════════
// Lazy panel initialization
// ══════════════════════════════════════════════════════════════════════════════
const _panelInitMap = {
  'workspace': () => {
    try {
      if (typeof window.laylaMemBrowse === 'function' && !window._memBrowseInit) {
        window._memBrowseInit = true;
        window.laylaMemBrowse(0);
      }
    } catch (_) {}
  },
  'artifacts': () => {
    try {
      if (typeof window.laylaArtifactsScan === 'function' && !window._artifactScanInit) {
        window._artifactScanInit = true;
        window.laylaArtifactsScan();
      }
    } catch (_) {}
  },
};

// ══════════════════════════════════════════════════════════════════════════════
// Aspect switch glow flash
// ══════════════════════════════════════════════════════════════════════════════
export function laylaAspectFlash(el) {
  if (!el) return;
  el.classList.remove('asp-switch-flash');
  void el.offsetWidth; // reflow to restart animation
  el.classList.add('asp-switch-flash');
  setTimeout(() => el.classList.remove('asp-switch-flash'), 600);
}

// ══════════════════════════════════════════════════════════════════════════════
// Keyboard trap for modals
// ══════════════════════════════════════════════════════════════════════════════
export function laylaModalTrap(overlay) {
  if (!overlay) return;
  const focusable = overlay.querySelectorAll(
    'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])'
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  first.focus();
  overlay.addEventListener('keydown', function trapKey(e) {
    if (e.key === 'Escape') {
      overlay.style.display = 'none';
      overlay.removeEventListener('keydown', trapKey);
      return;
    }
    if (e.key !== 'Tab') return;
    if (e.shiftKey) {
      if (document.activeElement === first) { last.focus(); e.preventDefault(); }
    } else {
      if (document.activeElement === last) { first.focus(); e.preventDefault(); }
    }
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// Voice settings persistence
// ══════════════════════════════════════════════════════════════════════════════
export function laylaVoiceSpeedChange(val) {
  const n = parseFloat(val);
  if (!Number.isFinite(n)) return;
  window._laylaVoiceSpeed = n;
  try { localStorage.setItem('layla_voice_speed', String(n)); } catch (_) {}
  const el = document.getElementById('voice-speed-display');
  if (el) el.textContent = n.toFixed(1) + '×';
}

export function laylaVoiceVolumeChange(val) {
  const n = parseFloat(val);
  if (!Number.isFinite(n)) return;
  window._laylaVoiceVolume = n;
  try { localStorage.setItem('layla_voice_volume', String(n)); } catch (_) {}
  const el = document.getElementById('voice-volume-display');
  if (el) el.textContent = Math.round(n * 100) + '%';
}

export async function laylaVoicePreview() {
  const asp = appState.get('aspect.current') || 'morrigan';
  const samples = {
    morrigan: 'Directive received. Processing now.',
    nyx: 'The threads align. What do you seek?',
    echo: 'I remember everything. How can I help?',
    eris: 'Oh this is going to be fun!',
    cassandra: 'I see seventeen failure modes. Want the list?',
    lilith: 'Power has a price. Are you certain?',
  };
  const text = samples[asp] || samples.morrigan;
  try {
    if (typeof window.speakText === 'function') await window.speakText(text);
  } catch (_) {}
}

// ══════════════════════════════════════════════════════════════════════════════
// Artifacts auto-scan preference
// ══════════════════════════════════════════════════════════════════════════════
export function laylaArtifactsAutoScan() {
  return localStorage.getItem('layla_artifacts_autoscan') !== 'false';
}

export function laylaToggleArtifactsAutoScan(val) {
  const enabled = val !== undefined ? !!val : localStorage.getItem('layla_artifacts_autoscan') !== 'false';
  localStorage.setItem('layla_artifacts_autoscan', (!enabled).toString());
  const cb = document.getElementById('artifacts-autoscan-toggle');
  if (cb) cb.checked = !enabled;
}

// ══════════════════════════════════════════════════════════════════════════════
// Init — called from main.js
// ══════════════════════════════════════════════════════════════════════════════
export function initPerf() {
  // Lazy panel init on tab click
  document.addEventListener('click', e => {
    const tab = e.target.closest('.rcp-tab[data-rcp]');
    if (!tab) return;
    const panel = tab.getAttribute('data-rcp');
    const init = _panelInitMap[panel];
    if (init) { try { init(); } catch (_) {} }
  }, true);

  // Patch conversation list refresh to sync to IDB
  const _origRefreshConvs = window.refreshConversationsPanel || window.laylaLoadConversations;
  if (typeof _origRefreshConvs === 'function') {
    const _patched = async function () {
      const result = await _origRefreshConvs.apply(this, arguments);
      try {
        const res = await fetch('/conversations?limit=50');
        if (res.ok) {
          const data = await res.json();
          const convs = data.conversations || data.items || [];
          convs.forEach(c => laylaIdbSaveConv(c));
        }
      } catch (_) {}
      return result;
    };
    if (window.refreshConversationsPanel) window.refreshConversationsPanel = _patched;
    if (window.laylaLoadConversations) window.laylaLoadConversations = _patched;
  }

  // Modal focus trap for plan-viz and artifact-edit overlays
  const planVizOverlay = document.getElementById('plan-viz-overlay');
  if (planVizOverlay) {
    const observer = new MutationObserver(muts => {
      muts.forEach(m => {
        if (m.type === 'attributes' && m.attributeName === 'style') {
          if (planVizOverlay.style.display === 'flex') laylaModalTrap(planVizOverlay);
        }
      });
    });
    observer.observe(planVizOverlay, { attributes: true });
  }

  const artOverlay = document.getElementById('artifact-edit-overlay');
  if (artOverlay) {
    const observer = new MutationObserver(muts => {
      muts.forEach(m => {
        if (m.type === 'attributes' && m.attributeName === 'style') {
          if (artOverlay.style.display === 'flex') laylaModalTrap(artOverlay);
        }
      });
    });
    observer.observe(artOverlay, { attributes: true });
  }

  // Voice settings restore
  try {
    const speed = parseFloat(localStorage.getItem('layla_voice_speed') || '1.0');
    const vol   = parseFloat(localStorage.getItem('layla_voice_volume') || '1.0');
    window._laylaVoiceSpeed = speed;
    window._laylaVoiceVolume = vol;
    const speedEl = document.getElementById('voice-speed-range');
    if (speedEl) { speedEl.value = speed; laylaVoiceSpeedChange(speed); }
    const volEl = document.getElementById('voice-volume-range');
    if (volEl) { volEl.value = vol; laylaVoiceVolumeChange(vol); }
  } catch (_) {}

  // Idle prefetch health endpoint
  if ('requestIdleCallback' in window) {
    requestIdleCallback(() => {
      fetch('/health', { method: 'GET' }).catch(() => {});
    }, { timeout: 3000 });
  } else {
    setTimeout(() => { fetch('/health', { method: 'GET' }).catch(() => {}); }, 2000);
  }
}
