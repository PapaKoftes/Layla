/**
 * components/app.js — Main orchestrator: send(), executePlan(), health,
 * panel routing, and DOMContentLoaded init.
 *
 * Converted from js/layla-app.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast, _dbg)
 *             components/chat-render.js (addMsg, addSeparator, hideEmpty,
 *               laylaHeaderProgressStart/Stop, operatorTraceClear,
 *               laylaStreamStatsStart/Step/Chars/Stop, laylaNotifyStreamPhase,
 *               laylaShowTypingIndicator, laylaRemoveTypingIndicator,
 *               toggleSendButton, UX_STATE_LABELS, laylaAgentStreamTimeoutMs,
 *               laylaStalledSilenceMs, _renderDeliberationTranscript)
 *             components/aspect.js (formatLaylaLabelHtml)
 *
 * Heavy cross-module deps resolved at call-time via window.* guards:
 *   fetchWithTimeout, formatAgentError, laylaAgentTimeoutMs, ASPECTS,
 *   refreshApprovals, updateContextChip, laylaScrollActiveConversationIntoView,
 *   refreshMaturityCard, speakText, laylaIngestArtifacts, refreshGrowthDashboard,
 *   refreshClusterStatus, refreshContentPolicyToggles, refreshMissionStatus,
 *   showResearchTab, loadProjectsIntoSelect, _hideMentionDropdown,
 *   checkSetupStatus, dismissSetupOverlay, dismissOnboarding,
 *   refreshWorkspacePresetsDropdown, sanitizeHtml
 */

import { escapeHtml, showToast, _dbg, cleanLaylaText } from '../services/utils.js';
import {
  addMsg, addSeparator, hideEmpty,
  laylaHeaderProgressStart, laylaHeaderProgressStop,
  operatorTraceClear,
  laylaStreamStatsStart, laylaStreamStatsStep, laylaStreamStatsChars, laylaStreamStatsStop,
  laylaNotifyStreamPhase,
  laylaShowTypingIndicator, laylaRemoveTypingIndicator,
  toggleSendButton, UX_STATE_LABELS,
  laylaAgentStreamTimeoutMs, laylaStalledSilenceMs,
  _renderDeliberationTranscript, enhanceCodeBlocks,
} from './chat-render.js';
import { formatLaylaLabelHtml } from './aspect.js';

// ── Global state ─────────────────────────────────────────────────────────────
// Ensure health state object exists (may already be set by legacy code)
window.__laylaHealth = window.__laylaHealth || {
  payload: null,
  lastFetch: 0,
  lastDeepFetch: 0,
  deepIntervalMs: 60000,
  inFlight: false,
  agentRequestActive: false,
  _inFlightPromise: null,
};

// Aspect + conversation globals (may already be set by aspect.js module)
if (typeof window.currentAspect === 'undefined') window.currentAspect = 'morrigan';
try {
  if (!window.currentConversationId) {
    window.currentConversationId = localStorage.getItem('layla_current_conversation_id') || '';
  }
} catch (_) {}
var sessionStart = Date.now();

// ── Internal state ──────────────────────────────────────────────────────────
var _lastDisplayMsg = null;
window._lastDisplayMsg = null;
var _activeAgentAbort = null;

// ── Cancel / busy state ──────────────────────────────────────────────────────
export function cancelActiveSend() {
  try {
    if (_activeAgentAbort) _activeAgentAbort.abort();
  } catch (_e) { console.debug('app:', _e); }
  try { laylaHeaderProgressStop(); } catch (_e) { console.debug('app:', _e); }
}

export function setCancelSendVisible(visible) {
  var b = document.getElementById('cancel-send-btn');
  if (b) b.style.display = visible ? 'inline-block' : 'none';
}

// ── Header context row ───────────────────────────────────────────────────────
export function laylaRefreshHeaderContextRow() {
  try {
    var cid = String(window.currentConversationId || '').trim();
    var el = document.getElementById('header-conv-id');
    if (el) {
      el.textContent = cid ? ('conv ' + cid.slice(0, 8)) : 'new chat';
      el.title = cid ? ('conversation_id: ' + cid) : 'No conversation id yet';
    }
  } catch (_e) { console.debug('app:', _e); }
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

// ── Conversation ID helper ───────────────────────────────────────────────────
export function ensureLaylaConversationId() {
  if (typeof window.currentConversationId === 'string' && String(window.currentConversationId).trim()) {
    try { laylaRefreshHeaderContextRow(); } catch (_e) { console.debug('app:', _e); }
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
  try { localStorage.setItem('layla_current_conversation_id', id); } catch (_e) { console.debug('app:', _e); }
  try { if (typeof window.updateContextChip === 'function') window.updateContextChip(); } catch (_e) { console.debug('app:', _e); }
  try { laylaRefreshHeaderContextRow(); } catch (_e) { console.debug('app:', _e); }
  return id;
}

// ── Panel refresh routing ────────────────────────────────────────────────────
export function panelRefreshRouting(main) {
  if (main === 'status') {
    refreshPlatformHealth();
    refreshVersionInfo();
    refreshRuntimeOptions();
    if (typeof window.refreshGrowthDashboard === 'function') try { window.refreshGrowthDashboard(); } catch (_) {}
    if (typeof window.refreshClusterStatus === 'function') try { window.refreshClusterStatus(); } catch (_) {}
  }
  if (main === 'prefs') {
    if (typeof window.refreshContentPolicyToggles === 'function') try { window.refreshContentPolicyToggles(); } catch (_) {}
    try { if (typeof window.refreshApprovals === 'function') window.refreshApprovals(); } catch (_e) { console.debug('app:', _e); }
    try { if (typeof window.loadProjectsIntoSelect === 'function') window.loadProjectsIntoSelect(); } catch (_e) { console.debug('app:', _e); }
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
    if (typeof window.refreshMissionStatus === 'function') {
      window.refreshMissionStatus().then(function () {
        var t = document.querySelector('#research-mission-panel .tab-btn.active');
        if (t && typeof window.showResearchTab === 'function') window.showResearchTab(t.getAttribute('data-tab'));
      });
    }
  }
  if (main === 'growth') {
    if (typeof window.refreshGrowthDashboard === 'function') {
      try { window.refreshGrowthDashboard(); } catch (_e) { console.debug('app: growth refresh', _e); }
    }
  }
  if (main === 'cluster') {
    if (typeof window.refreshClusterStatus === 'function') {
      try { window.refreshClusterStatus(); } catch (_e) { console.debug('app: cluster refresh', _e); }
    }
  }
}

// ── executePlan ──────────────────────────────────────────────────────────────
export async function executePlan(plan, goal) {
  var workspacePath = (document.getElementById('workspace-path') ? document.getElementById('workspace-path').value : '').trim();
  var allowWrite = document.getElementById('allow-write') ? document.getElementById('allow-write').checked : false;
  var allowRun = document.getElementById('allow-run') ? document.getElementById('allow-run').checked : false;
  try { ensureLaylaConversationId(); } catch (_e) { console.debug('app:', _e); }
  try { laylaHeaderProgressStart(); } catch (_e) { console.debug('app:', _e); }
  var fetchFn = (typeof window.fetchWithTimeout === 'function') ? window.fetchWithTimeout : fetch;
  try {
    var res = await fetchFn(
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
      showToast(err);
      return;
    }
    var okAll = !!data.all_steps_ok;
    showToast(okAll ? 'Plan finished' : 'Plan finished (some steps reported issues)');
    try {
      var summary = JSON.stringify(data.results || {}, null, 2);
      addMsg('layla', '**Plan executed**\n```json\n' + summary.slice(0, 12000) + (summary.length > 12000 ? '\n…' : '') + '\n```');
    } catch (_e) { console.debug('app:', _e); }
  } catch (e) {
    var msg = (e && e.message) ? String(e.message) : String(e);
    showToast('executePlan: ' + msg);
  } finally {
    try { laylaHeaderProgressStop(); } catch (_e) { console.debug('app:', _e); }
  }
}

// ── compactConversation ──────────────────────────────────────────────────────
export async function compactConversation() {
  var fetchFn = (typeof window.fetchWithTimeout === 'function') ? window.fetchWithTimeout : fetch;
  try {
    var res = await fetchFn(
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
    showToast('Compacted · messages in buffer: ~' + tok);
    try { if (typeof window.updateContextChip === 'function') window.updateContextChip(); } catch (_e) { console.debug('app:', _e); }
  } catch (e) {
    showToast('Compact failed: ' + ((e && e.message) || e));
  }
}

// ── send() — main chat entry point ──────────────────────────────────────────
// Live context-usage meter — fed by the SSE stream's ctx_pct frames (was a dead
// "Ctx: —" placeholder). Green < 60%, amber 60–85%, red above; shows chunking hint.
function laylaUpdateCtxBar(pct) {
  var p = Number(pct);
  if (!isFinite(p)) return;
  if (p > 0 && p <= 1) p = p * 100; // tolerate a 0..1 fraction
  p = Math.max(0, Math.min(100, Math.round(p)));
  var fill = document.getElementById('ctx-bar-fill');
  var label = document.getElementById('ctx-usage-label');
  var hint = document.getElementById('token-pressure-hint');
  if (fill) { fill.style.width = p + '%'; fill.style.background = p >= 85 ? '#d0454e' : (p >= 60 ? '#e0a020' : '#3a7'); }
  if (label) label.textContent = 'Ctx: ' + p + '%';
  if (hint) hint.style.display = p >= 60 ? '' : 'none';
}

// Pipeline clarify — render the server's questions into the panel and show it
// (was: server returned questions, the UI only ever hid the panel + read answers).
function laylaShowPipelineClarify(questions) {
  var panel = document.getElementById('pipeline-clarify-panel');
  if (!panel) return;
  var qs = Array.isArray(questions) ? questions : (questions ? [questions] : []);
  var text = qs.map(function (q, i) {
    if (q && typeof q === 'object') return (i + 1) + '. ' + (q.question || q.text || q.prompt || JSON.stringify(q));
    return (i + 1) + '. ' + String(q);
  }).join('\n');
  var pre = panel.querySelector('.pipeline-clarify-questions');
  if (pre) pre.textContent = text || 'The pipeline needs a bit more detail to proceed.';
  panel.style.display = 'block';
  try { var ta = document.getElementById('pipeline-clarify-answers'); if (ta) ta.focus(); } catch (_e) { console.debug('app:', _e); }
}

export async function send() {
  _dbg('send() called');
  try { if (typeof window._hideMentionDropdown === 'function') window._hideMentionDropdown(); } catch (_e) { console.debug('app:', _e); }
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
  try { laylaHeaderProgressStart(); } catch (_e) { console.debug('app:', _e); }
  try { operatorTraceClear(); } catch (_e) { console.debug('app:', _e); }
  try { laylaStreamStatsStart(''); } catch (_e) { console.debug('app:', _e); }

  var msgAspect = window.currentAspect;
  // A leading @mention switches the aspect for this turn. Tolerate leading whitespace,
  // accept an unambiguous partial/typo (@ny or @nyxx -> nyx when exactly one aspect
  // matches), and — instead of the old silent no-op — tell the user when a @word looks
  // like a mention but resolves to nothing.
  var mentionMatch = msg.match(/^\s*@([a-z]+)\s*/i);
  if (mentionMatch) {
    try {
      var mentioned = mentionMatch[1].toLowerCase();
      var ASPECTS = window.ASPECTS || [];
      var found = ASPECTS.find(function (a) { return a.id === mentioned || (a.name || '').toLowerCase() === mentioned; });
      if (!found) {
        var fuzzy = ASPECTS.filter(function (a) {
          var id = a.id;
          return id.indexOf(mentioned) === 0 || (mentioned.indexOf(id) === 0 && mentioned.length - id.length <= 2);
        });
        if (fuzzy.length === 1) found = fuzzy[0];
      }
      if (found) {
        msgAspect = found.id;
        msg = msg.slice(mentionMatch[0].length).trim() || msg;
      } else {
        var _hint = ASPECTS.slice(0, 3).map(function (a) { return '@' + a.id; }).join(', ');
        try { showToast('No aspect “@' + mentioned + '”. Try ' + (_hint || '@morrigan') + '…'); } catch (_t) {}
      }
    } catch (_e) { console.debug('app:', _e); }
  }
  if (window._aspectLocked) msgAspect = window.currentAspect;

  input.value = '';
  try { toggleSendButton(); } catch (_e) { console.debug('app:', _e); }
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
  try { projectId = (localStorage.getItem('layla_active_project_id') || '').trim(); } catch (_e) { console.debug('app:', _e); }
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
  // Wire the previously-dead composer toggles to the fields the server expects
  // (agent.py reads req.plan_mode and req.reasoning_effort=="high").
  var _planEl = document.getElementById('plan-mode-toggle');
  if (_planEl && _planEl.checked) payload.plan_mode = true;
  var _reEl = document.getElementById('reasoning-effort');
  if (_reEl && _reEl.checked) payload.reasoning_effort = 'high';
  var _epSel = document.getElementById('engineering-pipeline-mode');
  if (_epSel && _epSel.value && _epSel.value !== 'chat') payload.engineering_pipeline_mode = _epSel.value;
  var _clarTa = document.getElementById('pipeline-clarify-answers');
  if (_clarTa && _clarTa.value.trim()) {
    payload.clarification_reply = _clarTa.value.trim();
    _clarTa.value = '';
    var _cp = document.getElementById('pipeline-clarify-panel');
    if (_cp) _cp.style.display = 'none';
  }

  // Working notes are one-shot context for THIS turn — clear after capture so
  // they don't silently ride along on every later message (was a context leak).
  if (composeDraft && composeDraftEl) {
    composeDraftEl.value = '';
    try { localStorage.removeItem('layla_compose_draft'); } catch (_e) { console.debug('app:', _e); }
  }

  try { laylaShowTypingIndicator(msgAspect, streamMode ? 'connecting' : 'preparing_reply'); } catch (_e) { console.debug('app:', _e); }

  var fetchFn = (typeof window.fetchWithTimeout === 'function') ? window.fetchWithTimeout : fetch;
  var formatErr = (typeof window.formatAgentError === 'function') ? window.formatAgentError : function (r, b) { return 'Error: HTTP ' + (r && r.status); };
  var sanitize = (typeof window.sanitizeHtml === 'function') ? window.sanitizeHtml : function (h) { return h; };

  try {
    if (streamMode) {
      var res = await fetchFn(
        '/agent',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: ac.signal },
        Math.max(laylaAgentStreamTimeoutMs(), 300000)
      );
      if (!res.ok || !res.body) {
        var body = {};
        try { var t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) {} } catch(_) {}
        try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('app:', _e); }
        addMsg('layla', formatErr(res, body));
        try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_e) { console.debug('app:', _e); }
        return;
      }
      try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('app:', _e); }
      try { if (window.laylaChatFSM) window.laylaChatFSM.beginStream(); } catch (_e) { console.debug('app:', _e); }
      var reader = res.body.getReader();
      var dec = new TextDecoder();
      var full = '';
      hideEmpty();
      var div = document.createElement('div');
      div.className = 'msg msg-layla';
      div.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(msgAspect) + '</div><div class="msg-bubble" title="Click to copy"><div class="md-content stream-md-placeholder"><div class="typing-indicator" style="min-height:36px"><div class="typing-dots"><span></span><span></span><span></span></div></div><div class="tool-status-label">' + (UX_STATE_LABELS.connecting || 'Connecting') + '</div></div></div>';
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
      streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS.connecting || 'Connecting') + ' · 0s · 0 chars';
      div.appendChild(streamMeta);
      var streamStartedAt = Date.now();
      var liveStatus = 'connecting';
      try { laylaNotifyStreamPhase(div, 'connecting'); } catch (_e) { console.debug('app:', _e); }
      metaTimer = setInterval(function () {
        var secs = Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000));
        streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS[liveStatus] || liveStatus) + ' · ' + secs + 's · ' + (full || '').length + ' chars';
      }, 500);
      var gotToken = false;
      var _lastCharsReported = 0;
      firstTokenTimer = setTimeout(function () {
        liveStatus = 'waiting_first_token';
        var statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; var mb = div.querySelector('.msg-bubble'); if (mb) mb.appendChild(statusEl); }
        statusEl.textContent = UX_STATE_LABELS.waiting_first_token || 'Waiting for first token';
        try { laylaNotifyStreamPhase(div, liveStatus); } catch (_e) { console.debug('app:', _e); }
      }, 1800);
      // Connection-audit fix: a bare keepalive `pulse` proves the SOCKET is alive, NOT that
      // work is progressing — so pulses must NOT reset these timers (that's the bug that let
      // the UI spin "Thinking" forever during a hung/cold model load). Only real frames
      // (ux_state/token/tool/thinking/done) count as progress via _markRealProgress().
      // Soft-stall warning must be STRICTLY ABOVE the server keepalive (default 20s) or a
      // healthy-but-slow first token on a cold model trips "Still working… · 0 chars" every time.
      var STALL_WARN_MS = Math.max(45000, (typeof laylaStalledSilenceMs === 'function' ? laylaStalledSilenceMs() : 45000));
      var HARD_SILENCE_MS = 150000;   // no real progress frame this long → abort + offer retry
      var hardTimer = null;
      function _showStalled() {
        liveStatus = 'still_working';
        var statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; var mb = div.querySelector('.msg-bubble'); if (mb) mb.appendChild(statusEl); }
        // Before the first token, a slow wait is model warm-up (prefill), not a stall.
        statusEl.textContent = gotToken
          ? (UX_STATE_LABELS.still_working || 'Still working…')
          : (UX_STATE_LABELS.loading_model || 'Warming up the model… (first reply can take a bit)');
        try { laylaNotifyStreamPhase(div, gotToken ? 'still_working' : 'loading_model'); } catch (_e) { console.debug('app:', _e); }
      }
      function _hardTimeout() {
        // No REAL progress frame for HARD_SILENCE_MS (bare keepalive pulses don't count) →
        // the stream is stuck. Abort → reader.read() rejects → the outer catch shows an
        // error + Retry and `finally` clears the busy flag, so the chat never soft-bricks
        // into an un-sendable state (the exact "connecting forever" bug).
        try { ac.abort(); } catch (_e) { console.debug('app:', _e); }
      }
      function _markRealProgress() {
        clearTimeout(stalledTimer); stalledTimer = setTimeout(_showStalled, STALL_WARN_MS);
        clearTimeout(hardTimer); hardTimer = setTimeout(_hardTimeout, HARD_SILENCE_MS);
      }
      stalledTimer = setTimeout(_showStalled, STALL_WARN_MS);
      hardTimer = setTimeout(_hardTimeout, HARD_SILENCE_MS);
      var _sseBuf = '';
      var _sawDone = false;   // set when a done frame arrives; drives post-loop finalization if not
      while (true) {
        var _read = await reader.read();
        var value = _read.value;
        var done = _read.done;
        if (done) break;
        // Carry incomplete lines across reads: a `data:` frame split across two network chunks
        // was being JSON.parsed as a half-line (throws → discarded) and its continuation arrived
        // headless and skipped — silently truncating the bubble, or losing the done frame so the
        // raw streamed text (with leaked scaffolding) was never replaced by the cleaned content.
        _sseBuf += dec.decode(value, { stream: true });
        var lines = _sseBuf.split('\n');
        _sseBuf = lines.pop();  // last element is the possibly-incomplete trailing line
        for (var li = 0; li < lines.length; li++) {
          var line = lines[li];
          if (!line.startsWith('data: ')) continue;
          var obj = null;
          try { obj = JSON.parse(line.slice(6)); } catch (_) { obj = null; }
          if (!obj) continue;
          if (obj.pulse === true) {
            // keepalive only: the socket is alive, but this is NOT progress — do NOT reset
            // the stall/hard timers (resetting them here is what let it spin forever).
          } else {
            _markRealProgress();   // any real (non-pulse) frame counts as progress
          }
          if (obj.error) {
            clearTimeout(firstTokenTimer);
            clearTimeout(stalledTimer);
            clearTimeout(hardTimer);
            clearInterval(metaTimer);
            try { div.remove(); } catch (_e) { console.debug('app:', _e); }
            try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('app:', _e); }
            addMsg('layla', String(obj.error));
            try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_e) { console.debug('app:', _e); }
            return;
          }
          if (obj.ux_state) {
            liveStatus = String(obj.ux_state);
            try { laylaNotifyStreamPhase(div, liveStatus); } catch (_e) { console.debug('app:', _e); }
            var statusEl = div.querySelector('.tool-status-label');
            if (statusEl) statusEl.textContent = UX_STATE_LABELS[liveStatus] || liveStatus;
          }
          if (typeof obj.ctx_pct === 'number') {
            try { laylaUpdateCtxBar(obj.ctx_pct); } catch (_e) { console.debug('app:', _e); }
          }
          if (obj.type === 'thinking' || obj.think) {
            // The live "Thinking" panel is a second raw model-output surface — clean it like the answer
            // bubble so a doubled "⚔ Morrigan:" / "[Layla]:" label, a reasoning trace, or "</s>" residue
            // doesn't render verbatim in the trace.
            var tt = String(obj.text || obj.think || '').trim();
            try { tt = cleanLaylaText(tt); } catch (_e) { console.debug('app:', _e); }
            if (tt) appendThinkLine('✦ ' + tt);
          }
          if (obj.type === 'tool_step' || obj.tool_start) {
            var tool = String(obj.tool || obj.tool_start || '').trim();
            var phase = String(obj.phase || (obj.tool_start ? 'start' : 'end'));
            var ok = (obj.ok === true ? 'ok' : obj.ok === false ? 'fail' : '');
            var _summary = String(obj.summary || '').trim();
            var _line = '▸ ' + tool + (phase ? (' [' + phase + ']') : '') + (ok ? (' ' + ok) : '') + (_summary ? (' — ' + _summary) : '');
            if (tool) { appendThinkLine(_line); try { laylaStreamStatsStep(tool); } catch (_e) { console.debug('app:', _e); } }
          }
          if (obj.type === 'model_selection' || obj.model_selection) {
            var ms = obj.model_selection || obj;
            var mdl = String(ms.model || '').replace(/^claude-/i, '').replace(/-\d{8}$/, '');
            try { var el = document.getElementById('stream-model-badge'); if (el && mdl) el.textContent = '⬡ ' + mdl; } catch (_e) { console.debug('app:', _e); }
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
              // Guard against a DUPLICATE badge: the backend emits obj.deliberation twice per turn
              // (mid-stream __DELIB_META__ frame + the done frame), so this block runs twice — only
              // mint the badge if one isn't already present.
              if (mb && !div.querySelector('.deliberation-label')) mb.parentNode.insertBefore(delibBadge, mb);
            } catch (_e) { console.debug('app:', _e); }
          }
          if (obj.token) {
            liveStatus = 'streaming';
            try { laylaNotifyStreamPhase(div, 'streaming'); } catch (_e) { console.debug('app:', _e); }
            if (!gotToken) {
              gotToken = true;
              clearTimeout(firstTokenTimer);
              if (bubble && bubble.classList.contains('stream-md-placeholder')) {
                bubble.classList.remove('stream-md-placeholder');
                bubble.innerHTML = '';
              }
              // Real text is now flowing — clear any lingering "Still working…" status label
              // (the server never emits ux_state:'streaming', so nothing else clears it).
              try { var _sl = div.querySelector('.tool-status-label'); if (_sl) _sl.textContent = (UX_STATE_LABELS.streaming || 'Streaming response'); } catch (_e) { console.debug('app:', _e); }
            }
            full += String(obj.token);
            if (bubble) {
              // Render markdown during streaming for better readability.
              if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
                // Balance an unclosed ``` fence: a lone opening fence makes `marked` render
                // EVERYTHING after it as one code block (the whole reply "bleeds" into monospace)
                // until the closing fence streams in. Temporarily close it for the live render;
                // the done frame re-renders the real (cleaned) text, so nothing is lost.
                var _mdSrc = full;
                // Count ``` and ~~~ fences independently (same-char open/close) and close whichever
                // is unclosed — a lone ~~~ opener bled the rest of the reply into monospace too.
                if (((_mdSrc.match(/(?:^|\n)[ \t]*`{3,}/g) || []).length % 2)) _mdSrc += '\n```';
                if (((_mdSrc.match(/(?:^|\n)[ \t]*~{3,}/g) || []).length % 2)) _mdSrc += '\n~~~';
                try { bubble.innerHTML = sanitize(marked.parse(_mdSrc)); } catch (_mdErr) { bubble.textContent = full; }
              } else { bubble.textContent = full; }
            }
            // Advance the char counter on a size DELTA, not an exact multiple — multi-char
            // token deltas step over `% 200 === 0` and freeze the counter at "0 chars".
            try { if (full.length - _lastCharsReported >= 48) { _lastCharsReported = full.length; laylaStreamStatsChars(full.length); } } catch (_e) { console.debug('app:', _e); }
          }
          if (obj.done) {
            _sawDone = true;
            clearTimeout(firstTokenTimer);
            clearTimeout(stalledTimer);
            clearTimeout(hardTimer);
            clearInterval(metaTimer);
            // Remove the live "Status: Streaming response · Ns · N chars" progress line — it was only a
            // during-stream indicator but was never torn down, so it froze permanently under the finished
            // bubble (and the non-stream/reload path never shows it).
            try { if (streamMeta) streamMeta.remove(); } catch (_e) { console.debug('app:', _e); }
            liveStatus = 'done';
            try { laylaNotifyStreamPhase(div, 'done'); } catch (_e) { console.debug('app:', _e); }
            // The server's done frame carries the CLEANED, polished final text (control
            // markers stripped, tool-echoes cut). The live `full` is the raw token stream and
            // can contain leaked scaffolding ([TOOL:…], [EARNED_TITLE:…], etc.), so prefer
            // obj.content for the final render — and sync `full` so TTS/artifacts match.
            // Prefer the server's cleaned content. If it is present but EMPTY (the reply cleaned
            // down to nothing), do NOT keep the raw streamed `full` — that still carries any leaked
            // leading tag / scaffolding and would be rendered, spoken by TTS, and scanned for
            // artifacts. Use a neutral standby so all three consumers get clean text.
            if (typeof obj.content === 'string') {
              full = obj.content.trim() ? obj.content : "Sorry — I couldn't generate a response just then. Please try again.";
            }
            // Frontend defense-in-depth: the streaming render never called cleanLaylaText (unlike the
            // non-stream/reload path via addMsg), so a decorated persona chip label the backend strip
            // missed rendered as a second broken tag. Clean the done-frame content here too.
            try { full = cleanLaylaText(full); } catch (_cl) { console.debug('app:', _cl); }
            if (bubble) {
              if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
                // Balance an unclosed fence on the DONE render too (the live render already does): a
                // reply truncated at a role boundary mid-code-block reaches here with an odd fence
                // count, and without this the whole tail rendered as one grey monospace block.
                var _dsrc = full;
                // Line-anchored counts (an INLINE ``` / ~~~ inside prose must not flip the balance).
                if (((full.match(/(?:^|\n)[ \t]*`{3,}/g) || []).length % 2)) _dsrc += '\n```';
                if (((full.match(/(?:^|\n)[ \t]*~{3,}/g) || []).length % 2)) _dsrc += '\n~~~';
                try { bubble.innerHTML = sanitize(marked.parse(_dsrc)); } catch (_mdErr) { bubble.textContent = full; }
                // ChatGPT-style copyable code blocks (syntax highlight + copy + apply buttons).
                try { enhanceCodeBlocks(bubble); } catch (_e) { console.debug('app:', _e); }
              } else { bubble.textContent = full; }
            }
            if (thinkBox) { try { thinkBox.open = false; } catch (_e) { console.debug('app:', _e); } }
            if (window._ttsEnabled && full) { try { if (typeof window.speakText === 'function') window.speakText(full).catch(function () {}); } catch (_e) { console.debug('app:', _e); } }
            try { if (typeof window.refreshMaturityCard === 'function') window.refreshMaturityCard(true); } catch (_e) { console.debug('app:', _e); }
            // Refresh the chat sidebar so a brand-new conversation's server-generated title
            // (and updated ordering) replaces the creation-time placeholder.
            try { if (typeof window.refreshConversationList === 'function') window.refreshConversationList(); } catch (_e) { console.debug('app:', _e); }
            try { laylaStreamStatsChars(full.length); laylaStreamStatsStop(); } catch (_e) { console.debug('app:', _e); }
            // Prefer the server's hardened artifact list (obj.artifacts) — it handles info-string
            // fences, ~~~ blocks and truncated blocks the client scanner would otherwise miss.
            try { if (typeof window.laylaIngestArtifacts === 'function') window.laylaIngestArtifacts((obj.artifacts && obj.artifacts.length) ? obj.artifacts : full); } catch (_e) { console.debug('app:', _e); }
            // Render full deliberation transcript if available
            var _delibDone = obj.deliberation || div._deliberationMeta;
            if (_delibDone && _delibDone.mode && _delibDone.mode !== 'solo') {
              // Drop EVERY inline LIVE badge first — the transcript's own <summary> carries the same
              // mode label, so any surviving badge showed the deliberation indicator twice. querySelectorAll
              // (not querySelector) because a double-emit could have inserted more than one.
              try { div.querySelectorAll('.deliberation-label').forEach(function (b) { b.remove(); }); } catch (_e) { console.debug('app:', _e); }
              try { _renderDeliberationTranscript(div, _delibDone); } catch (_e) { console.debug('app:', _e); }
            }
            // "Memory updated" receipt — a small chip when Layla filed a durable fact this turn.
            if (obj.memory_updated && typeof obj.memory_updated === 'string' && obj.memory_updated.trim()) {
              try {
                var _mchip = document.createElement('div');
                _mchip.className = 'memory-receipt';
                _mchip.style.cssText = 'margin-top:6px;font-size:0.66rem;color:var(--text-dim);display:flex;gap:8px;align-items:center;flex-wrap:wrap';
                var _mtxt = document.createElement('span');
                _mtxt.textContent = '✦ ' + obj.memory_updated;
                var _mlink = document.createElement('a');
                _mlink.textContent = 'Manage';
                _mlink.href = '#';
                _mlink.style.cssText = 'color:var(--asp);cursor:pointer';
                _mlink.addEventListener('click', function (e) {
                  e.preventDefault();
                  try {
                    if (typeof window.showMainPanel === 'function') window.showMainPanel('workspace');
                    var s = document.querySelector('[data-rcp-sub="memory"]'); if (s) s.click();
                    var a = document.querySelector('[data-mem-sub="about"]'); if (a) a.click();
                  } catch (_) {}
                });
                _mchip.appendChild(_mtxt);
                _mchip.appendChild(_mlink);
                div.appendChild(_mchip);
              } catch (_e) { console.debug('app:', _e); }
            }
            if (obj.status === 'pipeline_needs_input') {
              try { laylaShowPipelineClarify(obj.questions); } catch (_e) { console.debug('app:', _e); }
            }
          }
        }
      }
      // Stream ended WITHOUT a done frame (reverse-proxy read timeout / server crash after the last
      // token): the done block's finalization never ran, so the bubble still holds the RAW live render
      // of `full` (leaked scaffolding, temporary fence balance). Run the minimal finalize so it's
      // cleaned + code-enhanced. (The server's obj.content isn't available on this truncated path.)
      if (!_sawDone && bubble) {
        try { if (streamMeta) streamMeta.remove(); } catch (_e) { console.debug('app:', _e); }
        try { full = cleanLaylaText(full); } catch (_cl) { console.debug('app:', _cl); }
        try {
          if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
            var _fsrc = full;
            if (((full.match(/(?:^|\n)[ \t]*`{3,}/g) || []).length % 2)) _fsrc += '\n```';
            if (((full.match(/(?:^|\n)[ \t]*~{3,}/g) || []).length % 2)) _fsrc += '\n~~~';
            bubble.innerHTML = sanitize(marked.parse(_fsrc));
            try { enhanceCodeBlocks(bubble); } catch (_e) { console.debug('app:', _e); }
          } else { bubble.textContent = full; }
        } catch (_fe) { console.debug('app:', _fe); }
      }
    } else {
      // Non-stream JSON mode
      var agentTimeout = (typeof window.laylaAgentTimeoutMs === 'function') ? window.laylaAgentTimeoutMs() : 120000;
      var res = await fetchFn(
        '/agent',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: ac.signal },
        Math.max(agentTimeout, 120000)
      );
      var data = {};
      try { data = await res.json(); } catch (_) { data = {}; }
      if (!res.ok || !data || data.ok === false) {
        try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('app:', _e); }
        addMsg('layla', formatErr(res, data || {}));
        try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_e) { console.debug('app:', _e); }
        return;
      }
      try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('app:', _e); }
      var resp = (data && (data.response || data.reply)) || '(no output)';
      var replyAspect = (data && (data.aspect || (data.state && data.state.aspect))) || msgAspect;
      var _steps = data && data.state && data.state.steps;
      var _delib = _steps && _steps.some(function (s) { return s.deliberated; });
      var _uxStates = data && data.state && data.state.ux_states;
      var _memInf = data && data.state && data.state.memory_influenced;
      addMsg('layla', resp, replyAspect, _delib, _steps, _uxStates, _memInf);
      if (data.status === 'pipeline_needs_input') {
        try { laylaShowPipelineClarify(data.questions); } catch (_e) { console.debug('app:', _e); }
      }
      if (window._ttsEnabled && resp && resp !== '(no output)') { try { if (typeof window.speakText === 'function') window.speakText(resp).catch(function () {}); } catch (_e) { console.debug('app:', _e); } }
      try { if (typeof window.refreshMaturityCard === 'function') window.refreshMaturityCard(true); } catch (_e) { console.debug('app:', _e); }
      try { laylaStreamStatsStop(); } catch (_e) { console.debug('app:', _e); }
      // Prefer the server's hardened artifact list (data.artifacts) over re-scanning the reply text.
      try { if (typeof window.laylaIngestArtifacts === 'function') window.laylaIngestArtifacts((data.artifacts && data.artifacts.length) ? data.artifacts : resp); } catch (_e) { console.debug('app:', _e); }
    }
  } catch (e) {
    try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('app:', _e); }
    // An ABORTED/errored stream (user cancel, 150s hard-silence, or a dropped connection) throws out of
    // the read loop, skipping BOTH graceful finalizers — so the partial bubble was left rendered from
    // RAW un-cleaned tokens (a leaked '⚔ Morrigan:' label / scaffolding persisting permanently) with the
    // frozen 'Status: Streaming …' line under it. Finalize it here too.
    try { if (typeof streamMeta !== 'undefined' && streamMeta) streamMeta.remove(); } catch (_e) { console.debug('app:', _e); }
    try {
      if (typeof bubble !== 'undefined' && bubble && typeof full !== 'undefined' && full) {
        var _cf = cleanLaylaText(full);
        if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
          bubble.innerHTML = sanitize(marked.parse(_cf));
          // Match the two graceful finalizers (done-frame + no-done): wrap/highlight code blocks and
          // inject copy/apply buttons, so a code block that streamed before the abort isn't left plain.
          try { if (typeof enhanceCodeBlocks === 'function') enhanceCodeBlocks(bubble); } catch (_e2) { console.debug('app:', _e2); }
        }
        else { bubble.textContent = _cf; }
      }
    } catch (_e) { console.debug('app:', _e); }
    var errMsg = (e && e.message ? e.message : String(e));
    // Phase 6B: Enhanced error recovery with retry button
    var isTimeout = /timeout|abort|network/i.test(errMsg);
    var isServerDown = /fetch|network|failed to fetch/i.test(errMsg);
    // Build the error banner via DOM nodes (NOT an HTML string through addMsg → sanitizeHtml, which
    // strips <button>/onclick), with a real click handler pointing at the actual input id 'msg-input'
    // (the old inline handler used a non-existent 'chat-input', so even an un-sanitized button threw).
    try {
      var _chatEl2 = document.getElementById('chat');
      var _wrap = document.createElement('div');
      _wrap.className = 'msg msg-layla';
      var _banner = document.createElement('div');
      _banner.className = 'layla-error-banner';
      var _span = document.createElement('span');
      _span.textContent = isTimeout ? 'Connection timed out' : (isServerDown ? 'Server unreachable' : ('Error: ' + errMsg.substring(0, 120)));
      var _btn = document.createElement('button');
      _btn.type = 'button';
      _btn.textContent = 'Retry';
      _btn.addEventListener('click', function () {
        try {
          var _inp = document.getElementById('msg-input');
          if (_inp) _inp.value = msg || '';
          var _send = (typeof send === 'function') ? send : (typeof window.send === 'function' ? window.send : null);
          if (_send) _send();
        } catch (_re) { console.debug('app:', _re); }
      });
      _banner.appendChild(_span);
      _banner.appendChild(_btn);
      _wrap.appendChild(_banner);
      if (_chatEl2) _chatEl2.appendChild(_wrap);
    } catch (_be) {
      try { addMsg('layla', isServerDown ? 'Server unreachable — try again.' : 'Connection error — try again.'); } catch (_e2) { console.debug('app:', _e2); }
    }
    // Check if server is down and show model loading state
    if (isServerDown) {
      try { _checkServerHealth(); } catch (_hc) {}
    }
    try { if (window.laylaChatFSM) window.laylaChatFSM.finishError(); } catch (_e) { console.debug('app:', _e); }
  } finally {
    window._laylaSendBusy = false;
    try { if (firstTokenTimer) clearTimeout(firstTokenTimer); } catch (_e) { console.debug('app:', _e); }
    try { if (stalledTimer) clearTimeout(stalledTimer); } catch (_e) { console.debug('app:', _e); }
    try { if (typeof hardTimer !== 'undefined' && hardTimer) clearTimeout(hardTimer); } catch (_e) { console.debug('app:', _e); }
    try { if (metaTimer) clearInterval(metaTimer); } catch (_e) { console.debug('app:', _e); }
    try { laylaRemoveTypingIndicator(); } catch (_e) { console.debug('app:', _e); }
    try { if (window.laylaChatFSM) window.laylaChatFSM.finishOk(); } catch (_e) { console.debug('app:', _e); }
    try { laylaHeaderProgressStop(); } catch (_e) { console.debug('app:', _e); }
    try { laylaStreamStatsStop(); } catch (_e) { console.debug('app:', _e); }
    try { if (typeof window.refreshApprovals === 'function') window.refreshApprovals(); } catch (_e) { console.debug('app:', _e); }
    try { if (typeof window.updateContextChip === 'function') window.updateContextChip(); } catch (_e) { console.debug('app:', _e); }
    try { if (typeof window.laylaScrollActiveConversationIntoView === 'function') window.laylaScrollActiveConversationIntoView(); } catch (_e) { console.debug('app:', _e); }
  }
}

// Phase 6B: Server health check for error recovery
function _checkServerHealth() {
  var banner = document.createElement('div');
  banner.className = 'layla-model-loading';
  banner.id = 'layla-health-banner';
  banner.innerHTML = '<div class="spinner"></div><span>Checking server health...</span>';
  var chatEl = document.getElementById('chat-messages');
  if (chatEl) chatEl.appendChild(banner);

  var _healthPoll = setInterval(function () {
    fetch('/health', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.status === 'ok') {
          clearInterval(_healthPoll);
          var b = document.getElementById('layla-health-banner');
          if (b) {
            b.innerHTML = '<span style="color:#4caf50">Server is back online</span>';
            setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 3000);
          }
        } else {
          var b = document.getElementById('layla-health-banner');
          if (b) {
            var modelLoaded = d && d.model_loaded;
            b.innerHTML = '<div class="spinner"></div><span>' +
              (modelLoaded ? 'Server responding, model loaded' : 'Waiting for server... (model may be loading)') +
              '</span>';
          }
        }
      })
      .catch(function () {
        var b = document.getElementById('layla-health-banner');
        if (b) b.innerHTML = '<div class="spinner"></div><span>Server unreachable... retrying in 5s</span>';
      });
  }, 5000);
  // Stop polling after 2 minutes
  setTimeout(function () { clearInterval(_healthPoll); }, 120000);
}

// ── Status panel helpers ────────────────────────────────────────────────────
export async function refreshVersionInfo() {
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

export async function refreshPlatformHealth() {
  var box = document.getElementById('platform-health');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    var r = await fetch('/health');
    var d = await r.json().catch(function () { return {}; });
    var status = String((d && d.status) || 'unknown');
    var html = [];
    html.push('<div><strong>Status</strong>: ' + escapeHtml(status) + '</div>');
    html.push('<div><strong>Uptime</strong>: ' + escapeHtml(String(Math.round((d && d.uptime_seconds) || 0))) + 's</div>');
    html.push('<div><strong>Model</strong>: ' + escapeHtml((d && d.model_loaded) ? 'loaded' : 'not loaded') + '</div>');
    html.push('<div><strong>Tools</strong>: ' + escapeHtml(String((d && d.tools_registered) || 0)) + '</div>');
    html.push('<div><strong>Learnings</strong>: ' + escapeHtml(String((d && d.learnings) || 0)) + '</div>');
    html.push('<div><strong>Study plans</strong>: ' + escapeHtml(String((d && d.study_plans) || 0)) + '</div>');
    html.push('<div><strong>Vector store</strong>: ' + escapeHtml(String((d && d.vector_store) || 'unknown')) + '</div>');
    box.innerHTML = html.join('');
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load health</span>';
  }
}

export async function refreshRuntimeOptions() {
  var box = document.getElementById('runtime-options-panel');
  if (!box) return;
  box.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Loading…</span>';
  try {
    var r = await fetch('/health?deep=true');
    var d = await r.json().catch(function () { return {}; });
    var html = [];
    html.push('<div style="display:flex;flex-wrap:wrap;gap:6px">');
    html.push('<span class="option-pill">safe_mode: ' + escapeHtml(String(!!(d && d.safe_mode))) + '</span>');
    html.push('<span class="option-pill">uncensored: ' + escapeHtml(String(!!(d && d.uncensored))) + '</span>');
    html.push('<span class="option-pill">nsfw_allowed: ' + escapeHtml(String(!!(d && d.nsfw_allowed))) + '</span>');
    html.push('<span class="option-pill">use_chroma: ' + escapeHtml(String(!!(d && d.use_chroma))) + '</span>');
    html.push('</div>');
    if (d && d.limits) {
      html.push('<div style="margin-top:8px"><strong>Limits</strong></div>');
      html.push('<div style="color:var(--text-dim);font-size:0.7rem;line-height:1.5">');
      html.push('max_active_runs: ' + escapeHtml(String(d.limits.max_active_runs != null ? d.limits.max_active_runs : '—')) + '<br>');
      html.push('max_cpu_percent: ' + escapeHtml(String(d.limits.max_cpu_percent != null ? d.limits.max_cpu_percent : '—')) + '<br>');
      html.push('max_ram_percent: ' + escapeHtml(String(d.limits.max_ram_percent != null ? d.limits.max_ram_percent : '—')) + '<br>');
      html.push('</div>');
    }
    box.innerHTML = html.join('');
  } catch (_) {
    box.innerHTML = '<span style="color:var(--text-dim)">Could not load runtime options</span>';
  }
}

// ── refreshContentPolicyToggles (stub — full version in settings-full.js) ────
export function refreshContentPolicyToggles() {
  // Delegate to settings-full if available
  if (typeof window._refreshContentPolicyToggles === 'function') {
    window._refreshContentPolicyToggles();
  }
}

// ── Init ─────────────────────────────────────────────────────────────────────
export function initApp() {
  // Theme restore
  try {
    var th = localStorage.getItem('layla_theme');
    if (th === 'light') document.body.classList.add('theme-light');
    else document.body.classList.remove('theme-light');
  } catch (_e) { console.debug('app:', _e); }

  // Tool approval bypass toggle
  try {
    var bypassCb = document.getElementById('tool-approval-bypass');
    var bypassWarn = document.getElementById('bypass-warning');
    var allowWriteCb = document.getElementById('allow-write');
    var allowRunCb = document.getElementById('allow-run');
    if (bypassCb) {
      // Load initial state from server config
      fetch('/health', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        var cfg = d.effective_config || {};
        if (cfg.tool_approval_bypass) {
          bypassCb.checked = true;
          if (bypassWarn) bypassWarn.style.display = 'block';
          if (allowWriteCb) allowWriteCb.checked = true;
          if (allowRunCb) allowRunCb.checked = true;
        }
      }).catch(function () {});
      // Toggle handler
      bypassCb.addEventListener('change', function () {
        var on = bypassCb.checked;
        if (bypassWarn) bypassWarn.style.display = on ? 'block' : 'none';
        if (on) {
          if (allowWriteCb) allowWriteCb.checked = true;
          if (allowRunCb) allowRunCb.checked = true;
        }
        // Persist to server
        fetch('/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tool_approval_bypass: on })
        }).catch(function () {});
      });
    }
  } catch (_e) { console.debug('app: bypass init', _e); }

  // Module init hooks
  try { if (typeof window.refreshWorkspacePresetsDropdown === 'function') window.refreshWorkspacePresetsDropdown(); } catch (_e) { console.debug('app:', _e); }
  try { toggleSendButton(); } catch (_e) { console.debug('app:', _e); }

  // Legacy health polling (will be killed by health service via _laylaKillLegacyPolling)
  try {
    function laylaBasenameDisplay(p) {
      if (!p) return '';
      var s = String(p).trim();
      var i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
      return i >= 0 ? s.slice(i + 1) : s;
    }
    var _pollHealthTimer = null;
    function laylaPollHeaderDeep() {
      var el = document.getElementById('header-system-status');
      if (!el) return;
      fetch('/health?deep=true', { cache: 'no-store' }).then(function (r) {
        return r.json().then(function (d) { return { r: r, d: d }; });
      }).then(function (x) {
        if (!x.r.ok) { el.textContent = 'degraded'; return; }
        var d = x.d || {};
        try { if (typeof window.laylaApplyUiTimeoutsFromHealth === 'function') window.laylaApplyUiTimeoutsFromHealth(d); } catch (_e) { console.debug('app:', _e); }
        var mode = (d.remote_mode ? 'remote' : 'local');
        var raw = String(d.active_model || d.model_path || d.model || d.model_filename || '').trim();
        var tail = laylaBasenameDisplay(raw);
        el.title = raw ? raw : '';
        if (tail.length > 28) tail = tail.slice(0, 28);
        el.textContent = mode + (tail ? ' · ' + tail : '');
        var msb = document.getElementById('model-status-badge');
        if (msb) {
          var loaded = d.model_loaded;
          msb.textContent = loaded ? '● Model OK' : '○ No model';
          msb.title = loaded ? ('Model loaded' + (raw ? ': ' + raw : '')) : 'No model loaded';
          msb.style.color = loaded ? 'var(--success)' : 'var(--text-dim)';
        }
      }).catch(function () { el.textContent = 'offline'; });
    }
    laylaPollHeaderDeep();
    _pollHealthTimer = setInterval(laylaPollHeaderDeep, 20000);

    // Connection banner
    var ban = document.getElementById('connection-banner');
    var _pollConnTimer = null;
    function laylaPingConn() {
      fetch('/health', { cache: 'no-store' }).then(function () {
        if (navigator.onLine && ban) ban.style.display = 'none';
      }).catch(function () {
        if (ban) ban.style.display = 'block';
      });
    }
    window.addEventListener('online', function () { if (ban) ban.style.display = 'none'; });
    window.addEventListener('offline', function () { if (ban) ban.style.display = 'block'; });
    _pollConnTimer = setInterval(laylaPingConn, 15000);
    laylaPingConn();

    // Header context row
    laylaRefreshHeaderContextRow();
    var _pollCtxTimer = setInterval(function () { try { laylaRefreshHeaderContextRow(); } catch (_e) { console.debug('app:', _e); } }, 12000);

    // Session time ticker
    var _sessionTimeTimer = null;
    function _updateSessionTime() {
      var el = document.getElementById('session-time');
      if (!el) return;
      var elapsed = Math.floor((Date.now() - sessionStart) / 1000);
      var h = Math.floor(elapsed / 3600);
      var m = Math.floor((elapsed % 3600) / 60);
      var s = elapsed % 60;
      el.textContent = h > 0 ? (h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0'))
                              : (m + ':' + String(s).padStart(2, '0'));
    }
    _updateSessionTime();
    _sessionTimeTimer = setInterval(_updateSessionTime, 1000);

    // MIGRATION: Allow ES module health service to kill legacy polling
    window._laylaKillLegacyPolling = function () {
      try { if (_pollHealthTimer) { clearInterval(_pollHealthTimer); _pollHealthTimer = null; } } catch (_) {}
      try { if (_pollConnTimer) { clearInterval(_pollConnTimer); _pollConnTimer = null; } } catch (_) {}
      try { if (_pollCtxTimer) { clearInterval(_pollCtxTimer); _pollCtxTimer = null; } } catch (_) {}
      try { if (_sessionTimeTimer) { clearInterval(_sessionTimeTimer); _sessionTimeTimer = null; } } catch (_) {}
      try { if (typeof window._laylaStopDashPoll === 'function') window._laylaStopDashPoll(); } catch (_) {}
      console.log('[Layla] legacy polling killed — ES module health service takes over');
    };
  } catch (_e) { console.debug('app:', _e); }

  // Setup overlay Escape listeners
  try {
    var sw = document.getElementById('setup-workspace-path');
    if (sw) {
      sw.addEventListener('input', function () { sw.setAttribute('data-user-edited', '1'); });
    }
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      var so = document.getElementById('setup-overlay');
      if (so && so.classList.contains('visible')) {
        if (typeof window.dismissSetupOverlay === 'function') window.dismissSetupOverlay(true);
        else so.classList.remove('visible');
        ev.preventDefault();
        return;
      }
      var ob = document.getElementById('onboarding-overlay');
      if (ob && ob.classList.contains('visible')) {
        if (typeof window.dismissOnboarding === 'function') window.dismissOnboarding();
        ev.preventDefault();
      }
    });
  } catch (_e) { console.debug('app:', _e); }

  // Visibility change — pause/resume polling (skip if compat loaded since ES health service handles it)
  document.addEventListener('visibilitychange', function () {
    if (window.__laylaCompatLoaded) return;
  });

  // Panel refresh routing — chain hook
  var _prevRefreshHook = window.__laylaRefreshAfterShowMainPanel;
  window.__laylaRefreshAfterShowMainPanel = function (main) {
    try { if (typeof _prevRefreshHook === 'function') _prevRefreshHook(main); } catch (_e) { console.debug('app: prev hook', _e); }
    panelRefreshRouting(main);
  };

  // First-run setup check
  if (typeof window.checkSetupStatus === 'function') window.checkSetupStatus();

  console.log('[Layla] app.js initialized — core orchestrator active');
}
