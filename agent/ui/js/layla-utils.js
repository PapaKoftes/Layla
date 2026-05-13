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
    if (typeof DOMPurify !== 'undefined') return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['p','br','strong','em','code','pre','ul','ol','li','a','h1','h2','h3','blockquote','span','div'], ALLOWED_ATTR: ['href','class'] });
    return html.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '').replace(/on\w+\s*=\s*["'][^"']*["']/gi, '').replace(/javascript:/gi, '');
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

  window.laylaUtilsLoaded = true;
})();
