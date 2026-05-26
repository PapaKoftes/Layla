/**
 * components/search.js — Global smart search across conversations, learnings, workspace, knowledge.
 *
 * Converted from js/layla-search.js (top-level -> ES module).
 * Depends on: services/utils.js (showToast, escapeHtml)
 */

import { showToast } from '../services/utils.js';

// ── State ───────────────────────────────────────────────────────────────────
let _searchTimer = null;
let _searchAbort = null;

// ── HTML escaping (local shorthand) ─────────────────────────────────────────
function _esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Public API ──────────────────────────────────────────────────────────────
export function laylaGlobalSearchInput(q) {
  clearTimeout(_searchTimer);
  if (!q || !q.trim()) { laylaGlobalSearchClose(); return; }
  _searchTimer = setTimeout(() => _runGlobalSearch(q.trim()), 320);
}

export function laylaGlobalSearchKey(e) {
  if (e.key === 'Escape') { laylaGlobalSearchClose(); return; }
  if (e.key === 'Enter') {
    clearTimeout(_searchTimer);
    const q = e.target.value.trim();
    if (q) _runGlobalSearch(q);
  }
}

async function _runGlobalSearch(q) {
  const drop = document.getElementById('global-search-dropdown');
  if (!drop) return;
  drop.style.display = 'block';
  drop.innerHTML = '<div style="padding:10px 12px;color:var(--text-dim);font-size:0.7rem">Searching…</div>';

  if (_searchAbort) { try { _searchAbort.abort(); } catch (_) {} }
  _searchAbort = new AbortController();

  try {
    const res = await fetch(`/search?q=${encodeURIComponent(q)}&context=all&limit=20`, {
      signal: _searchAbort.signal,
    });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    _renderSearchResults(data, q);
  } catch (err) {
    if (err.name === 'AbortError') return;
    drop.innerHTML = '<div style="padding:10px 12px;color:var(--text-dim);font-size:0.7rem">Search failed — is the server running?</div>';
  }
}

function _renderSearchResults(data, q) {
  const drop = document.getElementById('global-search-dropdown');
  if (!drop) return;

  const conv = data.conversations || [];
  const learn = data.learnings || [];
  const ws = data.workspace || [];
  const know = data.knowledge || [];

  const total = conv.length + learn.length + ws.length + know.length;
  if (total === 0) {
    drop.innerHTML = `<div style="padding:10px 12px;color:var(--text-dim);font-size:0.7rem">No results for "${_esc(q)}"</div>`;
    return;
  }

  let html = '';

  if (conv.length) {
    html += `<div class="srch-group-header">Conversations</div>`;
    conv.forEach(r => {
      html += `<div class="srch-item" onclick="laylaSearchOpenConv('${_esc(r.id)}')">
        <span class="srch-title">${_esc(r.title || 'New chat')}</span>
        <span class="srch-meta">${_esc(r.match || '')} · ${_esc((r.updated_at || '').slice(0, 10))}</span>
      </div>`;
    });
  }
  if (learn.length) {
    html += `<div class="srch-group-header">Learnings</div>`;
    learn.forEach(r => {
      const snippet = (r.content || '').slice(0, 120);
      html += `<div class="srch-item" onclick="laylaSearchOpenMemory()">
        <span class="srch-title srch-mono">${_esc(snippet)}${snippet.length >= 120 ? '…' : ''}</span>
        <span class="srch-meta">${_esc(r.type || 'fact')} · score ${(r.score || 0).toFixed(2)}</span>
      </div>`;
    });
  }
  if (ws.length) {
    html += `<div class="srch-group-header">Workspace</div>`;
    ws.forEach(r => {
      const snippet = (r.snippet || '').slice(0, 100);
      html += `<div class="srch-item" onclick="laylaSearchOpenWorkspace(${JSON.stringify(r.path || '')})" style="cursor:pointer">
        <span class="srch-title srch-mono">${_esc(r.path || '')}</span>
        <span class="srch-meta srch-mono">${_esc(snippet)}${snippet.length >= 100 ? '…' : ''}</span>
      </div>`;
    });
  }
  if (know.length) {
    html += `<div class="srch-group-header">Knowledge</div>`;
    know.forEach(r => {
      const snippet = (r.snippet || '').slice(0, 100);
      html += `<div class="srch-item" onclick="laylaSearchOpenKnowledge()" style="cursor:pointer">
        <span class="srch-title">${_esc(r.source || '')}</span>
        <span class="srch-meta">${_esc(snippet)}${snippet.length >= 100 ? '…' : ''}</span>
      </div>`;
    });
  }

  drop.innerHTML = html;
}

export function laylaGlobalSearchClose() {
  const drop = document.getElementById('global-search-dropdown');
  if (drop) drop.style.display = 'none';
  if (_searchAbort) { try { _searchAbort.abort(); } catch (_) {} _searchAbort = null; }
}

export function laylaSearchOpenConv(id) {
  laylaGlobalSearchClose();
  const inputEl = document.getElementById('global-search-input');
  if (inputEl) inputEl.value = '';
  if (typeof window.laylaOpenConversation === 'function') {
    window.laylaOpenConversation(id);
  } else {
    showToast('Open the Chats rail to navigate to this conversation');
  }
}

export function laylaSearchOpenMemory() {
  laylaGlobalSearchClose();
  const inputEl = document.getElementById('global-search-input');
  if (inputEl) inputEl.value = '';
  if (typeof window.showMainPanel === 'function') window.showMainPanel('workspace');
  setTimeout(() => {
    if (typeof window.showMemorySubTab === 'function') window.showMemorySubTab('browse');
  }, 100);
}

export function laylaSearchOpenWorkspace(filePath) {
  laylaGlobalSearchClose();
  const inputEl = document.getElementById('global-search-input');
  if (inputEl) inputEl.value = '';
  if (typeof window.showMainPanel === 'function') window.showMainPanel('workspace');
  setTimeout(() => {
    if (typeof window.showWorkspaceSubtab === 'function') window.showWorkspaceSubtab('awareness');
    if (filePath) {
      const el = document.getElementById('workspace-path');
      if (el && !el.value) el.value = filePath;
      try { showToast('Workspace: ' + filePath); } catch (_) {}
    }
  }, 100);
}

export function laylaSearchOpenKnowledge() {
  laylaGlobalSearchClose();
  const inputEl = document.getElementById('global-search-input');
  if (inputEl) inputEl.value = '';
  if (typeof window.showMainPanel === 'function') window.showMainPanel('workspace');
  setTimeout(() => {
    if (typeof window.showWorkspaceSubtab === 'function') window.showWorkspaceSubtab('knowledge');
  }, 100);
}

// ── Init ────────────────────────────────────────────────────────────────────
export function initSearch() {
  // Close dropdown on outside click
  document.addEventListener('click', e => {
    const container = document.getElementById('global-search-container');
    if (container && !container.contains(e.target)) laylaGlobalSearchClose();
  }, true);

  // Inject scoped styles
  const s = document.createElement('style');
  s.textContent = `
    .srch-group-header {
      padding: 4px 12px;
      font-size: 0.6rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--asp, #9b59b6);
      border-top: 1px solid var(--border);
      margin-top: 2px;
    }
    .srch-group-header:first-child { border-top: none; margin-top: 0; }
    .srch-item {
      padding: 6px 12px;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 2px;
      transition: background 0.1s;
    }
    .srch-item:hover { background: rgba(255,255,255,0.06); }
    .srch-title { font-size: 0.72rem; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .srch-meta { font-size: 0.62rem; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .srch-mono { font-family: ui-monospace, monospace; }
  `;
  document.head.appendChild(s);
}
