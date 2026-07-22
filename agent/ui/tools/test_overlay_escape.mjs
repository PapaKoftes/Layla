/**
 * test_overlay_escape.mjs — EXECUTES all 21 ⌘K overlay modules against a stub DOM (BL-386 follow-up).
 *
 * Sibling of test_setup_profiles_escape.mjs. NOT a text grep: it imports each REAL ES module, calls its
 * real exported openX()/closeX(), and asserts on the DOM + the document-listener registry they mutate.
 *
 * The defect (fixed on setup-profiles.js, latent in ~20 others): the Escape handler lived on _root, which
 * never receives a keydown while focus is on <body> (the first-run / just-opened default), so the advertised
 * "esc" chip promised an exit that never fired. The fix mirrors setup-profiles.js exactly:
 *
 *   1. openX() registers a MODULE-LEVEL `_onDocKeydown` via document.addEventListener('keydown', fn, true),
 *      so Escape closes the overlay regardless of where focus sits.
 *   2. closeX() removes that same listener — no accumulation across open/close cycles (leak guard).
 *   3. the `.cmdp-esc` chip is a real button: a click (and Enter/Space) closes the overlay.
 *
 * For every overlay this pins: opens+shows, registers exactly one document keydown listener, a document
 * Escape (focus on <body>) closes it and REMOVES the listener, reopening does not accumulate listeners, and
 * the esc-chip click closes it too. Uses deltas against a per-module baseline so any listener registered by
 * an imported dependency (e.g. custom-aspect → aspect.js) cannot mask a leak.
 *
 * Exit 0 = all assertions passed; non-zero + a printed reason = failure.
 */

// Background _load() fetches run with stub data; their async settling is irrelevant to the Escape contract.
process.on('unhandledRejection', () => {});

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
    tagName: (tag || 'div').toUpperCase(), id: '', type: '', name: '',
    style: {}, dataset: {}, classList: classList(), children: [], attributes: {},
    value: '', textContent: '', hidden: false, disabled: false, checked: false,
    options: [], selectedOptions: [], offsetParent: null,
    _html: '', _qs: new Map(),
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; this._qs = new Map(); this.children = []; },
    setAttribute(k, v) { this.attributes[k] = v; if (k === 'id') this.id = v; },
    getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; },
    removeAttribute(k) { delete this.attributes[k]; },
    appendChild(c) { this.children.push(c); return c; },
    insertBefore(c) { this.children.push(c); return c; },
    removeChild() {}, remove() {}, prepend() {}, after() {}, before() {},
    addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    removeEventListener(type, fn) { if (handlers[type]) handlers[type] = handlers[type].filter((h) => h !== fn); },
    dispatchEvent() { return true; },
    _fire(type, ev) { (handlers[type] || []).slice().forEach((fn) => fn(ev || { preventDefault() {}, stopPropagation() {}, target: el })); },
    click() { this._fire('click'); },
    focus() {}, blur() {}, closest() { return null; }, contains() { return false; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0, right: 0, bottom: 0 }; },
    // Selector-STABLE: repeated queries for the same selector return the same child element, so a handler
    // attached to a queried node (e.g. the esc chip) is observable when the test re-queries + clicks it.
    querySelector(sel) { if (!this._qs.has(sel)) { const c = makeEl(); this._qs.set(sel, c); } return this._qs.get(sel); },
    querySelectorAll() { return []; },
    _handlers: handlers,
  };
  return el;
}

// document with a real handler registry so we can assert add/remove of the Escape listener.
const docHandlers = []; // { type, fn, capture }
function walkById(node, id) {
  if (!node || !node.children) return null;
  for (const c of node.children) {
    if (c && c.id === id) return c;
    const found = walkById(c, id);
    if (found) return found;
  }
  return null;
}
const documentStub = {
  readyState: 'complete', documentElement: makeEl('html'), head: makeEl('head'), body: makeEl('body'),
  getElementById(id) { return walkById(this.body, id); },
  querySelector: () => null, querySelectorAll: () => [],
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
globalThis.sessionStorage = store();
globalThis.window = globalThis;
globalThis.location = { href: 'http://localhost/', hostname: 'localhost', origin: 'http://localhost', search: '', pathname: '/', protocol: 'http:' };
if (!globalThis.navigator) globalThis.navigator = { userAgent: 'node', language: 'en', onLine: true };
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
globalThis.cancelAnimationFrame = () => {};
if (!globalThis.performance) globalThis.performance = { now: () => 0 };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.dispatchEvent = () => true;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } };
globalThis.Event = class { constructor(type, init) { this.type = type; Object.assign(this, init || {}); } };
globalThis.KeyboardEvent = class { constructor(type, init) { this.type = type; Object.assign(this, init || {}); } };
globalThis.AbortController = globalThis.AbortController || class { constructor() { this.signal = { addEventListener() {}, removeEventListener() {}, aborted: false }; } abort() {} };
globalThis.showToast = () => {};
globalThis.confirm = () => true;

// Every overlay fetch resolves to a benign envelope so open()'s background _load never throws in a way
// that matters; the Escape contract is independent of load success.
globalThis.fetch = () => Promise.resolve({
  ok: true, status: 200,
  json: () => Promise.resolve({ ok: true, profiles: [], features: [], items: [], tools: [], missions: [], cards: [], languages: [] }),
  text: () => Promise.resolve(''),
});

const tick = () => new Promise((r) => setTimeout(r, 0));

// ── the 21 overlays: module file, its _root id, and its open/close export names ─────────────────
const OVERLAYS = [
  { file: 'approvals',          id: 'approvals',    open: 'openApprovals',         close: 'closeApprovals' },
  { file: 'agent-tasks',        id: 'agenttasks',   open: 'openAgentTasks',        close: 'closeAgentTasks' },
  { file: 'custom-aspect',      id: 'customaspect', open: 'openCustomAspect',      close: 'closeCustomAspect' },
  { file: 'missions',           id: 'missions',     open: 'openMissions',          close: 'closeMissions' },
  { file: 'kb',                 id: 'kb',           open: 'openKb',                close: 'closeKb' },
  { file: 'codex',              id: 'codex',        open: 'openCodex',             close: 'closeCodex' },
  { file: 'journal',            id: 'journal',      open: 'openJournal',           close: 'closeJournal' },
  { file: 'improvements',       id: 'improvements', open: 'openImprovements',      close: 'closeImprovements' },
  { file: 'marketplace',        id: 'marketplace',  open: 'openMarketplace',       close: 'closeMarketplace' },
  { file: 'plans',              id: 'plans',        open: 'openPlans',             close: 'closePlans' },
  { file: 'intake-quiz',        id: 'intakequiz',   open: 'openIntakeQuiz',        close: 'closeIntakeQuiz' },
  { file: 'macros',             id: 'macros',       open: 'openMacros',            close: 'closeMacros' },
  { file: 'intelligence',       id: 'intelligence', open: 'openIntelligence',      close: 'closeIntelligence' },
  { file: 'self-test',          id: 'selftest',     open: 'openSelfTest',          close: 'closeSelfTest' },
  { file: 'german',             id: 'german',       open: 'openGerman',            close: 'closeGerman' },
  { file: 'sync',               id: 'sync',         open: 'openSync',              close: 'closeSync' },
  { file: 'system-diagnostics', id: 'sysdiag',      open: 'openSystemDiagnostics', close: 'closeSystemDiagnostics' },
  { file: 'tools-history',      id: 'toolshist',    open: 'openToolsHistory',      close: 'closeToolsHistory' },
  { file: 'tutor',              id: 'tutor',        open: 'openTutor',             close: 'closeTutor' },
  { file: 'verify',             id: 'verify',       open: 'openVerify',            close: 'closeVerify' },
  { file: 'debate',             id: 'debate',       open: 'openDebate',            close: 'closeDebate' },
];

// ── assertions ────────────────────────────────────────────────────────────────
let failed = 0;
function check(name, cond) { if (cond) { console.log('  ok  ' + name); } else { failed++; console.error('  XX  ' + name); } }
function docKeydownCount() { return docHandlers.filter((h) => h.type === 'keydown').length; }
function fireDocEscape() {
  const ev = { key: 'Escape', preventDefault() {}, stopPropagation() {} };
  docHandlers.filter((h) => h.type === 'keydown').slice().forEach((h) => h.fn(ev));
}

for (const ov of OVERLAYS) {
  const mod = await import('../components/' + ov.file + '.js');
  const open = mod[ov.open];
  const close = mod[ov.close];
  if (typeof open !== 'function' || typeof close !== 'function') {
    check(ov.file + ': exports ' + ov.open + '/' + ov.close, false);
    continue;
  }

  // Baseline: any keydown listeners already present (imports may register some) — measure deltas from here.
  const base = docKeydownCount();

  // 1) open → built + shown, and exactly one document keydown listener registered.
  await open();
  await tick();
  const root = documentStub.getElementById(ov.id);
  check(ov.file + ': opens + shows (root#' + ov.id + ' visible)', !!root && root.hidden === false);
  check(ov.file + ': registers exactly ONE document keydown listener on open', docKeydownCount() === base + 1);

  // 2) document Escape with focus on <body> closes it AND removes the listener (no leak).
  fireDocEscape();
  await tick();
  check(ov.file + ': document Escape CLOSES the overlay', !root || root.hidden === true);
  check(ov.file + ': document keydown listener REMOVED on close', docKeydownCount() === base);

  // 3) reopen — the listener count must not grow across opens (leak guard).
  await open();
  await tick();
  check(ov.file + ': reopen registers exactly ONE listener again (no accumulation)', docKeydownCount() === base + 1);

  // 4) esc-chip CLICK closes it (the chip advertised an exit — it must actually fire) + removes listener.
  const root2 = documentStub.getElementById(ov.id);
  const chip = root2 && root2.querySelector('.cmdp-esc');
  check(ov.file + ': has an .cmdp-esc chip', !!chip);
  if (chip) chip.click();
  await tick();
  check(ov.file + ': esc-chip CLICK closes the overlay', !root2 || root2.hidden === true);
  check(ov.file + ': esc-chip click also removes the document listener', docKeydownCount() === base);
}

if (failed) { console.error(`\nOVERLAY ESCAPE: ${failed} assertion(s) FAILED across ${OVERLAYS.length} overlays`); process.exit(1); }
console.log(`\nOVERLAY ESCAPE: all assertions passed for ${OVERLAYS.length} overlays`);
