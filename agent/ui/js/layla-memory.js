/**
 * Layla UI — Memory browser (Phase 1.3)
 * Paginated browse, type/keyword filter, edit/delete for learnings.
 * Depends on: showToast (layla-app.js)
 */

let _memPage = 0;
let _memTotal = 0;
const _MEM_LIMIT = 20;

// ─── Sub-tab switching ────────────────────────────────────────────────────────
function showMemorySubTab(sub) {
  document.querySelectorAll('[data-mem-subpage]').forEach(el => {
    el.style.display = el.getAttribute('data-mem-subpage') === sub ? '' : 'none';
  });
  document.querySelectorAll('[data-mem-sub]').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-mem-sub') === sub);
  });
  if (sub === 'browse' && !_memTotal) laylaMemBrowse(0);
}

// ─── Browse / load ────────────────────────────────────────────────────────────
async function laylaMemBrowse(page) {
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

function _renderMemList(items, listEl) {
  if (!listEl) return;
  if (!items.length) {
    listEl.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">No learnings found.</span>';
    return;
  }
  listEl.innerHTML = items.map(r => {
    const conf = Math.round((r.confidence || 0.5) * 100);
    const confColor = conf >= 80 ? '#4caf50' : conf >= 50 ? '#f7c94b' : '#e74c3c';
    return `<div class="mem-item" data-id="${r.id}" style="border:1px solid var(--border);border-radius:4px;padding:7px 8px;margin-bottom:5px;background:var(--code-bg)">
      <div style="display:flex;align-items:flex-start;gap:6px">
        <span style="font-size:0.6rem;color:var(--asp);min-width:56px;text-align:center;padding:2px 4px;border:1px solid var(--asp);border-radius:2px;margin-top:1px">${_mesc(r.type || 'fact')}</span>
        <div style="flex:1;min-width:0">
          <div id="mem-content-${r.id}" style="font-size:0.7rem;color:var(--text);word-break:break-word;margin-bottom:4px">${_mesc(r.content || '')}</div>
          <div style="font-size:0.6rem;color:var(--text-dim);display:flex;gap:8px;flex-wrap:wrap">
            <span style="color:${confColor}">conf: ${conf}%</span>
            ${r.tags ? `<span>${_mesc(r.tags)}</span>` : ''}
            ${r.created_at ? `<span>${_mesc(r.created_at.slice(0,10))}</span>` : ''}
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

// ─── Inline edit ──────────────────────────────────────────────────────────────
function laylaMemEdit(id) {
  document.querySelectorAll('[id^="mem-edit-"]').forEach(el => el.style.display = 'none');
  const panel = document.getElementById(`mem-edit-${id}`);
  if (panel) panel.style.display = '';
  const ta = document.getElementById(`mem-edit-ta-${id}`);
  if (ta) { ta.value = ta.value; ta.focus(); }
}

function laylaMemCancelEdit(id) {
  const panel = document.getElementById(`mem-edit-${id}`);
  if (panel) panel.style.display = 'none';
}

async function laylaMemSaveEdit(id) {
  const ta = document.getElementById(`mem-edit-ta-${id}`);
  if (!ta) return;
  const content = ta.value.trim();
  if (!content) { showToast && showToast('Content cannot be empty'); return; }
  try {
    const res = await fetch(`/memory/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'save failed');
    // Update displayed text
    const disp = document.getElementById(`mem-content-${id}`);
    if (disp) disp.textContent = content;
    laylaMemCancelEdit(id);
    showToast && showToast('Learning updated');
  } catch (err) {
    showToast && showToast(`Error: ${err.message}`);
  }
}

// ─── Delete ───────────────────────────────────────────────────────────────────
async function laylaMemDelete(id) {
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
    showToast && showToast('Learning deleted');
  } catch (err) {
    showToast && showToast(`Error: ${err.message}`);
  }
}

function _mesc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
