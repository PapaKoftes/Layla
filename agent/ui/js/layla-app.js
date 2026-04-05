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
  if (modelOverride) payload.model_override = modelOverride;
  if (document.getElementById('reasoning-effort')?.checked) payload.reasoning_effort = 'high';
  if (document.getElementById('plan-mode-toggle')?.checked) payload.plan_mode = true;
  const composeNotes = (document.getElementById('compose-draft')?.value || '').trim();
  if (composeNotes) {
    payload.context = '[Working notes from operator sidebar]\n' + composeNotes + (payload.context ? '\n\n' + payload.context : '');
  }
  const projSel = document.getElementById('project-select');
  if (projSel && projSel.value) payload.project_id = projSel.value;
  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  if (wp) {
    payload.workspace_root = wp;
    try {
      let recent = JSON.parse(localStorage.getItem(WS_RECENT_KEY) || '[]');
      recent = [wp, ...recent.filter(p => p !== wp)].slice(0, WS_RECENT_MAX);
      localStorage.setItem(WS_RECENT_KEY, JSON.stringify(recent));
    } catch (_) {}
  }
  if (hadImages) {
    payload.image_base64 = _attachedImages[0].base64;
    _attachedImages = [];
    const chips = document.getElementById('file-context-chips');
    if (chips) {
      chips.querySelectorAll('[data-image-chip]').forEach(el => el.remove());
      if (!chips.children.length) chips.style.display = 'none';
    }
  }

  const chatEl = document.getElementById('chat');

  _dbg('send() calling fetch /agent', 'stream=' + !!streamMode);
  window._laylaSendBusy = true;
  _promptHistoryIdx = -1;
  try { if (typeof setHeaderAgentActivity === 'function') setHeaderAgentActivity(true); } catch (_) {}
  try {
    if (streamMode) {
      // Stream row shows facet + pulsing dots until first token arrives
      const res = await fetchWithTimeout('/agent', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: ac.signal }, laylaAgentStreamTimeoutMs());
      if (!res.ok || !res.body) { let body = {}; try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) { body = { response: t.length < 120 ? t : res.statusText }; } } catch(_) {} addMsg('layla', formatAgentError(res, body), null, false, null); refreshApprovals(); setCancelSendVisible(false); _activeAgentAbort = null; return; }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = '';
      let streamUxStates = [];
      let streamMemoryInfluenced = [];
      let streamDoneSteps = [];
      let gotDone = false;
      let streamDoneAspectName = null;
      hideEmpty();
      const div = document.createElement('div');
      div.className = 'msg msg-layla';
      div.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(msgAspect) + '</div><div class="msg-bubble" title="Click to copy"><div class="md-content stream-md-placeholder"><div class="typing-indicator" style="min-height:36px"><div class="typing-dots"><span></span><span></span><span></span></div></div></div></div>';
      chatEl.appendChild(div);
      laylaNotifyStreamPhase(div, 'connecting');
      if (streamMode) {
        const steerCid = String(currentConversationId || '').trim() || ensureLaylaConversationId();
        const wrap = document.createElement('div');
        wrap.className = 'layla-steer-wrap';
        wrap.innerHTML = '<span class="layla-steer-lbl" title="Queued at her next thinking step">Steer</span><input type="text" class="layla-steer-inp" maxlength="200" placeholder="Short redirect…" aria-label="Steer in-flight reply" /><button type="button" class="layla-steer-go" title="Send steer">→</button>';
        const inp = wrap.querySelector('.layla-steer-inp');
        const sendSteer = function () {
          const h = (inp && inp.value ? inp.value : '').trim();
          if (!h) return;
          fetch('/agent/steer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation_id: steerCid, hint: h }),
          }).then(function (r) {
            if (inp) inp.value = '';
            if (typeof showToast === 'function') showToast(r.ok ? 'Steer queued' : 'Steer failed');
          }).catch(function () { if (typeof showToast === 'function') showToast('Steer failed'); });
        };
        wrap.querySelector('.layla-steer-go')?.addEventListener('click', sendSteer);
        inp?.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') { e.preventDefault(); sendSteer(); }
        });
        const bubOuter = div.querySelector('.msg-bubble');
        if (bubOuter) div.insertBefore(wrap, bubOuter);
      }
      const bubble = div.querySelector('.md-content');
      const streamMeta = document.createElement('div');
      streamMeta.className = 'memory-attribution';
      streamMeta.textContent = 'Status: ' + (UX_STATE_LABELS.connecting || 'Connecting') + ' | elapsed: 0s | chars: 0';
      div.appendChild(streamMeta);
      const streamStartedAt = Date.now();
      const stallMs = laylaStalledSilenceMs();
      const capMs = laylaAgentStreamTimeoutMs();
      let liveStatus = 'connecting';
      const metaTimer = setInterval(() => {
        const secs = Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000));
        const line = UX_STATE_LABELS[liveStatus] || liveStatus;
        streamMeta.textContent = 'Status: ' + line + ' | elapsed: ' + secs + 's | chars: ' + (full || '').length + ' | wait cap ~' + Math.round(capMs / 60000) + 'm | stall warn ~' + Math.round(stallMs / 1000) + 's';
      }, 500);
      let gotToken = false;
      let firstTokenTimer = setTimeout(() => {
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
        liveStatus = 'waiting_first_token';
        statusEl.textContent = UX_STATE_LABELS.waiting_first_token;
        laylaNotifyStreamPhase(div, liveStatus);
      }, 1200);
      let stalledTimer = setTimeout(() => {
        let statusEl = div.querySelector('.tool-status-label');
        if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
        liveStatus = 'stalled';
        statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
        laylaNotifyStreamPhase(div, 'stalled');
      }, stallMs);
      let streamReasoningTree = null;
      while (true) {
        let value, done;
        try {
          const r = await reader.read();
          value = r.value;
          done = r.done;
        } catch (readErr) {
          clearInterval(metaTimer);
          clearTimeout(firstTokenTimer);
          clearTimeout(stalledTimer);
          if (ac.signal.aborted || (readErr && readErr.name === 'AbortError')) {
            try { operatorTraceLine('aborted', 'client stop'); } catch (_) {}
            addMsg('layla', 'Generation stopped.');
          } else {
            addMsg('layla', 'Stream read error: ' + (readErr && readErr.message || readErr));
          }
          laylaRemoveTypingIndicator();
          setCancelSendVisible(false);
          _activeAgentAbort = null;
          return;
        }
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
                  let statusEl = div.querySelector('.tool-status-label');
                  if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
                  liveStatus = 'stalled';
                  statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
                  laylaNotifyStreamPhase(div, 'stalled');
                }, stallMs);
                try { operatorTraceLine('pulse', 'keepalive'); } catch (_) {}
              }
              if (obj.ux_state) {
                streamUxStates.push(obj.ux_state);
                liveStatus = obj.ux_state;
                try { operatorTraceLine('ux_state', obj.ux_state); } catch (_) {}
                let statusEl = div.querySelector('.tool-status-label');
                if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
                statusEl.textContent = UX_STATE_LABELS[obj.ux_state] || obj.ux_state;
                laylaNotifyStreamPhase(div, obj.ux_state);
              }
              if (obj.ctx_pct != null && obj.ux_state) {
                const nctx = window.__laylaNCtx || 4096;
                const est = Math.round((Number(obj.ctx_pct) / 100) * nctx);
                updateLaylaCtxBar(obj.ctx_pct, est, nctx);
                const ban = document.getElementById('context-limit-banner');
                if (ban) {
                  ban.style.display = 'block';
                  if (obj.ux_state === 'context_critical') {
                    ban.style.background = '#822';
                    ban.textContent = 'Context critical (~' + obj.ctx_pct + '% of window). Use ⊙ Compact.';
                  } else {
                    ban.style.background = '#664400';
                    ban.textContent = 'Context ~' + obj.ctx_pct + '% full — ⊙ Compact or POST /compact';
                  }
                }
              }
              if (obj.tool_start) {
                liveStatus = 'tool_running';
                laylaNotifyStreamPhase(div, 'tool_running');
                try { operatorTraceLine('tool', obj.tool_start); } catch (_) {}
                updateToolStatus(obj.tool_start, div);
                // Live step row — append to a dedicated live-actions container
                let liveTrace = div.querySelector('.live-tool-trace');
                if (!liveTrace) {
                  liveTrace = document.createElement('div');
                  liveTrace.className = 'live-tool-trace';
                  liveTrace.style.cssText = 'margin-top:5px;font-size:0.66rem;color:var(--text-dim)';
                  const bubble2 = div.querySelector('.msg-bubble');
                  if (bubble2) bubble2.appendChild(liveTrace); else div.appendChild(liveTrace);
                }
                const row = document.createElement('div');
                row.style.cssText = 'padding:1px 0;opacity:0.8';
                row.textContent = '⟳ ' + obj.tool_start;
                row.dataset.tool = obj.tool_start;
                liveTrace.appendChild(row);
                chatEl.scrollTop = chatEl.scrollHeight;
              }
              if (Object.prototype.hasOwnProperty.call(obj, 'think') && String(obj.think || '').trim()) {
                try { operatorTraceLine('think', String(obj.think).slice(0, 400)); } catch (_) {}
                laylaAppendReasoningStep(div, obj.think, obj.think_step);
                liveStatus = 'thinking';
                let statusEl = div.querySelector('.tool-status-label');
                if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
                statusEl.textContent = UX_STATE_LABELS.thinking || 'Thinking';
                laylaNotifyStreamPhase(div, 'thinking');
              }
              if (obj.token) {
                liveStatus = 'streaming';
                laylaNotifyStreamPhase(div, 'streaming');
                if (!gotToken) {
                  gotToken = true;
                  clearTimeout(firstTokenTimer);
                  if (bubble && bubble.classList.contains('stream-md-placeholder')) {
                    bubble.classList.remove('stream-md-placeholder');
                    bubble.innerHTML = '';
                  }
                }
                clearTimeout(stalledTimer);
                stalledTimer = setTimeout(() => {
                  let statusEl = div.querySelector('.tool-status-label');
                  if (!statusEl) { statusEl = document.createElement('div'); statusEl.className = 'tool-status-label'; div.querySelector('.msg-bubble')?.appendChild(statusEl); }
                  liveStatus = 'stalled';
                  statusEl.textContent = UX_STATE_LABELS.stalled + ' — ' + UX_STATE_LABELS.retry_hint;
                  laylaNotifyStreamPhase(div, 'stalled');
                }, stallMs);
                full += obj.token; let parsed = full; try { if (typeof marked !== 'undefined') parsed = sanitizeHtml(marked.parse(full)); } catch (_) {} bubble.innerHTML = parsed; bubble.querySelectorAll('pre code').forEach(el => { if (window.hljs) hljs.highlightElement(el); }); chatEl.scrollTop = chatEl.scrollHeight;
              }
              if (obj.done) {
                clearTimeout(firstTokenTimer);
                clearTimeout(stalledTimer);
                clearToolStatus(div);
                if (obj.aspect_name) streamDoneAspectName = obj.aspect_name;
                if (obj.content != null && String(obj.content).trim() !== '') full = String(obj.content).trim();
                if (obj.conversation_id) {
                  currentConversationId = String(obj.conversation_id);
                  localStorage.setItem('layla_current_conversation_id', currentConversationId);
                  try { updateContextChip(); _renderSessionList(); } catch (_) {}
                }
                if (Array.isArray(obj.ux_states)) streamUxStates = obj.ux_states;
                if (Array.isArray(obj.memory_influenced)) streamMemoryInfluenced = obj.memory_influenced;
                if (obj.reasoning_tree_summary) streamReasoningTree = obj.reasoning_tree_summary;
                if (Array.isArray(obj.steps)) streamDoneSteps = obj.steps;
                try {
                  const rmBadge = document.getElementById('reasoning-mode-badge');
                  if (rmBadge && obj.reasoning_mode) rmBadge.textContent = 'Thinking: ' + obj.reasoning_mode;
                } catch (_) {}
                gotDone = true;
                try { updateLaylaCtxFromSessionStats(); } catch (_) {}
                break;
              }
            } catch (_) {}
          }
        }
        if (gotDone) break;
      }
      laylaRemoveTypingIndicator();
      clearInterval(metaTimer);
      streamMeta.textContent = 'Done · ' + Math.max(0, Math.floor((Date.now() - streamStartedAt) / 1000)) + 's · ' + (full || '').length + ' chars';
      full = cleanLaylaText(full);
      let parsed = full; try { if (typeof marked !== 'undefined') parsed = sanitizeHtml(marked.parse(full)); } catch (_) {} bubble.innerHTML = parsed;
      try {
        div.querySelector('.msg-bubble')?.removeAttribute('data-layla-phase');
        if (window.LaylaUI && typeof window.LaylaUI.clearBodyPhase === 'function') window.LaylaUI.clearBodyPhase();
      } catch (_) {}
      bubble.querySelectorAll('pre code').forEach(el => { if (window.hljs) hljs.highlightElement(el); });
      const label = div.querySelector('.msg-label-layla') || div.querySelector('.msg-label');
      if (label) {
        const fa = facetMetaFromNameOrId(streamDoneAspectName || msgAspect);
        const chip = label.querySelector('.msg-facet-chip');
        if (fa && chip) {
          chip.textContent = fa.sym + ' ' + fa.name;
          chip.classList.remove('msg-facet-unknown');
        }
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
      }
      if (streamUxStates.length > 0) {
        const badges = document.createElement('div');
        badges.className = 'ux-state-badges';
        streamUxStates.forEach(s => { const b = document.createElement('span'); b.className = 'ux-state-badge'; b.textContent = UX_STATE_LABELS[s] || s; badges.appendChild(b); });
        div.appendChild(badges);
      }
      if (streamMemoryInfluenced.length > 0) {
        const mem = document.createElement('div');
        mem.className = 'memory-attribution';
        mem.textContent = 'Used memory: ' + (streamMemoryInfluenced.includes('learnings') && streamMemoryInfluenced.includes('semantic_recall') ? 'learnings & recall' : streamMemoryInfluenced.includes('learnings') ? 'learnings' : 'recall');
        div.appendChild(mem);
      }
      // Replace live-tool-trace with final structured step trace (if steps present)
      const liveTraceEl = div.querySelector('.live-tool-trace');
      const doneSteps = streamDoneSteps || [];
      if (liveTraceEl) {
        if (doneSteps.length > 0) {
          const finalTrace = document.createElement('details');
          finalTrace.className = 'tool-trace';
          finalTrace.innerHTML = '<summary>What she did (' + doneSteps.length + ')</summary>';
          const pre = document.createElement('div');
          pre.className = 'tool-trace-content';
          pre.textContent = doneSteps.map(s => { try { return s.action + ': ' + JSON.stringify(s.result).slice(0, 200); } catch (_) { return s.action + ': [unserializable]'; } }).join('\n');
          finalTrace.appendChild(pre);
          liveTraceEl.replaceWith(finalTrace);
        } else {
          liveTraceEl.remove();
        }
      }
      _renderReasoningTreeSummary(div, streamReasoningTree);
      chatEl.scrollTop = chatEl.scrollHeight;
      if (_ttsEnabled && full) { speakText(full).catch(() => {}); }
      updateRetryButton();
      refreshApprovals();
      document.getElementById('msg-input')?.focus();
      setCancelSendVisible(false);
      _activeAgentAbort = null;
      return;
    }
    laylaShowTypingIndicator(msgAspect, 'connecting');
    laylaStartNonStreamTypingPhases();
    const res = await fetchWithTimeout('/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: ac.signal,
    }, laylaAgentJsonTimeoutMs());
    laylaRemoveTypingIndicator();
    if (!res.ok) {
      let body = {};
      try { const t = await res.text(); if (t) try { body = JSON.parse(t); } catch(_) { body = { response: t }; } } catch (_) {}
      addMsg('layla', formatAgentError(res, body));
      refreshApprovals();
      setCancelSendVisible(false);
      _activeAgentAbort = null;
      return;
    }
    let data = {};
    try { data = await res.json(); } catch (_) {
      addMsg('layla', 'Invalid response from server (non-JSON).');
      refreshApprovals();
      setCancelSendVisible(false);
      _activeAgentAbort = null;
      return;
    }
    // Paused due to high resource load — show checkpoint banner with Resume button
    if (data.status === 'paused_high_load' || (data.state && data.state.status === 'paused_high_load')) {
      laylaRemoveTypingIndicator();
      hideEmpty();
      const pausedDiv = document.createElement('div');
      pausedDiv.className = 'msg msg-layla';
      const checkpoint = data.state?.checkpoint || data.checkpoint || {};
      const stepsCount = (checkpoint.steps || []).length;
      const pausedGoal = checkpoint.goal || goal || '';
      pausedDiv.innerHTML = `<div class="msg-label msg-label-layla">${formatLaylaLabelHtml(msgAspect)}</div>
        <div class="msg-bubble">
          <div style="color:#fa0;font-size:0.8rem;margin-bottom:5px">⚠ Paused — system resources high (${stepsCount} step${stepsCount!==1?'s':''} completed)</div>
          <div style="font-size:0.75rem;color:var(--text-dim);margin-bottom:8px">She saved progress. Click Resume when your system is less busy.</div>
          <div style="display:flex;gap:6px">
            <button onclick="resumeFromCheckpoint(${JSON.stringify(checkpoint).replace(/"/g,'&quot;')})" style="font-size:0.75rem;padding:5px 14px;background:var(--asp);border:1px solid var(--asp);color:#fff;border-radius:3px;cursor:pointer">▶ Resume</button>
          </div>
        </div>`;
      document.getElementById('chat')?.appendChild(pausedDiv);
      document.getElementById('chat')?.scrollTo(0, 99999);
      setCancelSendVisible(false); _activeAgentAbort = null;
      return;
    }

    // Plan-ready: editable JSON + execute (operator can revise steps before run)
    if (data.status === 'plan_ready' && Array.isArray(data.plan)) {
      laylaRemoveTypingIndicator();
      hideEmpty();
      const planDiv = document.createElement('div');
      planDiv.className = 'msg msg-layla plan-review-msg';
      planDiv.dataset.planGoal = msg;
      const esc = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const summary = data.plan.map((s, i) =>
        '<div style="margin:3px 0;font-size:0.78rem"><b>' + (i + 1) + '.</b> ' + esc(s.task || '') + '</div>'
      ).join('');
      planDiv.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(msgAspect) + '</div>' +
        '<div class="msg-bubble">' +
        '<div style="font-size:0.78rem;color:var(--asp);margin-bottom:6px">Plan ready — ' + data.plan.length + ' step' + (data.plan.length !== 1 ? 's' : '') + ' (edit JSON if needed, then Execute)</div>' +
        '<div style="font-size:0.65rem;color:var(--text-dim);margin-bottom:6px">Preview:</div>' + summary +
        '<label style="display:block;font-size:0.65rem;color:var(--text-dim);margin:10px 0 4px">Plan JSON</label>' +
        '<div class="layla-plan-json-wrap"></div>' +
        '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">' +
        '<button type="button" onclick="laylaRunPlanFromElement(this.closest(\'.plan-review-msg\'))" style="font-size:0.75rem;padding:5px 14px;background:var(--asp);border:1px solid var(--asp);color:#fff;border-radius:3px;cursor:pointer">▶ Execute plan</button>' +
        '<button type="button" onclick="laylaFormatPlanJson(this)" style="font-size:0.75rem;padding:5px 10px;background:var(--code-bg);border:1px solid var(--border);color:var(--text);border-radius:3px;cursor:pointer">Reformat JSON</button>' +
        '<button type="button" onclick="this.closest(\'.msg\').remove()" style="font-size:0.75rem;padding:5px 10px;background:transparent;border:1px solid var(--border);color:var(--text-dim);border-radius:3px;cursor:pointer">Discard</button>' +
        '</div></div>';
      const ta = document.createElement('textarea');
      ta.className = 'layla-plan-json';
      ta.style.cssText = 'width:100%;min-height:140px;box-sizing:border-box;font-family:JetBrains Mono,monospace;font-size:0.68rem;padding:8px;background:var(--code-bg);border:1px solid var(--border);color:var(--text);border-radius:4px';
      ta.value = JSON.stringify(data.plan, null, 2);
      planDiv.querySelector('.layla-plan-json-wrap')?.appendChild(ta);
      document.getElementById('chat')?.appendChild(planDiv);
      document.getElementById('chat')?.scrollTo(0, 99999);
      try { operatorTraceLine('plan', 'plan_ready ' + data.plan.length + ' steps'); } catch (_) {}
      setCancelSendVisible(false); _activeAgentAbort = null;
      return;
    }
    const replyText = (data.response != null && String(data.response).trim() !== '') ? data.response : 'No response from Layla.';
    if (data.conversation_id) {
      currentConversationId = String(data.conversation_id);
      localStorage.setItem('layla_current_conversation_id', currentConversationId);
      try { updateContextChip(); _renderSessionList(); } catch (_) {}
    }
    try {
      const rmBadge = document.getElementById('reasoning-mode-badge');
      const rm = data.reasoning_mode || data.state?.reasoning_mode;
      if (rmBadge) rmBadge.textContent = rm ? ('Thinking: ' + rm) : '';
    } catch (_) {}
    addMsg('layla', replyText, data.aspect_name, data.state?.steps?.some(s => s.deliberated), data.state?.steps, data.ux_states, data.memory_influenced, data.reasoning_tree_summary || data.state?.reasoning_tree_summary);
    updateRetryButton();
    if (data.refused && data.refusal_reason) {
      const refDiv = document.createElement('div');
      refDiv.className = 'deliberation';
      refDiv.innerHTML = '<span class="deliberation-label">She declined</span><br>' + (data.refusal_reason || '').replace(/</g, '&lt;');
      const lastLayla = document.querySelector('#chat .msg-layla:last-of-type');
      if (lastLayla) lastLayla.appendChild(refDiv);
    }
    if (_ttsEnabled && (data.response || '').trim()) { speakText(data.response).catch(() => {}); }
    refreshApprovals();
    document.getElementById('msg-input')?.focus();
    setCancelSendVisible(false);
    _activeAgentAbort = null;
  } catch (e) {
    _dbg('send() catch', e && e.message, e);
    laylaRemoveTypingIndicator();
    const errRaw = (e && (e.message || e.reason)) || String(e || '');
    const err = errRaw.toLowerCase();
    if (e && e.name === 'AbortError') {
      addMsg('layla', 'Generation stopped.');
      setCancelSendVisible(false);
      _activeAgentAbort = null;
      refreshApprovals();
      document.getElementById('msg-input')?.focus();
      return;
    }
    const msg = (err.includes('fetch') || err.includes('network') || err.includes('load failed')) ? formatAgentError(null, null) : ('Something went wrong: ' + (e && (e.message || e.reason)) || 'unknown error');
    addMsg('layla', msg);
    refreshApprovals();
    document.getElementById('msg-input')?.focus();
    setCancelSendVisible(false);
    _activeAgentAbort = null;
  } finally {
    window._laylaSendBusy = false;
    try { laylaHeaderProgressStop(); } catch (_) {}
    try { if (typeof setHeaderAgentActivity === 'function') setHeaderAgentActivity(false); } catch (_) {}
  }
}

async function refreshApprovals() {
  const list = document.getElementById('approvals-list');
  try {
    const res = await fetchWithTimeout('/pending', {}, 10000);
    if (!res.ok) {
      if (list) list.innerHTML = '<span style="color:#f90;font-size:0.75rem">Could not load approvals (' + res.status + ')</span>';
      return;
    }
    const data = await res.json();
    const pending = (data.pending || []).filter(e => e.status === 'pending');
    if (!pending.length) { if (list) list.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">Layla will ask here when she needs permission to act</span>'; return; }
    if (!list) return;
    list.innerHTML = '';
    pending.forEach(e => {
      const item = document.createElement('div');
      item.className = 'panel-item';
      item.style.cssText = 'flex-direction:column;align-items:flex-start;gap:4px;padding:6px 8px';
      const files = e.args?.files;
      const isBatch = e.tool === 'write_files_batch' && Array.isArray(files) && files.length > 1;
      const riskColor = {high:'#f44',medium:'#fa0',low:'#8f8'}[e.risk_level] || '#aaa';
      const headerRow = document.createElement('div');
      headerRow.style.cssText = 'display:flex;align-items:center;gap:6px;width:100%';
      headerRow.innerHTML =
        '<span style="font-size:0.7rem;flex:1">'
        + '<b style="color:'+riskColor+'">' + e.tool + '</b>'
        + (isBatch ? ' <span style="color:var(--text-dim)">(' + files.length + ' files)</span>' : '')
        + '<br><span style="color:var(--text-dim);font-size:0.62rem">' + e.id.slice(0,8) + ' · ' + (e.risk_level||'?') + ' risk</span></span>';
      item.appendChild(headerRow);
      // Inline diff preview if available
      const diff = e.args?.diff;
      if (diff) {
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:0.6rem;max-height:120px;overflow:auto;background:var(--bg-deep,#111);border:1px solid #333;padding:4px 6px;border-radius:3px;width:100%;box-sizing:border-box;white-space:pre;color:#ccc';
        pre.textContent = typeof diff === 'string' ? diff.slice(0, 2000) + (diff.length > 2000 ? '\n...' : '') : JSON.stringify(diff, null, 2).slice(0, 1200);
        item.appendChild(pre);
      }
      // Session grant checkbox
      const grantRow = document.createElement('label');
      grantRow.style.cssText = 'display:flex;align-items:center;gap:5px;font-size:0.65rem;color:var(--text-dim);cursor:pointer';
      const grantCb = document.createElement('input');
      grantCb.type = 'checkbox';
      grantCb.id = 'sg-' + e.id;
      grantRow.appendChild(grantCb);
      grantRow.appendChild(document.createTextNode('Allow for this session'));
      item.appendChild(grantRow);
      // Buttons row
      const btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;gap:6px';
      if (isBatch) {
        const viewBtn = document.createElement('button');
        viewBtn.className = 'approve-btn';
        viewBtn.textContent = 'View';
        viewBtn.onclick = () => openBatchDiffViewer(e);
        btnRow.appendChild(viewBtn);
      }
      const approveBtn = document.createElement('button');
      approveBtn.className = 'approve-btn';
      approveBtn.textContent = isBatch ? 'Apply all' : 'Approve';
      approveBtn.onclick = () => approveId(e.id, document.getElementById('sg-' + e.id)?.checked);
      btnRow.appendChild(approveBtn);
      const denyBtn = document.createElement('button');
      denyBtn.className = 'approve-btn';
      denyBtn.style.cssText = 'background:transparent;border:1px solid #555;color:#aaa';
      denyBtn.textContent = 'Deny';
      denyBtn.onclick = () => denyApproval(e.id);
      btnRow.appendChild(denyBtn);
      item.appendChild(btnRow);
      list.appendChild(item);
    });
  } catch (e) {
    if (list) list.innerHTML = '<span style="color:#f90;font-size:0.75rem">Approvals unavailable — check connection</span>';
  }
}

async function approveId(id, saveForSession = false) {
  await fetch('/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, save_for_session: saveForSession }),
  });
  refreshApprovals();
}

async function denyApproval(id) {
  await fetch('/deny', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  refreshApprovals();
}

function _studyChipButton(label, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'approve-btn';
  b.style.cssText = 'font-size:0.62rem;padding:3px 6px;line-height:1.2;max-width:100%;text-align:left';
  const short = label.length > 52 ? label.slice(0, 50) + '…' : label;
  b.textContent = short;
  b.title = label;
  b.onclick = onClick;
  return b;
}

function fillStudyTopicAndFocus(topic) {
  const input = document.getElementById('study-input');
  if (input) {
    input.value = topic;
    input.focus();
  }
}

async function loadStudyPresetsAndSuggestions() {
  const pre = document.getElementById('study-presets');
  const sug = document.getElementById('study-suggestions');
  if (!pre || !sug) return;
  try {
    const [rp, rs] = await Promise.all([
      fetchWithTimeout('/study_plans/presets', {}, 8000),
      fetchWithTimeout('/study_plans/suggestions', {}, 8000),
    ]);
    pre.innerHTML = '';
    sug.innerHTML = '';
    if (rp.ok) {
      const d = await rp.json();
      (d.topics || []).forEach(function(t) {
        pre.appendChild(_studyChipButton(t, function() { fillStudyTopicAndFocus(t); }));
      });
    }
    if (rs.ok) {
      const d2 = await rs.json();
      (d2.suggestions || []).forEach(function(t) {
        sug.appendChild(_studyChipButton(t, function() { fillStudyTopicAndFocus(t); }));
      });
    }
  } catch (e) {
    console.warn('loadStudyPresetsAndSuggestions', e);
  }
}

async function deriveAndFillStudyTopic(message) {
  try {
    const res = await fetch('/study_plans/derive_topic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: message }),
    });
    const d = await res.json();
    if (d.ok && d.topic) {
      fillStudyTopicAndFocus(d.topic);
      showToast('Topic filled — press + to add plan');
    } else {
      showToast(d.error || 'Could not derive topic');
    }
  } catch (e) {
    showToast('Error: ' + e.message);
  }
}

async function studyTopicFromChatInput() {
  const inp = document.getElementById('msg-input');
  const text = inp && inp.value.trim();
  if (!text) {
    showToast('Type in the main chat input first');
    return;
  }
  await deriveAndFillStudyTopic(text);
}

async function studyTopicFromLastUserMessage() {
  const bubbles = document.querySelectorAll('.msg-you .msg-bubble');
  if (!bubbles.length) {
    showToast('No sent messages in this chat yet');
    return;
  }
  const text = bubbles[bubbles.length - 1].textContent.trim();
  if (!text) {
    showToast('Last message empty');
    return;
  }
  await deriveAndFillStudyTopic(text);
}

async function refreshStudyPlans() {
  loadStudyPresetsAndSuggestions().catch(function(e) { console.warn('study presets', e); });
  const list = document.getElementById('study-list');
  try {
    const res = await fetchWithTimeout('/study_plans', {}, 12000);
    if (!res.ok) {
      if (list) list.innerHTML = '<span style="color:#f90;font-size:0.75rem">Could not load study plans (' + res.status + ')</span>';
      return;
    }
    const data = await res.json();
    const plans = data.plans || [];
    if (!plans.length) { list.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">Add a topic — Layla will study it when you're active</span>'; return; }
    list.innerHTML = '';
    plans.forEach(p => {
      const card = document.createElement('div');
      card.className = 'panel-item';
      card.style.cssText = 'display:flex;flex-direction:column;gap:3px;padding:7px 8px;margin-bottom:4px;background:var(--code-bg);border:1px solid var(--border);border-radius:3px';
      const topRow = document.createElement('div');
      topRow.style.cssText = 'display:flex;justify-content:space-between;align-items:flex-start;gap:4px';
      const topic = document.createElement('span');
      topic.style.cssText = 'font-size:0.73rem;color:var(--text);line-height:1.35;flex:1';
      topic.textContent = p.topic || '';
      const delBtn = document.createElement('button');
      delBtn.style.cssText = 'background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:0.8rem;opacity:0.6;flex-shrink:0;padding:0 2px;line-height:1';
      delBtn.textContent = '✕';
      delBtn.title = 'Remove plan';
      delBtn.onclick = async () => {
        if (!p.id) return;
        await fetch(`/study_plans/${p.id}`, { method: 'DELETE' });
        refreshStudyPlans();
      };
      topRow.appendChild(topic);
      topRow.appendChild(delBtn);
      card.appendChild(topRow);
      const meta = document.createElement('div');
      meta.style.cssText = 'font-size:0.63rem;color:var(--text-dim);display:flex;justify-content:space-between;align-items:center';
      const lastStr = p.last_studied ? 'last: ' + p.last_studied.slice(0, 16) : 'not yet studied';
      const sessStr = p.study_sessions > 0 ? `${p.study_sessions} session${p.study_sessions>1?'s':''}` : '';
      meta.innerHTML = `<span>${lastStr}</span><span style="color:var(--asp)">${sessStr}</span>`;
      card.appendChild(meta);
      const studyBtn = document.createElement('button');
      studyBtn.className = 'approve-btn';
      studyBtn.style.cssText = 'margin-top:4px;font-size:0.68rem;padding:3px 8px';
      studyBtn.textContent = '▶ Study now';
      studyBtn.onclick = () => studyNow(p.topic);
      card.appendChild(studyBtn);
      list.appendChild(card);
    });
  } catch (e) {
    console.warn('refreshStudyPlans failed:', e);
    if (list) list.innerHTML = '<span style="color:#f90;font-size:0.75rem">Study plans unavailable</span>';
  }
}

async function studyNow(topic) {
  if (!topic) return;
  const payload = { message: 'Study session on: ' + topic + '. Explain key concepts, list important points, and suggest resources.', aspect_id: 'nyx', show_thinking: false, allow_write: false, allow_run: false };
  addMsg('you', 'Study now: ' + topic);
  addSeparator();
  laylaShowTypingIndicator('nyx', 'connecting');
  laylaStartNonStreamTypingPhases();
  try {
    const res = await fetchWithTimeout('/agent', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, laylaAgentJsonTimeoutMs());
    laylaRemoveTypingIndicator();
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      addMsg('layla', formatAgentError(res, data));
      refreshStudyPlans();
      return;
    }
    addMsg('layla', data.response || '', data.aspect_name, data.state?.steps?.some(s => s.deliberated), data.state?.steps, data.ux_states, data.memory_influenced);
    if (_ttsEnabled && (data.response || '').trim()) { speakText(data.response).catch(() => {}); }
    if (res.ok && (data.response || '').trim()) {
      await fetch('/study_plans/record_progress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic, note: (data.response || '').trim().slice(0, 500) }),
      });
    }
  } catch (e) {
    laylaRemoveTypingIndicator();
    addMsg('layla', 'Error: ' + (e && e.message || e));
  }
  refreshStudyPlans();
}

async function refreshPlatformHealth() {
  const el = document.getElementById('platform-health');
  if (!el) return;
  const h = window.__laylaHealth || (window.__laylaHealth = { payload: null, lastFetch: 0, lastDeepFetch: 0, deepIntervalMs: 60000, inFlight: false, agentRequestActive: false, _inFlightPromise: null });
  el.innerHTML = '<div class="skeleton" style="height:12px;width:80%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:60%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:70%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:50%"></div>';
  try {
    let d = h.payload;
    const stale = !d || (Date.now() - (h.lastFetch || 0) > 8000);
    if (stale) d = await fetchHealthPayloadOnce();
    if (!d) { el.innerHTML = '<span style="color:#f90">Health unavailable</span>'; return; }
    const opt = d.system_optimizer || {};
    const m = opt.metrics || {};
    const dbOk = d.db_ok !== false;
    const chromaOk = d.chroma_ok === true;
    const uptimeSec = d.uptime_seconds || 0;
    const uh = Math.floor(uptimeSec / 3600);
    const um = Math.floor((uptimeSec % 3600) / 60);
    const uptimeStr = uh > 0 ? uh + 'h ' + um + 'm' : um + 'm';
    let html = `<div style="margin-bottom:6px">DB: ${dbOk ? '✓' : '✗'} | Chroma: ${chromaOk ? '✓' : '✗'} | Uptime: ${uptimeStr}</div>`;
    html += `<div style="margin-bottom:6px"><span style="color:${d.status==='ok'?'#4dff88':'#f90'}">●</span> ${d.status || 'unknown'}</div>`;
    html += `<div>Model: ${d.model_loaded ? 'loaded' : 'not loaded'}${d.active_model ? ' (' + String(d.active_model).replace(/</g, '') + ')' : ''}</div>`;
    const dep = d.dependencies;
    if (dep && typeof dep === 'object') {
      const bits = Object.keys(dep).map((k) => k + ':' + dep[k]).join(' · ');
      html += `<div style="margin-top:4px;font-size:0.68rem;color:var(--text-dim)">${String(bits).replace(/</g, '')}</div>`;
    }
    html += `<div>Tools: ${d.tools_registered || 0}</div>`;
    html += `<div>Learnings: ${d.learnings || 0}</div>`;
    html += `<div>Study plans: ${d.study_plans || 0}</div>`;
    if (m.cpu_percent != null) html += `<div>CPU: ${m.cpu_percent}%</div>`;
    if (m.ram_percent != null) html += `<div>RAM: ${m.ram_percent}%</div>`;
    const kis = d.knowledge_index_status;
    if (kis != null && kis !== '') html += `<div style="margin-top:6px">Knowledge index: ${d.knowledge_index_ready === true ? '✓ ' : d.knowledge_index_ready === false ? '○ ' : ''}${String(kis).replace(/</g, '')}</div>`;
    const elims = d.effective_limits;
    if (elims && typeof elims === 'object') {
      const mtc = elims.max_tool_calls;
      const mrs = elims.max_runtime_seconds;
      if (mtc != null || mrs != null) html += `<div style="margin-top:6px;font-size:0.68rem;color:var(--text-dim)">Limits: tools ${mtc != null ? mtc : '—'} · run ${mrs != null ? mrs + 's' : '—'}</div>`;
    }
    const ec = d.effective_config || {};
    const caps = ec.effective_caps || {};
    if (caps.n_ctx != null) window.__laylaNCtx = Number(caps.n_ctx);
    try {
      const sr = await fetchWithTimeout('/session/stats', {}, 8000);
      if (sr.ok) {
        const s = await sr.json();
        const tin = s.tokens_in || 0;
        const tout = s.tokens_out || 0;
        html += `<div style="margin-top:6px;font-size:0.68rem">Session: tokens in ${tin} · out ${tout} · tools ${s.tool_calls || 0} · ${s.elapsed_seconds || 0}s · ${s.tokens_per_second || 0} tok/s</div>`;
        updateLaylaCtxFromSessionStatsPayload(s);
      }
    } catch (_) {}
    el.innerHTML = html;
  } catch (e) { el.innerHTML = '<span style="color:#f90">Health check timed out or failed.</span>'; }
}

function updateLaylaCtxBar(pct, totalTok, nCtx) {
  const fill = document.getElementById('ctx-bar-fill');
  const label = document.getElementById('ctx-usage-label');
  const pressureHint = document.getElementById('token-pressure-hint');
  const n = nCtx || window.__laylaNCtx || 4096;
  const w = Math.min(100, Math.max(0, Number(pct) || 0));
  if (fill) {
    fill.style.width = w + '%';
    fill.style.background = w >= 90 ? '#c33' : w >= 70 ? '#c90' : '#3a7';
  }
  if (label) {
    if (totalTok != null && totalTok !== '') label.textContent = 'Ctx: ' + totalTok + ' / ' + n;
    else if (pct != null) label.textContent = 'Ctx: ~' + Math.round(pct) + '% · ' + n + ' window';
    else label.textContent = 'Ctx: —';
  }
  // Show chunking indicator when token pressure is above 60%
  if (pressureHint) pressureHint.style.display = w >= 60 ? 'inline' : 'none';
}

function updateLaylaCtxFromSessionStatsPayload(s) {
  try {
    const nctx = window.__laylaNCtx || 4096;
    const used = (s.tokens_in || 0) + (s.tokens_out || 0);
    updateLaylaCtxBar(Math.min(100, (used / nctx) * 100), used, nctx);
  } catch (_) {}
}

async function updateLaylaCtxFromSessionStats() {
  try {
    const r = await fetchWithTimeout('/session/stats', {}, 8000);
    if (!r.ok) return;
    updateLaylaCtxFromSessionStatsPayload(await r.json());
  } catch (_) {}
}

async function compactConversation() {
  if (window._laylaSendBusy) {
    if (typeof showToast === 'function') showToast('Wait for the current message to finish.');
    return;
  }
  try {
    const r = await fetchWithTimeout('/compact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }, 120000);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (typeof showToast === 'function') showToast('Compact failed: ' + (d.detail || d.error || r.status));
      return;
    }
    const chat = document.getElementById('chat');
    if (chat) {
      chat.innerHTML = '';
      const sum = (d.summary || '').trim();
      if (sum) {
        if (typeof addMsg === 'function') addMsg('layla', '[Compacted summary]\n\n' + sum, null, false, [], [], []);
      } else {
        const empty = document.createElement('div');
        empty.id = 'chat-empty';
        empty.innerHTML = typeof renderPromptTilesAndEmptyState === 'function' ? renderPromptTilesAndEmptyState() : '';
        chat.appendChild(empty);
      }
    }
    try { localStorage.removeItem(typeof HISTORY_KEY !== 'undefined' ? HISTORY_KEY : 'layla_chat_history'); } catch (_) {}
    if (typeof showToast === 'function') showToast('Conversation compacted on server.');
    updateLaylaCtxBar(0, 0, window.__laylaNCtx || 4096);
    const ban = document.getElementById('context-limit-banner');
    if (ban) ban.style.display = 'none';
  } catch (e) {
    if (typeof showToast === 'function') showToast('Compact error: ' + (e && e.message || e));
  }
}

async function refreshSkillsList() {
  const el = document.getElementById('platform-skills');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetchWithTimeout('/skills', {}, 12000);
    const d = await r.json();
    const skills = d.skills || [];
    if (!skills.length) {
      el.innerHTML = '<span style="color:var(--text-dim)">No skills found. Add <code>.layla/skills/*.md</code> with YAML frontmatter (name, triggers, description).</span>';
      return;
    }
    el.innerHTML = skills.map((s) => {
      const name = String(s.name || 'Skill');
      const desc = String(s.description || '');
      const tr = (s.triggers || []).map((t) => '<span style="display:inline-block;margin:2px;padding:2px 6px;background:var(--bg2);border-radius:4px;font-size:0.65rem">' + escapeHtml(String(t)) + '</span>').join('');
      return '<div style="margin-bottom:10px;padding:8px;background:var(--code-bg);border:1px solid var(--border);border-radius:4px"><strong>' + escapeHtml(name) + '</strong><div style="font-size:0.68rem;color:var(--text-dim);margin-top:4px">' + escapeHtml(desc) + '</div><div style="margin-top:4px">' + tr + '</div></div>';
    }).join('');
  } catch (e) {
    el.innerHTML = '<span style="color:#f90">Failed to load skills</span>';
  }
}

function laylaPlanStatusColor(st) {
  const x = String(st || '').toLowerCase();
  if (x === 'blocked') return '#c66';
  if (x === 'executing') return '#f90';
  if (x === 'approved') return '#6ad';
  if (x === 'done') return '#6c8';
  return 'var(--text-dim)';
}

function renderLaylaPlansLastExec() {
  const box = document.getElementById('layla-plans-last-exec');
  if (!box) return;
  try {
    const raw = sessionStorage.getItem('layla_last_plan_exec');
    if (!raw) {
      box.innerHTML = '';
      return;
    }
    const o = JSON.parse(raw);
    const j = o.j || {};
    const id = escapeHtml(String(o.id || ''));
    if (!j.ok) {
      box.innerHTML = '<span style="color:#c66">Last execute failed' + (id ? ' (' + id + ')' : '') + ': ' + escapeHtml(String(j.error || '')) + '</span>';
      return;
    }
    const allOk = j.all_steps_ok;
    const r = j.results || {};
    const sd = r.steps_done || [];
    const bad = sd.filter(function (s) { return s && s.governance_ok === false; });
    const head = allOk === true
      ? '<span style="color:#6c8">Last run: all steps OK</span>'
      : (allOk === false
        ? '<span style="color:#c66">Last run: ' + bad.length + ' step(s) blocked / failed validation</span>'
        : '<span>Last run finished</span>');
    const hint = bad[0] && bad[0].validation_error
      ? '<div style="margin-top:4px;opacity:0.9">' + escapeHtml(String(bad[0].validation_error).slice(0, 200)) + '</div>'
      : '';
    box.innerHTML = '<div><strong>SQLite plan</strong> <code>' + id + '</code> — ' + head + '</div>' + hint;
  } catch (_) {
    box.innerHTML = '';
  }
}

async function refreshLaylaPlansPanel() {
  const el = document.getElementById('layla-plans-list');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  renderLaylaPlansLastExec();
  const wp = (document.getElementById('workspace-path') && document.getElementById('workspace-path').value) || '';
  const q = wp ? ('?workspace_root=' + encodeURIComponent(wp)) : '';
  try {
    const res = await fetchWithTimeout('/plans' + q, {}, 20000);
    const j = await res.json();
    if (!j.ok || !Array.isArray(j.plans)) {
      el.innerHTML = '<span style="color:var(--text-dim)">Could not load plans</span>';
      return;
    }
    if (j.plans.length === 0) {
      el.innerHTML = '<span style="color:var(--text-dim)">No plans for this filter. Create one with <code>plan_mode</code> on <code>/agent</code> or <code>POST /plans</code>.</span>';
      return;
    }
    el.innerHTML = j.plans.map(function (p) {
      const rawId = String(p.id || '').replace(/"/g, '');
      const sidDisp = escapeHtml(rawId);
      const stRaw = String(p.status || '');
      const st = escapeHtml(stRaw);
      const stCol = laylaPlanStatusColor(stRaw);
      const n = (p.steps && p.steps.length) || 0;
      const goalLine = escapeHtml(String(p.goal || '').trim().slice(0, 160));
      return '<div class="rta-card" style="margin-bottom:8px;font-size:0.7rem">' +
        '<div><strong>Plan</strong> <code>' + sidDisp + '</code> · <span style="color:' + stCol + '">' + st + '</span> · ' + n + ' steps</div>' +
        (goalLine ? '<div style="margin-top:4px;opacity:0.92">' + goalLine + '</div>' : '') +
        '<div style="margin-top:6px">' +
        '<button type="button" class="approve-btn" style="font-size:0.65rem;margin-right:6px" data-layla-plan-approve="' + rawId + '">Approve</button>' +
        '<button type="button" class="approve-btn" style="font-size:0.65rem" data-layla-plan-exec="' + rawId + '">Execute</button>' +
        '</div></div>';
    }).join('');
    el.querySelectorAll('[data-layla-plan-approve]').forEach(function (btn) {
      btn.onclick = function () {
        const pid = btn.getAttribute('data-layla-plan-approve');
        if (pid) window.laylaApprovePlan(pid);
      };
    });
    el.querySelectorAll('[data-layla-plan-exec]').forEach(function (btn) {
      btn.onclick = function () {
        const pid = btn.getAttribute('data-layla-plan-exec');
        if (pid) window.laylaExecutePlan(pid);
      };
    });
  } catch (e) {
    el.innerHTML = '<span style="color:#c66">' + escapeHtml(String(e && e.message || e)) + '</span>';
  }
}

window.laylaApprovePlan = async function (id) {
  try {
    const res = await fetchWithTimeout('/plans/' + encodeURIComponent(id) + '/approve', { method: 'POST' }, 30000);
    const j = await res.json();
    if (typeof showToast === 'function') showToast(j.ok ? 'Plan approved' : (j.error || 'Approve failed'));
    else alert(j.ok ? 'Approved' : (j.error || 'failed'));
    refreshLaylaPlansPanel();
  } catch (e) {
    if (typeof showToast === 'function') showToast(String(e && e.message || e));
    else alert(String(e));
  }
};

window.laylaExecutePlan = async function (id) {
  const awEl = document.getElementById('allow-write');
  const arEl = document.getElementById('allow-run');
  const aw = !!(awEl && awEl.checked);
  const ar = !!(arEl && arEl.checked);
  const wp = (document.getElementById('workspace-path') && document.getElementById('workspace-path').value) || '';
  try {
    const res = await fetchWithTimeout('/plans/' + encodeURIComponent(id) + '/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ allow_write: aw, allow_run: ar, workspace_root: wp }),
    }, Math.max(laylaAgentJsonTimeoutMs(), 120000));
    const j = await res.json();
    try {
      sessionStorage.setItem('layla_last_plan_exec', JSON.stringify({ id: id, j: j }));
    } catch (_) {}
    if (typeof showToast === 'function') {
      if (j.ok) {
        const ok = j.all_steps_ok;
        showToast(ok === false ? 'Plan finished with validation issues — see Plans panel' : 'Plan execution finished (all steps OK)');
      } else {
        showToast(j.error || 'Execute failed');
      }
    } else {
      alert(j.ok ? (j.all_steps_ok === false ? 'Done with issues' : 'Done') : (j.error || JSON.stringify(j)));
    }
    refreshLaylaPlansPanel();
    renderLaylaPlansLastExec();
  } catch (e) {
    if (typeof showToast === 'function') showToast(String(e && e.message || e));
    else alert(String(e));
  }
};

window.refreshLaylaPlansPanel = refreshLaylaPlansPanel;

let _promptHistoryList = null;
let _promptHistoryIdx = -1;
function _resetPromptHistoryNav() {
  _promptHistoryList = null;
  _promptHistoryIdx = -1;
}
async function _ensurePromptHistory() {
  if (_promptHistoryList !== null) return;
  try {
    const r = await fetchWithTimeout('/history', {}, 8000);
    const d = await r.json();
    const rows = Array.isArray(d.prompts) ? d.prompts : [];
    _promptHistoryList = rows.map((x) => String(x.prompt || '').trim()).filter(Boolean);
  } catch (_) {
    _promptHistoryList = [];
  }
}

async function refreshContentPolicyToggles() {
  const u = document.getElementById('opt-uncensored');
  const n = document.getElementById('opt-nsfw-allowed');
  if (!u || !n) return;
  try {
    const r = await fetchWithTimeout('/settings', {}, 12000);
    const d = await r.json();
    if (!r.ok) return;
    u.checked = d.uncensored !== false;
    n.checked = d.nsfw_allowed !== false;
  } catch (_) {
    /* leave checkboxes unchanged */
  }
}

async function saveContentPolicySettings() {
  const u = document.getElementById('opt-uncensored');
  const n = document.getElementById('opt-nsfw-allowed');
  if (!u || !n) return;
  try {
    const res = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uncensored: !!u.checked, nsfw_allowed: !!n.checked }),
    });
    const data = await res.json();
    if (data.ok) {
      showToast('Content policy saved to runtime_config.json');
      refreshRuntimeOptions();
    } else {
      showToast('Save failed: ' + (data.error || 'unknown'));
    }
  } catch (e) {
    showToast('Error: ' + (e && e.message || e));
  }
}
window.saveContentPolicySettings = saveContentPolicySettings;

async function refreshRuntimeOptions() {
  const el = document.getElementById('runtime-options-panel');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    let d = window.__laylaHealth && window.__laylaHealth.payload;
    const stale = !d || (Date.now() - (window.__laylaHealth.lastFetch || 0) > 8000);
    if (stale) d = await fetchHealthPayloadOnce();
    if (!d) {
      el.innerHTML = '<span style="color:#f90">Could not load <code>/health</code></span>';
      return;
    }
    const fe = d.features_enabled || {};
    const ec = d.effective_config || {};
    const ecaps = ec.effective_caps || {};
    const deps = d.dependencies || {};
    const lim = d.effective_limits || {};
    let html = '';
    html += '<div class="rta-section-title" style="margin-top:0">Feature flags</div><div class="rta-kv">';
    Object.keys(fe).sort().forEach(k => {
      const v = fe[k];
      html += '<div class="rta-kv-row"><span>' + escapeHtml(k) + '</span><span class="' + (v ? 'rta-ok' : 'rta-off') + '">' + (v ? 'on' : 'off') + '</span></div>';
    });
    html += '</div>';
    html += '<div class="rta-section-title">Optional dependencies</div><div class="rta-kv">';
    Object.keys(deps).sort().forEach(k => {
      const s = deps[k];
      const ok = s === 'ok';
      html += '<div class="rta-kv-row"><span>' + escapeHtml(k) + '</span><span class="' + (ok ? 'rta-ok' : 'rta-off') + '">' + escapeHtml(String(s)) + '</span></div>';
    });
    html += '</div>';
    html += '<div class="rta-section-title">Effective limits</div><div class="rta-kv">';
    [['max_tool_calls', lim.max_tool_calls], ['max_runtime_seconds', lim.max_runtime_seconds], ['chat_light_max_runtime_seconds', lim.chat_light_max_runtime_seconds], ['research_max_tool_calls', lim.research_max_tool_calls], ['research_max_runtime_seconds', lim.research_max_runtime_seconds], ['completion_max_tokens', lim.completion_max_tokens], ['max_active_runs', lim.max_active_runs], ['performance_mode', lim.performance_mode], ['max_cpu_percent', lim.max_cpu_percent], ['max_ram_percent', lim.max_ram_percent], ['warn_cpu_percent', lim.warn_cpu_percent], ['hard_cpu_percent', lim.hard_cpu_percent], ['ui_agent_stream_timeout_seconds', lim.ui_agent_stream_timeout_seconds], ['ui_agent_json_timeout_seconds', lim.ui_agent_json_timeout_seconds], ['ui_stalled_silence_ms', lim.ui_stalled_silence_ms]].forEach(([a, b]) => {
      if (b != null && b !== '') html += '<div class="rta-kv-row"><span>' + escapeHtml(a) + '</span><span>' + escapeHtml(String(b)) + '</span></div>';
    });
    html += '</div>';
    html += '<div class="rta-section-title">Config snapshot (non-secret)</div><div class="rta-kv">';
    Object.keys(ec).sort().forEach(k => {
      if (k === 'effective_caps') return;
      const v = ec[k];
      if (v === undefined || v === null || v === '') return;
      let disp = typeof v === 'object' ? JSON.stringify(v) : String(v);
      if (disp.length > 140) disp = disp.slice(0, 137) + '…';
      html += '<div class="rta-kv-row"><span>' + escapeHtml(k) + '</span><span style="text-align:right;word-break:break-all">' + escapeHtml(disp) + '</span></div>';
    });
    Object.keys(ecaps).sort().forEach(k => {
      const v = ecaps[k];
      if (v === undefined || v === null) return;
      let disp = typeof v === 'object' ? JSON.stringify(v) : String(v);
      html += '<div class="rta-kv-row"><span>cap:' + escapeHtml(k) + '</span><span style="text-align:right;word-break:break-all">' + escapeHtml(disp) + '</span></div>';
    });
    html += '</div>';
    if (d.model_routing && typeof d.model_routing === 'object') {
      html += '<div class="rta-section-title">Model routing</div><div class="rta-muted">' + escapeHtml(JSON.stringify(d.model_routing).slice(0, 400)) + '</div>';
    }
    el.innerHTML = html;
  } catch (_) {
    el.innerHTML = '<span style="color:#f90">Runtime options failed to load.</span>';
  }
}

async function refreshAgentsPanel() {
  const el = document.getElementById('agents-resource-panel');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const h = window.__laylaHealth || (window.__laylaHealth = { payload: null, lastFetch: 0, lastDeepFetch: 0, deepIntervalMs: 60000, inFlight: false, agentRequestActive: false, _inFlightPromise: null });
    let d = h.payload;
    const stale = !d || (Date.now() - (h.lastFetch || 0) > 8000);
    if (stale) d = await fetchHealthPayloadOnce();
    if (!d) {
      el.innerHTML = '<span style="color:#f90">Could not load <code>/health</code>. Is the server running?</span>';
      return;
    }
    const lim = d.effective_limits || {};
    const ec = d.effective_config || {};
    const caps = ec.effective_caps || {};
    const rows = [];
    function pushRow(k, v) {
      if (v === undefined || v === null || v === '') return;
      rows.push('<div class="rta-kv-row"><span>' + escapeHtml(k) + '</span><span>' + escapeHtml(String(v)) + '</span></div>');
    }
    pushRow('performance_mode', lim.performance_mode != null ? lim.performance_mode : ec.performance_mode);
    pushRow('max_active_runs', lim.max_active_runs != null ? lim.max_active_runs : ec.max_active_runs);
    pushRow('max_cpu_percent', lim.max_cpu_percent != null ? lim.max_cpu_percent : ec.max_cpu_percent);
    pushRow('max_ram_percent', lim.max_ram_percent != null ? lim.max_ram_percent : ec.max_ram_percent);
    pushRow('warn_cpu_percent', lim.warn_cpu_percent != null ? lim.warn_cpu_percent : ec.warn_cpu_percent);
    pushRow('hard_cpu_percent', lim.hard_cpu_percent != null ? lim.hard_cpu_percent : ec.hard_cpu_percent);
    pushRow('max_tool_calls', lim.max_tool_calls != null ? lim.max_tool_calls : caps.max_tool_calls);
    pushRow('max_runtime_seconds', lim.max_runtime_seconds != null ? lim.max_runtime_seconds : caps.max_runtime_seconds);
    pushRow('chat_light_max_runtime_seconds', lim.chat_light_max_runtime_seconds);
    pushRow('response_pacing_ms', ec.response_pacing_ms);
    const rl = d.resource_load;
    if (rl && typeof rl === 'object') {
      try {
        pushRow('resource_load', JSON.stringify(rl).slice(0, 120));
      } catch (_) {}
    }
    el.innerHTML = rows.length ? '<div class="rta-kv">' + rows.join('') + '</div>' : '<span style="color:var(--text-dim)">No resource fields in this /health payload.</span>';
  } catch (e) {
    el.innerHTML = '<span style="color:#f90">Failed to load agents snapshot.</span>';
  }
}

async function refreshVersionInfo() {
  const el = document.getElementById('app-version');
  if (!el) return;
  try {
    const r = await fetchWithTimeout('/version', {}, 12000);
    const d = await r.json();
    if (!r.ok || !d || !d.version) {
      el.textContent = 'Version: unknown';
      return;
    }
    el.textContent = 'Version: ' + d.version;
  } catch (_) {
    el.textContent = 'Version: unknown';
  }
}

async function checkForUpdates() {
  const el = document.getElementById('update-status');
  if (!el) return;
  el.textContent = 'Checking...';
  try {
    const r = await fetch('/update/check');
    const d = await r.json();
    if (!r.ok || !d.ok) {
      el.textContent = 'Update check failed.';
      return;
    }
    if (d.update_available) {
      const url = d.release_url ? ` <a href="${String(d.release_url).replace(/"/g, '&quot;')}" target="_blank" rel="noopener">release</a>` : '';
      el.innerHTML = `Update available: ${d.latest_version}.${url}`;
    } else {
      el.textContent = 'You are up to date.';
    }
  } catch (_) {
    el.textContent = 'Update check failed.';
  }
}

async function refreshPlatformModels() {
  const el = document.getElementById('platform-models');
  if (!el) return;
  el.innerHTML = '<div class="skeleton" style="height:12px;width:90%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:75%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:85%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:65%"></div>';
  try {
    const r = await fetchWithTimeout('/platform/models', {}, 12000);
    const d = await r.json();
    if (!r.ok) { el.innerHTML = '<span style="color:#f90">' + formatAgentError(r, d) + '</span>'; return; }
    let html = '';
    if (d.active) html += `<div style="margin-bottom:6px;color:var(--asp)">Active: ${d.active}</div>`;
    (d.models || []).forEach(m => {
      const bench = (d.benchmarks || {})[m.filename];
      const tps = bench?.tokens_per_sec;
      const benchStr = tps != null ? ` — ${tps.toFixed(1)} tok/s` : '';
      html += `<div style="padding:4px 0;border-bottom:1px solid var(--border)">${m.filename || ''} (${m.size_mb || 0} MB)${benchStr}</div>`;
    });
    if ((d.catalog || []).length) {
      html += '<div style="margin-top:10px;font-weight:600;color:var(--asp)">Catalog (jinx/dolphin/hermes/qwen)</div>';
      (d.catalog || []).slice(0, 6).forEach(m => {
        html += `<div style="padding:2px 0;font-size:0.65rem;color:var(--text-dim)">${m.family || ''} ${m.size || ''} — ${(m.desc || '').slice(0, 50)}…</div>`;
      });
    }
    if (!html) html = '<span style="color:var(--text-dim)">No models found</span>';
    el.innerHTML = html;
  } catch (e) { el.innerHTML = '<span style="color:#f90">Model list timed out or failed.</span>'; }
}

async function refreshKnowledgeIngestList() {
  const el = document.getElementById('km-ingest-list');
  if (!el) return;
  try {
    const r = await fetch('/knowledge/ingest/sources');
    const d = await r.json();
    const items = d.sources || [];
    if (!items.length) { el.textContent = 'No ingested sources yet.'; return; }
    el.innerHTML = items.map(s => `<div>${(s.name || '').replace(/</g, '&lt;')} <span style="opacity:0.7">(${s.entries || 0})</span></div>`).join('');
  } catch (_) { el.textContent = ''; }
}

async function runKnowledgeIngest() {
  const src = document.getElementById('km-source')?.value?.trim() || '';
  const label = document.getElementById('km-label')?.value?.trim() || '';
  if (!src) { alert('Enter a URL or folder path'); return; }
  try {
    const r = await fetch('/knowledge/ingest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: src, label }) });
    const d = await r.json();
    if (d.ok) alert('Ingest OK: ' + (d.path || '').slice(0, 120));
    else alert('Ingest failed: ' + (d.error || 'unknown'));
    refreshKnowledgeIngestList();
  } catch (e) { alert('Request failed'); }
}

async function refreshPlatformKnowledge() {
  const el = document.getElementById('platform-knowledge');
  if (!el) return;
  refreshKnowledgeIngestList();
  el.innerHTML = '<div class="skeleton" style="height:12px;width:85%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:70%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:80%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:60%"></div>';
  try {
    const r = await fetchWithTimeout('/platform/knowledge', {}, 12000);
    if (!r.ok) { el.innerHTML = '<span style="color:#f90">' + formatAgentError(r, {}) + '</span>'; return; }
    const d = await r.json();
    let html = '<div style="margin-bottom:8px;font-weight:600;color:var(--asp)">Summaries</div>';
    (d.summaries || []).forEach(s => { html += `<div style="padding:4px 0;font-size:0.68rem;border-bottom:1px solid var(--border)">${(s.summary||'').slice(0,100)}…</div>`; });
    html += '<div style="margin:10px 0 6px;font-weight:600;color:var(--asp)">Learnings</div>';
    (d.learnings || []).slice(0,5).forEach(l => { html += `<div style="padding:4px 0;font-size:0.68rem;border-bottom:1px solid var(--border)">[${l.type||'fact'}] ${(l.content||'').slice(0,80)}…</div>`; });
    html += '<div style="margin:10px 0 6px;font-weight:600;color:var(--asp)">Graph nodes</div>';
    (d.graph_nodes || []).slice(0,8).forEach(n => { html += `<div style="padding:2px 0;font-size:0.65rem;color:var(--text-dim)">${n.label||n.id||''}</div>`; });
    if (Object.keys(d.user_identity || {}).length) {
      html += '<div style="margin:10px 0 6px;font-weight:600;color:var(--asp)">User identity</div>';
      Object.entries(d.user_identity).forEach(([k,v]) => { if(v) html += `<div style="padding:2px 0;font-size:0.65rem">${k}: ${(v+'').slice(0,60)}…</div>`; });
    }
    if (!d.summaries?.length && !d.learnings?.length && !d.graph_nodes?.length && !Object.keys(d.user_identity||{}).length) html = '<span style="color:var(--text-dim)">No data yet</span>';
    el.innerHTML = html;
  } catch (e) { el.innerHTML = '<span style="color:#f90">Failed to load</span>'; }
}

async function refreshPlatformProjects() {
  const el = document.getElementById('platform-projects');
  if (!el) return;
  el.innerHTML = '<div class="skeleton" style="height:12px;width:88%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:72%"></div>';
  try {
    const r = await fetchWithTimeout('/platform/projects', {}, 12000);
    if (!r.ok) { el.innerHTML = '<span style="color:#f90">' + formatAgentError(r, {}) + '</span>'; return; }
    const d = await r.json();
    let html = '';
    if (d.project_name) html += `<div style="margin-bottom:6px;font-weight:600;color:var(--asp)">${d.project_name}</div>`;
    if (d.lifecycle_stage) html += `<div style="font-size:0.68rem;color:var(--text-dim)">Lifecycle: ${d.lifecycle_stage}</div>`;
    if (d.goals) html += `<div style="margin-top:6px;font-weight:600">Goals</div><div style="font-size:0.68rem;padding:4px 0">${(d.goals+'').slice(0,300)}</div>`;
    if (d.progress) html += `<div style="margin-top:6px;font-weight:600">Progress</div><div style="font-size:0.68rem;padding:4px 0">${(d.progress+'').slice(0,200)}</div>`;
    if (d.blockers) html += `<div style="margin-top:6px;font-weight:600">Blockers</div><div style="font-size:0.68rem;padding:4px 0;color:#f90">${(d.blockers+'').slice(0,200)}</div>`;
    if (d.last_discussed) html += `<div style="margin-top:6px;font-weight:600">Last discussed</div><div style="font-size:0.68rem;padding:4px 0">${(d.last_discussed+'').slice(0,200)}</div>`;
    if (!html) html = '<span style="color:var(--text-dim)">No project context set. Use update_project_context tool or POST /project_context.</span>';
    el.innerHTML = html;
  } catch (e) { el.innerHTML = '<span style="color:#f90">Failed to load</span>'; }
}

async function refreshPlatformTimeline() {
  const el = document.getElementById('platform-timeline');
  if (!el) return;
  el.innerHTML = '<div class="skeleton" style="height:12px;width:90%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:75%"></div>';
  try {
    const r = await fetchWithTimeout('/platform/knowledge', {}, 12000);
    if (!r.ok) { el.innerHTML = '<span style="color:#f90">' + formatAgentError(r, {}) + '</span>'; return; }
    const d = await r.json();
    const timeline = d.timeline || [];
    let html = '';
    timeline.forEach(t => {
      const ts = (t.timestamp || '').slice(0, 19).replace('T', ' ');
      html += `<div style="padding:6px 0;border-bottom:1px solid var(--border)"><span style="font-size:0.65rem;color:var(--text-dim)">[${t.event_type||''}] ${ts}</span><div style="font-size:0.68rem;margin-top:2px">${(t.content||'').slice(0,120)}…</div></div>`;
    });
    if (!html) html = '<span style="color:var(--text-dim)">No timeline events yet. Events are added when conversations are summarized.</span>';
    el.innerHTML = html;
  } catch (e) { el.innerHTML = '<span style="color:#f90">Failed to load</span>'; }
}

async function refreshPlatformPlugins() {
  const el = document.getElementById('platform-plugins');
  if (!el) return;
  el.innerHTML = '<div class="skeleton" style="height:12px;width:70%;margin-bottom:8px"></div><div class="skeleton" style="height:12px;width:55%"></div>';
  try {
    const r = await fetchWithTimeout('/platform/plugins', {}, 12000);
    if (!r.ok) { el.innerHTML = '<span style="color:#f90">' + formatAgentError(r, {}) + '</span>'; return; }
    const d = await r.json();
    let html = `<div>Skills added: ${d.skills_added || 0}</div>`;
    html += `<div>Tools added: ${d.tools_added || 0}</div>`;
    if (d.errors?.length) html += `<div style="color:#f90;margin-top:6px">Errors: ${d.errors.join('; ')}</div>`;
    if (d.skills?.length) {
      html += '<div style="margin-top:8px;font-weight:600;color:var(--asp)">Skills</div>';
      d.skills.forEach(s => { html += `<div style="font-size:0.68rem;padding:2px 0">${s.name||''}</div>`; });
    }
    el.innerHTML = html;
  } catch (e) { el.innerHTML = '<span style="color:#f90">Plugin scan timed out or failed.</span>'; }
}

async function addStudyPlan() {
  const input = document.getElementById('study-input');
  const topic = input.value.trim();
  if (!topic) return;
  input.value = '';
  await fetch('/study_plans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic }),
  });
  refreshStudyPlans();
}

async function doWakeup() {
  try {
    const res = await fetch('/wakeup');
    const data = await res.json();
    if (data.greeting) {
      const chat = document.getElementById('chat');
      if (!chat) return;
      const banner = document.createElement('div');
      banner.className = 'greeting-banner';
      banner.innerHTML = '<div class="from">— Echo (session start)</div>' + sanitizeHtml(data.greeting || '');
      chat.appendChild(banner);
    }
    refreshStudyPlans();
  } catch (e) { console.warn('doWakeup failed:', e); }
}

// Session timer
setInterval(() => {
  const elapsed = Math.floor((Date.now() - sessionStart) / 1000);
  const m = Math.floor(elapsed / 60).toString().padStart(2,'0');
  const s = (elapsed % 60).toString().padStart(2,'0');
  document.getElementById('session-time').textContent = m + ':' + s;
}, 1000);

// ─── localStorage: persist workspace path + presets + autocomplete ────────
const WS_KEY = 'layla_workspace_path';
const WS_PRESETS_KEY = 'layla_workspace_presets';
const WS_RECENT_KEY = 'layla_workspace_recent';
const WS_RECENT_MAX = 8;
function getWorkspacePresets() {
  try { return JSON.parse(localStorage.getItem(WS_PRESETS_KEY) || '[]'); } catch (_) { return []; }
}
function setWorkspacePresets(arr) {
  localStorage.setItem(WS_PRESETS_KEY, JSON.stringify(arr));
  renderWorkspacePresets();
}
function renderWorkspacePresets() {
  const sel = document.getElementById('workspace-presets');
  if (!sel) return;
  const presets = getWorkspacePresets();
  sel.innerHTML = '<option value="">— Preset —</option>' + presets.map((p, i) => '<option value="' + i + '">' + escapeHtml((p.name || p.path || 'Preset').slice(0, 30)) + '</option>').join('');
}
function onWorkspacePresetSelect() {
  const sel = document.getElementById('workspace-presets');
  const wp = document.getElementById('workspace-path');
  if (!sel || !wp) return;
  const idx = sel.value;
  if (idx === '') return;
  const presets = getWorkspacePresets();
  const p = presets[parseInt(idx, 10)];
  if (p && p.path) { wp.value = p.path; localStorage.setItem(WS_KEY, p.path); }
}
function addWorkspacePreset() {
  const wp = document.getElementById('workspace-path');
  if (!wp) return;
  const path = wp.value.trim();
  if (!path) { showToast('Enter a path first'); return; }
  const presets = getWorkspacePresets();
  const name = path.split(/[/\\]/).pop() || path.slice(-20);
  presets.push({ name, path });
  setWorkspacePresets(presets);
  showToast('Preset added');
}
function removeWorkspacePreset() {
  const sel = document.getElementById('workspace-presets');
  if (!sel || sel.value === '') { showToast('Select a preset to remove'); return; }
  const presets = getWorkspacePresets();
  presets.splice(parseInt(sel.value, 10), 1);
  setWorkspacePresets(presets);
  sel.value = '';
  showToast('Preset removed');
}
const wpEl = document.getElementById('workspace-path');
if (wpEl) {
  renderWorkspacePresets();
  const saved = localStorage.getItem(WS_KEY);
  if (saved) wpEl.value = saved;
  wpEl.addEventListener('input', () => {
    if (typeof refreshOptionDependencies === 'function') refreshOptionDependencies();
  });
  wpEl.addEventListener('change', () => {
    const v = wpEl.value.trim();
    if (v) {
      localStorage.setItem(WS_KEY, v);
      try {
        let recent = JSON.parse(localStorage.getItem(WS_RECENT_KEY) || '[]');
        recent = [v, ...recent.filter(p => p !== v)].slice(0, WS_RECENT_MAX);
        localStorage.setItem(WS_RECENT_KEY, JSON.stringify(recent));
      } catch (_) {}
    }
  });
  try {
    const recent = JSON.parse(localStorage.getItem(WS_RECENT_KEY) || '[]');
    if (recent.length) {
      const dl = document.createElement('datalist');
      dl.id = 'workspace-datalist';
      recent.forEach(p => { const o = document.createElement('option'); o.value = p; dl.appendChild(o); });
      wpEl.setAttribute('list', 'workspace-datalist');
      wpEl.parentNode?.appendChild(dl);
    }
  } catch (_) {}
}
document.getElementById('show-thinking')?.addEventListener('change', () => {
  if (typeof refreshOptionDependencies === 'function') refreshOptionDependencies();
});
document.getElementById('workspace-presets')?.addEventListener('change', () => {
  if (typeof refreshOptionDependencies === 'function') refreshOptionDependencies();
});
if (typeof refreshOptionDependencies === 'function') refreshOptionDependencies();

// ─── localStorage: persist conversation history ─────────────
const HISTORY_KEY = 'layla_chat_history';
const MAX_HISTORY_ENTRIES = 40;
let _saveHistoryTimer = null;

function saveChatHistory() {
  if (_saveHistoryTimer) clearTimeout(_saveHistoryTimer);
  _saveHistoryTimer = setTimeout(() => {
    _saveHistoryTimer = null;
    try {
      const chat = document.getElementById('chat');
      if (!chat) return;
      const entries = [];
      for (const node of chat.children) {
        if (node.classList.contains('msg') || node.classList.contains('separator') || node.classList.contains('greeting-banner')) {
          entries.push({ html: node.outerHTML, cls: node.className });
        }
      }
      const trimmed = entries.slice(-MAX_HISTORY_ENTRIES);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed));
    } catch (e) { console.warn('saveChatHistory failed:', e); }
  }, 400);
}

function loadChatHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return;
    const entries = JSON.parse(raw);
    const chat = document.getElementById('chat');
    if (!chat || !entries.length) return;
    const frag = document.createDocumentFragment();
    entries.forEach(e => {
      const tmp = document.createElement('div');
      tmp.innerHTML = sanitizeHtml(e.html || '');
      if (tmp.firstChild) frag.appendChild(tmp.firstChild);
    });
    chat.insertBefore(frag, chat.firstChild);
    chat.scrollTop = chat.scrollHeight;
    hideEmpty();
  } catch (e) { console.warn('loadChatHistory failed:', e); }
}

// Attach history save observer
const chatObserver = new MutationObserver(() => saveChatHistory());
const chatEl2 = document.getElementById('chat');
if (chatEl2) chatObserver.observe(chatEl2, { childList: true, subtree: false });

// ─── Clear chat ─────────────────────────────────────────────
function updateToolStatus(toolName, containerEl) {
  const wrap = containerEl || document.getElementById('typing-wrap');
  if (!wrap) return;
  let statusEl = wrap.querySelector('.tool-status-label');
  if (!statusEl) {
    statusEl = document.createElement('div');
    statusEl.className = 'tool-status-label';
    wrap.querySelector('.msg-bubble')?.appendChild(statusEl);
  }
  const TOOL_LABELS = {
    ddg_search: 'Searching the web…', web_search: 'Searching the web…',
    fetch_article: 'Fetching article…', fetch_url: 'Fetching page…',
    wiki_search: 'Searching Wikipedia…', arxiv_search: 'Searching arXiv…',
    read_file: 'Reading file…', write_file: 'Writing file…',
    list_dir: 'Listing directory…', git_status: 'Checking git…',
    git_diff: 'Reading diff…', run_python: 'Running Python…',
    shell: 'Running command…', apply_patch: 'Applying patch…',
    search_memories: 'Searching memory…', save_note: 'Saving to memory…',
    vector_search: 'Semantic search…', code_symbols: 'Indexing symbols…',
    workspace_map: 'Mapping workspace…', dependency_graph: 'Building graph…',
    dataset_summary: 'Analyzing data…', cluster_data: 'Clustering…',
    ocr_image: 'Reading image…', describe_image: 'Captioning image…',
    plot_chart: 'Generating chart…', scipy_compute: 'Computing…',
    sql_query: 'Querying database…', schema_introspect: 'Reading schema…',
    geo_query: 'Geocoding…', crypto_prices: 'Fetching prices…',
    detect_objects: 'Detecting objects…', extract_frames: 'Extracting frames…',
    stt_file: 'Transcribing audio…', tts_speak: 'Synthesizing speech…',
    schedule_task: 'Scheduling task…', code_metrics: 'Measuring code…',
    code_lint: 'Linting code…', summarize_text: 'Summarizing…',
    translate_text: 'Translating…', classify_text: 'Classifying…',
    extract_entities: 'Extracting entities…', sentiment_timeline: 'Analyzing sentiment…',
  };
  statusEl.textContent = TOOL_LABELS[toolName] || ('Running ' + toolName + '…');
}

function clearToolStatus(containerEl) {
  const wrap = containerEl || document.getElementById('typing-wrap');
  if (wrap) wrap.querySelector('.tool-status-label')?.remove();
}

function updateRetryButton() {
  const btn = document.getElementById('retry-btn');
  if (btn) btn.style.display = _lastDisplayMsg ? 'inline-block' : 'none';
}

function clearChat() {
  if (!confirm('Clear all messages? This cannot be undone.')) return;
  _lastDisplayMsg = null;
  updateRetryButton();
  _saveCurrentSession();
  const chat = document.getElementById('chat');
  if (chat) {
    chat.innerHTML = '';
    const empty = document.createElement('div');
    empty.id = 'chat-empty';
    empty.innerHTML = renderPromptTilesAndEmptyState();
    chat.appendChild(empty);
  }
  localStorage.removeItem(HISTORY_KEY);
}

// ─── Copy-to-clipboard on message click ─────────────────────
const chatEl = document.getElementById('chat');
if (chatEl) chatEl.addEventListener('click', (e) => {
  const bubble = e.target.closest('.msg-bubble');
  if (!bubble) return;
  if (e.target.closest('button') || e.target.closest('a')) return;
  const text = bubble.innerText || bubble.textContent || '';
  if (!text.trim()) return;
  navigator.clipboard.writeText(text.trim()).then(() => {
    bubble.style.outline = '1px solid var(--asp)';
    bubble.style.boxShadow = '0 0 12px var(--asp-glow)';
    setTimeout(() => { bubble.style.outline = ''; bubble.style.boxShadow = ''; }, 600);
  }).catch(() => {});
});

// ─── File drop + attach ───────────────────────────────────────────────────
let _attachedFiles = [];  // [{name, content}]
let _attachedImages = []; // [{name, base64}] for image context in agent loop

function handleFileDrop(e) {
  e.preventDefault();
  document.getElementById('input-area-drop').style.borderColor = '';
  const files = e.dataTransfer?.files;
  if (files && files.length) {
    Array.from(files).forEach(f => readFileIntoContext(f));
  }
}

function attachFile(input) {
  if (input.files && input.files.length) {
    Array.from(input.files).forEach(f => readFileIntoContext(f));
    input.value = '';
  }
}

function readFileIntoContext(file) {
  const TEXT_EXTS = /\.(txt|md|py|js|ts|jsx|tsx|html|css|json|yaml|yml|toml|ini|cfg|sh|bat|ps1|c|cpp|h|rs|go|java|rb|php|sql|xml|csv|log)$/i;
  const IMAGE_EXTS = /\.(png|jpg|jpeg|webp|gif|bmp)$/i;
  const MAX_SIZE = 200 * 1024; // 200 KB (text)
  const MAX_IMAGE_SIZE = 4 * 1024 * 1024; // 4 MB for images
  if (IMAGE_EXTS.test(file.name)) {
    if (file.size > MAX_IMAGE_SIZE) {
      showToast(`Image too large: ${file.name} (max 4 MB)`);
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      const dataUrl = ev.target.result;
      _attachedImages.push({ name: file.name, base64: dataUrl });
      const chips = document.getElementById('file-context-chips');
      if (chips) {
        chips.style.display = 'flex';
        const chip = document.createElement('span');
        chip.style.cssText = 'background:var(--asp-mid);border:1px solid var(--asp);border-radius:12px;padding:2px 10px;color:var(--text);display:flex;align-items:center;gap:6px';
        chip.setAttribute('data-image-chip', '1');
        chip.dataset.type = 'image';
        chip.dataset.filename = file.name;
        chip.innerHTML = `🖼 ${escapeHtml(file.name)} <button class="chip-remove-btn" style="background:none;border:none;color:var(--text-dim);cursor:pointer;padding:0;font-size:0.85rem">✕</button>`;
        chips.appendChild(chip);
      }
      showToast(`🖼 ${file.name} attached (image context)`);
      toggleSendButton();
    };
    reader.readAsDataURL(file);
    return;
  }
  if (file.size > MAX_SIZE) {
    showToast(`File too large: ${file.name} (max 200 KB)`);
    return;
  }
  const reader = new FileReader();
  reader.onload = (e) => {
    const content = e.target.result;
    _attachedFiles.push({ name: file.name, content });
    const chips = document.getElementById('file-context-chips');
    if (chips) {
      chips.style.display = 'flex';
      const chip = document.createElement('span');
      chip.style.cssText = 'background:var(--asp-mid);border:1px solid var(--asp);border-radius:12px;padding:2px 10px;color:var(--text);display:flex;align-items:center;gap:6px';
      chip.dataset.type = 'file';
      chip.dataset.filename = file.name;
      chip.innerHTML = `📄 ${escapeHtml(file.name)} <button class="chip-remove-btn" style="background:none;border:none;color:var(--text-dim);cursor:pointer;padding:0;font-size:0.85rem">✕</button>`;
      chips.appendChild(chip);
    }
    showToast(`📄 ${file.name} attached`);
    toggleSendButton();
  };
  if (TEXT_EXTS.test(file.name)) {
    reader.readAsText(file, 'utf-8');
  } else {
    showToast(`Unsupported file type: ${file.name}. Text or image files only.`);
  }
}

function removeImageChip(chip) {
  const filename = chip?.dataset?.filename || '';
  _attachedImages = _attachedImages.filter(f => f.name !== filename);
  chip?.remove();
  if (!_attachedImages.length && !_attachedFiles.length) {
    const chips = document.getElementById('file-context-chips');
    if (chips) chips.style.display = 'none';
  }
  toggleSendButton();
}

function removeFileChip(chip) {
  const filename = chip?.dataset?.filename || '';
  _attachedFiles = _attachedFiles.filter(f => f.name !== filename);
  chip?.remove();
  if (!_attachedFiles.length && !_attachedImages.length) {
    const chips = document.getElementById('file-context-chips');
    if (chips) chips.style.display = 'none';
  }
  toggleSendButton();
}

// Delegated handler for file-context chip remove buttons (avoids XSS from filename/url in onclick)
const fileChipsEl = document.getElementById('file-context-chips');
if (fileChipsEl) {
  fileChipsEl.addEventListener('click', (e) => {
    const btn = e.target.closest('.chip-remove-btn');
    if (!btn) return;
    const chip = btn.closest('[data-type]');
    if (!chip) return;
    if (chip.dataset.type === 'image') removeImageChip(chip);
    else if (chip.dataset.type === 'file') removeFileChip(chip);
  });
}

// ─── Inline approvals ───────────────────────────────────────────────────────
async function batchApproveAll(pending, btnEl) {
  if (!btnEl) return;
  btnEl.disabled = true;
  btnEl.textContent = 'Approving…';
  let ok = 0;
  for (const e of pending) {
    try {
      const res = await fetch('/approve', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ id: e.id }) });
      const data = await res.json();
      if (data.ok || res.ok) ok++;
    } catch (_) {}
  }
  showToast('Approved ' + ok + ' of ' + pending.length);
  refreshApprovals();
}
async function approveAction(id, btnEl) {
  const tool = btnEl?.dataset?.tool || '';
  try {
    const res = await fetch('/approve', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ id }) });
    const data = await res.json();
    if (data.ok || res.ok) {
      btnEl.textContent = '✓ Approved';
      btnEl.style.background = '#0a3';
      btnEl.style.color = '#fff';
      btnEl.disabled = true;
      btnEl.closest('.inline-approval')?.classList.add('approved');
      const canUndo = (tool === 'write_file' || tool === 'apply_patch');
      if (canUndo) {
        const t = document.createElement('div');
        t.className = 'toast';
        t.innerHTML = 'Approved. <a href="#" class="undo-link" data-undo-id="' + escapeHtml(id) + '" style="color:var(--asp);text-decoration:underline;margin-left:4px">Undo</a>';
        document.body.appendChild(t);
        t.querySelector('.undo-link')?.addEventListener('click', (ev) => {
          ev.preventDefault();
          const uid = ev.target.dataset?.undoId;
          if (uid) fetch('/undo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: uid }) });
          t.remove();
        });
        setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; setTimeout(() => t.remove(), 300); }, 5000);
      } else {
        showToast('Action approved — Layla will continue');
      }
      refreshApprovals();
    }
  } catch(e) { showToast('Approval failed: ' + e.message); }
}

let _lastPendingCount = 0;
// Override refreshApprovals to also inject inline approval cards
async function refreshApprovals() {
  try {
    const res = await fetchWithTimeout('/pending', {}, 10000);
    const data = await res.json();
    const list = document.getElementById('approvals-list');
    const pending = (data.pending || []).filter(e => e.status === 'pending');
    if (_lastPendingCount === 0 && pending.length > 0) showToast('🔐 Approval needed — check Approvals panel or inline');
    _lastPendingCount = pending.length;
    if (!pending.length) {
      if (list) list.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">Layla will ask here when she needs permission to act</span>';
      return;
    }
    if (list) {
      list.innerHTML = '';
      if (pending.length > 1) {
        const batchBtn = document.createElement('button');
        batchBtn.className = 'approve-btn';
        batchBtn.style.cssText = 'margin-bottom:10px;font-size:0.72rem;padding:6px 14px;background:var(--asp);border:none;color:#fff;border-radius:3px;cursor:pointer';
        batchBtn.textContent = '✓ Approve all (' + pending.length + ')';
        batchBtn.onclick = () => batchApproveAll(pending, batchBtn);
        list.appendChild(batchBtn);
      }
      pending.forEach(e => {
        const item = document.createElement('div');
        item.className = 'panel-item';
        const btn = document.createElement('button');
        btn.style.cssText = 'font-size:0.72rem;padding:4px 12px;background:transparent;border:1px solid var(--asp);color:var(--asp);border-radius:3px;cursor:pointer';
        btn.textContent = 'Approve';
        btn.dataset.id = e.id || '';
        btn.dataset.tool = e.tool || '';
        btn.onclick = () => approveAction(btn.dataset.id, btn);
        item.innerHTML = `<div style="font-size:0.73rem;margin-bottom:6px;color:var(--text)">${escapeHtml(e.tool || '')} <span style="opacity:0.4">${escapeHtml((e.id||'').slice(0,8))}</span></div>`;
        item.appendChild(btn);
        list.appendChild(item);
      });
    }
    // Inject inline into last Layla message
    const chat = document.getElementById('chat');
    if (!chat) return;
    // Remove old inline approval cards first
    chat.querySelectorAll('.inline-approval').forEach(el => el.remove());
    const lastLayla = [...chat.querySelectorAll('.msg-layla')].pop();
    if (lastLayla && pending.length > 0) {
      const inlineWrap = document.createElement('div');
      inlineWrap.className = 'inline-approval';
      inlineWrap.style.cssText = 'margin:6px 0 0 0;display:flex;flex-direction:column;gap:6px';
      pending.forEach(e => {
        const card = document.createElement('div');
        card.style.cssText = 'background:rgba(139,0,0,0.08);border:1px solid var(--asp);border-radius:6px;padding:10px 14px;font-size:0.78rem;display:flex;align-items:center;gap:12px;flex-wrap:wrap';
        card.innerHTML = `<span style="flex:1">🔐 <b>${escapeHtml(e.tool||'action')}</b> needs approval${e.args ? ' — ' + escapeHtml(JSON.stringify(e.args)).slice(0,80) : ''}</span>`;
        const appBtn = document.createElement('button');
        appBtn.style.cssText = 'padding:5px 16px;background:var(--asp);border:none;color:#fff;border-radius:4px;cursor:pointer;font-family:inherit;font-size:0.78rem';
        appBtn.textContent = 'Approve';
        appBtn.dataset.id = e.id || '';
        appBtn.dataset.tool = e.tool || '';
        appBtn.onclick = () => approveAction(appBtn.dataset.id, appBtn);
        card.appendChild(appBtn);
        inlineWrap.appendChild(card);
      });
      lastLayla.appendChild(inlineWrap);
      chat.scrollTop = chat.scrollHeight;
    }
  } catch (e) { console.warn('refreshApprovals failed:', e); }
}

// ─── Inject file context into send payload ─────────────────────────────────
// Wrap original send() to prepend file context to message
(function () {
  // Capture original send from a stable place (window). Fallback to any existing `send`.
  const _origSend = (typeof window !== "undefined" && window.send) || (typeof send !== "undefined" ? send : null);
  if (!_origSend) {
    // If there's no original send (unexpected), don't overwrite anything.
    return;
  }

  // Replace the global/send function with a safe wrapper that preserves `this` and args.
  _dbg('window.send wrapper installed');
  window.send = async function (...args) {
    if (_attachedFiles.length > 0) {
      const input = document.getElementById("msg-input");
      if (input && input.value.trim()) {
        const ctx = _attachedFiles
          .map(
            (f) =>
              `[Context from ${f.name}]:\n\`\`\`\n${f.content.slice(0, 4000)}\n\`\`\``,
          )
          .join("\n\n");
        input.value = ctx + "\n\n" + input.value;
        _attachedFiles = [];
        const chips = document.getElementById("file-context-chips");
        if (chips) {
          chips.innerHTML = "";
          chips.style.display = "none";
        }
      }
    }
    // Call the original with the same `this` and arguments.
    return _origSend.apply(this, args);
  };
})();


// ─── Unified /health poller (status bar, platform panel, connection) ────────
// window.__laylaHealth initialized at top of this script (before any refresh calls).

// Cross-tab /health freshness: other tabs' fetches update this tab's header without waiting for poll.
(function laylaInitHealthBroadcastChannel() {
  try {
    if (typeof BroadcastChannel === 'undefined') return;
    const ch = new BroadcastChannel('layla-health-v1');
    window.__laylaHealthChannel = ch;
    ch.onmessage = function (ev) {
      try {
        const m = ev.data;
        if (!m || m.type !== 'layla-health' || typeof m.ts !== 'number' || !m.payload) return;
        const h = window.__laylaHealth;
        if (m.ts <= (h.lastFetch || 0)) return;
        h.payload = m.payload;
        h.lastFetch = m.ts;
        if (typeof m.lastDeepFetch === 'number') h.lastDeepFetch = m.lastDeepFetch;
        laylaApplyHeaderStatusFromHealth(m.payload);
      } catch (_) {}
    };
  } catch (_) {}
})();

function laylaFormatDepsShort(deps) {
  if (!deps || typeof deps !== 'object') return '';
  const p = [];
  const c = deps.chroma;
  if (c) p.push('ch:' + (c === 'ok' ? '✓' : c === 'missing' ? '—' : '!'));
  const st = deps.voice_stt;
  const tt = deps.voice_tts;
  if (st || tt) p.push('voc:' + (st === 'ok' ? '↤' : '·') + (tt === 'ok' ? '↦' : '·'));
  const tst = deps.tree_sitter;
  if (tst) p.push('ts:' + (tst === 'ok' ? '✓' : '—'));
  return p.length ? (' · ' + p.join(' ')) : '';
}

function laylaApplyHeaderStatusFromHealth(d) {
  const hs = document.getElementById('header-system-status');
  if (!hs || !d) return;
  laylaApplyUiTimeoutsFromHealth(d);
  const ok = d.status === 'ok';
  const ki = d.knowledge_index_ready === true ? ' · idx✓' : d.knowledge_index_ready === false ? ' · idx…' : '';
  const model = (d.active_model || '').replace(/</g, '');
  const ml = d.model_loaded ? '●' : '○';
  const pm = (d.effective_limits && d.effective_limits.performance_mode != null)
    ? String(d.effective_limits.performance_mode)
    : '';
  const deps = laylaFormatDepsShort(d.dependencies);
  const busy = window.__laylaHealth.agentRequestActive ? ' · agent…' : '';
  let line = (ok ? '●' : '○') + ' ' + (d.status || 'unknown') + ki;
  if (model) line += ' · ' + model;
  if (pm) line += ' · pm:' + pm;
  line += ' · ' + ml + 'llm' + deps + busy;
  hs.textContent = line;
  hs.style.color = ok ? '#6dcea0' : '#e8a030';
}

function setHeaderAgentActivity(on) {
  window.__laylaHealth.agentRequestActive = !!on;
  const d = window.__laylaHealth.payload;
  if (d) laylaApplyHeaderStatusFromHealth(d);
}

async function fetchHealthPayloadOnce() {
  const h = window.__laylaHealth;
  if (h._inFlightPromise) return h._inFlightPromise;
  h._inFlightPromise = (async () => {
    const now = Date.now();
    h.inFlight = true;
    try {
      const useDeep = !h.lastDeepFetch || (now - h.lastDeepFetch >= h.deepIntervalMs);
      const url = useDeep ? '/health?deep=true' : '/health';
      const r = await fetchWithTimeout(url, {}, 12000);
      let d = null;
      try {
        d = await r.json();
      } catch (_) {
        d = null;
      }
      if (!r.ok) {
        h.lastFetch = now;
        if (h.payload) {
          try { laylaApplyHeaderStatusFromHealth(h.payload); } catch (_) {}
        }
        return h.payload != null ? h.payload : null;
      }
      if (useDeep) h.lastDeepFetch = now;
      h.payload = d;
      h.lastFetch = now;
      try {
        const bc = window.__laylaHealthChannel;
        if (bc && typeof bc.postMessage === 'function') {
          bc.postMessage({
            type: 'layla-health',
            ts: now,
            payload: d,
            lastDeepFetch: h.lastDeepFetch,
          });
        }
      } catch (_) {}
      try {
        laylaApplyHeaderStatusFromHealth(d);
      } catch (_) {}
      return d;
    } catch (_) {
      return h.payload;
    } finally {
      h.inFlight = false;
      h._inFlightPromise = null;
    }
  })();
  return h._inFlightPromise;
}

// ─── Warmup bar ─────────────────────────────────────────────────────────────
let _warmupDone = false;
let _connectionOk = true;
async function pollWarmup() {
  try {
    const d = await fetchHealthPayloadOnce();
    if (!d) throw new Error('health empty');
    _connectionOk = true;
    document.getElementById('connection-banner')?.style.setProperty('display', 'none');
    try {
      const cs = d.cache_stats;
      const cb = document.getElementById('cache-stats-badge');
      if (cb && cs && typeof cs.hits === 'number' && typeof cs.misses === 'number') {
        const tot = cs.hits + cs.misses;
        const show = (typeof localStorage !== 'undefined' && localStorage.getItem('layla_show_cache_stats') === '1');
        if (show && tot > 0) {
          const pct = Math.round((cs.hit_ratio != null ? cs.hit_ratio : (cs.hits / tot)) * 100);
          cb.textContent = 'Cache: ' + pct + '% hit';
          cb.style.display = '';
        } else {
          cb.style.display = 'none';
        }
      }
    } catch (_) {}
    if (_warmupDone) return;
    if (d.model_loaded) {
      _warmupDone = true;
      document.getElementById('model-readiness-banner')?.style.setProperty('display', 'none');
      const bar = document.getElementById('warmup-bar');
      if (bar) { bar.style.transition = 'opacity 0.5s'; bar.style.opacity = '0'; setTimeout(() => bar.remove(), 600); }
      const badge = document.getElementById('model-status-badge');
      if (badge && !badge.textContent.startsWith('●')) {
        badge.textContent = '● model ready'; badge.style.color = '#4dff88';
      }
      return;
    }
    const detail = document.getElementById('warmup-detail');
    const modelBanner = document.getElementById('model-readiness-banner');
    try {
      const setupRes = await fetchWithTimeout('/setup_status', {}, 12000);
      if (setupRes.ok) {
        const setup = await setupRes.json();
        if (!setup.ready) {
          if (detail) detail.textContent = 'No model configured';
          if (modelBanner) {
            const err = (d.model_error || '').replace(/</g, '&lt;');
            modelBanner.innerHTML = 'No model loaded' + (err ? ' — ' + err + '. ' : ' — ') + '<a href="/docs/MODELS.md" target="_blank" style="color:#e0a0ff;text-decoration:underline">Configure</a> or run first setup';
            modelBanner.style.display = 'block';
          }
        } else {
          if (modelBanner) modelBanner.style.display = 'none';
          if (detail) detail.textContent = d.detail || 'warming up…';
        }
      } else {
        if (detail) detail.textContent = d.detail || 'warming up…';
        if (modelBanner) modelBanner.style.display = 'none';
      }
    } catch (_) {
      if (detail) detail.textContent = d.detail || 'warming up…';
      if (modelBanner) modelBanner.style.display = 'none';
    }
  } catch {
    _connectionOk = false;
    document.getElementById('connection-banner')?.style.setProperty('display', 'block');
    document.getElementById('model-readiness-banner')?.style.setProperty('display', 'none');
    try {
      const hs = document.getElementById('header-system-status');
      if (hs) { hs.textContent = '○ offline'; hs.style.color = '#f90'; }
    } catch (_) {}
  }
  setTimeout(pollWarmup, _warmupDone ? 10000 : 3000);
}
function pollConnectionStatus() {
  if (_warmupDone) {
    const d = window.__laylaHealth.payload;
    if (d && d.status) {
      _connectionOk = true;
      document.getElementById('connection-banner')?.style.setProperty('display', 'none');
    } else {
      fetchHealthPayloadOnce().then((dd) => {
        if (dd && dd.status) {
          _connectionOk = true;
          laylaApplyHeaderStatusFromHealth(dd);
          document.getElementById('connection-banner')?.style.setProperty('display', 'none');
        }
      }).catch(() => {
        _connectionOk = false;
        document.getElementById('connection-banner')?.style.setProperty('display', 'block');
      });
    }
  }
  setTimeout(pollConnectionStatus, 10000);
}
function startWarmupPoll() {
  const bar = document.getElementById('warmup-bar');
  if (bar) bar.classList.add('visible');
  pollWarmup();
}
// Start polling immediately; checkSetupStatus will also fire — warmup supplements it
startWarmupPoll();
setTimeout(pollConnectionStatus, 15000);
// ─── URL auto-detect chip ────────────────────────────────────────────────────
const URL_RE = /https?:\/\/[^\s"'<>]+/i;
let _detectedUrl = '';
let _urlFetchDismissed = false;

function _checkUrlInInput(val) {
  const m = val.match(URL_RE);
  const chip = document.getElementById('url-detect-chip');
  if (!chip) return;
  if (m && !_urlFetchDismissed) {
    _detectedUrl = m[0];
    const domain = (new URL(_detectedUrl)).hostname;
    const domEl = document.getElementById('url-chip-domain');
    if (domEl) domEl.textContent = domain;
    chip.classList.add('visible');
  } else if (!m) {
    chip.classList.remove('visible');
    _detectedUrl = '';
    _urlFetchDismissed = false;
  }
}

function dismissUrlChip() {
  _urlFetchDismissed = true;
  document.getElementById('url-detect-chip')?.classList.remove('visible');
}

function acceptUrlFetch() {
  if (!_detectedUrl) return;
  const chip = document.getElementById('url-detect-chip');
  if (chip) { chip.classList.remove('visible'); chip.innerHTML = '<span class="url-chip-label">Fetching <b id="url-chip-domain2"></b>…</span>'; chip.classList.add('visible'); }
  const url = _detectedUrl;
  _detectedUrl = '';
  _fetchUrlAsContext(url);
}

async function _fetchUrlAsContext(url) {
  const chip = document.getElementById('url-detect-chip');
  try {
    const r = await fetch('/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'fetch_url_only: ' + url, tool_only: 'fetch_article', url }),
    });
    const d = await r.json();
    const content = d.response || d.result || '';
    if (content) {
      _attachedFiles.push({ name: url, content: content.slice(0, 6000) });
      const chips = document.getElementById('file-context-chips');
      if (chips) {
        chips.style.display = 'flex';
        const chip2 = document.createElement('span');
        chip2.style.cssText = 'background:var(--asp-mid);border:1px solid var(--asp);border-radius:12px;padding:2px 10px;color:var(--text);display:flex;align-items:center;gap:6px;font-size:0.73rem';
        const hostname = (() => { try { return new URL(url).hostname; } catch { return url.slice(0,30); } })();
        chip2.dataset.type = 'file';
        chip2.dataset.filename = url;
        chip2.innerHTML = `🌐 ${escapeHtml(hostname)} <button class="chip-remove-btn" style="background:none;border:none;color:var(--text-dim);cursor:pointer;padding:0;font-size:0.85rem">✕</button>`;
        chips.appendChild(chip2);
      }
      showToast('🌐 URL content fetched');
    }
  } catch(e) {
    showToast('Could not fetch URL content');
  }
  if (chip) chip.classList.remove('visible');
}

// ─── Apply to file + diff viewer ─────────────────────────────────────────────
let _diffPending = { filepath: '', newContent: '' };

function _detectFilename(codeEl) {
  // Check prev sibling heading for filename hint
  const pre = codeEl.closest('pre');
  const wrap = pre?.parentElement;
  // Look at the text node / p just before the pre
  let prev = pre?.previousElementSibling;
  while (prev) {
    const t = prev.textContent?.trim();
    if (t && /\.(py|js|ts|jsx|tsx|html|css|json|yaml|yml|toml|ini|cfg|sh|bat|ps1|c|cpp|h|rs|go|java|md|txt|sql|xml)$/i.test(t.split(/\s/).pop())) {
      return t.split(/\s/).pop();
    }
    prev = prev.previousElementSibling;
  }
  // Check first comment line in code
  const lines = (codeEl.textContent || '').split('\n');
  const first = lines[0]?.trim();
  if (first) {
    const commentMatch = first.match(/^(?:#|\/\/|<!--|--)\s*([^\s]+\.(py|js|ts|jsx|tsx|html|css|json|yaml|yml|sh|bat|ps1|c|cpp|h|rs|go|java|md|sql|xml))/i);
    if (commentMatch) return commentMatch[1];
  }
  return null;
}

function _addApplyBtnToCodeBlock(wrap, codeEl) {
  const filename = _detectFilename(codeEl);
  if (!filename) return;
  const btn = document.createElement('button');
  btn.className = 'apply-btn';
  btn.textContent = 'apply';
  btn.title = 'Apply to ' + filename;
  btn.onclick = () => openDiffViewer(filename, codeEl.textContent || '');
  wrap.appendChild(btn);
}

async function openDiffViewer(filepath, newContent) {
  _diffPending = { filepath, newContent };
  document.getElementById('diff-filepath').textContent = filepath;
  // Fetch current file
  let currentContent = '';
  try {
    const r = await fetch('/file_content?path=' + encodeURIComponent(filepath));
    const d = await r.json();
    currentContent = d.content || '';
  } catch { currentContent = ''; }
  // Render unified diff
  _renderDiff(currentContent, newContent);
  document.getElementById('diff-overlay').classList.add('visible');
}

function closeDiffViewer() {
  document.getElementById('diff-overlay').classList.remove('visible');
  _diffPending = { filepath: '', newContent: '' };
}

function _renderDiff(oldText, newText) {
  const oldLines = oldText.split('\n');
  const newLines = newText.split('\n');
  const leftEl = document.getElementById('diff-left-content');
  const rightEl = document.getElementById('diff-right-content');
  leftEl.innerHTML = '';
  rightEl.innerHTML = '';
  // Simple LCS-based diff
  const lcs = _lcs(oldLines, newLines);
  let oi = 0, ni = 0, li = 0;
  const leftFrag = document.createDocumentFragment();
  const rightFrag = document.createDocumentFragment();
  while (oi < oldLines.length || ni < newLines.length) {
    if (li < lcs.length && oi === lcs[li][0] && ni === lcs[li][1]) {
      const t = oldLines[oi];
      leftFrag.appendChild(_diffLine(t, 'diff-eq'));
      rightFrag.appendChild(_diffLine(t, 'diff-eq'));
      oi++; ni++; li++;
    } else if (ni < newLines.length && (li >= lcs.length || ni < lcs[li][1])) {
      rightFrag.appendChild(_diffLine(newLines[ni], 'diff-add'));
      ni++;
    } else {
      leftFrag.appendChild(_diffLine(oldLines[oi], 'diff-del'));
      oi++;
    }
  }
  leftEl.appendChild(leftFrag);
  rightEl.appendChild(rightFrag);
}

function _diffLine(text, cls) {
  const span = document.createElement('span');
  span.className = 'diff-line ' + cls;
  span.textContent = text;
  return span;
}

function _lcs(a, b) {
  // Return array of [ai, bi] index pairs in the LCS (capped for perf)
  const MAX = 300;
  const al = Math.min(a.length, MAX), bl = Math.min(b.length, MAX);
  const dp = Array.from({length: al+1}, () => new Int32Array(bl+1));
  for (let i = 1; i <= al; i++)
    for (let j = 1; j <= bl; j++)
      dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1]+1 : Math.max(dp[i-1][j], dp[i][j-1]);
  const res = [];
  let i = al, j = bl;
  while (i > 0 && j > 0) {
    if (a[i-1] === b[j-1]) { res.push([i-1, j-1]); i--; j--; }
    else if (dp[i-1][j] > dp[i][j-1]) i--;
    else j--;
  }
  return res.reverse();
}

async function confirmApplyFile() {
  if (!_diffPending.filepath) return;
  const btn = document.getElementById('diff-confirm-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }
  const input = document.getElementById('msg-input');
  closeDiffViewer();
  // Send as a write request through the agent (goes through approval)
  const payload = {
    message: `write_file path="${_diffPending.filepath}" content=<provided>`,
    tool_call: { name: 'write_file', args: { path: _diffPending.filepath, content: _diffPending.newContent } },
    allow_write: true,
    workspace_root: (document.getElementById('workspace-path')?.value || ''),
  };
  addMsg('you', 'Apply to file: ' + _diffPending.filepath);
  try {
    const r = await fetch('/agent', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const d = await r.json();
    addMsg('layla', d.response || '✓ File apply sent (check approvals if needed)', d.aspect_name);
  } catch {
    addMsg('layla', '⚠ Could not apply file — check server');
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Apply (requires approval)'; }
}

let _batchDiffPending = null;
function openBatchDiffViewer(approvalEntry) {
  const files = approvalEntry?.args?.files || [];
  if (!files.length) return;
  _batchDiffPending = approvalEntry;
  const overlay = document.getElementById('batch-diff-overlay');
  const countEl = document.getElementById('batch-diff-count');
  const tabsEl = document.getElementById('batch-diff-tabs');
  const contentEl = document.getElementById('batch-diff-content');
  countEl.textContent = files.length;
  tabsEl.innerHTML = '';
  contentEl.textContent = '';
  files.forEach((f, i) => {
    const tab = document.createElement('button');
    tab.style.cssText = 'padding:4px 10px;background:var(--code-bg);border:1px solid var(--border);color:var(--text);border-radius:3px;cursor:pointer;font-size:0.7rem';
    tab.textContent = (f.path || f.filepath || 'file ' + (i+1)).split(/[/\\]/).pop();
    tab.onclick = () => {
      tabsEl.querySelectorAll('button').forEach(b => b.style.borderColor = '');
      tab.style.borderColor = 'var(--asp)';
      contentEl.textContent = (f.content || '').slice(0, 8000);
    };
    tabsEl.appendChild(tab);
    if (i === 0) tab.click();
  });
  overlay.style.display = 'flex';
}
function closeBatchDiffViewer() {
  document.getElementById('batch-diff-overlay').style.display = 'none';
  _batchDiffPending = null;
}
async function confirmApplyBatch() {
  if (!_batchDiffPending?.id) return;
  const btn = document.getElementById('batch-apply-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Applying…'; }
  closeBatchDiffViewer();
  await approveId(_batchDiffPending.id);
  if (btn) { btn.disabled = false; btn.textContent = 'Apply all'; }
}

// ─── Memory search ───────────────────────────────────────────────────────────
let _memSearchTimer = null;
const _MEMORY_SEARCH_EMPTY = '<span style="color:var(--text-dim);font-size:0.7rem">Type to search learnings (local filter)</span>';
async function onMemorySearch(query) {
  clearTimeout(_memSearchTimer);
  const results = document.getElementById('memory-search-results');
  if (!query.trim()) { if (results) results.innerHTML = _MEMORY_SEARCH_EMPTY; return; }
  if (results) results.innerHTML = '<span style="color:var(--text-dim)">Searching…</span>';
  _memSearchTimer = setTimeout(async () => {
    if (!results) return;
    results.innerHTML = '<span style="color:var(--text-dim)">Searching…</span>';
    try {
      const r = await fetchWithTimeout('/learnings?limit=100', {}, 15000);
      if (!r.ok) { results.innerHTML = '<span style="color:#f90">Could not load learnings (' + r.status + ')</span>'; return; }
      const d = await r.json();
      const q = query.toLowerCase();
      const matches = (d.items || []).filter(item =>
        (item.content || '').toLowerCase().includes(q)
      ).slice(0, 12);
      if (!matches.length) {
        results.innerHTML = '<span style="color:var(--text-dim)">No matches</span>';
        return;
      }
      results.innerHTML = '';
      matches.forEach(item => {
        const el = document.createElement('div');
        el.style.cssText = 'padding:5px 0;border-bottom:1px solid var(--border);color:var(--text);line-height:1.4';
        const content = item.content || '';
        const safe = escapeHtml(content);
        const hi = safe.replace(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`, 'gi'), '<mark style="background:var(--asp);color:#000;border-radius:2px;padding:0 2px">$1</mark>');
        el.innerHTML = `<span style="font-size:0.68rem;color:var(--text-dim);margin-right:6px">[${escapeHtml(item.type||'?')}]</span>${hi}`;
        results.appendChild(el);
      });
    } catch (e) {
      const msg = (e && e.name === 'AbortError') ? 'Search timed out' : (formatAgentError(null, null));
      results.innerHTML = '<span style="color:#f90">' + msg + '</span>';
    }
  }, 250);
}

async function refreshFileCheckpointsPanel() {
  const el = document.getElementById('file-checkpoints-list');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
  try {
    const r = await fetchWithTimeout('/memory/file_checkpoints?limit=50', {}, 15000);
    const j = await r.json();
    if (j.ok === false && j.error) {
      el.innerHTML = '<span style="color:#f90">' + escapeHtml(String(j.error)) + '</span>';
      return;
    }
    const cps = j.checkpoints || [];
    if (!cps.length) {
      el.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">No checkpoints yet (created before each write when checkpoints are enabled).</span>';
      return;
    }
    el.innerHTML = '';
    cps.forEach(function (cp) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:6px 0;border-bottom:1px solid var(--border);font-size:0.68rem';
      const path = escapeHtml(String((cp.original_path || '').split(/[/\\\\]/).pop() || '?'));
      const tool = escapeHtml(String(cp.tool_name || ''));
      const when = escapeHtml(String((cp.created_at || '').replace('T', ' ').slice(0, 19)));
      const cid = cp.checkpoint_id;
      row.innerHTML = '<span style="flex:1;min-width:120px;color:var(--text)">' + path + '</span>' +
        '<span style="color:var(--text-dim)">' + tool + '</span>' +
        '<span style="color:var(--text-dim)">' + when + '</span>' +
        '<button type="button" class="approve-btn" style="font-size:0.65rem;padding:3px 8px">Restore</button>';
      const btn = row.querySelector('button');
      if (btn && cid) btn.onclick = function () { requestCheckpointRestore(cid); };
      el.appendChild(row);
    });
  } catch (e) {
    el.innerHTML = '<span style="color:#f90">Failed to load checkpoints</span>';
  }
}

async function requestCheckpointRestore(checkpointId) {
  if (!checkpointId) return;
  try {
    const r = await fetchWithTimeout('/memory/file_checkpoints/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ checkpoint_id: checkpointId }),
    }, 20000);
    const j = await r.json().catch(function () { return {}; });
    if (j.approval_required && j.approval_id) {
      if (typeof showToast === 'function') showToast('Restore queued — approve in Safety tab');
      if (typeof refreshApprovals === 'function') refreshApprovals();
      return;
    }
    if (j.ok) {
      if (typeof showToast === 'function') showToast('File restored from checkpoint');
      refreshFileCheckpointsPanel();
      return;
    }
    if (typeof showToast === 'function') showToast(j.error || 'Restore failed');
  } catch (e) {
    if (typeof showToast === 'function') showToast('Restore request failed');
  }
}

async function runElasticsearchLearningSearch() {
  const input = document.getElementById('es-learning-search');
  const out = document.getElementById('es-learning-results');
  if (!input || !out) return;
  const q = (input.value || '').trim();
  if (!q) {
    out.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">Enter keywords (optional: elasticsearch_enabled + server).</span>';
    return;
  }
  out.innerHTML = '<span style="color:var(--text-dim)">Searching…</span>';
  try {
    const r = await fetchWithTimeout('/memory/elasticsearch/search?q=' + encodeURIComponent(q) + '&limit=15', {}, 20000);
    const j = await r.json();
    if (j.error === 'elasticsearch_disabled') {
      out.innerHTML = '<span style="color:var(--text-dim)">Elasticsearch is off — use memory search above or enable in config.</span>';
      return;
    }
    if (!j.ok) {
      out.innerHTML = '<span style="color:#f90">' + escapeHtml(String(j.error || 'Search failed')) + '</span>';
      return;
    }
    const hits = j.hits || [];
    if (!hits.length) {
      out.innerHTML = '<span style="color:var(--text-dim)">No hits</span>';
      return;
    }
    out.innerHTML = '';
    hits.forEach(function (h) {
      const div = document.createElement('div');
      div.style.cssText = 'padding:5px 0;border-bottom:1px solid var(--border);font-size:0.68rem;line-height:1.35';
      div.innerHTML = '<span style="color:var(--text-dim)">id ' + escapeHtml(String(h.id)) + '</span> — ' + escapeHtml((h.text || '').slice(0, 400));
      out.appendChild(div);
    });
  } catch (e) {
    out.innerHTML = '<span style="color:#f90">Request failed</span>';
  }
}

// ─── First-run onboarding ───────────────────────────────────────────────
let _onboardingStep = 0;
const ONBOARDING_STEPS = [
  { text: 'Choose a voice — pick one in the sidebar.', selector: '.aspect-btn' },
  { text: 'Send a message — type below and hit Send.', selector: '#msg-input, #send-btn' },
  { text: 'Layla will ask here when she needs permission to act.', selector: '#layla-right-panel .rcp-tab[data-rcp="safety"]' },
  { text: "You're ready. Start chatting.", selector: null }
];
function showOnboarding() {
  const ov = document.getElementById('onboarding-overlay');
  if (!ov) return;
  _onboardingStep = 0;
  ov.style.display = 'flex';
  applyOnboardingStep();
}
function dismissOnboarding() {
  const ov = document.getElementById('onboarding-overlay');
  if (ov) ov.style.display = 'none';
  document.querySelectorAll('.onboarding-highlight').forEach(el => el.classList.remove('onboarding-highlight'));
  localStorage.setItem('layla_onboarding_done', '1');
  document.getElementById('msg-input')?.focus();
}
function applyOnboardingStep() {
  document.querySelectorAll('.onboarding-highlight').forEach(el => el.classList.remove('onboarding-highlight'));
  const step = ONBOARDING_STEPS[_onboardingStep];
  const textEl = document.getElementById('onboarding-text');
  const nextBtn = document.getElementById('onboarding-next');
  const doneBtn = document.getElementById('onboarding-done');
  if (textEl) textEl.textContent = step.text;
  if (step && step.selector) {
    document.querySelectorAll(step.selector).forEach(el => el.classList.add('onboarding-highlight'));
  }
  if (_onboardingStep === 3) {
    if (nextBtn) nextBtn.style.display = 'none';
    if (doneBtn) doneBtn.style.display = 'inline-block';
  } else {
    if (nextBtn) nextBtn.style.display = 'inline-block';
    if (doneBtn) doneBtn.style.display = 'none';
  }
}
function onboardingNext() {
  _onboardingStep++;
  if (_onboardingStep >= 4) return dismissOnboarding();
  applyOnboardingStep();
}

// Init
(function () {
  const e = document.getElementById('chat-empty');
  if (e) e.innerHTML = renderPromptTilesAndEmptyState();
})();
loadChatHistory();
(function initComposeAndUiTimeouts() {
  try {
    const ce = document.getElementById('compose-draft');
    if (ce && localStorage.getItem('layla_compose_draft')) ce.value = localStorage.getItem('layla_compose_draft');
    if (localStorage.getItem('layla_compose_open') === '1' && typeof toggleComposePanel === 'function') toggleComposePanel(true);
  } catch (_) {}
  laylaApplyUiTimeoutsFromHealth({ effective_limits: { max_runtime_seconds: 900, performance_mode: 'auto' }, effective_config: {} });
})();
doWakeup();
refreshApprovals();
refreshStudyPlans();
refreshVersionInfo();
(function syncPermissionMirrors() {
  const a = document.getElementById('allow-write');
  const ar = document.getElementById('allow-run');
  const a2 = document.getElementById('allow-write-rta');
  const ar2 = document.getElementById('allow-run-rta');
  if (a && a2) {
    a2.checked = !!a.checked;
    a.addEventListener('change', function() { a2.checked = a.checked; });
    a2.addEventListener('change', function() { a.checked = a2.checked; });
  }
  if (ar && ar2) {
    ar2.checked = !!ar.checked;
    ar.addEventListener('change', function() { ar2.checked = ar.checked; });
    ar2.addEventListener('change', function() { ar.checked = ar2.checked; });
  }
})();
if (typeof window.showMainPanel === 'function') window.showMainPanel('status');
if (typeof refreshContentPolicyToggles === 'function') refreshContentPolicyToggles();
checkSetupStatus().then(function() {
  if (!localStorage.getItem('layla_onboarding_done') && !document.getElementById('setup-overlay')?.classList.contains('visible')) {
    if (document.activeElement && document.activeElement.id === 'msg-input') {
      localStorage.setItem('layla_onboarding_done', '1');
    } else {
      showOnboarding();
    }
  }
});
_renderSessionList();
document.getElementById('chat-rail-search')?.addEventListener('input', function() {
  clearTimeout(window.__chatRailSearchT);
  window.__chatRailSearchT = setTimeout(function() { _renderSessionList(); }, 280);
});
tryLoadActiveConversationOnBoot();
try { loadProjectsIntoSelect(); } catch (_) {}
document.getElementById('workspace-path')?.addEventListener('change', function() { try { updateContextChip(); } catch (_) {} });
document.getElementById('workspace-path')?.addEventListener('input', function() { try { updateContextChip(); } catch (_) {} });
document.getElementById('project-select')?.addEventListener('change', function() { try { onProjectSelectChange(); } catch (_) {} });

// ─── Export chat, theme, compact, search ─────────────────────────────────
function exportChat() {
  const chat = document.getElementById('chat');
  if (!chat) return;
  const entries = [];
  for (const node of chat.children) {
    if (node.classList.contains('msg')) {
      const role = node.classList.contains('msg-you') ? 'you' : 'layla';
      const bubble = node.querySelector('.msg-bubble');
      const text = (bubble?.innerText || bubble?.textContent || '').trim();
      if (text) entries.push({ role, text });
    }
  }
  if (!entries.length) { showToast('No messages to export'); return; }
  const md = entries.map(e => `**${e.role === 'you' ? 'You' : 'Layla'}:**\n${e.text}`).join('\n\n---\n\n');
  const blob = new Blob([md], { type: 'text/markdown' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'layla_chat_' + new Date().toISOString().slice(0,10) + '.md';
  a.click();
  URL.revokeObjectURL(a.href);
  showToast('Chat exported');
}

function toggleTheme() {
  const isLight = document.body.classList.toggle('theme-light');
  localStorage.setItem('layla_theme', isLight ? 'light' : 'dark');
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = isLight ? '☀' : '🌙';
}
(function initTheme() {
  const t = localStorage.getItem('layla_theme');
  if (t === 'light') { document.body.classList.add('theme-light'); const b = document.getElementById('theme-btn'); if (b) b.textContent = '☀'; }
})();

function toggleSidebarCompact() {
  document.querySelector('.sidebar')?.classList.toggle('compact');
  const btn = document.getElementById('sidebar-compact-btn');
  if (btn) btn.textContent = document.querySelector('.sidebar')?.classList.contains('compact') ? '▶' : '◀';
  localStorage.setItem('layla_sidebar_compact', document.querySelector('.sidebar')?.classList.contains('compact') ? '1' : '');
}
(function initSidebarCompact() {
  if (localStorage.getItem('layla_sidebar_compact') === '1') { document.querySelector('.sidebar')?.classList.add('compact'); const b = document.getElementById('sidebar-compact-btn'); if (b) b.textContent = '▶'; }
})();
function toggleMobileSidebar() {
  const sb = document.querySelector('.sidebar');
  if (!sb) return;
  const open = !sb.classList.toggle('mobile-sidebar-hidden');
  localStorage.setItem('layla_sidebar_mobile_open', open ? '1' : '');
}
(function initMobileSidebar() {
  if (window.matchMedia('(max-width: 768px)').matches && localStorage.getItem('layla_sidebar_mobile_open') !== '1') {
    document.querySelector('.sidebar')?.classList.add('mobile-sidebar-hidden');
  }
})();

let _chatSearchIdx = -1;
let _lastFocusedBeforeModal = null;
function openChatSearch() {
  _lastFocusedBeforeModal = document.activeElement;
  const ov = document.getElementById('chat-search-overlay');
  if (ov) { ov.style.display = 'flex'; document.getElementById('chat-search-input')?.focus(); }
}
function closeChatSearch() {
  const ov = document.getElementById('chat-search-overlay');
  if (ov) ov.style.display = 'none';
  document.querySelectorAll('.msg-search-hit').forEach(el => el.classList.remove('msg-search-hit'));
  if (_lastFocusedBeforeModal && typeof _lastFocusedBeforeModal.focus === 'function') _lastFocusedBeforeModal.focus(); else document.getElementById('msg-input')?.focus();
}
function showKeyboardShortcutsSheet() {
  const el = document.getElementById('keyboard-shortcuts-sheet');
  if (el) el.style.display = 'flex';
}
function hideKeyboardShortcutsSheet() {
  const el = document.getElementById('keyboard-shortcuts-sheet');
  if (el) el.style.display = 'none';
}
function downloadSessionExport() {
  const q = (typeof currentConversationId !== 'undefined' && currentConversationId)
    ? ('?conversation_id=' + encodeURIComponent(String(currentConversationId)))
    : '';
  fetch('/session/export' + q)
    .then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    })
    .then(function (data) {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'layla-session-export.json';
      a.click();
      URL.revokeObjectURL(a.href);
      if (typeof showToast === 'function') showToast('Session export downloaded');
    })
    .catch(function (e) {
      const msg = 'Export failed: ' + (e && e.message ? e.message : e);
      if (typeof showToast === 'function') showToast(msg);
      else alert(msg);
    });
}
function onChatSearchInput(val) {
  const q = (val || '').trim().toLowerCase();
  document.querySelectorAll('.msg-search-hit').forEach(el => el.classList.remove('msg-search-hit'));
  if (!q) return;
  const chat = document.getElementById('chat');
  if (!chat) return;
  let first = null;
  chat.querySelectorAll('.msg .msg-bubble').forEach(b => {
    if ((b.innerText || b.textContent || '').toLowerCase().includes(q)) {
      b.closest('.msg')?.classList.add('msg-search-hit');
      if (!first) first = b.closest('.msg');
    }
  });
  if (first) first.scrollIntoView({ block: 'nearest' });
}
function chatSearchNext() {
  const hits = document.querySelectorAll('.msg-search-hit');
  if (!hits.length) return;
  _chatSearchIdx = (_chatSearchIdx + 1) % hits.length;
  hits[_chatSearchIdx].scrollIntoView({ block: 'nearest' });
}

// ─── Fill prompt tile into input ───────────────────────────────────────
function fillPrompt(text) {
  const input = document.getElementById('msg-input');
  if (input) {
    input.value = text;
    input.focus();
    toggleSendButton();
    // Cursor at end
    input.selectionStart = input.selectionEnd = input.value.length;
  }
}

// ─── Setup status check ────────────────────────────────────────────────
async function refreshModelStatus(prefetched) {
  try {
    const d = prefetched != null ? prefetched : await (await fetch('/setup_status')).json();
    const badge = document.getElementById('model-status-badge');
    if (!badge) return;
    const mode = d.performance_mode || 'auto';
    const valid = (d.model_valid !== false) && (d.ready || d.model_found || (d.model_filename || '').length > 0);
    if (valid) {
      const raw = ((d.resolved_model || d.model_filename || '') + '').trim() || 'model';
      const short = raw.replace(/\.gguf$/i, '').slice(0, 36);
      const hint = (d.model_route_hint || '').trim();
      const hintPart = hint ? ' (' + hint + ')' : '';
      badge.textContent = 'Model: ' + short + hintPart + ' | Mode: ' + mode;
      badge.style.color = '#4dff88';
    } else {
      badge.textContent = '⚠ setup required';
      badge.style.color = '#ffa040';
    }
  } catch (_) {}
}

async function checkSetupStatus() {
  try {
    const res = await fetch('/setup_status');
    if (!res.ok) return;
    const data = await res.json();
    await refreshModelStatus(data);
    if (data.model_valid === false || !data.ready) {
      showSetupOverlay(data);
    }
  } catch(e) {
    // Server not reachable — show connection banner only; do not block the whole UI
    document.getElementById('connection-banner')?.style.setProperty('display', 'block');
  }
}

let _selectedModelUrl = '';
let _selectedModelFilename = '';
let _lastDownloadUrl = '';
let _lastDownloadFilename = '';

async function showSetupOverlay(statusData) {
  const overlay = document.getElementById('setup-overlay');
  if (!overlay) return;
  overlay.classList.add('visible');

  // Fill hardware info
  const hw = statusData.hardware || {};
  const hwEl = document.getElementById('setup-hw');
  if (hwEl) {
    const ramTxt = hw.ram_gb ? `RAM: ${hw.ram_gb} GB` : 'RAM: unknown';
    const gpuTxt = hw.gpu_vendor && hw.gpu_vendor !== 'none' ? `  GPU: ${hw.gpu_vendor.toUpperCase()}, ${hw.vram_gb} GB VRAM` : '  GPU: none (CPU inference)';
    const tierTxt = hw.tier ? `  Tier: ${hw.tier} — ${hw.suggestion || ''}` : '';
    hwEl.innerHTML = ramTxt + '<br>' + gpuTxt + (tierTxt ? '<br>' + tierTxt : '');
  }

  // If models already exist, offer to use them
  if (statusData.available_models && statusData.available_models.length > 0) {
    const existEl = document.getElementById('setup-existing-models');
    if (existEl) {
      existEl.style.display = 'block';
      const list = document.getElementById('setup-existing-list');
      if (list) {
        list.innerHTML = statusData.available_models.map(m =>
          `<button class="model-card" data-existing-filename="${escapeHtml(m)}">
            <div class="mc-name">${escapeHtml(m)}</div>
            <div class="mc-meta">Already downloaded — click to use</div>
           </button>`
        ).join('');
        list.querySelectorAll('.model-card[data-existing-filename]').forEach(btn => {
          btn.onclick = () => useExistingModel(btn.dataset.existingFilename || '');
        });
      }
    }
  }

  // Load model catalog
  try {
    const catRes = await fetch('/setup/models');
    const catData = await catRes.json();
    const container = document.getElementById('setup-model-list');
    if (container && catData.catalog) {
      container.innerHTML = catData.catalog.map(m => {
        const viable = m.viable !== false;
        const rec = m.recommended ? ' recommended' : '';
        return `<div class="model-card ${viable ? '' : 'not-viable'}${rec}" data-model-url="${escapeHtml(m.url || '')}" data-model-filename="${escapeHtml(m.filename || '')}">
          <div class="mc-name">${escapeHtml(m.name || '')} <span class="mc-badge ${viable ? 'viable' : 'heavy'}">${m.recommended ? '★ recommended · ' : ''}${viable ? '✓ fits RAM' : '⚠ ' + (m.ram_gb || '') + 'GB RAM needed'}</span></div>
          <div class="mc-meta">${escapeHtml(String(m.size_gb || ''))} GB download · needs ${escapeHtml(String(m.ram_gb || ''))} GB RAM</div>
          <div class="mc-desc">${escapeHtml(m.desc || '')}</div>
        </div>`;
      }).join('');
      container.querySelectorAll('.model-card[data-model-url]').forEach(el => {
        el.onclick = () => selectModel(el.dataset.modelUrl || '', el.dataset.modelFilename || '', el);
      });
    }
  } catch(e) {}
}

function selectModel(url, filename, el) {
  _selectedModelUrl = url;
  _selectedModelFilename = filename;
  document.querySelectorAll('.model-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  const btn = document.getElementById('setup-download-btn');
  if (btn) btn.disabled = false;
}

async function useExistingModel(filename) {
  try {
    await fetch('/settings', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model_filename: filename }) });
    document.getElementById('setup-overlay')?.classList.remove('visible');
    showToast('✓ Model set: ' + filename + ' — restart server to apply');
    checkSetupStatus();
  } catch(e) { showToast('Error: ' + e.message); }
}

function retryModelDownload() {
  if (!_lastDownloadUrl) { showToast('Nothing to retry — select a model first'); return; }
  _selectedModelUrl = _lastDownloadUrl;
  _selectedModelFilename = _lastDownloadFilename;
  startModelDownload();
}

async function startModelDownload() {
  const url = _selectedModelUrl || document.getElementById('setup-custom-url')?.value?.trim();
  if (!url) { showToast('Select a model first'); return; }
  const filename = _selectedModelFilename || url.split('/').pop();
  _lastDownloadUrl = url;
  _lastDownloadFilename = filename;
  const btn = document.getElementById('setup-download-btn');
  const retryBtn = document.getElementById('setup-retry-btn');
  const progressBar = document.getElementById('setup-progress-bar');
  const progressLabel = document.getElementById('setup-progress-label');
  const doneMsg = document.getElementById('setup-done-msg');
  if (btn) { btn.disabled = true; btn.textContent = 'Downloading…'; }
  if (retryBtn) retryBtn.style.display = 'none';
  if (doneMsg) doneMsg.style.display = 'none';

  try {
    const es = new EventSource('/setup/download?url=' + encodeURIComponent(url) + '&filename=' + encodeURIComponent(filename));
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.error) {
          es.close();
          showToast('Download failed: ' + data.error);
          if (btn) { btn.disabled = false; btn.textContent = 'Download'; }
          if (retryBtn) { retryBtn.style.display = 'inline-block'; retryBtn.textContent = 'Retry download'; }
          return;
        }
        if (progressBar) progressBar.style.width = (data.pct || 0) + '%';
        if (progressLabel) progressLabel.textContent = (data.pct || 0) + '% · ' + (data.dl_mb || 0) + ' / ' + (data.tot_mb || '?') + ' MB';
        if (data.done) {
          es.close();
          if (progressBar) progressBar.style.width = '100%';
          if (progressLabel) progressLabel.textContent = '✓ Download complete';
          if (doneMsg) { doneMsg.textContent = '✓ Model ready: ' + (data.filename || filename); doneMsg.style.display = 'block'; }
          if (btn) { btn.textContent = '✓ Done — reload page'; btn.onclick = () => location.reload(); btn.disabled = false; }
          if (retryBtn) retryBtn.style.display = 'none';
          const badge = document.getElementById('model-status-badge');
          if (badge) { badge.textContent = '● ' + (data.filename || filename); badge.style.color = '#4dff88'; }
        }
      } catch(ex) {}
    };
    es.onerror = () => {
      es.close();
      if (btn) { btn.disabled = false; btn.textContent = 'Download'; }
      if (retryBtn) { retryBtn.style.display = 'inline-block'; retryBtn.textContent = 'Retry download'; }
    };
  } catch(e) {
    showToast('Error: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = 'Download'; }
    if (retryBtn) { retryBtn.style.display = 'inline-block'; }
  }
}

// ─── Settings panel (schema-driven, full configurability) ─────────────────
const CAT_LABELS = { core: 'Core', model: 'Model', memory: 'Memory', voice: 'Voice', scheduler: 'Scheduler', limits: 'Runtime limits', safety: 'Safety', remote: 'Remote', integrations: 'Integrations' };

function renderSettingField(f, val) {
  const id = 'set-' + f.key.replace(/_/g, '-');
  const label = (f.label || f.key.replace(/_/g, ' ')).replace(/\b\w/g, c => c.toUpperCase());
  const hint = f.hint ? `<div class="hint">${f.hint}</div>` : '';
  let input = '';
  if (f.type === 'boolean') {
    input = `<select id="${id}"><option value="true"${val === true || val === 'true' ? ' selected' : ''}>Yes</option><option value="false"${val === false || val === 'false' ? ' selected' : ''}>No</option></select>`;
  } else if (f.options) {
    const opts = f.options.map(o => `<option value="${o}"${val === o ? ' selected' : ''}>${o}</option>`).join('');
    input = `<select id="${id}">${opts}</select>`;
  } else if (f.type === 'number') {
    const v = val != null && val !== '' ? val : (f.default ?? '');
    const min = f.min != null ? ` min="${f.min}"` : '';
    const max = f.max != null ? ` max="${f.max}"` : '';
    const step = f.key === 'temperature' ? ' step="0.01"' : ' step="1"';
    const ph = f.default != null ? ` placeholder="${f.default}"` : '';
    if (f.key === 'temperature') {
      input = `<input type="range" id="${id}"${min} max="${f.max ?? 1.5}" step="0.01" value="${v}" oninput="document.getElementById('${id}-val').textContent=parseFloat(this.value).toFixed(2)"><span id="${id}-val">${parseFloat(v) || 0.2}</span>`;
    } else {
      input = `<input type="number" id="${id}"${min}${max}${step} value="${v}"${ph}>`;
    }
  } else {
    const v = (val != null && val !== '') ? String(val).replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;') : '';
    const ph = f.key === 'model_filename' ? 'e.g. jinx-20b.gguf' : (f.key === 'sandbox_root' ? 'e.g. C:\\Users\\you' : '');
    if (f.multiline) {
      input = `<textarea id="${id}" rows="3" placeholder="${ph}" style="width:100%;min-height:60px;resize:vertical">${v}</textarea>`;
    } else {
      input = `<input type="text" id="${id}" value="${v}" placeholder="${ph}">`;
    }
  }
  return `<div class="settings-row"><label for="${id}">${label}</label>${input}${hint}</div>`;
}

async function openSettings() {
  _lastFocusedBeforeModal = document.activeElement;
  const overlay = document.getElementById('settings-overlay');
  if (!overlay) return;
  overlay.classList.add('visible');
  const loading = document.getElementById('settings-loading');
  const form = document.getElementById('settings-form');
  loading.style.display = 'block';
  form.style.display = 'none';
  try {
    const [schemaRes, dataRes] = await Promise.all([fetch('/settings/schema'), fetch('/settings')]);
    const schema = await schemaRes.json();
    const data = await dataRes.json();
    const byCat = {};
    for (const f of schema.fields) {
      const c = f.category || 'advanced';
      if (!byCat[c]) byCat[c] = [];
      byCat[c].push(f);
    }
    const order = ['core', 'model', 'memory', 'voice', 'scheduler', 'limits', 'safety', 'remote', 'integrations'];
    let html = '';
    for (const cat of order) {
      if (!byCat[cat]) continue;
      const label = CAT_LABELS[cat] || cat;
      const isCore = cat === 'core';
      const inner = byCat[cat].map(f => renderSettingField(f, data[f.key])).join('');
      if (isCore) {
        html += `<div class="settings-section settings-core">${inner}</div>`;
      } else {
        html += `<details class="settings-advanced"><summary>${label}</summary><div class="settings-advanced-inner">${inner}</div></details>`;
      }
    }
    form.innerHTML = html;
    loading.style.display = 'none';
    form.style.display = 'block';
  } catch (e) {
    loading.textContent = 'Failed to load settings: ' + e.message;
  }
}

function closeSettings() {
  document.getElementById('settings-overlay')?.classList.remove('visible');
  if (_lastFocusedBeforeModal && typeof _lastFocusedBeforeModal.focus === 'function') _lastFocusedBeforeModal.focus(); else document.getElementById('msg-input')?.focus();
}

function openCliHelp() {
  var cmd = 'python layla.py tui';
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(cmd).then(function() {
      showToast('Copied: ' + cmd + ' — run in terminal to open the TUI');
    }).catch(function() {
      showToast('TUI: run in terminal from repo root: ' + cmd);
    });
  } else {
    showToast('TUI: from repo root run: ' + cmd);
  }
}

async function applySettingsPreset(preset) {
  if (!preset) return;
  if (!confirm('Apply preset "' + preset + '"? This overwrites matching settings in runtime_config.json.')) return;
  try {
    const res = await fetch('/settings/preset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ preset }) });
    const data = await res.json();
    if (data.ok) {
      showToast('Preset applied: ' + (data.applied || []).join(', ') + ' — reopen Settings to review; restart server if needed');
      await openSettings();
    } else {
      showToast('Preset failed: ' + (data.error || JSON.stringify(data)));
    }
  } catch (e) { showToast('Error: ' + e.message); }
}

async function saveSettings() {
  const form = document.getElementById('settings-form');
  if (!form) return;
  const body = {};
  const inputs = form.querySelectorAll('input[id^="set-"], select[id^="set-"], textarea[id^="set-"]');
  for (const el of inputs) {
    const key = el.id.replace(/^set-/, '').replace(/-/g, '_');
    let v = el.value;
    if (el.type === 'number' || el.type === 'range') {
      v = v === '' ? undefined : parseFloat(v);
    } else if (el.tagName === 'SELECT' && (v === 'true' || v === 'false')) {
      v = v === 'true';
    } else if (typeof v === 'string') {
      v = v.trim();
    }
    if (v !== undefined && v !== '') body[key] = v;
  }
  if (Object.keys(body).length === 0) { showToast('No changes to save'); return; }
  try {
    const res = await fetch('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json();
    const msg = document.getElementById('settings-save-msg');
    if (data.ok) {
      if (msg) { msg.style.display = 'inline'; setTimeout(() => { if (msg) msg.style.display = 'none'; }, 2500); }
      showToast('Settings saved — restart server for model/config changes to apply');
      if (typeof refreshContentPolicyToggles === 'function') refreshContentPolicyToggles();
    } else {
      showToast('Save failed: ' + (data.error || 'unknown'));
    }
  } catch (e) { showToast('Error: ' + e.message); }
}

// Close overlays on background click
document.addEventListener('click', (e) => {
  if (e.target.id === 'settings-overlay') closeSettings();
  if (e.target.id === 'setup-overlay') { /* don't close setup on backdrop click — intentional */ }
});
document.addEventListener('keydown', (e) => {
  // Enter handled by early listener at top of script
  if (e.key === 'Escape') {
    if (_micActive) { stopMic(); return; }
    const ks = document.getElementById('keyboard-shortcuts-sheet');
    if (ks && ks.style.display === 'flex') { hideKeyboardShortcutsSheet(); return; }
    const onboardingOv = document.getElementById('onboarding-overlay');
    if (onboardingOv && onboardingOv.style.display === 'flex') {
      dismissOnboarding();
      document.getElementById('msg-input')?.focus();
      return;
    }
    closeChatSearch();
    closeSettings();
    if (document.getElementById('setup-overlay')?.classList.contains('visible')) {
      document.getElementById('setup-overlay').classList.remove('visible');
    }
  }
}, true);

// Expose all UI handlers to window so inline onclick/onchange work regardless of script scope
if (typeof exportChat === 'function') window.exportChat = exportChat;
if (typeof toggleTheme === 'function') window.toggleTheme = toggleTheme;
if (typeof toggleSidebarCompact === 'function') window.toggleSidebarCompact = toggleSidebarCompact;
if (typeof openSettings === 'function') window.openSettings = openSettings;
if (typeof clearChat === 'function') window.clearChat = clearChat;
if (typeof openCliHelp === 'function') window.openCliHelp = openCliHelp;
if (typeof toggleAspectLock === 'function') window.toggleAspectLock = toggleAspectLock;
if (typeof toggleMobileSidebar === 'function') window.toggleMobileSidebar = toggleMobileSidebar;
if (typeof addWorkspacePreset === 'function') window.addWorkspacePreset = addWorkspacePreset;
if (typeof removeWorkspacePreset === 'function') window.removeWorkspacePreset = removeWorkspacePreset;
if (typeof onWorkspacePresetSelect === 'function') window.onWorkspacePresetSelect = onWorkspacePresetSelect;
if (typeof sendResearch === 'function') window.sendResearch = sendResearch;
if (typeof startResearchMission === 'function') window.startResearchMission = startResearchMission;
if (typeof focusResearchPanel === 'function') window.focusResearchPanel = focusResearchPanel;
if (typeof acceptUrlFetch === 'function') window.acceptUrlFetch = acceptUrlFetch;
if (typeof dismissUrlChip === 'function') window.dismissUrlChip = dismissUrlChip;
if (typeof toggleMic === 'function') window.toggleMic = toggleMic;
if (typeof retryLastMessage === 'function') window.retryLastMessage = retryLastMessage;
if (typeof showKeyboardShortcutsSheet === 'function') window.showKeyboardShortcutsSheet = showKeyboardShortcutsSheet;
if (typeof hideKeyboardShortcutsSheet === 'function') window.hideKeyboardShortcutsSheet = hideKeyboardShortcutsSheet;
if (typeof downloadSessionExport === 'function') window.downloadSessionExport = downloadSessionExport;
if (typeof addStudyPlan === 'function') window.addStudyPlan = addStudyPlan;
if (typeof fillPrompt === 'function') window.fillPrompt = fillPrompt;
if (typeof showResearchTab === 'function') window.showResearchTab = showResearchTab;
if (typeof chatSearchNext === 'function') window.chatSearchNext = chatSearchNext;
if (typeof closeChatSearch === 'function') window.closeChatSearch = closeChatSearch;
if (typeof onChatSearchInput === 'function') window.onChatSearchInput = onChatSearchInput;
if (typeof openChatSearch === 'function') window.openChatSearch = openChatSearch;
if (typeof dismissOnboarding === 'function') window.dismissOnboarding = dismissOnboarding;
if (typeof onboardingNext === 'function') window.onboardingNext = onboardingNext;
if (typeof startModelDownload === 'function') window.startModelDownload = startModelDownload;
if (typeof saveSettings === 'function') window.saveSettings = saveSettings;
if (typeof closeSettings === 'function') window.closeSettings = closeSettings;
if (typeof closeBatchDiffViewer === 'function') window.closeBatchDiffViewer = closeBatchDiffViewer;
if (typeof confirmApplyBatch === 'function') window.confirmApplyBatch = confirmApplyBatch;
if (typeof closeDiffViewer === 'function') window.closeDiffViewer = closeDiffViewer;
if (typeof confirmApplyFile === 'function') window.confirmApplyFile = confirmApplyFile;
if (typeof refreshPlatformHealth === 'function') window.refreshPlatformHealth = refreshPlatformHealth;
if (typeof refreshAgentsPanel === 'function') window.refreshAgentsPanel = refreshAgentsPanel;
if (typeof refreshPlatformModels === 'function') window.refreshPlatformModels = refreshPlatformModels;
if (typeof refreshPlatformKnowledge === 'function') window.refreshPlatformKnowledge = refreshPlatformKnowledge;
if (typeof refreshPlatformPlugins === 'function') window.refreshPlatformPlugins = refreshPlatformPlugins;
if (typeof refreshPlatformProjects === 'function') window.refreshPlatformProjects = refreshPlatformProjects;
if (typeof refreshPlatformTimeline === 'function') window.refreshPlatformTimeline = refreshPlatformTimeline;
if (typeof attachFile === 'function') window.attachFile = attachFile;
if (typeof onMemorySearch === 'function') window.onMemorySearch = onMemorySearch;
if (typeof refreshFileCheckpointsPanel === 'function') window.refreshFileCheckpointsPanel = refreshFileCheckpointsPanel;
if (typeof requestCheckpointRestore === 'function') window.requestCheckpointRestore = requestCheckpointRestore;
if (typeof runElasticsearchLearningSearch === 'function') window.runElasticsearchLearningSearch = runElasticsearchLearningSearch;
/* Inline HTML handlers resolve on window — functions inside try{} are block-scoped in modern engines */
if (typeof checkForUpdates === 'function') window.checkForUpdates = checkForUpdates;
if (typeof runKnowledgeIngest === 'function') window.runKnowledgeIngest = runKnowledgeIngest;
if (typeof studyTopicFromChatInput === 'function') window.studyTopicFromChatInput = studyTopicFromChatInput;
if (typeof studyTopicFromLastUserMessage === 'function') window.studyTopicFromLastUserMessage = studyTopicFromLastUserMessage;
if (typeof refreshMissionStatus === 'function') window.refreshMissionStatus = refreshMissionStatus;
if (typeof applySettingsPreset === 'function') window.applySettingsPreset = applySettingsPreset;
if (typeof retryModelDownload === 'function') window.retryModelDownload = retryModelDownload;
if (typeof cancelActiveSend === 'function') window.cancelActiveSend = cancelActiveSend;
if (typeof compactConversation === 'function') window.compactConversation = compactConversation;
if (typeof refreshSkillsList === 'function') window.refreshSkillsList = refreshSkillsList;
if (typeof updateToolStatus === 'function') window.updateToolStatus = updateToolStatus;
if (typeof clearToolStatus === 'function') window.clearToolStatus = clearToolStatus;
if (typeof approveId === 'function') window.approveId = approveId;
if (typeof denyApproval === 'function') window.denyApproval = denyApproval;
if (typeof refreshApprovals === 'function') window.refreshApprovals = refreshApprovals;
if (typeof openBatchDiffViewer === 'function') window.openBatchDiffViewer = openBatchDiffViewer;
if (typeof onInputKeydown === 'function') window.onInputKeydown = onInputKeydown;
if (typeof onInputChange === 'function') window.onInputChange = onInputChange;
if (typeof refreshStudyPlans === 'function') window.refreshStudyPlans = refreshStudyPlans;
if (typeof loadStudyPresetsAndSuggestions === 'function') window.loadStudyPresetsAndSuggestions = loadStudyPresetsAndSuggestions;
if (typeof _pickMention === 'function') window._pickMention = _pickMention;

// ── Phone / LAN access ───────────────────────────────────────────────────────
let _phoneUrl = '';
async function loadPhoneAccess() {
  const urlEl = document.getElementById('phone-access-url');
  const statusEl = document.getElementById('phone-access-status');
  const qrEl = document.getElementById('phone-qr-area');
  try {
    const res = await fetch('/local_access_info');
    const d = await res.json();
    _phoneUrl = d.ui_url || d.url || '';
    if (urlEl) urlEl.textContent = _phoneUrl;
    if (statusEl) {
      if (d.remote_enabled) {
        statusEl.textContent = 'Remote access enabled' + (d.api_key_required ? ' (API key required)' : ' (no key — set one!)');
        statusEl.style.color = d.api_key_required ? 'var(--asp,#8f8)' : '#fa0';
      } else {
        statusEl.textContent = 'Remote access disabled — enable in runtime_config.json';
        statusEl.style.color = '#f88';
      }
    }
    // QR via Google Charts API (no external lib needed; only calls if UI already has internet or user opens link)
    if (qrEl && _phoneUrl) {
      const qrUrl = 'https://chart.googleapis.com/chart?chs=160x160&cht=qr&chl=' + encodeURIComponent(_phoneUrl);
      qrEl.innerHTML = '<img src="' + qrUrl + '" alt="QR code for ' + _phoneUrl + '" style="width:120px;height:120px;border-radius:4px;border:1px solid var(--border)" onerror="this.outerHTML=\'<div style=&quot;font-size:0.7rem;color:var(--text-dim)&quot;>QR unavailable offline — copy the URL above</div>\'">';
    }
  } catch (e) {
    if (urlEl) urlEl.textContent = 'Could not load — is the server running?';
    if (statusEl) statusEl.textContent = '';
  }
}
function copyPhoneUrl() {
  if (_phoneUrl) navigator.clipboard?.writeText(_phoneUrl).then(() => showToast('URL copied')).catch(() => {});
}
window.loadPhoneAccess = loadPhoneAccess;
window.copyPhoneUrl = copyPhoneUrl;

// ── Plan mode execution ──────────────────────────────────────────────────────
async function executePlan(plan, goal) {
  if (!plan || !plan.length) return;
  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  const aspect = currentAspect || 'morrigan';
  const cid = (typeof ensureLaylaConversationId === 'function') ? ensureLaylaConversationId() : (currentConversationId || '');
  showToast('Executing plan (' + plan.length + ' steps)…');
  hideEmpty();
  const chat = document.getElementById('chat');
  const runDiv = document.createElement('div');
  runDiv.className = 'msg msg-layla';
  runDiv.innerHTML = '<div class="msg-label msg-label-layla">' + formatLaylaLabelHtml(aspect) + '</div><div class="msg-bubble"><div class="memory-attribution" id="plan-exec-status">Executing plan…</div></div>';
  chat?.appendChild(runDiv);
  chat?.scrollTo(0, 99999);
  try {
    const res = await fetchWithTimeout('/execute_plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plan,
        goal,
        workspace_root: wp,
        allow_write: document.getElementById('allow-write')?.checked ?? false,
        allow_run: document.getElementById('allow-run')?.checked ?? false,
        aspect_id: aspect,
        conversation_id: cid,
      }),
    }, laylaAgentJsonTimeoutMs());
    const d = await res.json();
    const statusEl = document.getElementById('plan-exec-status');
    if (statusEl) statusEl.remove();
    if (d.ok && d.results) {
      const stepsDone = d.results.steps_done || [];
      const allOk = d.all_steps_ok;
      const stepLines = stepsDone.map((s, i) => {
        const task = String(s.task || s.goal || '').slice(0, 120);
        const st = String(s.result_status || s.status || '');
        let extra = '';
        if (s.governance_ok === false && s.validation_error) {
          extra = ' [' + String(s.validation_error).slice(0, 100) + ']';
        }
        return (i + 1) + '. ' + task + ' — ' + st + extra;
      }).join('\n');
      const head = allOk === true ? ' (all steps OK)' : (allOk === false ? ' (some steps need attention)' : '');
      const bubble = runDiv.querySelector('.msg-bubble');
      if (bubble) {
        bubble.innerHTML = '<b>Plan executed</b>' + head + ' (' + plan.length + ' steps)<br><pre style="font-size:0.7rem;margin-top:6px;white-space:pre-wrap">' + (stepLines || 'Done').replace(/</g, '&lt;') + '</pre>';
      }
    } else {
      const bubble = runDiv.querySelector('.msg-bubble');
      if (bubble) bubble.textContent = 'Plan execution failed: ' + (d.error || 'unknown error');
    }
  } catch (e) {
    const bubble = runDiv.querySelector('.msg-bubble');
    if (bubble) bubble.textContent = 'Network error during plan execution.';
  }
  chat?.scrollTo(0, 99999);
}
window.executePlan = executePlan;
window.toggleComposePanel = toggleComposePanel;
window.laylaRunPlanFromElement = laylaRunPlanFromElement;
window.laylaFormatPlanJson = laylaFormatPlanJson;

async function resumeFromCheckpoint(checkpoint) {
  if (!checkpoint) return;
  const wp = (document.getElementById('workspace-path')?.value || '').trim();
  showToast('Resuming…');
  try {
    const res = await fetch('/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        checkpoint,
        workspace_root: wp,
        allow_write: document.getElementById('allow-write')?.checked ?? false,
        allow_run: document.getElementById('allow-run')?.checked ?? false,
        aspect_id: currentAspect || 'morrigan',
      }),
    });
    const d = await res.json();
    if (d.ok) {
      addMsg('layla', d.response || 'Resumed and completed.', null, false, d.state?.steps, [], []);
    } else {
      addMsg('layla', 'Resume failed: ' + (d.error || 'unknown'));
    }
  } catch (e) {
    addMsg('layla', 'Network error during resume.');
  }
}
window.resumeFromCheckpoint = resumeFromCheckpoint;

// Auto-load phone info when Help tab is clicked
document.addEventListener('click', function(e) {
  const tab = e.target && e.target.closest && e.target.closest('.rcp-tab[data-rcp="help"]');
  if (tab) setTimeout(loadPhoneAccess, 100);
}, true);

} finally {
// Bind input keydown (Ctrl+K, mentions, etc.) and optional toggleSendButton/onInputChange. Send and Enter use triggerSend (inline + document keydown). Panel tabs use inline onclick only.
(function bindChatInputNow() {
  try {
    if (typeof _dbg === 'function') _dbg('bindChatInputNow running');
    var input = document.getElementById('msg-input');
    var btn = document.getElementById('send-btn');
    if (input) {
      if (typeof onInputKeydown === 'function') input.addEventListener('keydown', onInputKeydown);
      if (typeof onInputChange === 'function') input.addEventListener('input', onInputChange);
      if (typeof toggleSendButton === 'function') {
        input.addEventListener('focus', toggleSendButton);
        toggleSendButton();
      }
      if (typeof _dbg === 'function') _dbg('input listeners attached');
    }
    if (btn) {
      btn.removeAttribute('disabled');
      btn.disabled = false;
      if (typeof toggleSendButton === 'function') toggleSendButton();
    }
  } catch (e) {
    if (typeof _dbg === 'function') _dbg('bindChatInputNow FAILED', e);
    try { console.warn('[Layla] bindChatInputNow error', e); } catch (_) {}
  }
})();
}
