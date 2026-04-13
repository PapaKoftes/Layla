window.__laylaHealth = window.__laylaHealth || {
  payload: null,
  lastFetch: 0,
  lastDeepFetch: 0,
  deepIntervalMs: 60000,
  inFlight: false,
  agentRequestActive: false,
  _inFlightPromise: null,
};
let currentAspect = 'morrigan';
var currentConversationId = localStorage.getItem('layla_current_conversation_id') || '';
const sessionStart = Date.now();

// Debug: localStorage.setItem('layla_debug','1') and reload; or ?layla_debug=1 in URL; or in console: window.LAYLA_DEBUG = true
var LAYLA_DEBUG = (typeof localStorage !== 'undefined' && localStorage.getItem('layla_debug') === '1') || (typeof location !== 'undefined' && location.search.indexOf('layla_debug') !== -1);
window.LAYLA_DEBUG = LAYLA_DEBUG; // allow toggling in console without reload
function _dbg() {
  if (!window.LAYLA_DEBUG && !LAYLA_DEBUG) return;
  try { console.log.apply(console, ['[Layla]'].concat(Array.prototype.slice.call(arguments))); } catch (_) {}
}
_dbg('script started');

// triggerSend and Enter listener already registered by bootstrap script above; ensure window.send wrapper can delegate to full send()
try {
function formatAgentError(res, body) {
  if (!res) return "Can't reach Layla. Is the server running at http://127.0.0.1:8000?";
  if (res.status === 500) return 'Something went wrong. Check the server logs or try again.';
  if (res.status === 503) return (body && body.detail) || 'Service temporarily unavailable.';
  const err = (body && (body.detail || body.response || body.message)) || res.statusText;
  return err && String(err).length < 200 ? String(err) : 'Request failed: ' + res.status;
}

// Per-aspect color palette — shifts the whole UI on switch
const ASPECT_COLORS = {
  morrigan: { asp: '#8b0000', glow: 'rgba(139,0,0,0.28)',   mid: 'rgba(139,0,0,0.10)' },
  nyx:      { asp: '#3a1f9a', glow: 'rgba(58,31,154,0.28)', mid: 'rgba(58,31,154,0.10)' },
  echo:     { asp: '#006878', glow: 'rgba(0,104,120,0.28)', mid: 'rgba(0,104,120,0.10)' },
  eris:     { asp: '#8a4000', glow: 'rgba(138,64,0,0.28)',  mid: 'rgba(138,64,0,0.10)' },
  cassandra: { asp: '#4a1a7a', glow: 'rgba(74,26,122,0.28)', mid: 'rgba(74,26,122,0.10)' },
  lilith:   { asp: '#6a0070', glow: 'rgba(106,0,112,0.28)', mid: 'rgba(106,0,112,0.10)' },
};

let _lastAspectSwitchTime = 0;
function setAspect(id, force) {
  if (_aspectLocked && !force) return; // locked — ignore sidebar clicks unless forced
  currentAspect = id;
  document.querySelectorAll('.aspect-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + id)?.classList.add('active');
  const badge = document.getElementById('aspect-badge');
  const ASPECT_SYMBOLS = { morrigan:'⚔', nyx:'✦', echo:'◎', eris:'⚡', cassandra:'⌖', lilith:'⊛' };
  const sym = ASPECT_SYMBOLS[id] || '∴';
  if (badge) { badge.textContent = sym + ' ' + id.toUpperCase(); badge.style.animation = 'none'; void badge.offsetWidth; badge.style.animation = ''; }
  const c = ASPECT_COLORS[id] || ASPECT_COLORS.morrigan;
  const root = document.documentElement.style;
  document.body?.setAttribute('data-aspect', id);
  root.setProperty('--asp',      c.asp);
  root.setProperty('--asp-glow', c.glow);
  root.setProperty('--asp-mid',  c.mid);
  if (Date.now() - _lastAspectSwitchTime > 300) {
    _lastAspectSwitchTime = Date.now();
    const name = (typeof ASPECTS !== 'undefined' && ASPECTS.find) ? ASPECTS.find(a => a.id === id)?.name : null;
    showToast('Now talking to ' + (name || id));
  }
  try { updateContextChip(); } catch (_) {}
  try {
    const doodles = {
      morrigan: '⚔ ◈ ⚔ ◈ ⚔\n/\\\\ /\\\\ /\\\\',
      nyx: '✦ ⊛ ∴ ✦ ⊛\n..::..::..',
      echo: '◎ ∞ ◎ ∞ ◎\n==== ====',
      eris: '⚡ ⊘ ⚡ ⊘ ⚡\n/\\/\\/\\/\\',
      cassandra: '⌖ △ ⌖ △ ⌖\n<> <> <>',
      lilith: '⊛ ♾ ✶ ⊛ ♾\n### ### ###',
    };
    const ov = document.getElementById('doodle-overlay');
    if (ov) ov.textContent = (doodles[id] || doodles.morrigan).repeat(180);
  } catch (_) {}
  try {
    if (typeof window.laylaSetAspectSprite === 'function') window.laylaSetAspectSprite(id);
  } catch (_) {}
}
window.setAspect = setAspect;

function toggleAspectDescription(id) {
  const all = document.querySelectorAll('.aspect-option.expandable');
  all.forEach(el => {
    const isTarget = el.id === ('aspect-opt-' + id);
    el.classList.toggle('expanded', isTarget ? !el.classList.contains('expanded') : false);
  });
}
window.toggleAspectDescription = toggleAspectDescription;

function expandAspectDescription(id) {
  // Expand exactly one aspect description, collapse all others (no toggle — always show)
  document.querySelectorAll('.aspect-option.expandable').forEach(el => {
    el.classList.toggle('expanded', el.id === ('aspect-opt-' + id));
  });
}

function refreshOptionDependencies() {
  const showThinking = document.getElementById('show-thinking')?.checked ?? false;
  const reasoningRow = document.getElementById('reasoning-effort-row');
  const reasoningBox = document.getElementById('reasoning-effort');
  if (reasoningRow && reasoningBox) {
    const disabled = !showThinking;
    reasoningRow.classList.toggle('disabled', disabled);
    reasoningBox.disabled = disabled;
    if (disabled) reasoningBox.checked = false;
  }

  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  const addBtn = document.getElementById('workspace-add-btn');
  const removeBtn = document.getElementById('workspace-remove-btn');
  if (addBtn) {
    addBtn.disabled = !wp;
    addBtn.style.opacity = wp ? '1' : '0.45';
    addBtn.style.pointerEvents = wp ? 'auto' : 'none';
  }
  if (removeBtn) {
    removeBtn.disabled = !wp;
    removeBtn.style.opacity = wp ? '1' : '0.45';
    removeBtn.style.pointerEvents = wp ? 'auto' : 'none';
  }
}
window.refreshOptionDependencies = refreshOptionDependencies;

function cleanLaylaText(s) {
  if (typeof s !== 'string') return (s == null || s === undefined) ? '' : String(s);
  return s.replace(/\s*\[EARNED_TITLE:\s*[^\]]+\]\s*$/gi, '').trim();
}
function sanitizeHtml(html) {
  if (typeof html !== 'string') return '';
  if (typeof DOMPurify !== 'undefined') return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['p','br','strong','em','code','pre','ul','ol','li','a','h1','h2','h3','blockquote','span','div'], ALLOWED_ATTR: ['href','class'] });
  return html.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '').replace(/on\w+\s*=\s*["'][^"']*["']/gi, '').replace(/javascript:/gi, '');
}

// Aspect → TTS voice style (rate, pitch) for browser SpeechSynthesis
const TTS_VOICE_STYLES = {
  morrigan: { rate: 0.95, pitch: 1 },
  nyx: { rate: 0.85, pitch: 0.95 },
  eris: { rate: 1.15, pitch: 1.05 },
  echo: { rate: 0.9, pitch: 1.1 },
  cassandra: { rate: 1.1, pitch: 1.05 },
  lilith: { rate: 0.9, pitch: 0.98 },
};
const UX_STATE_LABELS = {
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

function laylaNotifyStreamPhase(row, uxKey) {
  try {
    if (window.LaylaUI && typeof window.LaylaUI.syncStreamRowPhase === 'function')
      window.LaylaUI.syncStreamRowPhase(row, uxKey);
  } catch (_) {}
}

function laylaApplyUiTimeoutsFromHealth(d) {
  if (!d) return;
  try {
    const lim = d.effective_limits || {};
    const ec = d.effective_config || {};
    const streamSec = Number(lim.ui_agent_stream_timeout_seconds ?? ec.ui_agent_stream_timeout_seconds);
    const jsonSec = Number(lim.ui_agent_json_timeout_seconds ?? ec.ui_agent_json_timeout_seconds);
    const stalledOverride = Number(lim.ui_stalled_silence_ms ?? ec.ui_stalled_silence_ms);
    window.__laylaUiTimeouts = {
      streamMs: Number.isFinite(streamSec) && streamSec > 0 ? Math.round(streamSec * 1000) : 900000,
      jsonMs: Number.isFinite(jsonSec) && jsonSec > 0 ? Math.round(jsonSec * 1000) : 720000,
      stalledMs: Number.isFinite(stalledOverride) && stalledOverride > 0 ? Math.round(stalledOverride) : 0,
      maxRuntimeSeconds: Number(lim.max_runtime_seconds) > 0 ? Number(lim.max_runtime_seconds) : 900,
      performanceMode: String(lim.performance_mode || ec.performance_mode || 'auto').toLowerCase(),
    };
  } catch (_) {}
}
function laylaAgentStreamTimeoutMs() {
  const t = window.__laylaUiTimeouts;
  return t && t.streamMs > 0 ? t.streamMs : 900000;
}
function laylaAgentJsonTimeoutMs() {
  const t = window.__laylaUiTimeouts;
  return t && t.jsonMs > 0 ? t.jsonMs : 720000;
}
function laylaStalledSilenceMs() {
  const t = window.__laylaUiTimeouts || {};
  if (t.stalledMs > 0) return t.stalledMs;
  const mrs = Number(t.maxRuntimeSeconds) > 0 ? Number(t.maxRuntimeSeconds) : 900;
  const pm = t.performanceMode || 'auto';
  const mult = pm === 'low' ? 2.5 : pm === 'mid' ? 1.65 : 1;
  return Math.min(240000, Math.max(22000, Math.round(mrs * 1000 * 0.42 * mult)));
}
function laylaHeaderProgressStart() {
  const row = document.getElementById('header-progress-row');
  const fill = document.getElementById('header-progress-fill');
  if (!row || !fill) return;
  row.style.display = 'block';
  row.classList.add('active', 'indeterminate');
  fill.style.width = '42%';
}
function laylaHeaderProgressStop() {
  const row = document.getElementById('header-progress-row');
  const fill = document.getElementById('header-progress-fill');
  if (row) {
    row.classList.remove('active', 'indeterminate');
    row.style.display = 'none';
  }
  if (fill) fill.style.width = '0%';
}
function operatorTraceClear() {
  const b = document.getElementById('operator-trace-log');
  if (b) b.innerHTML = '';
}
function operatorTraceLine(kind, text) {
  const b = document.getElementById('operator-trace-log');
  if (!b) return;
  const t = new Date().toISOString().slice(11, 19);
  const line = document.createElement('div');
  line.className = 'operator-trace-line';
  line.textContent = '[' + t + '] ' + kind + ': ' + String(text || '').replace(/\s+/g, ' ').slice(0, 800);
  b.appendChild(line);
  while (b.children.length > 80) b.removeChild(b.firstChild);
  b.scrollTop = b.scrollHeight;
}
function toggleComposePanel(force) {
  const p = document.getElementById('compose-panel');
  if (!p) return;
  let on;
  if (force === true) on = true;
  else if (force === false) on = false;
  else on = !p.classList.contains('visible');
  p.classList.toggle('visible', on);
  try { localStorage.setItem('layla_compose_open', on ? '1' : '0'); } catch (_) {}
}
function laylaRunPlanFromElement(el) {
  if (!el) return;
  const ta = el.querySelector('.layla-plan-json');
  const goal = el.dataset.planGoal || '';
  if (!ta) return;
  let plan;
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
  executePlan(plan, goal);
}
function laylaFormatPlanJson(btn) {
  const el = btn && btn.closest && btn.closest('.plan-review-msg');
  const ta = el && el.querySelector('.layla-plan-json');
  if (!ta) return;
  try {
    const p = JSON.parse(ta.value);
    ta.value = JSON.stringify(p, null, 2);
    if (typeof showToast === 'function') showToast('Plan reformatted');
  } catch (e) {
    if (typeof showToast === 'function') showToast('Invalid JSON');
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 12000) {
  const tCtrl = new AbortController();
  const timer = setTimeout(() => {
    try { tCtrl.abort(); } catch (_) {}
  }, timeoutMs);
  const userSig = options && options.signal;
  const linked = new AbortController();
  function abortLinked() {
    try { linked.abort(); } catch (_) {}
  }
  tCtrl.signal.addEventListener('abort', abortLinked);
  if (userSig) {
    if (userSig.aborted) abortLinked();
    else userSig.addEventListener('abort', abortLinked);
  }
  try {
    const merged = { ...options, signal: linked.signal };
    return await fetch(url, merged);
  } finally {
    clearTimeout(timer);
    try { tCtrl.signal.removeEventListener('abort', abortLinked); } catch (_) {}
    if (userSig) try { userSig.removeEventListener('abort', abortLinked); } catch (_) {}
  }
}

function speakReply(text, aspectId) {
  if (!text || typeof speechSynthesis === 'undefined') return;
  const style = TTS_VOICE_STYLES[aspectId] || { rate: 1, pitch: 1 };
  const u = new SpeechSynthesisUtterance(text.slice(0, 4000));
  u.rate = style.rate;
  u.pitch = style.pitch;
  speechSynthesis.speak(u);
}

function hideEmpty() {
  const e = document.getElementById('chat-empty');
  if (e) e.style.display = 'none';
}

function renderPromptTilesAndEmptyState() {
  return `<div class="sigil">∴</div><div class="hint">she is waiting</div>
      <div class="prompt-tiles" id="prompt-tiles">
        <button class="prompt-tile" onclick="fillPrompt('Explain how ')"><span class="tile-icon">✦</span><span class="tile-text">Explain something</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Write Python code to ')"><span class="tile-icon">⚔</span><span class="tile-text">Write code for me</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Research and summarize: ')"><span class="tile-icon">🔬</span><span class="tile-text">Research a topic</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Help me debug this error: ')"><span class="tile-icon">🔧</span><span class="tile-text">Debug an error</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Summarize this text: ')"><span class="tile-icon">◎</span><span class="tile-text">Summarize text</span></button>
        <button class="prompt-tile" onclick="fillPrompt('What should I do about ')"><span class="tile-icon">⌖</span><span class="tile-text">Get advice</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Refactor this code: ')"><span class="tile-icon">⚔</span><span class="tile-text">Refactor</span></button>
        <button class="prompt-tile" onclick="fillPrompt('Add tests for ')"><span class="tile-icon">🧪</span><span class="tile-text">Add tests</span></button>
      </div>
      <div class="try-this-chips" style="margin-top:16px;display:flex;flex-wrap:wrap;gap:8px;justify-content:center">
        <button class="try-this-chip" onclick="fillPrompt('Explain quantum entanglement')" style="padding:6px 12px;font-size:0.75rem;background:var(--asp-mid);border:1px solid var(--asp);color:var(--text);border-radius:4px;cursor:pointer">Explain quantum entanglement</button>
        <button class="try-this-chip" onclick="fillPrompt('Write a Python hello world')" style="padding:6px 12px;font-size:0.75rem;background:var(--asp-mid);border:1px solid var(--asp);color:var(--text);border-radius:4px;cursor:pointer">Write a Python hello world</button>
      </div>`;
}

function _renderReasoningTreeSummary(container, summary) {
  if (!summary || !Array.isArray(summary.nodes) || summary.nodes.length === 0) return;
  const wrap = document.createElement('details');
  wrap.className = 'tool-trace';
  const mode = summary.reasoning_mode ? (' • ' + summary.reasoning_mode) : '';
  wrap.innerHTML = '<summary>Reasoning summary (' + summary.nodes.length + mode + ')</summary>';
  const body = document.createElement('div');
  body.className = 'tool-trace-content';
  const lines = [];
  if (summary.goal) lines.push('Goal: ' + summary.goal);
  summary.nodes.forEach((n, i) => {
    lines.push((i + 1) + '. [' + (n.phase || 'step') + '] ' + (n.action || 'reason') + ' -> ' + (n.outcome_summary || 'ok'));
  });
  if (summary.final_summary) lines.push('Final: ' + summary.final_summary);
  body.textContent = lines.join('\n');
  wrap.appendChild(body);
  container.appendChild(wrap);
}

async function rememberLaylaBubble(bubble, btn) {
  const txt = (bubble && (bubble.innerText || bubble.textContent) || '').trim();
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
    const res = await fetch('/learn/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: txt, type: 'fact', tags: 'ui:remember' }),
    });
    const d = await res.json();
    if (d.ok) {
      showToast('Saved to learnings');
      if (btn) {
        btn.textContent = 'saved';
        setTimeout(function() { btn.textContent = 'remember'; btn.disabled = false; }, 2000);
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

function addMsg(role, text, aspectName, deliberated, steps, uxStates, memoryInfluenced, reasoningTreeSummary) {
  hideEmpty();
  const chat = document.getElementById('chat');
  if (!chat) return;
  const div = document.createElement('div');
  div.className = 'msg msg-' + (role === 'you' ? 'you' : 'layla');
  const label = document.createElement('div');
  label.className = 'msg-label' + (role === 'layla' ? ' msg-label-layla' : '');
  if (role === 'you') {
    const nameSpan = document.createElement('span');
    nameSpan.textContent = 'You';
    label.appendChild(nameSpan);
  } else {
    const brand = document.createElement('span');
    brand.className = 'msg-brand';
    brand.textContent = 'Layla';
    label.appendChild(brand);
    const facet = facetMetaFromNameOrId(aspectName || currentAspect);
    if (facet) {
      const chip = document.createElement('span');
      chip.className = 'msg-facet-chip';
      chip.textContent = facet.sym + ' ' + facet.name;
      chip.title = 'Facet (voice)';
      label.appendChild(chip);
    } else if (aspectName) {
      const chip = document.createElement('span');
      chip.className = 'msg-facet-chip msg-facet-unknown';
      chip.textContent = String(aspectName);
      label.appendChild(chip);
    } else {
      const chip = document.createElement('span');
      chip.className = 'msg-facet-chip msg-facet-unknown';
      chip.textContent = '◇ facet';
      chip.title = 'Session aspect: ' + (currentAspect || 'morrigan');
      label.appendChild(chip);
    }
  }
  const ts = document.createElement('span');
  ts.className = 'msg-ts';
  const now = new Date();
  ts.textContent = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
  label.appendChild(ts);
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.title = 'Click to copy';
  if (role === 'layla') {
    text = cleanLaylaText(text || '');
    if (typeof marked !== 'undefined') {
      const md = document.createElement('div');
      md.className = 'md-content';
      let parsed = '';
      try { parsed = marked.parse(text || ''); } catch (_) { parsed = (text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
      md.innerHTML = sanitizeHtml(parsed);
      // Syntax highlight + copy buttons on code blocks
      md.querySelectorAll('pre').forEach((pre) => {
        const code = pre.querySelector('code');
        if (code && window.hljs) hljs.highlightElement(code);
        const wrap = document.createElement('div');
        wrap.className = 'code-wrap';
        pre.parentNode.insertBefore(wrap, pre);
        wrap.appendChild(pre);
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.textContent = 'copy';
        copyBtn.onclick = () => {
          navigator.clipboard?.writeText(code ? code.innerText : pre.innerText).then(() => {
            copyBtn.textContent = 'copied';
            copyBtn.classList.add('copied');
            setTimeout(() => { copyBtn.textContent = 'copy'; copyBtn.classList.remove('copied'); }, 1800);
          });
        };
        wrap.appendChild(copyBtn);
        // Apply-to-file button (if filename detectable)
        if (code) _addApplyBtnToCodeBlock(wrap, code);
      });
      bubble.appendChild(md);
    } else {
      bubble.textContent = text;
    }
    // TTS is handled by send() and other entry points via tts-toggle checkbox
  } else {
    bubble.textContent = text;
  }
  if (role === 'layla') {
    const copyBtn = document.createElement('button');
    copyBtn.className = 'msg-copy-btn';
    copyBtn.textContent = 'copy';
    copyBtn.title = 'Copy response'; copyBtn.setAttribute('aria-label', 'Copy response');
    copyBtn.onclick = (ev) => {
      ev.stopPropagation();
      const txt = (bubble.innerText || bubble.textContent || '').trim();
      if (txt) navigator.clipboard?.writeText(txt).then(() => { copyBtn.textContent = 'copied'; copyBtn.classList.add('copied'); setTimeout(() => { copyBtn.textContent = 'copy'; copyBtn.classList.remove('copied'); }, 1500); }).catch(() => {});
    };
    label.appendChild(copyBtn);
    const rememberBtn = document.createElement('button');
    rememberBtn.className = 'msg-remember-btn';
    rememberBtn.type = 'button';
    rememberBtn.textContent = 'remember';
    rememberBtn.title = 'Save this reply as a learning';
    rememberBtn.setAttribute('aria-label', 'Remember this message');
    rememberBtn.onclick = (ev) => {
      ev.stopPropagation();
      rememberLaylaBubble(bubble, rememberBtn);
    };
    label.appendChild(rememberBtn);
  }
  div.appendChild(label);
  div.appendChild(bubble);
  if (Array.isArray(uxStates) && uxStates.length > 0) {
    const badges = document.createElement('div');
    badges.className = 'ux-state-badges';
    uxStates.forEach(s => {
      const b = document.createElement('span');
      b.className = 'ux-state-badge';
      b.textContent = UX_STATE_LABELS[s] || s;
      badges.appendChild(b);
    });
    div.appendChild(badges);
  }
  if (Array.isArray(memoryInfluenced) && memoryInfluenced.length > 0) {
    const mem = document.createElement('div');
    mem.className = 'memory-attribution';
    mem.textContent = 'Used memory: ' + (memoryInfluenced.includes('learnings') && memoryInfluenced.includes('semantic_recall') ? 'learnings & recall' : memoryInfluenced.includes('learnings') ? 'learnings' : 'recall');
    div.appendChild(mem);
  }
  if (steps && steps.length > 0) {
    const trace = document.createElement('details');
    trace.className = 'tool-trace';
    trace.innerHTML = '<summary>What she did (' + steps.length + ')</summary>';
    const pre = document.createElement('div');
    pre.className = 'tool-trace-content';
    pre.textContent = steps.map(s => { try { return s.action + ': ' + JSON.stringify(s.result).slice(0, 200); } catch (_) { return s.action + ': [unserializable]'; } }).join('\n');
    trace.appendChild(pre);
    div.appendChild(trace);
  }
  if (deliberated) {
    const d = document.createElement('details');
    d.className = 'tool-trace';
    d.style.borderLeft = '2px solid var(--violet,#8844cc)';
    d.innerHTML = '<summary style="color:var(--violet,#8844cc);font-size:0.68rem">✦ She deliberated</summary><div class="think-bubble">She weighed this with her inner voices before answering.</div>';
    div.appendChild(d);
  }
  _renderReasoningTreeSummary(div, reasoningTreeSummary);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function addSeparator() {
  const chat = document.getElementById('chat');
  if (!chat) return;
  const sep = document.createElement('div');
  sep.className = 'separator';
  sep.textContent = '✦';
  chat.appendChild(sep);
}

function getMissionDepth() {
  const r = document.querySelector('input[name="mission-depth"]:checked');
  return (r && r.value) ? r.value : 'deep';
}

const _LEGACY_PANEL_TO_RTA = {
  approvals: ['safety'],
  health: ['status'],
  models: ['workspace', 'models'],
  knowledge: ['workspace', 'knowledge'],
  codex: ['workspace', 'codex'],
  plugins: ['workspace', 'plugins'],
  projects: ['workspace', 'projects'],
  timeline: ['workspace', 'timeline'],
  study: ['workspace', 'study'],
  memory: ['workspace', 'memory'],
  skills: ['workspace', 'skills'],
  research: ['research'],
  help: ['help'],
};

/* Panel DOM is handled in bootstrap (window.showMainPanel). Main script only registers data refresh hooks. */
window.__laylaRefreshAfterShowMainPanel = function (main) {
  if (main === 'status') {
    refreshPlatformHealth();
    refreshVersionInfo();
    refreshRuntimeOptions();
  }
  if (main === 'prefs') {
    if (typeof refreshContentPolicyToggles === 'function') refreshContentPolicyToggles();
    try { loadProjectsIntoSelect(); } catch (_) {}
  }
  if (main === 'agents') {
    if (typeof refreshAgentsPanel === 'function') refreshAgentsPanel();
  }
  if (main === 'workspace') {
    /* Subtab refresh only ran on subtab click; opening Workspace left default "Models" stuck on "Loading…" */
    var wsRoot = document.querySelector('#layla-right-panel .rcp-page[data-rcp="workspace"]');
    var subEl = wsRoot && wsRoot.querySelector('.rcp-subtab.active');
    var sub = (subEl && subEl.getAttribute('data-rcp-sub')) || 'models';
    if (typeof window.__laylaRefreshAfterWorkspaceSubtab === 'function') {
      window.__laylaRefreshAfterWorkspaceSubtab(sub);
    }
  }
  if (main === 'safety') {
    refreshApprovals();
  }
  if (main === 'research') {
    refreshMissionStatus().then(function () {
      const t = document.querySelector('#research-mission-panel .tab-btn.active');
      if (t) showResearchTab(t.getAttribute('data-tab'));
    });
  }
};
window.__laylaRefreshAfterWorkspaceSubtab = function (sub) {
  const refreshers = {
    models: refreshPlatformModels,
    knowledge: refreshPlatformKnowledge,
    plugins: refreshPlatformPlugins,
    projects: refreshPlatformProjects,
    timeline: refreshPlatformTimeline,
    study: function () { refreshStudyPlans(); loadStudyPresetsAndSuggestions(); },
    memory: function () {
      if (typeof refreshFileCheckpointsPanel === 'function') refreshFileCheckpointsPanel();
    },
    codex: function () {
      if (typeof refreshRelationshipCodex === 'function') refreshRelationshipCodex();
    },
    skills: refreshSkillsList,
    plans: refreshLaylaPlansPanel,
  };
  const fn = refreshers[sub];
  if (typeof fn === 'function') fn();
};

/** Back-compat for shortcuts and old links: maps old tab id → new UI. */
function showPanelTab(tab) {
  const m = _LEGACY_PANEL_TO_RTA[tab];
  if (m) {
    if (m[1]) window.showWorkspaceSubtab(m[1]);
    else window.showMainPanel(m[0]);
    return;
  }
  window.showMainPanel('help');
}
window.showPanelTab = showPanelTab;

function focusResearchPanel() {
  window.showMainPanel('research');
  const panel = document.getElementById('research-mission-panel');
  if (panel) {
    panel.scrollIntoView({ behavior: 'smooth' });
    refreshMissionStatus().then(function() { showResearchTab('summary'); });
  }
}

function toggleSendButton() {
  const input = document.getElementById('msg-input');
  const btn = document.getElementById('send-btn');
  if (input && btn) {
    // Always leave button clickable so Send works even if input listener misses; send() no-ops when empty
    btn.disabled = false;
    btn.classList.toggle('send-empty', !(input.value && input.value.trim()));
  }
}

// ── Aspect registry for @mention ────────────────────────────────────────────
const ASPECTS = [
  { id: 'morrigan', sym: '⚔', name: 'Morrigan', desc: 'Code, debug, architecture — the blade' },
  { id: 'nyx',      sym: '✦', name: 'Nyx',      desc: 'Research, depth, synthesis' },
  { id: 'echo',     sym: '◎', name: 'Echo',     desc: 'Reflection, patterns, memory' },
  { id: 'eris',     sym: '⚡', name: 'Eris',     desc: 'Creative chaos, banter, lateral leaps' },
  { id: 'cassandra',sym: '⌖', name: 'Cassandra',desc: 'Unfiltered oracle — sees it first' },
  { id: 'lilith',   sym: '⊛', name: 'Lilith',   desc: 'Sovereign will, ethics, full honesty' },
];

function facetMetaFromNameOrId(aspectNameOrId) {
  if (!aspectNameOrId) return null;
  const s = String(aspectNameOrId).trim().toLowerCase();
  return ASPECTS.find(a => a.id === s || a.name.toLowerCase() === s) || null;
}

/** Label row HTML: Layla + facet chip (for typing / stream bootstrap). */
function formatLaylaLabelHtml(aspectId) {
  const aid = String(aspectId || 'morrigan').toLowerCase();
  const a = ASPECTS.find(x => x.id === aid) || ASPECTS[0];
  const sym = String(a.sym || '').replace(/</g, '&lt;');
  const name = String(a.name || '').replace(/</g, '&lt;');
  return '<span class="msg-brand">Layla</span><span class="msg-facet-chip" title="Facet (voice)">' + sym + ' ' + name + '</span>';
}

// ── Shared “Layla is working” row: one implementation for send(), sendResearch(), etc. ──
let _laylaTypingMetaTimer = null;
let _laylaTypingStartedAt = 0;
let _laylaTypingPhaseTimers = [];

function laylaClearTypingPhases() {
  _laylaTypingPhaseTimers.forEach((tid) => { try { clearTimeout(tid); } catch (_) {} });
  _laylaTypingPhaseTimers = [];
}

/** Client-side phases when the server sends no ux_state (non-stream JSON wait). */
function laylaStartNonStreamTypingPhases() {
  laylaClearTypingPhases();
  [
    { delay: 1200, key: 'thinking' },
    { delay: 8000, key: 'still_working' },
    { delay: 25000, key: 'preparing_reply' },
  ].forEach(({ delay, key }) => {
    _laylaTypingPhaseTimers.push(setTimeout(() => {
      if (document.getElementById('typing-wrap')) laylaUpdateTypingUx(key);
    }, delay));
  });
}

function laylaUpdateTypingUx(uxKey) {
  const wrap = document.getElementById('typing-wrap');
  if (!wrap) return;
  const labelText = UX_STATE_LABELS[uxKey] || uxKey;
  let statusEl = wrap.querySelector('.tool-status-label');
  if (!statusEl) {
    statusEl = document.createElement('div');
    statusEl.className = 'tool-status-label';
    wrap.querySelector('.msg-bubble')?.appendChild(statusEl);
  }
  statusEl.textContent = labelText;
  let metaEl = wrap.querySelector('.memory-attribution');
  if (!metaEl) {
    metaEl = document.createElement('div');
    metaEl.className = 'memory-attribution';
    wrap.querySelector('.msg-bubble')?.appendChild(metaEl);
  }
  if (!_laylaTypingStartedAt) _laylaTypingStartedAt = Date.now();
  const secs = Math.max(0, Math.floor((Date.now() - _laylaTypingStartedAt) / 1000));
  metaEl.textContent = 'Status: ' + labelText + ' | elapsed: ' + secs + 's';
  try {
    if (window.LaylaUI && typeof window.LaylaUI.applyToTypingWrap === 'function')
      window.LaylaUI.applyToTypingWrap(wrap, uxKey);
  } catch (_) {}
}

function laylaRemoveTypingIndicator() {
  const w = document.getElementById('typing-wrap');
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

function laylaShowTypingIndicator(aspectId, initialUxKey) {
  hideEmpty();
  const chatEl = document.getElementById('chat');
  if (!chatEl) return;
  const key = initialUxKey || 'connecting';
  const existing = document.getElementById('typing-wrap');
  if (existing) {
    laylaUpdateTypingUx(key);
    return;
  }
  const w = document.createElement('div');
  w.className = 'msg msg-layla';
  w.id = 'typing-wrap';
  _laylaTypingStartedAt = Date.now();
  const labelText = UX_STATE_LABELS[key] || key;
  w.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(aspectId) + '</div><div class="msg-bubble typing-indicator"><div class="typing-dots"><span></span><span></span><span></span></div><div class="tool-status-label">' + labelText + '</div><div class="memory-attribution">Status: ' + labelText + ' | elapsed: 0s</div></div>';
  chatEl.appendChild(w);
  if (_laylaTypingMetaTimer) clearInterval(_laylaTypingMetaTimer);
  _laylaTypingMetaTimer = setInterval(() => {
    const active = document.getElementById('typing-wrap');
    if (!active) return;
    const metaEl = active.querySelector('.memory-attribution');
    const status = (active.querySelector('.tool-status-label') && active.querySelector('.tool-status-label').textContent) || 'Thinking';
    if (metaEl) {
      const secs = Math.max(0, Math.floor((Date.now() - _laylaTypingStartedAt) / 1000));
      metaEl.textContent = 'Status: ' + status + ' | elapsed: ' + secs + 's';
    }
  }, 500);
  try {
    if (window.LaylaUI && typeof window.LaylaUI.applyToTypingWrap === 'function')
      window.LaylaUI.applyToTypingWrap(w, key);
  } catch (_) {}
  chatEl.scrollTop = chatEl.scrollHeight;
}

let _mentionActive = false;   // dropdown is open
window._mentionActive = false; // for listeners that run in finally (may run before this line)
let _mentionIdx = 0;          // selected item index
let _mentionAspectOverride = null; // one-shot aspect for next send
let _aspectLocked = false;    // lock prevents auto-route

// ── Aspect lock ──────────────────────────────────────────────────────────────
function toggleAspectLock() {
  _aspectLocked = !_aspectLocked;
  const btn = document.getElementById('aspect-lock-btn');
  if (btn) {
    btn.textContent = _aspectLocked ? '🔒' : '🔓';
    btn.classList.toggle('locked', _aspectLocked);
    btn.title = _aspectLocked
      ? `Locked to ${currentAspect.toUpperCase()} — click to unlock`
      : 'Lock this aspect (prevent auto-routing)';
  }
}

// ── Mention dropdown ─────────────────────────────────────────────────────────
function _getMentionQuery(val) {
  // Returns the @word being typed if cursor is in it, else null
  const m = val.match(/(?:^|\s)@(\w*)$/);
  return m ? m[1].toLowerCase() : null;
}

function _showMentionDropdown(query) {
  const dd = document.getElementById('mention-dropdown');
  if (!dd) return;
  const filtered = query === ''
    ? ASPECTS
    : ASPECTS.filter(a => a.id.startsWith(query) || a.name.toLowerCase().startsWith(query));
  if (!filtered.length) { _hideMentionDropdown(); return; }
  _mentionActive = true;
  window._mentionActive = true;
  _mentionIdx = 0;
  dd.innerHTML = filtered.map((a, i) =>
    `<div class="mention-item${i === 0 ? ' active' : ''}" data-id="${a.id}" onmousedown="event.preventDefault();_pickMention('${a.id}')">
      <span class="mention-sym">${a.sym}</span>
      <span class="mention-name">${a.name}</span>
      <span class="mention-desc">${a.desc}</span>
    </div>`
  ).join('');
  dd.classList.add('open');
  dd._filtered = filtered;
}

function _hideMentionDropdown() {
  const dd = document.getElementById('mention-dropdown');
  if (dd) { dd.classList.remove('open'); dd.innerHTML = ''; }
  _mentionActive = false;
  window._mentionActive = false;
  _mentionIdx = 0;
}

function _moveMentionDropdown(dir) {
  const dd = document.getElementById('mention-dropdown');
  if (!dd || !_mentionActive) return;
  const items = dd.querySelectorAll('.mention-item');
  if (!items.length) return;
  items[_mentionIdx]?.classList.remove('active');
  _mentionIdx = (_mentionIdx + dir + items.length) % items.length;
  items[_mentionIdx]?.classList.add('active');
  items[_mentionIdx]?.scrollIntoView({ block: 'nearest' });
}

function _pickMention(aspectId) {
  const input = document.getElementById('msg-input');
  if (!input) return;
  // Replace the trailing @word with @aspectId + space
  input.value = input.value.replace(/(?:^|\s)@\w*$/, m => {
    const prefix = m.startsWith('@') ? '' : m[0];
    return prefix + '@' + aspectId + ' ';
  });
  _hideMentionDropdown();
  input.focus();
  toggleSendButton();
}

function onInputChange(e) {
  toggleSendButton();
  const val = e.target.value;
  _checkUrlInInput(val);
  const query = _getMentionQuery(val);
  if (query !== null) {
    _showMentionDropdown(query);
  } else {
    _hideMentionDropdown();
  }
}

function _isEnterKey(e) {
  return e.key === 'Enter' || e.keyCode === 13;
}

function onInputKeydown(e) {
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'k') { e.preventDefault(); const inp = document.getElementById('msg-input'); if (inp) { inp.value = ''; toggleSendButton(); } return; }
    if (e.key === 'r') { e.preventDefault(); retryLastMessage(); return; }
    if (e.key === '/') { e.preventDefault(); showPanelTab('help'); return; }
    if (e.key === 'f') { e.preventDefault(); openChatSearch(); return; }
  }
  if (!_mentionActive && e.key === 'ArrowUp' && !e.shiftKey) {
    const inp = document.getElementById('msg-input');
    if (inp && (inp.selectionStart || 0) === 0) {
      e.preventDefault();
      _ensurePromptHistory().then(() => {
        if (!_promptHistoryList || !_promptHistoryList.length) return;
        _promptHistoryIdx = _promptHistoryIdx < 0 ? 0 : Math.min(_promptHistoryList.length - 1, _promptHistoryIdx + 1);
        inp.value = _promptHistoryList[_promptHistoryIdx] || '';
        toggleSendButton();
      });
      return;
    }
  }
  if (!_mentionActive && e.key === 'ArrowDown' && !e.shiftKey) {
    const inp = document.getElementById('msg-input');
    if (inp && _promptHistoryIdx >= 0 && (inp.selectionStart || 0) === (inp.value || '').length) {
      e.preventDefault();
      _promptHistoryIdx--;
      if (_promptHistoryIdx < 0) {
        inp.value = '';
        _promptHistoryIdx = -1;
        toggleSendButton();
        return;
      }
      inp.value = _promptHistoryList[_promptHistoryIdx] || '';
      toggleSendButton();
      return;
    }
  }
  if (_mentionActive) {
    if (e.key === 'ArrowDown') { e.preventDefault(); _moveMentionDropdown(1); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); _moveMentionDropdown(-1); return; }
    if (e.key === 'Tab' || _isEnterKey(e)) {
      const dd = document.getElementById('mention-dropdown');
      if (dd && _mentionActive) {
        e.preventDefault();
        const items = dd.querySelectorAll('.mention-item');
        const id = items[_mentionIdx]?.dataset?.id;
        if (id) _pickMention(id);
        return;
      }
    }
    if (e.key === 'Escape') { _hideMentionDropdown(); return; }
  }
  // Enter-to-send is handled solely by document keydown (bootstrap); do not duplicate here.
}

// ── Voice I/O ──────────────────────────────────────────────────────────────
let _micActive = false;
let _mediaRecorder = null;
let _audioChunks = [];
let _ttsEnabled = localStorage.getItem('layla_tts') !== 'false';
/** Default on: live progress + keepalive-friendly stall timer for long turns. */
let _streamEnabled = localStorage.getItem('layla_stream') !== 'false';
// Sync checkbox to persisted value on load
document.addEventListener('DOMContentLoaded', () => {
  const streamCb = document.getElementById('stream-toggle');
  if (streamCb) {
    streamCb.checked = _streamEnabled;
    streamCb.addEventListener('change', function () {
      _streamEnabled = !!this.checked;
      localStorage.setItem('layla_stream', _streamEnabled ? 'true' : 'false');
    });
  }
  const ttsCb = document.getElementById('tts-toggle');
  if (ttsCb) ttsCb.checked = _ttsEnabled;
  try {
    const asp = typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan';
    if (typeof window.laylaSetAspectSprite === 'function') window.laylaSetAspectSprite(asp);
  } catch (_) {}
});

async function toggleMic() {
  if (_micActive) {
    stopMic();
  } else {
    await startMic();
  }
}

async function startMic() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _audioChunks.push(e.data); };
    _mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(_audioChunks, { type: 'audio/webm' });
      await transcribeAndSend(blob);
    };
    _mediaRecorder.start();
    _micActive = true;
    const micBtn = document.getElementById('mic-btn');
    if (micBtn) {
      micBtn.textContent = '⏹';
      micBtn.classList.add('recording');
      micBtn.title = 'Click to stop recording';
    }
  } catch(e) {
    console.error('Mic access denied:', e);
    showToast('Microphone access denied');
  }
}

function stopMic() {
  if (_mediaRecorder && _micActive) {
    _mediaRecorder.stop();
    _micActive = false;
    const micBtn = document.getElementById('mic-btn');
    if (micBtn) {
      micBtn.textContent = '🎤';
      micBtn.classList.remove('recording');
      micBtn.title = 'Click to record voice';
    }
  }
}

async function transcribeAndSend(blob) {
  const micBtn = document.getElementById('mic-btn');
  if (micBtn) { micBtn.textContent = '⌛'; micBtn.classList.remove('recording'); }
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const resp = await fetch('/voice/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'audio/webm' },
      body: arrayBuffer,
    });
    const data = await resp.json();
    if (data.ok && data.text && data.text.trim()) {
      const input = document.getElementById('msg-input');
      if (input) {
        input.value = data.text.trim();
        toggleSendButton();
        // Auto-send after transcription
        send();
      }
    } else {
      showToast('Could not transcribe audio');
    }
  } catch(e) {
    console.error('Transcription error:', e);
    showToast('Transcription failed');
  } finally {
    if (micBtn) { micBtn.textContent = '🎤'; micBtn.style.color = 'var(--text-dim)'; }
  }
}

async function speakText(text) {
  if (!_ttsEnabled || !text) return;
  // Try server-side TTS (kokoro-onnx) first; fall back to browser SpeechSynthesis
  try {
    const resp = await fetch('/voice/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (resp.ok) {
      const arrayBuffer = await resp.arrayBuffer();
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      const source = audioCtx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioCtx.destination);
      source.start();
      return;
    }
    // 503 = kokoro-onnx not installed; fall through to browser fallback
  } catch(e) { /* network error; fall through */ }
  // Browser SpeechSynthesis fallback (always available, lower quality)
  if (typeof speechSynthesis !== 'undefined') {
    try { speakReply(text.slice(0, 500), currentAspect); } catch (_) {}
  }
}

function showToast(msg, opts) {
  const t = document.createElement('div');
  t.className = 'toast';
  if (opts && opts.html) { t.innerHTML = msg; } else { t.textContent = msg; }
  document.body.appendChild(t);
  const duration = (opts && opts.duration) || 2200;
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; setTimeout(() => t.remove(), 300); }, duration);
}

async function startResearchMission(isResume) {
  const workspacePath = (document.getElementById('workspace-path')?.value || '').trim();
  const missionDepth = getMissionDepth();
  const nextStage = document.getElementById('next-stage')?.checked || false;
  addMsg('you', (isResume ? '&#9208; Resume' : '&#9654; Start') + ' research mission: depth=' + missionDepth + (nextStage ? ', next_stage' : '') + (workspacePath ? ' · ' + workspacePath : ''));
  addSeparator();
  const chatEl = document.getElementById('chat');
  const wrap = document.createElement('div');
  wrap.className = 'msg msg-layla';
  wrap.id = 'typing-wrap';
  wrap.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan') + '</div><div class="msg-bubble typing-indicator"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
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
      try {
        const errBody = await res.json();
        if (errBody && (errBody.error || errBody.response || errBody.detail)) errMsg = errBody.response || errBody.error || (typeof errBody.detail === 'string' ? errBody.detail : errMsg);
      } catch (_) {}
      addMsg('layla', errMsg);
      await refreshMissionStatus();
      refreshApprovals();
      return;
    }
    const data = await res.json().catch(() => ({}));
    const resp = (data && data.response) || '(no output)';
    addMsg('layla', resp, data?.state?.aspect_name, data?.state?.steps?.some(s => s.deliberated), data?.state?.steps, data?.state?.ux_states, data?.state?.memory_influenced);
    if (data && data.mission_depth) addMsg('layla', 'Mission depth: ' + data.mission_depth + (data.stages_run?.length ? ', stages run: ' + data.stages_run.join(', ') : ''));
    if (_ttsEnabled && resp && resp !== '(no output)') { speakText(resp).catch(() => {}); }
    await refreshMissionStatus();
    const activeTab = document.querySelector('#research-mission-panel .tab-btn.active')?.getAttribute('data-tab') || 'summary';
    await showResearchTab(activeTab);
  } catch (e) {
    wrap.remove();
    addMsg('layla', 'Error: ' + e.message);
    await refreshMissionStatus();
  }
  refreshApprovals();
}

async function refreshMissionStatus() {
  const lineEl = document.getElementById('mission-status-line');
  const detailEl = document.getElementById('mission-status-detail');
  const liveEl = document.getElementById('mission-status-live');
  const warnEl = document.getElementById('mission-status-warning');
  const resumableEl = document.getElementById('mission-status-resumable');
  if (!lineEl) return;
  try {
    const res = await fetchWithTimeout('/research_mission/state', {}, 12000);
    let data = {};
    if (res.ok) try { data = await res.json(); } catch (_) {}
    const status = data.status ?? (Array.isArray(data.completed) && data.completed.length ? 'partial' : null);
    const completed = Array.isArray(data.completed) ? data.completed : [];
    const stage = data.stage ?? null;
    const lastRun = data.last_run ?? null;
    lineEl.textContent = 'Status: ' + (status || '—');
    const completedStr = completed.length ? '✔ ' + completed.join(', ') : '';
    if (detailEl) detailEl.innerHTML = (lastRun ? 'Last run: ' + escapeHtml(String(lastRun)) + '<br>' : '') + (stage ? '⏳ Current: ' + escapeHtml(String(stage)) + '<br>' : '') + (completedStr ? escapeHtml(completedStr) : '');
    if (liveEl) {
      const now = new Date();
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
function escapeHtml(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

const RESEARCH_BRAIN_PATHS = { summary: 'summaries/24h_summary.md', actions: 'actions/action_queue.md', patterns: 'patterns/patterns.md', risks: 'risk/risk_model.md' };

async function showResearchTab(tab) {
  const panel = document.getElementById('research-mission-panel');
  if (panel) {
    panel.querySelectorAll('.tab-btn').forEach(b => { b.classList.remove('active'); });
    const btn = panel.querySelector('.tab-btn[data-tab="' + tab + '"]');
    if (btn) btn.classList.add('active');
  }
  const contentEl = document.getElementById('research-tab-content');
  if (!contentEl) return;
  if (tab === 'last') {
    try {
      const res = await fetchWithTimeout('/research_output/last', {}, 12000);
      const data = await res.ok ? res.json() : {};
      contentEl.textContent = data.content || '(no output yet)';
    } catch (_) { contentEl.textContent = '(failed to load)'; }
    return;
  }
  const path = RESEARCH_BRAIN_PATHS[tab];
  if (!path) { contentEl.textContent = ''; return; }
  try {
    const res = await fetchWithTimeout('/research_brain/file?path=' + encodeURIComponent(path), {}, 12000);
    const data = await res.ok ? res.json() : {};
    contentEl.textContent = data.content || '(no content yet)';
  } catch (_) { contentEl.textContent = '(failed to load)'; }
}

setInterval(refreshMissionStatus, 5000);
document.addEventListener('DOMContentLoaded', function() {
  refreshMissionStatus();
  showResearchTab('summary');
  toggleSendButton();
});

async function sendResearch(customMessage) {
  const workspacePath = (document.getElementById('workspace-path')?.value || '').trim();
  const researchMsg = (typeof customMessage === 'string' && customMessage.trim()) ? customMessage.trim() : 'Research this repo and tell me if the implementation is optimal. Do not modify anything.';
  addMsg('you', '🔬 ' + (researchMsg.length > 120 ? researchMsg.slice(0, 120) + '…' : researchMsg) + (workspacePath ? ' (Repo: ' + workspacePath + ')' : ''));
  addSeparator();
  try {
    const rmBadge = document.getElementById('reasoning-mode-badge');
    if (rmBadge) rmBadge.textContent = '';
  } catch (_) {}

  const streamMode = document.getElementById('stream-toggle')?.checked || false;
  const payload = {
    message: researchMsg,
    repo_path: workspacePath || undefined,
    aspect_id: currentAspect,
    show_thinking: document.getElementById('show-thinking')?.checked ?? false,
    stream: streamMode,
  };

  const chatEl = document.getElementById('chat');
  const ra = typeof currentAspect !== 'undefined' ? currentAspect : 'morrigan';

  try {
    if (streamMode) {
      const res = await fetchWithTimeout('/research', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, Math.max(laylaAgentStreamTimeoutMs(), 720000));
      if (!res.ok || !res.body) {
        let body = {};
        try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) {} } catch(_) {}
        addMsg('layla', formatAgentError(res, body));
        refreshApprovals();
        return;
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = '';
      hideEmpty();
      const div = document.createElement('div');
      div.className = 'msg msg-layla';
      div.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(ra) + '</div><div class="msg-bubble" title="Click to copy"><div class="md-content stream-md-placeholder"><div class="typing-indicator" style="min-height:36px"><div class="typing-dots"><span></span><span></span><span></span></div></div><div class="tool-status-label">' + (UX_STATE_LABELS.connecting || 'Connecting') + '</div></div></div>';
      chatEl.appendChild(div);
      const bubble = div.querySelector('.md-content');
      const streamMeta = document.createElement('div');
      streamMeta.className = 'memory-attribution';
      streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS.connecting || 'Connecting') + ' · 0s · 0 chars';
      div.appendChild(streamMeta);
      const streamStartedAt = Date.now();
      let liveStatus = 'connecting';
      laylaNotifyStreamPhase(div, 'connecting');
      const metaTimer = setInterval(() => {
        const secs = Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000));
        streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS[liveStatus] || liveStatus) + ' · ' + secs + 's · ' + (full || '').length + ' chars';
      }, 500);
      let researchStreamGotToken = false;
      let firstTokenTimer = setTimeout(() => {
        liveStatus = 'waiting_first_token';
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
        statusEl.textContent = UX_STATE_LABELS.waiting_first_token;
        laylaNotifyStreamPhase(div, liveStatus);
      }, 1200);
      const researchStallMs = laylaStalledSilenceMs();
      let stalledTimer = setTimeout(() => {
        liveStatus = 'stalled';
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
        statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
        laylaNotifyStreamPhase(div, 'stalled');
      }, researchStallMs);
      let gotDone = false;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = dec.decode(value, { stream: true });
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const obj = JSON.parse(line.slice(6));
              if (obj.pulse === true) {
                clearTimeout(stalledTimer);
                stalledTimer = setTimeout(() => {
                  liveStatus = 'stalled';
                  let statusEl = div.querySelector('.tool-status-label');
                  if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
                  statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
                  laylaNotifyStreamPhase(div, 'stalled');
                }, researchStallMs);
              }
              if (obj.error) {
                clearTimeout(firstTokenTimer);
                clearTimeout(stalledTimer);
                clearInterval(metaTimer);
                try { div.remove(); } catch (_) {}
                addMsg('layla', 'Research stream error: ' + String(obj.error));
                refreshApprovals();
                return;
              }
              if (obj.token) {
                liveStatus = 'streaming';
                laylaNotifyStreamPhase(div, 'streaming');
                if (!researchStreamGotToken) {
                  researchStreamGotToken = true;
                  clearTimeout(firstTokenTimer);
                  if (bubble && bubble.classList.contains('stream-md-placeholder')) {
                    bubble.classList.remove('stream-md-placeholder');
                    bubble.innerHTML = '';
                  }
                }
                clearTimeout(stalledTimer);
                stalledTimer = setTimeout(() => {
                  liveStatus = 'stalled';
                  let statusEl = div.querySelector('.tool-status-label');
                  if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
                  statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
                  laylaNotifyStreamPhase(div, 'stalled');
                }, researchStallMs);
                full += obj.token;
                let parsed = full;
                try { if (typeof marked !== 'undefined') parsed = sanitizeHtml(marked.parse(full)); } catch (_) {}
                bubble.innerHTML = parsed;
                bubble.querySelectorAll('pre code').forEach(el => { if (window.hljs) hljs.highlightElement(el); });
                chatEl.scrollTop = chatEl.scrollHeight;
              }
              if (obj.done) {
                clearTimeout(firstTokenTimer);
                clearTimeout(stalledTimer);
                if (obj.content != null && String(obj.content).trim() !== '') full = String(obj.content).trim();
                try {
                  const rmBadge = document.getElementById('reasoning-mode-badge');
                  if (rmBadge && obj.reasoning_mode) rmBadge.textContent = 'Thinking: ' + obj.reasoning_mode;
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
      full = cleanLaylaText(full);
      let parsed = full;
      try { if (typeof marked !== 'undefined') parsed = sanitizeHtml(marked.parse(full)); } catch (_) {}
      bubble.innerHTML = parsed;
      try {
        div.querySelector('.msg-bubble')?.removeAttribute('data-layla-phase');
        if (window.LaylaUI && typeof window.LaylaUI.clearBodyPhase === 'function') window.LaylaUI.clearBodyPhase();
      } catch (_) {}
      bubble.querySelectorAll('pre code').forEach(el => { if (window.hljs) hljs.highlightElement(el); });
      chatEl.scrollTop = chatEl.scrollHeight;
      if (_ttsEnabled && full) { speakText(full).catch(() => {}); }
      refreshApprovals();
      return;
    }
    laylaShowTypingIndicator(ra, 'connecting');
    laylaStartNonStreamTypingPhases();
    const res = await fetchWithTimeout('/research', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, Math.max(laylaAgentStreamTimeoutMs(), 720000));
    laylaRemoveTypingIndicator();
    if (!res.ok) { let body = {}; try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) {} } catch(_) {} addMsg('layla', formatAgentError(res, body)); refreshApprovals(); return; }
    const data = await res.json();
    try {
      const rmBadge = document.getElementById('reasoning-mode-badge');
      const rm = data.reasoning_mode || data.state?.reasoning_mode;
      if (rmBadge) rmBadge.textContent = rm ? ('Thinking: ' + rm) : '';
    } catch (_) {}
    addMsg('layla', data.response || '', data.aspect_name, data.state?.steps?.some(s => s.deliberated), data.state?.steps, data.ux_states, data.memory_influenced);
    if (_ttsEnabled && (data.response || '').trim()) { speakText(data.response).catch(() => {}); }
  } catch (e) {
    laylaRemoveTypingIndicator();
    addMsg('layla', ((e && (e.message||'')).toLowerCase().includes('fetch') || (e && (e.message||'')).toLowerCase().includes('network') || (e && (e.message||'')).toLowerCase().includes('abort')) ? formatAgentError(null, null) : ('Error: ' + (e && e.message || 'unknown')));
  }
  refreshApprovals();
}

let _lastDisplayMsg = null;
let _activeAgentAbort = null;

function cancelActiveSend() {
  try {
    if (_activeAgentAbort) _activeAgentAbort.abort();
  } catch (_) {}
  try { laylaHeaderProgressStop(); } catch (_) {}
}

function setCancelSendVisible(visible) {
  const b = document.getElementById('cancel-send-btn');
  if (b) b.style.display = visible ? 'inline-block' : 'none';
}

function ensureLaylaConversationId() {
  if (typeof currentConversationId === 'string' && String(currentConversationId).trim()) {
    return String(currentConversationId).trim();
  }
  let id = '';
  try {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) id = crypto.randomUUID();
    else id = 'lc-' + Date.now() + '-' + Math.random().toString(36).slice(2, 9);
  } catch (_) {
    id = 'lc-' + Date.now();
  }
  currentConversationId = id;
  try { localStorage.setItem('layla_current_conversation_id', id); } catch (_) {}
  try { if (typeof updateContextChip === 'function') updateContextChip(); } catch (_) {}
  return id;
}

function laylaEnsureReasoningChain(msgLaylaDiv) {
  const msgBub = msgLaylaDiv.querySelector('.msg-bubble');
  if (!msgBub) return null;
  let chain = msgBub.querySelector('.layla-reasoning-chain');
  if (!chain) {
    chain = document.createElement('details');
    chain.className = 'layla-reasoning-chain tool-trace';
    chain.open = true;
    chain.innerHTML = '<summary class="layla-reasoning-summary">Reasoning</summary><div class="layla-reasoning-steps"></div>';
    const md = msgBub.querySelector('.md-content');
    if (md) msgBub.insertBefore(chain, md);
    else msgBub.insertBefore(chain, msgBub.firstChild);
  }
  return chain;
}

function laylaAppendReasoningStep(msgLaylaDiv, text, stepNum) {
  const chain = laylaEnsureReasoningChain(msgLaylaDiv);
  if (!chain) return;
  const steps = chain.querySelector('.layla-reasoning-steps');
  if (!steps) return;
  const n = stepNum && Number(stepNum) > 0 ? Number(stepNum) : (steps.children.length + 1);
  const row = document.createElement('div');
  row.className = 'layla-reasoning-step';
  row.innerHTML = '<span class="layla-reasoning-step-n">' + n + '.</span><div class="layla-reasoning-step-body"></div>';
  row.querySelector('.layla-reasoning-step-body').textContent = String(text || '');
  steps.appendChild(row);
  const sum = chain.querySelector('.layla-reasoning-summary');
  if (sum) sum.textContent = 'Reasoning · ' + steps.children.length + ' steps';
}

function retryLastMessage() {
  if (!_lastDisplayMsg) return;
  const chat = document.getElementById('chat');
  const input = document.getElementById('msg-input');
  if (!chat || !input) return;
  const nodes = [...chat.children];
  const toRemove = [];
  let foundLayla = false, foundSep = false, foundYou = false;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (n.id === 'typing-wrap') { toRemove.push(n); continue; }
    if (!foundLayla && n.classList.contains('msg-layla')) { foundLayla = true; toRemove.push(n); continue; }
    if (foundLayla && !foundSep && n.classList.contains('separator')) { foundSep = true; toRemove.push(n); continue; }
    if (foundSep && !foundYou && n.classList.contains('msg-you')) { foundYou = true; toRemove.push(n); break; }
  }
  toRemove.forEach(el => el.remove());
  input.value = _lastDisplayMsg;
  toggleSendButton();
  send();
}

async function send() {
  _dbg('send() called');
  _hideMentionDropdown();
  const input = document.getElementById('msg-input');
  if (!input) { _dbg('send() exit: no #msg-input'); return; }
  let msg = input.value.trim();
  if (!msg) { _dbg('send() exit: empty msg'); return; }
  if (window._laylaSendBusy) { _dbg('send() exit: already in flight'); return; }
  _dbg('send() proceeding', 'msg length=' + msg.length);

  const ac = new AbortController();
  _activeAgentAbort = ac;
  setCancelSendVisible(true);
  try { laylaHeaderProgressStart(); } catch (_) {}
  try { operatorTraceClear(); } catch (_) {}

  // Parse @mention — extract aspect override for this message only
  let msgAspect = currentAspect;
  const mentionMatch = msg.match(/^@([a-z]+)\s*/i);
  if (mentionMatch) {
    const mentioned = mentionMatch[1].toLowerCase();
    const found = ASPECTS.find(a => a.id === mentioned || a.name.toLowerCase() === mentioned);
    if (found) {
      msgAspect = found.id;
      msg = msg.slice(mentionMatch[0].length).trim() || msg; // strip @mention from message body
    }
  }

  // If aspect locked, always use currentAspect
  if (_aspectLocked) msgAspect = currentAspect;

  // Visual flash when routing to a different aspect than current
  if (msgAspect !== currentAspect) {
    const a = ASPECTS.find(x => x.id === msgAspect);
    if (a) {
      const badge = document.getElementById('aspect-badge');
      const prev = badge?.textContent;
      if (badge) { badge.textContent = a.sym + ' ' + a.name.toUpperCase() + ' ↩'; badge.style.opacity = '0.7'; }
      setTimeout(() => { if (badge) { badge.textContent = prev; badge.style.opacity = ''; } }, 2200);
    }
  }

  const hadImages = _attachedImages.length > 0;
  input.value = '';
  toggleSendButton();
  let displayMsg = mentionMatch && msgAspect !== currentAspect
    ? `@${msgAspect} ${msg}`
    : msg;
  if (hadImages) displayMsg += ' [📎 image attached]';
  addMsg('you', displayMsg);
  addSeparator();
  _lastDisplayMsg = displayMsg;
  try {
    const rmBadge = document.getElementById('reasoning-mode-badge');
    if (rmBadge) rmBadge.textContent = '';
  } catch (_) {}

  ensureLaylaConversationId();

  const streamMode = document.getElementById('stream-toggle')?.checked || false;
  const modelOverride = (document.getElementById('model-override')?.value || '').trim();
  const payload = {
    message: msg,
    aspect_id: msgAspect,
    conversation_id: currentConversationId,
    show_thinking: document.getElementById('show-thinking')?.checked ?? false,
    allow_write: document.getElementById('allow-write')?.checked ?? false,
    allow_run: document.getElementById('allow-run')?.checked ?? false,
    stream: streamMode,
  };
  const _epSel = document.getElementById('engineering-pipeline-mode');
  if (_epSel && _epSel.value && _epSel.value !== 'chat') payload.engineering_pipeline_mode = _epSel.value;
  const _clarTa = document.getElementById('pipeline-clarify-answers');
  if (_clarTa && _clarTa.value.trim()) {
    payload.clarification_reply = _clarTa.value.trim();
    _clarTa.value = '';
    const _cp = document.getElementById('pipeline-clarify-panel');
    if (_cp) _cp.style.display = 'none';
  }
