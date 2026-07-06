/*
 * core/i18n.js — Layla frontend internationalization.
 *
 * A small, dependency-free i18n runtime:
 *   - t(key, params)          → translated string with {param} interpolation + pluralization
 *   - applyTranslations(root) → translate all [data-i18n*] nodes in a subtree
 *   - setLanguage(lang)       → switch language (loads catalog, sets <html lang/dir>, persists, re-applies)
 *   - initI18n()              → pick the initial language and translate the page
 *
 * Catalogs live at /layla-ui/locales/<lang>.json (served from agent/ui/locales/). English (en)
 * is always loaded as the fallback, so any missing key degrades to English, then to the key name.
 *
 * DOM markup:
 *   <span data-i18n="nav.settings">Settings</span>           → textContent
 *   <input data-i18n-placeholder="chat.placeholder">          → placeholder attribute
 *   <button data-i18n-aria-label="action.close">             → aria-label attribute
 *   <button data-i18n-title="action.close">                  → title attribute
 * Nodes keep their English text as the in-file default (also the value in en.json).
 */

const _BASE = '/layla-ui/locales';
const RTL_LANGS = new Set(['ar', 'he', 'fa', 'ur']);
export const SUPPORTED = ['en', 'es', 'de', 'fr', 'it', 'pt', 'ja', 'zh', 'ar', 'ru', 'ko'];

const _catalogs = {};      // lang -> flat {key: string}
let _lang = 'en';
let _fallback = {};        // en catalog (always loaded)

function _flatten(obj, prefix, out) {
  for (const k of Object.keys(obj || {})) {
    const key = prefix ? prefix + '.' + k : k;
    const v = obj[k];
    if (v && typeof v === 'object' && !Array.isArray(v)) _flatten(v, key, out);
    else out[key] = v;
  }
  return out;
}

async function _loadCatalog(lang) {
  if (_catalogs[lang]) return _catalogs[lang];
  try {
    const res = await fetch(`${_BASE}/${lang}.json`, { cache: 'no-cache' });
    if (!res.ok) throw new Error('http ' + res.status);
    _catalogs[lang] = _flatten(await res.json(), '', {});
  } catch (_e) {
    _catalogs[lang] = {};   // graceful: empty catalog → falls back to en → key
  }
  return _catalogs[lang];
}

export function currentLanguage() { return _lang; }
export function isRTL() { return RTL_LANGS.has(_lang); }

/** Translate a key. params interpolate {name} tokens. For plurals pass {count}; a key with a
 *  "<key>.other"/".one" pair is resolved by count (falls back to the bare key). */
export function t(key, params) {
  const dict = _catalogs[_lang] || {};
  let str;
  if (params && typeof params.count === 'number') {
    const form = params.count === 1 ? '.one' : '.other';
    str = dict[key + form] ?? _fallback[key + form] ?? dict[key] ?? _fallback[key] ?? key;
  } else {
    str = dict[key] ?? _fallback[key] ?? key;
  }
  if (params) {
    str = String(str).replace(/\{(\w+)\}/g, (m, p) => (p in params ? String(params[p]) : m));
  }
  return str;
}

/** Translate all [data-i18n*] nodes within root (default: whole document). */
export function applyTranslations(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-i18n]').forEach((el) => {
    const val = t(el.getAttribute('data-i18n'));
    if (val) el.textContent = val;
  });
  const attrs = { 'data-i18n-placeholder': 'placeholder', 'data-i18n-aria-label': 'aria-label', 'data-i18n-title': 'title' };
  for (const [dataAttr, realAttr] of Object.entries(attrs)) {
    scope.querySelectorAll('[' + dataAttr + ']').forEach((el) => {
      const val = t(el.getAttribute(dataAttr));
      if (val) el.setAttribute(realAttr, val);
    });
  }
}

/** Switch the active language: load its catalog, set <html lang/dir>, persist, re-translate. */
export async function setLanguage(lang, opts) {
  lang = (SUPPORTED.includes(lang) ? lang : 'en');
  await _loadCatalog(lang);
  _lang = lang;
  document.documentElement.setAttribute('lang', lang);
  document.documentElement.setAttribute('dir', RTL_LANGS.has(lang) ? 'rtl' : 'ltr');
  try { localStorage.setItem('layla_ui_language', lang); } catch (_) {}
  applyTranslations(document);
  try { window.dispatchEvent(new CustomEvent('layla:languagechange', { detail: { lang } })); } catch (_) {}
  // Best-effort: persist to the server config so it survives a fresh browser (not required to work).
  if (!opts || opts.persistServer !== false) {
    try {
      fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ui_language: lang }),
      }).catch(() => {});
    } catch (_) {}
  }
}

/** Pick the initial language: localStorage → server config (window.__laylaConfig) → navigator → en. */
export async function initI18n() {
  _fallback = await _loadCatalog('en');
  let lang = '';
  try { lang = localStorage.getItem('layla_ui_language') || ''; } catch (_) {}
  if (!lang && window.__laylaConfig && window.__laylaConfig.ui_language) lang = String(window.__laylaConfig.ui_language);
  if (!lang) {
    const nav = (navigator.language || 'en').slice(0, 2).toLowerCase();
    if (SUPPORTED.includes(nav)) lang = nav;
  }
  await setLanguage(lang || 'en', { persistServer: false });
}

// ── Locale-aware formatting helpers (Intl) ──────────────────────────────────
export function fmtNumber(n, options) {
  try { return new Intl.NumberFormat(_lang, options).format(n); } catch (_) { return String(n); }
}
export function fmtDate(d, options) {
  try { return new Intl.DateTimeFormat(_lang, options).format(d instanceof Date ? d : new Date(d)); }
  catch (_) { return String(d); }
}

// Expose on window for non-module (inline) callers + convenience.
try {
  window.t = t;
  window.i18n = { t, setLanguage, applyTranslations, currentLanguage, isRTL, fmtNumber, fmtDate, SUPPORTED };
} catch (_) {}
