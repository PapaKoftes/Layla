/**
 * test_first_run.mjs — EXECUTES the real first-run tour code (setup.js) against a stub DOM.
 *
 * This is deliberately NOT a text grep. The previous attempt shipped 24 tests that read the .js as TEXT and
 * passed against a 100%-dead app. This imports the actual ES module, calls its real exported functions, and
 * asserts on the DOM they mutate — so if the tour stops rendering, or the Ctrl+K step vanishes, or the claim
 * guard stops holding, THIS fails. tests/test_first_run_tour.py runs it under pytest.
 *
 * Exit 0 = all assertions passed; non-zero + a printed reason = failure.
 */

// ── minimal DOM with a real element registry ────────────────────────────────
function classList() {
  const s = new Set();
  return {
    _s: s,
    add: (...c) => c.forEach((x) => s.add(x)),
    remove: (...c) => c.forEach((x) => s.delete(x)),
    toggle: (c, on) => { const want = on === undefined ? !s.has(c) : !!on; if (want) s.add(c); else s.delete(c); return want; },
    contains: (c) => s.has(c),
  };
}
function makeEl(id) {
  return {
    id: id || '', style: {}, dataset: {}, classList: classList(), attributes: {}, children: [],
    value: '', textContent: '', innerHTML: '', hidden: false, disabled: false, checked: false,
    setAttribute(k, v) { this.attributes[k] = v; }, getAttribute(k) { return this.attributes[k] ?? null; },
    removeAttribute(k) { delete this.attributes[k]; },
    appendChild(c) { this.children.push(c); return c; }, removeChild() {}, remove() {},
    addEventListener() {}, removeEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return []; }, closest() { return null; }, click() {}, focus() {}, blur() {},
    contains() { return false; },
  };
}
const REG = new Map();
function reg(id) { const e = makeEl(id); REG.set(id, e); return e; }
// The tour markup the fix added to index.html:
reg('tour-overlay'); reg('tour-text'); reg('tour-next'); reg('tour-done');
// Present so the wizard-visibility check in the guard has something to read:
reg('wizard-overlay');

const store = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear() }; };

globalThis.document = {
  readyState: 'complete', documentElement: makeEl(), head: makeEl(), body: makeEl(),
  getElementById: (id) => (REG.has(id) ? REG.get(id) : null),
  querySelector: () => null, querySelectorAll: () => [], createElement: () => makeEl(),
  addEventListener() {}, removeEventListener() {},
};
globalThis.localStorage = store();
function def(name, value) { try { globalThis[name] = value; } catch (_) { Object.defineProperty(globalThis, name, { value, configurable: true, writable: true }); } }
def('navigator', { userAgent: 'node', language: 'en' });
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};

// ── assertions ──────────────────────────────────────────────────────────────
let failed = 0;
function check(name, cond) { if (cond) { console.log('  ok  ' + name); } else { failed++; console.error('  XX  ' + name); } }

const setup = await import('../components/setup.js');
const overlay = REG.get('tour-overlay');
const textEl = REG.get('tour-text');
const nextBtn = REG.get('tour-next');
const doneBtn = REG.get('tour-done');

// 1) The wizard owns first-run: the tour must NOT open while the claim is not released.
window._laylaFirstRunClaim = 'showing';
localStorage.removeItem('layla_onboarding_v1_done');
setup.maybeStartTour();
check('tour stays hidden while wizard claim=showing', !overlay.classList.contains('visible'));

// 2) Once released, the tour opens and shows step 0 (workspace scoping).
window._laylaFirstRunClaim = 'released';
setup.maybeStartTour();
check('tour opens when claim=released', overlay.classList.contains('visible'));
check('step 0 explains the workspace', /workspace/i.test(textEl.textContent));
check('step 0 shows Next, hides Got it', nextBtn.style.display !== 'none' && doneBtn.style.display === 'none');

// 3) Step through — the last step MUST teach Ctrl+K (the only entry point to 21 features).
setup.tourNext();
check('step 1 points at the aspect sidebar', /sidebar|facet|voice/i.test(textEl.textContent));
setup.tourNext();
check('step 2 explains the aspect lock', /padlock|lock/i.test(textEl.textContent));
setup.tourNext();
check('final step teaches Ctrl+K', /ctrl\+k|command palette/i.test(textEl.textContent));
check('final step shows Got it, hides Next', doneBtn.style.display !== 'none' && nextBtn.style.display === 'none');

// 4) Dismiss persists the "seen" marker and hides the tour.
setup.dismissTour();
check('dismiss hides the tour', !overlay.classList.contains('visible'));
check('dismiss writes the onboarding-done marker', localStorage.getItem('layla_onboarding_v1_done') === '1');

// 5) A returning user (marker set) is not re-shown.
overlay.classList.remove('visible');
setup.maybeStartTour();
check('tour does not reopen once the marker is set', !overlay.classList.contains('visible'));

if (failed) { console.error(`\nFIRST-RUN TOUR: ${failed} assertion(s) FAILED`); process.exit(1); }
console.log('\nFIRST-RUN TOUR: all assertions passed');
