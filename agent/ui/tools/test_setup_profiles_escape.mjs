/**
 * test_setup_profiles_escape.mjs — EXECUTES the real setup-profiles.js against a stub DOM (BL-386).
 *
 * NOT a text grep. It imports the actual ES module, calls its real exported openSetupProfiles()/
 * closeSetupProfiles(), and asserts on the DOM + document-listener registry they mutate. It pins the
 * three defects the operator hit on the "set up layla" modal:
 *
 *   1. Options RENDER (a good /setup/profiles load shows the profile cards, not zero).
 *   2. A FAILED/EMPTY load FAILS VISIBLY — an error message + retry + skip, never a silent empty
 *      forEach that leaves "pick at least one" forever and no way out.
 *   3. ESCAPE actually closes: a document-level keydown (focus on <body>) closes the modal, the "esc"
 *      chip click closes it, and the document listener is REMOVED on close (no accumulation across opens).
 *
 * Exit 0 = all assertions passed; non-zero + a printed reason = failure.
 */

// ── minimal DOM with per-element event registry + selector-stable querySelector ───────────────
function classList() {
  const s = new Set();
  return {
    add: (...c) => c.forEach((x) => s.add(x)),
    remove: (...c) => c.forEach((x) => s.delete(x)),
    toggle: (c, on) => { const has = s.has(c); const want = on === undefined ? !has : !!on; if (want) s.add(c); else s.delete(c); return want; },
    contains: (c) => s.has(c),
  };
}

function makeEl(tag) {
  const handlers = {};
  const el = {
    tagName: (tag || 'div').toUpperCase(), id: '', type: '',
    style: {}, dataset: {}, classList: classList(), children: [], attributes: {},
    value: '', textContent: '', hidden: false, disabled: false, checked: false,
    _html: '', _qs: new Map(),
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; this._qs = new Map(); this.children = []; },
    setAttribute(k, v) { this.attributes[k] = v; },
    getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; },
    removeAttribute(k) { delete this.attributes[k]; },
    appendChild(c) { this.children.push(c); return c; },
    removeChild() {}, remove() {}, prepend() {},
    addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    removeEventListener(type, fn) { if (handlers[type]) handlers[type] = handlers[type].filter((h) => h !== fn); },
    _fire(type, ev) { (handlers[type] || []).slice().forEach((fn) => fn(ev || { preventDefault() {}, stopPropagation() {}, target: el })); },
    click() { this._fire('click'); },
    focus() {}, blur() {}, closest() { return null; }, contains() { return false; },
    // Selector-STABLE: repeated queries for the same selector return the same child element, so
    // state set on a queried node (e.g. next.hidden) is observable on the next query. Cache clears
    // whenever innerHTML is reassigned (a re-render), matching real DOM replacement semantics.
    querySelector(sel) { if (!this._qs.has(sel)) { const c = makeEl(); this._qs.set(sel, c); } return this._qs.get(sel); },
    querySelectorAll() { return []; },
    _handlers: handlers,
  };
  return el;
}

// document with a real handler registry so we can assert add/remove of the Escape listener.
const docHandlers = []; // { type, fn, capture }
const documentStub = {
  readyState: 'complete', documentElement: makeEl(), head: makeEl(), body: makeEl(),
  getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag), createTextNode: () => makeEl(),
  addEventListener(type, fn, capture) { docHandlers.push({ type, fn, capture: !!capture }); },
  removeEventListener(type, fn, capture) {
    const i = docHandlers.findIndex((h) => h.type === type && h.fn === fn && h.capture === !!capture);
    if (i >= 0) docHandlers.splice(i, 1);
  },
};

function store() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear() };
}

globalThis.document = documentStub;
globalThis.localStorage = store();
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.dispatchEvent = () => true;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } };

// Controllable /setup/profiles response.
let _fetchMode = 'ok';
function setFetch(mode) { _fetchMode = mode; }
const GOOD = {
  profiles: [
    { id: 'companion', label: 'Companion', desc: 'x', features: [] },
    { id: 'coding', label: 'Coding partner', desc: 'x', features: [] },
    { id: 'language', label: 'Language learning', desc: 'x', features: [] },
    { id: 'research', label: 'Research', desc: 'x', features: [] },
    { id: 'power', label: 'Power user', desc: 'x', features: [] },
    { id: 'minimal', label: 'Minimal', desc: 'x', features: [] },
  ],
  features: [{ id: 'voice', label: 'Voice', unlocks: 'x', deps: [], size_mb: 0 }],
};
globalThis.fetch = (url) => {
  if (typeof url === 'string' && url.indexOf('/setup/profiles') >= 0) {
    if (_fetchMode === 'ok') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(GOOD) });
    if (_fetchMode === '404') return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: 'Not Found' }) });
    if (_fetchMode === 'reject') return Promise.reject(new Error('network down'));
    if (_fetchMode === 'empty') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ profiles: [], features: [] }) });
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, profiles: [], features: [] }) });
};

const tick = () => new Promise((r) => setTimeout(r, 0));

// ── assertions ────────────────────────────────────────────────────────────────
let failed = 0;
function check(name, cond) { if (cond) { console.log('  ok  ' + name); } else { failed++; console.error('  XX  ' + name); } }

const mod = await import('../components/setup-profiles.js');
const root = () => documentStub.body.children[0]; // _build appends _root to body
function docKeydownHandlers() { return docHandlers.filter((h) => h.type === 'keydown'); }
function fireDocEscape() {
  let prevented = false;
  const ev = { key: 'Escape', preventDefault() { prevented = true; }, stopPropagation() {} };
  docKeydownHandlers().forEach((h) => h.fn(ev));
  return prevented;
}

// 1) GOOD load: options render (6 cards), not a silent empty.
setFetch('ok');
await mod.openSetupProfiles();
await tick();
const r1 = root();
check('modal built + shown', r1 && r1.hidden === false);
const body1 = r1.querySelector('.setupwiz-body');
const wrap1 = body1.querySelector('.setupwiz-profiles');
check('OPTIONS RENDER — profile cards present (not zero)', wrap1.children.length === 6);
check('continue button is available in the normal path', r1.querySelector('.setupwiz-next').hidden === false);

// 2) ESCAPE via document (focus on <body>) CLOSES the modal + removes the listener (no leak).
check('a document keydown listener is registered while open', docKeydownHandlers().length >= 1);
const before = docKeydownHandlers().length;
fireDocEscape();
await tick();
check('document Escape CLOSES the modal', root().hidden === true);
check('document keydown listener REMOVED on close (no accumulation)', docKeydownHandlers().length === before - 1);

// 2b) Reopen — the listener count must not grow across opens (leak guard).
setFetch('ok');
await mod.openSetupProfiles();
await tick();
check('reopen registers exactly one keydown listener again', docKeydownHandlers().length === 1);

// 3) ESC CHIP click closes.
root().querySelector('.cmdp-esc').click();
await tick();
check('esc chip click CLOSES the modal', root().hidden === true);
check('esc chip click also removes the document listener', docKeydownHandlers().length === 0);

// 4) FAILED load (404) FAILS VISIBLY — error + retry + skip, and NO dead-end continue.
setFetch('404');
await mod.openSetupProfiles();
await tick();
const rErr = root();
const bodyErr = rErr.querySelector('.setupwiz-body');
check('failed load shows a visible error block', /couldn.t load/i.test(bodyErr.innerHTML));
check('failed load offers RETRY', /setupwiz-retry/.test(bodyErr.innerHTML));
check('failed load offers SKIP', /setupwiz-skip/.test(bodyErr.innerHTML));
check('failed load HIDES the dead-end continue button', rErr.querySelector('.setupwiz-next').hidden === true);
// Escape still works on the error screen (still escapable).
check('a document keydown listener is present on the error screen', docKeydownHandlers().length === 1);
fireDocEscape();
await tick();
check('Escape closes the error screen too', root().hidden === true);

// 4b) A network reject is treated the same visible way (not a crash / silent empty).
setFetch('reject');
await mod.openSetupProfiles();
await tick();
check('rejected fetch also fails visibly (error block)', /couldn.t load/i.test(root().querySelector('.setupwiz-body').innerHTML));
root().querySelector('.cmdp-esc').click();
await tick();

// 4c) RETRY recovers: from an error screen, a retry after the service comes back renders options.
setFetch('404');
await mod.openSetupProfiles();
await tick();
check('error screen before retry (no cards)', root().querySelector('.setupwiz-body').querySelector('.setupwiz-profiles').children.length === 0);
setFetch('ok');
root().querySelector('.setupwiz-body').querySelector('.setupwiz-retry').click();
await tick();
await tick();
check('RETRY after recovery renders the 6 options', root().querySelector('.setupwiz-body').querySelector('.setupwiz-profiles').children.length === 6);
root().querySelector('.cmdp-esc').click();
await tick();

if (failed) { console.error(`\nSETUP-PROFILES ESCAPE/EMPTY: ${failed} assertion(s) FAILED`); process.exit(1); }
console.log('\nSETUP-PROFILES ESCAPE/EMPTY: all assertions passed');
