/**
 * services/utils.js — Shared utility functions for Layla UI.
 *
 * Converted from js/layla-utils.js (IIFE → ES module).
 * All 20+ consumer files depend on these functions.
 */

// ── Debug logging ────────────────────────────────────────────────────────────
let LAYLA_DEBUG = false;
try {
  LAYLA_DEBUG = (localStorage.getItem('layla_debug') === '1')
    || (location.search.indexOf('layla_debug') !== -1);
} catch (_) {}

export { LAYLA_DEBUG };

export function _dbg(...args) {
  if (!LAYLA_DEBUG) return;
  try { console.log('[Layla]', ...args); } catch (_) {}
}

// ── HTML escaping ────────────────────────────────────────────────────────────
export function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Text cleaning ────────────────────────────────────────────────────────────
export function cleanLaylaText(s) {
  if (typeof s !== 'string') return (s == null || s === undefined) ? '' : String(s);
  var t = s.replace(/\s*\[EARNED_TITLE:\s*[^\]]+\]\s*$/gi, '');
  // Defense-in-depth for the "two tags, one broken" leak: strip a leading persona/speaker label
  // the backend may have missed (older stored replies, non-stream/reload path). Name-GATED —
  // "Layla", a Layla sigil, or an aspect name must be present — so a real markdown heading
  // ("## Overview") or ordinary prose is never touched, and only when real prose follows.
  var lead = /^[ \t]*(?:>[ \t]*)?(?:#{1,3}[ \t]*)?(?:[*_]{1,2}[ \t]*)?((?:Layla\b[ \t]*)?(?:[⚔✦◎⚡⌖⊛][ \t]*)?(?:(?:Layla|Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\b[ \t]*)?)(?:[*_]{1,2})?[ \t]*(?::[ \t]*(?:[*_]{1,2}[ \t]*)?|\n+)/i;
  var m = t.match(lead);
  if (m && m[1] && (/[⚔✦◎⚡⌖⊛]/.test(m[1]) || /\b(?:Layla|Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\b/i.test(m[1]))) {
    var rest = t.slice(m[0].length).replace(/^\s+/, '');
    if (rest) t = rest;
  }
  return t.trim();
}

export function sanitizeHtml(html) {
  if (typeof html !== 'string') return '';
  if (typeof DOMPurify !== 'undefined') {
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: ['p','br','strong','em','code','pre','ul','ol','li','a',
                     'h1','h2','h3','blockquote','span','div','table','thead',
                     'tbody','tr','th','td'],
      ALLOWED_ATTR: ['href','class'],
    });
  }
  // Fallback: DOMPurify not loaded (should not happen — vendored locally)
  console.warn('sanitizeHtml: DOMPurify not available — using basic regex fallback');
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/on\w+\s*=\s*["'][^"']*["']/gi, '')
    .replace(/javascript:/gi, '')
    .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '')
    .replace(/<object\b[^<]*(?:(?!<\/object>)<[^<]*)*<\/object>/gi, '')
    .replace(/<embed\b[^>]*>/gi, '');
}

// ── Toast notifications ──────────────────────────────────────────────────────
export function showToast(msg, opts) {
  const t = document.createElement('div');
  t.className = 'toast';
  // a11y: announce to screen readers. Errors are assertive; everything else polite.
  const assertive = !!(opts && opts.assertive);
  t.setAttribute('role', assertive ? 'alert' : 'status');
  t.setAttribute('aria-live', assertive ? 'assertive' : 'polite');
  t.setAttribute('aria-atomic', 'true');
  if (opts && opts.html) { t.innerHTML = msg; } else { t.textContent = msg; }
  document.body.appendChild(t);
  const duration = (opts && opts.duration) || 2200;
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transition = 'opacity 0.3s';
    setTimeout(() => t.remove(), 300);
  }, duration);
}

// ── DOM helper ───────────────────────────────────────────────────────────────
export function _setBoxHtml(id, html) {
  const el = document.getElementById(id);
  if (!el) return null;
  el.innerHTML = html;
  return el;
}

// ── Styled modal replacements for confirm/prompt ─────────────────────────────
function _createModalOverlay() {
  const overlay = document.createElement('div');
  overlay.className = 'layla-modal-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(2px);';
  return overlay;
}

function _createModalBox(msg) {
  const box = document.createElement('div');
  box.className = 'layla-modal-box';
  box.style.cssText = 'background:var(--bg-card,#1a1428);border:1px solid var(--accent,#7c5cbf);border-radius:8px;padding:24px;max-width:420px;width:90%;color:var(--text-main,#e0d8f0);font-family:inherit;box-shadow:0 8px 32px rgba(0,0,0,0.5);';
  const msgEl = document.createElement('div');
  msgEl.style.cssText = 'margin-bottom:16px;line-height:1.5;font-size:0.95rem;';
  msgEl.textContent = msg;
  box.appendChild(msgEl);
  return box;
}

function _createBtn(label, isPrimary) {
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.style.cssText = 'padding:8px 20px;border-radius:4px;border:1px solid var(--accent,#7c5cbf);cursor:pointer;font-size:0.9rem;min-height:36px;margin-left:8px;'
    + (isPrimary ? 'background:var(--accent,#7c5cbf);color:#fff;' : 'background:transparent;color:var(--text-main,#e0d8f0);');
  return btn;
}

export function laylaConfirm(msg) {
  return new Promise((resolve) => {
    const overlay = _createModalOverlay();
    const box = _createModalBox(msg);
    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;';
    const cancelBtn = _createBtn('Cancel', false);
    const okBtn = _createBtn('OK', true);
    function cleanup(val) { try { overlay.remove(); } catch (_) {} resolve(val); }
    cancelBtn.onclick = () => cleanup(false);
    okBtn.onclick = () => cleanup(true);
    overlay.onclick = (e) => { if (e.target === overlay) cleanup(false); };
    btnRow.appendChild(cancelBtn);
    btnRow.appendChild(okBtn);
    box.appendChild(btnRow);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    okBtn.focus();
  });
}

export function laylaPrompt(msg, defaultVal) {
  return new Promise((resolve) => {
    const overlay = _createModalOverlay();
    const box = _createModalBox(msg);
    const input = document.createElement('input');
    input.type = 'text';
    input.value = defaultVal || '';
    input.style.cssText = 'width:100%;padding:8px;border:1px solid var(--accent,#7c5cbf);border-radius:4px;background:var(--bg-main,#0e0a14);color:var(--text-main,#e0d8f0);font-size:0.9rem;box-sizing:border-box;margin-bottom:16px;';
    box.appendChild(input);
    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;';
    const cancelBtn = _createBtn('Cancel', false);
    const okBtn = _createBtn('OK', true);
    function cleanup(val) { try { overlay.remove(); } catch (_) {} resolve(val); }
    cancelBtn.onclick = () => cleanup(null);
    okBtn.onclick = () => cleanup(input.value);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') cleanup(input.value);
      if (e.key === 'Escape') cleanup(null);
    });
    overlay.onclick = (e) => { if (e.target === overlay) cleanup(null); };
    btnRow.appendChild(cancelBtn);
    btnRow.appendChild(okBtn);
    box.appendChild(btnRow);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    input.focus();
    input.select();
  });
}
