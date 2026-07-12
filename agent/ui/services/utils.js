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
export function cleanLaylaText(s, messageAspect) {
  if (typeof s !== 'string') return (s == null || s === undefined) ? '' : String(s);
  var t = s.replace(/\s*\[EARNED_TITLE:\s*[^\]]+\]\s*$/gi, '');
  // Reasoning-model <think>/<reasoning> traces on a reloaded/older stored reply (paired + dangling).
  // MASK fenced code blocks first — a client-assembled JSON/plan message or a code EXAMPLE can legitimately
  // contain a "<reflection>…" string, and the un-anchored strip (esp. the dangling-tag "…to end") would
  // otherwise delete real code / the whole tail. Restore the blocks after the strip.
  var _fences = [];
  t = t.replace(/```[\s\S]*?```|~~~[\s\S]*?~~~/g, function (b) { _fences.push(b); return '' + (_fences.length - 1) + ''; });
  t = t.replace(/<(think|thinking|reasoning|scratchpad|reflection)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '');
  t = t.replace(/<(?:think|thinking|reasoning|scratchpad|reflection)\b[^>]*>[\s\S]*$/i, '').trim();
  t = t.replace(/(\d+)/g, function (_m, i) { return _fences[Number(i)] || ''; });
  // Defense-in-depth for the "two tags, one broken" leak: strip a leading persona/speaker label
  // the backend may have missed (older stored replies, non-stream/reload path). Name-GATED —
  // "Layla", a Layla sigil, or an aspect name must be present — so a real markdown heading
  // ("## Overview") or ordinary prose is never touched, and only when real prose follows. The
  // optional "(…)" OR "— Title"/"- Title"/", Title" after the name covers the decorated chip forms
  // ("Morrigan (Coding): …", "Morrigan — The Blade: …"). Loops for a stacked label pair.
  // The label's OPENING emphasis is captured as `em`; a trailing emphasis marker is consumed ONLY when
  // it matches that opening ("**Morrigan**:" / "**Morrigan:**") via the \k<em> backreference. Without an
  // opening emphasis, \k<em> matches empty (JS backref to a non-participating group), so the answer's OWN
  // leading bold is NOT eaten — parity with the backend guard (response_builder.py pat_colon `(?(em)…)`),
  // which fixes 'Morrigan: **Use a set.**' mangling to 'Use a set.**' (stranded closing '**').
  var lead = /^[ \t]*(?:>[ \t]*)?(?:#{1,6}[ \t]*)?(?<em>[*_]{1,2})?[ \t]*(?<label>(?:Layla\b[ \t]*)?(?:[⚔✦◎⚡⌖⊛]️?[ \t]*)?(?:(?:Layla|Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\b[ \t]*)?(?:\([^)\n]*\)[ \t]*|\[[^\]\n]{1,30}\][ \t]*)?(?:[-–—,][ \t]*[^:\n]{1,30}[ \t]*)?)(?:\k<em>)?[ \t]*(?::[ \t]*(?:\k<em>[ \t]*)?|\n+)/i;
  // Active-aspect gate (parity with the backend): a BARE 'Name:'/'Name\n'/'## Name' whose aspect is
  // NOT active is a definition subject ('Echo: a repetition of sound'), not a self-label — keep it.
  // Decorated forms (sigil/*_/paren/bracket/dash/comma) are unambiguous, strip. Prefer the MESSAGE's
  // own aspect (reload / a per-aspect deliberation card) over the global session aspect — otherwise a
  // historical reply's own bare label leaks when the session switched to a different aspect.
  var _cur = String(messageAspect || (typeof window !== 'undefined' && window.currentAspect) || '').toLowerCase();
  var _active = { layla: 1 }; if (_cur) _active[_cur] = 1;
  for (var _i = 0; _i < 2; _i++) {
    var m = t.match(lead);
    var _lbl = (m && m.groups && m.groups.label) || '';
    if (m && _lbl && (/[⚔✦◎⚡⌖⊛]/.test(_lbl) || /\b(?:Layla|Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\b/i.test(_lbl))) {
      var _decorated = /[*_()\[\]—–,]/.test(m[0]) || /[⚔✦◎⚡⌖⊛]/.test(m[0]);
      var _nm = (_lbl.match(/\b(Layla|Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\b/i) || [])[1];
      if (!_decorated && _nm && !_active[_nm.toLowerCase()]) { break; }   // non-active bare name → keep
      var rest = t.slice(m[0].length).replace(/^\s+/, '');
      if (rest) { t = rest; continue; }
    }
    break;
  }
  // A BARE leading sigil with no name/colon ("⚔ Fix it") is a decorated self-label the backend strips
  // (pat_dec Case 3); the name-gated lead regex needs a colon/newline terminator so it misses this,
  // which doubled the sigil inside a deliberation card whose header already prints the same glyph.
  t = t.replace(/^[ \t]*[⚔✦◎⚡⌖⊛]️?[ \t]+(?=\S)/, '');
  return t.trim();
}

let _classHookInstalled = false;

export function sanitizeHtml(html) {
  if (typeof html !== 'string') return '';
  if (typeof DOMPurify !== 'undefined') {
    // Restrict `class` to CODE-highlighting classes only. `class` is allow-listed so marked's
    // "<code class='language-python'>" survives, but that also let a model-echoed
    // "<span class='msg-facet-chip'>" render a spoofed, aspect-styled facet chip INSIDE the bubble
    // (the "two tags, one broken" symptom via HTML), and let any app utility class be applied. This
    // hook keeps only language-*/hljs classes; hljs re-adds its own classes to the live DOM after
    // sanitize (enhanceCodeBlocks), so nothing visual is lost.
    if (!_classHookInstalled && typeof DOMPurify.addHook === 'function') {
      DOMPurify.addHook('uponSanitizeAttribute', function (node, data) {
        if (data.attrName === 'class') {
          const kept = String(data.attrValue || '').split(/\s+/).filter(function (c) {
            return /^(?:language-[\w+#.-]+|hljs(?:-[\w-]+)?)$/.test(c);
          });
          data.attrValue = kept.join(' ');
          if (!data.attrValue) data.keepAttr = false;
        }
      });
      _classHookInstalled = true;
    }
    return DOMPurify.sanitize(html, {
      // h4/h5/h6/hr/del are inert structural markdown marked emits for "####".."######", "---" and
      // "~~strike~~"; without them DOMPurify (KEEP_CONTENT default) dropped the tag and flattened the
      // model's heading hierarchy / divider / strikethrough into plain prose. img/iframe/object stay
      // excluded on purpose (privacy/SSRF).
      ALLOWED_TAGS: ['p','br','strong','em','code','pre','ul','ol','li','a',
                     'h1','h2','h3','h4','h5','h6','hr','del','blockquote','span','div','table','thead',
                     'tbody','tr','th','td'],
      ALLOWED_ATTR: ['href','class'],
    });
  }
  // Fallback: DOMPurify not loaded (should not happen — vendored locally)
  console.warn('sanitizeHtml: DOMPurify not available — using basic regex fallback');
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    // Strip inline event handlers — QUOTED *and* UNQUOTED. The old regex required quotes, so a legal
    // HTML unquoted handler (onerror=alert(1)) survived this fallback and executed via innerHTML.
    .replace(/\son\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    // Neutralize <img>/<svg> entirely on the fallback path — they are the usual unquoted-onerror
    // XSS vector and are excluded from the allow-list above anyway.
    .replace(/<\/?(?:img|svg)\b[^>]*>/gi, '')
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
