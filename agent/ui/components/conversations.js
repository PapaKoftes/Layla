/**
 * components/conversations.js — Multi-chat rail, server conversation sync, context chip.
 *
 * Converted from js/layla-conversations.js (top-level script -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast, laylaConfirm, laylaPrompt, sanitizeHtml)
 *
 * References (via window.*): addMsg, hideEmpty, renderPromptTilesAndEmptyState,
 *   laylaScrollActiveConversationIntoView, currentAspect, currentConversationId
 */

import { escapeHtml, showToast, laylaConfirm, laylaPrompt, sanitizeHtml } from '../services/utils.js';

// Expose the sidebar re-fetch so app.js can refresh it when a turn completes — otherwise a
// new chat keeps its creation-time placeholder and never shows the server-generated title
// (the "title stuck loading" bug). _renderSessionList is a hoisted function declaration.
try { window.refreshConversationList = _renderSessionList; } catch (_e) { /* no-op */ }

// ── State ───────────────────────────────────────────────────────────────────
const SESSIONS_KEY = 'layla_sessions';
const MAX_SESSIONS = 10;
const RAIL_PAGE_SIZE = 30;
let _railOffset = 0;
let _railHasMore = false;
let _railSearchTimer = null;

// ── Helpers ─────────────────────────────────────────────────────────────────
function _hasChatContent() {
  const chat = document.getElementById('chat');
  return !!(chat && chat.querySelector('.msg'));
}

function _saveCurrentSession() {
  const chat = document.getElementById('chat');
  if (!chat) return;
  const msgs = chat.querySelectorAll('.msg');
  if (!msgs.length) return;
  const first = msgs[0].querySelector('.msg-bubble');
  const preview = (first ? first.textContent : 'Session').replace(/\s+/g, ' ').trim().slice(0, 60);
  const entry = {
    id: Date.now(),
    created: new Date().toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }),
    preview,
    html: chat.innerHTML,
  };
  try {
    let sessions = JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]');
    sessions.unshift(entry);
    sessions = sessions.slice(0, MAX_SESSIONS);
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
    _renderSessionList();
  } catch (_) {}
}

// ── Context chip ────────────────────────────────────────────────────────────
export function updateContextChip() {
  const el = document.getElementById('context-chip');
  if (!el) return;
  // U5: the empty-state hero is the sole empty state — no competing "No chat selected"
  // line. The chip only appears once a real conversation is active (it carries thread
  // context, which is meaningless with nothing loaded).
  const hasConv = typeof window.currentConversationId !== 'undefined' && !!window.currentConversationId;
  if (!hasConv) { el.style.display = 'none'; return; }
  el.style.display = '';
  const asp = (typeof window.currentAspect !== 'undefined' ? window.currentAspect : 'morrigan') || 'morrigan';
  const wsEl = document.getElementById('workspace-path');
  const ws = (wsEl && wsEl.value || '').trim() || '(default sandbox)';
  const cid =
    typeof window.currentConversationId !== 'undefined' && window.currentConversationId
      ? String(window.currentConversationId).slice(0, 10) + (String(window.currentConversationId).length > 10 ? '…' : '')
      : '—';
  const ps = document.getElementById('project-select');
  const ptxt = ps && ps.value ? (ps.options[ps.selectedIndex] && ps.options[ps.selectedIndex].text ? ps.options[ps.selectedIndex].text : ps.value).slice(0, 24) : '—';
  el.textContent = 'Thread: ' + cid + ' · Project: ' + ptxt + ' · Facet: ' + asp + ' · WS: ' + ws.slice(0, 32) + (ws.length > 32 ? '…' : '');
}

// ── Chat rail mobile toggle ────────────────────────────────────────────────
export function toggleChatRailMobile() {
  const rail = document.getElementById('chat-rail');
  if (rail) rail.classList.toggle('open');
  const bd = document.getElementById('chat-rail-backdrop');
  if (bd) bd.classList.toggle('visible');
}

export function closeChatRailMobile() {
  const rail = document.getElementById('chat-rail');
  if (rail) rail.classList.remove('open');
  const bd = document.getElementById('chat-rail-backdrop');
  if (bd) bd.classList.remove('visible');
}

// ── Load conversation ───────────────────────────────────────────────────────
export async function loadConversationIntoChat(convId, skipConfirm) {
  if (!convId) return;
  if (!skipConfirm && _hasChatContent()) {
    if (!(await laylaConfirm('Switch chats? Current messages will be replaced from the server.'))) return;
  }
  const chat = document.getElementById('chat');
  if (!chat) return;
  try {
    const r = await fetch('/conversations/' + encodeURIComponent(convId) + '/messages?limit=500');
    const d = await r.json();
    if (!d.ok || !Array.isArray(d.messages)) return;
    chat.innerHTML = '';
    d.messages.forEach((m) => {
      if (typeof window.addMsg === 'function') {
        window.addMsg((m.role || '') === 'user' ? 'you' : 'layla', m.content || '', null, false, null);
      }
    });
    if (typeof window.hideEmpty === 'function') window.hideEmpty();
    chat.scrollTop = chat.scrollHeight;
    window.currentConversationId = String(convId);
    localStorage.setItem('layla_current_conversation_id', window.currentConversationId);
    updateContextChip();
    _renderSessionList();
    closeChatRailMobile();
  } catch (_) {}
}

// ── New conversation ────────────────────────────────────────────────────────
export async function startNewConversation() {
  try {
    const aspect = (typeof window.currentAspect !== 'undefined' ? window.currentAspect : 'morrigan') || 'morrigan';
    const r = await fetch('/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ aspect_id: aspect }),
    });
    const d = await r.json();
    if (!d.ok || !d.conversation) {
      showToast('Could not create chat');
      return;
    }
    const chat = document.getElementById('chat');
    if (chat) {
      chat.innerHTML = '';
      const empty = document.createElement('div');
      empty.id = 'chat-empty';
      empty.innerHTML = typeof window.renderPromptTilesAndEmptyState === 'function' ? window.renderPromptTilesAndEmptyState() : '';
      chat.appendChild(empty);
    }
    window.currentConversationId = String(d.conversation.id);
    localStorage.setItem('layla_current_conversation_id', window.currentConversationId);
    updateContextChip();
    _renderSessionList();
    closeChatRailMobile();
    const inp = document.getElementById('msg-input');
    if (inp) inp.focus();
  } catch (_) {
    showToast('Network error');
  }
}

export async function clearAllConversations() {
  if (!(await laylaConfirm('Delete ALL conversations? This cannot be undone.'))) return;
  try {
    const r = await fetch('/conversations/clear_all', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (d && d.ok) {
      showToast('Cleared ' + (d.removed || 0) + ' conversation' + ((d.removed === 1) ? '' : 's'));
      try { localStorage.removeItem('layla_current_conversation_id'); } catch (_) {}
      window.currentConversationId = '';
      await startNewConversation();
      _renderSessionList();
    } else {
      showToast('Could not clear: ' + ((d && d.error) || r.status));
    }
  } catch (_) {
    showToast('Network error');
  }
}

// ── Boot: load active conversation ──────────────────────────────────────────
export async function tryLoadActiveConversationOnBoot() {
  const id = localStorage.getItem('layla_current_conversation_id');
  if (!id) {
    updateContextChip();
    return;
  }
  await loadConversationIntoChat(id, true);
}

// ── Pinned conversations ────────────────────────────────────────────────────
function _getPinned() {
  try {
    const raw = JSON.parse(localStorage.getItem('layla_pinned_conversations') || '[]');
    return Array.isArray(raw) ? raw.map(String) : [];
  } catch (_) { return []; }
}

function _setPinned(ids) {
  try { localStorage.setItem('layla_pinned_conversations', JSON.stringify(ids.map(String))); } catch (_) {}
}

function _togglePinned(id) {
  const ids = _getPinned();
  const sid = String(id);
  const idx = ids.indexOf(sid);
  if (idx >= 0) ids.splice(idx, 1);
  else ids.unshift(sid);
  _setPinned(ids.slice(0, 50));
}

// ── Date bucketing for the rail (Today / Yesterday / … like Claude/ChatGPT) ──
function _dateBucket(iso) {
  const t = Date.parse(String(iso || '').replace(' ', 'T'));
  if (!t) return 'Older';
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const dayMs = 86400000;
  if (t >= startOfToday) return 'Today';
  if (t >= startOfToday - dayMs) return 'Yesterday';
  if (t >= startOfToday - 7 * dayMs) return 'Previous 7 days';
  if (t >= startOfToday - 30 * dayMs) return 'Previous 30 days';
  return 'Older';
}

function _relTimeShort(iso) {
  const t = Date.parse(String(iso || '').replace(' ', 'T'));
  if (!t) return '';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return 'now';
  if (s < 3600) return Math.floor(s / 60) + 'm';
  if (s < 86400) return Math.floor(s / 3600) + 'h';
  if (s < 604800) return Math.floor(s / 86400) + 'd';
  const d = new Date(t);
  return (d.getMonth() + 1) + '/' + d.getDate();
}

// ── Render session list ─────────────────────────────────────────────────────
export async function _renderSessionList(isAppendArg) {
  const container = document.getElementById('chat-rail-list');
  if (!container) return;
  const rawQ = (document.getElementById('chat-rail-search') || {}).value || '';
  const trimQ = rawQ.trim();

  // Lightweight query syntax: tag:foo, after:YYYY-MM-DD, before:YYYY-MM-DD
  let q = trimQ;
  let tag = '';
  let after = '';
  let before = '';
  try {
    const parts = trimQ.split(/\s+/).filter(Boolean);
    const rest = [];
    parts.forEach((p) => {
      const m = String(p || '');
      if (m.toLowerCase().startsWith('tag:')) tag = m.slice(4).trim();
      else if (m.toLowerCase().startsWith('after:')) after = m.slice(6).trim();
      else if (m.toLowerCase().startsWith('before:')) before = m.slice(7).trim();
      else rest.push(m);
    });
    q = rest.join(' ').trim();
  } catch (_) {}

  function _parseDay(s) {
    const t = String(s || '').trim();
    if (!t) return null;
    const dt = new Date(t);
    return isNaN(dt.getTime()) ? null : dt.getTime();
  }

  try {
    const isAppend = isAppendArg === true;
    const pageOffset = isAppend ? _railOffset : 0;
    const limit = RAIL_PAGE_SIZE;
    const base = q ? '/conversations/search?q=' + encodeURIComponent(q) + '&limit=' + limit + '&offset=' + pageOffset : '/conversations?limit=' + limit + '&offset=' + pageOffset;
    const url = tag ? (base + '&tag=' + encodeURIComponent(tag)) : base;
    const r = await fetch(url);
    const d = await r.json();
    if (d.ok && Array.isArray(d.conversations)) {
      let convs = d.conversations.slice();
      _railHasMore = convs.length >= limit;

      // Client-side date filters
      const afterTs = after ? _parseDay(after) : null;
      const beforeTs = before ? _parseDay(before) : null;
      if (afterTs || beforeTs) {
        convs = convs.filter((c) => {
          const ts = _parseDay(c.updated_at || c.created_at || '');
          if (!ts) return true;
          if (afterTs && ts < afterTs) return false;
          if (beforeTs && ts > beforeTs) return false;
          return true;
        });
      }
      if (!convs.length) {
        container.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">No chats match. Try New chat.</span>';
        return;
      }
      const pinned = _getPinned();
      const conversations = convs.slice().sort(function (a, b) {
        const ap = pinned.indexOf(String(a.id)) >= 0 ? 0 : 1;
        const bp = pinned.indexOf(String(b.id)) >= 0 ? 0 : 1;
        if (ap !== bp) return ap - bp;
        return String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
      });
      if (!isAppend) container.innerHTML = '';
      else {
        const oldMore = container.querySelector('.rail-load-more');
        if (oldMore) oldMore.remove();
      }
      let _lastGroup = isAppend ? (container.getAttribute('data-last-group') || null) : null;
      conversations.forEach((s) => {
        const isPinned = pinned.indexOf(String(s.id)) >= 0;
        // Date-bucketed section dividers (pinned float to their own group at the top).
        const group = isPinned ? '⟡ Pinned' : _dateBucket(s.updated_at || s.created_at);
        if (group !== _lastGroup) {
          const gd = document.createElement('div');
          gd.className = 'rail-group-divider';
          gd.textContent = group;
          gd.style.cssText = 'font-size:0.56rem;text-transform:uppercase;letter-spacing:0.1em;color:var(--asp);opacity:0.7;padding:9px 6px 3px;border-top:1px solid var(--border);margin-top:3px';
          container.appendChild(gd);
          _lastGroup = group;
        }
        const item = document.createElement('div');
        const active = String(s.id) === String(window.currentConversationId);
        item.className = 'session-item chat-rail-item' + (active ? ' active' : '');
        try { item.setAttribute('data-conv-id', String(s.id || '')); } catch (_) {}
        const asp = String(s.aspect_id || '').toLowerCase();
        const proj = String(s.project_id || '').trim();
        const tagsRaw = String(s.tags || '').trim();
        const tags = tagsRaw ? tagsRaw.split(',').map(t => (t || '').trim()).filter(Boolean).slice(0, 3) : [];
        item.innerHTML =
          '<span class="sess-preview">' +
          '<span class="conv-meta">' +
          '<span class="conv-asp-dot" data-asp="' + escapeHtml(asp || 'morrigan') + '"></span>' +
          (isPinned ? '<span class="conv-pin">⟡</span>' : '') +
          (proj ? '<span class="conv-proj">' + escapeHtml(proj.slice(0, 16)) + '</span>' : '') +
          (tags.length ? ('<span class="conv-proj" title="Tags">' + escapeHtml(tags.join(' · ').slice(0, 28)) + '</span>') : '') +
          '</span>' +
          escapeHtml((s.title || 'New chat').slice(0, 110)) +
          '</span><span class="sess-date" title="' + escapeHtml(String((s.updated_at || '').replace('T', ' ').slice(0, 16))) + '">' +
          escapeHtml(_relTimeShort(s.updated_at || s.created_at)) +
          '</span>';
        const renBtn = document.createElement('button');
        renBtn.className = 'sess-del';
        renBtn.title = 'Rename';
        renBtn.textContent = '✎';
        renBtn.type = 'button';
        renBtn.addEventListener('click', async (ev) => {
          ev.stopPropagation();
          const nt = await laylaPrompt('Rename chat', (s.title || 'New chat').slice(0, 120));
          if (!nt || !nt.trim()) return;
          try {
            const rr = await fetch('/conversations/' + encodeURIComponent(s.id) + '/rename', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ title: nt.trim() }),
            });
            const dj = await rr.json();
            if (dj.ok) _renderSessionList();
          } catch (_) {}
        });
        const delBtn = document.createElement('button');
        delBtn.className = 'sess-del';
        delBtn.title = 'Delete';
        delBtn.textContent = '✕';
        delBtn.type = 'button';
        delBtn.dataset.sessionId = String(s.id);
        delBtn.addEventListener('click', async (ev) => {
          ev.stopPropagation();
          await _deleteSession(ev.target.dataset.sessionId);
        });
        item.appendChild(renBtn);
        item.appendChild(delBtn);
        const pinBtn = document.createElement('button');
        pinBtn.className = 'sess-del';
        pinBtn.title = isPinned ? 'Unpin' : 'Pin';
        pinBtn.textContent = isPinned ? '⟡' : '⟐';
        pinBtn.type = 'button';
        pinBtn.addEventListener('click', function (ev) {
          ev.stopPropagation();
          _togglePinned(s.id);
          _renderSessionList();
        });
        item.appendChild(pinBtn);
        item.addEventListener('click', async () => {
          await loadConversationIntoChat(String(s.id), false);
        });
        item.addEventListener('contextmenu', async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const action = await laylaPrompt('Chat actions: rename | delete | pin | tags | export', 'rename');
          if (!action) return;
          const a = action.trim().toLowerCase();
          if (a === 'pin') { _togglePinned(s.id); _renderSessionList(); return; }
          if (a === 'delete') { await _deleteSession(String(s.id)); return; }
          if (a === 'rename') { renBtn.click(); return; }
          if (a === 'export') {
            try {
              const rr = await fetch('/conversations/' + encodeURIComponent(s.id) + '/messages?limit=2000');
              const dj = await rr.json();
              if (!dj.ok || !Array.isArray(dj.messages)) { showToast('Could not export'); return; }
              const blob = new Blob([JSON.stringify({ conversation: s, messages: dj.messages }, null, 2)], { type: 'application/json' });
              const blobUrl = URL.createObjectURL(blob);
              const ael = document.createElement('a');
              const safe = String((s.title || 'chat') || 'chat').replace(/[^a-z0-9_-]+/gi, '_').slice(0, 48);
              ael.href = blobUrl;
              ael.download = 'layla_' + safe + '_' + String(s.id).slice(0, 8) + '.json';
              document.body.appendChild(ael);
              ael.click();
              setTimeout(() => { try { URL.revokeObjectURL(blobUrl); } catch (_2) {} try { ael.remove(); } catch (_2) {} }, 250);
              showToast('Exported');
            } catch (_) { showToast('Network error'); }
            return;
          }
          if (a === 'tags') {
            const nt = await laylaPrompt('Tags (comma-separated)', String(s.tags || ''));
            if (nt == null) return;
            try {
              const rr = await fetch('/conversations/' + encodeURIComponent(s.id) + '/tags', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tags: String(nt || '') }),
              });
              const dj = await rr.json();
              if (dj.ok) _renderSessionList();
              else showToast('Could not save tags');
            } catch (_) { showToast('Network error'); }
            return;
          }
        });
        container.appendChild(item);
      });
      try { container.setAttribute('data-last-group', _lastGroup || ''); } catch (_) {}
      _railOffset = pageOffset + convs.length;
      if (_railHasMore) {
        const moreBtn = document.createElement('button');
        moreBtn.className = 'rail-load-more';
        moreBtn.type = 'button';
        moreBtn.textContent = 'Load more...';
        moreBtn.style.cssText = 'width:100%;padding:6px;margin-top:4px;font-size:0.66rem;background:var(--code-bg);border:1px solid var(--border);color:var(--text-dim);border-radius:3px;cursor:pointer;font-family:inherit';
        moreBtn.addEventListener('click', function () { _renderSessionList(true); });
        container.appendChild(moreBtn);
      }
      try { if (typeof window.laylaScrollActiveConversationIntoView === 'function') window.laylaScrollActiveConversationIntoView(); } catch (_) {}
      return;
    }
  } catch (_) {}

  // Fallback: local sessions
  let sessions = [];
  try {
    sessions = JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]');
  } catch (_) {}
  if (!sessions.length) {
    container.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Server unavailable — no local sessions</span>';
    return;
  }
  container.innerHTML = '';
  sessions.forEach((s) => {
    const item = document.createElement('div');
    item.className = 'session-item chat-rail-item';
    item.innerHTML =
      '<span class="sess-preview">' +
      (s.preview || '').replace(/</g, '&lt;') +
      '</span><span class="sess-date">' +
      escapeHtml(String(s.created || '')) +
      '</span>';
    const delBtn = document.createElement('button');
    delBtn.className = 'sess-del';
    delBtn.title = 'Delete';
    delBtn.textContent = '✕';
    delBtn.type = 'button';
    delBtn.dataset.sessionId = String(s.id);
    delBtn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      _deleteSession(ev.target.dataset.sessionId);
    });
    item.appendChild(delBtn);
    item.addEventListener('click', () => _restoreSession(s));
    container.appendChild(item);
  });
}

// ── Restore local session ───────────────────────────────────────────────────
async function _restoreSession(s) {
  const chat = document.getElementById('chat');
  if (!chat) return;
  if (s && s.id && !s.html) {
    await loadConversationIntoChat(String(s.id), false);
    return;
  }
  if (!(await laylaConfirm('Restore this session? Current chat will be cleared.'))) return;
  chat.innerHTML = sanitizeHtml(s.html);
  if (typeof window.hideEmpty === 'function') window.hideEmpty();
  chat.scrollTop = chat.scrollHeight;
}

// ── Delete session ──────────────────────────────────────────────────────────
async function _deleteSession(id) {
  if (!(await laylaConfirm('Delete this chat?'))) return;
  try {
    const r = await fetch('/conversations/' + encodeURIComponent(id), { method: 'DELETE' });
    const d = await r.json();
    if (d.ok) {
      if (String(id) === String(window.currentConversationId)) {
        window.currentConversationId = '';
        localStorage.removeItem('layla_current_conversation_id');
        const chat = document.getElementById('chat');
        if (chat) {
          chat.innerHTML = '';
          const empty = document.createElement('div');
          empty.id = 'chat-empty';
          empty.innerHTML = typeof window.renderPromptTilesAndEmptyState === 'function' ? window.renderPromptTilesAndEmptyState() : '';
          chat.appendChild(empty);
        }
        updateContextChip();
      }
      _renderSessionList();
      return;
    }
  } catch (_) {}
  try {
    let sessions = JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]');
    sessions = sessions.filter((s) => String(s.id) !== String(id));
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
    _renderSessionList();
  } catch (_) {}
}

// ── Projects ────────────────────────────────────────────────────────────────
export async function loadProjectsIntoSelect() {
  const sel = document.getElementById('project-select');
  if (!sel) return;
  const cur = localStorage.getItem('layla_active_project_id') || '';
  try {
    const r = await fetch('/projects?limit=200');
    const d = await r.json();
    if (!d.ok || !Array.isArray(d.projects)) return;
    sel.innerHTML = '';
    const none = document.createElement('option');
    none.value = '';
    none.textContent = '— None —';
    sel.appendChild(none);
    d.projects.forEach((p) => {
      const o = document.createElement('option');
      o.value = p.id;
      o.textContent = (p.name || p.id).slice(0, 50);
      sel.appendChild(o);
    });
    if (cur && [...sel.options].some((x) => x.value === cur)) sel.value = cur;
  } catch (_) {}
}

export function onProjectSelectChange() {
  const sel = document.getElementById('project-select');
  if (!sel) return;
  if (sel.value) localStorage.setItem('layla_active_project_id', sel.value);
  else localStorage.removeItem('layla_active_project_id');
  updateContextChip();
}

export async function createProjectQuick() {
  const name = await laylaPrompt('Project name?', 'My project');
  if (!name || !name.trim()) return;
  try {
    const r = await fetch('/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim() }),
    });
    const d = await r.json();
    if (d.ok && d.project) {
      await loadProjectsIntoSelect();
      const sel = document.getElementById('project-select');
      if (sel) {
        sel.value = d.project.id;
        onProjectSelectChange();
      }
      showToast('Project created');
    } else showToast('Could not create project');
  } catch (_) {
    showToast('Network error');
  }
}

// ── Init: debounced chat-rail search ────────────────────────────────────────
export function initConversations() {
  try {
    const searchEl = document.getElementById('chat-rail-search');
    if (!searchEl) return;
    searchEl.addEventListener('input', function () {
      clearTimeout(_railSearchTimer);
      _railSearchTimer = setTimeout(function () {
        _railOffset = 0;
        _renderSessionList();
      }, 280);
    });
    searchEl.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        searchEl.value = '';
        _railOffset = 0;
        _renderSessionList();
      }
    });
  } catch (_) {}
}

// Re-export for compat
export { _saveCurrentSession };
