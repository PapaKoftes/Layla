/**
 * components/memory.js — Memory browser with paginated browse, edit/delete.
 *
 * Converted from js/layla-memory.js (top-level -> ES module).
 * Depends on: services/utils.js (showToast, escapeHtml), services/utils.js (laylaConfirm)
 */

import { showToast, escapeHtml, laylaConfirm } from '../services/utils.js';

// ── State ───────────────────────────────────────────────────────────────────
let _memPage = 0;
let _memTotal = 0;
const _MEM_LIMIT = 20;

// ── HTML escaping (local shorthand) ─────────────────────────────────────────
function _mesc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Sub-tab switching ───────────────────────────────────────────────────────
export function showMemorySubTab(sub) {
  document.querySelectorAll('[data-mem-subpage]').forEach(el => {
    el.style.display = el.getAttribute('data-mem-subpage') === sub ? '' : 'none';
  });
  document.querySelectorAll('[data-mem-sub]').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-mem-sub') === sub);
  });
  if (sub === 'browse' && !_memTotal) laylaMemBrowse(0);
}

// ── Browse / load ───────────────────────────────────────────────────────────
export async function laylaMemBrowse(page) {
  if (typeof page !== 'number') page = 0;
  _memPage = page;

  const typeEl = document.getElementById('mem-browse-type');
  const sortEl = document.getElementById('mem-browse-sort');
  const qEl    = document.getElementById('mem-browse-q');

  const type = typeEl ? typeEl.value : '';
  const sort = sortEl ? sortEl.value : 'recent';
  const q    = qEl    ? qEl.value.trim() : '';

  const listEl  = document.getElementById('mem-browse-list');
  const pagerEl = document.getElementById('mem-browse-pager');
  if (listEl) listEl.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Loading…</span>';

  try {
    const params = new URLSearchParams({ page, limit: _MEM_LIMIT, sort });
    if (type) params.set('type', type);
    if (q)    params.set('q', q);

    const res = await fetch(`/memory/browse?${params}`);
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();

    if (!data.ok) throw new Error(data.error || 'unknown error');
    _memTotal = data.total || 0;
    _renderMemList(data.learnings || [], listEl);
    _renderMemPager(pagerEl);
  } catch (err) {
    if (listEl) listEl.innerHTML = `<span style="color:var(--text-dim);font-size:0.7rem">Error: ${_mesc(String(err))}</span>`;
  }
}

// Human-readable, colour-coded kind labels (raw kinds are opaque: outcome, user_fact…).
const _MEM_KIND = {
  user_fact:  { label: 'You told me', color: '#5ac8fa' },
  fact:       { label: 'Fact',        color: '#5ac8fa' },
  preference: { label: 'Preference',  color: '#c084fc' },
  strategy:   { label: 'What worked', color: '#4caf50' },
  outcome:    { label: 'Outcome',     color: '#8aa0b4' },
  general:    { label: 'Learned',     color: '#f7c94b' },
};
function _memKind(t) { return _MEM_KIND[String(t || 'general')] || { label: String(t || 'general'), color: 'var(--asp)' }; }
function _relTime(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return String(iso).slice(0, 10);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return 'just now';
  if (s < 5400) return Math.round(s / 60) + 'm ago';
  if (s < 129600) return Math.round(s / 3600) + 'h ago';
  const d = Math.round(s / 86400);
  return d < 30 ? d + 'd ago' : String(iso).slice(0, 10);
}

function _renderMemList(items, listEl) {
  if (!listEl) return;
  if (!items.length) {
    listEl.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">No learnings yet — things you tell Layla to remember, and what she picks up as you work, show up here.</span>';
    return;
  }
  listEl.innerHTML = items.map(r => {
    const conf = Math.round((r.confidence || 0.5) * 100);
    const confColor = conf >= 80 ? '#4caf50' : conf >= 50 ? '#f7c94b' : '#e74c3c';
    const kind = _memKind(r.type);
    return `<div class="mem-item" data-id="${r.id}" style="border:1px solid var(--border);border-left:3px solid ${kind.color};border-radius:4px;padding:7px 8px;margin-bottom:5px;background:var(--code-bg)">
      <div style="display:flex;align-items:flex-start;gap:6px">
        <span style="font-size:0.58rem;font-weight:600;color:${kind.color};min-width:64px;text-align:center;padding:2px 4px;border:1px solid ${kind.color};border-radius:3px;margin-top:1px;white-space:nowrap">${_mesc(kind.label)}</span>
        <div style="flex:1;min-width:0">
          <div id="mem-content-${r.id}" style="font-size:0.72rem;line-height:1.4;color:var(--text);word-break:break-word;margin-bottom:4px">${_mesc(r.content || '')}</div>
          <div style="font-size:0.6rem;color:var(--text-dim);display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <span style="color:${confColor}" title="confidence">●&nbsp;${conf}%</span>
            ${r.tags ? `<span title="tags">#${_mesc(String(r.tags).replace(/,/g, ' #'))}</span>` : ''}
            ${r.created_at ? `<span title="${_mesc(r.created_at)}">${_mesc(_relTime(r.created_at))}</span>` : ''}
          </div>
        </div>
        <div style="display:flex;gap:3px;flex-shrink:0">
          <button type="button" onclick="laylaMemEdit(${r.id})" class="approve-btn" style="font-size:0.6rem;padding:2px 5px" title="Edit">✎</button>
          <button type="button" onclick="laylaMemDelete(${r.id})" style="font-size:0.6rem;padding:2px 5px;background:transparent;border:1px solid var(--border);color:var(--text-dim);border-radius:3px;cursor:pointer" title="Delete">✕</button>
        </div>
      </div>
      <div id="mem-edit-${r.id}" style="display:none;margin-top:6px">
        <textarea id="mem-edit-ta-${r.id}" style="width:100%;min-height:64px;box-sizing:border-box;font-size:0.68rem;padding:6px;background:var(--bg-panel,#1a1a2e);color:var(--text);border:1px solid var(--asp);border-radius:3px;resize:vertical">${_mesc(r.content || '')}</textarea>
        <div style="display:flex;gap:4px;margin-top:4px">
          <button type="button" onclick="laylaMemSaveEdit(${r.id})" class="approve-btn" style="font-size:0.62rem;padding:2px 6px">Save</button>
          <button type="button" onclick="laylaMemCancelEdit(${r.id})" class="tab-btn" style="font-size:0.62rem;padding:2px 6px;background:transparent;border-color:var(--border);color:var(--text-dim)">Cancel</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

function _renderMemPager(pagerEl) {
  if (!pagerEl) return;
  const totalPages = Math.max(1, Math.ceil(_memTotal / _MEM_LIMIT));
  const showing = Math.min((_memPage + 1) * _MEM_LIMIT, _memTotal);
  pagerEl.innerHTML = `
    <button type="button" onclick="laylaMemBrowse(${_memPage - 1})" ${_memPage <= 0 ? 'disabled' : ''} class="approve-btn" style="font-size:0.6rem;padding:2px 6px">‹ Prev</button>
    <span style="flex:1;text-align:center">Page ${_memPage + 1} / ${totalPages} &nbsp;(${showing} of ${_memTotal})</span>
    <button type="button" onclick="laylaMemBrowse(${_memPage + 1})" ${_memPage + 1 >= totalPages ? 'disabled' : ''} class="approve-btn" style="font-size:0.6rem;padding:2px 6px">Next ›</button>
  `;
}

// ── Inline edit ─────────────────────────────────────────────────────────────
export function laylaMemEdit(id) {
  document.querySelectorAll('[id^="mem-edit-"]').forEach(el => el.style.display = 'none');
  const panel = document.getElementById(`mem-edit-${id}`);
  if (panel) panel.style.display = '';
  const ta = document.getElementById(`mem-edit-ta-${id}`);
  if (ta) { ta.value = ta.value; ta.focus(); }
}

export function laylaMemCancelEdit(id) {
  const panel = document.getElementById(`mem-edit-${id}`);
  if (panel) panel.style.display = 'none';
}

export async function laylaMemSaveEdit(id) {
  const ta = document.getElementById(`mem-edit-ta-${id}`);
  if (!ta) return;
  const content = ta.value.trim();
  if (!content) { showToast('Content cannot be empty'); return; }
  try {
    const res = await fetch(`/memory/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'save failed');
    const disp = document.getElementById(`mem-content-${id}`);
    if (disp) disp.textContent = content;
    laylaMemCancelEdit(id);
    showToast('Learning updated');
  } catch (err) {
    showToast(`Error: ${err.message}`);
  }
}

// ── Delete ──────────────────────────────────────────────────────────────────
export async function laylaMemDelete(id) {
  if (!(await laylaConfirm('Delete this learning?'))) return;
  try {
    const res = await fetch(`/memory/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'delete failed');
    const item = document.querySelector(`.mem-item[data-id="${id}"]`);
    if (item) item.remove();
    _memTotal = Math.max(0, _memTotal - 1);
    const pagerEl = document.getElementById('mem-browse-pager');
    _renderMemPager(pagerEl);
    showToast('Learning deleted');
  } catch (err) {
    showToast(`Error: ${err.message}`);
  }
}

/**
 * POST /memory/import — restore a memory bundle ZIP (counterpart to the
 * ⬇ Memory bundle export link). Opens a file picker and uploads the chosen
 * .zip as multipart/form-data. Merges non-conflicting knowledge + learnings.
 */
export function laylaImportMemoryBundle() {
  let inp = document.getElementById('memory-import-file');
  if (!inp) {
    inp = document.createElement('input');
    inp.type = 'file';
    inp.id = 'memory-import-file';
    inp.accept = '.zip';
    inp.style.display = 'none';
    document.body.appendChild(inp);
    inp.addEventListener('change', async () => {
      const f = inp.files && inp.files[0];
      inp.value = '';
      if (!f) return;
      if (!/\.zip$/i.test(f.name)) { showToast('Pick a .zip memory bundle'); return; }
      showToast('Importing memory bundle…');
      try {
        const fd = new FormData();
        fd.append('file', f, f.name);
        const res = await fetch('/memory/import', { method: 'POST', body: fd });
        const data = await res.json();
        if (data.ok === false) throw new Error(data.error || data.detail || 'import failed');
        const kn = (data.knowledge_imported || []).length;
        const le = data.learnings_added || 0;
        showToast(`Imported ${kn} docs · ${le} learnings`);
      } catch (err) {
        showToast(`Import error: ${err.message}`);
      }
    });
  }
  inp.click();
}
