/**
 * Layla UI — multi-chat rail, server conversation sync, context chip.
 * Loaded after inline script that defines: addMsg, showToast, escapeHtml,
 * renderPromptTilesAndEmptyState, hideEmpty, currentAspect, currentConversationId (var).
 */
// ─── Session history + chat rail ─────────────────────────────────────────────
const SESSIONS_KEY = 'layla_sessions';
const MAX_SESSIONS = 10;

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

function _hasChatContent() {
  const chat = document.getElementById('chat');
  return !!(chat && chat.querySelector('.msg'));
}

function updateContextChip() {
  const el = document.getElementById('context-chip');
  if (!el) return;
  const asp = (typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan') || 'morrigan';
  const ws = (document.getElementById('workspace-path')?.value || '').trim() || '(default sandbox)';
  const cid =
    typeof currentConversationId !== 'undefined' && currentConversationId
      ? String(currentConversationId).slice(0, 10) + (String(currentConversationId).length > 10 ? '…' : '')
      : '—';
  const ps = document.getElementById('project-select');
  const ptxt = ps && ps.value ? (ps.options[ps.selectedIndex] && ps.options[ps.selectedIndex].text ? ps.options[ps.selectedIndex].text : ps.value).slice(0, 24) : '—';
  el.textContent = 'Thread: ' + cid + ' · Project: ' + ptxt + ' · Facet: ' + asp + ' · WS: ' + ws.slice(0, 32) + (ws.length > 32 ? '…' : '');
}

function toggleChatRailMobile() {
  document.getElementById('chat-rail')?.classList.toggle('open');
  document.getElementById('chat-rail-backdrop')?.classList.toggle('visible');
}
function closeChatRailMobile() {
  document.getElementById('chat-rail')?.classList.remove('open');
  document.getElementById('chat-rail-backdrop')?.classList.remove('visible');
}

async function loadConversationIntoChat(convId, skipConfirm) {
  if (!convId) return;
  if (!skipConfirm && _hasChatContent()) {
    if (!confirm('Switch chats? Current messages will be replaced from the server.')) return;
  }
  const chat = document.getElementById('chat');
  if (!chat) return;
  try {
    const r = await fetch('/conversations/' + encodeURIComponent(convId) + '/messages?limit=500');
    const d = await r.json();
    if (!d.ok || !Array.isArray(d.messages)) return;
    chat.innerHTML = '';
    d.messages.forEach((m) => addMsg((m.role || '') === 'user' ? 'user' : 'layla', m.content || '', null, false, null));
    hideEmpty();
    chat.scrollTop = chat.scrollHeight;
    currentConversationId = String(convId);
    localStorage.setItem('layla_current_conversation_id', currentConversationId);
    updateContextChip();
    _renderSessionList();
    closeChatRailMobile();
  } catch (_) {}
}

async function startNewConversation() {
  try {
    const aspect = (typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan') || 'morrigan';
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
      empty.innerHTML = typeof renderPromptTilesAndEmptyState === 'function' ? renderPromptTilesAndEmptyState() : '';
      chat.appendChild(empty);
    }
    currentConversationId = String(d.conversation.id);
    localStorage.setItem('layla_current_conversation_id', currentConversationId);
    updateContextChip();
    _renderSessionList();
    closeChatRailMobile();
    document.getElementById('msg-input')?.focus();
  } catch (_) {
    showToast('Network error');
  }
}

async function tryLoadActiveConversationOnBoot() {
  const id = localStorage.getItem('layla_current_conversation_id');
  if (!id) {
    updateContextChip();
    return;
  }
  await loadConversationIntoChat(id, true);
}

async function _renderSessionList() {
  const container = document.getElementById('chat-rail-list');
  if (!container) return;
  const q = (document.getElementById('chat-rail-search')?.value || '').trim();
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
  try {
    const url = q ? '/conversations/search?q=' + encodeURIComponent(q) + '&limit=80' : '/conversations?limit=100';
    const r = await fetch(url);
    const d = await r.json();
    if (d.ok && Array.isArray(d.conversations)) {
      if (!d.conversations.length) {
        container.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">No chats match. Try New chat.</span>';
        return;
      }
      const pinned = _getPinned();
      const conversations = d.conversations.slice().sort(function(a, b) {
        const ap = pinned.indexOf(String(a.id)) >= 0 ? 0 : 1;
        const bp = pinned.indexOf(String(b.id)) >= 0 ? 0 : 1;
        if (ap !== bp) return ap - bp;
        // newest first fallback
        return String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
      });
      container.innerHTML = '';
      conversations.forEach((s) => {
        const item = document.createElement('div');
        const active = String(s.id) === String(currentConversationId);
        item.className = 'session-item chat-rail-item' + (active ? ' active' : '');
        try { item.setAttribute('data-conv-id', String(s.id || '')); } catch (_) {}
        const asp = String(s.aspect_id || '').toLowerCase();
        const isPinned = pinned.indexOf(String(s.id)) >= 0;
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
          escapeHtml((s.title || 'New chat').slice(0, 72)) +
          '</span><span class="sess-date">' +
          escapeHtml(String((s.updated_at || '').replace('T', ' ').slice(0, 16))) +
          '</span>';
        const renBtn = document.createElement('button');
        renBtn.className = 'sess-del';
        renBtn.title = 'Rename';
        renBtn.textContent = '✎';
        renBtn.type = 'button';
        renBtn.addEventListener('click', async (ev) => {
          ev.stopPropagation();
          const nt = prompt('Rename chat', (s.title || 'New chat').slice(0, 120));
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
        pinBtn.addEventListener('click', function(ev) {
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
          const action = prompt('Chat actions: rename | delete | pin | tags', 'rename');
          if (!action) return;
          const a = action.trim().toLowerCase();
          if (a === 'pin') { _togglePinned(s.id); _renderSessionList(); return; }
          if (a === 'delete') { await _deleteSession(String(s.id)); return; }
          if (a === 'rename') { renBtn.click(); return; }
          if (a === 'tags') {
            const nt = prompt('Tags (comma-separated)', String(s.tags || ''));
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
      try { if (typeof laylaScrollActiveConversationIntoView === 'function') laylaScrollActiveConversationIntoView(); } catch (_) {}
      return;
    }
  } catch (_) {}
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

async function _restoreSession(s) {
  const chat = document.getElementById('chat');
  if (!chat) return;
  if (s && s.id && !s.html) {
    await loadConversationIntoChat(String(s.id), false);
    return;
  }
  if (!confirm('Restore this session? Current chat will be cleared.')) return;
  chat.innerHTML = s.html;
  hideEmpty();
  chat.scrollTop = chat.scrollHeight;
}

async function _deleteSession(id) {
  if (!confirm('Delete this chat?')) return;
  try {
    const r = await fetch('/conversations/' + encodeURIComponent(id), { method: 'DELETE' });
    const d = await r.json();
    if (d.ok) {
      if (String(id) === String(currentConversationId)) {
        currentConversationId = '';
        localStorage.removeItem('layla_current_conversation_id');
        const chat = document.getElementById('chat');
        if (chat) {
          chat.innerHTML = '';
          const empty = document.createElement('div');
          empty.id = 'chat-empty';
          empty.innerHTML = typeof renderPromptTilesAndEmptyState === 'function' ? renderPromptTilesAndEmptyState() : '';
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

window.updateContextChip = updateContextChip;
window.toggleChatRailMobile = toggleChatRailMobile;
window.closeChatRailMobile = closeChatRailMobile;
window.startNewConversation = startNewConversation;
window.loadConversationIntoChat = loadConversationIntoChat;
window.tryLoadActiveConversationOnBoot = tryLoadActiveConversationOnBoot;
window._renderSessionList = _renderSessionList;
window._saveCurrentSession = _saveCurrentSession;

async function loadProjectsIntoSelect() {
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

function onProjectSelectChange() {
  const sel = document.getElementById('project-select');
  if (!sel) return;
  if (sel.value) localStorage.setItem('layla_active_project_id', sel.value);
  else localStorage.removeItem('layla_active_project_id');
  updateContextChip();
}

async function createProjectQuick() {
  const name = prompt('Project name?', 'My project');
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

window.loadProjectsIntoSelect = loadProjectsIntoSelect;
window.onProjectSelectChange = onProjectSelectChange;
window.createProjectQuick = createProjectQuick;
