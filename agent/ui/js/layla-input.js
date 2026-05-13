/**
 * layla-input.js — Input field behavior, @mention dropdown, URL detection chip,
 * file attachments, theme/sidebar toggles, chat export, chat search, and diff viewer.
 *
 * Depends on:
 *   layla-utils.js   (escapeHtml, showToast, fetchWithTimeout)
 *   layla-aspect.js  (ASPECTS)
 *   layla-chat-render.js (toggleSendButton, renderPromptTilesAndEmptyState)
 */
(function () {
  'use strict';

  // ── Prompt history (module-scoped) ──────────────────────────────────────────
  var _promptHistoryList = null;
  var _promptHistoryIdx = -1;

  function _ensurePromptHistory() {
    if (_promptHistoryList) return Promise.resolve();
    return fetch('/conversations/prompt_history')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        _promptHistoryList = Array.isArray(d && d.history) ? d.history : [];
        _promptHistoryIdx = -1;
      })
      .catch(function () {
        _promptHistoryList = [];
        _promptHistoryIdx = -1;
      });
  }

  // ── Mention dropdown (module-scoped vars) ─────────────────────────────────
  var _mentionActive = false;
  window._mentionActive = false;
  var _mentionIdx = 0;
  var _mentionAspectOverride = null;

  function _getMentionQuery(val) {
    var m = val.match(/(?:^|\s)@(\w*)$/);
    return m ? m[1].toLowerCase() : null;
  }

  function _showMentionDropdown(query) {
    var dd = document.getElementById('mention-dropdown');
    if (!dd) return;
    var ASPECTS = window.ASPECTS || [];
    var filtered = query === ''
      ? ASPECTS
      : ASPECTS.filter(function (a) { return a.id.startsWith(query) || a.name.toLowerCase().startsWith(query); });
    if (!filtered.length) { _hideMentionDropdown(); return; }
    _mentionActive = true;
    window._mentionActive = true;
    _mentionIdx = 0;
    dd.innerHTML = filtered.map(function (a, i) {
      return '<div class="mention-item' + (i === 0 ? ' active' : '') + '" data-id="' + a.id + '" onmousedown="event.preventDefault();_pickMention(\'' + a.id + '\')">'
        + '<span class="mention-sym">' + a.sym + '</span>'
        + '<span class="mention-name">' + a.name + '</span>'
        + '<span class="mention-desc">' + a.desc + '</span>'
        + '</div>';
    }).join('');
    dd.classList.add('open');
    dd._filtered = filtered;
  }

  function _hideMentionDropdown() {
    var dd = document.getElementById('mention-dropdown');
    if (dd) { dd.classList.remove('open'); dd.innerHTML = ''; }
    _mentionActive = false;
    window._mentionActive = false;
    _mentionIdx = 0;
  }

  function _moveMentionDropdown(dir) {
    var dd = document.getElementById('mention-dropdown');
    if (!dd || !_mentionActive) return;
    var items = dd.querySelectorAll('.mention-item');
    if (!items.length) return;
    if (items[_mentionIdx]) items[_mentionIdx].classList.remove('active');
    _mentionIdx = (_mentionIdx + dir + items.length) % items.length;
    if (items[_mentionIdx]) items[_mentionIdx].classList.add('active');
    if (items[_mentionIdx]) items[_mentionIdx].scrollIntoView({ block: 'nearest' });
  }

  function _pickMention(aspectId) {
    var input = document.getElementById('msg-input');
    if (!input) return;
    input.value = input.value.replace(/(?:^|\s)@\w*$/, function (m) {
      var prefix = m.charAt(0) === '@' ? '' : m.charAt(0);
      return prefix + '@' + aspectId + ' ';
    });
    _hideMentionDropdown();
    input.focus();
    window.toggleSendButton();
  }

  // ── Input event handlers ──────────────────────────────────────────────────
  function onInputChange(e) {
    window.toggleSendButton();
    var val = e.target.value;
    _checkUrlInInput(val);
    var query = _getMentionQuery(val);
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
      if (e.key === 'k') { e.preventDefault(); var inp = document.getElementById('msg-input'); if (inp) { inp.value = ''; window.toggleSendButton(); } return; }
      if (e.key === 'r') { e.preventDefault(); window.retryLastMessage(); return; }
      if (e.key === '/') { e.preventDefault(); showPanelTab('help'); return; }
      if (e.key === 'f') { e.preventDefault(); openChatSearch(); return; }
    }
    if (!_mentionActive && e.key === 'ArrowUp' && !e.shiftKey) {
      var inp = document.getElementById('msg-input');
      if (inp && (inp.selectionStart || 0) === 0) {
        e.preventDefault();
        _ensurePromptHistory().then(function () {
          if (!_promptHistoryList || !_promptHistoryList.length) return;
          _promptHistoryIdx = _promptHistoryIdx < 0 ? 0 : Math.min(_promptHistoryList.length - 1, _promptHistoryIdx + 1);
          inp.value = _promptHistoryList[_promptHistoryIdx] || '';
          window.toggleSendButton();
        });
        return;
      }
    }
    if (!_mentionActive && e.key === 'ArrowDown' && !e.shiftKey) {
      var inp = document.getElementById('msg-input');
      if (inp && _promptHistoryIdx >= 0 && (inp.selectionStart || 0) === (inp.value || '').length) {
        e.preventDefault();
        _promptHistoryIdx--;
        if (_promptHistoryIdx < 0) {
          inp.value = '';
          _promptHistoryIdx = -1;
          window.toggleSendButton();
          return;
        }
        inp.value = _promptHistoryList[_promptHistoryIdx] || '';
        window.toggleSendButton();
        return;
      }
    }
    if (_mentionActive) {
      if (e.key === 'ArrowDown') { e.preventDefault(); _moveMentionDropdown(1); return; }
      if (e.key === 'ArrowUp')   { e.preventDefault(); _moveMentionDropdown(-1); return; }
      if (e.key === 'Tab' || _isEnterKey(e)) {
        var dd = document.getElementById('mention-dropdown');
        if (dd && _mentionActive) {
          e.preventDefault();
          var items = dd.querySelectorAll('.mention-item');
          var id = items[_mentionIdx] && items[_mentionIdx].dataset && items[_mentionIdx].dataset.id;
          if (id) _pickMention(id);
          return;
        }
      }
      if (e.key === 'Escape') { _hideMentionDropdown(); return; }
    }
    // Enter-to-send is handled solely by document keydown (bootstrap); do not duplicate here.
  }

  // ── URL chip, attachments ─────────────────────────────────────────────────
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
      if (typeof window.showToast === 'function') window.showToast('No URL detected in the input');
      return;
    }
    var input = document.getElementById('msg-input');
    if (input) {
      var pre = String(input.value || '').replace(/https?:\/\/[^\s<>"']+/i, '').trim();
      input.value = (pre ? pre + '\n\n' : '') + 'Fetch and summarize this URL:\n' + _laylaPendingUrl;
      try { window.toggleSendButton(); } catch (_) {}
    }
    dismissUrlChip();
    if (typeof window.showToast === 'function') window.showToast('URL added to message — press Send');
  }

  // ── File attachments ──────────────────────────────────────────────────────
  function attachFile(inp) {
    var f = inp && inp.files && inp.files[0];
    if (!f) return;
    var r = new FileReader();
    r.onload = function () {
      var text = String(r.result || '').slice(0, 120000);
      var mi = document.getElementById('msg-input');
      if (mi) {
        mi.value = (mi.value ? mi.value + '\n\n' : '') + '--- file: ' + f.name + ' ---\n' + text;
        try { window.toggleSendButton(); } catch (_) {}
      }
      if (typeof window.showToast === 'function') window.showToast('Attached ' + f.name);
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
        try { window.toggleSendButton(); } catch (_) {}
      }
      if (typeof window.showToast === 'function') window.showToast('Dropped ' + f.name);
    };
    r.readAsText(f);
  }

  // ── Theme / Sidebar toggles ───────────────────────────────────────────────
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

  // ── Chat export / clear / fill / CLI help ─────────────────────────────────
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
      if (typeof window.showToast === 'function') window.showToast('Export downloaded');
    } catch (e) {
      if (typeof window.showToast === 'function') window.showToast('Export failed');
    }
  }

  function clearChat() {
    if (!confirm('Clear the chat panel?')) return;
    var chat = document.getElementById('chat');
    if (chat) {
      chat.innerHTML = '<div id="chat-empty">' + window.renderPromptTilesAndEmptyState() + '</div>';
    }
  }

  function fillPrompt(prefix) {
    var inp = document.getElementById('msg-input');
    if (!inp) return;
    inp.value = String(prefix || '');
    try {
      inp.focus();
      window.toggleSendButton();
    } catch (_) {}
  }

  function openCliHelp() {
    var t = 'Open a terminal in the Layla repo and start the server (see README Quick start). UI: Settings use /settings.';
    if (typeof window.showToast === 'function') window.showToast(t);
    else try { alert(t); } catch (_) {}
  }

  // ── Chat search ───────────────────────────────────────────────────────────
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

  // ── Diff viewer ───────────────────────────────────────────────────────────
  var _laylaDiffApprovalId = '';

  function closeDiffViewer() {
    var o = document.getElementById('diff-overlay');
    if (o) o.style.display = 'none';
    _laylaDiffApprovalId = '';
  }

  function confirmApplyFile() {
    if (!_laylaDiffApprovalId) {
      if (typeof window.showToast === 'function') window.showToast('Use Approvals panel — no preview approval id bound');
      closeDiffViewer();
      return;
    }
    window.fetchWithTimeout('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: _laylaDiffApprovalId }) }, 20000)
      .then(function (r) { return r.json().then(function (d) { return { r: r, d: d }; }); })
      .then(function (x) {
        if (x.r.ok && x.d && x.d.ok) {
          if (typeof window.showToast === 'function') window.showToast('Applied');
          closeDiffViewer();
          try { window.refreshApprovals(); } catch (_) {}
        } else if (typeof window.showToast === 'function') window.showToast((x.d && x.d.error) || 'Approve failed');
      })
      .catch(function () { if (typeof window.showToast === 'function') window.showToast('Approve failed'); });
  }

  function closeBatchDiffViewer() {
    var o = document.getElementById('batch-diff-overlay');
    if (o) o.style.display = 'none';
  }

  function confirmApplyBatch() {
    if (typeof window.showToast === 'function') window.showToast('Approve each pending item in the Approvals panel (batch id wiring is server-side)');
    closeBatchDiffViewer();
  }

  // ── Panel navigation helpers ──────────────────────────────────────────────
  var _LEGACY_PANEL_TO_RTA = {
    approvals: ['prefs'],
    health: ['status'],
    models: ['workspace', 'models'],
    knowledge: ['workspace', 'knowledge'],
    plugins: ['workspace', 'plugins'],
    study: ['workspace', 'study'],
    memory: ['workspace', 'memory'],
    research: ['research'],
  };

  function showPanelTab(tab) {
    var m = _LEGACY_PANEL_TO_RTA[tab];
    if (m) {
      if (m[1]) window.showWorkspaceSubtab(m[1]);
      else window.showMainPanel(m[0]);
      return;
    }
    window.showMainPanel('prefs');
  }

  function focusResearchPanel() {
    window.showMainPanel('research');
    var panel = document.getElementById('research-mission-panel');
    if (panel) {
      panel.scrollIntoView({ behavior: 'smooth' });
      window.refreshMissionStatus().then(function () { window.showResearchTab('summary'); });
    }
  }

  // ── Expose all public functions on window ─────────────────────────────────
  window._pickMention            = _pickMention;
  window.onInputChange           = onInputChange;
  window._isEnterKey             = _isEnterKey;
  window.onInputKeydown          = onInputKeydown;
  window.dismissUrlChip          = dismissUrlChip;
  window.acceptUrlFetch          = acceptUrlFetch;
  window.attachFile              = attachFile;
  window.handleFileDrop          = handleFileDrop;
  window.toggleTheme             = toggleTheme;
  window.toggleSidebarCompact    = toggleSidebarCompact;
  window.toggleMobileSidebar     = toggleMobileSidebar;
  window.exportChat              = exportChat;
  window.clearChat               = clearChat;
  window.fillPrompt              = fillPrompt;
  window.openCliHelp             = openCliHelp;
  window.openChatSearch          = openChatSearch;
  window.closeChatSearch         = closeChatSearch;
  window.onChatSearchInput       = onChatSearchInput;
  window.chatSearchNext          = chatSearchNext;
  window.closeDiffViewer         = closeDiffViewer;
  window.confirmApplyFile        = confirmApplyFile;
  window.closeBatchDiffViewer    = closeBatchDiffViewer;
  window.confirmApplyBatch       = confirmApplyBatch;
  window.showPanelTab            = showPanelTab;
  window.focusResearchPanel      = focusResearchPanel;

  window.laylaInputModuleLoaded  = true;
})();
