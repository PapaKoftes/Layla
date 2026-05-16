/**
 * layla-app.js (core) — Main orchestrator: send(), executePlan(), health,
 * panel routing, and DOMContentLoaded init.
 *
 * Depends on (loaded BEFORE this file):
 *   layla-utils.js, layla-aspect.js, layla-voice.js, layla-chat-render.js,
 *   layla-input.js, layla-setup.js, layla-settings-full.js
 *
 * The original 4024-line layla-app.js has been split into ~10 focused modules.
 * This file keeps only the core send/execute loop, health polling, and init.
 */

// ── Global state ─────────────────────────────────────────────────────────────
window.__laylaHealth = window.__laylaHealth || {
  payload: null,
  lastFetch: 0,
  lastDeepFetch: 0,
  deepIntervalMs: 60000,
  inFlight: false,
  agentRequestActive: false,
  _inFlightPromise: null,
};

// Aspect + conversation globals (may already be set by layla-aspect.js)
if (typeof window.currentAspect === 'undefined') window.currentAspect = 'morrigan';
window.currentConversationId = window.currentConversationId || localStorage.getItem('layla_current_conversation_id') || '';
var sessionStart = Date.now();

// ── Core try-catch wrapper ───────────────────────────────────────────────────
try {

var _lastDisplayMsg = null;
window._lastDisplayMsg = null;
var _activeAgentAbort = null;

// ── Cancel / busy state ──────────────────────────────────────────────────────
function cancelActiveSend() {
  try {
    if (_activeAgentAbort) _activeAgentAbort.abort();
  } catch (_e) { console.debug('layla-app:', _e); }
  try { laylaHeaderProgressStop(); } catch (_e) { console.debug('layla-app:', _e); }
}
window.cancelActiveSend = cancelActiveSend;

function setCancelSendVisible(visible) {
  var b = document.getElementById('cancel-send-btn');
  if (b) b.style.display = visible ? 'inline-block' : 'none';
}
window.setCancelSendVisible = setCancelSendVisible;

// ── Header context row ───────────────────────────────────────────────────────
function laylaRefreshHeaderContextRow() {
  try {
    var cid = String(window.currentConversationId || '').trim();
    var el = document.getElementById('header-conv-id');
    if (el) {
      el.textContent = cid ? ('conv ' + cid.slice(0, 8)) : 'new chat';
      el.title = cid ? ('conversation_id: ' + cid) : 'No conversation id yet';
    }
  } catch (_e) { console.debug('layla-app:', _e); }
  fetch('/session/stats', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
    var t = document.getElementById('header-session-tokens');
    if (!t || !d || d.error) return;
    var tt = d.total_tokens != null ? Number(d.total_tokens) : 0;
    var tc = d.tool_calls != null ? Number(d.tool_calls) : 0;
    var elapsed = d.elapsed_seconds != null ? Number(d.elapsed_seconds) : 0;
    t.textContent = 'Σ ' + tt + ' tok · ' + tc + ' tools · ' + elapsed + 's';
    t.title = 'GET /session/stats — prompt:' + (d.prompt_tokens != null ? d.prompt_tokens : '?') + ' completion:' + (d.completion_tokens != null ? d.completion_tokens : '?');
  }).catch(function () {
    var t = document.getElementById('header-session-tokens');
    if (t) t.textContent = '';
  });
}
window.laylaRefreshHeaderContextRow = laylaRefreshHeaderContextRow;

// ── Conversation ID helper ───────────────────────────────────────────────────
function ensureLaylaConversationId() {
  if (typeof window.currentConversationId === 'string' && String(window.currentConversationId).trim()) {
    try { laylaRefreshHeaderContextRow(); } catch (_e) { console.debug('layla-app:', _e); }
    return String(window.currentConversationId).trim();
  }
  var id = '';
  try {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) id = crypto.randomUUID();
    else id = 'lc-' + Date.now() + '-' + Math.random().toString(36).slice(2, 9);
  } catch (_) {
    id = 'lc-' + Date.now();
  }
  window.currentConversationId = id;
  try { localStorage.setItem('layla_current_conversation_id', id); } catch (_e) { console.debug('layla-app:', _e); }
  try { if (typeof updateContextChip === 'function') updateContextChip(); } catch (_e) { console.debug('layla-app:', _e); }
  try { laylaRefreshHeaderContextRow(); } catch (_e) { console.debug('layla-app:', _e); }
  return id;
}
window.ensureLaylaConversationId = ensureLaylaConversationId;

// ── Panel refresh routing ────────────────────────────────────────────────────
window.__laylaRefreshAfterShowMainPanel = function (main) {
  if (main === 'status') {
    refreshPlatformHealth();
    refreshVersionInfo();
    refreshRuntimeOptions();
  }
  if (main === 'prefs') {
    if (typeof refreshContentPolicyToggles === 'function') refreshContentPolicyToggles();
    try { refreshApprovals(); } catch (_e) { console.debug('layla-app:', _e); }
    try { loadProjectsIntoSelect(); } catch (_e) { console.debug('layla-app:', _e); }
  }
  if (main === 'workspace') {
    var wsRoot = document.querySelector('#layla-right-panel .rcp-page[data-rcp="workspace"]');
    var subEl = wsRoot && wsRoot.querySelector('.rcp-subtab.active');
    var sub = (subEl && subEl.getAttribute('data-rcp-sub')) || 'models';
    if (typeof window.__laylaRefreshAfterWorkspaceSubtab === 'function') {
      window.__laylaRefreshAfterWorkspaceSubtab(sub);
    }
  }
  if (main === 'research') {
    refreshMissionStatus().then(function () {
      var t = document.querySelector('#research-mission-panel .tab-btn.active');
      if (t) showResearchTab(t.getAttribute('data-tab'));
    });
  }
};

// ── executePlan ──────────────────────────────────────────────────────────────
async function executePlan(plan, goal) {
  var workspacePath = (document.getElementById('workspace-path') ? document.getElementById('workspace-path').value : '').trim();
  var allowWrite = document.getElementById('allow-write') ? document.getElementById('allow-write').checked : false;
  var allowRun = document.getElementById('allow-run') ? document.getElementById('allow-run').checked : false;
  try { ensureLaylaConversationId(); } catch (_e) { console.debug('layla-app:', _e); }
  try { laylaHeaderProgressStart(); } catch (_e) { console.debug('layla-app:', _e); }
  try {
    var res = await fetchWithTimeout(
      '/execute_plan',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan: plan,
          goal: goal || '',
          workspace_root: workspacePath,
          aspect_id: window.currentAspect || 'morrigan',
          conversation_id: window.currentConversationId || '',
          allow_write: !!allowWrite,
          allow_run: !!allowRun,
        }),
      },
      600000
    );
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok || data.ok === false) {
      var err = (data && (data.error || data.detail)) ? String(data.error || data.detail) : ('HTTP ' + res.status);
      if (typeof showToast === 'function') showToast(err);
      else _dbg('executePlan failed', err);
      return;
    }
    var okAll = !!data.all_steps_ok;
    if (typeof showToast === 'function') showToast(okAll ? 'Plan finished' : 'Plan finished (some steps reported issues)');
    try {
      var summary = JSON.stringify(data.results || {}, null, 2);
      addMsg('layla', '**Plan executed**\n```json\n' + summary.slice(0, 12000) + (summary.length > 12000 ? '\n…' : '') + '\n```');
    } catch (_e) { console.debug('layla-app:', _e); }
  } catch (e) {
    var msg = (e && e.message) ? String(e.message) : String(e);
    if (typeof showToast === 'function') showToast('executePlan: ' + msg);
    else _dbg('executePlan', e);
  } finally {
    try { laylaHeaderProgressStop(); } catch (_e) { console.debug('layla-app:', _e); }
  }
}
window.executePlan = executePlan;

// ── compactConversation ──────────────────────────────────────────────────────
async function compactConversation() {
  try {
    var res = await fetchWithTimeout(
      '/compact',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: window.currentConversationId || '' }),
      },
      120000
    );
    var data = await res.json().catch(function () { return {}; });
    var n = data && typeof data.messages_remaining === 'number' ? data.messages_remaining : null;
    var tok = n != null ? String(n) : '?';
    if (typeof showToast === 'function') showToast('Compacted · messages in buffer: ~' + tok);
    try { if (typeof updateContextChip === 'function') updateContextChip(); } catch (_e) { console.debug('layla-app:', _e); }
  } catch (e) {
    if (typeof showToast === 'function') showToast('Compact failed: ' + ((e && e.message) || e));
  }
}
window.compactConversation = compactConversation;

// ── send() — main chat entry point ──────────────────────────────────────────
async function send() {
  _dbg('send() called');
  try { if (typeof _hideMentionDropdown === 'function') _hideMentionDropdown(); } catch (_e) { console.debug('layla-app:', _e); }
  var input = document.getElementById('msg-input');
  if (!input) return;
  var msg = (input.value || '').trim();
  if (!msg) return;
  if (window._laylaSendBusy) return;
  window._laylaSendBusy = true;
  if (window.laylaChatFSM && !window.laylaChatFSM.beginSend()) {
    window._laylaSendBusy = false;
    return;
  }

  var ac = new AbortController();
  _activeAgentAbort = ac;
  var metaTimer = null;
  var firstTokenTimer = null;
  var stalledTimer = null;
  try { laylaHeaderProgressStart(); } catch (_e) { console.debug('layla-app:', _e); }
  try { operatorTraceClear(); } catch (_e) { console.debug('layla-app:', _e); }
  try { laylaStreamStatsStart(''); } catch (_e) { console.debug('layla-app:', _e); }

  var msgAspect = window.currentAspect;
  var mentionMatch = msg.match(/^@([a-z]+)\s*/i);
  if (mentionMatch) {
    try {
      var mentioned = mentionMatch[1].toLowerCase();
      var found = (typeof ASPECTS !== 'undefined' && ASPECTS.find)
        ? ASPECTS.find(function (a) { return a.id === mentioned || (a.name || '').toLowerCase() === mentioned; })
        : null;
      if (found) {
        msgAspect = found.id;
        msg = msg.slice(mentionMatch[0].length).trim() || msg;
      }
    } catch (_e) { console.debug('layla-app:', _e); }
  }
  if (window._aspectLocked) msgAspect = window.currentAspect;

  input.value = '';
  try { toggleSendButton(); } catch (_e) { console.debug('layla-app:', _e); }
  var displayMsg = mentionMatch && msgAspect !== window.currentAspect ? ('@' + msgAspect + ' ' + msg) : msg;
  addMsg('you', displayMsg);
  addSeparator();
  _lastDisplayMsg = displayMsg;
  window._lastDisplayMsg = displayMsg;

  ensureLaylaConversationId();

  var chatEl = document.getElementById('chat');
  var streamToggle = document.getElementById('stream-toggle');
  var streamMode = streamToggle ? streamToggle.checked : false;
  var modelOverrideEl = document.getElementById('model-override');
  var modelOverride = modelOverrideEl ? (modelOverrideEl.value || '').trim() : '';
  var wpEl = document.getElementById('workspace-path');
  var workspacePath = wpEl ? (wpEl.value || '').trim() : '';
  var projectId = '';
  try { projectId = (localStorage.getItem('layla_active_project_id') || '').trim(); } catch (_e) { console.debug('layla-app:', _e); }
  var composeDraftEl = document.getElementById('compose-draft');
  var composeDraft = composeDraftEl ? (composeDraftEl.value || '').trim() : '';

  var payload = {
    message: msg,
    context: composeDraft || '',
    workspace_root: workspacePath || '',
    project_id: projectId || '',
    aspect_id: msgAspect,
    conversation_id: window.currentConversationId,
    show_thinking: !!(document.getElementById('show-thinking') && document.getElementById('show-thinking').checked),
    allow_write: !!(document.getElementById('allow-write') && document.getElementById('allow-write').checked),
    allow_run: !!(document.getElementById('allow-run') && document.getElementById('allow-run').checked),
    stream: !!streamMode,
  };
  if (modelOverride) payload.model_override = modelOverride;
  var _epSel = document.getElementById('engineering-pipeline-mode');
  if (_epSel && _epSel.value && _epSel.value !== 'chat') payload.engineering_pipeline_mode = _epSel.value;
  var _clarTa = document.getElementById('pipeline-clarify-answers');
  if (_clarTa && _clarTa.value.trim()) {
    payload.clarification_reply = _clarTa.value.trim();
    _clarTa.value = '';
    var _cp = document.getElementById('pipeline-clarify-panel');
    if (_cp) _cp.style.display = 'none';
  }

  try { laylaShowTypingIndicator(msgAspect, streamMode ? 'connecting' : 'preparing_reply'); } catch (_e) { console.debug('layla-app:', _e); }

  try {
    if (streamMode) {
      var res = await fetchWithTimeout(
        '/agent',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: ac.signal },
        Math.max(laylaAgentStreamTimeoutMs(), 300000)
      );
      if (!res.ok || !res.body) {
        var body = {};
        try { var t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) {} } catch(_) {}
        try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('layla-app:', _e); }
        addMsg('layla', formatAgentError(res, body));
        try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_e) { console.debug('layla-app:', _e); }
        return;
      }
      try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('layla-app:', _e); }
      try { if (window.laylaChatFSM) window.laylaChatFSM.beginStream(); } catch (_e) { console.debug('layla-app:', _e); }
      var reader = res.body.getReader();
      var dec = new TextDecoder();
      var full = '';
      hideEmpty();
      var div = document.createElement('div');
      div.className = 'msg msg-layla';
      div.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(msgAspect) + '</div><div class="msg-bubble" title="Click to copy"><div class="md-content stream-md-placeholder"><div class="typing-indicator" style="min-height:36px"><div class="typing-dots"><span></span><span></span><span></span></div></div><div class="tool-status-label">' + ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.connecting) || 'Connecting') + '</div></div></div>';
      if (chatEl) chatEl.appendChild(div);
      var bubble = div.querySelector('.md-content');
      var thinkBox = null;
      var thinkContent = null;
      var thinkCount = 0;
      function ensureThinkBox() {
        if (thinkBox) return;
        thinkBox = document.createElement('details');
        thinkBox.className = 'tool-trace';
        thinkBox.style.borderLeft = '2px solid var(--asp)';
        thinkBox.open = true;
        thinkBox.innerHTML = '<summary>Thinking (live)</summary>';
        thinkContent = document.createElement('div');
        thinkContent.className = 'tool-trace-content';
        thinkContent.style.whiteSpace = 'pre-wrap';
        thinkContent.style.maxHeight = '180px';
        thinkContent.style.overflow = 'auto';
        thinkBox.appendChild(thinkContent);
        div.appendChild(thinkBox);
      }
      function appendThinkLine(txt) {
        if (!txt) return;
        ensureThinkBox();
        thinkCount += 1;
        if (thinkBox && thinkBox.querySelector('summary')) {
          thinkBox.querySelector('summary').textContent = 'Thinking (live) · ' + thinkCount;
        }
        if (thinkContent) {
          thinkContent.textContent += (thinkContent.textContent ? '\n' : '') + txt;
          thinkContent.scrollTop = thinkContent.scrollHeight;
        }
      }
      var streamMeta = document.createElement('div');
      streamMeta.className = 'memory-attribution';
      streamMeta.textContent = 'Status: ' + ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.connecting) || 'Connecting') + ' · 0s · 0 chars';
      div.appendChild(streamMeta);
      var streamStartedAt = Date.now();
      var liveStatus = 'connecting';
      try { laylaNotifyStreamPhase(div, 'connecting'); } catch (_e) { console.debug('layla-app:', _e); }
      metaTimer = setInterval(function () {
        var secs = Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000));
        streamMeta.textContent = 'Status: ' + ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS[liveStatus]) || liveStatus) + ' · ' + secs + 's · ' + (full || '').length + ' chars';
      }, 500);
      var gotToken = false;
      firstTokenTimer = setTimeout(function () {
        liveStatus = 'waiting_first_token';
        var statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; var mb = div.querySelector('.msg-bubble'); if (mb) mb.appendChild(statusEl); }
        statusEl.textContent = (typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.waiting_first_token) || 'Waiting for first token';
        try { laylaNotifyStreamPhase(div, liveStatus); } catch (_e) { console.debug('layla-app:', _e); }
      }, 1800);
      var stallMs = (typeof laylaStalledSilenceMs === 'function') ? laylaStalledSilenceMs() : 60000;
      stalledTimer = setTimeout(function () {
        liveStatus = 'stalled';
        var statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; var mb = div.querySelector('.msg-bubble'); if (mb) mb.appendChild(statusEl); }
        statusEl.textContent = ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.stalled) || 'Stalled') + ' — ' + ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.retry_hint) || 'Retry suggested');
        try { laylaNotifyStreamPhase(div, 'stalled'); } catch (_e) { console.debug('layla-app:', _e); }
      }, stallMs);
      while (true) {
        var _read = await reader.read();
        var value = _read.value;
        var done = _read.done;
        if (done) break;
        var chunk = dec.decode(value, { stream: true });
        var lines = chunk.split('\n');
        for (var li = 0; li < lines.length; li++) {
          var line = lines[li];
          if (!line.startsWith('data: ')) continue;
          var obj = null;
          try { obj = JSON.parse(line.slice(6)); } catch (_) { obj = null; }
          if (!obj) continue;
          if (obj.pulse === true) {
            clearTimeout(stalledTimer);
            stalledTimer = setTimeout(function () {
              liveStatus = 'stalled';
              var statusEl = div.querySelector('.tool-status-label');
              if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; var mb = div.querySelector('.msg-bubble'); if (mb) mb.appendChild(statusEl); }
              statusEl.textContent = ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.stalled) || 'Stalled') + ' — ' + ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.retry_hint) || 'Retry suggested');
              try { laylaNotifyStreamPhase(div, 'stalled'); } catch (_e) { console.debug('layla-app:', _e); }
            }, stallMs);
          }
          if (obj.error) {
            clearTimeout(firstTokenTimer);
            clearTimeout(stalledTimer);
            clearInterval(metaTimer);
            try { div.remove(); } catch (_e) { console.debug('layla-app:', _e); }
            try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('layla-app:', _e); }
            addMsg('layla', String(obj.error));
            try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_e) { console.debug('layla-app:', _e); }
            return;
          }
          if (obj.ux_state) {
            liveStatus = String(obj.ux_state);
            try { laylaNotifyStreamPhase(div, liveStatus); } catch (_e) { console.debug('layla-app:', _e); }
            var statusEl = div.querySelector('.tool-status-label');
            if (statusEl) statusEl.textContent = (typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS[liveStatus]) || liveStatus;
          }
          if (obj.type === 'thinking' || obj.think) {
            var tt = String(obj.text || obj.think || '').trim();
            if (tt) appendThinkLine('✦ ' + tt);
          }
          if (obj.type === 'tool_step' || obj.tool_start) {
            var tool = String(obj.tool || obj.tool_start || '').trim();
            var phase = String(obj.phase || (obj.tool_start ? 'start' : 'end'));
            var ok = (obj.ok === true ? 'ok' : obj.ok === false ? 'fail' : '');
            var _summary = String(obj.summary || '').trim();
            var _line = '▸ ' + tool + (phase ? (' [' + phase + ']') : '') + (ok ? (' ' + ok) : '') + (_summary ? (' — ' + _summary) : '');
            if (tool) { appendThinkLine(_line); try { laylaStreamStatsStep(tool); } catch (_e) { console.debug('layla-app:', _e); } }
          }
          if (obj.type === 'model_selection' || obj.model_selection) {
            var ms = obj.model_selection || obj;
            var mdl = String(ms.model || '').replace(/^claude-/i, '').replace(/-\d{8}$/, '');
            try { var el = document.getElementById('stream-model-badge'); if (el && mdl) el.textContent = '⬡ ' + mdl; } catch (_e) { console.debug('layla-app:', _e); }
          }
          // Deliberation metadata from debate engine
          if (obj.deliberation && obj.deliberation.mode && obj.deliberation.mode !== 'solo') {
            div._deliberationMeta = obj.deliberation;
            try {
              var delibBadge = document.createElement('div');
              delibBadge.className = 'deliberation-label';
              delibBadge.style.cssText = 'font-size:0.62rem;color:var(--violet,#8844cc);padding:2px 0;font-style:italic';
              var modeLabel = {debate:'⚔ Debate',council:'⊛ Council',tribunal:'✦ Tribunal'}[obj.deliberation.mode] || obj.deliberation.mode;
              delibBadge.textContent = '✦ ' + modeLabel + ' — ' + (obj.deliberation.participating_aspects || []).length + ' voices contributing';
              var mb = div.querySelector('.msg-bubble');
              if (mb) mb.parentNode.insertBefore(delibBadge, mb);
            } catch (_e) { console.debug('layla-app:', _e); }
          }
          if (obj.token) {
            liveStatus = 'streaming';
            try { laylaNotifyStreamPhase(div, 'streaming'); } catch (_e) { console.debug('layla-app:', _e); }
            if (!gotToken) {
              gotToken = true;
              clearTimeout(firstTokenTimer);
              if (bubble && bubble.classList.contains('stream-md-placeholder')) {
                bubble.classList.remove('stream-md-placeholder');
                bubble.innerHTML = '';
              }
            }
            clearTimeout(stalledTimer);
            stalledTimer = setTimeout(function () {
              liveStatus = 'stalled';
              var statusEl = div.querySelector('.tool-status-label');
              if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; var mb = div.querySelector('.msg-bubble'); if (mb) mb.appendChild(statusEl); }
              statusEl.textContent = ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.stalled) || 'Stalled') + ' — ' + ((typeof UX_STATE_LABELS !== 'undefined' && UX_STATE_LABELS.retry_hint) || 'Retry suggested');
              try { laylaNotifyStreamPhase(div, 'stalled'); } catch (_e) { console.debug('layla-app:', _e); }
            }, stallMs);
            full += String(obj.token);
            if (bubble) bubble.textContent = full;
            try { if (full.length % 200 === 0) laylaStreamStatsChars(full.length); } catch (_e) { console.debug('layla-app:', _e); }
          }
          if (obj.done) {
            clearTimeout(firstTokenTimer);
            clearTimeout(stalledTimer);
            clearInterval(metaTimer);
            liveStatus = 'done';
            try { laylaNotifyStreamPhase(div, 'done'); } catch (_e) { console.debug('layla-app:', _e); }
            if (bubble) bubble.textContent = full;
            if (thinkBox) { try { thinkBox.open = false; } catch (_e) { console.debug('layla-app:', _e); } }
            if (window._ttsEnabled && full) { try { speakText(full).catch(function () {}); } catch (_e) { console.debug('layla-app:', _e); } }
            try { refreshMaturityCard(true); } catch (_e) { console.debug('layla-app:', _e); }
            try { laylaStreamStatsChars(full.length); laylaStreamStatsStop(); } catch (_e) { console.debug('layla-app:', _e); }
            try { if (typeof laylaIngestArtifacts === 'function') laylaIngestArtifacts(full); } catch (_e) { console.debug('layla-app:', _e); }
            // Render full deliberation transcript if available
            var _delibDone = obj.deliberation || div._deliberationMeta;
            if (_delibDone && _delibDone.mode && _delibDone.mode !== 'solo') {
              try { if (typeof _renderDeliberationTranscript === 'function') _renderDeliberationTranscript(div, _delibDone); } catch (_e) { console.debug('layla-app:', _e); }
            }
          }
        }
      }
    } else {
      // Non-stream JSON mode
      var res = await fetchWithTimeout(
        '/agent',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: ac.signal },
        Math.max(laylaAgentTimeoutMs(), 120000)
      );
      var data = {};
      try { data = await res.json(); } catch (_) { data = {}; }
      if (!res.ok || !data || data.ok === false) {
        try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('layla-app:', _e); }
        addMsg('layla', formatAgentError(res, data || {}));
        try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_e) { console.debug('layla-app:', _e); }
        return;
      }
      try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('layla-app:', _e); }
      var resp = (data && (data.response || data.reply)) || '(no output)';
      var replyAspect = (data && (data.aspect || (data.state && data.state.aspect))) || msgAspect;
      var _steps = data && data.state && data.state.steps;
      var _delib = _steps && _steps.some(function (s) { return s.deliberated; });
      var _uxStates = data && data.state && data.state.ux_states;
      var _memInf = data && data.state && data.state.memory_influenced;
      addMsg('layla', resp, replyAspect, _delib, _steps, _uxStates, _memInf);
      if (window._ttsEnabled && resp && resp !== '(no output)') { try { speakText(resp).catch(function () {}); } catch (_e) { console.debug('layla-app:', _e); } }
      try { refreshMaturityCard(true); } catch (_e) { console.debug('layla-app:', _e); }
      try { laylaStreamStatsStop(); } catch (_e) { console.debug('layla-app:', _e); }
      try { if (typeof laylaIngestArtifacts === 'function') laylaIngestArtifacts(resp); } catch (_e) { console.debug('layla-app:', _e); }
    }
  } catch (e) {
    try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('layla-app:', _e); }
    addMsg('layla', 'Error: ' + (e && e.message ? e.message : String(e)));
    try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_e) { console.debug('layla-app:', _e); }
  } finally {
    window._laylaSendBusy = false;
    try { if (firstTokenTimer) clearTimeout(firstTokenTimer); } catch (_e) { console.debug('layla-app:', _e); }
    try { if (stalledTimer) clearTimeout(stalledTimer); } catch (_e) { console.debug('layla-app:', _e); }
    try { if (metaTimer) clearInterval(metaTimer); } catch (_e) { console.debug('layla-app:', _e); }
    try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('layla-app:', _e); }
    try { if (window.laylaChatFSM) window.laylaChatFSM.finishOk(); } catch (_e) { console.debug('layla-app:', _e); }
    try { laylaHeaderProgressStop(); } catch (_e) { console.debug('layla-app:', _e); }
    try { laylaStreamStatsStop(); } catch (_e) { console.debug('layla-app:', _e); }
    try { refreshApprovals(); } catch (_e) { console.debug('layla-app:', _e); }
    try { updateContextChip(); } catch (_e) { console.debug('layla-app:', _e); }
    try { if (typeof laylaScrollActiveConversationIntoView === 'function') laylaScrollActiveConversationIntoView(); } catch (_e) { console.debug('layla-app:', _e); }
  }
}

window.send = send;

} catch (_) {
  // UI script should fail soft; server still usable.
}

// ── UI repair shims ──────────────────────────────────────────────────────────
var __esc = (typeof window.escapeHtml === 'function')
  ? window.escapeHtml
  : function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
var __toast = (typeof window.showToast === 'function')
  ? window.showToast
  : function (t) { try { console.log('[Layla UI]', t); } catch (_e) { console.debug('layla-app:', _e); } };

async function refreshVersionInfo() {
  var el = document.getElementById('app-version');
  if (!el) return;
  el.textContent = 'Version: loading…';
  try {
    var r = await fetch('/version');
    var d = await r.json().catch(function () { return {}; });
    var v = (d && d.ok && d.version) ? String(d.version) : '';
    el.textContent = 'Version: ' + (v || '—');
  } catch (_) {
    el.textContent = 'Version: (could not load)';
  }
}
window.refreshVersionInfo = refreshVersionInfo;

async function refreshPlatformHealth() {
  var box = document.getElementById('platform-health');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    var r = await fetch('/health');
    var d = await r.json().catch(function () { return {}; });
    var status = String((d && d.status) || 'unknown');
    var html = [];
    html.push('<div><strong>Status</strong>: ' + __esc(status) + '</div>');
    html.push('<div><strong>Uptime</strong>: ' + __esc(String(Math.round((d && d.uptime_seconds) || 0))) + 's</div>');
    html.push('<div><strong>Model</strong>: ' + __esc((d && d.model_loaded) ? 'loaded' : 'not loaded') + '</div>');
    html.push('<div><strong>Tools</strong>: ' + __esc(String((d && d.tools_registered) || 0)) + '</div>');
    html.push('<div><strong>Learnings</strong>: ' + __esc(String((d && d.learnings) || 0)) + '</div>');
    html.push('<div><strong>Study plans</strong>: ' + __esc(String((d && d.study_plans) || 0)) + '</div>');
    html.push('<div><strong>Vector store</strong>: ' + __esc(String((d && d.vector_store) || 'unknown')) + '</div>');
    box.innerHTML = html.join('');
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load health</span>';
  }
}
window.refreshPlatformHealth = refreshPlatformHealth;

async function refreshRuntimeOptions() {
  var box = document.getElementById('runtime-options-panel');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Loading…</span>';
  try {
    var r = await fetch('/health?deep=true');
    var d = await r.json().catch(function () { return {}; });
    var html = [];
    html.push('<div style="display:flex;flex-wrap:wrap;gap:6px">');
    html.push('<span class="option-pill">safe_mode: ' + __esc(String(!!(d && d.safe_mode))) + '</span>');
    html.push('<span class="option-pill">uncensored: ' + __esc(String(!!(d && d.uncensored))) + '</span>');
    html.push('<span class="option-pill">nsfw_allowed: ' + __esc(String(!!(d && d.nsfw_allowed))) + '</span>');
    html.push('<span class="option-pill">use_chroma: ' + __esc(String(!!(d && d.use_chroma))) + '</span>');
    html.push('</div>');
    if (d && d.limits) {
      html.push('<div style="margin-top:8px"><strong>Limits</strong></div>');
      html.push('<div style="color:var(--text-dim);font-size:0.7rem;line-height:1.5">');
      html.push('max_active_runs: ' + __esc(String(d.limits.max_active_runs != null ? d.limits.max_active_runs : '—')) + '<br>');
      html.push('max_cpu_percent: ' + __esc(String(d.limits.max_cpu_percent != null ? d.limits.max_cpu_percent : '—')) + '<br>');
      html.push('max_ram_percent: ' + __esc(String(d.limits.max_ram_percent != null ? d.limits.max_ram_percent : '—')) + '<br>');
      html.push('</div>');
    }
    box.innerHTML = html.join('');
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load runtime options</span>';
  }
}
window.refreshRuntimeOptions = refreshRuntimeOptions;

// ── DOMContentLoaded: init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  // Theme restore
  try {
    var th = localStorage.getItem('layla_theme');
    if (th === 'light') document.body.classList.add('theme-light');
    else document.body.classList.remove('theme-light');
  } catch (_e) { console.debug('layla-app:', _e); }

  // Module init hooks (functions may not exist if module not loaded yet — try/catch)
  try { if (typeof refreshWorkspacePresetsDropdown === 'function') refreshWorkspacePresetsDropdown(); } catch (_e) { console.debug('layla-app:', _e); }
  try { if (typeof toggleSendButton === 'function') toggleSendButton(); } catch (_e) { console.debug('layla-app:', _e); }

  // Health polling (header status badge)
  try {
    function laylaBasenameDisplay(p) {
      if (!p) return '';
      var s = String(p).trim();
      var i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
      return i >= 0 ? s.slice(i + 1) : s;
    }
    function laylaPollHeaderDeep() {
      var el = document.getElementById('header-system-status');
      if (!el) return;
      fetch('/health?deep=true', { cache: 'no-store' }).then(function (r) {
        return r.json().then(function (d) { return { r: r, d: d }; });
      }).then(function (x) {
        if (!x.r.ok) { el.textContent = 'degraded'; return; }
        var d = x.d || {};
        try { if (typeof laylaApplyUiTimeoutsFromHealth === 'function') laylaApplyUiTimeoutsFromHealth(d); } catch (_e) { console.debug('layla-app:', _e); }
        var mode = (d.remote_mode ? 'remote' : 'local');
        var raw = String(d.active_model || d.model_path || d.model || d.model_filename || '').trim();
        var tail = laylaBasenameDisplay(raw);
        el.title = raw ? raw : '';
        if (tail.length > 28) tail = tail.slice(0, 28);
        el.textContent = mode + (tail ? ' · ' + tail : '');
      }).catch(function () { el.textContent = 'offline'; });
    }
    laylaPollHeaderDeep();
    var _pollHealthTimer = setInterval(laylaPollHeaderDeep, 20000);

    // Connection banner
    var ban = document.getElementById('connection-banner');
    function laylaPingConn() {
      fetch('/health', { cache: 'no-store' }).then(function () {
        if (navigator.onLine && ban) ban.style.display = 'none';
      }).catch(function () {
        if (ban) ban.style.display = 'block';
      });
    }
    window.addEventListener('online', function () { if (ban) ban.style.display = 'none'; });
    window.addEventListener('offline', function () { if (ban) ban.style.display = 'block'; });
    var _pollConnTimer = setInterval(laylaPingConn, 15000);
    laylaPingConn();
  } catch (_e) { console.debug('layla-app:', _e); }

  // Header context row
  try {
    laylaRefreshHeaderContextRow();
    var _pollCtxTimer = setInterval(function () { try { laylaRefreshHeaderContextRow(); } catch (_e) { console.debug('layla-app:', _e); } }, 12000);
  } catch (_e) { console.debug('layla-app:', _e); }

  // Setup overlay listeners
  try {
    var sw = document.getElementById('setup-workspace-path');
    if (sw) {
      sw.addEventListener('input', function () { sw.setAttribute('data-user-edited', '1'); });
    }
    var cu = document.getElementById('setup-custom-url');
    if (cu && typeof _setupRefreshDownloadButton === 'function') {
      cu.addEventListener('input', _setupRefreshDownloadButton);
    }
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      var so = document.getElementById('setup-overlay');
      if (so && so.classList.contains('visible')) {
        if (typeof dismissSetupOverlay === 'function') dismissSetupOverlay(true);
        else so.classList.remove('visible');
        ev.preventDefault();
        return;
      }
      var ob = document.getElementById('onboarding-overlay');
      if (ob && ob.classList.contains('visible')) {
        if (typeof dismissOnboarding === 'function') dismissOnboarding();
        ev.preventDefault();
      }
    });
  } catch (_e) { console.debug('layla-app:', _e); }

  // P4-3: Pause polling when tab is hidden to save resources
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      // Clear all polling intervals
      if (typeof _pollHealthTimer !== 'undefined' && _pollHealthTimer) clearInterval(_pollHealthTimer);
      if (typeof _pollConnTimer !== 'undefined' && _pollConnTimer) clearInterval(_pollConnTimer);
      if (typeof _pollCtxTimer !== 'undefined' && _pollCtxTimer) clearInterval(_pollCtxTimer);
    } else {
      // Restart polling when tab becomes visible again
      try { laylaPollHeaderDeep(); _pollHealthTimer = setInterval(laylaPollHeaderDeep, 20000); } catch (_e) { console.debug('layla-app:', _e); }
      try { laylaPingConn(); _pollConnTimer = setInterval(laylaPingConn, 15000); } catch (_e) { console.debug('layla-app:', _e); }
      try { laylaRefreshHeaderContextRow(); _pollCtxTimer = setInterval(function () { try { laylaRefreshHeaderContextRow(); } catch (_e) { console.debug('layla-app:', _e); } }, 12000); } catch (_e) { console.debug('layla-app:', _e); }
    }
  });

  // First-run setup check
  if (typeof checkSetupStatus === 'function') checkSetupStatus();
});

window.laylaCoreModuleLoaded = true;
