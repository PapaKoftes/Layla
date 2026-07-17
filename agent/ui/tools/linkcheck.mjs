/**
 * linkcheck.mjs — prove the Layla UI ES-module graph LINKS in Node, with no browser.
 *
 * WHY THIS EXISTS. The naive check `import('./main.js')` reports "document is not defined" for a perfectly
 * healthy app: that is a RUNTIME ReferenceError from evaluation, thrown long AFTER the module graph has
 * successfully linked. A genuine link failure — a missing named export, the exact bug that shipped a 100%
 * dead UI once — throws a `SyntaxError: ... does not provide an export named 'X'` during INSTANTIATION,
 * before any code runs. The bare command cannot tell those two apart, so it fails on both.
 *
 * This harness installs the minimal browser globals main.js touches at import time and pins
 * document.readyState = 'loading' so main.js registers its DOMContentLoaded listener instead of running the
 * full init() (which needs a real DOM). Top-level module code then evaluates to completion. Outcome:
 *   - resolves            -> LINK OK   (every import resolved, every named export exists, top-level ran)
 *   - SyntaxError export  -> LINK FAILED — a real missing/renamed export
 *   - other runtime error -> a genuine top-level crash worth seeing (printed verbatim)
 */

function makeClassList() {
  const s = new Set();
  return {
    add: (...c) => c.forEach((x) => s.add(x)),
    remove: (...c) => c.forEach((x) => s.delete(x)),
    toggle: (c, on) => { const has = s.has(c); const want = on === undefined ? !has : !!on; if (want) s.add(c); else s.delete(c); return want; },
    contains: (c) => s.has(c),
  };
}

function makeEl() {
  const el = {
    style: {}, dataset: {}, classList: makeClassList(), children: [], attributes: {},
    value: '', textContent: '', innerHTML: '', hidden: false, disabled: false, checked: false,
    setAttribute(k, v) { this.attributes[k] = v; }, getAttribute(k) { return this.attributes[k] ?? null; },
    removeAttribute(k) { delete this.attributes[k]; },
    appendChild(c) { this.children.push(c); return c; }, removeChild() {}, remove() {}, prepend() {},
    addEventListener() {}, removeEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return []; }, closest() { return null; }, click() {}, focus() {}, blur() {},
    insertAdjacentHTML() {}, cloneNode() { return makeEl(); }, getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 }; },
    setProperty() {}, scrollIntoView() {}, contains() { return false; },
  };
  return el;
}

const noopStore = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear(), key: () => null, get length() { return m.size; } };
};

const documentStub = {
  readyState: 'loading', // KEY: keeps main.js from running full init() — it registers a listener instead
  documentElement: makeEl(),
  head: makeEl(),
  body: makeEl(),
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return makeEl(); },
  createElementNS() { return makeEl(); },
  createDocumentFragment() { return makeEl(); },
  createTextNode() { return makeEl(); },
  addEventListener() {},
  removeEventListener() {},
  getElementsByClassName() { return []; },
  getElementsByTagName() { return []; },
  cookie: '',
};

// Some of these are read-only getters on globalThis in modern Node (navigator, location) — install them
// with defineProperty so the assignment cannot fail. The rest are plain assignable globals.
function def(name, value) {
  try { globalThis[name] = value; }
  catch (_) { try { Object.defineProperty(globalThis, name, { value, configurable: true, writable: true }); } catch (__) {} }
}

globalThis.document = documentStub;
globalThis.localStorage = noopStore();
globalThis.sessionStorage = noopStore();
def('navigator', { userAgent: 'node-linkcheck', language: 'en', languages: ['en'], onLine: true, clipboard: {}, serviceWorker: { register() { return Promise.resolve(); }, addEventListener() {} } });
def('location', { href: 'http://localhost/ui/', origin: 'http://localhost', pathname: '/ui/', search: '', hash: '', reload() {}, assign() {}, replace() {} });
globalThis.fetch = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}), text: () => Promise.resolve('') });
globalThis.EventSource = class { constructor() {} close() {} addEventListener() {} };
globalThis.WebSocket = class { constructor() {} close() {} send() {} addEventListener() {} };
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 0);
globalThis.cancelAnimationFrame = () => {};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } };
globalThis.Event = class { constructor(type) { this.type = type; } };
globalThis.IntersectionObserver = class { observe() {} disconnect() {} unobserve() {} };
globalThis.ResizeObserver = class { observe() {} disconnect() {} unobserve() {} };
globalThis.alert = () => {};
globalThis.confirm = () => true;
globalThis.prompt = () => null;

// `window` is the same surface as globalThis for the app's purposes.
const win = globalThis;
win.window = win;
win.addEventListener = () => {};
win.removeEventListener = () => {};
win.dispatchEvent = () => true;
win.setTimeout = win.setTimeout || ((cb) => cb && 0);
win.scrollTo = () => {};

// Resolve the entry against the CWD (not this tool's dir), so `node tools/linkcheck.mjs ./main.js` run
// from ui/ imports ui/main.js as intended.
import { pathToFileURL } from 'node:url';
const arg = process.argv[2] || './main.js';
const entry = /^([a-z]+:)?\//i.test(arg) ? arg : new URL(arg, pathToFileURL(process.cwd() + '/')).href;
import(entry)
  .then(() => { console.log('LINK OK'); process.exit(0); })
  .catch((e) => {
    const msg = String(e && e.message || e);
    const isLinkError = e instanceof SyntaxError && /does not provide an export|Cannot find module|Unexpected|import/i.test(msg);
    if (isLinkError) {
      console.error('LINK FAILED (module graph did not link):', msg);
    } else {
      console.error('EVALUATION ERROR (graph linked, top-level threw):', e && e.stack || msg);
    }
    process.exit(1);
  });
