"""BL-301b (UI half) — the aspect bar and @mention must resolve a custom aspect's NAME.

This EXECUTES the real UI modules in Node against a stub DOM (the idiom ui/tools/test_first_run.mjs
established), it is not a text grep. The bug it pins was invisible to text tests: `aspect.js` really
did export an `ASPECTS` array and `app.js` really did search it — the array simply only ever held the
6 built-ins, so a persona the operator had just created resolved nowhere.

What runs here:
  • aspect.js::mergeCustomAspects / resolveAspectRef / renderCustomAspectBar — the roster + the bar
  • input.js::onInputChange                                                  — the @mention dropdown
  • app.js::resolveLeadingMention                                            — @mention on send

Revert the merge (make mergeCustomAspects a no-op, or restore the hardcoded 6-entry search in
app.js) and this fails: the roster stays at 6, `@sable` resolves to null, and the bar renders no
custom button.

The harness is generated into tmp_path rather than committed under ui/tools/ so it cannot drift out
of sync with the assertions it exists for.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent / "ui"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


_HARNESS = r"""
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const UI = process.argv[2];
const url = (rel) => pathToFileURL(path.join(UI, rel)).href;

// ── minimal DOM ─────────────────────────────────────────────────────────────
function classList(el) {
  const s = new Set();
  const sync = () => { el._class = Array.from(s).join(' '); };
  return {
    add: (...c) => { c.forEach(x => x && s.add(x)); sync(); },
    remove: (...c) => { c.forEach(x => s.delete(x)); sync(); },
    toggle: (c, on) => { const want = on === undefined ? !s.has(c) : !!on; if (want) s.add(c); else s.delete(c); sync(); return want; },
    contains: (c) => s.has(c),
  };
}

function matches(el, sel) {
  if (!el || !sel || el.nodeType === 3) return false;
  if (sel[0] === '.') return String(el.className || '').split(/\s+/).indexOf(sel.slice(1)) >= 0;
  if (sel[0] === '#') return el.id === sel.slice(1);
  if (sel[0] === '[') {
    const name = sel.slice(1, -1).split('=')[0];
    return Object.prototype.hasOwnProperty.call(el.attributes || {}, name);
  }
  return String(el.tagName || '').toLowerCase() === sel.toLowerCase();
}

function makeEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    id: '', className: '', type: '', value: '', textContent: '', innerHTML: '',
    hidden: false, disabled: false, checked: false,
    style: { setProperty() {} }, dataset: {}, attributes: {}, children: [], _listeners: {},
    classList: null,
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null; },
    removeAttribute(k) { delete this.attributes[k]; },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); },
    remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    prepend() {}, insertBefore(c) { return this.appendChild(c); },
    addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); },
    removeEventListener() {},
    querySelectorAll(sel) {
      const out = [];
      const walk = (n) => (n.children || []).forEach((c) => { if (matches(c, sel)) out.push(c); walk(c); });
      walk(this);
      return out;
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    closest() { return null; }, click() {}, focus() {}, blur() {}, contains() { return false; },
    scrollIntoView() {}, insertAdjacentHTML() {}, cloneNode() { return makeEl(tag); },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 }; },
  };
  el.classList = classList(el);
  Object.defineProperty(el, 'className', {
    get() { return this._class || ''; },
    set(v) { this._class = String(v || ''); },
    configurable: true,
  });
  return el;
}

const REG = new Map();
function reg(id, tag) { const e = makeEl(tag); e.id = id; REG.set(id, e); return e; }

const sidebar = reg('sidebar-voices');
const mentionDd = reg('mention-dropdown');
reg('sidebar-voices-active');
reg('aspect-badge');
reg('topbar-aspect-badge');
reg('msg-input', 'textarea');

const store = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), clear: () => m.clear(), key: () => null, get length() { return m.size; } }; };

globalThis.document = {
  readyState: 'loading',   // keeps aspect.js from auto-fetching at import time
  documentElement: makeEl(), head: makeEl(), body: makeEl(),
  getElementById: (id) => (REG.has(id) ? REG.get(id) : null),
  querySelector: () => null, querySelectorAll: () => [],
  createElement: (t) => makeEl(t), createElementNS: (n, t) => makeEl(t),
  createTextNode: (t) => ({ nodeType: 3, textContent: String(t), children: [] }),
  createDocumentFragment: () => makeEl(),
  addEventListener() {}, removeEventListener() {},
  getElementsByClassName: () => [], getElementsByTagName: () => [], cookie: '',
};
globalThis.localStorage = store();
globalThis.sessionStorage = store();
function def(name, value) {
  try { globalThis[name] = value; }
  catch (_) { try { Object.defineProperty(globalThis, name, { value, configurable: true, writable: true }); } catch (__) {} }
}
def('navigator', { userAgent: 'node', language: 'en', languages: ['en'], onLine: true, clipboard: {} });
def('location', { href: 'http://localhost/ui/', origin: 'http://localhost', protocol: 'http:', hostname: 'localhost', pathname: '/ui/', search: '', hash: '' });
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.EventSource = class { constructor() {} close() {} addEventListener() {} };
globalThis.MutationObserver = class { observe() {} disconnect() {} };
globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });

// fetch: only /character/custom-aspects matters here.
let CUSTOM_PAYLOAD = [];
globalThis.fetch = (u) => {
  const s = String(u || '');
  const body = s.indexOf('/character/custom-aspects') >= 0
    ? { ok: true, custom: CUSTOM_PAYLOAD, base_aspects: ['morrigan', 'nyx', 'echo', 'eris', 'cassandra', 'lilith'] }
    : {};
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve('') });
};

// ── assertions ──────────────────────────────────────────────────────────────
let failed = 0;
function check(name, cond) { if (cond) { console.log('  ok  ' + name); } else { failed++; console.error('  XX  ' + name); } }

const aspect = await import(url('components/aspect.js'));
const { ASPECTS } = aspect;
globalThis.ASPECTS = ASPECTS;   // compat.js does this in the real app

const SABLE = { id: 'sable', name: 'Sable', symbol: '☾', tagline: 'quiet, nocturnal, precise', base_aspect: 'nyx', color_primary: '#3a2a5a', custom: true };

// ── 1. the roster the aspect bar renders ────────────────────────────────────
const builtinIds = aspect.BUILTIN_ASPECT_IDS.slice();
check('starts with exactly the 6 built-ins', ASPECTS.length === 6 && builtinIds.length === 6);

aspect.mergeCustomAspects([SABLE]);
check('(b) custom aspect joins the roster the bar renders', ASPECTS.some(a => a.id === 'sable'));
check('(b) the 6 built-ins stay first and in order',
  ASPECTS.slice(0, 6).map(a => a.id).join(',') === builtinIds.join(','));
check('(b) the custom entry carries its own name + sigil',
  (ASPECTS.find(a => a.id === 'sable') || {}).name === 'Sable' &&
  (ASPECTS.find(a => a.id === 'sable') || {}).sym === '☾');

// ── 2. the bar actually grows a button ──────────────────────────────────────
const opts = sidebar.querySelectorAll('[data-custom-aspect]');
check('(b) the aspect bar renders a button for the custom aspect', opts.length === 1);
const btn = sidebar.querySelector('.aspect-btn');
check('(b) the button uses the btn-<id> delegation contract bootstrap.js reads',
  !!btn && btn.id === 'btn-sable' && btn.getAttribute('data-action') === 'setAspect' && btn.getAttribute('data-arg') === 'sable');
check('(b) the button is labelled with the custom NAME, not the id',
  !!btn && /Sable/.test(btn.children.map(c => c.textContent).join(' ')) &&
  /Sable/.test(btn.getAttribute('aria-label') || ''));

// ── 3. @mention resolution ──────────────────────────────────────────────────
check('(a) @mention resolves the custom id', (aspect.resolveAspectRef('@sable') || {}).id === 'sable');
check('(a) @mention resolves the custom NAME, any case', (aspect.resolveAspectRef('SABLE') || {}).id === 'sable');
check('(a) a genuine miss is still a miss', aspect.resolveAspectRef('@not_a_thing_zzz') === null);
check('built-in mentions unchanged', builtinIds.every(id => (aspect.resolveAspectRef('@' + id) || {}).id === id));

// ── 4. collisions must not shadow a built-in ────────────────────────────────
aspect.mergeCustomAspects([
  SABLE,
  { id: 'morrigan', name: 'Impostor', base_aspect: 'eris', custom: true },   // forged built-in id
  { id: 'morri', name: 'Morrigan', base_aspect: 'eris', custom: true },      // built-in display name
]);
check('(d) a custom row with a built-in ID is dropped',
  ASPECTS.filter(a => a.id === 'morrigan').length === 1 && ASPECTS[0].name === 'Morrigan' && !ASPECTS[0].custom);
check('(d) a custom NAMED like a built-in does not steal the name',
  (aspect.resolveAspectRef('Morrigan') || {}).id === 'morrigan' &&
  (aspect.resolveAspectRef('@morrigan') || {}).id === 'morrigan');
check('(d) the name-colliding custom is still reachable by its own id',
  (aspect.resolveAspectRef('morri') || {}).id === 'morri');

// ── 5. invalid / empty input is dropped, not rendered ───────────────────────
aspect.mergeCustomAspects([
  SABLE,
  { id: '' }, { id: '   ' }, { id: 'Bad Id!' }, { id: '9lives' }, { id: 'x' }, null, 'nope',
  { id: 'wisp', name: '   ' },
  { id: 'night_owl', name: 'Night Owl', base_aspect: 'nyx', custom: true },
]);
const ids = ASPECTS.map(a => a.id);
check('invalid ids never enter the roster',
  ids.indexOf('') < 0 && ids.indexOf('Bad Id!') < 0 && ids.indexOf('9lives') < 0 && ids.indexOf('x') < 0);
check('a blank name falls back to something addressable',
  (ASPECTS.find(a => a.id === 'wisp') || {}).name === 'Wisp');
check('underscore ids are first-class', (aspect.resolveAspectRef('night_owl') || {}).id === 'night_owl');

// ── 6. delete: re-merging without a row removes it from bar AND roster ──────
aspect.mergeCustomAspects([SABLE]);
check('(c) re-merge replaces the custom slice rather than appending',
  ASPECTS.length === 7 && aspect.resolveAspectRef('wisp') === null);
check('(c) the deleted aspect loses its bar button',
  sidebar.querySelectorAll('[data-custom-aspect]').length === 1);

// ── 7. the backend is the source of truth -> survives a reload ──────────────
CUSTOM_PAYLOAD = [SABLE];
aspect.mergeCustomAspects([]);                       // fresh page: roster starts as the 6 built-ins
check('(c) a fresh load starts from the built-ins only', ASPECTS.length === 6);
await aspect.initAspectRoster();                     // what boot does
check('(c) the custom aspect is re-hydrated from the backend after a reload',
  ASPECTS.some(a => a.id === 'sable') && (aspect.resolveAspectRef('@sable') || {}).id === 'sable');
check('(c) and its bar button comes back', sidebar.querySelectorAll('[data-custom-aspect]').length === 1);

// ── 8. the @mention DROPDOWN offers it ──────────────────────────────────────
const input = await import(url('components/input.js'));
input.onInputChange({ target: { value: 'hey @sab' } });
check('(a) the @mention dropdown offers the custom aspect',
  /data-id="sable"/.test(mentionDd.innerHTML) && /Sable/.test(mentionDd.innerHTML));
input.onInputChange({ target: { value: '@morr' } });
check('the dropdown still offers built-ins', /data-id="morrigan"/.test(mentionDd.innerHTML));

// operator-supplied text must not become markup in the dropdown
aspect.mergeCustomAspects([{ id: 'xss', name: '<img src=x onerror=alert(1)>', tagline: '"><b>t</b>', custom: true }]);
input.onInputChange({ target: { value: '@xs' } });
check('operator-supplied names are escaped in the dropdown',
  mentionDd.innerHTML.indexOf('<img') < 0 && mentionDd.innerHTML.indexOf('<b>') < 0 && /&lt;img/.test(mentionDd.innerHTML));

// ── 9. @mention on SEND ─────────────────────────────────────────────────────
aspect.mergeCustomAspects([SABLE, { id: 'night_owl', name: 'Night Owl', base_aspect: 'nyx', custom: true },
                           { id: 'morri', name: 'Morrigan', base_aspect: 'eris', custom: true }]);
const app = await import(url('components/app.js'));
let r = app.resolveLeadingMention('@sable what changed?');
check('(a) send-time @mention resolves the custom id', r.matched && r.aspectId === 'sable' && r.rest === 'what changed?');
r = app.resolveLeadingMention('@Sable hi');
check('(a) send-time @mention resolves the custom NAME', r.aspectId === 'sable');
r = app.resolveLeadingMention('@night_owl hi');
check('(a) send-time @mention accepts underscore ids', r.aspectId === 'night_owl');
r = app.resolveLeadingMention('@morrigan hi');
check('(d) send-time @morrigan still reaches the built-in', r.aspectId === 'morrigan');
r = app.resolveLeadingMention('@totally_unknown_zzz hi');
check('a send-time miss is reported, not silently routed', r.matched && !r.aspectId);
r = app.resolveLeadingMention('no mention here');
check('a plain message is untouched', !r.matched && r.rest === 'no mention here');

if (failed) { console.error(failed + ' assertion(s) failed'); process.exit(1); }
console.log('all assertions passed');
"""


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    script = tmp_path / "custom_aspect_roster.mjs"
    script.write_text(_HARNESS, encoding="utf-8")
    return subprocess.run(
        ["node", str(script), str(UI)],
        cwd=str(UI),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_custom_aspect_is_first_class_in_the_ui(tmp_path):
    proc = _run(tmp_path)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0 and "all assertions passed" in (proc.stdout or ""), (
        "A custom aspect is NOT first-class in the UI — the bar and/or @mention cannot resolve it:\n"
        + combined
    )
