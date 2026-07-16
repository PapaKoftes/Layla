/**
 * components/workspace.js — Workspace panel refreshers.
 *
 * Converted from js/layla-workspace.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast)
 *
 * Handles: platform models/knowledge/plugins/projects/timeline, study plans,
 * skills, plans panel, workspace tools (awareness, memory inspector, symbol
 * search), memory search, file checkpoints, execution panels, agents panel,
 * and the panel-refresh routing helper.
 */

import { escapeHtml, showToast } from '../services/utils.js';
import { showMemorySubTab } from './memory.js';

// ── Helpers ─────────────────────────────────────────────────────────────────
function _el(id) { return document.getElementById(id); }

// ═════════════════════════════════════════════════════════════════════════════
//  PLATFORM PANELS
// ═════════════════════════════════════════════════════════════════════════════

export async function refreshPlatformModels() {
  const box = _el('platform-models');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/platform/models');
    const d = await r.json();
    const active = (d && d.active) ? String(d.active) : '';
    const models = Array.isArray(d && d.models) ? d.models : [];
    box.innerHTML = '<div><strong>Active</strong>: ' + escapeHtml(active || '—') + '</div>' +
      '<div style="margin-top:6px"><strong>Available</strong>: ' + escapeHtml(models.slice(0, 10).join(', ') || '—') + '</div>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Could not load models</span>'; }
}

export async function refreshPlatformKnowledge() {
  const box = _el('platform-knowledge');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/platform/knowledge');
    const d = await r.json();
    const learnings = Array.isArray(d && d.learnings) ? d.learnings : [];
    const summaries = Array.isArray(d && d.summaries) ? d.summaries : [];
    box.innerHTML =
      '<div><strong>Recent learnings</strong>:</div>' +
      '<div style="margin-top:4px;color:var(--text-dim)">' + escapeHtml(learnings.map(x => x.content || '').slice(0, 5).join(' · ') || '—') + '</div>' +
      '<div style="margin-top:10px"><strong>Conversation summaries</strong>:</div>' +
      '<div style="margin-top:4px;color:var(--text-dim)">' + escapeHtml(summaries.map(x => x.summary || '').slice(0, 3).join(' · ') || '—') + '</div>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Could not load knowledge</span>'; }
}

export async function refreshPlatformPlugins() {
  const box = _el('platform-plugins');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/platform/plugins');
    const d = await r.json();
    box.innerHTML =
      '<div><strong>Skills</strong>: ' + escapeHtml(String((d && d.skills_added) || 0)) + '</div>' +
      '<div><strong>Tools</strong>: ' + escapeHtml(String((d && d.tools_added) || 0)) + '</div>' +
      '<div><strong>Capabilities</strong>: ' + escapeHtml(String((d && d.capabilities_added) || 0)) + '</div>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Could not load plugins</span>'; }
}

export async function refreshPlatformProjects() {
  const box = _el('platform-projects');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';

  let ctx = null;
  try { const r = await fetch('/platform/projects'); ctx = await r.json(); } catch (_) {}

  let preset = null;
  const pid = (typeof localStorage !== 'undefined' ? (localStorage.getItem('layla_active_project_id') || '') : '').trim();
  if (pid) {
    try { const r2 = await fetch('/projects/' + encodeURIComponent(pid)); const d2 = await r2.json(); if (d2 && d2.ok && d2.project) preset = d2.project; } catch (_) {}
  }

  const html = [];
  html.push('<div class="panel-title">Project context</div>');
  if (ctx && (ctx.project_name || ctx.goals || ctx.lifecycle_stage || ctx.progress || ctx.blockers)) {
    html.push('<div><strong>Name</strong>: ' + escapeHtml(String(ctx.project_name || '—')) + '</div>');
    html.push('<div><strong>Stage</strong>: ' + escapeHtml(String(ctx.lifecycle_stage || '—')) + '</div>');
    html.push('<div style="margin-top:6px"><strong>Goals</strong>: <span style="color:var(--text-dim)">' + escapeHtml(String(ctx.goals || '')) + '</span></div>');
    html.push('<div style="margin-top:6px"><strong>Progress</strong>: <span style="color:var(--text-dim)">' + escapeHtml(String(ctx.progress || '')) + '</span></div>');
    html.push('<div style="margin-top:6px"><strong>Blockers</strong>: <span style="color:var(--text-dim)">' + escapeHtml(String(ctx.blockers || '')) + '</span></div>');
  } else {
    html.push('<div style="color:var(--text-dim)">No project context set yet.</div>');
  }

  html.push('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:10px 0">');
  html.push('<div><strong>Active preset</strong>: ' + escapeHtml(preset ? (preset.name || preset.id || '—') : (pid || '—')) + '</div>');
  if (preset) {
    html.push('<div style="color:var(--text-dim);margin-top:4px">WS: ' + escapeHtml(String(preset.workspace_root || '')) + '</div>');
    html.push('<div style="color:var(--text-dim)">Aspect default: ' + escapeHtml(String(preset.aspect_default || '')) + '</div>');
  } else {
    html.push('<div style="color:var(--text-dim);margin-top:4px">Select a preset in Prefs → Project preset.</div>');
  }

  html.push('<div style="margin-top:10px"><strong>Edit project context</strong></div>');
  html.push('<div style="display:flex;flex-direction:column;gap:6px;margin-top:6px">');
  html.push('<input id="pc_name" placeholder="Project name" value="' + escapeHtml(String((ctx && ctx.project_name) || '')) + '" />');
  html.push('<input id="pc_stage" placeholder="Lifecycle stage" value="' + escapeHtml(String((ctx && ctx.lifecycle_stage) || '')) + '" />');
  html.push('<textarea id="pc_goals" placeholder="Goals" style="min-height:60px">' + escapeHtml(String((ctx && ctx.goals) || '')) + '</textarea>');
  html.push('<textarea id="pc_progress" placeholder="Progress" style="min-height:50px">' + escapeHtml(String((ctx && ctx.progress) || '')) + '</textarea>');
  html.push('<textarea id="pc_blockers" placeholder="Blockers" style="min-height:50px">' + escapeHtml(String((ctx && ctx.blockers) || '')) + '</textarea>');
  html.push('<button type="button" class="tab-btn" id="pc_save_btn" style="margin-top:4px">Save</button>');
  html.push('<span id="pc_save_msg" style="color:var(--text-dim);font-size:0.7rem"></span>');
  html.push('</div>');

  box.innerHTML = html.join('');

  try {
    const btn = _el('pc_save_btn');
    if (btn) btn.onclick = async function () {
      const body = {
        project_name: ((_el('pc_name') || {}).value || '').trim(),
        lifecycle_stage: ((_el('pc_stage') || {}).value || '').trim(),
        goals: ((_el('pc_goals') || {}).value || '').trim(),
        progress: ((_el('pc_progress') || {}).value || '').trim(),
        blockers: ((_el('pc_blockers') || {}).value || '').trim(),
      };
      const msgEl = _el('pc_save_msg');
      if (msgEl) msgEl.textContent = 'Saving…';
      try {
        const r3 = await fetch('/project_context', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const d3 = await r3.json().catch(() => ({}));
        if (msgEl) msgEl.textContent = (d3 && d3.ok) ? 'Saved' : 'Save failed';
        try { if (typeof window.updateContextChip === 'function') window.updateContextChip(); } catch (_) {}
      } catch (_) { if (msgEl) msgEl.textContent = 'Save failed'; }
    };
  } catch (_) {}
}

export async function refreshPlatformTimeline() {
  const box = _el('platform-timeline');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/platform/knowledge');
    const d = await r.json();
    const tl = Array.isArray(d && d.timeline) ? d.timeline : [];
    box.innerHTML = tl.length
      ? tl.slice(0, 8).map(t => '<div style="margin:4px 0"><span style="color:var(--text-dim)">' + escapeHtml(String(t.event_type || '')) + '</span> ' + escapeHtml(String(t.content || '')) + '</div>').join('')
      : '<span style="color:var(--text-dim)">No timeline yet.</span>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Could not load timeline</span>'; }
}

// ═════════════════════════════════════════════════════════════════════════════
//  STUDY PLANS
// ═════════════════════════════════════════════════════════════════════════════

export async function refreshStudyPlans() {
  const box = _el('study-list');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/study_plans');
    const d = await r.json().catch(() => ({}));
    const plans = Array.isArray(d && d.plans) ? d.plans : [];
    if (!plans.length) { box.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">No active study plans yet.</span>'; return; }
    box.innerHTML = plans.slice(0, 20).map(p =>
      '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06);display:flex;justify-content:space-between;align-items:flex-start;gap:8px">' +
      '<div><div><strong>' + escapeHtml(String(p.topic || '')) + '</strong></div>' +
      '<div style="color:var(--text-dim);font-size:0.68rem">sessions: ' + escapeHtml(String(p.study_sessions != null ? p.study_sessions : 0)) + (p.last_studied ? (' · last: ' + escapeHtml(String(p.last_studied))) : '') + '</div></div>' +
      (p.id != null ? ('<button type="button" class="approve-btn" style="font-size:0.62rem;flex-shrink:0" data-action="deleteStudyPlan" data-arg="' + escapeHtml(String(p.id)) + '" title="Delete this study plan">✕</button>') : '') +
      '</div>'
    ).join('');
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Could not load study plans</span>'; }
}

// Delete a study plan (the DELETE endpoint existed but had no UI control).
export async function deleteStudyPlan(id) {
  if (id == null || id === '') return;
  try { await fetch('/study_plans/' + encodeURIComponent(id), { method: 'DELETE' }); } catch (_) {}
  try { refreshStudyPlans(); } catch (_) {}
}

export async function loadStudyPresetsAndSuggestions() {
  const presets = _el('study-presets');
  const sug = _el('study-suggestions');
  if (presets) presets.innerHTML = '';
  if (sug) sug.innerHTML = '';
  try {
    const r1 = await fetch('/study_plans/presets');
    const d1 = await r1.json().catch(() => ({}));
    const topics = Array.isArray(d1 && d1.topics) ? d1.topics : [];
    if (presets) presets.innerHTML = topics.slice(0, 16).map(t => '<button type="button" class="approve-btn" style="font-size:0.62rem" onclick="addStudyPlan(' + JSON.stringify(String(t)) + ')">' + escapeHtml(String(t)) + '</button>').join('');
  } catch (_) {}
  try {
    const r2 = await fetch('/study_plans/suggestions');
    const d2 = await r2.json().catch(() => ({}));
    const suggestions = Array.isArray(d2 && d2.suggestions) ? d2.suggestions : [];
    if (sug) sug.innerHTML = suggestions.slice(0, 16).map(t => '<button type="button" class="approve-btn" style="font-size:0.62rem" onclick="addStudyPlan(' + JSON.stringify(String(t)) + ')">' + escapeHtml(String(t)) + '</button>').join('');
  } catch (_) {}
}

export async function addStudyPlan(topicOverride) {
  const inp = _el('study-input');
  const topic = String(topicOverride || (inp && inp.value) || '').trim();
  if (!topic) return;
  if (inp) inp.value = '';
  try {
    const r = await fetch('/study_plans', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic }) });
    const d = await r.json().catch(() => ({}));
    showToast((d && d.ok) ? 'Added' : 'Add failed');
    try { refreshStudyPlans(); } catch (_) {}
  } catch (_) { showToast('Add failed'); }
}

export async function studyTopicFromChatInput() {
  const text = ((_el('msg-input') || {}).value || '').trim();
  if (!text) return;
  try {
    const r = await fetch('/study_plans/derive_topic', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text }) });
    const d = await r.json().catch(() => ({}));
    if (d && d.ok && d.topic) addStudyPlan(String(d.topic));
  } catch (_) {}
}

export function studyTopicFromLastUserMessage() {
  try {
    const chat = _el('chat');
    if (!chat) return;
    const rows = chat.querySelectorAll('.msg.msg-you .msg-bubble');
    const last = rows && rows.length ? String(rows[rows.length - 1].textContent || '').trim() : '';
    if (!last) return;
    fetch('/study_plans/derive_topic', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: last }) })
      .then(r => r.json())
      .then(d => { if (d && d.ok && d.topic) addStudyPlan(String(d.topic)); })
      .catch(() => {});
  } catch (_) {}
}

// ═════════════════════════════════════════════════════════════════════════════
//  SKILLS
// ═════════════════════════════════════════════════════════════════════════════

export async function refreshSkillsList() {
  const box = _el('platform-skills');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/skills');
    const d = await r.json().catch(() => ({}));
    const skills = Array.isArray(d && d.skills) ? d.skills : [];
    box.innerHTML = skills.length
      ? skills.slice(0, 40).map(s => '<div style="margin:4px 0"><strong>' + escapeHtml(String(s.name || '')) + '</strong><div style="color:var(--text-dim);font-size:0.68rem">' + escapeHtml(String(s.description || '')) + '</div></div>').join('')
      : '<span style="color:var(--text-dim)">No skills found.</span>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Could not load skills</span>'; }
}

// ═════════════════════════════════════════════════════════════════════════════
//  PLANS PANEL
// ═════════════════════════════════════════════════════════════════════════════

export async function refreshLaylaPlansPanel() {
  const listEl = _el('layla-plans-list');
  if (!listEl) return;
  listEl.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const wr = ((_el('workspace-path') || {}).value || '').trim();
    const q = wr ? ('?workspace_root=' + encodeURIComponent(wr) + '&limit=30') : '?limit=30';
    const r = await fetch('/plans' + q);
    const d = await r.json().catch(() => ({}));
    const plans = Array.isArray(d && d.plans) ? d.plans : [];
    if (!plans.length) { listEl.innerHTML = '<span style="color:var(--text-dim)">No plans for this workspace filter.</span>'; return; }
    listEl.innerHTML = plans.slice(0, 24).map(p => {
      const id = String(p.id || '');
      const g = escapeHtml(String(p.goal || '').slice(0, 120));
      const st = escapeHtml(String(p.status || ''));
      const sid = id.replace(/[^a-zA-Z0-9_-]/g, '_');
      return '<div style="margin:6px 0;padding:8px;border:1px solid rgba(255,255,255,0.06);border-radius:6px;background:rgba(0,0,0,0.15)">' +
        '<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><strong>' + g + '</strong>' +
        '<span style="color:var(--text-dim);font-size:0.68rem">' + st + '</span></div>' +
        '<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px">' +
        '<button type="button" class="approve-btn" onclick="laylaApprovePlan(' + JSON.stringify(id) + ')">Approve</button>' +
        '<button type="button" class="approve-btn" onclick="laylaExecutePlan(' + JSON.stringify(id) + ')">Execute</button>' +
        '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--asp);color:var(--asp)" onclick="typeof laylaShowPlanViz===\'function\'&&laylaShowPlanViz(' + JSON.stringify(id) + ')">⬡ Gantt</button>' +
        '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--border);color:var(--text-dim)" onclick="laylaExpandPlan(' + JSON.stringify(id) + ', ' + JSON.stringify(sid) + ')">Detail</button>' +
        '</div>' +
        '<pre id="plan-detail-' + sid + '" style="display:none;margin-top:8px;font-size:0.62rem;max-height:200px;overflow:auto;white-space:pre-wrap"></pre></div>';
    }).join('');
  } catch (_) { listEl.innerHTML = '<span style="color:var(--text-dim)">Could not load plans</span>'; }
}

export async function laylaApprovePlan(planId) {
  try {
    const r = await fetch('/plans/' + encodeURIComponent(planId) + '/approve', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    showToast(d.ok ? 'Plan approved' : (d.error || 'failed'));
    refreshLaylaPlansPanel();
  } catch (_) { showToast('Approve failed'); }
}

export async function laylaExecutePlan(planId) {
  const wp = ((_el('workspace-path') || {}).value || '').trim();
  const allowWriteEl = _el('allow-write');
  const allowRunEl = _el('allow-run');
  const allowWrite = allowWriteEl ? !!allowWriteEl.checked : false;
  const allowRun = allowRunEl ? !!allowRunEl.checked : false;
  try { if (typeof window.ensureLaylaConversationId === 'function') window.ensureLaylaConversationId(); } catch (_) {}
  try { if (typeof window.laylaHeaderProgressStart === 'function') window.laylaHeaderProgressStart(); } catch (_) {}
  try {
    const r = await fetch('/plans/' + encodeURIComponent(planId) + '/execute', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_root: wp, allow_write: allowWrite, allow_run: allowRun,
        aspect_id: (typeof window.currentAspect !== 'undefined') ? window.currentAspect : 'morrigan',
        conversation_id: (typeof window.currentConversationId !== 'undefined') ? window.currentConversationId : '',
      }),
    });
    const d = await r.json().catch(() => ({}));
    showToast(d.ok ? 'Execution finished' : (d.error || 'execute failed'));
    refreshLaylaPlansPanel();
  } catch (_) { showToast('Execute failed'); }
  finally { try { if (typeof window.laylaHeaderProgressStop === 'function') window.laylaHeaderProgressStop(); } catch (_) {} }
}

export async function laylaExpandPlan(planId, sid) {
  const pre = _el('plan-detail-' + sid);
  if (!pre) return;
  const on = pre.style.display !== 'block';
  pre.style.display = on ? 'block' : 'none';
  if (!on) return;
  pre.textContent = 'Loading…';
  try {
    const r = await fetch('/plans/' + encodeURIComponent(planId));
    const d = await r.json().catch(() => ({}));
    pre.textContent = (d && d.plan) ? JSON.stringify(d.plan, null, 2) : JSON.stringify(d, null, 2);
  } catch (_) { pre.textContent = 'Failed to load'; }
}

// ═════════════════════════════════════════════════════════════════════════════
//  UTILITY ACTIONS
// ═════════════════════════════════════════════════════════════════════════════

export async function laylaGitUndo() {
  try {
    const r = await fetch('/undo', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    showToast(d.ok ? (d.message || 'Undone') : (d.error || 'undo failed'));
  } catch (_) { showToast('Undo failed'); }
}

export async function laylaRunSetupAuto() {
  try {
    const r = await fetch('/setup/auto', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    showToast((d && d.ok) ? 'Auto-setup finished' : String((d && d.error) || 'failed'));
  } catch (_) { showToast('Auto-setup failed'); }
}

export async function laylaRunDoctor() {
  try {
    const r = await fetch('/doctor');
    const d = await r.json().catch(() => ({}));
    if (typeof window.addMsg === 'function') {
      window.addMsg('layla', '**Doctor snapshot**\n```json\n' + JSON.stringify(d, null, 2).slice(0, 8000) + '\n```');
    }
  } catch (_) { showToast('Doctor failed'); }
}

// ═════════════════════════════════════════════════════════════════════════════
//  WORKSPACE TOOLS
// ═════════════════════════════════════════════════════════════════════════════

export async function laylaRefreshWorkspaceAwareness() {
  const wp = ((_el('workspace-path') || {}).value || '').trim();
  const pulse = _el('workspace-awareness-pulse');
  const pulseTab = _el('workspace-awareness-tab-pulse');
  if (!wp) { showToast('Set workspace path first'); return; }
  if (pulse) pulse.style.display = 'inline';
  if (pulseTab) pulseTab.style.display = 'inline';
  try {
    const r = await fetch('/workspace/awareness/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_root: wp }) });
    const d = await r.json().catch(() => ({}));
    showToast(d.ok ? 'Awareness refresh started' : String(d.error || 'failed'));
  } catch (_) { showToast('Awareness refresh failed'); }
  finally { if (pulse) pulse.style.display = 'none'; if (pulseTab) pulseTab.style.display = 'none'; }
}

export async function laylaLoadProjectMemoryInspector() {
  const pre = _el('project-memory-inspector');
  const wp = ((_el('workspace-path') || {}).value || '').trim();
  if (!wp) { showToast('Set workspace path first'); return; }
  if (pre) pre.textContent = 'Loading…';
  try {
    const r = await fetch('/workspace/project_memory?workspace_root=' + encodeURIComponent(wp));
    const d = await r.json().catch(() => ({}));
    const sec = (d && d.project_memory) || {};
    const pick = ['modules', 'issues', 'plans', 'todos'];
    let out = '';
    for (let i = 0; i < pick.length; i++) {
      const k = pick[i];
      out += '## ' + k + '\n' + JSON.stringify(sec[k] != null ? sec[k] : (d[k] != null ? d[k] : null), null, 2).slice(0, 6000) + '\n\n';
    }
    if (pre) pre.textContent = out.trim() || JSON.stringify(d, null, 2).slice(0, 12000);
  } catch (e) { if (pre) pre.textContent = String(e); }
}

export async function laylaWorkspaceSymbolSearch() {
  const q = String((_el('workspace-symbol-query') || {}).value || '').trim();
  const wp = ((_el('workspace-path') || {}).value || '').trim();
  const box = _el('workspace-symbol-results');
  if (!q) { showToast('Enter a symbol or phrase'); return; }
  if (box) box.textContent = 'Searching…';
  try {
    const url = '/workspace/symbol_search?q=' + encodeURIComponent(q) + (wp ? '&workspace_root=' + encodeURIComponent(wp) : '');
    const r = await fetch(url);
    const d = await r.json().catch(() => ({}));
    if (box) box.textContent = JSON.stringify(d, null, 2).slice(0, 12000);
  } catch (e) { if (box) box.textContent = String(e); }
}

// ═════════════════════════════════════════════════════════════════════════════
//  MEMORY SEARCH
// ═════════════════════════════════════════════════════════════════════════════

export async function onMemorySearch(q) {
  const box = _el('memory-search-results');
  const query = String(q || '').trim();
  if (!box) return;
  if (!query) { box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Type to search learnings (semantic / FTS)</span>'; return; }
  box.innerHTML = '<span style="color:var(--text-dim)">Searching…</span>';
  try {
    const r = await fetch('/memories?q=' + encodeURIComponent(query) + '&n=8');
    const d = await r.json().catch(() => ({}));
    const items = Array.isArray(d && d.memories) ? d.memories : [];
    box.innerHTML = items.length
      ? items.map(m => '<div style="margin:6px 0;padding:6px;border-left:2px solid var(--asp);background:rgba(0,0,0,0.12)">' + escapeHtml(String(m || '')) + '</div>').join('')
      : '<span style="color:var(--text-dim)">No matches.</span>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Search failed</span>'; }
}

export async function runElasticsearchLearningSearch() {
  const q = String((_el('es-learning-search') || {}).value || '').trim();
  const box = _el('es-learning-results');
  if (!box) return;
  if (!q) { box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Enter a keyword query.</span>'; return; }
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/memory/elasticsearch/search?q=' + encodeURIComponent(q) + '&limit=20');
    const d = await r.json().catch(() => ({}));
    const hits = Array.isArray(d && d.hits) ? d.hits : [];
    box.innerHTML = hits.length
      ? hits.map(h => '<div style="margin:6px 0"><strong>' + escapeHtml(String(h.title || h.id || 'hit')) + '</strong><div style="color:var(--text-dim);font-size:0.68rem">' + escapeHtml(String(h.snippet || h.content || '')) + '</div></div>').join('')
      : '<span style="color:var(--text-dim)">' + escapeHtml(String((d && d.error) || 'No hits')) + '</span>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Search failed</span>'; }
}

// ═════════════════════════════════════════════════════════════════════════════
//  FILE CHECKPOINTS
// ═════════════════════════════════════════════════════════════════════════════

export async function refreshFileCheckpointsPanel() {
  const box = _el('file-checkpoints-list');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/memory/file_checkpoints?limit=40');
    const d = await r.json().catch(() => ({}));
    const items = Array.isArray(d && d.items) ? d.items : (Array.isArray(d && d.checkpoints) ? d.checkpoints : []);
    box.innerHTML = items.length
      ? items.slice(0, 40).map(c => {
          const id = escapeHtml(String(c.id || c.checkpoint_id || ''));
          const p = escapeHtml(String(c.path || c.filepath || ''));
          const ts = escapeHtml(String(c.timestamp || c.created_at || ''));
          return '<div style="margin:6px 0;padding:6px;border:1px solid rgba(255,255,255,0.06);border-radius:6px;background:rgba(0,0,0,0.12)">' +
            '<div style="font-size:0.68rem;color:var(--text-dim)">' + ts + '</div>' +
            '<div style="font-size:0.72rem"><strong>' + p + '</strong></div>' +
            '<div style="font-size:0.62rem;color:var(--text-dim)">' + id + '</div></div>';
        }).join('')
      : '<span style="color:var(--text-dim)">No checkpoints yet.</span>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Could not load checkpoints</span>'; }
}

// ═════════════════════════════════════════════════════════════════════════════
//  EXECUTION PANELS
// ═════════════════════════════════════════════════════════════════════════════

export async function wsRefreshExecutionPanels() {
  try {
    const pre = _el('exec-trace-json');
    if (pre) pre.textContent = 'Loading…';
    const r = await fetch('/debug/state');
    const d = await r.json().catch(() => ({}));
    if (pre) pre.textContent = JSON.stringify(d && (d.snapshot || d), null, 2);
  } catch (_) { try { const pre2 = _el('exec-trace-json'); if (pre2) pre2.textContent = 'Could not load'; } catch (_2) {} }

  try {
    const box = _el('tasks-list-json');
    if (box) box.textContent = 'Loading…';
    const results = await Promise.all([
      fetch('/debug/tasks?limit=40').then(x => x.json().catch(() => ({}))),
      fetch('/agent/tasks').then(x => x.json().catch(() => ({}))),
    ]);
    const persisted = Array.isArray(results[0] && results[0].tasks) ? results[0].tasks : [];
    const bg = Array.isArray(results[1] && results[1].tasks) ? results[1].tasks : [];
    if (!box) return;
    const rows = [];
    if (bg.length) {
      rows.push('<div style="margin-bottom:6px"><strong>Background tasks</strong></div>');
      rows.push(bg.slice(0, 25).map(t => {
        const id = escapeHtml(String(t.task_id || t.id || ''));
        const st = escapeHtml(String(t.status || ''));
        const goal = escapeHtml(String(t.goal || '').slice(0, 140));
        const canCancel = (String(t.status || '').toLowerCase() === 'running' || String(t.status || '').toLowerCase() === 'queued');
        return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06)"><div><strong>' + st + '</strong> <span style="color:var(--text-dim)">' + id.slice(0, 10) + '</span></div>' +
          (goal ? ('<div style="color:var(--text-dim)">' + goal + '</div>') : '') +
          (canCancel ? ('<button type="button" class="approve-btn" style="margin-top:4px" onclick="cancelBackgroundTask(' + JSON.stringify(String(t.task_id || t.id || '')) + ')">Cancel</button>') : '') + '</div>';
      }).join(''));
    }
    if (persisted.length) {
      rows.push('<div style="margin:10px 0 6px"><strong>Persisted coordinator tasks</strong></div>');
      rows.push('<div style="color:var(--text-dim)">' + escapeHtml(JSON.stringify(persisted.slice(0, 20), null, 2)).replace(/\\n/g, '<br/>') + '</div>');
    }
    box.innerHTML = rows.length ? rows.join('') : '<span style="color:var(--text-dim)">No tasks</span>';
  } catch (_) { try { const box2 = _el('tasks-list-json'); if (box2) box2.textContent = 'Could not load'; } catch (_2) {} }
}

export async function cancelBackgroundTask(taskId) {
  const tid = String(taskId || '').trim();
  if (!tid) return;
  try { await fetch('/agent/tasks/' + encodeURIComponent(tid), { method: 'DELETE' }); } catch (_) {}
  try { wsRefreshExecutionPanels(); } catch (_) {}
}

// ═════════════════════════════════════════════════════════════════════════════
//  AGENTS
// ═════════════════════════════════════════════════════════════════════════════

export async function refreshAgentsPanel() {
  const box = _el('agents-resource-panel');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetch('/health?deep=true');
    const d = await r.json().catch(() => ({}));
    const lim = (d && (d.effective_limits || d.limits)) || {};
    box.innerHTML =
      '<div><strong>max_active_runs</strong>: ' + escapeHtml(String(lim.max_active_runs != null ? lim.max_active_runs : '—')) + '</div>' +
      '<div><strong>performance_mode</strong>: ' + escapeHtml(String(lim.performance_mode != null ? lim.performance_mode : (d.performance_mode != null ? d.performance_mode : '—'))) + '</div>' +
      '<div><strong>CPU cap</strong>: ' + escapeHtml(String(lim.max_cpu_percent != null ? lim.max_cpu_percent : '—')) + '%</div>' +
      '<div><strong>RAM cap</strong>: ' + escapeHtml(String(lim.max_ram_percent != null ? lim.max_ram_percent : '—')) + '%</div>';
  } catch (_) { box.innerHTML = '<span style="color:var(--text-dim)">Could not load</span>'; }
}

// ═════════════════════════════════════════════════════════════════════════════
//  PANEL REFRESH ROUTING
// ═════════════════════════════════════════════════════════════════════════════

export function workspaceSubtabRefresh(sub) {
  const refreshers = {
    models: refreshPlatformModels,
    knowledge: refreshPlatformKnowledge,
    study: function () { refreshStudyPlans(); loadStudyPresetsAndSuggestions(); try { refreshLaylaPlansPanel(); } catch (_) {} },
    // Route to whichever mem-subtab is actually SHOWING. This used to hardcode
    // refreshFileCheckpointsPanel(), which loads the Checkpoints pane — hidden by default. The
    // default-visible "About you" pane was never loaded, so it sat on "Loading what Layla knows
    // about you…" forever: it is selected on arrival, so nothing ever prompts the user to click it,
    // and that click was its only loader. showMemorySubTab() owns the per-subtab load routing.
    memory: function () {
      var sub = 'about';  // the default-visible pane (index.html: data-mem-sub="about" is active)
      try {
        var activeBtn = document.querySelector('[data-mem-sub].active');
        if (activeBtn) sub = activeBtn.getAttribute('data-mem-sub') || 'about';
      } catch (_) {}
      try { showMemorySubTab(sub); } catch (_) {}
      try { refreshFileCheckpointsPanel(); } catch (_) {}
    },
    plugins: function () {
      refreshPlatformPlugins();
      try { if (typeof window.refreshRelationshipCodex === 'function') window.refreshRelationshipCodex(); } catch (_) {}
      try { refreshSkillsList(); } catch (_) {}
    },
  };
  const fn = refreshers[sub];
  if (typeof fn === 'function') fn();
}
