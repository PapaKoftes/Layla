/**
 * layla-utils.js — Shared utilities used by all other Layla UI modules.
 * Must load BEFORE all other layla-*.js files.
 */
(function () {
  'use strict';

  // ── Debug logging ──────────────────────────────────────────────────────────
  var LAYLA_DEBUG = (typeof localStorage !== 'undefined' && localStorage.getItem('layla_debug') === '1') || (typeof location !== 'undefined' && location.search.indexOf('layla_debug') !== -1);
  window.LAYLA_DEBUG = LAYLA_DEBUG;

  function _dbg() {
    if (!window.LAYLA_DEBUG && !LAYLA_DEBUG) return;
    try { console.log.apply(console, ['[Layla]'].concat(Array.prototype.slice.call(arguments))); } catch (_) {}
  }
  window._dbg = _dbg;

  // ── Agent timeout ──────────────────────────────────────────────────────────
  function laylaAgentTimeoutMs() {
    var stored = parseInt(localStorage.getItem('layla_agent_timeout_ms') || '', 10);
    return (stored > 0 && stored <= 600000) ? stored : 120000;
  }
  window.laylaAgentTimeoutMs = laylaAgentTimeoutMs;

  // ── Error formatting ───────────────────────────────────────────────────────
  function formatAgentError(res, body) {
    if (!res) return "Can't reach Layla. Is the server running at http://127.0.0.1:8000?";
    if (res.status === 500) return 'Something went wrong. Check the server logs or try again.';
    if (res.status === 503) return (body && body.detail) || 'Service temporarily unavailable.';
    var err = (body && (body.detail || body.response || body.message)) || res.statusText;
    return err && String(err).length < 200 ? String(err) : 'Request failed: ' + res.status;
  }
  window.formatAgentError = formatAgentError;

  // ── HTML escaping ──────────────────────────────────────────────────────────
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  window.escapeHtml = escapeHtml;

  // ── Text cleaning ──────────────────────────────────────────────────────────
  function cleanLaylaText(s) {
    if (typeof s !== 'string') return (s == null || s === undefined) ? '' : String(s);
    return s.replace(/\s*\[EARNED_TITLE:\s*[^\]]+\]\s*$/gi, '').trim();
  }
  window.cleanLaylaText = cleanLaylaText;

  function sanitizeHtml(html) {
    if (typeof html !== 'string') return '';
    if (typeof DOMPurify !== 'undefined') return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['p','br','strong','em','code','pre','ul','ol','li','a','h1','h2','h3','blockquote','span','div','table','thead','tbody','tr','th','td'], ALLOWED_ATTR: ['href','class'] });
    // Fallback: DOMPurify not loaded (should not happen — vendored locally)
    console.warn('sanitizeHtml: DOMPurify not available — using basic regex fallback');
    return html.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '').replace(/on\w+\s*=\s*["'][^"']*["']/gi, '').replace(/javascript:/gi, '').replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '').replace(/<object\b[^<]*(?:(?!<\/object>)<[^<]*)*<\/object>/gi, '').replace(/<embed\b[^>]*>/gi, '');
  }
  window.sanitizeHtml = sanitizeHtml;

  // ── Fetch with timeout ─────────────────────────────────────────────────────
  async function fetchWithTimeout(url, options, timeoutMs) {
    if (options === undefined) options = {};
    if (timeoutMs === undefined) timeoutMs = 12000;
    var tCtrl = new AbortController();
    var timer = setTimeout(function () {
      try { tCtrl.abort(); } catch (_) {}
    }, timeoutMs);
    var userSig = options && options.signal;
    var linked = new AbortController();
    function abortLinked() {
      try { linked.abort(); } catch (_) {}
    }
    tCtrl.signal.addEventListener('abort', abortLinked);
    if (userSig) {
      if (userSig.aborted) abortLinked();
      else userSig.addEventListener('abort', abortLinked);
    }
    try {
      var merged = Object.assign({}, options, { signal: linked.signal });
      return await fetch(url, merged);
    } finally {
      clearTimeout(timer);
      try { tCtrl.signal.removeEventListener('abort', abortLinked); } catch (_) {}
      if (userSig) try { userSig.removeEventListener('abort', abortLinked); } catch (_) {}
    }
  }
  window.fetchWithTimeout = fetchWithTimeout;

  // ── Toast notifications ────────────────────────────────────────────────────
  function showToast(msg, opts) {
    var t = document.createElement('div');
    t.className = 'toast';
    if (opts && opts.html) { t.innerHTML = msg; } else { t.textContent = msg; }
    document.body.appendChild(t);
    var duration = (opts && opts.duration) || 2200;
    setTimeout(function () { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; setTimeout(function () { t.remove(); }, 300); }, duration);
  }
  window.showToast = showToast;

  // ── DOM helper ─────────────────────────────────────────────────────────────
  function _setBoxHtml(id, html) {
    var el = document.getElementById(id);
    if (!el) return null;
    el.innerHTML = html;
    return el;
  }
  window._setBoxHtml = _setBoxHtml;

  // ── Styled modal replacements for native confirm/prompt (P4-4) ────────────
  function _createModalOverlay() {
    var overlay = document.createElement('div');
    overlay.className = 'layla-modal-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(2px);';
    return overlay;
  }

  function _createModalBox(msg) {
    var box = document.createElement('div');
    box.className = 'layla-modal-box';
    box.style.cssText = 'background:var(--bg-card,#1a1428);border:1px solid var(--accent,#7c5cbf);border-radius:8px;padding:24px;max-width:420px;width:90%;color:var(--text-main,#e0d8f0);font-family:inherit;box-shadow:0 8px 32px rgba(0,0,0,0.5);';
    var msgEl = document.createElement('div');
    msgEl.style.cssText = 'margin-bottom:16px;line-height:1.5;font-size:0.95rem;';
    msgEl.textContent = msg;
    box.appendChild(msgEl);
    return box;
  }

  function _createBtn(label, isPrimary) {
    var btn = document.createElement('button');
    btn.textContent = label;
    btn.style.cssText = 'padding:8px 20px;border-radius:4px;border:1px solid var(--accent,#7c5cbf);cursor:pointer;font-size:0.9rem;min-height:36px;margin-left:8px;' + (isPrimary ? 'background:var(--accent,#7c5cbf);color:#fff;' : 'background:transparent;color:var(--text-main,#e0d8f0);');
    return btn;
  }

  /**
   * laylaConfirm(msg) — Returns a Promise<boolean>. Styled modal replacement for confirm().
   */
  function laylaConfirm(msg) {
    return new Promise(function (resolve) {
      var overlay = _createModalOverlay();
      var box = _createModalBox(msg);
      var btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;';
      var cancelBtn = _createBtn('Cancel', false);
      var okBtn = _createBtn('OK', true);
      function cleanup(val) { try { overlay.remove(); } catch(_e){} resolve(val); }
      cancelBtn.onclick = function () { cleanup(false); };
      okBtn.onclick = function () { cleanup(true); };
      overlay.onclick = function (e) { if (e.target === overlay) cleanup(false); };
      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(okBtn);
      box.appendChild(btnRow);
      overlay.appendChild(box);
      document.body.appendChild(overlay);
      okBtn.focus();
    });
  }
  window.laylaConfirm = laylaConfirm;

  /**
   * laylaPrompt(msg, defaultVal) — Returns a Promise<string|null>. Styled modal replacement for prompt().
   */
  function laylaPrompt(msg, defaultVal) {
    return new Promise(function (resolve) {
      var overlay = _createModalOverlay();
      var box = _createModalBox(msg);
      var input = document.createElement('input');
      input.type = 'text';
      input.value = defaultVal || '';
      input.style.cssText = 'width:100%;padding:8px;border:1px solid var(--accent,#7c5cbf);border-radius:4px;background:var(--bg-main,#0e0a14);color:var(--text-main,#e0d8f0);font-size:0.9rem;box-sizing:border-box;margin-bottom:16px;';
      box.appendChild(input);
      var btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;';
      var cancelBtn = _createBtn('Cancel', false);
      var okBtn = _createBtn('OK', true);
      function cleanup(val) { try { overlay.remove(); } catch(_e){} resolve(val); }
      cancelBtn.onclick = function () { cleanup(null); };
      okBtn.onclick = function () { cleanup(input.value); };
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') cleanup(input.value); if (e.key === 'Escape') cleanup(null); });
      overlay.onclick = function (e) { if (e.target === overlay) cleanup(null); };
      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(okBtn);
      box.appendChild(btnRow);
      overlay.appendChild(box);
      document.body.appendChild(overlay);
      input.focus();
      input.select();
    });
  }
  window.laylaPrompt = laylaPrompt;

  window.laylaUtilsLoaded = true;
})();
