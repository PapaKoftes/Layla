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

// i18n: window.t is installed by ui/core/i18n.js init. Fall back to the key's default if it isn't
// ready yet (never render "undefined"). Keys live under mem.* in ui/locales/*.json.
function T(key, fallback, params){ try{ if(window.t){ const v=window.t(key,params); if(v&&v!==key) return v; } }catch(_){}; let s=fallback; if(params) for(const k in params) s=s.replace("{"+k+"}",params[k]); return s; }

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
  if (sub === 'about') renderMemoryAbout();
}

// ── "About you": what Layla knows (GET /memory/about) ───────────────────────
// Internal user_identity keys (calibration/maturity/bookkeeping) are NOT facts about the
// user — hide them so the panel reads like Claude/ChatGPT "memories about you".
const _MEM_ABOUT_INTERNAL = /^(stat_|maturity_|interaction_history|tutorial|main_aspect|personality_last|last_wakeup|earned_title|quiz_completed|_migrated|response$|voice_adjustment|custom_|frame_)/i;

function _memAboutIsFact(key, val) {
  const k = String(key || '').toLowerCase();
  if (_MEM_ABOUT_INTERNAL.test(k)) return false;
  const sv = String(val == null ? '' : val).trim();
  if (!sv) return false;
  if (sv.startsWith('{') || sv.startsWith('[')) return false;  // serialized blobs aren't facts
  return true;
}

function _memAboutSection(title, bodyHtml) {
  return `<div style="margin:0 0 12px"><div style="font-size:0.62rem;text-transform:uppercase;letter-spacing:0.08em;color:var(--asp);margin-bottom:5px">${_mesc(title)}</div>${bodyHtml}</div>`;
}

export async function renderMemoryAbout() {
  const box = document.getElementById('mem-about');
  const sum = document.getElementById('mem-about-summary');
  if (!box) return;
  box.innerHTML = `<span style="color:var(--text-dim)">${_mesc(T('mem.loading', 'Loading…'))}</span>`;
  let d;
  try {
    d = await (await fetch('/memory/about')).json();
  } catch (err) {
    box.innerHTML = `<span style="color:var(--text-dim)">${_mesc(T('mem.about.load_error', 'Couldn\'t load: {err}', { err: String(err) }))}</span>`;
    return;
  }
  const parts = [];

  // Durable facts (identity KV) — each with a forget (✕) control.
  const idEntries = Object.entries(d.identity || {}).filter(([k, v]) => _memAboutIsFact(k, v));
  if (idEntries.length) {
    const rows = idEntries.map(([k, v]) =>
      `<div class="mem-fact" data-key="${_mesc(k)}" style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;border:1px solid var(--border);border-left:3px solid var(--asp-morrigan,var(--asp));border-radius:4px;padding:6px 8px;margin-bottom:4px;background:var(--code-bg)">
        <div><span style="color:var(--text-dim);font-size:0.62rem">${_mesc(k.replace(/_/g, ' '))}</span><br><span style="color:var(--text)">${_mesc(v)}</span></div>
        <button type="button" title="${_mesc(T('mem.about.forget_this', 'Forget this'))}" data-action="laylaForgetIdentity" data-arg="${_mesc(k)}" style="background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:0.85rem;line-height:1">✕</button>
      </div>`).join('');
    parts.push(_memAboutSection(T('mem.about.durable_facts', 'Durable facts'), rows));
  }

  // People & bonds
  const rels = d.relationship_memories || [];
  if (rels.length) {
    const rows = rels.map(r =>
      `<div style="border-left:2px solid var(--asp-nyx,var(--violet));padding:3px 8px;margin-bottom:3px"><span style="color:var(--text)">${_mesc(r.content || r.summary || r.memory || '')}</span> <span style="color:var(--text-dim);font-size:0.6rem">${_mesc(_relTime(r.created_at))}</span></div>`).join('');
    parts.push(_memAboutSection(T('mem.about.people_bonds', 'People & bonds'), rows));
  }

  // Timeline
  const tl = d.timeline || [];
  if (tl.length) {
    const rows = tl.map(e =>
      `<div style="display:flex;gap:8px;margin-bottom:3px"><span style="color:var(--asp-cassandra,var(--asp));font-size:0.6rem;white-space:nowrap">${_mesc(_relTime(e.created_at))}</span><span style="color:var(--text)">${_mesc(e.description || e.summary || e.content || e.event || '')}</span></div>`).join('');
    parts.push(_memAboutSection(T('mem.about.timeline', 'Timeline'), rows));
  }

  // Goals
  const goals = d.goals || [];
  if (goals.length) {
    const rows = goals.map(g =>
      `<div style="border-left:2px solid var(--asp-lilith,var(--asp));padding:3px 8px;margin-bottom:3px">${_mesc(g.goal || g.title || g.description || g.text || '')}${g.progress != null ? ` <span style="color:var(--text-dim);font-size:0.6rem">(${_mesc(g.progress)}%)</span>` : ''}</div>`).join('');
    parts.push(_memAboutSection(T('mem.about.goals', 'Goals'), rows));
  }

  if (sum) {
    sum.textContent = T('mem.about.summary', '{facts} facts · {bonds} bonds · {events} events · {goals} goals · {learnings} learnings', {
      facts: idEntries.length, bonds: rels.length, events: tl.length, goals: goals.length, learnings: d.learnings_count || 0,
    });
  }
  box.innerHTML = parts.length
    ? parts.join('')
    : `<span style="color:var(--text-dim)">${_mesc(T('mem.about.empty', 'Nothing yet. As you talk and work, Layla files what matters about you here — you can edit or forget any of it.'))}</span>`;
}

export async function laylaForgetIdentity(key) {
  if (!key) return;
  if (!(await laylaConfirm(T('mem.forget.confirm', 'Forget what Layla knows for "{key}"?', { key: String(key).replace(/_/g, ' ') })))) return;
  try {
    const res = await fetch(`/memory/identity/${encodeURIComponent(key)}`, { method: 'DELETE' });
    const d = await res.json().catch(() => ({}));
    if (d && d.ok !== false) {
      const el = document.querySelector(`.mem-fact[data-key="${CSS.escape(key)}"]`);
      if (el) el.remove();
      showToast(T('mem.forget.done', 'Forgotten'));
    } else {
      showToast(T('mem.forget.error', 'Could not forget: {err}', { err: (d && d.error) || res.status }));
    }
  } catch (e) {
    showToast(T('mem.forget.failed', 'Forget failed'));
  }
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
  if (listEl) listEl.innerHTML = `<span style="color:var(--text-dim);font-size:0.7rem">${_mesc(T('mem.loading', 'Loading…'))}</span>`;

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
    if (listEl) listEl.innerHTML = `<span style="color:var(--text-dim);font-size:0.7rem">${_mesc(T('mem.browse.error', 'Error: {err}', { err: String(err) }))}</span>`;
  }
}

// Human-readable, colour-coded kind labels (raw kinds are opaque: outcome, user_fact…).
const _MEM_KIND = {
  user_fact:  { key: 'kind.user_fact',  label: 'You told me', color: '#5ac8fa' },
  fact:       { key: 'kind.fact',       label: 'Fact',        color: '#5ac8fa' },
  preference: { key: 'kind.preference', label: 'Preference',  color: '#c084fc' },
  strategy:   { key: 'kind.strategy',   label: 'What worked', color: '#4caf50' },
  outcome:    { key: 'kind.outcome',    label: 'Outcome',     color: '#8aa0b4' },
  general:    { key: 'kind.general',    label: 'Learned',     color: '#f7c94b' },
};
function _memKind(t) {
  const m = _MEM_KIND[String(t || 'general')];
  if (m) return { label: T('mem.' + m.key, m.label), color: m.color };
  return { label: String(t || 'general'), color: 'var(--asp)' };
}
function _relTime(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return String(iso).slice(0, 10);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return T('mem.rel.now', 'just now');
  if (s < 5400) return T('mem.rel.m', '{n}m ago', { n: Math.round(s / 60) });
  if (s < 129600) return T('mem.rel.h', '{n}h ago', { n: Math.round(s / 3600) });
  const d = Math.round(s / 86400);
  return d < 30 ? T('mem.rel.d', '{n}d ago', { n: d }) : String(iso).slice(0, 10);
}

function _renderMemList(items, listEl) {
  if (!listEl) return;
  if (!items.length) {
    listEl.innerHTML = `<span style="color:var(--text-dim);font-size:0.7rem">${_mesc(T('mem.browse.empty', 'No learnings yet — things you tell Layla to remember, and what she picks up as you work, show up here.'))}</span>`;
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
            <span style="color:${confColor}" title="${_mesc(T('mem.item.confidence', 'confidence'))}">●&nbsp;${conf}%</span>
            ${r.tags ? `<span title="${_mesc(T('mem.item.tags', 'tags'))}">#${_mesc(String(r.tags).replace(/,/g, ' #'))}</span>` : ''}
            ${r.created_at ? `<span title="${_mesc(r.created_at)}">${_mesc(_relTime(r.created_at))}</span>` : ''}
          </div>
        </div>
        <div style="display:flex;gap:3px;flex-shrink:0">
          <button type="button" onclick="laylaMemEdit(${r.id})" class="approve-btn" style="font-size:0.6rem;padding:2px 5px" title="${_mesc(T('mem.item.edit', 'Edit'))}">✎</button>
          <button type="button" onclick="laylaMemDelete(${r.id})" style="font-size:0.6rem;padding:2px 5px;background:transparent;border:1px solid var(--border);color:var(--text-dim);border-radius:3px;cursor:pointer" title="${_mesc(T('mem.item.delete', 'Delete'))}">✕</button>
        </div>
      </div>
      <div id="mem-edit-${r.id}" style="display:none;margin-top:6px">
        <textarea id="mem-edit-ta-${r.id}" style="width:100%;min-height:64px;box-sizing:border-box;font-size:0.68rem;padding:6px;background:var(--bg-panel,#1a1a2e);color:var(--text);border:1px solid var(--asp);border-radius:3px;resize:vertical">${_mesc(r.content || '')}</textarea>
        <div style="display:flex;gap:4px;margin-top:4px">
          <button type="button" onclick="laylaMemSaveEdit(${r.id})" class="approve-btn" style="font-size:0.62rem;padding:2px 6px">${_mesc(T('mem.item.save', 'Save'))}</button>
          <button type="button" onclick="laylaMemCancelEdit(${r.id})" class="tab-btn" style="font-size:0.62rem;padding:2px 6px;background:transparent;border-color:var(--border);color:var(--text-dim)">${_mesc(T('mem.item.cancel', 'Cancel'))}</button>
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
    <button type="button" onclick="laylaMemBrowse(${_memPage - 1})" ${_memPage <= 0 ? 'disabled' : ''} class="approve-btn" style="font-size:0.6rem;padding:2px 6px">${_mesc(T('mem.pager.prev', '‹ Prev'))}</button>
    <span style="flex:1;text-align:center">${_mesc(T('mem.pager.page', 'Page {page} / {total}  ({showing} of {count})', { page: _memPage + 1, total: totalPages, showing, count: _memTotal }))}</span>
    <button type="button" onclick="laylaMemBrowse(${_memPage + 1})" ${_memPage + 1 >= totalPages ? 'disabled' : ''} class="approve-btn" style="font-size:0.6rem;padding:2px 6px">${_mesc(T('mem.pager.next', 'Next ›'))}</button>
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
  if (!content) { showToast(T('mem.edit.empty', 'Content cannot be empty')); return; }
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
    showToast(T('mem.edit.updated', 'Learning updated'));
  } catch (err) {
    showToast(T('mem.browse.error', 'Error: {err}', { err: err.message }));
  }
}

// ── Delete ──────────────────────────────────────────────────────────────────
export async function laylaMemDelete(id) {
  if (!(await laylaConfirm(T('mem.delete.confirm', 'Delete this learning?')))) return;
  try {
    const res = await fetch(`/memory/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'delete failed');
    const item = document.querySelector(`.mem-item[data-id="${id}"]`);
    if (item) item.remove();
    _memTotal = Math.max(0, _memTotal - 1);
    const pagerEl = document.getElementById('mem-browse-pager');
    _renderMemPager(pagerEl);
    showToast(T('mem.delete.done', 'Learning deleted'));
  } catch (err) {
    showToast(T('mem.browse.error', 'Error: {err}', { err: err.message }));
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
      if (!/\.zip$/i.test(f.name)) { showToast(T('mem.import.pick_zip', 'Pick a .zip memory bundle')); return; }
      showToast(T('mem.import.importing', 'Importing memory bundle…'));
      try {
        const fd = new FormData();
        fd.append('file', f, f.name);
        const res = await fetch('/memory/import', { method: 'POST', body: fd });
        const data = await res.json();
        if (data.ok === false) throw new Error(data.error || data.detail || 'import failed');
        const kn = (data.knowledge_imported || []).length;
        const le = data.learnings_added || 0;
        showToast(T('mem.import.done', 'Imported {docs} docs · {learnings} learnings', { docs: kn, learnings: le }));
      } catch (err) {
        showToast(T('mem.import.error', 'Import error: {err}', { err: err.message }));
      }
    });
  }
  inp.click();
}


// ── Memory self-consistency door (verification + conflicts) ──────────────────
// Backend was complete (POST /memory/verification/run, GET /memory/conflicts) but had no UI.
export async function runMemorySelfCheck() {
  const out = document.getElementById('mem-selfcheck-result');
  if (out) out.textContent = T('mem.selfcheck.running', 'Running self-check…');
  try {
    const res = await fetch('/memory/verification/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const data = await res.json().catch(() => ({}));
    let conflicts = [];
    try {
      const cr = await fetch('/memory/conflicts');
      const cd = await cr.json().catch(() => ({}));
      conflicts = (cd && cd.conflicts) || [];
    } catch (_) { /* conflicts are best-effort */ }
    if (out) {
      const pick = (...keys) => { for (const k of keys) { if (data && data[k] != null) return data[k]; } return null; };
      const scanned = pick('checked', 'sample', 'scanned', 'verified');
      const pruned = pick('pruned', 'removed', 'deleted') ?? 0;
      let html = '<div style="color:var(--text-dim);font-size:0.66rem;margin-top:4px">' + _mesc(T('mem.selfcheck.label', 'Self-check'))
        + (scanned != null ? (' · ' + _mesc(T('mem.selfcheck.scanned', 'scanned {n}', { n: String(scanned) }))) : '')
        + ' · ' + _mesc(T('mem.selfcheck.pruned', 'pruned {n}', { n: String(pruned) })) + '</div>';
      if (conflicts.length) {
        html += '<div style="margin-top:6px;font-size:0.66rem;color:#ffb454">' + _mesc(T('mem.selfcheck.conflicts', '{n} conflict(s):', { n: conflicts.length })) + '</div>';
        html += conflicts.slice(0, 12).map((c) => {
          const txt = c.summary || c.description || c.detail
            || (c.new_content && c.existing_content ? (c.new_content + ' <-> ' + c.existing_content) : JSON.stringify(c));
          return '<div style="font-size:0.64rem;color:var(--text);margin:2px 0">- ' + escapeHtml(String(txt).slice(0, 140)) + '</div>';
        }).join('');
      } else {
        html += '<div style="margin-top:6px;font-size:0.66rem;color:#4dff88">' + _mesc(T('mem.selfcheck.no_conflicts', 'No conflicts found — memory looks consistent.')) + '</div>';
      }
      out.innerHTML = html;
    }
    showToast(T('mem.selfcheck.complete', 'Memory self-check complete'));
  } catch (_e) {
    if (out) out.textContent = T('mem.selfcheck.failed_log', 'Self-check failed — see server logs.');
    showToast(T('mem.selfcheck.failed', 'Self-check failed'));
  }
}
