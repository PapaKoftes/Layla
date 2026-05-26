/**
 * components/bootstrap.js — Core bootstrap: remote auth, input binding, shortcuts, panels.
 *
 * Converted from js/layla-bootstrap.js (IIFE -> ES module).
 * No module dependencies — this is foundational infrastructure.
 *
 * Contains:
 *   - Fetch monkey-patch for remote (non-local) Authorization headers
 *   - triggerSend() fallback for sending messages
 *   - bindChatInputNow() — Enter-to-send + send button
 *   - Keyboard shortcuts (Ctrl+/, Ctrl+K, Escape)
 *   - Right panel tab switching (showMainPanel / showWorkspaceSubtab)
 *   - MutationObserver badge syncing (header → topbar)
 *   - Aspect button click delegation
 *   - Phase 4B auto-aspect from /operator/profile
 */

// ── Remote auth helpers ────────────────────────────────────────────────────
function _isNonLocalHost() {
  try {
    const h = location.hostname || '';
    if (!h) return false;
    return h !== '127.0.0.1' && h !== 'localhost';
  } catch (_) { return false; }
}

function _remoteAuthHeader() {
  try {
    const k = localStorage.getItem('layla_remote_api_key') || '';
    if (!k) return null;
    return 'Bearer ' + k;
  } catch (_) { return null; }
}

// ── Fetch monkey-patch for remote auth ─────────────────────────────────────
function _patchFetchForRemoteAuth() {
  try {
    const _nativeFetch = typeof fetch !== 'undefined' ? fetch.bind(window) : null;
    if (_nativeFetch) {
      window.fetch = function (input, init) {
        init = init || {};
        const u = typeof input === 'string' ? input : (input && input.url) || '';
        if (_isNonLocalHost() && u.charAt(0) === '/') {
          const h = new Headers(init.headers || undefined);
          const bearer = _remoteAuthHeader();
          if (bearer && !h.has('Authorization')) h.set('Authorization', bearer);
          init.headers = h;
        }
        return _nativeFetch(input, init);
      };
    }
  } catch (_) {}
}

// ── triggerSend fallback ───────────────────────────────────────────────────
export function triggerSend() {
  try {
    if (typeof window.send === 'function') { window.send(); return; }
    const inp = document.getElementById('msg-input');
    if (!inp || !inp.value || !inp.value.trim()) return;
    const msg = inp.value.trim();
    const aspect = (typeof window.currentAspect !== 'undefined') ? window.currentAspect : 'morrigan';
    const chat = document.getElementById('chat');
    inp.value = '';
    if (chat) {
      const you = document.createElement('div');
      you.className = 'msg msg-you';
      you.innerHTML = '<div class="msg-label">You</div><div class="msg-bubble">' +
        String(msg).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
      chat.appendChild(you);
    }
    let conv = '';
    let wp = '';
    let aw = false;
    let ar = false;
    try {
      conv = (typeof localStorage !== 'undefined') ? (localStorage.getItem('layla_current_conversation_id') || '') : '';
      const wpe = document.getElementById('workspace-path');
      wp = (wpe && wpe.value || '').trim();
      aw = !!(document.getElementById('allow-write') && document.getElementById('allow-write').checked);
      ar = !!(document.getElementById('allow-run') && document.getElementById('allow-run').checked);
    } catch (_) {}
    fetch('/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        aspect_id: aspect,
        show_thinking: false,
        allow_write: aw,
        allow_run: ar,
        stream: false,
        workspace_root: wp,
        conversation_id: conv,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        const el = document.getElementById('chat');
        if (el && d && d.response) {
          const div = document.createElement('div');
          div.className = 'msg msg-layla';
          div.innerHTML = '<div class="msg-label">Layla</div><div class="msg-bubble">' +
            String(d.response).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
          el.appendChild(div);
          el.scrollTop = el.scrollHeight;
        }
      })
      .catch(function (e) {
        if (chat) {
          const err = document.createElement('div');
          err.className = 'msg msg-layla';
          const emsg = (e && (e.message || '').toLowerCase()) || '';
          const friendly = (emsg.indexOf('fetch') !== -1 || emsg.indexOf('network') !== -1 || emsg.indexOf('load failed') !== -1)
            ? "Can't reach Layla. Is the server running at http://127.0.0.1:8000?"
            : ('Error: ' + String(e && e.message || e));
          err.innerHTML = '<div class="msg-label">Layla</div><div class="msg-bubble">' +
            String(friendly).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
          chat.appendChild(err);
          chat.scrollTop = chat.scrollHeight;
        }
      });
  } catch (e) { console.warn('[Layla] triggerSend', e); }
}

// ── Bind chat input ────────────────────────────────────────────────────────
export function bindChatInputNow() {
  try {
    document.addEventListener('keydown', function (e) {
      if ((e.key !== 'Enter' && e.keyCode !== 13) || e.shiftKey) return;
      const active = document.activeElement;
      if (!active || active.id !== 'msg-input') return;
      const dd = document.getElementById('mention-dropdown');
      if (dd && dd.children.length > 0) return;
      e.preventDefault();
      e.stopPropagation();
      if (typeof window.triggerSend === 'function') window.triggerSend();
    }, true);
    const sendBtn = document.getElementById('send-btn');
    if (sendBtn) {
      sendBtn.removeAttribute('disabled');
      sendBtn.disabled = false;
      sendBtn.addEventListener('click', function () {
        if (typeof window.triggerSend === 'function') window.triggerSend();
      });
    }
  } finally {
    /* contract: Enter-to-send + send button rebound for UI repair tests */
  }
}

// ── Keyboard shortcuts sheet ───────────────────────────────────────────────
export function showKeyboardShortcutsSheet() {
  const el = document.getElementById('keyboard-shortcuts-sheet');
  if (!el) return;
  el.style.display = 'flex';
}

export function hideKeyboardShortcutsSheet() {
  const el = document.getElementById('keyboard-shortcuts-sheet');
  if (!el) return;
  el.style.display = 'none';
}

// ── Overflow menu ──────────────────────────────────────────────────────────
export function toggleHeaderOverflow() {
  const menu = document.getElementById('header-overflow-menu');
  if (!menu) return;
  const show = menu.style.display === 'none' || !menu.style.display;
  menu.style.display = show ? 'block' : 'none';
  if (show) {
    const _closer = function (ev) {
      if (!menu.contains(ev.target) && ev.target.id !== 'header-overflow-btn') {
        menu.style.display = 'none';
        document.removeEventListener('click', _closer, true);
      }
    };
    setTimeout(function () { document.addEventListener('click', _closer, true); }, 0);
  }
}

// ── Right panel tab switching ──────────────────────────────────────────────
const _rcpAliases = { growth: 'status', cluster: 'status' };

function _applyRcpMain(main) {
  main = _rcpAliases[main] || main;
  const root = document.getElementById('layla-right-panel');
  if (!root || !main) return;
  const tabs = root.querySelectorAll('.rcp-tab');
  for (let i = 0; i < tabs.length; i++) {
    const b = tabs[i];
    const on = b.getAttribute('data-rcp') === main;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  }
  const pages = root.querySelectorAll('.rcp-page');
  for (let j = 0; j < pages.length; j++) {
    const p = pages[j];
    const onp = p.getAttribute('data-rcp') === main;
    p.classList.toggle('active', onp);
    p.setAttribute('aria-hidden', onp ? 'false' : 'true');
    try { p.removeAttribute('hidden'); } catch (_) {}
  }
}

function _applyRcpWs(sub) {
  _applyRcpMain('workspace');
  const root = document.getElementById('layla-right-panel');
  const ws = root && root.querySelector('.rcp-page[data-rcp="workspace"]');
  if (!ws || !sub) return;
  const subs = ws.querySelectorAll('.rcp-subtab');
  for (let a = 0; a < subs.length; a++) {
    const sb = subs[a];
    sb.classList.toggle('active', sb.getAttribute('data-rcp-sub') === sub);
  }
  const panes = ws.querySelectorAll('.rcp-subpage');
  for (let b = 0; b < panes.length; b++) {
    const pane = panes[b];
    pane.classList.toggle('active', pane.getAttribute('data-rcp-sub') === sub);
  }
}

export function showMainPanel(main) {
  _applyRcpMain(main);
  // Also open the overlay panel if not already open
  const rp = document.getElementById('layla-right-panel');
  const bd = document.getElementById('rp-backdrop');
  if (rp && !rp.classList.contains('rp-open')) {
    rp.classList.add('rp-open');
    if (bd) { bd.classList.add('visible'); bd.setAttribute('aria-hidden', 'false'); }
  }
  if (typeof window.__laylaRefreshAfterShowMainPanel === 'function') {
    try { window.__laylaRefreshAfterShowMainPanel(main); } catch (err) { console.warn('[Layla] refresh main panel', err); }
  }
}

export function showWorkspaceSubtab(sub) {
  _applyRcpWs(sub);
  if (typeof window.__laylaRefreshAfterWorkspaceSubtab === 'function') {
    try { window.__laylaRefreshAfterWorkspaceSubtab(sub); } catch (err) { console.warn('[Layla] refresh workspace sub', err); }
  }
}

// ── Init: set up all event listeners, observers, delegations ───────────────
export function initBootstrap() {
  // Patch fetch for remote auth
  _patchFetchForRemoteAuth();

  // Bind chat input (Enter-to-send + send button)
  bindChatInputNow();

  // Keyboard shortcuts
  document.addEventListener('keydown', function (e) {
    try {
      const k = (e.key || '').toLowerCase();
      // Ctrl+/ opens help sheet
      if ((e.ctrlKey || e.metaKey) && (k === '/' || e.code === 'Slash')) {
        e.preventDefault();
        e.stopPropagation();
        showKeyboardShortcutsSheet();
        return;
      }
      // Ctrl+K focuses the conversation search (spotlight-like)
      if ((e.ctrlKey || e.metaKey) && k === 'k') {
        e.preventDefault();
        e.stopPropagation();
        try { if (typeof window.toggleChatRailMobile === 'function') window.toggleChatRailMobile(); } catch (_) {}
        const s = document.getElementById('chat-rail-search');
        if (s) { s.focus(); if (s.select) s.select(); }
        return;
      }
      // Escape closes overlays
      if (k === 'escape') {
        hideKeyboardShortcutsSheet();
      }
    } catch (_) {}
  }, true);

  // Capture phase: right-panel tabs before any bubble-phase stopPropagation steals the click
  document.addEventListener('click', function (e) {
    const t = e.target;
    const rcpTab = t && t.closest && t.closest('#layla-right-panel .rcp-tab');
    if (rcpTab) {
      const rm = rcpTab.getAttribute('data-rcp');
      if (rm && typeof window.showMainPanel === 'function') window.showMainPanel(rm);
      return;
    }
    const rcpSub = t && t.closest && t.closest('#layla-right-panel .rcp-subtab');
    if (rcpSub) {
      const ws = rcpSub.getAttribute('data-rcp-sub');
      if (ws && typeof window.showWorkspaceSubtab === 'function') window.showWorkspaceSubtab(ws);
      return;
    }
  }, true);

  // Delegated click (bubble): aspect buttons
  document.addEventListener('click', function (e) {
    const t = e.target;
    const aspectBtn = t && t.closest && t.closest('.aspect-btn');
    if (aspectBtn) {
      if (typeof window.setAspect === 'function') {
        window.setAspect(aspectBtn.id ? aspectBtn.id.replace(/^btn-/, '') : '');
        return;
      }
      const id = (aspectBtn.id || '').replace(/^btn-/, '') || 'morrigan';
      window.currentAspect = id;
      document.querySelectorAll('.aspect-btn').forEach(function (b) {
        b.classList.remove('active');
        if (b.id === 'btn-' + id) b.classList.add('active');
      });
      const badge = document.getElementById('aspect-badge');
      if (badge) badge.textContent = id.toUpperCase();
    }
  }, false);

  // Sync hidden header badges → topbar badges via MutationObserver
  try {
    const _syncPairs = [
      ['header-system-status', 'topbar-system-status'],
      ['model-status-badge', 'topbar-model-status'],
      ['session-time', 'topbar-session-time'],
    ];
    const _syncObs = new MutationObserver(function (mutations) {
      mutations.forEach(function (m) {
        const srcId = m.target.id;
        for (let i = 0; i < _syncPairs.length; i++) {
          if (_syncPairs[i][0] === srcId) {
            const dst = document.getElementById(_syncPairs[i][1]);
            if (dst) { dst.textContent = m.target.textContent; dst.title = m.target.title || ''; }
            break;
          }
        }
      });
    });
    _syncPairs.forEach(function (pair) {
      const src = document.getElementById(pair[0]);
      if (src) _syncObs.observe(src, { childList: true, characterData: true, subtree: true });
    });
  } catch (_) {}

  // Escape key closes right panel overlay
  document.addEventListener('keydown', function (e) {
    if ((e.key || '').toLowerCase() === 'escape') {
      const rp = document.getElementById('layla-right-panel');
      if (rp && rp.classList.contains('rp-open')) {
        if (typeof window.closeRightPanel === 'function') window.closeRightPanel();
        e.stopPropagation();
      }
    }
  }, true);

  // Phase 4B: Auto-switch to default aspect from onboarding
  // MIGRATION NOTE: ES module health service also handles this via
  // profile:default-aspect bus event. Both paths are safe — the second
  // call is a no-op if the aspect is already set.
  try {
    fetch('/operator/profile')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        const defAspect = d && d.identity && d.identity.default_aspect;
        if (defAspect && typeof window.setAspect === 'function') {
          if (!window._aspectManuallySet) {
            window.setAspect(defAspect);
          }
        }
      })
      .catch(function () {});
  } catch (_) {}
}
