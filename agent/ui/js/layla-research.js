/**
 * layla-research.js -- Research missions, approvals panel, research brain tabs,
 * sendResearch streaming, and autonomous research/investigation.
 * Extracted from layla-app.js as part of a UI code-split.
 *
 * Depends on (loaded before this):
 *   layla-utils.js      -- escapeHtml, showToast, fetchWithTimeout, cleanLaylaText, sanitizeHtml, formatAgentError
 *   layla-chat-render.js -- addMsg, addSeparator, hideEmpty, laylaShowTypingIndicator,
 *                           laylaRemoveTypingIndicator, laylaStartNonStreamTypingPhases,
 *                           laylaNotifyStreamPhase, UX_STATE_LABELS, laylaAgentStreamTimeoutMs,
 *                           laylaStalledSilenceMs, formatLaylaLabelHtml
 *   layla-voice.js       -- speakText
 *   layla-aspect.js      -- currentAspect
 */
(function () {
  'use strict';

  // ── Safe fallbacks for cross-module dependencies ──────────────────────────
  var __esc = (typeof window.escapeHtml === 'function')
    ? window.escapeHtml
    : function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };

  var __toast = (typeof window.showToast === 'function')
    ? window.showToast
    : function (t) { try { console.log('[Layla UI]', t); } catch (_) {} };

  // ── Helpers that resolve at call-time (modules may load after us) ─────────
  function _addMsg()                  { return (window.addMsg || function () {}).apply(null, arguments); }
  function _addSeparator()            { return (window.addSeparator || function () {})(); }
  function _hideEmpty()               { return (window.hideEmpty || function () {})(); }
  function _formatLaylaLabelHtml(a)   { return (window.formatLaylaLabelHtml || function () { return ''; })(a); }
  function _speakText(t)              { return (window.speakText || function () { return Promise.resolve(); })(t); }
  function _laylaShowTypingIndicator(a, k) { return (window.laylaShowTypingIndicator || function () {})(a, k); }
  function _laylaRemoveTypingIndicator()   { return (window.laylaRemoveTypingIndicator || function () {})(); }
  function _laylaStartNonStreamTypingPhases() { return (window.laylaStartNonStreamTypingPhases || function () {})(); }
  function _laylaNotifyStreamPhase(r, k)   { return (window.laylaNotifyStreamPhase || function () {})(r, k); }
  function _fetchWithTimeout(u, o, t) { return (window.fetchWithTimeout || function (u, o) { return fetch(u, o || {}); })(u, o, t); }
  function _formatAgentError(r, b)    { return (window.formatAgentError || function (r) { return r ? 'Request failed' : "Can't reach server"; })(r, b); }
  function _cleanLaylaText(s)         { return (window.cleanLaylaText || function (s) { return String(s || ''); })(s); }
  function _sanitizeHtml(h)           { return (window.sanitizeHtml || function (h) { return h; })(h); }
  function _getUxStateLabels()        { return window.UX_STATE_LABELS || {}; }
  function _laylaAgentStreamTimeoutMs() { return (typeof window.laylaAgentStreamTimeoutMs === 'function') ? window.laylaAgentStreamTimeoutMs() : 720000; }
  function _laylaStalledSilenceMs()   { return (typeof window.laylaStalledSilenceMs === 'function') ? window.laylaStalledSilenceMs() : 12000; }
  function _getCurrentAspect()        { return (typeof window.currentAspect !== 'undefined') ? window.currentAspect : 'morrigan'; }

  // ═══════════════════════════════════════════════════════════════════════════
  // 1. getMissionDepth
  // ═══════════════════════════════════════════════════════════════════════════
  function getMissionDepth() {
    var r = document.querySelector('input[name="mission-depth"]:checked');
    return (r && r.value) ? r.value : 'deep';
  }
  window.getMissionDepth = getMissionDepth;

  // ═══════════════════════════════════════════════════════════════════════════
  // 2. startResearchMission
  // ═══════════════════════════════════════════════════════════════════════════
  async function startResearchMission(isResume) {
    var wpEl = document.getElementById('workspace-path');
    var workspacePath = (wpEl ? wpEl.value : '').trim();
    var missionDepth = getMissionDepth();
    var nsEl = document.getElementById('next-stage');
    var nextStage = nsEl ? nsEl.checked : false;

    _addMsg('you', (isResume ? '&#9208; Resume' : '&#9654; Start') + ' research mission: depth=' + missionDepth + (nextStage ? ', next_stage' : '') + (workspacePath ? ' · ' + workspacePath : ''));
    _addSeparator();

    var chatEl = document.getElementById('chat');
    var wrap = document.createElement('div');
    wrap.className = 'msg msg-layla';
    wrap.id = 'typing-wrap';
    wrap.innerHTML = '<div class="msg-label msg-label-layla">' + _formatLaylaLabelHtml(_getCurrentAspect()) + '</div><div class="msg-bubble typing-indicator"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
    chatEl.appendChild(wrap);
    chatEl.scrollTop = chatEl.scrollHeight;

    try {
      var res = await fetch('/research_mission', {
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
        var errMsg = 'Research mission failed: ' + res.status;
        try {
          var errBody = await res.json();
          if (errBody && (errBody.error || errBody.response || errBody.detail))
            errMsg = errBody.response || errBody.error || (typeof errBody.detail === 'string' ? errBody.detail : errMsg);
        } catch (_) {}
        _addMsg('layla', errMsg);
        await refreshMissionStatus();
        refreshApprovals();
        return;
      }
      var data = await res.json().catch(function () { return {}; });
      var resp = (data && data.response) || '(no output)';
      var aspectName = data && data.state ? data.state.aspect_name : undefined;
      var deliberated = data && data.state && data.state.steps ? data.state.steps.some(function (s) { return s.deliberated; }) : false;
      var steps = data && data.state ? data.state.steps : undefined;
      var uxStates = data && data.state ? data.state.ux_states : undefined;
      var memInfluenced = data && data.state ? data.state.memory_influenced : undefined;
      _addMsg('layla', resp, aspectName, deliberated, steps, uxStates, memInfluenced);
      if (data && data.mission_depth) {
        var stagesRun = Array.isArray(data.stages_run) ? data.stages_run : [];
        _addMsg('layla', 'Mission depth: ' + data.mission_depth + (stagesRun.length ? ', stages run: ' + stagesRun.join(', ') : ''));
      }
      if (window._ttsEnabled && resp && resp !== '(no output)') { _speakText(resp).catch(function () {}); }
      await refreshMissionStatus();
      var activeBtnEl = document.querySelector('#research-mission-panel .tab-btn.active');
      var activeTab = (activeBtnEl && activeBtnEl.getAttribute('data-tab')) || 'summary';
      await showResearchTab(activeTab);
    } catch (e) {
      wrap.remove();
      _addMsg('layla', 'Error: ' + e.message);
      await refreshMissionStatus();
    }
    refreshApprovals();
  }
  window.startResearchMission = startResearchMission;

  // ═══════════════════════════════════════════════════════════════════════════
  // 3. refreshMissionStatus
  // ═══════════════════════════════════════════════════════════════════════════
  async function refreshMissionStatus() {
    var lineEl = document.getElementById('mission-status-line');
    var detailEl = document.getElementById('mission-status-detail');
    var liveEl = document.getElementById('mission-status-live');
    var warnEl = document.getElementById('mission-status-warning');
    var resumableEl = document.getElementById('mission-status-resumable');
    if (!lineEl) return;
    try {
      var res = await _fetchWithTimeout('/research_mission/state', {}, 12000);
      var data = {};
      if (res.ok) try { data = await res.json(); } catch (_) {}
      var status = (data.status != null) ? data.status : (Array.isArray(data.completed) && data.completed.length ? 'partial' : null);
      var completed = Array.isArray(data.completed) ? data.completed : [];
      var stage = (data.stage != null) ? data.stage : null;
      var lastRun = (data.last_run != null) ? data.last_run : null;
      lineEl.textContent = 'Status: ' + (status || '—');
      var completedStr = completed.length ? '✔ ' + completed.join(', ') : '';
      if (detailEl) detailEl.innerHTML = (lastRun ? 'Last run: ' + __esc(String(lastRun)) + '<br>' : '') + (stage ? '⏳ Current: ' + __esc(String(stage)) + '<br>' : '') + (completedStr ? __esc(completedStr) : '');
      if (liveEl) {
        var now = new Date();
        liveEl.textContent = 'Updated ' + now.toLocaleTimeString();
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
  window.refreshMissionStatus = refreshMissionStatus;

  // Auto-poll mission status every 5 seconds
  setInterval(refreshMissionStatus, 5000);

  // ═══════════════════════════════════════════════════════════════════════════
  // 4. refreshApprovals
  // ═══════════════════════════════════════════════════════════════════════════
  async function refreshApprovals() {
    var box = document.getElementById('approvals-list');
    if (!box) return;
    try {
      var res = await _fetchWithTimeout('/pending', {}, 8000);
      var data = {};
      if (res && res.ok) {
        try { data = await res.json(); } catch (_) {}
      }
      var pending = Array.isArray(data && data.pending) ? data.pending : [];
      var todo = pending.filter(function (e) { return (e && e.status) === 'pending'; });
      if (!todo.length) {
        box.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">No pending approvals</span>';
        return;
      }
      var html = [];
      todo.forEach(function (e) {
        var id = String(e.id || '');
        var tool = String(e.tool || '');
        var args = e.args || {};
        var argsPreview = (function () { try { return JSON.stringify(args, null, 2); } catch (_) { return String(args); } })();
        var diffBlock = args && args.diff
          ? ('<pre style="margin:6px 0 8px;white-space:pre-wrap;word-break:break-word;font-size:0.62rem;background:var(--bg);padding:6px;border-radius:4px;border:1px solid rgba(255,255,255,0.06);max-height:140px;overflow:auto">' + __esc(String(args.diff)) + '</pre>')
          : '';
        html.push(
          '<div class="approval-card" style="margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:6px;background:rgba(0,0,0,0.12)">' +
            '<div style="font-size:0.72rem"><strong>' + __esc(tool || 'tool') + '</strong> <span style="color:var(--text-dim)">(' + __esc(id.slice(0, 8) || 'id') + '…)</span></div>' +
            diffBlock +
            '<pre style="margin:6px 0 8px;white-space:pre-wrap;word-break:break-word;font-size:0.65rem;background:var(--code-bg);padding:6px;border-radius:4px;border:1px solid rgba(255,255,255,0.06);max-height:160px;overflow:auto">' + __esc(argsPreview) + '</pre>' +
            '<label style="font-size:0.62rem;display:flex;gap:6px;align-items:center;margin:4px 0;color:var(--text-dim)"><input type="checkbox" class="grant-session-cb" /> Grant for session (same tool)</label>' +
            '<label style="font-size:0.62rem;display:block;margin:4px 0;color:var(--text-dim)">grant_pattern <input type="text" class="grant-pattern-inp" style="width:100%;padding:4px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:4px;font-size:0.62rem" placeholder="optional path glob" /></label>' +
            '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">' +
              '<button type="button" class="approve-btn" data-approve-id="' + __esc(id) + '">Approve</button>' +
              '<button type="button" class="approve-btn" style="background:transparent;border-color:var(--border);color:var(--text-dim)" data-deny-id="' + __esc(id) + '">Deny</button>' +
            '</div>' +
          '</div>'
        );
      });
      box.innerHTML = html.join('');

      // Approve buttons
      box.querySelectorAll('button[data-approve-id]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
          var id = btn.getAttribute('data-approve-id') || '';
          btn.disabled = true;
          try {
            var card = btn.closest('.approval-card');
            var sess = card && card.querySelector('.grant-session-cb');
            var gpi = card && card.querySelector('.grant-pattern-inp');
            var payload = { id: id };
            if (sess && sess.checked) payload.save_for_session = true;
            if (gpi && (gpi.value || '').trim()) payload.grant_pattern = (gpi.value || '').trim();
            var r = await _fetchWithTimeout('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, 15000);
            var body = {};
            try { body = await r.json(); } catch (_) {}
            if (!r.ok || !body.ok) __toast((body && body.error) ? ('Approve failed: ' + body.error) : ('Approve failed: ' + r.status));
            else __toast('Approved');
          } catch (e) {
            __toast('Approve error: ' + (e && e.message || e));
          } finally {
            btn.disabled = false;
            refreshApprovals();
          }
        });
      });

      // Deny buttons
      box.querySelectorAll('button[data-deny-id]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
          var id = btn.getAttribute('data-deny-id') || '';
          btn.disabled = true;
          try {
            var r = await _fetchWithTimeout('/deny', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id }) }, 15000);
            var body = {};
            try { body = await r.json(); } catch (_) {}
            if (!r.ok || !body.ok) __toast((body && body.error) ? ('Deny failed: ' + body.error) : ('Deny failed: ' + r.status));
            else __toast('Denied');
          } catch (e) {
            __toast('Deny error: ' + (e && e.message || e));
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
  window.refreshApprovals = refreshApprovals;

  // ═══════════════════════════════════════════════════════════════════════════
  // 5. RESEARCH_BRAIN_PATHS
  // ═══════════════════════════════════════════════════════════════════════════
  var RESEARCH_BRAIN_PATHS = {
    summary:  'summaries/24h_summary.md',
    actions:  'actions/action_queue.md',
    patterns: 'patterns/patterns.md',
    risks:    'risk/risk_model.md'
  };
  window.RESEARCH_BRAIN_PATHS = RESEARCH_BRAIN_PATHS;

  // ═══════════════════════════════════════════════════════════════════════════
  // 6. showResearchTab
  // ═══════════════════════════════════════════════════════════════════════════
  async function showResearchTab(tab) {
    var panel = document.getElementById('research-mission-panel');
    if (panel) {
      panel.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
      var btn = panel.querySelector('.tab-btn[data-tab="' + tab + '"]');
      if (btn) btn.classList.add('active');
    }
    var contentEl = document.getElementById('research-tab-content');
    if (!contentEl) return;
    if (tab === 'last') {
      try {
        var res = await _fetchWithTimeout('/research_output/last', {}, 12000);
        var data = res.ok ? await res.json() : {};
        contentEl.textContent = data.content || '(no output yet)';
      } catch (_) { contentEl.textContent = '(failed to load)'; }
      return;
    }
    var path = RESEARCH_BRAIN_PATHS[tab];
    if (!path) { contentEl.textContent = ''; return; }
    try {
      var res = await _fetchWithTimeout('/research_brain/file?path=' + encodeURIComponent(path), {}, 12000);
      var data = res.ok ? await res.json() : {};
      contentEl.textContent = data.content || '(no content yet)';
    } catch (_) { contentEl.textContent = '(failed to load)'; }
  }
  window.showResearchTab = showResearchTab;

  // ═══════════════════════════════════════════════════════════════════════════
  // 7. sendResearch  (~170 lines)
  // ═══════════════════════════════════════════════════════════════════════════
  async function sendResearch(customMessage) {
    var wpEl = document.getElementById('workspace-path');
    var workspacePath = (wpEl ? wpEl.value : '').trim();
    var researchMsg = (typeof customMessage === 'string' && customMessage.trim())
      ? customMessage.trim()
      : 'Research this repo and tell me if the implementation is optimal. Do not modify anything.';

    _addMsg('you', '🔬 ' + (researchMsg.length > 120 ? researchMsg.slice(0, 120) + '…' : researchMsg) + (workspacePath ? ' (Repo: ' + workspacePath + ')' : ''));
    _addSeparator();

    try {
      var rmBadge = document.getElementById('reasoning-mode-badge');
      if (rmBadge) rmBadge.textContent = '';
    } catch (_) {}

    var stEl = document.getElementById('stream-toggle');
    var streamMode = stEl ? stEl.checked : false;
    var thEl = document.getElementById('show-thinking');
    var payload = {
      message: researchMsg,
      repo_path: workspacePath || undefined,
      aspect_id: _getCurrentAspect(),
      show_thinking: thEl ? thEl.checked : false,
      stream: streamMode,
    };

    var chatEl = document.getElementById('chat');
    var ra = _getCurrentAspect();
    var UX = _getUxStateLabels();

    try {
      if (streamMode) {
        // ── Stream mode ──────────────────────────────────────────────────
        var res = await _fetchWithTimeout('/research', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }, Math.max(_laylaAgentStreamTimeoutMs(), 720000));

        if (!res.ok || !res.body) {
          var body = {};
          try { var t = await res.text(); if (t) try { body = JSON.parse(t); } catch (_) {} } catch (_) {}
          _addMsg('layla', _formatAgentError(res, body));
          refreshApprovals();
          return;
        }

        var reader = res.body.getReader();
        var dec = new TextDecoder();
        var full = '';

        _hideEmpty();
        var div = document.createElement('div');
        div.className = 'msg msg-layla';
        div.innerHTML = '<div class="msg-label msg-label-layla">' + _formatLaylaLabelHtml(ra) +
          '</div><div class="msg-bubble" title="Click to copy"><div class="md-content stream-md-placeholder">' +
          '<div class="typing-indicator" style="min-height:36px"><div class="typing-dots"><span></span><span></span><span></span></div></div>' +
          '<div class="tool-status-label">' + (UX.connecting || 'Connecting') + '</div></div></div>';
        chatEl.appendChild(div);

        var bubble = div.querySelector('.md-content');

        var streamMeta = document.createElement('div');
        streamMeta.className = 'memory-attribution';
        streamMeta.textContent = 'Status: ' + (UX.connecting || 'Connecting') + ' · 0s · 0 chars';
        div.appendChild(streamMeta);

        var streamStartedAt = Date.now();
        var liveStatus = 'connecting';
        _laylaNotifyStreamPhase(div, 'connecting');

        var metaTimer = setInterval(function () {
          var secs = Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000));
          var UXnow = _getUxStateLabels();
          streamMeta.textContent = 'Status: ' + (UXnow[liveStatus] || liveStatus) + ' · ' + secs + 's · ' + (full || '').length + ' chars';
        }, 500);

        var researchStreamGotToken = false;

        var firstTokenTimer = setTimeout(function () {
          liveStatus = 'waiting_first_token';
          var UXnow = _getUxStateLabels();
          var statusEl = div.querySelector('.tool-status-label');
          if (!statusEl) {
            statusEl = document.createElement('div');
            statusEl.className = 'tool-status-label';
            var msgBub = div.querySelector('.msg-bubble');
            if (msgBub) msgBub.appendChild(statusEl);
          }
          statusEl.textContent = UXnow.waiting_first_token || 'Waiting for first token';
          _laylaNotifyStreamPhase(div, liveStatus);
        }, 1200);

        var researchStallMs = _laylaStalledSilenceMs();

        function _resetStalledTimer() {
          clearTimeout(stalledTimer);
          stalledTimer = setTimeout(function () {
            liveStatus = 'stalled';
            var UXnow = _getUxStateLabels();
            var statusEl = div.querySelector('.tool-status-label');
            if (!statusEl) {
              statusEl = document.createElement('div');
              statusEl.className = 'tool-status-label';
              var msgBub = div.querySelector('.msg-bubble');
              if (msgBub) msgBub.appendChild(statusEl);
            }
            statusEl.textContent = (UXnow.stalled || 'Stalled') + ' — ' + (UXnow.retry_hint || 'Retry suggested');
            _laylaNotifyStreamPhase(div, 'stalled');
          }, researchStallMs);
        }

        var stalledTimer;
        _resetStalledTimer();

        var gotDone = false;
        while (true) {
          var readResult = await reader.read();
          var value = readResult.value;
          var done = readResult.done;
          if (done) break;
          var chunk = dec.decode(value, { stream: true });
          var lines = chunk.split('\n');
          for (var li = 0; li < lines.length; li++) {
            var line = lines[li];
            if (line.indexOf('data: ') === 0) {
              try {
                var obj = JSON.parse(line.slice(6));

                // pulse: reset stall timer
                if (obj.pulse === true) {
                  _resetStalledTimer();
                }

                // error: abort stream
                if (obj.error) {
                  clearTimeout(firstTokenTimer);
                  clearTimeout(stalledTimer);
                  clearInterval(metaTimer);
                  try { div.remove(); } catch (_) {}
                  _addMsg('layla', 'Research stream error: ' + String(obj.error));
                  refreshApprovals();
                  return;
                }

                // token: accumulate and render
                if (obj.token) {
                  liveStatus = 'streaming';
                  _laylaNotifyStreamPhase(div, 'streaming');
                  if (!researchStreamGotToken) {
                    researchStreamGotToken = true;
                    clearTimeout(firstTokenTimer);
                    if (bubble && bubble.classList.contains('stream-md-placeholder')) {
                      bubble.classList.remove('stream-md-placeholder');
                      bubble.innerHTML = '';
                    }
                  }
                  _resetStalledTimer();
                  full += obj.token;
                  var parsed = full;
                  try { if (typeof marked !== 'undefined') parsed = _sanitizeHtml(marked.parse(full)); } catch (_) {}
                  bubble.innerHTML = parsed;
                  bubble.querySelectorAll('pre code').forEach(function (el) { if (window.hljs) window.hljs.highlightElement(el); });
                  chatEl.scrollTop = chatEl.scrollHeight;
                }

                // done: finalise
                if (obj.done) {
                  clearTimeout(firstTokenTimer);
                  clearTimeout(stalledTimer);
                  if (obj.content != null && String(obj.content).trim() !== '') full = String(obj.content).trim();
                  try {
                    var rmB = document.getElementById('reasoning-mode-badge');
                    if (rmB && obj.reasoning_mode) rmB.textContent = 'Thinking: ' + obj.reasoning_mode;
                  } catch (_) {}
                  gotDone = true;
                  break;
                }
              } catch (_) {}
            }
          }
          if (gotDone) break;
        }

        clearInterval(metaTimer);
        clearTimeout(firstTokenTimer);
        clearTimeout(stalledTimer);
        streamMeta.textContent = 'Done · ' + Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000)) + 's · ' + (full || '').length + ' chars';

        full = _cleanLaylaText(full);
        var parsedFinal = full;
        try { if (typeof marked !== 'undefined') parsedFinal = _sanitizeHtml(marked.parse(full)); } catch (_) {}
        bubble.innerHTML = parsedFinal;
        try {
          var msgBubble = div.querySelector('.msg-bubble');
          if (msgBubble) msgBubble.removeAttribute('data-layla-phase');
          if (window.LaylaUI && typeof window.LaylaUI.clearBodyPhase === 'function') window.LaylaUI.clearBodyPhase();
        } catch (_) {}
        bubble.querySelectorAll('pre code').forEach(function (el) { if (window.hljs) window.hljs.highlightElement(el); });
        chatEl.scrollTop = chatEl.scrollHeight;
        if (window._ttsEnabled && full) { _speakText(full).catch(function () {}); }
        refreshApprovals();
        return;
      }

      // ── Non-stream mode ────────────────────────────────────────────────
      _laylaShowTypingIndicator(ra, 'connecting');
      _laylaStartNonStreamTypingPhases();
      var res = await _fetchWithTimeout('/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }, Math.max(_laylaAgentStreamTimeoutMs(), 720000));
      _laylaRemoveTypingIndicator();

      if (!res.ok) {
        var body = {};
        try { var t = await res.text(); if (t) try { body = JSON.parse(t); } catch (_) {} } catch (_) {}
        _addMsg('layla', _formatAgentError(res, body));
        refreshApprovals();
        return;
      }

      var data = await res.json();
      try {
        var rmBadge2 = document.getElementById('reasoning-mode-badge');
        var rm = data.reasoning_mode || (data.state ? data.state.reasoning_mode : undefined);
        if (rmBadge2) rmBadge2.textContent = rm ? ('Thinking: ' + rm) : '';
      } catch (_) {}

      var respText = data.response || '';
      var aspName = data.aspect_name;
      var delib = data.state && data.state.steps ? data.state.steps.some(function (s) { return s.deliberated; }) : false;
      var stepsArr = data.state ? data.state.steps : undefined;
      var uxs = data.ux_states;
      var memInfl = data.memory_influenced;
      _addMsg('layla', respText, aspName, delib, stepsArr, uxs, memInfl);
      if (window._ttsEnabled && respText.trim()) { _speakText(respText).catch(function () {}); }
    } catch (e) {
      _laylaRemoveTypingIndicator();
      var msg = (e && (e.message || '')) || '';
      var lc = msg.toLowerCase();
      if (lc.indexOf('fetch') !== -1 || lc.indexOf('network') !== -1 || lc.indexOf('abort') !== -1) {
        _addMsg('layla', _formatAgentError(null, null));
      } else {
        _addMsg('layla', 'Error: ' + (e && e.message || 'unknown'));
      }
    }
    refreshApprovals();
  }
  window.sendResearch = sendResearch;

  // ═══════════════════════════════════════════════════════════════════════════
  // 8. Investigation presets
  // ═══════════════════════════════════════════════════════════════════════════
  function _laylaAutonomousInvestigationPreset(goalText) {
    var g = document.getElementById('autonomous-goal');
    if (g) g.value = goalText;
    var rm = document.getElementById('autonomous-research-mode');
    if (rm) rm.checked = true;
    var cf = document.getElementById('autonomous-confirm');
    if (cf) cf.checked = true;
  }
  window._laylaAutonomousInvestigationPreset = _laylaAutonomousInvestigationPreset;

  window.laylaRunInvestigation = function laylaRunInvestigation() {
    var g = document.getElementById('autonomous-goal');
    if (g) {
      g.value = 'Investigate this workspace for bugs, risky patterns, and inconsistencies. Trace logic across files where needed. Summarize root causes and cite paths/lines. Do not modify any files.';
    }
    var rm = document.getElementById('autonomous-research-mode');
    if (rm) rm.checked = true;
    var cf = document.getElementById('autonomous-confirm');
    if (cf) cf.checked = true;
    return window.laylaRunAutonomousResearch();
  };

  window.laylaInvestigationTemplateTrace = function laylaInvestigationTemplateTrace() {
    _laylaAutonomousInvestigationPreset(
      'Trace where the selected symbol, function, or public API is defined and used across this repository. Map call sites, key modules, and data flow between files. Summarize findings with file:line evidence. Do not modify any files.'
    );
    return window.laylaRunAutonomousResearch();
  };

  window.laylaInvestigationTemplateStructure = function laylaInvestigationTemplateStructure() {
    _laylaAutonomousInvestigationPreset(
      'Analyze the repository structure: top-level layout, main packages, entry points, configuration and CI workflows. Identify coupling risks and ambiguous boundaries across multiple directories. Summarize with cited paths. Do not modify any files.'
    );
    return window.laylaRunAutonomousResearch();
  };

  window.laylaInvestigationTemplateBug = function laylaInvestigationTemplateBug() {
    _laylaAutonomousInvestigationPreset(
      'Investigate likely sources of incorrect behavior: trace error paths, suspicious hotspots, and inconsistent assumptions across modules. Hypothesize root causes with evidence from code reads and search; propose verification steps only (no execution). Do not modify any files.'
    );
    return window.laylaRunAutonomousResearch();
  };

  // ═══════════════════════════════════════════════════════════════════════════
  // 9. laylaRunAutonomousResearch  (~85 lines)
  // ═══════════════════════════════════════════════════════════════════════════
  window.laylaRunAutonomousResearch = async function laylaRunAutonomousResearch() {
    var goalEl = document.getElementById('autonomous-goal');
    var goal = String(goalEl ? goalEl.value : '').trim();
    var confirmCb = document.getElementById('autonomous-confirm');
    var out = document.getElementById('autonomous-result');
    var wpEl = document.getElementById('workspace-path');
    var wp = (wpEl ? wpEl.value : '').trim();

    if (!goal) {
      __toast('Enter a goal');
      return;
    }
    if (!confirmCb || !confirmCb.checked) {
      __toast('Check confirm_autonomous');
      return;
    }

    var msEl = document.getElementById('autonomous-max-steps');
    var toEl = document.getElementById('autonomous-timeout');
    var maxSteps = parseInt(String(msEl ? msEl.value : '30'), 10);
    var timeoutS = parseInt(String(toEl ? toEl.value : '120'), 10);
    if (!(maxSteps >= 1 && maxSteps <= 500)) maxSteps = 30;
    if (!(timeoutS >= 5 && timeoutS <= 7200)) timeoutS = 120;

    var taskId = (window.crypto && typeof window.crypto.randomUUID === 'function')
      ? window.crypto.randomUUID()
      : ('au-' + String(Date.now()));
    window._laylaCurrentAutoTaskId = taskId;

    var sumOut = document.getElementById('autonomous-result-summary');
    if (sumOut) sumOut.textContent = 'Running… (task ' + taskId.slice(0, 8) + ')';
    if (out) out.textContent = 'Running (task ' + taskId.slice(0, 8) + '…)…\nPoll /agent/tasks for tool progress.';

    var rmEl = document.getElementById('autonomous-research-mode');
    var poll = setInterval(async function () {
      try {
        var r = await fetch('/agent/tasks/' + encodeURIComponent(taskId));
        var d = await r.json().catch(function () { return {}; });
        if (d && d.ok && d.task && Array.isArray(d.task.progress_tail) && d.task.progress_tail.length && out) {
          var tail = d.task.progress_tail;
          var last = tail[tail.length - 1];
          out.textContent = 'progress: ' + JSON.stringify(last).slice(0, 1500) + '\n…';
        }
      } catch (_) {}
    }, 500);

    try {
      var r = await fetch('/autonomous/run', {
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
      var raw = await r.text();
      var d = {};
      try { d = JSON.parse(raw); } catch (_) { d = { _raw: raw }; }

      if (sumOut && d && typeof d === 'object') {
        var lines = [];
        lines.push('Steps: ' + (d.steps_used != null ? d.steps_used : '—') + ' · Stopped: ' + (d.stopped_reason || '—'));
        if (d.budget_detail) lines[lines.length - 1] += ' · budget: ' + d.budget_detail;
        lines.push('Confidence: ' + (d.confidence != null ? d.confidence : '—'));
        var src = String(d.source || '').trim();
        if (src === 'reuse') lines.push('Source: reused knowledge (investigation_reuse.jsonl)');
        else if (src === 'wiki') lines.push('Source: wiki markdown (prefetch)');
        else if (src === 'fresh') lines.push('Source: fresh investigation');
        else if (src === 'blocked') lines.push('Source: blocked (value gate)');
        else if (src) lines.push('Source: ' + src);
        if (d.reused === true) lines.push('Reused: yes');
        else if (d.reused === false) lines.push('Reused: no');
        var files = Array.isArray(d.files_accessed) ? d.files_accessed : [];
        var show = files.slice(0, 12);
        var more = files.length - show.length;
        lines.push('Files accessed (' + files.length + '): ' + (show.length ? show.join(', ') : '—') + (more > 0 ? ' … +' + more + ' more' : ''));
        var rs = String(d.investigation_trace || d.reasoning_summary || d.reasoning || '').trim();
        if (rs) lines.push('Trace: ' + rs.slice(0, 1200) + (rs.length > 1200 ? '…' : ''));
        sumOut.textContent = lines.join('\n');
      } else if (sumOut) {
        sumOut.textContent = '';
      }
      if (out) {
        var pretty = typeof d === 'object' ? JSON.stringify(d, null, 2) : String(d);
        out.textContent = pretty.slice(0, 16000);
      }
      __toast(r.ok ? 'Autonomous run finished' : 'Autonomous run error');
    } catch (e) {
      clearInterval(poll);
      if (out) out.textContent = String(e);
    }
  };

  // ═══════════════════════════════════════════════════════════════════════════
  // DOMContentLoaded
  // ═══════════════════════════════════════════════════════════════════════════
  document.addEventListener('DOMContentLoaded', function () {
    refreshMissionStatus();
    showResearchTab('summary');
  });

  // ── Module loaded flag ────────────────────────────────────────────────────
  window.laylaResearchModuleLoaded = true;
})();
