(function() {
  'use strict';
  function __laylaIsNonLocalHost() {
    try {
      var h = location.hostname || '';
      if (!h) return false;
      return h !== '127.0.0.1' && h !== 'localhost';
    } catch (_) { return false; }
  }
  function __laylaRemoteAuthHeader() {
    try {
      var k = localStorage.getItem('layla_remote_api_key') || '';
      if (!k) return null;
      return 'Bearer ' + k;
    } catch (_) { return null; }
  }
  try {
    var _nativeFetch = typeof fetch !== 'undefined' ? fetch.bind(window) : null;
    if (_nativeFetch) {
      window.fetch = function(input, init) {
        init = init || {};
        var u = typeof input === 'string' ? input : (input && input.url) || '';
        if (__laylaIsNonLocalHost() && u.charAt(0) === '/') {
          var h = new Headers(init.headers || undefined);
          var bearer = __laylaRemoteAuthHeader();
          if (bearer && !h.has('Authorization')) h.set('Authorization', bearer);
          init.headers = h;
        }
        return _nativeFetch(input, init);
      };
    }
  } catch (_) {}
  window.currentAspect = window.currentAspect || 'morrigan';
  window.triggerSend = function triggerSend() {
    try {
      if (typeof window.send === 'function') { window.send(); return; }
      var inp = document.getElementById('msg-input');
      if (!inp || !inp.value || !inp.value.trim()) return;
      var msg = inp.value.trim();
      var aspect = (typeof window.currentAspect !== 'undefined') ? window.currentAspect : 'morrigan';
      var chat = document.getElementById('chat');
      inp.value = '';
      if (chat) {
        var you = document.createElement('div');
        you.className = 'msg msg-you';
        you.innerHTML = '<div class="msg-label">You</div><div class="msg-bubble">' + String(msg).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
        chat.appendChild(you);
      }
      var conv = '';
      var wp = '';
      var aw = false;
      var ar = false;
      try {
        conv = (typeof localStorage !== 'undefined') ? (localStorage.getItem('layla_current_conversation_id') || '') : '';
        var wpe = document.getElementById('workspace-path');
        wp = (wpe && wpe.value || '').trim();
        aw = !!(document.getElementById('allow-write') && document.getElementById('allow-write').checked);
        ar = !!(document.getElementById('allow-run') && document.getElementById('allow-run').checked);
      } catch (_) {}
      fetch('/agent', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        message: msg,
        aspect_id: aspect,
        show_thinking: false,
        allow_write: aw,
        allow_run: ar,
        stream: false,
        workspace_root: wp,
        conversation_id: conv,
      }) })
        .then(function(r) { return r.json(); })
        .then(function(d) {
          var el = document.getElementById('chat');
          if (el && d && d.response) {
            var div = document.createElement('div');
            div.className = 'msg msg-layla';
            div.innerHTML = '<div class="msg-label">Layla</div><div class="msg-bubble">' + String(d.response).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
            el.appendChild(div);
            el.scrollTop = el.scrollHeight;
          }
        })
        .catch(function(e) {
          if (chat) {
            var err = document.createElement('div');
            err.className = 'msg msg-layla';
            var msg = (e && (e.message || '').toLowerCase()) || '';
            var friendly = (msg.indexOf('fetch') !== -1 || msg.indexOf('network') !== -1 || msg.indexOf('load failed') !== -1)
              ? "Can't reach Layla. Is the server running at http://127.0.0.1:8000?"
              : ('Error: ' + String(e && e.message || e));
            err.innerHTML = '<div class="msg-label">Layla</div><div class="msg-bubble">' + String(friendly).replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
            chat.appendChild(err);
            chat.scrollTop = chat.scrollHeight;
          }
        });
    } catch (e) { console.warn('[Layla] triggerSend', e); }
  };
   function bindChatInputNow() {
    try {
      document.addEventListener('keydown', function (e) {
        if ((e.key !== 'Enter' && e.keyCode !== 13) || e.shiftKey) return;
        var active = document.activeElement;
        if (!active || active.id !== 'msg-input') return;
        var dd = document.getElementById('mention-dropdown');
        if (dd && dd.children.length > 0) return;
        e.preventDefault();
        e.stopPropagation();
        if (typeof window.triggerSend === 'function') window.triggerSend();
      }, true);
      var sendBtn = document.getElementById('send-btn');
      if (sendBtn) {
        sendBtn.removeAttribute('disabled');
        sendBtn.disabled = false;
        sendBtn.addEventListener('click', function () { if (typeof window.triggerSend === 'function') window.triggerSend(); });
      }
    } finally {
      /* contract: Enter-to-send + send button rebound for UI repair tests */
    }
  }
  window.bindChatInputNow = bindChatInputNow;
  bindChatInputNow();
  // ── Help & shortcuts sheet (Ctrl+/) ────────────────────────────────────────
  function showKeyboardShortcutsSheet() {
    var el = document.getElementById('keyboard-shortcuts-sheet');
    if (!el) return;
    el.style.display = 'flex';
  }
  function hideKeyboardShortcutsSheet() {
    var el = document.getElementById('keyboard-shortcuts-sheet');
    if (!el) return;
    el.style.display = 'none';
  }
  window.showKeyboardShortcutsSheet = showKeyboardShortcutsSheet;
  window.hideKeyboardShortcutsSheet = hideKeyboardShortcutsSheet;

  document.addEventListener('keydown', function (e) {
    try {
      var k = (e.key || '').toLowerCase();
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
        var s = document.getElementById('chat-rail-search');
        if (s) { s.focus(); s.select && s.select(); }
        return;
      }
      // Escape closes overlays
      if (k === 'escape') {
        hideKeyboardShortcutsSheet();
      }
    } catch (_) {}
  }, true);
  /* Right panel: DOM switching lives here so tabs work even if the huge main script throws before assigning handlers. */
  function __laylaApplyRcpMain(main) {
    var root = document.getElementById('layla-right-panel');
    if (!root || !main) return;
    var tabs = root.querySelectorAll('.rcp-tab');
    for (var i = 0; i < tabs.length; i++) {
      var b = tabs[i];
      var on = b.getAttribute('data-rcp') === main;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    }
    var pages = root.querySelectorAll('.rcp-page');
    for (var j = 0; j < pages.length; j++) {
      var p = pages[j];
      var onp = p.getAttribute('data-rcp') === main;
      p.classList.toggle('active', onp);
      p.setAttribute('aria-hidden', onp ? 'false' : 'true');
      try { p.removeAttribute('hidden'); } catch (e2) {}
    }
  }
  function __laylaApplyRcpWs(sub) {
    __laylaApplyRcpMain('workspace');
    var root = document.getElementById('layla-right-panel');
    var ws = root && root.querySelector('.rcp-page[data-rcp="workspace"]');
    if (!ws || !sub) return;
    var subs = ws.querySelectorAll('.rcp-subtab');
    for (var a = 0; a < subs.length; a++) {
      var sb = subs[a];
      sb.classList.toggle('active', sb.getAttribute('data-rcp-sub') === sub);
    }
    var panes = ws.querySelectorAll('.rcp-subpage');
    for (var b = 0; b < panes.length; b++) {
      var pane = panes[b];
      pane.classList.toggle('active', pane.getAttribute('data-rcp-sub') === sub);
    }
  }
  window.showMainPanel = function (main) {
    __laylaApplyRcpMain(main);
    if (typeof window.__laylaRefreshAfterShowMainPanel === 'function') {
      try { window.__laylaRefreshAfterShowMainPanel(main); } catch (err) { console.warn('[Layla] refresh main panel', err); }
    }
  };
  window.showWorkspaceSubtab = function (sub) {
    __laylaApplyRcpWs(sub);
    if (typeof window.__laylaRefreshAfterWorkspaceSubtab === 'function') {
      try { window.__laylaRefreshAfterWorkspaceSubtab(sub); } catch (err) { console.warn('[Layla] refresh workspace sub', err); }
    }
  };
  /* Capture phase: right-panel tabs before any bubble-phase stopPropagation steals the click */
  document.addEventListener('click', function (e) {
    var t = e.target;
    var rcpTab = t && t.closest && t.closest('#layla-right-panel .rcp-tab');
    if (rcpTab) {
      var rm = rcpTab.getAttribute('data-rcp');
      if (rm && typeof window.showMainPanel === 'function') window.showMainPanel(rm);
      return;
    }
    var rcpSub = t && t.closest && t.closest('#layla-right-panel .rcp-subtab');
    if (rcpSub) {
      var ws = rcpSub.getAttribute('data-rcp-sub');
      if (ws && typeof window.showWorkspaceSubtab === 'function') window.showWorkspaceSubtab(ws);
      return;
    }
  }, true);
  // Delegated click (bubble): aspect buttons — keep separate so we do not rely on capture for sidebar
  document.addEventListener('click', function (e) {
    var t = e.target;
    var aspectBtn = t && t.closest && t.closest('.aspect-btn');
    if (aspectBtn) {
      if (typeof window.setAspect === 'function') { window.setAspect(aspectBtn.id ? aspectBtn.id.replace(/^btn-/, '') : ''); return; }
      var id = (aspectBtn.id || '').replace(/^btn-/, '') || 'morrigan';
      window.currentAspect = id;
      document.querySelectorAll('.aspect-btn').forEach(function(b) { b.classList.remove('active'); if (b.id === 'btn-' + id) b.classList.add('active'); });
      var badge = document.getElementById('aspect-badge');
      if (badge) badge.textContent = id.toUpperCase();
    }
  }, false);
})();
