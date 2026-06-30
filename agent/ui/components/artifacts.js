/**
 * components/artifacts.js — Artifacts panel: code block extraction and management.
 *
 * Converted from js/layla-artifacts.js (top-level -> ES module).
 * Depends on: services/utils.js (showToast, escapeHtml)
 */

import { showToast, escapeHtml } from '../services/utils.js';

// ── State ───────────────────────────────────────────────────────────────────
const _artifacts = [];  // {id, lang, content, ts}
let _artifactEditId = null;

// ── Extraction ──────────────────────────────────────────────────────────────
export function laylaExtractArtifacts(text) {
  if (!text) return [];
  const found = [];
  const re = /```(\w*)\n([\s\S]*?)```/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const lang = (m[1] || 'text').trim();
    const content = m[2];
    if (!content.trim()) continue;
    const id = 'art_' + Math.random().toString(36).slice(2, 8);
    found.push({ id, lang, content, ts: Date.now() });
  }
  return found;
}

export function laylaArtifactsScan() {
  const chat = document.getElementById('chat');
  if (!chat) return;
  const bubbles = chat.querySelectorAll('.msg.layla .msg-bubble');
  let added = 0;
  bubbles.forEach(b => {
    const raw = b.getAttribute('data-raw') || b.textContent || '';
    const arts = laylaExtractArtifacts(raw);
    arts.forEach(a => {
      if (!_artifacts.find(x => x.content === a.content)) {
        _artifacts.unshift(a);
        added++;
      }
    });
  });
  _renderArtifactsList();
  if (added) showToast(`${added} artifact${added > 1 ? 's' : ''} extracted`);
}

export function laylaIngestArtifacts(responseText) {
  if (!responseText) return;
  const arts = laylaExtractArtifacts(responseText);
  if (!arts.length) return;
  arts.forEach(a => {
    if (!_artifacts.find(x => x.content === a.content)) {
      _artifacts.unshift(a);
    }
  });
  if (_artifacts.length > 40) _artifacts.splice(40);
  _renderArtifactsList();
  // Badge the tab if not active
  const tab = document.querySelector('.rcp-tab[data-rcp="artifacts"]');
  if (tab && !tab.classList.contains('active')) {
    tab.style.setProperty('--asp', 'var(--asp-warn, #f7c94b)');
    tab.title = `${arts.length} new artifact${arts.length > 1 ? 's' : ''}`;
  }
}

export function laylaArtifactsClear() {
  _artifacts.length = 0;
  _renderArtifactsList();
}

// ── Render ───────────────────────────────────────────────────────────────────
function _renderArtifactsList() {
  const el = document.getElementById('artifacts-list');
  if (!el) return;
  if (!_artifacts.length) {
    el.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Artifacts appear here when Layla generates code blocks.</span>';
    return;
  }
  el.innerHTML = _artifacts.map(a => {
    const preview = (a.content || '').slice(0, 120).replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const lines = (a.content || '').split('\n').length;
    return `<div class="artifact-card" id="${a.id}" style="background:var(--code-bg);border:1px solid var(--border);border-radius:4px;padding:8px;position:relative">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
        <span style="font-size:0.68rem;color:var(--asp);font-family:ui-monospace,monospace">${a.lang}</span>
        <span style="font-size:0.62rem;color:var(--text-dim)">${lines} line${lines !== 1 ? 's' : ''}</span>
      </div>
      <pre style="margin:0;font-size:0.62rem;max-height:80px;overflow:hidden;color:var(--text-dim);white-space:pre-wrap;word-break:break-all">${preview}${a.content.length > 120 ? '…' : ''}</pre>
      <div style="display:flex;gap:4px;margin-top:6px;flex-wrap:wrap">
        <button type="button" onclick="laylaArtifactCopy('${a.id}')" class="approve-btn" style="font-size:0.62rem;padding:2px 6px">Copy</button>
        <button type="button" onclick="laylaArtifactEdit('${a.id}')" class="approve-btn" style="font-size:0.62rem;padding:2px 6px">Edit &amp; send</button>
        <button type="button" onclick="laylaArtifactRemove('${a.id}')" class="tab-btn" style="font-size:0.62rem;padding:2px 6px;background:transparent;border-color:var(--border);color:var(--text-dim)">✕</button>
      </div>
    </div>`;
  }).join('');
}

// ── Actions ─────────────────────────────────────────────────────────────────
export function laylaArtifactCopy(id) {
  const a = _artifacts.find(x => x.id === id);
  if (!a) return;
  navigator.clipboard.writeText(a.content).then(() => {
    showToast('Copied to clipboard');
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = a.content;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast('Copied');
  });
}

export function laylaArtifactEdit(id) {
  const a = _artifacts.find(x => x.id === id);
  if (!a) return;
  _artifactEditId = id;
  const langEl = document.getElementById('artifact-edit-lang');
  if (langEl) langEl.textContent = a.lang || 'text';
  const contentEl = document.getElementById('artifact-edit-content');
  if (contentEl) contentEl.value = a.content;
  const overlay = document.getElementById('artifact-edit-overlay');
  if (overlay) overlay.style.display = 'flex';
}

export function laylaArtifactEditClose() {
  _artifactEditId = null;
  const overlay = document.getElementById('artifact-edit-overlay');
  if (overlay) overlay.style.display = 'none';
}

export function laylaArtifactCopyEdit() {
  const contentEl = document.getElementById('artifact-edit-content');
  if (contentEl) navigator.clipboard.writeText(contentEl.value).catch(() => {});
  showToast('Copied');
}

export function laylaArtifactSendEdit() {
  const contentEl = document.getElementById('artifact-edit-content');
  if (!contentEl) return;
  const content = contentEl.value;
  if (!content.trim()) return;
  laylaArtifactEditClose();
  const input = document.getElementById('msg-input');
  if (input) {
    input.value = 'Update this code:\n```\n' + content + '\n```';
    input.focus();
    showToast('Pasted into input — review and send');
  }
}

export function laylaArtifactRemove(id) {
  const idx = _artifacts.findIndex(x => x.id === id);
  if (idx >= 0) _artifacts.splice(idx, 1);
  _renderArtifactsList();
}

// ── Init: clear badge when Artifacts tab is activated ───────────────────────
export function initArtifacts() {
  document.querySelectorAll('.rcp-tab[data-rcp="artifacts"]').forEach(tab => {
    tab.addEventListener('click', () => {
      tab.style.removeProperty('--asp');
      tab.title = '';
    });
  });
}
