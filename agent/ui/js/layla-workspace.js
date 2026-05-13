/**
 * layla-workspace.js — Workspace panel refreshers extracted from layla-app.js.
 *
 * Handles: platform models/knowledge/plugins/projects/timeline, study plans,
 * skills, plans panel, workspace tools (awareness, memory inspector, symbol
 * search), memory search, file checkpoints, execution panels, agents panel,
 * and the panel-refresh routing helper.
 *
 * Dependencies:
 *   layla-utils.js  -> escapeHtml, showToast, fetchWithTimeout
 *   Core app        -> window.currentAspect, window.currentConversationId,
 *                      window.ensureLaylaConversationId,
 *                      window.laylaHeaderProgressStart,
 *                      window.laylaHeaderProgressStop,
 *                      window.updateContextChip, window.addMsg
 */
(function () {
  'use strict';

  // ── Safe fallbacks ──────────────────────────────────────────────────────────
  var __esc = window.escapeHtml || function (s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  };

  var __toast = window.showToast || function (t) {
    try { console.log('[Layla]', t); } catch (_) {}
  };

  var __fetch = window.fetchWithTimeout || fetch;

  // ── Helpers ─────────────────────────────────────────────────────────────────
  function _el(id) { return document.getElementById(id); }

  // ═══════════════════════════════════════════════════════════════════════════
  //  PLATFORM PANELS
  // ═══════════════════════════════════════════════════════════════════════════

  // 1. refreshPlatformModels
  async function refreshPlatformModels() {
    var box = _el('platform-models');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/platform/models');
      var d = await r.json();
      var active = (d && d.active) ? String(d.active) : '';
      var models = Array.isArray(d && d.models) ? d.models : [];
      box.innerHTML =
        '<div><strong>Active</strong>: ' + __esc(active || '—') + '</div>' +
        '<div style="margin-top:6px"><strong>Available</strong>: ' + __esc(models.slice(0, 10).join(', ') || '—') + '</div>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Could not load models</span>';
    }
  }
  window.refreshPlatformModels = refreshPlatformModels;

  // 2. refreshPlatformKnowledge
  async function refreshPlatformKnowledge() {
    var box = _el('platform-knowledge');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/platform/knowledge');
      var d = await r.json();
      var learnings = Array.isArray(d && d.learnings) ? d.learnings : [];
      var summaries = Array.isArray(d && d.summaries) ? d.summaries : [];
      box.innerHTML =
        '<div><strong>Recent learnings</strong>:</div>' +
        '<div style="margin-top:4px;color:var(--text-dim)">' + __esc(learnings.map(function (x) { return x.content || ''; }).slice(0, 5).join(' · ') || '—') + '</div>' +
        '<div style="margin-top:10px"><strong>Conversation summaries</strong>:</div>' +
        '<div style="margin-top:4px;color:var(--text-dim)">' + __esc(summaries.map(function (x) { return x.summary || ''; }).slice(0, 3).join(' · ') || '—') + '</div>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Could not load knowledge</span>';
    }
  }
  window.refreshPlatformKnowledge = refreshPlatformKnowledge;

  // 3. refreshPlatformPlugins
  async function refreshPlatformPlugins() {
    var box = _el('platform-plugins');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/platform/plugins');
      var d = await r.json();
      box.innerHTML =
        '<div><strong>Skills</strong>: ' + __esc(String((d && d.skills_added) || 0)) + '</div>' +
        '<div><strong>Tools</strong>: ' + __esc(String((d && d.tools_added) || 0)) + '</div>' +
        '<div><strong>Capabilities</strong>: ' + __esc(String((d && d.capabilities_added) || 0)) + '</div>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Could not load plugins</span>';
    }
  }
  window.refreshPlatformPlugins = refreshPlatformPlugins;

  // 4. refreshPlatformProjects
  async function refreshPlatformProjects() {
    var box = _el('platform-projects');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';

    var ctx = null;
    try {
      var r = await fetch('/platform/projects');
      ctx = await r.json();
    } catch (_) { ctx = null; }

    var preset = null;
    var pid = (typeof localStorage !== 'undefined' ? (localStorage.getItem('layla_active_project_id') || '') : '').trim();
    if (pid) {
      try {
        var r2 = await fetch('/projects/' + encodeURIComponent(pid));
        var d2 = await r2.json();
        if (d2 && d2.ok && d2.project) preset = d2.project;
      } catch (_) {}
    }

    var html = [];
    html.push('<div class="panel-title">Project context</div>');
    if (ctx && (ctx.project_name || ctx.goals || ctx.lifecycle_stage || ctx.progress || ctx.blockers)) {
      html.push('<div><strong>Name</strong>: ' + __esc(String(ctx.project_name || '—')) + '</div>');
      html.push('<div><strong>Stage</strong>: ' + __esc(String(ctx.lifecycle_stage || '—')) + '</div>');
      html.push('<div style="margin-top:6px"><strong>Goals</strong>: <span style="color:var(--text-dim)">' + __esc(String(ctx.goals || '')) + '</span></div>');
      html.push('<div style="margin-top:6px"><strong>Progress</strong>: <span style="color:var(--text-dim)">' + __esc(String(ctx.progress || '')) + '</span></div>');
      html.push('<div style="margin-top:6px"><strong>Blockers</strong>: <span style="color:var(--text-dim)">' + __esc(String(ctx.blockers || '')) + '</span></div>');
    } else {
      html.push('<div style="color:var(--text-dim)">No project context set yet.</div>');
    }

    html.push('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.08);margin:10px 0">');
    html.push('<div><strong>Active preset</strong>: ' + __esc(preset ? (preset.name || preset.id || '—') : (pid || '—')) + '</div>');
    if (preset) {
      html.push('<div style="color:var(--text-dim);margin-top:4px">WS: ' + __esc(String(preset.workspace_root || '')) + '</div>');
      html.push('<div style="color:var(--text-dim)">Aspect default: ' + __esc(String(preset.aspect_default || '')) + '</div>');
    } else {
      html.push('<div style="color:var(--text-dim);margin-top:4px">Select a preset in Prefs → Project preset.</div>');
    }

    // Minimal editor for project_context (uses existing POST /project_context)
    html.push('<div style="margin-top:10px"><strong>Edit project context</strong></div>');
    html.push('<div style="display:flex;flex-direction:column;gap:6px;margin-top:6px">');
    html.push('<input id="pc_name" placeholder="Project name" value="' + __esc(String((ctx && ctx.project_name) || '')) + '" />');
    html.push('<input id="pc_stage" placeholder="Lifecycle stage (idea/planning/prototype/iteration/execution/reflection)" value="' + __esc(String((ctx && ctx.lifecycle_stage) || '')) + '" />');
    html.push('<textarea id="pc_goals" placeholder="Goals" style="min-height:60px">' + __esc(String((ctx && ctx.goals) || '')) + '</textarea>');
    html.push('<textarea id="pc_progress" placeholder="Progress" style="min-height:50px">' + __esc(String((ctx && ctx.progress) || '')) + '</textarea>');
    html.push('<textarea id="pc_blockers" placeholder="Blockers" style="min-height:50px">' + __esc(String((ctx && ctx.blockers) || '')) + '</textarea>');
    html.push('<button type="button" class="tab-btn" id="pc_save_btn" style="margin-top:4px">Save</button>');
    html.push('<span id="pc_save_msg" style="color:var(--text-dim);font-size:0.7rem"></span>');
    html.push('</div>');

    box.innerHTML = html.join('');

    try {
      var btn = _el('pc_save_btn');
      if (btn) btn.onclick = async function () {
        var body = {
          project_name: ((_el('pc_name') || {}).value || '').trim(),
          lifecycle_stage: ((_el('pc_stage') || {}).value || '').trim(),
          goals: ((_el('pc_goals') || {}).value || '').trim(),
          progress: ((_el('pc_progress') || {}).value || '').trim(),
          blockers: ((_el('pc_blockers') || {}).value || '').trim(),
        };
        var msgEl = _el('pc_save_msg');
        if (msgEl) msgEl.textContent = 'Saving…';
        try {
          var r3 = await fetch('/project_context', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
          var d3 = await r3.json().catch(function () { return {}; });
          if (msgEl) msgEl.textContent = (d3 && d3.ok) ? 'Saved' : 'Save failed';
          try { if (typeof window.updateContextChip === 'function') window.updateContextChip(); } catch (_) {}
        } catch (_) {
          if (msgEl) msgEl.textContent = 'Save failed';
        }
      };
    } catch (_) {}
  }
  window.refreshPlatformProjects = refreshPlatformProjects;

  // 5. refreshPlatformTimeline
  async function refreshPlatformTimeline() {
    var box = _el('platform-timeline');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/platform/knowledge');
      var d = await r.json();
      var tl = Array.isArray(d && d.timeline) ? d.timeline : [];
      box.innerHTML = tl.length
        ? tl.slice(0, 8).map(function (t) {
          return '<div style="margin:4px 0"><span style="color:var(--text-dim)">' +
            __esc(String(t.event_type || '')) + '</span> ' +
            __esc(String(t.content || '')) + '</div>';
        }).join('')
        : '<span style="color:var(--text-dim)">No timeline yet.</span>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Could not load timeline</span>';
    }
  }
  window.refreshPlatformTimeline = refreshPlatformTimeline;

  // ═══════════════════════════════════════════════════════════════════════════
  //  STUDY PLANS
  // ═══════════════════════════════════════════════════════════════════════════

  // 6. refreshStudyPlans
  async function refreshStudyPlans() {
    var box = _el('study-list');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/study_plans');
      var d = await r.json().catch(function () { return {}; });
      var plans = Array.isArray(d && d.plans) ? d.plans : [];
      if (!plans.length) {
        box.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">No active study plans yet.</span>';
        return;
      }
      box.innerHTML = plans.slice(0, 20).map(function (p) {
        var topic = __esc(String(p.topic || ''));
        var sessions = __esc(String(p.study_sessions != null ? p.study_sessions : 0));
        var last = __esc(String(p.last_studied || ''));
        return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06)">' +
          '<div><strong>' + topic + '</strong></div>' +
          '<div style="color:var(--text-dim);font-size:0.68rem">sessions: ' + sessions + (last ? (' · last: ' + last) : '') + '</div>' +
          '</div>';
      }).join('');
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Could not load study plans</span>';
    }
  }
  window.refreshStudyPlans = refreshStudyPlans;

  // 7. loadStudyPresetsAndSuggestions
  async function loadStudyPresetsAndSuggestions() {
    var presets = _el('study-presets');
    var sug = _el('study-suggestions');
    if (presets) presets.innerHTML = '';
    if (sug) sug.innerHTML = '';
    try {
      var r1 = await fetch('/study_plans/presets');
      var d1 = await r1.json().catch(function () { return {}; });
      var topics = Array.isArray(d1 && d1.topics) ? d1.topics : [];
      if (presets) presets.innerHTML = topics.slice(0, 16).map(function (t) {
        return '<button type="button" class="approve-btn" style="font-size:0.62rem" onclick="addStudyPlan(' + JSON.stringify(String(t)) + ')">' + __esc(String(t)) + '</button>';
      }).join('');
    } catch (_) {}
    try {
      var r2 = await fetch('/study_plans/suggestions');
      var d2 = await r2.json().catch(function () { return {}; });
      var suggestions = Array.isArray(d2 && d2.suggestions) ? d2.suggestions : [];
      if (sug) sug.innerHTML = suggestions.slice(0, 16).map(function (t) {
        return '<button type="button" class="approve-btn" style="font-size:0.62rem" onclick="addStudyPlan(' + JSON.stringify(String(t)) + ')">' + __esc(String(t)) + '</button>';
      }).join('');
    } catch (_) {}
  }
  window.loadStudyPresetsAndSuggestions = loadStudyPresetsAndSuggestions;

  // 8. addStudyPlan
  async function addStudyPlan(topicOverride) {
    var inp = _el('study-input');
    var topic = String(topicOverride || (inp && inp.value) || '').trim();
    if (!topic) return;
    if (inp) inp.value = '';
    try {
      var r = await fetch('/study_plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic }),
      });
      var d = await r.json().catch(function () { return {}; });
      __toast((d && d.ok) ? 'Added' : 'Add failed');
      try { refreshStudyPlans(); } catch (_) {}
    } catch (_) {
      __toast('Add failed');
    }
  }
  window.addStudyPlan = addStudyPlan;

  // 9. studyTopicFromChatInput
  async function studyTopicFromChatInput() {
    var text = ((_el('msg-input') || {}).value || '').trim();
    if (!text) return;
    try {
      var r = await fetch('/study_plans/derive_topic', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      var d = await r.json().catch(function () { return {}; });
      if (d && d.ok && d.topic) addStudyPlan(String(d.topic));
    } catch (_) {}
  }
  window.studyTopicFromChatInput = studyTopicFromChatInput;

  // 10. studyTopicFromLastUserMessage
  function studyTopicFromLastUserMessage() {
    try {
      var chat = _el('chat');
      if (!chat) return;
      var rows = chat.querySelectorAll('.msg.msg-you .msg-bubble');
      var last = rows && rows.length ? String(rows[rows.length - 1].textContent || '').trim() : '';
      if (!last) return;
      fetch('/study_plans/derive_topic', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: last }),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (d && d.ok && d.topic) addStudyPlan(String(d.topic)); })
        .catch(function () {});
    } catch (_) {}
  }
  window.studyTopicFromLastUserMessage = studyTopicFromLastUserMessage;

  // ═══════════════════════════════════════════════════════════════════════════
  //  SKILLS
  // ═══════════════════════════════════════════════════════════════════════════

  // 11. refreshSkillsList
  async function refreshSkillsList() {
    var box = _el('platform-skills');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/skills');
      var d = await r.json().catch(function () { return {}; });
      var skills = Array.isArray(d && d.skills) ? d.skills : [];
      box.innerHTML = skills.length
        ? skills.slice(0, 40).map(function (s) {
          return '<div style="margin:4px 0"><strong>' + __esc(String(s.name || '')) + '</strong>' +
            '<div style="color:var(--text-dim);font-size:0.68rem">' + __esc(String(s.description || '')) + '</div></div>';
        }).join('')
        : '<span style="color:var(--text-dim)">No skills found.</span>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Could not load skills</span>';
    }
  }
  window.refreshSkillsList = refreshSkillsList;

  // ═══════════════════════════════════════════════════════════════════════════
  //  PLANS PANEL
  // ═══════════════════════════════════════════════════════════════════════════

  // 12. refreshLaylaPlansPanel
  async function refreshLaylaPlansPanel() {
    var listEl = _el('layla-plans-list');
    if (!listEl) return;
    listEl.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var wr = ((_el('workspace-path') || {}).value || '').trim();
      var q = wr ? ('?workspace_root=' + encodeURIComponent(wr) + '&limit=30') : '?limit=30';
      var r = await fetch('/plans' + q);
      var d = await r.json().catch(function () { return {}; });
      var plans = Array.isArray(d && d.plans) ? d.plans : [];
      if (!plans.length) {
        listEl.innerHTML = '<span style="color:var(--text-dim)">No plans for this workspace filter.</span>';
        return;
      }
      listEl.innerHTML = plans.slice(0, 24).map(function (p) {
        var id = String(p.id || '');
        var g = __esc(String(p.goal || '').slice(0, 120));
        var st = __esc(String(p.status || ''));
        var sid = id.replace(/[^a-zA-Z0-9_-]/g, '_');
        return '<div style="margin:6px 0;padding:8px;border:1px solid rgba(255,255,255,0.06);border-radius:6px;background:rgba(0,0,0,0.15)">' +
          '<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><strong>' + g + '</strong>' +
          '<span style="color:var(--text-dim);font-size:0.68rem">' + st + '</span></div>' +
          '<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px">' +
          '<button type="button" class="approve-btn" onclick="laylaApprovePlan(' + JSON.stringify(id) + ')">Approve</button>' +
          '<button type="button" class="approve-btn" onclick="laylaExecutePlan(' + JSON.stringify(id) + ')">Execute</button>' +
          '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--asp);color:var(--asp)" onclick="typeof laylaShowPlanViz===\'function\'&&laylaShowPlanViz(' + JSON.stringify(id) + ')">⬡ Gantt</button>' +
          '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--border);color:var(--text-dim)" onclick="laylaExpandPlan(' + JSON.stringify(id) + ', ' + JSON.stringify(sid) + ')">Detail</button>' +
          '</div>' +
          '<pre id="plan-detail-' + sid + '" style="display:none;margin-top:8px;font-size:0.62rem;max-height:200px;overflow:auto;white-space:pre-wrap"></pre>' +
          '</div>';
      }).join('');
    } catch (_) {
      listEl.innerHTML = '<span style="color:var(--text-dim)">Could not load plans</span>';
    }
  }
  window.refreshLaylaPlansPanel = refreshLaylaPlansPanel;

  // 13. laylaApprovePlan
  async function laylaApprovePlan(planId) {
    try {
      var r = await fetch('/plans/' + encodeURIComponent(planId) + '/approve', { method: 'POST' });
      var d = await r.json().catch(function () { return {}; });
      __toast(d.ok ? 'Plan approved' : (d.error || 'failed'));
      refreshLaylaPlansPanel();
    } catch (_) {
      __toast('Approve failed');
    }
  }
  window.laylaApprovePlan = laylaApprovePlan;

  // 14. laylaExecutePlan
  async function laylaExecutePlan(planId) {
    var wp = ((_el('workspace-path') || {}).value || '').trim();
    var allowWriteEl = _el('allow-write');
    var allowRunEl = _el('allow-run');
    var allowWrite = allowWriteEl ? !!allowWriteEl.checked : false;
    var allowRun = allowRunEl ? !!allowRunEl.checked : false;
    try { if (typeof window.ensureLaylaConversationId === 'function') window.ensureLaylaConversationId(); } catch (_) {}
    try { if (typeof window.laylaHeaderProgressStart === 'function') window.laylaHeaderProgressStart(); } catch (_) {}
    try {
      var r = await fetch('/plans/' + encodeURIComponent(planId) + '/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_root: wp,
          allow_write: allowWrite,
          allow_run: allowRun,
          aspect_id: (typeof window.currentAspect !== 'undefined') ? window.currentAspect : 'morrigan',
          conversation_id: (typeof window.currentConversationId !== 'undefined') ? window.currentConversationId : '',
        }),
      });
      var d = await r.json().catch(function () { return {}; });
      __toast(d.ok ? 'Execution finished' : (d.error || 'execute failed'));
      refreshLaylaPlansPanel();
    } catch (_) {
      __toast('Execute failed');
    } finally {
      try { if (typeof window.laylaHeaderProgressStop === 'function') window.laylaHeaderProgressStop(); } catch (_) {}
    }
  }
  window.laylaExecutePlan = laylaExecutePlan;

  // 15. laylaExpandPlan
  async function laylaExpandPlan(planId, sid) {
    var pre = _el('plan-detail-' + sid);
    if (!pre) return;
    var on = pre.style.display !== 'block';
    pre.style.display = on ? 'block' : 'none';
    if (!on) return;
    pre.textContent = 'Loading…';
    try {
      var r = await fetch('/plans/' + encodeURIComponent(planId));
      var d = await r.json().catch(function () { return {}; });
      var p = d && d.plan;
      pre.textContent = p ? JSON.stringify(p, null, 2) : JSON.stringify(d, null, 2);
    } catch (_) {
      pre.textContent = 'Failed to load';
    }
  }
  window.laylaExpandPlan = laylaExpandPlan;

  // ═══════════════════════════════════════════════════════════════════════════
  //  UTILITY ACTIONS
  // ═══════════════════════════════════════════════════════════════════════════

  // 16. laylaGitUndo
  async function laylaGitUndo() {
    try {
      var r = await fetch('/undo', { method: 'POST' });
      var d = await r.json().catch(function () { return {}; });
      __toast(d.ok ? (d.message || 'Undone') : (d.error || 'undo failed'));
    } catch (_) {
      __toast('Undo failed');
    }
  }
  window.laylaGitUndo = laylaGitUndo;

  // 17. laylaRunSetupAuto
  async function laylaRunSetupAuto() {
    try {
      var r = await fetch('/setup/auto', { method: 'POST' });
      var d = await r.json().catch(function () { return {}; });
      __toast((d && d.ok) ? 'Auto-setup finished' : String((d && d.error) || 'failed'));
    } catch (_) {
      __toast('Auto-setup failed');
    }
  }
  window.laylaRunSetupAuto = laylaRunSetupAuto;

  // 18. laylaRunDoctor
  async function laylaRunDoctor() {
    try {
      var r = await fetch('/doctor');
      var d = await r.json().catch(function () { return {}; });
      if (typeof window.addMsg === 'function') {
        window.addMsg('layla', '**Doctor snapshot**\n```json\n' + JSON.stringify(d, null, 2).slice(0, 8000) + '\n```');
      }
    } catch (_) {
      __toast('Doctor failed');
    }
  }
  window.laylaRunDoctor = laylaRunDoctor;

  // ═══════════════════════════════════════════════════════════════════════════
  //  WORKSPACE TOOLS
  // ═══════════════════════════════════════════════════════════════════════════

  // 19. laylaRefreshWorkspaceAwareness
  async function laylaRefreshWorkspaceAwareness() {
    var wp = ((_el('workspace-path') || {}).value || '').trim();
    var pulse = _el('workspace-awareness-pulse');
    var pulseTab = _el('workspace-awareness-tab-pulse');
    if (!wp) {
      __toast('Set workspace path first');
      return;
    }
    if (pulse) pulse.style.display = 'inline';
    if (pulseTab) pulseTab.style.display = 'inline';
    try {
      var r = await fetch('/workspace/awareness/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_root: wp }),
      });
      var d = await r.json().catch(function () { return {}; });
      __toast(d.ok ? 'Awareness refresh started' : String(d.error || 'failed'));
    } catch (_) {
      __toast('Awareness refresh failed');
    } finally {
      if (pulse) pulse.style.display = 'none';
      if (pulseTab) pulseTab.style.display = 'none';
    }
  }
  window.laylaRefreshWorkspaceAwareness = laylaRefreshWorkspaceAwareness;

  // 20. laylaLoadProjectMemoryInspector
  async function laylaLoadProjectMemoryInspector() {
    var pre = _el('project-memory-inspector');
    var wp = ((_el('workspace-path') || {}).value || '').trim();
    if (!wp) {
      __toast('Set workspace path first');
      return;
    }
    if (pre) pre.textContent = 'Loading…';
    try {
      var r = await fetch('/workspace/project_memory?workspace_root=' + encodeURIComponent(wp));
      var d = await r.json().catch(function () { return {}; });
      var sec = (d && d.project_memory) || {};
      var pick = ['modules', 'issues', 'plans', 'todos'];
      var out = '';
      for (var i = 0; i < pick.length; i++) {
        var k = pick[i];
        out += '## ' + k + '\n' + JSON.stringify(sec[k] != null ? sec[k] : (d[k] != null ? d[k] : null), null, 2).slice(0, 6000) + '\n\n';
      }
      if (pre) pre.textContent = out.trim() || JSON.stringify(d, null, 2).slice(0, 12000);
    } catch (e) {
      if (pre) pre.textContent = String(e);
    }
  }
  window.laylaLoadProjectMemoryInspector = laylaLoadProjectMemoryInspector;

  // 21. laylaWorkspaceSymbolSearch
  async function laylaWorkspaceSymbolSearch() {
    var q = String((_el('workspace-symbol-query') || {}).value || '').trim();
    var wp = ((_el('workspace-path') || {}).value || '').trim();
    var box = _el('workspace-symbol-results');
    if (!q) {
      __toast('Enter a symbol or phrase');
      return;
    }
    if (box) box.textContent = 'Searching…';
    try {
      var url = '/workspace/symbol_search?q=' + encodeURIComponent(q) + (wp ? '&workspace_root=' + encodeURIComponent(wp) : '');
      var r = await fetch(url);
      var d = await r.json().catch(function () { return {}; });
      if (box) box.textContent = JSON.stringify(d, null, 2).slice(0, 12000);
    } catch (e) {
      if (box) box.textContent = String(e);
    }
  }
  window.laylaWorkspaceSymbolSearch = laylaWorkspaceSymbolSearch;

  // ═══════════════════════════════════════════════════════════════════════════
  //  MEMORY SEARCH
  // ═══════════════════════════════════════════════════════════════════════════

  // 22. onMemorySearch
  async function onMemorySearch(q) {
    var box = _el('memory-search-results');
    var query = String(q || '').trim();
    if (!box) return;
    if (!query) {
      box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Type to search learnings (semantic / FTS)</span>';
      return;
    }
    box.innerHTML = '<span style="color:var(--text-dim)">Searching…</span>';
    try {
      var r = await fetch('/memories?q=' + encodeURIComponent(query) + '&n=8');
      var d = await r.json().catch(function () { return {}; });
      var items = Array.isArray(d && d.memories) ? d.memories : [];
      box.innerHTML = items.length
        ? items.map(function (m) {
          return '<div style="margin:6px 0;padding:6px;border-left:2px solid var(--asp);background:rgba(0,0,0,0.12)">' + __esc(String(m || '')) + '</div>';
        }).join('')
        : '<span style="color:var(--text-dim)">No matches.</span>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Search failed</span>';
    }
  }
  window.onMemorySearch = onMemorySearch;

  // 23. runElasticsearchLearningSearch
  async function runElasticsearchLearningSearch() {
    var q = String((_el('es-learning-search') || {}).value || '').trim();
    var box = _el('es-learning-results');
    if (!box) return;
    if (!q) {
      box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Enter a keyword query.</span>';
      return;
    }
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/elasticsearch/search?q=' + encodeURIComponent(q) + '&limit=20');
      var d = await r.json().catch(function () { return {}; });
      var hits = Array.isArray(d && d.hits) ? d.hits : [];
      box.innerHTML = hits.length
        ? hits.map(function (h) {
          return '<div style="margin:6px 0"><strong>' + __esc(String(h.title || h.id || 'hit')) + '</strong>' +
            '<div style="color:var(--text-dim);font-size:0.68rem">' + __esc(String(h.snippet || h.content || '')) + '</div></div>';
        }).join('')
        : '<span style="color:var(--text-dim)">' + __esc(String((d && d.error) || 'No hits')) + '</span>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Search failed</span>';
    }
  }
  window.runElasticsearchLearningSearch = runElasticsearchLearningSearch;

  // ═══════════════════════════════════════════════════════════════════════════
  //  FILE CHECKPOINTS
  // ═══════════════════════════════════════════════════════════════════════════

  // 24. refreshFileCheckpointsPanel
  async function refreshFileCheckpointsPanel() {
    var box = _el('file-checkpoints-list');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/file_checkpoints?limit=40');
      var d = await r.json().catch(function () { return {}; });
      var items = Array.isArray(d && d.items) ? d.items : (Array.isArray(d && d.checkpoints) ? d.checkpoints : []);
      box.innerHTML = items.length
        ? items.slice(0, 40).map(function (c) {
          var id = __esc(String(c.id || c.checkpoint_id || ''));
          var p = __esc(String(c.path || c.filepath || ''));
          var ts = __esc(String(c.timestamp || c.created_at || ''));
          return '<div style="margin:6px 0;padding:6px;border:1px solid rgba(255,255,255,0.06);border-radius:6px;background:rgba(0,0,0,0.12)">' +
            '<div style="font-size:0.68rem;color:var(--text-dim)">' + ts + '</div>' +
            '<div style="font-size:0.72rem"><strong>' + p + '</strong></div>' +
            '<div style="font-size:0.62rem;color:var(--text-dim)">' + id + '</div>' +
            '</div>';
        }).join('')
        : '<span style="color:var(--text-dim)">No checkpoints yet.</span>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Could not load checkpoints</span>';
    }
  }
  window.refreshFileCheckpointsPanel = refreshFileCheckpointsPanel;

  // ═══════════════════════════════════════════════════════════════════════════
  //  EXECUTION PANELS
  // ═══════════════════════════════════════════════════════════════════════════

  // 25. laylaRefreshExecutionPanels
  async function laylaRefreshExecutionPanels() {
    // Exec trace
    try {
      var pre = _el('exec-trace-json');
      if (pre) pre.textContent = 'Loading…';
      var r = await fetch('/debug/state');
      var d = await r.json().catch(function () { return {}; });
      if (pre) pre.textContent = JSON.stringify(d && (d.snapshot || d), null, 2);
    } catch (_) {
      try { var pre2 = _el('exec-trace-json'); if (pre2) pre2.textContent = 'Could not load'; } catch (_) {}
    }
    // Coordinator + background tasks
    try {
      var box = _el('tasks-list-json');
      if (box) box.textContent = 'Loading…';
      var results = await Promise.all([
        fetch('/debug/tasks?limit=40').then(function (x) { return x.json().catch(function () { return {}; }); }),
        fetch('/agent/tasks').then(function (x) { return x.json().catch(function () { return {}; }); }),
      ]);
      var r1 = results[0];
      var r2 = results[1];
      var persisted = Array.isArray(r1 && r1.tasks) ? r1.tasks : [];
      var bg = Array.isArray(r2 && r2.tasks) ? r2.tasks : [];
      if (!box) return;
      var rows = [];
      if (bg.length) {
        rows.push('<div style="margin-bottom:6px"><strong>Background tasks</strong></div>');
        rows.push(bg.slice(0, 25).map(function (t) {
          var id = __esc(String(t.task_id || t.id || ''));
          var st = __esc(String(t.status || ''));
          var goal = __esc(String(t.goal || '').slice(0, 140));
          var canCancel = (String(t.status || '').toLowerCase() === 'running' || String(t.status || '').toLowerCase() === 'queued');
          return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06)">' +
            '<div><strong>' + st + '</strong> <span style="color:var(--text-dim)">' + id.slice(0, 10) + '</span></div>' +
            (goal ? ('<div style="color:var(--text-dim)">' + goal + '</div>') : '') +
            (canCancel ? ('<button type="button" class="approve-btn" style="margin-top:4px" onclick="cancelBackgroundTask(' + JSON.stringify(String(t.task_id || t.id || '')) + ')">Cancel</button>') : '') +
            '</div>';
        }).join(''));
      }
      if (persisted.length) {
        rows.push('<div style="margin:10px 0 6px"><strong>Persisted coordinator tasks</strong></div>');
        rows.push('<div style="color:var(--text-dim)">' + __esc(JSON.stringify(persisted.slice(0, 20), null, 2)).replace(/\\n/g, '<br/>') + '</div>');
      }
      box.innerHTML = rows.length ? rows.join('') : '<span style="color:var(--text-dim)">No tasks</span>';
    } catch (_) {
      try { var box2 = _el('tasks-list-json'); if (box2) box2.textContent = 'Could not load'; } catch (_) {}
    }
  }
  window.laylaRefreshExecutionPanels = laylaRefreshExecutionPanels;

  // 26. cancelBackgroundTask
  async function cancelBackgroundTask(taskId) {
    var tid = String(taskId || '').trim();
    if (!tid) return;
    try {
      await fetch('/agent/tasks/' + encodeURIComponent(tid), { method: 'DELETE' });
    } catch (_) {}
    try { laylaRefreshExecutionPanels(); } catch (_) {}
  }
  window.cancelBackgroundTask = cancelBackgroundTask;

  // ═══════════════════════════════════════════════════════════════════════════
  //  AGENTS
  // ═══════════════════════════════════════════════════════════════════════════

  // 27. refreshAgentsPanel
  async function refreshAgentsPanel() {
    var box = _el('agents-resource-panel');
    if (!box) return;
    box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      var r = await fetch('/health?deep=true');
      var d = await r.json().catch(function () { return {}; });
      var lim = d && d.limits ? d.limits : {};
      box.innerHTML =
        '<div><strong>max_active_runs</strong>: ' + __esc(String(lim.max_active_runs != null ? lim.max_active_runs : '—')) + '</div>' +
        '<div><strong>performance_mode</strong>: ' + __esc(String(lim.performance_mode != null ? lim.performance_mode : (d.performance_mode != null ? d.performance_mode : '—'))) + '</div>' +
        '<div><strong>CPU cap</strong>: ' + __esc(String(lim.max_cpu_percent != null ? lim.max_cpu_percent : '—')) + '%</div>' +
        '<div><strong>RAM cap</strong>: ' + __esc(String(lim.max_ram_percent != null ? lim.max_ram_percent : '—')) + '%</div>';
    } catch (_) {
      box.innerHTML = '<span style="color:var(--text-dim)">Could not load</span>';
    }
  }
  window.refreshAgentsPanel = refreshAgentsPanel;

  // ═══════════════════════════════════════════════════════════════════════════
  //  PANEL REFRESH ROUTING
  // ═══════════════════════════════════════════════════════════════════════════

  // 28. __laylaRefreshAfterWorkspaceSubtab
  window.__laylaRefreshAfterWorkspaceSubtab = function (sub) {
    var refreshers = {
      models: refreshPlatformModels,
      knowledge: refreshPlatformKnowledge,
      study: function () {
        refreshStudyPlans();
        loadStudyPresetsAndSuggestions();
        try { refreshLaylaPlansPanel(); } catch (_) {}
      },
      memory: function () {
        try { refreshFileCheckpointsPanel(); } catch (_) {}
      },
      plugins: function () {
        refreshPlatformPlugins();
        try { if (typeof window.refreshRelationshipCodex === 'function') window.refreshRelationshipCodex(); } catch (_) {}
        try { refreshSkillsList(); } catch (_) {}
      },
    };
    var fn = refreshers[sub];
    if (typeof fn === 'function') fn();
  };

  // ── Module loaded flag ──────────────────────────────────────────────────────
  window.laylaWorkspaceModuleLoaded = true;
})();
