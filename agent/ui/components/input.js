/**
 * components/input.js — Input field behavior, @mention dropdown, URL detection,
 * file attachments, theme/sidebar toggles, chat export/search, and diff viewer.
 *
 * Converted from js/layla-input.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast, laylaConfirm),
 *             components/aspect.js (ASPECTS)
 */

import { escapeHtml, showToast, laylaConfirm } from '../services/utils.js';
import { ASPECTS } from './aspect.js';

// ── Prompt history ──────────────────────────────────────────────────────────
let _promptHistoryList = null;
let _promptHistoryIdx = -1;

function _ensurePromptHistory() {
  if (_promptHistoryList) return Promise.resolve();
  // Real endpoint is /history → {prompts:[{id,prompt,aspect,created_at}, ...]}
  // (newest first). The UI recalls plain strings, so map to .prompt.
  return fetch('/history')
    .then(r => r.json())
    .then(d => {
      const arr = Array.isArray(d && d.prompts) ? d.prompts : [];
      _promptHistoryList = arr
        .map(p => (p && typeof p === 'object') ? (p.prompt || '') : String(p || ''))
        .filter(Boolean);
      _promptHistoryIdx = -1;
    })
    .catch(() => {
      _promptHistoryList = [];
      _promptHistoryIdx = -1;
    });
}

// ── Mention dropdown ────────────────────────────────────────────────────────
let _mentionActive = false;
let _mentionIdx = 0;

function _getMentionQuery(val) {
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
  dd.innerHTML = filtered.map((a, i) => {
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
  if (items[_mentionIdx]) items[_mentionIdx].classList.remove('active');
  _mentionIdx = (_mentionIdx + dir + items.length) % items.length;
  if (items[_mentionIdx]) items[_mentionIdx].classList.add('active');
  if (items[_mentionIdx]) items[_mentionIdx].scrollIntoView({ block: 'nearest' });
}

export function _pickMention(aspectId) {
  const input = document.getElementById('msg-input');
  if (!input) return;
  input.value = input.value.replace(/(?:^|\s)@\w*$/, m => {
    const prefix = m.charAt(0) === '@' ? '' : m.charAt(0);
    return prefix + '@' + aspectId + ' ';
  });
  _hideMentionDropdown();
  input.focus();
  if (typeof window.toggleSendButton === 'function') window.toggleSendButton();
}

// ── Input event handlers ────────────────────────────────────────────────────
export function onInputChange(e) {
  if (typeof window.toggleSendButton === 'function') window.toggleSendButton();
  const val = e.target.value;
  _checkUrlInInput(val);
  const query = _getMentionQuery(val);
  if (query !== null) {
    _showMentionDropdown(query);
  } else {
    _hideMentionDropdown();
  }
}

export function _isEnterKey(e) {
  return e.key === 'Enter' || e.keyCode === 13;
}

export function onInputKeydown(e) {
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'k') { e.preventDefault(); const inp = document.getElementById('msg-input'); if (inp) { inp.value = ''; if (typeof window.toggleSendButton === 'function') window.toggleSendButton(); } return; }
    if (e.key === 'r') { e.preventDefault(); if (typeof window.retryLastMessage === 'function') window.retryLastMessage(); return; }
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
        if (typeof window.toggleSendButton === 'function') window.toggleSendButton();
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
        if (typeof window.toggleSendButton === 'function') window.toggleSendButton();
        return;
      }
      inp.value = _promptHistoryList[_promptHistoryIdx] || '';
      if (typeof window.toggleSendButton === 'function') window.toggleSendButton();
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
        const id = items[_mentionIdx] && items[_mentionIdx].dataset && items[_mentionIdx].dataset.id;
        if (id) _pickMention(id);
        return;
      }
    }
    if (e.key === 'Escape') { _hideMentionDropdown(); return; }
  }
}

// ── URL chip ────────────────────────────────────────────────────────────────
let _laylaPendingUrl = null;

function _checkUrlInInput(val) {
  const chip = document.getElementById('url-detect-chip');
  if (!chip) return;
  const s = String(val || '');
  const m = s.match(/https?:\/\/[^\s<>"']{4,}/i);
  if (m) {
    _laylaPendingUrl = m[0];
    try {
      const u = new URL(m[0]);
      const d = document.getElementById('url-chip-domain');
      if (d) d.textContent = u.hostname;
    } catch (_) {}
    chip.style.display = 'flex';
  } else {
    _laylaPendingUrl = null;
    chip.style.display = 'none';
  }
}

export function dismissUrlChip() {
  const chip = document.getElementById('url-detect-chip');
  if (chip) chip.style.display = 'none';
  _laylaPendingUrl = null;
}

export function acceptUrlFetch() {
  if (!_laylaPendingUrl) { showToast('No URL detected in the input'); return; }
  const input = document.getElementById('msg-input');
  if (input) {
    const pre = String(input.value || '').replace(/https?:\/\/[^\s<>"']+/i, '').trim();
    input.value = (pre ? pre + '\n\n' : '') + 'Fetch and summarize this URL:\n' + _laylaPendingUrl;
    try { if (typeof window.toggleSendButton === 'function') window.toggleSendButton(); } catch (_) {}
  }
  dismissUrlChip();
  showToast('URL added to message — press Send');
}

// ── File attachments ────────────────────────────────────────────────────────
export function attachFile(inp) {
  const f = inp && inp.files && inp.files[0];
  if (!f) return;
  const r = new FileReader();
  r.onload = () => {
    const text = String(r.result || '').slice(0, 120000);
    const mi = document.getElementById('msg-input');
    if (mi) {
      mi.value = (mi.value ? mi.value + '\n\n' : '') + '--- file: ' + f.name + ' ---\n' + text;
      try { if (typeof window.toggleSendButton === 'function') window.toggleSendButton(); } catch (_) {}
    }
    showToast('Attached ' + f.name);
  };
  r.readAsText(f);
  inp.value = '';
}

export function handleFileDrop(ev) {
  try { ev.preventDefault(); } catch (_) {}
  const area = document.getElementById('input-area-drop');
  if (area) area.style.borderColor = '';
  const fl = ev.dataTransfer && ev.dataTransfer.files;
  if (!fl || !fl.length) return;
  const f = fl[0];
  const r = new FileReader();
  r.onload = () => {
    const text = String(r.result || '').slice(0, 120000);
    const mi = document.getElementById('msg-input');
    if (mi) {
      mi.value = (mi.value ? mi.value + '\n\n' : '') + '--- file: ' + f.name + ' ---\n' + text;
      try { if (typeof window.toggleSendButton === 'function') window.toggleSendButton(); } catch (_) {}
    }
    showToast('Dropped ' + f.name);
  };
  r.readAsText(f);
}

// ── Theme / Sidebar toggles ─────────────────────────────────────────────────
export function toggleTheme() {
  document.body.classList.toggle('theme-light');
  try { localStorage.setItem('layla_theme', document.body.classList.contains('theme-light') ? 'light' : 'dark'); } catch (_) {}
}

export function toggleSidebarCompact() {
  const sb = document.querySelector('.sidebar');
  if (sb) sb.classList.toggle('compact');
}

export function toggleMobileSidebar() {
  const sb = document.querySelector('.sidebar');
  if (!sb) return;
  const isOpen = sb.classList.contains('mobile-open');
  const bd = document.getElementById('sidebar-backdrop');
  if (isOpen) {
    sb.classList.remove('mobile-open');
    if (bd) { bd.classList.remove('visible'); bd.setAttribute('aria-hidden', 'true'); }
  } else {
    sb.classList.add('mobile-open');
    if (bd) { bd.classList.add('visible'); bd.setAttribute('aria-hidden', 'false'); }
    closeRightPanel();
  }
}

export function closeMobileSidebar() {
  const sb = document.querySelector('.sidebar');
  if (sb) sb.classList.remove('mobile-open');
  const bd = document.getElementById('sidebar-backdrop');
  if (bd) { bd.classList.remove('visible'); bd.setAttribute('aria-hidden', 'true'); }
}

export function toggleRightPanel() {
  const rp = document.getElementById('layla-right-panel');
  if (!rp) return;
  const isOpen = rp.classList.contains('rp-open');
  const bd = document.getElementById('rp-backdrop');
  if (isOpen) {
    rp.classList.remove('rp-open');
    if (bd) { bd.classList.remove('visible'); bd.setAttribute('aria-hidden', 'true'); }
  } else {
    rp.classList.add('rp-open');
    if (bd) { bd.classList.add('visible'); bd.setAttribute('aria-hidden', 'false'); }
    closeMobileSidebar();
  }
}

export function closeRightPanel() {
  const rp = document.getElementById('layla-right-panel');
  if (rp) rp.classList.remove('rp-open');
  const bd = document.getElementById('rp-backdrop');
  if (bd) { bd.classList.remove('visible'); bd.setAttribute('aria-hidden', 'true'); }
}

export function openOverlayPanel(tab) {
  const rp = document.getElementById('layla-right-panel');
  const bd = document.getElementById('rp-backdrop');
  if (rp) rp.classList.add('rp-open');
  if (bd) { bd.classList.add('visible'); bd.setAttribute('aria-hidden', 'false'); }
  if (typeof window.showMainPanel === 'function') window.showMainPanel(tab);
  closeMobileSidebar();
}

// ── Chat export / clear / fill / CLI help ───────────────────────────────────
export function exportChat() {
  const chat = document.getElementById('chat');
  if (!chat) return;
  let md = '# Layla chat export\n\n';
  chat.querySelectorAll('.msg').forEach(row => {
    const lab = row.querySelector('.msg-label');
    const bub = row.querySelector('.msg-bubble');
    const role = (lab && lab.textContent && lab.textContent.indexOf('You') >= 0) ? 'You' : 'Layla';
    md += '## ' + role + '\n\n' + (bub ? String(bub.innerText || '').trim() : '') + '\n\n';
  });
  try {
    const blob = new Blob([md], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'layla-chat-export.md';
    a.click();
    URL.revokeObjectURL(a.href);
    showToast('Export downloaded');
  } catch (_) {
    showToast('Export failed');
  }
}

export async function clearChat() {
  if (!(await laylaConfirm('Clear the chat panel?'))) return;
  const chat = document.getElementById('chat');
  if (chat) {
    chat.innerHTML = '<div id="chat-empty">' + (typeof window.renderPromptTilesAndEmptyState === 'function' ? window.renderPromptTilesAndEmptyState() : '') + '</div>';
  }
}

export function fillPrompt(prefix) {
  const inp = document.getElementById('msg-input');
  if (!inp) return;
  inp.value = String(prefix || '');
  try { inp.focus(); if (typeof window.toggleSendButton === 'function') window.toggleSendButton(); } catch (_) {}
}

export function openCliHelp() {
  showToast('Open a terminal in the Layla repo and start the server (see README Quick start). UI: Settings use /settings.');
}

// ── Chat search ─────────────────────────────────────────────────────────────
let _laylaChatSearchMatches = [];
let _laylaChatSearchIdx = -1;

function _clearSearchHighlights() {
  document.querySelectorAll('.msg-bubble.search-hit').forEach(e => e.classList.remove('search-hit'));
}

export function openChatSearch() {
  const o = document.getElementById('chat-search-overlay');
  if (o) o.style.display = 'flex';
  const inp = document.getElementById('chat-search-input');
  if (inp) { inp.value = ''; inp.focus(); }
  _laylaChatSearchMatches = [];
  _laylaChatSearchIdx = -1;
  _clearSearchHighlights();
}

export function closeChatSearch() {
  const o = document.getElementById('chat-search-overlay');
  if (o) o.style.display = 'none';
  _clearSearchHighlights();
}

export function onChatSearchInput(q) {
  _laylaChatSearchMatches = [];
  _laylaChatSearchIdx = -1;
  _clearSearchHighlights();
  const chat = document.getElementById('chat');
  if (!chat) return;
  const Q = String(q || '').trim().toLowerCase();
  if (!Q) return;
  const els = chat.querySelectorAll('.msg-bubble');
  for (let i = 0; i < els.length; i++) {
    if ((els[i].textContent || '').toLowerCase().indexOf(Q) >= 0) _laylaChatSearchMatches.push(els[i]);
  }
  if (_laylaChatSearchMatches.length) {
    _laylaChatSearchIdx = 0;
    const cur = _laylaChatSearchMatches[0];
    if (cur) { cur.classList.add('search-hit'); cur.scrollIntoView({ block: 'center' }); }
  }
}

export function chatSearchNext() {
  if (!_laylaChatSearchMatches.length) return;
  _clearSearchHighlights();
  _laylaChatSearchIdx = (_laylaChatSearchIdx + 1) % _laylaChatSearchMatches.length;
  const cur = _laylaChatSearchMatches[_laylaChatSearchIdx];
  if (cur) { cur.classList.add('search-hit'); cur.scrollIntoView({ block: 'center' }); }
}

// ── Diff viewer ─────────────────────────────────────────────────────────────
let _laylaDiffApprovalId = '';

export function closeDiffViewer() {
  const o = document.getElementById('diff-overlay');
  if (o) o.style.display = 'none';
  _laylaDiffApprovalId = '';
}

export function confirmApplyFile() {
  if (!_laylaDiffApprovalId) {
    showToast('Use Approvals panel — no preview approval id bound');
    closeDiffViewer();
    return;
  }
  window.fetchWithTimeout('/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: _laylaDiffApprovalId }),
  }, 20000)
    .then(r => r.json().then(d => ({ r, d })))
    .then(x => {
      if (x.r.ok && x.d && x.d.ok) {
        showToast('Applied');
        closeDiffViewer();
        try { if (typeof window.refreshApprovals === 'function') window.refreshApprovals(); } catch (_) {}
      } else showToast((x.d && x.d.error) || 'Approve failed');
    })
    .catch(() => showToast('Approve failed'));
}

export function closeBatchDiffViewer() {
  const o = document.getElementById('batch-diff-overlay');
  if (o) o.style.display = 'none';
}

export function confirmApplyBatch() {
  showToast('Approve each pending item in the Approvals panel (batch id wiring is server-side)');
  closeBatchDiffViewer();
}

// ── Panel navigation helpers ────────────────────────────────────────────────
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

export function showPanelTab(tab) {
  const m = _LEGACY_PANEL_TO_RTA[tab];
  if (m) {
    if (m[1] && typeof window.showWorkspaceSubtab === 'function') window.showWorkspaceSubtab(m[1]);
    else if (typeof window.showMainPanel === 'function') window.showMainPanel(m[0]);
    return;
  }
  if (typeof window.showMainPanel === 'function') window.showMainPanel('prefs');
}

export function focusResearchPanel() {
  if (typeof window.showMainPanel === 'function') window.showMainPanel('research');
  const panel = document.getElementById('research-mission-panel');
  if (panel) {
    panel.scrollIntoView({ behavior: 'smooth' });
    if (typeof window.refreshMissionStatus === 'function') {
      window.refreshMissionStatus().then(() => {
        if (typeof window.showResearchTab === 'function') window.showResearchTab('summary');
      });
    }
  }
}
