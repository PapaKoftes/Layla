/**
 * components/onboarding.js — Onboarding interview overlay UI.
 *
 * Converted from js/layla-onboarding.js (IIFE -> ES module).
 * Checks /onboarding/status on load. If onboarding is needed, shows a
 * chat-style interview overlay. Each stage shows Layla's opener and
 * collects the user's response via a text input.
 *
 * Phase 4D of the distributed infrastructure plan.
 * No module dependencies — self-contained with inline styles.
 */

// ── State ───────────────────────────────────────────────────────────────────
let _overlay = null;
let _state = null;
let _stageInfo = null;

// ── Helpers ─────────────────────────────────────────────────────────────────
function _renderMarkdown(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n/g, '<br>');
}

function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ── Inline styles for the overlay ─────────────────────────────────────────
function _injectStyles() {
  if (document.getElementById('onboarding-styles')) return;

  const style = document.createElement('style');
  style.id = 'onboarding-styles';
  style.textContent =
    '.onboarding-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px)}' +
    '.onboarding-modal{background:var(--bg,#0d1117);border:1px solid var(--border,rgba(255,255,255,0.12));border-radius:12px;width:min(520px,90vw);max-height:85vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.5)}' +
    '.onboarding-header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border,rgba(255,255,255,0.1))}' +
    '.onboarding-title{font-family:"Cinzel",serif;font-size:0.95rem;color:var(--accent,#c9a0dc);letter-spacing:0.04em}' +
    '.onboarding-close{background:none;border:none;color:var(--text-dim,#888);font-size:1.4rem;cursor:pointer;padding:0 4px;line-height:1}' +
    '.onboarding-close:hover{color:#fff}' +
    '.onboarding-content{flex:1;overflow-y:auto;padding:16px 18px}' +
    '.onboarding-progress{margin-bottom:14px}' +
    '.onboarding-progress-text{font-size:0.65rem;color:var(--text-dim,#888);margin-bottom:4px}' +
    '.onboarding-progress-bar{height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden}' +
    '.onboarding-progress-fill{height:100%;background:var(--accent,#c9a0dc);border-radius:2px;transition:width 0.3s ease}' +
    '.onboarding-chat{display:flex;flex-direction:column;gap:10px;margin-bottom:14px;max-height:320px;overflow-y:auto}' +
    '.onboarding-msg{display:flex;flex-direction:column}' +
    '.onboarding-msg-label{font-size:0.6rem;color:var(--text-dim,#888);margin-bottom:2px;font-weight:600}' +
    '.onboarding-msg-bubble{padding:10px 14px;border-radius:10px;font-size:0.8rem;line-height:1.5;white-space:pre-wrap}' +
    '.onboarding-msg-layla .onboarding-msg-bubble{background:rgba(201,160,220,0.1);border:1px solid rgba(201,160,220,0.2);color:var(--text,#e6e6e6)}' +
    '.onboarding-msg-user .onboarding-msg-bubble{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);color:var(--text,#e6e6e6);align-self:flex-end}' +
    '.onboarding-input-area{border-top:1px solid var(--border,rgba(255,255,255,0.1));padding-top:12px}' +
    '.onboarding-textarea{width:100%;background:var(--input-bg,rgba(255,255,255,0.04));border:1px solid var(--border,rgba(255,255,255,0.12));border-radius:8px;padding:10px 12px;font-size:0.8rem;color:var(--text,#e6e6e6);resize:none;font-family:inherit;box-sizing:border-box}' +
    '.onboarding-textarea:focus{outline:none;border-color:var(--accent,#c9a0dc)}' +
    '.onboarding-actions{display:flex;gap:8px;justify-content:center;margin-top:14px}' +
    '.onboarding-btn{padding:8px 20px;border-radius:6px;border:none;cursor:pointer;font-size:0.78rem;font-weight:500;transition:background 0.2s}' +
    '.onboarding-btn-primary{background:var(--accent,#c9a0dc);color:#111}' +
    '.onboarding-btn-primary:hover{filter:brightness(1.1)}' +
    '.onboarding-btn-primary:disabled{opacity:0.5;cursor:not-allowed}' +
    '.onboarding-btn-secondary{background:rgba(255,255,255,0.08);color:var(--text-dim,#888)}' +
    '.onboarding-btn-secondary:hover{background:rgba(255,255,255,0.14)}';

  document.head.appendChild(style);
}

// ── Overlay management ────────────────────────────────────────────────────
function _createOverlay() {
  if (_overlay) return _overlay;

  const el = document.createElement('div');
  el.id = 'onboarding-overlay';
  el.className = 'onboarding-overlay';
  // a11y: this is a modal dialog — announce it as one and label it.
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  el.setAttribute('aria-label', 'Meet Layla — first-run setup');
  el.innerHTML =
    '<div class="onboarding-modal">' +
      '<div class="onboarding-header">' +
        '<span class="onboarding-title" id="onboarding-title">∴ Meet Layla</span>' +
        '<button type="button" class="onboarding-close" id="onboarding-close-btn" title="Close" aria-label="Close">&times;</button>' +
      '</div>' +
      '<div class="onboarding-content"></div>' +
    '</div>';
  el.setAttribute('aria-labelledby', 'onboarding-title');

  document.body.appendChild(el);
  _overlay = el;

  // Make visible
  el.classList.add('visible');

  // a11y: remember focus to restore on close, and trap Tab within the dialog.
  el._prevFocus = document.activeElement;
  el.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab') return;
    const f = el.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])');
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
    else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
  });

  // Close button
  const closeBtn = document.getElementById('onboarding-close-btn');
  if (closeBtn) closeBtn.onclick = function () { _skipAndClose(); };

  // Inject styles if not already present
  _injectStyles();

  return el;
}

function _ensureOverlay() {
  return _overlay || _createOverlay();
}

function _closeOverlay() {
  if (_overlay) {
    const prev = _overlay._prevFocus;
    _overlay.remove();
    _overlay = null;
    if (prev && typeof prev.focus === 'function') { try { prev.focus(); } catch (_) {} }
  }
  _state = null;
  _stageInfo = null;
}

// ── Skip interview ────────────────────────────────────────────────────────
function _skipAndClose() {
  fetch('/onboarding/skip', { method: 'POST' })
    .then(function () { _closeOverlay(); })
    .catch(function () { _closeOverlay(); });
}

/**
 * Close the interview (BL-249). This is what window.dismissOnboarding now points at.
 *
 * It used to point at setup.js's tour dismiss, because the tour and this interview shared
 * #onboarding-overlay — so Escape here fired the TOUR's close, which stripped a `visible` class this
 * overlay's CSS never used and marked the tour as seen while leaving the interview on screen. The tour has
 * its own #tour-overlay now; #onboarding-overlay belongs to this module, and Escape / the overlay manager
 * close it correctly by skipping the interview.
 */
export function dismissOnboarding() {
  _skipAndClose();
}

// ── Soft prompt before starting ───────────────────────────────────────────
function _showOnboardingPrompt() {
  const overlay = _createOverlay();
  const content = overlay.querySelector('.onboarding-content');
  if (!content) return;

  content.innerHTML =
    '<div class="onboarding-chat">' +
      '<div class="onboarding-msg onboarding-msg-layla">' +
        '<div class="onboarding-msg-label">Layla</div>' +
        '<div class="onboarding-msg-bubble">' +
          'Welcome! I\'d like to get to know you so I can be more helpful. ' +
          'Would you like to do a quick interview? It takes about 5 minutes.' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="onboarding-actions">' +
      '<button type="button" class="onboarding-btn onboarding-btn-primary" id="onboarding-start-btn">Let\'s do it</button>' +
      '<button type="button" class="onboarding-btn onboarding-btn-secondary" id="onboarding-skip-btn">Skip for now</button>' +
    '</div>';

  const startBtn = document.getElementById('onboarding-start-btn');
  const skipBtn = document.getElementById('onboarding-skip-btn');

  if (startBtn) startBtn.onclick = function () { _startInterview(false); };
  if (skipBtn) skipBtn.onclick = function () { _skipAndClose(); };
}

// ── Start / resume the interview ──────────────────────────────────────────
function _startInterview(isResume) {
  const endpoint = isResume ? '/onboarding/stage' : '/onboarding/start';
  const method = isResume ? 'GET' : 'POST';

  fetch(endpoint, { method: method })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.state) _state = d.state;
      _stageInfo = d.stage_info || d;
      _renderStage();
    })
    .catch(function (e) {
      console.warn('[Layla Onboarding] start failed:', e);
      _closeOverlay();
    });
}

// ── Render current stage ──────────────────────────────────────────────────
function _renderStage() {
  if (!_stageInfo) return;

  const overlay = _ensureOverlay();
  const content = overlay.querySelector('.onboarding-content');
  if (!content) return;

  const stage = _stageInfo.stage || '';
  const stageNum = _stageInfo.number || 1;
  const stageTotal = _stageInfo.total || 6;
  const opener = _stageInfo.opener || '';

  const pct = Math.round((stageNum / stageTotal) * 100);

  let html = '';

  // Progress indicator
  html += '<div class="onboarding-progress">';
  html += '<div class="onboarding-progress-text">Step ' + stageNum + ' of ' + stageTotal + '</div>';
  html += '<div class="onboarding-progress-bar"><div class="onboarding-progress-fill" style="width:' + pct + '%"></div></div>';
  html += '</div>';

  // Chat area
  html += '<div class="onboarding-chat" id="onboarding-chat">';
  html += '<div class="onboarding-msg onboarding-msg-layla">';
  html += '<div class="onboarding-msg-label">Layla</div>';
  html += '<div class="onboarding-msg-bubble">' + _renderMarkdown(opener) + '</div>';
  html += '</div>';
  html += '</div>';

  // Input area
  html += '<div class="onboarding-input-area">';
  html += '<textarea id="onboarding-input" class="onboarding-textarea" placeholder="Type your response..." rows="3"></textarea>';
  html += '<div style="display:flex;gap:6px;justify-content:flex-end;margin-top:6px">';
  html += '<button type="button" class="onboarding-btn onboarding-btn-secondary" id="onboarding-skip-stage-btn">Skip this</button>';
  html += '<button type="button" class="onboarding-btn onboarding-btn-primary" id="onboarding-send-btn">Continue →</button>';
  html += '</div>';
  html += '</div>';

  content.innerHTML = html;

  // Wire events
  const sendBtn = document.getElementById('onboarding-send-btn');
  const skipStageBtn = document.getElementById('onboarding-skip-stage-btn');
  const input = document.getElementById('onboarding-input');

  if (sendBtn) sendBtn.onclick = function () { _submitResponse(); };
  if (skipStageBtn) skipStageBtn.onclick = function () { _advanceStage(); };
  if (input) {
    input.focus();
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        _submitResponse();
      }
    });
  }
}

// ── Submit the user's response ────────────────────────────────────────────
function _submitResponse() {
  const input = document.getElementById('onboarding-input');
  if (!input) return;

  const text = (input.value || '').trim();
  if (!text) return;

  const stage = (_stageInfo && _stageInfo.stage) || '';

  // Show user message in chat
  const chat = document.getElementById('onboarding-chat');
  if (chat) {
    const userMsg = document.createElement('div');
    userMsg.className = 'onboarding-msg onboarding-msg-user';
    userMsg.innerHTML =
      '<div class="onboarding-msg-label">You</div>' +
      '<div class="onboarding-msg-bubble">' + _esc(text) + '</div>';
    chat.appendChild(userMsg);
    chat.scrollTop = chat.scrollHeight;
  }

  // Disable input while submitting
  input.disabled = true;
  const sendBtn = document.getElementById('onboarding-send-btn');
  if (sendBtn) sendBtn.disabled = true;

  // Submit response then advance
  fetch('/onboarding/response', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stage: stage, data: { response: text } }),
  })
    .then(function (r) { return r.json(); })
    .then(function () {
      _advanceStage();
    })
    .catch(function (e) {
      console.warn('[Layla Onboarding] submit failed:', e);
      if (input) input.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
    });
}

// ── Advance to next stage ─────────────────────────────────────────────────
function _advanceStage() {
  fetch('/onboarding/advance', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.is_complete || d.stage === 'complete') {
        _completeInterview();
      } else {
        _stageInfo = d.stage_info || d;
        _state = d.state || _state;
        _renderStage();
      }
    })
    .catch(function (e) {
      console.warn('[Layla Onboarding] advance failed:', e);
    });
}

// ── Complete the interview ────────────────────────────────────────────────
function _completeInterview() {
  fetch('/onboarding/complete', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function () {
      _showCompletion();
    })
    .catch(function () {
      _showCompletion();
    });
}

function _showCompletion() {
  const overlay = _ensureOverlay();
  const content = overlay.querySelector('.onboarding-content');
  if (!content) return;

  content.innerHTML =
    '<div class="onboarding-chat">' +
      '<div class="onboarding-msg onboarding-msg-layla">' +
        '<div class="onboarding-msg-label">Layla</div>' +
        '<div class="onboarding-msg-bubble">' +
          'Thank you! I\'ve got everything I need to get started. ' +
          'I\'ll keep learning about you as we work together. ' +
          'Let\'s get to it.' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="onboarding-actions">' +
      '<button type="button" class="onboarding-btn onboarding-btn-primary" id="onboarding-done-btn">Start using Layla</button>' +
    '</div>';

  const doneBtn = document.getElementById('onboarding-done-btn');
  if (doneBtn) doneBtn.onclick = function () { _closeOverlay(); };
}

/** True while an earlier first-run surface (the wizard, or its tour handoff) still owns the screen.
 *
 * This interview is the LAST first-run surface. It used to fire unconditionally 2s after load; while the
 * wizard was skipped on any machine with a model (BL-250) it never visibly collided, so nothing revealed
 * the conflict. The moment the wizard came back (BL-250 fix), this overlay would stack ON TOP of it — two
 * "Meet Layla" modals fighting for a first-time user's attention. window._laylaFirstRunClaim is the shared
 * signal wizard.js sets; a visibility check of the wizard/tour overlays is the belt-and-braces for the
 * window where the wizard is deciding but not yet painted.
 */
function _firstRunSurfaceAhead() {
  try {
    if (window._laylaFirstRunClaim && window._laylaFirstRunClaim !== 'released') return true;
    for (var i = 0, ids = ['wizard-overlay', 'tour-overlay']; i < ids.length; i++) {
      var el = document.getElementById(ids[i]);
      if (el && el.classList.contains('visible')) return true;
    }
  } catch (_) {}
  return false;
}

/** Poll until every earlier surface is gone, then re-check. Bounded: an introduction nobody finishes must
 *  not leave a timer running for the life of the tab. */
let _obDeferring = false;
function _deferOnboarding() {
  if (_obDeferring) return;
  _obDeferring = true;
  let waited = 0;
  const iv = setInterval(function () {
    waited += 1000;
    if (!_firstRunSurfaceAhead()) { clearInterval(iv); _obDeferring = false; checkOnboarding(); return; }
    if (waited >= 15 * 60 * 1000) { clearInterval(iv); _obDeferring = false; }
  }, 1000);
}

// ── Bootstrap: check if onboarding needed ─────────────────────────────────
export function checkOnboarding() {
  if (_firstRunSurfaceAhead()) { _deferOnboarding(); return; }
  fetch('/onboarding/status')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      // Re-check: /onboarding/status is a round-trip, and the wizard can open while it is in flight.
      if (_firstRunSurfaceAhead()) { _deferOnboarding(); return; }
      if (d.needs_onboarding && !d.in_progress) {
        _showOnboardingPrompt();
      } else if (d.in_progress && d.state) {
        _state = d.state;
        _startInterview(true);
      }
    })
    .catch(function () {
      // Server not ready or endpoint missing — silently skip
    });
}

// ── Init: delayed check on load ───────────────────────────────────────────
export function initOnboarding() {
  // Delay check slightly so the main UI loads first
  setTimeout(checkOnboarding, 2000);
}
