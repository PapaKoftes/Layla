/**
 * layla-chat-render.js — Chat rendering, typing indicators, streaming UI,
 * message display, and stream statistics.
 *
 * Extracted from layla-app.js as part of a UI code-split.
 *
 * Dependencies (loaded before this file):
 *   - layla-utils.js  : escapeHtml, showToast, sanitizeHtml, cleanLaylaText,
 *                       fetchWithTimeout, _dbg
 *   - layla-aspect.js : ASPECTS, facetMetaFromNameOrId, formatLaylaLabelHtml,
 *                       currentAspect
 */
(function () {
  'use strict';

  // ── UX state labels ─────────────────────────────────────────────────────────
  var UX_STATE_LABELS = {
    connecting: 'Connecting',
    waiting_first_token: 'Waiting for first token',
    streaming: 'Streaming response',
    tool_running: 'Running tool',
    verifying: 'Verifying',
    thinking: 'Thinking',
    stalled: 'Stalled',
    retry_hint: 'Retry suggested',
    changing_approach: 'Changing approach',
    reframing_objective: 'Reframing objective',
    preparing_reply: 'Preparing reply…',
    still_working: 'Still working…',
    approaching_context_limit: 'Context ~70%+ full',
    context_critical: 'Context critical — compact',
  };
  window.UX_STATE_LABELS = UX_STATE_LABELS;

  // ── Stream phase notification ───────────────────────────────────────────────
  function laylaNotifyStreamPhase(row, uxKey) {
    try {
      if (window.LaylaUI && typeof window.LaylaUI.syncStreamRowPhase === 'function')
        window.LaylaUI.syncStreamRowPhase(row, uxKey);
    } catch (_) {}
  }
  window.laylaNotifyStreamPhase = laylaNotifyStreamPhase;

  // ── UI timeouts from health endpoint ────────────────────────────────────────
  function laylaApplyUiTimeoutsFromHealth(d) {
    if (!d) return;
    try {
      var lim = d.effective_limits || {};
      var ec = d.effective_config || {};
      var streamSec = Number(lim.ui_agent_stream_timeout_seconds != null ? lim.ui_agent_stream_timeout_seconds : ec.ui_agent_stream_timeout_seconds);
      var jsonSec = Number(lim.ui_agent_json_timeout_seconds != null ? lim.ui_agent_json_timeout_seconds : ec.ui_agent_json_timeout_seconds);
      var stalledOverride = Number(lim.ui_stalled_silence_ms != null ? lim.ui_stalled_silence_ms : ec.ui_stalled_silence_ms);
      window.__laylaUiTimeouts = {
        streamMs: Number.isFinite(streamSec) && streamSec > 0 ? Math.round(streamSec * 1000) : 900000,
        jsonMs: Number.isFinite(jsonSec) && jsonSec > 0 ? Math.round(jsonSec * 1000) : 720000,
        stalledMs: Number.isFinite(stalledOverride) && stalledOverride > 0 ? Math.round(stalledOverride) : 0,
        maxRuntimeSeconds: Number(lim.max_runtime_seconds) > 0 ? Number(lim.max_runtime_seconds) : 900,
        performanceMode: String(lim.performance_mode || ec.performance_mode || 'auto').toLowerCase(),
      };
    } catch (_) {}
  }
  window.laylaApplyUiTimeoutsFromHealth = laylaApplyUiTimeoutsFromHealth;

  function laylaAgentStreamTimeoutMs() {
    var t = window.__laylaUiTimeouts;
    return t && t.streamMs > 0 ? t.streamMs : 900000;
  }
  window.laylaAgentStreamTimeoutMs = laylaAgentStreamTimeoutMs;

  function laylaAgentJsonTimeoutMs() {
    var t = window.__laylaUiTimeouts;
    return t && t.jsonMs > 0 ? t.jsonMs : 720000;
  }
  window.laylaAgentJsonTimeoutMs = laylaAgentJsonTimeoutMs;

  function laylaStalledSilenceMs() {
    var t = window.__laylaUiTimeouts || {};
    if (t.stalledMs > 0) return t.stalledMs;
    var mrs = Number(t.maxRuntimeSeconds) > 0 ? Number(t.maxRuntimeSeconds) : 900;
    var pm = t.performanceMode || 'auto';
    var mult = pm === 'low' ? 2.5 : pm === 'mid' ? 1.65 : 1;
    return Math.min(240000, Math.max(38000, Math.round(mrs * 1000 * 0.42 * mult)));
  }
  window.laylaStalledSilenceMs = laylaStalledSilenceMs;

  // ── Header progress bar ─────────────────────────────────────────────────────
  function laylaHeaderProgressStart() {
    var row = document.getElementById('header-progress-row');
    var fill = document.getElementById('header-progress-fill');
    if (!row || !fill) return;
    row.style.display = 'block';
    row.classList.add('active', 'indeterminate');
    fill.style.width = '42%';
  }
  window.laylaHeaderProgressStart = laylaHeaderProgressStart;

  function laylaHeaderProgressStop() {
    var row = document.getElementById('header-progress-row');
    var fill = document.getElementById('header-progress-fill');
    if (row) {
      row.classList.remove('active', 'indeterminate');
      row.style.display = 'none';
    }
    if (fill) fill.style.width = '0%';
  }
  window.laylaHeaderProgressStop = laylaHeaderProgressStop;

  // ── Operator trace log ──────────────────────────────────────────────────────
  function operatorTraceClear() {
    var b = document.getElementById('operator-trace-log');
    if (b) b.innerHTML = '';
  }
  window.operatorTraceClear = operatorTraceClear;

  function operatorTraceLine(kind, text) {
    var b = document.getElementById('operator-trace-log');
    if (!b) return;
    var t = new Date().toISOString().slice(11, 19);
    var line = document.createElement('div');
    line.className = 'operator-trace-line';
    line.textContent = '[' + t + '] ' + kind + ': ' + String(text || '').replace(/\s+/g, ' ').slice(0, 800);
    b.appendChild(line);
    while (b.children.length > 80) b.removeChild(b.firstChild);
    b.scrollTop = b.scrollHeight;
  }
  window.operatorTraceLine = operatorTraceLine;

  // ── Stream stats dock ───────────────────────────────────────────────────────
  var _streamStatsActive = false;
  var _streamStepCount = 0;
  var _streamStartTs = 0;
  var _streamElapsedTimer = null;

  function _updateStreamStepEl() {
    var el = document.getElementById('stream-step-counter');
    if (el) el.textContent = 'step ' + _streamStepCount;
    var badge = document.getElementById('stream-step-badge');
    if (badge && _streamStepCount > 0) badge.textContent = '· ' + _streamStepCount + ' steps';
  }

  function _updateStreamElapsed() {
    if (!_streamStatsActive) return;
    var el = document.getElementById('stream-elapsed-counter');
    if (el) el.textContent = Math.round((Date.now() - _streamStartTs) / 1000) + 's';
  }

  function laylaStreamStatsStart(modelName) {
    _streamStatsActive = true;
    _streamStepCount = 0;
    _streamStartTs = Date.now();
    var row = document.getElementById('stream-stats-row');
    if (row) row.style.display = 'flex';
    var badge = document.getElementById('stream-step-badge');
    if (badge) { badge.textContent = ''; badge.style.display = 'inline'; }
    var modelEl = document.getElementById('stream-model-badge');
    if (modelEl) modelEl.textContent = modelName ? '⬡ ' + modelName : '';
    _updateStreamStepEl();
    clearInterval(_streamElapsedTimer);
    _streamElapsedTimer = setInterval(_updateStreamElapsed, 1000);
  }
  window.laylaStreamStatsStart = laylaStreamStatsStart;

  function laylaStreamStatsStep(label) {
    if (!_streamStatsActive) return;
    _streamStepCount++;
    _updateStreamStepEl();
    if (label) operatorTraceLine('step', label);
  }
  window.laylaStreamStatsStep = laylaStreamStatsStep;

  function laylaStreamStatsChars(n) {
    if (!_streamStatsActive) return;
    var el = document.getElementById('stream-token-counter');
    if (el) el.textContent = n + ' chars';
  }
  window.laylaStreamStatsChars = laylaStreamStatsChars;

  function laylaStreamStatsStop() {
    _streamStatsActive = false;
    clearInterval(_streamElapsedTimer);
    _streamElapsedTimer = null;
    var badge = document.getElementById('stream-step-badge');
    if (badge) badge.style.display = 'none';
    setTimeout(function () {
      var row = document.getElementById('stream-stats-row');
      if (row) row.style.display = 'none';
    }, 3000);
  }
  window.laylaStreamStatsStop = laylaStreamStatsStop;

  // ── Compose panel toggle ────────────────────────────────────────────────────
  function toggleComposePanel(force) {
    var p = document.getElementById('compose-panel');
    if (!p) return;
    var on;
    if (force === true) on = true;
    else if (force === false) on = false;
    else on = !p.classList.contains('visible');
    p.classList.toggle('visible', on);
    try { localStorage.setItem('layla_compose_open', on ? '1' : '0'); } catch (_) {}
  }
  window.toggleComposePanel = toggleComposePanel;

  // ── Plan review UI buttons ──────────────────────────────────────────────────
  function laylaRunPlanFromElement(el) {
    if (!el) return;
    var ta = el.querySelector('.layla-plan-json');
    var goal = el.dataset.planGoal || '';
    if (!ta) return;
    var plan;
    try {
      plan = JSON.parse(ta.value);
    } catch (e) {
      if (typeof showToast === 'function') showToast('Invalid JSON — fix the plan text');
      return;
    }
    if (!Array.isArray(plan)) {
      if (typeof showToast === 'function') showToast('Plan must be a JSON array of steps');
      return;
    }
    window.executePlan(plan, goal);
  }
  window.laylaRunPlanFromElement = laylaRunPlanFromElement;

  function laylaFormatPlanJson(btn) {
    var el = btn && btn.closest && btn.closest('.plan-review-msg');
    var ta = el && el.querySelector('.layla-plan-json');
    if (!ta) return;
    try {
      var p = JSON.parse(ta.value);
      ta.value = JSON.stringify(p, null, 2);
      if (typeof showToast === 'function') showToast('Plan reformatted');
    } catch (e) {
      if (typeof showToast === 'function') showToast('Invalid JSON');
    }
  }
  window.laylaFormatPlanJson = laylaFormatPlanJson;

  // ── Code block path guessing & approval ─────────────────────────────────────
  function _guessPathFromCodeBlock(text) {
    var lines = String(text || '').split(/\r?\n/).slice(0, 8);
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var m = line.match(/(?:file|path)\s*[:=]\s*[`'"]?([^\s`'")\]]+)/i);
      if (m && m[1]) return m[1].trim();
    }
    return '';
  }
  window._guessPathFromCodeBlock = _guessPathFromCodeBlock;

  async function _laylaApprovePendingForCodeBlock(codeText) {
    var res = await fetchWithTimeout('/pending', {}, 8000);
    var data = await res.json().catch(function () { return {}; });
    var pending = Array.isArray(data.pending) ? data.pending : [];
    var todo = pending.filter(function (e) { return e && e.status === 'pending'; });
    if (!todo.length) {
      if (typeof showToast === 'function') showToast('No pending approvals — use the Approvals panel');
      return;
    }
    var id = '';
    if (todo.length === 1) {
      id = String(todo[0].id || '');
    } else {
      var hint = _guessPathFromCodeBlock(codeText);
      for (var i = 0; i < todo.length; i++) {
        var e = todo[i];
        var args = e.args || {};
        var paths = [args.path, args.file, args.file_path, args.target_file].filter(function (x) { return x && String(x).trim(); }).map(function (x) { return String(x); });
        for (var j = 0; j < paths.length; j++) {
          var p = paths[j];
          if (hint && (p === hint || p.endsWith(hint) || p.includes(hint))) {
            id = String(e.id || '');
            break;
          }
        }
        if (id) break;
      }
      if (!id) id = String(todo[0].id || '');
    }
    if (!id) return;
    var r = await fetchWithTimeout('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id }) }, 15000);
    var body = await r.json().catch(function () { return {}; });
    if (!r.ok || !body.ok) {
      if (typeof showToast === 'function') showToast((body && body.error) ? String(body.error) : ('Approve failed: ' + r.status));
      return;
    }
    if (typeof showToast === 'function') showToast('Applied');
    try { window.refreshApprovals(); } catch (_) {}
  }
  window._laylaApprovePendingForCodeBlock = _laylaApprovePendingForCodeBlock;

  function _addApplyBtnToCodeBlock(wrap, codeEl) {
    if (!wrap || !codeEl) return;
    var applyBtn = document.createElement('button');
    applyBtn.type = 'button';
    applyBtn.className = 'copy-btn';
    applyBtn.style.marginLeft = '4px';
    applyBtn.textContent = 'apply';
    applyBtn.title = 'Approve matching pending tool call (see Approvals panel for diff)';
    applyBtn.onclick = function (ev) {
      ev.stopPropagation();
      var txt = (codeEl.innerText || codeEl.textContent || '').trim();
      _laylaApprovePendingForCodeBlock(txt).catch(function (e) {
        if (typeof showToast === 'function') showToast(String((e && e.message) || e));
      });
    };
    wrap.appendChild(applyBtn);
  }
  window._addApplyBtnToCodeBlock = _addApplyBtnToCodeBlock;

  // ── Empty state ─────────────────────────────────────────────────────────────
  function hideEmpty() {
    var e = document.getElementById('chat-empty');
    if (e) e.style.display = 'none';
  }
  window.hideEmpty = hideEmpty;

  function renderPromptTilesAndEmptyState() {
    var isFirstRun = false;
    try { isFirstRun = !localStorage.getItem('layla_onboarded'); } catch (_) {}

    var welcomeBlock = '';
    if (isFirstRun) {
      welcomeBlock =
        '<div style="max-width:480px;text-align:left;margin:0 auto 16px;padding:14px 16px;border:1px solid var(--border);border-radius:6px;background:rgba(0,0,0,0.25)">' +
          '<div style="font-family:\'Cinzel\',serif;font-size:0.9rem;color:var(--asp);letter-spacing:0.12em;margin-bottom:8px">Welcome to Layla</div>' +
          '<div style="font-size:0.74rem;color:var(--text);line-height:1.6">' +
            'Layla is a multi-aspect AI agent with persistent memory. She grows with you.' +
          '</div>' +
          '<div style="margin-top:10px;display:flex;flex-direction:column;gap:6px;font-size:0.68rem;color:var(--text-dim);line-height:1.45">' +
            '<div><strong style="color:var(--asp-morrigan)">6 Voices</strong> — Switch between Morrigan (code), Nyx (research), Echo (empathy), Eris (creativity), Cassandra (critique), Lilith (safety) in the left panel.</div>' +
            '<div><strong style="color:var(--asp-nyx)">Persistent Memory</strong> — She remembers conversations, learns from interactions, and improves over time. Browse in Library tab.</div>' +
            '<div><strong style="color:var(--asp-echo)">Deliberation</strong> — For complex questions, multiple aspects can debate and synthesize a response. Set mode in Settings.</div>' +
            '<div><strong style="color:var(--asp-eris)">Tools</strong> — File operations, code execution, web search, research missions. Enable in Settings &rarr; Permissions.</div>' +
            '<div><strong style="color:var(--asp-cassandra)">Keyboard</strong> — Enter to send, Shift+Enter for newline, Ctrl+K to search chats, Ctrl+/ for shortcuts.</div>' +
          '</div>' +
          '<button type="button" onclick="try{localStorage.setItem(\'layla_onboarded\',\'1\');this.parentNode.style.display=\'none\';}catch(_){}" style="margin-top:10px;padding:6px 16px;font-size:0.7rem;background:var(--asp-mid);border:1px solid var(--asp);color:var(--text);border-radius:4px;cursor:pointer;font-family:\'JetBrains Mono\',monospace">Got it</button>' +
        '</div>';
    }

    return '<div class="sigil">∴</div><div class="hint">she is waiting</div>' +
      welcomeBlock +
      '<div class="prompt-tiles" id="prompt-tiles">' +
        '<button class="prompt-tile" onclick="fillPrompt(\'Explain how \')"><span class="tile-icon">✦</span><span class="tile-text">Explain something</span></button>' +
        '<button class="prompt-tile" onclick="fillPrompt(\'Write Python code to \')"><span class="tile-icon">⚔</span><span class="tile-text">Write code for me</span></button>' +
        '<button class="prompt-tile" onclick="fillPrompt(\'Research and summarize: \')"><span class="tile-icon">🔬</span><span class="tile-text">Research a topic</span></button>' +
        '<button class="prompt-tile" onclick="fillPrompt(\'Help me debug this error: \')"><span class="tile-icon">🔧</span><span class="tile-text">Debug an error</span></button>' +
        '<button class="prompt-tile" onclick="fillPrompt(\'Summarize this text: \')"><span class="tile-icon">◎</span><span class="tile-text">Summarize text</span></button>' +
        '<button class="prompt-tile" onclick="fillPrompt(\'What should I do about \')"><span class="tile-icon">⌖</span><span class="tile-text">Get advice</span></button>' +
        '<button class="prompt-tile" onclick="fillPrompt(\'Refactor this code: \')"><span class="tile-icon">⚔</span><span class="tile-text">Refactor</span></button>' +
        '<button class="prompt-tile" onclick="fillPrompt(\'Add tests for \')"><span class="tile-icon">🧪</span><span class="tile-text">Add tests</span></button>' +
      '</div>' +
      '<div class="try-this-chips" style="margin-top:16px;display:flex;flex-wrap:wrap;gap:8px;justify-content:center">' +
        '<button class="try-this-chip" onclick="fillPrompt(\'Explain quantum entanglement\')" style="padding:6px 12px;font-size:0.75rem;background:var(--asp-mid);border:1px solid var(--asp);color:var(--text);border-radius:4px;cursor:pointer">Explain quantum entanglement</button>' +
        '<button class="try-this-chip" onclick="fillPrompt(\'Write a Python hello world\')" style="padding:6px 12px;font-size:0.75rem;background:var(--asp-mid);border:1px solid var(--asp);color:var(--text);border-radius:4px;cursor:pointer">Write a Python hello world</button>' +
      '</div>' +
      '<div id="layla-capabilities-ref" style="margin-top:18px;max-width:520px;text-align:left">' +
        '<details style="font-size:0.66rem;color:var(--text-dim)">' +
          '<summary style="cursor:pointer;color:var(--asp);letter-spacing:0.08em;font-size:0.62rem;text-transform:uppercase;font-family:\'Cinzel\',serif;list-style:none">What can Layla do?</summary>' +
          '<div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;line-height:1.45">' +
            '<div>Write, refactor, and debug code</div>' +
            '<div>Research topics with web search</div>' +
            '<div>Read, create, and edit files</div>' +
            '<div>Execute shell commands (with approval)</div>' +
            '<div>Multi-aspect deliberation on decisions</div>' +
            '<div>Persistent memory across sessions</div>' +
            '<div>Spaced repetition study sessions</div>' +
            '<div>Knowledge base with semantic search</div>' +
            '<div>Plan and execute multi-step tasks</div>' +
            '<div>Voice input/output (STT + TTS)</div>' +
            '<div>Export chats, memory, and system state</div>' +
            '<div>Discord bot integration</div>' +
          '</div>' +
        '</details>' +
      '</div>';
  }
  window.renderPromptTilesAndEmptyState = renderPromptTilesAndEmptyState;

  // ── Reasoning tree summary ──────────────────────────────────────────────────
  function _renderReasoningTreeSummary(container, summary) {
    if (!summary || !Array.isArray(summary.nodes) || summary.nodes.length === 0) return;
    var wrap = document.createElement('details');
    wrap.className = 'tool-trace';
    var mode = summary.reasoning_mode ? (' • ' + summary.reasoning_mode) : '';
    wrap.innerHTML = '<summary>Reasoning summary (' + summary.nodes.length + mode + ')</summary>';
    var body = document.createElement('div');
    body.className = 'tool-trace-content';
    var lines = [];
    if (summary.goal) lines.push('Goal: ' + summary.goal);
    summary.nodes.forEach(function (n, i) {
      lines.push((i + 1) + '. [' + (n.phase || 'step') + '] ' + (n.action || 'reason') + ' -> ' + (n.outcome_summary || 'ok'));
    });
    if (summary.final_summary) lines.push('Final: ' + summary.final_summary);
    body.textContent = lines.join('\n');
    wrap.appendChild(body);
    container.appendChild(wrap);
  }
  window._renderReasoningTreeSummary = _renderReasoningTreeSummary;

  // ── Remember a Layla bubble as a learning ───────────────────────────────────
  async function rememberLaylaBubble(bubble, btn) {
    var txt = (bubble && (bubble.innerText || bubble.textContent) || '').trim();
    if (!txt) {
      showToast('Nothing to remember');
      return;
    }
    if (txt.length > 12000) {
      showToast('Message too long; copy a shorter excerpt');
      return;
    }
    if (btn) btn.disabled = true;
    try {
      var res = await fetch('/learn/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: txt, type: 'fact', tags: 'ui:remember' }),
      });
      var d = await res.json();
      if (d.ok) {
        showToast('Saved to learnings');
        if (btn) {
          btn.textContent = 'saved';
          setTimeout(function () { btn.textContent = 'remember'; btn.disabled = false; }, 2000);
        }
      } else {
        showToast(d.error || 'Save failed');
        if (btn) btn.disabled = false;
      }
    } catch (e) {
      showToast('Error: ' + (e && e.message || e));
      if (btn) btn.disabled = false;
    }
  }
  window.rememberLaylaBubble = rememberLaylaBubble;

  // ── Main chat message renderer ──────────────────────────────────────────────
  function addMsg(role, text, aspectName, deliberated, steps, uxStates, memoryInfluenced, reasoningTreeSummary) {
    hideEmpty();
    var chat = document.getElementById('chat');
    if (!chat) return;
    var div = document.createElement('div');
    div.className = 'msg msg-' + (role === 'you' ? 'you' : 'layla');

    // ── Label row ──
    var label = document.createElement('div');
    label.className = 'msg-label' + (role === 'layla' ? ' msg-label-layla' : '');
    if (role === 'you') {
      var nameSpan = document.createElement('span');
      nameSpan.textContent = 'You';
      label.appendChild(nameSpan);
    } else {
      var brand = document.createElement('span');
      brand.className = 'msg-brand';
      brand.textContent = 'Layla';
      label.appendChild(brand);
      var facet = facetMetaFromNameOrId(aspectName || window.currentAspect);
      if (facet) {
        var chip = document.createElement('span');
        chip.className = 'msg-facet-chip';
        chip.textContent = facet.sym + ' ' + facet.name;
        chip.title = 'Facet (voice)';
        label.appendChild(chip);
      } else if (aspectName) {
        var chip2 = document.createElement('span');
        chip2.className = 'msg-facet-chip msg-facet-unknown';
        chip2.textContent = String(aspectName);
        label.appendChild(chip2);
      } else {
        var chip3 = document.createElement('span');
        chip3.className = 'msg-facet-chip msg-facet-unknown';
        chip3.textContent = '◇ facet';
        chip3.title = 'Session aspect: ' + (window.currentAspect || 'morrigan');
        label.appendChild(chip3);
      }
    }

    // ── Timestamp ──
    var ts = document.createElement('span');
    ts.className = 'msg-ts';
    var now = new Date();
    ts.textContent = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0');
    label.appendChild(ts);

    // ── Bubble ──
    var bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.title = 'Click to copy';
    if (role === 'layla') {
      text = cleanLaylaText(text || '');
      if (typeof marked !== 'undefined') {
        var md = document.createElement('div');
        md.className = 'md-content';
        var parsed = '';
        try { parsed = marked.parse(text || ''); } catch (_) { parsed = (text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
        md.innerHTML = sanitizeHtml(parsed);
        // Syntax highlight + copy buttons on code blocks
        md.querySelectorAll('pre').forEach(function (pre) {
          var code = pre.querySelector('code');
          if (code && window.hljs) window.hljs.highlightElement(code);
          var wrap = document.createElement('div');
          wrap.className = 'code-wrap';
          pre.parentNode.insertBefore(wrap, pre);
          wrap.appendChild(pre);
          var copyBtn = document.createElement('button');
          copyBtn.className = 'copy-btn';
          copyBtn.textContent = 'copy';
          copyBtn.onclick = function () {
            var clipText = code ? code.innerText : pre.innerText;
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(clipText).then(function () {
                copyBtn.textContent = 'copied';
                copyBtn.classList.add('copied');
                setTimeout(function () { copyBtn.textContent = 'copy'; copyBtn.classList.remove('copied'); }, 1800);
              });
            }
          };
          wrap.appendChild(copyBtn);
          // Apply-to-file button (if filename detectable)
          if (code) _addApplyBtnToCodeBlock(wrap, code);
        });
        bubble.appendChild(md);
      } else {
        bubble.textContent = text;
      }
    } else {
      bubble.textContent = text;
    }

    // ── Copy & remember buttons (Layla messages) ──
    if (role === 'layla') {
      var copyBtn = document.createElement('button');
      copyBtn.className = 'msg-copy-btn';
      copyBtn.textContent = 'copy';
      copyBtn.title = 'Copy response';
      copyBtn.setAttribute('aria-label', 'Copy response');
      copyBtn.onclick = function (ev) {
        ev.stopPropagation();
        var txt = (bubble.innerText || bubble.textContent || '').trim();
        if (txt && navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(txt).then(function () {
            copyBtn.textContent = 'copied';
            copyBtn.classList.add('copied');
            setTimeout(function () { copyBtn.textContent = 'copy'; copyBtn.classList.remove('copied'); }, 1500);
          }).catch(function () {});
        }
      };
      label.appendChild(copyBtn);

      var rememberBtn = document.createElement('button');
      rememberBtn.className = 'msg-remember-btn';
      rememberBtn.type = 'button';
      rememberBtn.textContent = 'remember';
      rememberBtn.title = 'Save this reply as a learning';
      rememberBtn.setAttribute('aria-label', 'Remember this message');
      rememberBtn.onclick = function (ev) {
        ev.stopPropagation();
        rememberLaylaBubble(bubble, rememberBtn);
      };
      label.appendChild(rememberBtn);
    }

    div.appendChild(label);
    div.appendChild(bubble);

    // ── UX state badges ──
    if (Array.isArray(uxStates) && uxStates.length > 0) {
      var badges = document.createElement('div');
      badges.className = 'ux-state-badges';
      uxStates.forEach(function (s) {
        var b = document.createElement('span');
        b.className = 'ux-state-badge';
        b.textContent = UX_STATE_LABELS[s] || s;
        badges.appendChild(b);
      });
      div.appendChild(badges);
    }

    // ── Memory attribution ──
    if (Array.isArray(memoryInfluenced) && memoryInfluenced.length > 0) {
      var mem = document.createElement('div');
      mem.className = 'memory-attribution';
      mem.textContent = 'Used memory: ' + (memoryInfluenced.includes('learnings') && memoryInfluenced.includes('semantic_recall') ? 'learnings & recall' : memoryInfluenced.includes('learnings') ? 'learnings' : 'recall');
      div.appendChild(mem);
    }

    // ── Tool trace (steps) ──
    if (steps && steps.length > 0) {
      var trace = document.createElement('details');
      trace.className = 'tool-trace';
      trace.innerHTML = '<summary>What she did (' + steps.length + ')</summary>';
      var pre = document.createElement('div');
      pre.className = 'tool-trace-content';
      pre.textContent = steps.map(function (s) {
        var act = (s && (s.action || s.tool)) ? String(s.action || s.tool) : '?';
        var r = (s && s.result != null) ? s.result : null;
        try {
          if (r && typeof r === 'object' && !Array.isArray(r)) {
            var ok = (typeof r.ok === 'boolean') ? (r.ok ? 'ok' : 'fail') : '';
            var msg = (r.message || r.error || r.reason || r.status || '');
            var m = (typeof msg === 'string') ? msg : String(msg || '');
            var tail = m ? (' — ' + m.replace(/\s+/g, ' ').trim().slice(0, 180)) : '';
            return act + (ok ? (' [' + ok + ']') : '') + tail;
          }
          var txt = (typeof r === 'string') ? r : JSON.stringify(r);
          return act + ': ' + String(txt || '').slice(0, 200);
        } catch (_) {
          return act + ': [unserializable]';
        }
      }).join('\n');
      trace.appendChild(pre);
      div.appendChild(trace);
    }

    // ── Deliberation indicator / transcript ──
    if (deliberated) {
      var d = document.createElement('details');
      d.className = 'tool-trace';
      d.style.borderLeft = '2px solid var(--violet,#8844cc)';
      d.innerHTML = '<summary style="color:var(--violet,#8844cc);font-size:0.68rem">✦ She deliberated</summary><div class="think-bubble">She weighed this with her inner voices before answering.</div>';
      div.appendChild(d);
    }
    // Attach full deliberation metadata if present (stored by SSE handler)
    if (div._deliberationMeta) {
      _renderDeliberationTranscript(div, div._deliberationMeta);
    }

    // ── Reasoning tree summary ──
    _renderReasoningTreeSummary(div, reasoningTreeSummary);

    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
  }
  window.addMsg = addMsg;

  // ── Deliberation transcript renderer ──────────────────────────────────────
  var ASPECT_SYMBOLS = {
    morrigan: '⚔', nyx: '✦', echo: '◎', eris: '⚡', cassandra: '⌖', lilith: '⊛'
  };
  var MODE_LABELS = {
    debate: '⚔ Debate (2 aspects)',
    council: '⊛ Council (3 aspects)',
    tribunal: '✦ Tribunal (all aspects)',
  };

  function _renderDeliberationTranscript(msgDiv, meta) {
    if (!meta || !meta.mode || meta.mode === 'solo') return;
    var container = document.createElement('details');
    container.className = 'deliberation';
    container.open = false;

    var aspects = meta.participating_aspects || [];
    var label = MODE_LABELS[meta.mode] || ('✦ ' + meta.mode);
    var summaryEl = document.createElement('summary');
    summaryEl.className = 'deliberation-label';
    summaryEl.innerHTML = label + ' — <span style="opacity:0.7">' + aspects.length + ' voices</span>';
    container.appendChild(summaryEl);

    // Aspect responses
    var responses = meta.aspect_responses || {};
    var critiques = meta.critiques || {};
    var hasResponses = Object.keys(responses).length > 0;
    var hasCritiques = Object.keys(critiques).length > 0;

    if (hasResponses) {
      var respSection = document.createElement('div');
      respSection.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:6px';
      aspects.forEach(function (asp) {
        if (!responses[asp]) return;
        var card = document.createElement('div');
        card.style.cssText = 'padding:6px 8px;border-left:2px solid var(--asp-' + asp + ', var(--violet));background:rgba(0,0,0,0.2);border-radius:2px';
        var header = document.createElement('div');
        header.style.cssText = 'font-size:0.66rem;font-weight:600;color:var(--asp-' + asp + ', var(--text));margin-bottom:3px;text-transform:uppercase;letter-spacing:0.08em';
        header.textContent = (ASPECT_SYMBOLS[asp] || '◇') + ' ' + asp;
        card.appendChild(header);
        var body = document.createElement('div');
        body.style.cssText = 'font-size:0.72rem;color:var(--text);line-height:1.4;white-space:pre-wrap';
        body.textContent = String(responses[asp] || '').trim().slice(0, 800);
        card.appendChild(body);

        // Show critique for this aspect if available
        if (hasCritiques && critiques[asp]) {
          var crit = document.createElement('div');
          crit.style.cssText = 'margin-top:4px;padding:4px 6px;font-size:0.66rem;color:var(--text-dim);border-top:1px solid rgba(255,255,255,0.06);font-style:italic';
          crit.textContent = '↳ Critique: ' + String(critiques[asp] || '').trim().slice(0, 400);
          card.appendChild(crit);
        }
        respSection.appendChild(card);
      });
      container.appendChild(respSection);
    }

    // Synthesis notes
    if (meta.synthesis_notes) {
      var synth = document.createElement('div');
      synth.style.cssText = 'margin-top:6px;padding:6px 8px;background:rgba(61,0,80,0.2);border:1px solid var(--border);border-radius:3px;font-size:0.68rem;color:var(--text-dim)';
      synth.innerHTML = '<strong style="color:var(--asp);font-size:0.62rem;letter-spacing:0.1em;text-transform:uppercase">Synthesis</strong>';
      var synthBody = document.createElement('div');
      synthBody.style.cssText = 'margin-top:3px;white-space:pre-wrap';
      synthBody.textContent = String(meta.synthesis_notes || '').trim().slice(0, 600);
      synth.appendChild(synthBody);
      container.appendChild(synth);
    }

    msgDiv.appendChild(container);
  }
  window._renderDeliberationTranscript = _renderDeliberationTranscript;

  // ── Separator ───────────────────────────────────────────────────────────────
  function addSeparator() {
    var chat = document.getElementById('chat');
    if (!chat) return;
    var sep = document.createElement('div');
    sep.className = 'separator';
    sep.textContent = '✦';
    chat.appendChild(sep);
  }
  window.addSeparator = addSeparator;

  // ── Typing indicator system ─────────────────────────────────────────────────
  var _laylaTypingMetaTimer = null;
  var _laylaTypingStartedAt = 0;
  var _laylaTypingPhaseTimers = [];

  function laylaClearTypingPhases() {
    _laylaTypingPhaseTimers.forEach(function (tid) { try { clearTimeout(tid); } catch (_) {} });
    _laylaTypingPhaseTimers = [];
  }
  window.laylaClearTypingPhases = laylaClearTypingPhases;

  function laylaStartNonStreamTypingPhases() {
    laylaClearTypingPhases();
    var phases = [
      { delay: 1200, key: 'thinking' },
      { delay: 8000, key: 'still_working' },
      { delay: 25000, key: 'preparing_reply' },
    ];
    phases.forEach(function (ph) {
      _laylaTypingPhaseTimers.push(setTimeout(function () {
        if (document.getElementById('typing-wrap')) laylaUpdateTypingUx(ph.key);
      }, ph.delay));
    });
  }
  window.laylaStartNonStreamTypingPhases = laylaStartNonStreamTypingPhases;

  function laylaUpdateTypingUx(uxKey) {
    var wrap = document.getElementById('typing-wrap');
    if (!wrap) return;
    var labelText = UX_STATE_LABELS[uxKey] || uxKey;
    var statusEl = wrap.querySelector('.tool-status-label');
    if (!statusEl) {
      statusEl = document.createElement('div');
      statusEl.className = 'tool-status-label';
      var bub = wrap.querySelector('.msg-bubble');
      if (bub) bub.appendChild(statusEl);
    }
    statusEl.textContent = labelText;
    var metaEl = wrap.querySelector('.memory-attribution');
    if (!metaEl) {
      metaEl = document.createElement('div');
      metaEl.className = 'memory-attribution';
      var bub2 = wrap.querySelector('.msg-bubble');
      if (bub2) bub2.appendChild(metaEl);
    }
    if (!_laylaTypingStartedAt) _laylaTypingStartedAt = Date.now();
    var secs = Math.max(0, Math.floor((Date.now() - _laylaTypingStartedAt) / 1000));
    metaEl.textContent = 'Status: ' + labelText + ' | elapsed: ' + secs + 's';
    try {
      if (window.LaylaUI && typeof window.LaylaUI.applyToTypingWrap === 'function')
        window.LaylaUI.applyToTypingWrap(wrap, uxKey);
    } catch (_) {}
  }
  window.laylaUpdateTypingUx = laylaUpdateTypingUx;

  function laylaRemoveTypingIndicator() {
    var w = document.getElementById('typing-wrap');
    if (w) w.remove();
    if (_laylaTypingMetaTimer) {
      clearInterval(_laylaTypingMetaTimer);
      _laylaTypingMetaTimer = null;
    }
    laylaClearTypingPhases();
    _laylaTypingStartedAt = 0;
    try {
      if (window.LaylaUI && typeof window.LaylaUI.clearBodyPhase === 'function') window.LaylaUI.clearBodyPhase();
    } catch (_) {}
  }
  window.laylaRemoveTypingIndicator = laylaRemoveTypingIndicator;

  function laylaShowTypingIndicator(aspectId, initialUxKey) {
    hideEmpty();
    var chatEl = document.getElementById('chat');
    if (!chatEl) return;
    var key = initialUxKey || 'connecting';
    var existing = document.getElementById('typing-wrap');
    if (existing) {
      laylaUpdateTypingUx(key);
      return;
    }
    var w = document.createElement('div');
    w.className = 'msg msg-layla';
    w.id = 'typing-wrap';
    _laylaTypingStartedAt = Date.now();
    var labelText = UX_STATE_LABELS[key] || key;
    w.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(aspectId) + '</div><div class="msg-bubble typing-indicator"><div class="typing-dots"><span></span><span></span><span></span></div><div class="tool-status-label">' + labelText + '</div><div class="memory-attribution">Status: ' + labelText + ' | elapsed: 0s</div></div>';
    chatEl.appendChild(w);
    if (_laylaTypingMetaTimer) clearInterval(_laylaTypingMetaTimer);
    _laylaTypingMetaTimer = setInterval(function () {
      var active = document.getElementById('typing-wrap');
      if (!active) return;
      var metaEl = active.querySelector('.memory-attribution');
      var statusLabelEl = active.querySelector('.tool-status-label');
      var status = (statusLabelEl && statusLabelEl.textContent) || 'Thinking';
      if (metaEl) {
        var secs = Math.max(0, Math.floor((Date.now() - _laylaTypingStartedAt) / 1000));
        metaEl.textContent = 'Status: ' + status + ' | elapsed: ' + secs + 's';
      }
    }, 500);
    try {
      if (window.LaylaUI && typeof window.LaylaUI.applyToTypingWrap === 'function')
        window.LaylaUI.applyToTypingWrap(w, key);
    } catch (_) {}
    chatEl.scrollTop = chatEl.scrollHeight;
  }
  window.laylaShowTypingIndicator = laylaShowTypingIndicator;

  // ── Reasoning chain helpers ─────────────────────────────────────────────────
  function laylaEnsureReasoningChain(msgLaylaDiv) {
    var msgBub = msgLaylaDiv.querySelector('.msg-bubble');
    if (!msgBub) return null;
    var chain = msgBub.querySelector('.layla-reasoning-chain');
    if (!chain) {
      chain = document.createElement('details');
      chain.className = 'layla-reasoning-chain tool-trace';
      chain.open = true;
      chain.innerHTML = '<summary class="layla-reasoning-summary">Reasoning</summary><div class="layla-reasoning-steps"></div>';
      var md = msgBub.querySelector('.md-content');
      if (md) msgBub.insertBefore(chain, md);
      else msgBub.insertBefore(chain, msgBub.firstChild);
    }
    return chain;
  }
  window.laylaEnsureReasoningChain = laylaEnsureReasoningChain;

  function laylaAppendReasoningStep(msgLaylaDiv, text, stepNum) {
    var chain = laylaEnsureReasoningChain(msgLaylaDiv);
    if (!chain) return;
    var steps = chain.querySelector('.layla-reasoning-steps');
    if (!steps) return;
    var n = stepNum && Number(stepNum) > 0 ? Number(stepNum) : (steps.children.length + 1);
    var row = document.createElement('div');
    row.className = 'layla-reasoning-step';
    row.innerHTML = '<span class="layla-reasoning-step-n">' + n + '.</span><div class="layla-reasoning-step-body"></div>';
    row.querySelector('.layla-reasoning-step-body').textContent = String(text || '');
    steps.appendChild(row);
    var sum = chain.querySelector('.layla-reasoning-summary');
    if (sum) sum.textContent = 'Reasoning · ' + steps.children.length + ' steps';
  }
  window.laylaAppendReasoningStep = laylaAppendReasoningStep;

  // ── Retry last message ──────────────────────────────────────────────────────
  function retryLastMessage() {
    if (!window._lastDisplayMsg) return;
    if (window.laylaChatFSM && !window.laylaChatFSM.canSend()) return;
    var chat = document.getElementById('chat');
    var input = document.getElementById('msg-input');
    if (!chat || !input) return;
    var nodes = Array.prototype.slice.call(chat.children);
    var toRemove = [];
    var foundLayla = false, foundSep = false, foundYou = false;
    for (var i = nodes.length - 1; i >= 0; i--) {
      var n = nodes[i];
      if (n.id === 'typing-wrap') { toRemove.push(n); continue; }
      if (!foundLayla && n.classList.contains('msg-layla')) { foundLayla = true; toRemove.push(n); continue; }
      if (foundLayla && !foundSep && n.classList.contains('separator')) { foundSep = true; toRemove.push(n); continue; }
      if (foundSep && !foundYou && n.classList.contains('msg-you')) { foundYou = true; toRemove.push(n); break; }
    }
    toRemove.forEach(function (el) { el.remove(); });
    input.value = window._lastDisplayMsg;
    toggleSendButton();
    window.send();
  }
  window.retryLastMessage = retryLastMessage;

  // ── FSM chat chrome sync ────────────────────────────────────────────────────
  function laylaSyncChatChromeFromFSM(state) {
    try {
      var st = String(state || (window.laylaChatFSM && window.laylaChatFSM.getState && window.laylaChatFSM.getState()) || '');
      var canSend = !(window.laylaChatFSM && window.laylaChatFSM.canSend) ? true : !!window.laylaChatFSM.canSend();
      var inFlight = st === 'sending' || st === 'streaming';
      // setCancelSendVisible is in the core (layla-app.js)
      try {
        var cancelBtn = document.getElementById('cancel-send-btn');
        if (cancelBtn) cancelBtn.style.display = inFlight ? 'inline-block' : 'none';
      } catch (_) {}
      toggleSendButton();
      if (!canSend && st !== 'sending' && st !== 'streaming') {
        window._laylaSendBusy = false;
      }
    } catch (_) {}
  }
  window.laylaSyncChatChromeFromFSM = laylaSyncChatChromeFromFSM;

  window.laylaOnChatState = function (st) {
    laylaSyncChatChromeFromFSM(st);
    try {
      if (typeof localStorage !== 'undefined' && localStorage.getItem('layla_debug_fsm') === '1') {
        try { sessionStorage.setItem('layla_chat_fsm_state', String(st || '')); } catch (_) {}
      }
    } catch (_) {}
  };

  // ── Send button toggle ──────────────────────────────────────────────────────
  function toggleSendButton() {
    var input = document.getElementById('msg-input');
    var btn = document.getElementById('send-btn');
    if (input && btn) {
      // Always leave button clickable so Send works even if input listener misses; send() no-ops when empty
      btn.disabled = false;
      btn.classList.toggle('send-empty', !(input.value && input.value.trim()));
    }
  }
  window.toggleSendButton = toggleSendButton;

  // ── Module loaded flag ──────────────────────────────────────────────────────
  window.laylaCharRenderModuleLoaded = true;
})();
