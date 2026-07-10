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
// Line-based fence scanner — mirrors the server's routers/agent.py::_extract_artifacts so the
// client fallback produces the SAME artifacts as the server. Replaces a greedy
// /```(\w*)\n([\s\S]*?)```/g regex that silently dropped: (a) blocks whose fence carried an info
// string like "```python title=x" (\w* stopped at the space), (b) the final block of a reply cut
// off mid-stream with no closing fence, and (c) ~~~-delimited blocks entirely.
export function laylaExtractArtifacts(text) {
  if (!text) return [];
  const found = [];
  const lines = String(text).split('\n');
  const n = lines.length;
  let i = 0;
  while (i < n && found.length < 20) {
    const open = lines[i].match(/^\s*(`{3,}|~{3,})(.*)$/);
    if (!open) { i += 1; continue; }
    const fenceChar = open[1][0];                 // '`' or '~' — the close must use the same char
    const closeRe = new RegExp('^\\s*' + (fenceChar === '`' ? '`' : '~') + '{3,}\\s*$');
    const info = (open[2] || '').trim();
    const lang = (info ? info.split(/\s+/)[0] : 'text') || 'text';   // first token of the info string
    const body = [];
    let j = i + 1;
    let closed = false;
    while (j < n) {
      if (closeRe.test(lines[j])) { closed = true; break; }
      body.push(lines[j]);
      j += 1;
    }
    let content = body.join('\n');
    if (closed && body.length) content += '\n';   // the newline that preceded the closing fence
    if (content.trim()) {
      const nLines = content.replace(/\n+$/, '').split('\n').length;
      if (nLines >= 2) {                           // skip trivial one-liners (parity with server)
        const art = { id: 'art_' + Math.random().toString(36).slice(2, 8), lang, content, ts: Date.now() };
        if (!closed) art.truncated = true;          // reply cut before the closing fence
        found.push(art);
      }
    }
    i = closed ? (j + 1) : n;
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

// Accepts EITHER a pre-extracted artifact array (the server's response_payload['artifacts'] /
// SSE done-frame 'artifacts', already parsed by the hardened server scanner) OR a raw reply
// string (falls back to the client scanner above). Prefer passing the server list when present.
export function laylaIngestArtifacts(source) {
  if (!source) return;
  const arts = Array.isArray(source) ? source : laylaExtractArtifacts(source);
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
