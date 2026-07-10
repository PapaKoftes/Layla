/**
 * components/research.js — Research missions, approvals panel, research brain tabs,
 * sendResearch streaming, and autonomous research/investigation.
 *
 * Converted from js/layla-research.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast)
 *
 * Heavy cross-module deps resolved at call-time via window.* guards:
 *   addMsg, addSeparator, hideEmpty, formatLaylaLabelHtml, speakText,
 *   laylaShowTypingIndicator, laylaRemoveTypingIndicator,
 *   laylaStartNonStreamTypingPhases, laylaNotifyStreamPhase,
 *   fetchWithTimeout, formatAgentError, cleanLaylaText, sanitizeHtml,
 *   UX_STATE_LABELS, laylaAgentStreamTimeoutMs, laylaStalledSilenceMs,
 *   currentAspect
 */

import { escapeHtml, showToast } from '../services/utils.js';

// ── Call-time resolved helpers (modules may load after us) ──────────────────
function _addMsg()                  { return (window.addMsg || function () {}).apply(null, arguments); }
function _addSeparator()            { return (window.addSeparator || function () {})(); }
function _hideEmpty()               { return (window.hideEmpty || function () {})(); }
function _formatLaylaLabelHtml(a)   { return (window.formatLaylaLabelHtml || function () { return ''; })(a); }
function _speakText(t)              { return (window.speakText || function () { return Promise.resolve(); })(t); }
function _laylaShowTypingIndicator(a, k) { return (window.laylaShowTypingIndicator || function () {})(a, k); }
function _laylaRemoveTypingIndicator()   { return (window.laylaRemoveTypingIndicator || function () {})(); }
function _laylaStartNonStreamTypingPhases() { return (window.laylaStartNonStreamTypingPhases || function () {})(); }
function _laylaNotifyStreamPhase(r, k)   { return (window.laylaNotifyStreamPhase || function () {})(r, k); }
function _fetchWithTimeout(u, o, t) { return (window.fetchWithTimeout || function (u2, o2) { return fetch(u2, o2 || {}); })(u, o, t); }
function _formatAgentError(r, b)    { return (window.formatAgentError || function (r2) { return r2 ? 'Request failed' : "Can't reach server"; })(r, b); }
function _cleanLaylaText(s)         { return (window.cleanLaylaText || function (s2) { return String(s2 || ''); })(s); }
function _sanitizeHtml(h)           { return (window.sanitizeHtml || function (h2) { return h2; })(h); }
function _getUxStateLabels()        { return window.UX_STATE_LABELS || {}; }
function _laylaAgentStreamTimeoutMs() { return (typeof window.laylaAgentStreamTimeoutMs === 'function') ? window.laylaAgentStreamTimeoutMs() : 720000; }
function _laylaStalledSilenceMs()   { return (typeof window.laylaStalledSilenceMs === 'function') ? window.laylaStalledSilenceMs() : 12000; }
function _getCurrentAspect()        { return (typeof window.currentAspect !== 'undefined') ? window.currentAspect : 'morrigan'; }

// ── getMissionDepth ─────────────────────────────────────────────────────────
export function getMissionDepth() {
  const r = document.querySelector('input[name="mission-depth"]:checked');
  return (r && r.value) ? r.value : 'deep';
}

// ── startResearchMission ────────────────────────────────────────────────────
export async function startResearchMission(isResume) {
  const wpEl = document.getElementById('workspace-path');
  const workspacePath = (wpEl ? wpEl.value : '').trim();
  const missionDepth = getMissionDepth();
  const nsEl = document.getElementById('next-stage');
  const nextStage = nsEl ? nsEl.checked : false;

  _addMsg('you', (isResume ? '&#9208; Resume' : '&#9654; Start') + ' research mission: depth=' + missionDepth + (nextStage ? ', next_stage' : '') + (workspacePath ? ' · ' + workspacePath : ''));
  _addSeparator();

  const chatEl = document.getElementById('chat');
  const wrap = document.createElement('div');
  wrap.className = 'msg msg-layla';
  wrap.id = 'typing-wrap';
  wrap.innerHTML = '<div class="msg-label msg-label-layla">' + _formatLaylaLabelHtml(_getCurrentAspect()) + '</div><div class="msg-bubble typing-indicator"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
  chatEl.appendChild(wrap);
  chatEl.scrollTop = chatEl.scrollHeight;

  try {
    const res = await fetch('/research_mission', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_root: workspacePath || undefined,
        mission_depth: missionDepth,
        next_stage: nextStage,
        mission_type: 'repo_analysis',
      }),
    });
    wrap.remove();
    if (!res.ok) {
      let errMsg = 'Research mission failed: ' + res.status;
      try { const errBody = await res.json(); if (errBody && (errBody.error || errBody.response || errBody.detail)) errMsg = errBody.response || errBody.error || (typeof errBody.detail === 'string' ? errBody.detail : errMsg); } catch (_) {}
      _addMsg('layla', errMsg);
      await refreshMissionStatus();
      refreshApprovals();
      return;
    }
    const data = await res.json().catch(function () { return {}; });
    const resp = (data && data.response) || '(no output)';
    const aspectName = data && data.state ? data.state.aspect_name : undefined;
    const deliberated = data && data.state && data.state.steps ? data.state.steps.some(function (s) { return s.deliberated; }) : false;
    const steps = data && data.state ? data.state.steps : undefined;
    const uxStates = data && data.state ? data.state.ux_states : undefined;
    const memInfluenced = data && data.state ? data.state.memory_influenced : undefined;
    _addMsg('layla', resp, aspectName, deliberated, steps, uxStates, memInfluenced);
    if (data && data.mission_depth) {
      const stagesRun = Array.isArray(data.stages_run) ? data.stages_run : [];
      _addMsg('layla', 'Mission depth: ' + data.mission_depth + (stagesRun.length ? ', stages run: ' + stagesRun.join(', ') : ''));
    }
    if (window._ttsEnabled && resp && resp !== '(no output)') { _speakText(resp).catch(function () {}); }
    await refreshMissionStatus();
    const activeBtnEl = document.querySelector('#research-mission-panel .tab-btn.active');
    const activeTab = (activeBtnEl && activeBtnEl.getAttribute('data-tab')) || 'summary';
    await showResearchTab(activeTab);
  } catch (e) {
    wrap.remove();
    _addMsg('layla', 'Error: ' + e.message);
    await refreshMissionStatus();
  }
  refreshApprovals();
}

// ── refreshMissionStatus ────────────────────────────────────────────────────
export async function refreshMissionStatus() {
  const lineEl = document.getElementById('mission-status-line');
  const detailEl = document.getElementById('mission-status-detail');
  const liveEl = document.getElementById('mission-status-live');
  const warnEl = document.getElementById('mission-status-warning');
  const resumableEl = document.getElementById('mission-status-resumable');
  if (!lineEl) return;
  try {
    const res = await _fetchWithTimeout('/research_mission/state', {}, 12000);
    let data = {};
    if (res.ok) try { data = await res.json(); } catch (_) {}
    const status = (data.status != null) ? data.status : (Array.isArray(data.completed) && data.completed.length ? 'partial' : null);
    const completed = Array.isArray(data.completed) ? data.completed : [];
    const stage = (data.stage != null) ? data.stage : null;
    const lastRun = (data.last_run != null) ? data.last_run : null;
    lineEl.textContent = 'Status: ' + (status || '—');
    const completedStr = completed.length ? '✔ ' + completed.join(', ') : '';
    if (detailEl) detailEl.innerHTML = (lastRun ? 'Last run: ' + escapeHtml(String(lastRun)) + '<br>' : '') + (stage ? '⏳ Current: ' + escapeHtml(String(stage)) + '<br>' : '') + (completedStr ? escapeHtml(completedStr) : '');
    if (liveEl) {
      liveEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
      liveEl.style.animation = status !== 'complete' ? 'mission-pulse 2s ease-in-out infinite' : 'none';
    }
    if (warnEl) warnEl.style.display = (status === 'partial' || status === 'stopped') ? 'block' : 'none';
    if (resumableEl) resumableEl.style.display = (status && status !== 'complete') ? 'block' : 'none';
  } catch (_) {
    lineEl.textContent = 'Status: —';
    if (detailEl) detailEl.textContent = '';
    if (liveEl) liveEl.textContent = 'Update failed';
    if (warnEl) warnEl.style.display = 'none';
    if (resumableEl) resumableEl.style.display = 'none';
  }
}

// ── refreshApprovals ────────────────────────────────────────────────────────
export async function refreshApprovals() {
  const box = document.getElementById('approvals-list');
  if (!box) return;
  try {
    const res = await _fetchWithTimeout('/pending', {}, 8000);
    let data = {};
    if (res && res.ok) { try { data = await res.json(); } catch (_) {} }
    const pending = Array.isArray(data && data.pending) ? data.pending : [];
    const todo = pending.filter(function (e) { return (e && e.status) === 'pending'; });
    // Surface the pending count in the topbar so approvals are never invisible/buried.
    try {
      const _badge = document.getElementById('topbar-approvals');
      if (_badge) {
        if (todo.length) {
          _badge.textContent = '⚠ ' + todo.length + (todo.length === 1 ? ' approval' : ' approvals');
          _badge.style.display = '';
        } else {
          _badge.style.display = 'none';
        }
      }
    } catch (_) {}
    if (!todo.length) {
      box.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">No pending approvals</span>';
      return;
    }
    const html = [];
    todo.forEach(function (e) {
      const id = String(e.id || '');
      const tool = String(e.tool || '');
      const args = e.args || {};
      const argsPreview = (function () { try { return JSON.stringify(args, null, 2); } catch (_) { return String(args); } })();
      const diffBlock = args && args.diff
        ? ('<pre style="margin:6px 0 8px;white-space:pre-wrap;word-break:break-word;font-size:0.62rem;background:var(--bg);padding:6px;border-radius:4px;border:1px solid rgba(255,255,255,0.06);max-height:140px;overflow:auto">' + escapeHtml(String(args.diff)) + '</pre>')
        : '';
      html.push(
        '<div class="approval-card" style="margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:6px;background:rgba(0,0,0,0.12)">' +
          '<div style="font-size:0.72rem"><strong>' + escapeHtml(tool || 'tool') + '</strong> <span style="color:var(--text-dim)">(' + escapeHtml(id.slice(0, 8) || 'id') + '…)</span></div>' +
          diffBlock +
          '<pre style="margin:6px 0 8px;white-space:pre-wrap;word-break:break-word;font-size:0.65rem;background:var(--code-bg);padding:6px;border-radius:4px;border:1px solid rgba(255,255,255,0.06);max-height:160px;overflow:auto">' + escapeHtml(argsPreview) + '</pre>' +
          '<label style="font-size:0.62rem;display:flex;gap:6px;align-items:center;margin:4px 0;color:var(--text-dim)"><input type="checkbox" class="grant-session-cb" /> Grant for session (same tool)</label>' +
          '<label style="font-size:0.62rem;display:block;margin:4px 0;color:var(--text-dim)">grant_pattern <input type="text" class="grant-pattern-inp" style="width:100%;padding:4px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px;font-size:0.62rem" placeholder="optional path glob" /></label>' +
          '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">' +
            '<button type="button" class="approve-btn" data-approve-id="' + escapeHtml(id) + '">Approve</button>' +
            '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--border);color:var(--text-dim)" data-deny-id="' + escapeHtml(id) + '">Deny</button>' +
          '</div></div>'
      );
    });
    box.innerHTML = html.join('');

    // Approve buttons
    box.querySelectorAll('button[data-approve-id]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const approveId = btn.getAttribute('data-approve-id') || '';
        btn.disabled = true;
        try {
          const card = btn.closest('.approval-card');
          const sess = card && card.querySelector('.grant-session-cb');
          const gpi = card && card.querySelector('.grant-pattern-inp');
          const payload = { id: approveId };
          if (sess && sess.checked) payload.save_for_session = true;
          if (gpi && (gpi.value || '').trim()) payload.grant_pattern = (gpi.value || '').trim();
          const r = await _fetchWithTimeout('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, 15000);
          let body = {};
          try { body = await r.json(); } catch (_) {}
          if (!r.ok || !body.ok) showToast((body && body.error) ? ('Approve failed: ' + body.error) : ('Approve failed: ' + r.status));
          else showToast('Approved');
        } catch (e2) {
          showToast('Approve error: ' + (e2 && e2.message || e2));
        } finally {
          btn.disabled = false;
          refreshApprovals();
        }
      });
    });

    // Deny buttons
    box.querySelectorAll('button[data-deny-id]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const denyId = btn.getAttribute('data-deny-id') || '';
        btn.disabled = true;
        try {
          const r = await _fetchWithTimeout('/deny', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: denyId }) }, 15000);
          let body = {};
          try { body = await r.json(); } catch (_) {}
          if (!r.ok || !body.ok) showToast((body && body.error) ? ('Deny failed: ' + body.error) : ('Deny failed: ' + r.status));
          else showToast('Denied');
        } catch (e2) {
          showToast('Deny error: ' + (e2 && e2.message || e2));
        } finally {
          btn.disabled = false;
          refreshApprovals();
        }
      });
    });
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">Could not load approvals</span>';
  }
}

// ── RESEARCH_BRAIN_PATHS ────────────────────────────────────────────────────
export const RESEARCH_BRAIN_PATHS = {
  summary:  'summaries/24h_summary.md',
  actions:  'actions/action_queue.md',
  patterns: 'patterns/patterns.md',
  risks:    'risk/risk_model.md',
};

// ── showResearchTab ─────────────────────────────────────────────────────────
export async function showResearchTab(tab) {
  const panel = document.getElementById('research-mission-panel');
  if (panel) {
    panel.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
    const btn = panel.querySelector('.tab-btn[data-tab="' + tab + '"]');
    if (btn) btn.classList.add('active');
  }
  const contentEl = document.getElementById('research-tab-content');
  if (!contentEl) return;
  if (tab === 'last') {
    try {
      const res = await _fetchWithTimeout('/research_output/last', {}, 12000);
      const data = res.ok ? await res.json() : {};
      contentEl.textContent = data.content || '(no output yet)';
    } catch (_) { contentEl.textContent = '(failed to load)'; }
    return;
  }
  const path = RESEARCH_BRAIN_PATHS[tab];
  if (!path) { contentEl.textContent = ''; return; }
  try {
    const res = await _fetchWithTimeout('/research_brain/file?path=' + encodeURIComponent(path), {}, 12000);
    const data = res.ok ? await res.json() : {};
    contentEl.textContent = data.content || '(no content yet)';
  } catch (_) { contentEl.textContent = '(failed to load)'; }
}

// ── sendResearch ────────────────────────────────────────────────────────────
export async function sendResearch(customMessage) {
  const wpEl = document.getElementById('workspace-path');
  const workspacePath = (wpEl ? wpEl.value : '').trim();
  const researchMsg = (typeof customMessage === 'string' && customMessage.trim())
    ? customMessage.trim()
    : 'Research this repo and tell me if the implementation is optimal. Do not modify anything.';

  _addMsg('you', '🔬 ' + (researchMsg.length > 120 ? researchMsg.slice(0, 120) + '…' : researchMsg) + (workspacePath ? ' (Repo: ' + workspacePath + ')' : ''));
  _addSeparator();

  try { const rmBadge = document.getElementById('reasoning-mode-badge'); if (rmBadge) rmBadge.textContent = ''; } catch (_) {}

  const stEl = document.getElementById('stream-toggle');
  const streamMode = stEl ? stEl.checked : false;
  const thEl = document.getElementById('show-thinking');
  const payload = {
    message: researchMsg,
    repo_path: workspacePath || undefined,
    aspect_id: _getCurrentAspect(),
    show_thinking: thEl ? thEl.checked : false,
    stream: streamMode,
  };

  const chatEl = document.getElementById('chat');
  const ra = _getCurrentAspect();
  const UX = _getUxStateLabels();

  try {
    if (streamMode) {
      // Stream mode
      const res = await _fetchWithTimeout('/research', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }, Math.max(_laylaAgentStreamTimeoutMs(), 720000));

      if (!res.ok || !res.body) {
        let body = {};
        try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch (_) {} } catch (_) {}
        _addMsg('layla', _formatAgentError(res, body));
        refreshApprovals();
        return;
      }

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = '';

      _hideEmpty();
      const div = document.createElement('div');
      div.className = 'msg msg-layla';
      div.innerHTML = '<div class="msg-label msg-label-layla">' + _formatLaylaLabelHtml(ra) +
        '</div><div class="msg-bubble" title="Click to copy"><div class="md-content stream-md-placeholder">' +
        '<div class="typing-indicator" style="min-height:36px"><div class="typing-dots"><span></span><span></span><span></span></div></div>' +
        '<div class="tool-status-label">' + (UX.connecting || 'Connecting') + '</div></div></div>';
      chatEl.appendChild(div);

      const bubble = div.querySelector('.md-content');

      const streamMeta = document.createElement('div');
      streamMeta.className = 'memory-attribution';
      streamMeta.textContent = 'Status: ' + (UX.connecting || 'Connecting') + ' · 0s · 0 chars';
      div.appendChild(streamMeta);

      const streamStartedAt = Date.now();
      let liveStatus = 'connecting';
      _laylaNotifyStreamPhase(div, 'connecting');

      const metaTimer = setInterval(function () {
        const secs = Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000));
        const UXnow = _getUxStateLabels();
        streamMeta.textContent = 'Status: ' + (UXnow[liveStatus] || liveStatus) + ' · ' + secs + 's · ' + (full || '').length + ' chars';
      }, 500);

      let researchStreamGotToken = false;
      const researchStallMs = _laylaStalledSilenceMs();

      const firstTokenTimer = setTimeout(function () {
        liveStatus = 'waiting_first_token';
        const UXnow = _getUxStateLabels();
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; const msgBub = div.querySelector('.msg-bubble'); if (msgBub) msgBub.appendChild(statusEl); }
        statusEl.textContent = UXnow.waiting_first_token || 'Waiting for first token';
        _laylaNotifyStreamPhase(div, liveStatus);
      }, 1200);

      let stalledTimer;
      function _resetStalledTimer() {
        clearTimeout(stalledTimer);
        stalledTimer = setTimeout(function () {
          liveStatus = 'stalled';
          const UXnow = _getUxStateLabels();
          let statusEl = div.querySelector('.tool-status-label');
          if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; const msgBub = div.querySelector('.msg-bubble'); if (msgBub) msgBub.appendChild(statusEl); }
          statusEl.textContent = (UXnow.stalled || 'Stalled') + ' — ' + (UXnow.retry_hint || 'Retry suggested');
          _laylaNotifyStreamPhase(div, 'stalled');
        }, researchStallMs);
      }
      _resetStalledTimer();

      let gotDone = false;
      let _rbuf = '';  // carry an incomplete SSE line across network reads (parity with app.js _sseBuf)
      while (true) {
        const readResult = await reader.read();
        if (readResult.done) break;
        // A `data: {...}` frame split across two TCP reads was parsed as a half-line (JSON.parse
        // throws, silently swallowed) — dropping that token, or losing the done frame so the raw
        // `full` (with any leaked scaffolding) was never replaced by the cleaned obj.content.
        _rbuf += dec.decode(readResult.value, { stream: true });
        const lines = _rbuf.split('\n');
        _rbuf = lines.pop();  // last element is the possibly-incomplete trailing line
        for (let li = 0; li < lines.length; li++) {
          const line = lines[li];
          if (line.indexOf('data: ') === 0) {
            try {
              const obj = JSON.parse(line.slice(6));
              if (obj.pulse === true) _resetStalledTimer();
              if (obj.error) {
                clearTimeout(firstTokenTimer); clearTimeout(stalledTimer); clearInterval(metaTimer);
                try { div.remove(); } catch (_) {}
                _addMsg('layla', 'Research stream error: ' + String(obj.error));
                refreshApprovals();
                return;
              }
              if (obj.token) {
                liveStatus = 'streaming';
                _laylaNotifyStreamPhase(div, 'streaming');
                if (!researchStreamGotToken) {
                  researchStreamGotToken = true;
                  clearTimeout(firstTokenTimer);
                  if (bubble && bubble.classList.contains('stream-md-placeholder')) { bubble.classList.remove('stream-md-placeholder'); bubble.innerHTML = ''; }
                }
                _resetStalledTimer();
                full += obj.token;
                // Balance an unclosed ``` fence during live render (parity with app.js): a lone
                // opening fence makes marked render the whole rest of the reply as one code block
                // (bleeds to monospace) until the close streams in. The done frame re-renders clean.
                let _mdSrc = full;
                if (((full.match(/```/g) || []).length % 2)) _mdSrc = full + '\n```';
                let parsed = full;
                try { if (typeof marked !== 'undefined') parsed = _sanitizeHtml(marked.parse(_mdSrc)); } catch (_) {}
                bubble.innerHTML = parsed;
                bubble.querySelectorAll('pre code').forEach(function (el) { if (window.hljs) window.hljs.highlightElement(el); });
                chatEl.scrollTop = chatEl.scrollHeight;
              }
              if (obj.done) {
                clearTimeout(firstTokenTimer); clearTimeout(stalledTimer);
                if (obj.content != null && String(obj.content).trim() !== '') full = String(obj.content).trim();
                try { const rmB = document.getElementById('reasoning-mode-badge'); if (rmB && obj.reasoning_mode) rmB.textContent = 'Thinking: ' + obj.reasoning_mode; } catch (_) {}
                gotDone = true;
                break;
              }
            } catch (_) {}
          }
        }
        if (gotDone) break;
      }

      clearInterval(metaTimer); clearTimeout(firstTokenTimer); clearTimeout(stalledTimer);
      streamMeta.textContent = 'Done · ' + Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000)) + 's · ' + (full || '').length + ' chars';

      full = _cleanLaylaText(full);
      let parsedFinal = full;
      try { if (typeof marked !== 'undefined') parsedFinal = _sanitizeHtml(marked.parse(full)); } catch (_) {}
      bubble.innerHTML = parsedFinal;
      try {
        const msgBubble = div.querySelector('.msg-bubble');
        if (msgBubble) msgBubble.removeAttribute('data-layla-phase');
        if (window.LaylaUI && typeof window.LaylaUI.clearBodyPhase === 'function') window.LaylaUI.clearBodyPhase();
      } catch (_) {}
      bubble.querySelectorAll('pre code').forEach(function (el) { if (window.hljs) window.hljs.highlightElement(el); });
      chatEl.scrollTop = chatEl.scrollHeight;
      if (window._ttsEnabled && full) { _speakText(full).catch(function () {}); }
      refreshApprovals();
      return;
    }

    // Non-stream mode
    _laylaShowTypingIndicator(ra, 'connecting');
    _laylaStartNonStreamTypingPhases();
    const res = await _fetchWithTimeout('/research', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }, Math.max(_laylaAgentStreamTimeoutMs(), 720000));
    _laylaRemoveTypingIndicator();

    if (!res.ok) {
      let body = {};
      try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch (_) {} } catch (_) {}
      _addMsg('layla', _formatAgentError(res, body));
      refreshApprovals();
      return;
    }

    const data = await res.json();
    try { const rmBadge2 = document.getElementById('reasoning-mode-badge'); const rm = data.reasoning_mode || (data.state ? data.state.reasoning_mode : undefined); if (rmBadge2) rmBadge2.textContent = rm ? ('Thinking: ' + rm) : ''; } catch (_) {}

    const respText = data.response || '';
    const aspName = data.aspect_name;
    const delib = data.state && data.state.steps ? data.state.steps.some(function (s) { return s.deliberated; }) : false;
    const stepsArr = data.state ? data.state.steps : undefined;
    const uxs = data.ux_states;
    const memInfl = data.memory_influenced;
    _addMsg('layla', respText, aspName, delib, stepsArr, uxs, memInfl);
    if (window._ttsEnabled && respText.trim()) { _speakText(respText).catch(function () {}); }
  } catch (e) {
    _laylaRemoveTypingIndicator();
    const msg = (e && (e.message || '')) || '';
    const lc = msg.toLowerCase();
    if (lc.indexOf('fetch') !== -1 || lc.indexOf('network') !== -1 || lc.indexOf('abort') !== -1) {
      _addMsg('layla', _formatAgentError(null, null));
    } else {
      _addMsg('layla', 'Error: ' + (e && e.message || 'unknown'));
    }
  }
  refreshApprovals();
}

// ── Investigation presets ───────────────────────────────────────────────────
export function laylaAutonomousInvestigationPreset(goalText) {
  const g = document.getElementById('autonomous-goal');
  if (g) g.value = goalText;
  const rm = document.getElementById('autonomous-research-mode');
  if (rm) rm.checked = true;
  const cf = document.getElementById('autonomous-confirm');
  if (cf) cf.checked = true;
}

export function laylaRunInvestigation() {
  const g = document.getElementById('autonomous-goal');
  if (g) g.value = 'Investigate this workspace for bugs, risky patterns, and inconsistencies. Trace logic across files where needed. Summarize root causes and cite paths/lines. Do not modify any files.';
  const rm = document.getElementById('autonomous-research-mode');
  if (rm) rm.checked = true;
  const cf = document.getElementById('autonomous-confirm');
  if (cf) cf.checked = true;
  return laylaRunAutonomousResearch();
}

export function laylaInvestigationTemplateTrace() {
  laylaAutonomousInvestigationPreset(
    'Trace where the selected symbol, function, or public API is defined and used across this repository. Map call sites, key modules, and data flow between files. Summarize findings with file:line evidence. Do not modify any files.'
  );
  return laylaRunAutonomousResearch();
}

export function laylaInvestigationTemplateStructure() {
  laylaAutonomousInvestigationPreset(
    'Analyze the repository structure: top-level layout, main packages, entry points, configuration and CI workflows. Identify coupling risks and ambiguous boundaries across multiple directories. Summarize with cited paths. Do not modify any files.'
  );
  return laylaRunAutonomousResearch();
}

export function laylaInvestigationTemplateBug() {
  laylaAutonomousInvestigationPreset(
    'Investigate likely sources of incorrect behavior: trace error paths, suspicious hotspots, and inconsistent assumptions across modules. Hypothesize root causes with evidence from code reads and search; propose verification steps only (no execution). Do not modify any files.'
  );
  return laylaRunAutonomousResearch();
}

// ── laylaRunAutonomousResearch ──────────────────────────────────────────────
export async function laylaRunAutonomousResearch() {
  const goalEl = document.getElementById('autonomous-goal');
  const goal = String(goalEl ? goalEl.value : '').trim();
  const confirmCb = document.getElementById('autonomous-confirm');
  const out = document.getElementById('autonomous-result');
  const wpEl = document.getElementById('workspace-path');
  const wp = (wpEl ? wpEl.value : '').trim();

  if (!goal) { showToast('Enter a goal'); return; }
  if (!confirmCb || !confirmCb.checked) { showToast('Check confirm_autonomous'); return; }

  const msEl = document.getElementById('autonomous-max-steps');
  const toEl = document.getElementById('autonomous-timeout');
  let maxSteps = parseInt(String(msEl ? msEl.value : '30'), 10);
  let timeoutS = parseInt(String(toEl ? toEl.value : '120'), 10);
  if (!(maxSteps >= 1 && maxSteps <= 500)) maxSteps = 30;
  if (!(timeoutS >= 5 && timeoutS <= 7200)) timeoutS = 120;

  const taskId = (window.crypto && typeof window.crypto.randomUUID === 'function')
    ? window.crypto.randomUUID()
    : ('au-' + String(Date.now()));
  window._laylaCurrentAutoTaskId = taskId;

  const sumOut = document.getElementById('autonomous-result-summary');
  if (sumOut) sumOut.textContent = 'Running… (task ' + taskId.slice(0, 8) + ')';
  if (out) out.textContent = 'Running (task ' + taskId.slice(0, 8) + '…)…\nPoll /agent/tasks for tool progress.';

  const rmEl = document.getElementById('autonomous-research-mode');
  const poll = setInterval(async function () {
    try {
      const r = await fetch('/agent/tasks/' + encodeURIComponent(taskId));
      const d = await r.json().catch(function () { return {}; });
      if (d && d.ok && d.task && Array.isArray(d.task.progress_tail) && d.task.progress_tail.length && out) {
        const tail = d.task.progress_tail;
        const last = tail[tail.length - 1];
        out.textContent = 'progress: ' + JSON.stringify(last).slice(0, 1500) + '\n…';
      }
    } catch (_) {}
  }, 500);

  try {
    const r = await fetch('/autonomous/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        goal: goal,
        workspace_root: wp || '',
        max_steps: maxSteps,
        timeout_seconds: timeoutS,
        research_mode: !!(rmEl && rmEl.checked),
        confirm_autonomous: true,
        progress_task_id: taskId,
      }),
    });
    clearInterval(poll);
    const raw = await r.text();
    let d = {};
    try { d = JSON.parse(raw); } catch (_) { d = { _raw: raw }; }

    if (sumOut && d && typeof d === 'object') {
      const lines = [];
      lines.push('Steps: ' + (d.steps_used != null ? d.steps_used : '—') + ' · Stopped: ' + (d.stopped_reason || '—'));
      if (d.budget_detail) lines[lines.length - 1] += ' · budget: ' + d.budget_detail;
      lines.push('Confidence: ' + (d.confidence != null ? d.confidence : '—'));
      const src = String(d.source || '').trim();
      if (src === 'reuse') lines.push('Source: reused knowledge (investigation_reuse.jsonl)');
      else if (src === 'wiki') lines.push('Source: wiki markdown (prefetch)');
      else if (src === 'fresh') lines.push('Source: fresh investigation');
      else if (src === 'blocked') lines.push('Source: blocked (value gate)');
      else if (src) lines.push('Source: ' + src);
      if (d.reused === true) lines.push('Reused: yes');
      else if (d.reused === false) lines.push('Reused: no');
      const files = Array.isArray(d.files_accessed) ? d.files_accessed : [];
      const show = files.slice(0, 12);
      const more = files.length - show.length;
      lines.push('Files accessed (' + files.length + '): ' + (show.length ? show.join(', ') : '—') + (more > 0 ? ' … +' + more + ' more' : ''));
      const rs = String(d.investigation_trace || d.reasoning_summary || d.reasoning || '').trim();
      if (rs) lines.push('Trace: ' + rs.slice(0, 1200) + (rs.length > 1200 ? '…' : ''));
      sumOut.textContent = lines.join('\n');
    } else if (sumOut) {
      sumOut.textContent = '';
    }
    if (out) {
      const pretty = typeof d === 'object' ? JSON.stringify(d, null, 2) : String(d);
      out.textContent = pretty.slice(0, 16000);
    }
    showToast(r.ok ? 'Autonomous run finished' : 'Autonomous run error');
  } catch (e) {
    clearInterval(poll);
    if (out) out.textContent = String(e);
  }
}

// ── Init ────────────────────────────────────────────────────────────────────
let _missionPollTimer = null;

export function initResearch() {
  refreshMissionStatus();
  showResearchTab('summary');
  // Auto-poll mission status every 5s
  if (!_missionPollTimer) {
    _missionPollTimer = setInterval(refreshMissionStatus, 5000);
  }
}
