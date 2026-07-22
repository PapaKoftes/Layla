/**
 * components/self-test.js — install self-test (GUI rebuild G5: "proof not a promise").
 *
 * Runs live checks and shows pass/fail with detail so onboarding can *prove* the install
 * works instead of promising it: database reachable, vector memory enabled, and the model
 * actually replies. Reuses the palette/diagnostics overlay shell; opened via ⌘K →
 * "Run self-test". Fetches are relative (auth applied by the patched fetch).
 */

let _root = null;
let _open = false;
let _running = false;

async function _health() {
  const r = await fetch('/health', { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

const CHECKS = [
  {
    key: 'db', label: 'database',
    fn: async () => { const h = await _health(); return { ok: !!h.db_ok, detail: h.db_ok ? 'sqlite reachable' : 'not reachable' }; },
  },
  {
    key: 'mem', label: 'vector memory',
    fn: async () => { const h = await _health(); return { ok: h.vector_store === 'enabled', detail: 'vector store: ' + (h.vector_store || 'off') }; },
  },
  {
    key: 'model', label: 'model replies',
    fn: async () => {
      const t0 = (window.performance && performance.now) ? performance.now() : 0;
      const r = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [{ role: 'user', content: 'Reply with exactly the word: ready' }], max_tokens: 12, temperature: 0 }),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      const txt = ((((j.choices || [])[0] || {}).message || {}).content || '').trim();
      const secs = t0 ? ((performance.now() - t0) / 1000).toFixed(1) + 's' : '';
      return { ok: !!txt, detail: txt ? '"' + txt.slice(0, 28) + '"' + (secs ? ' · ' + secs : '') : 'no reply' };
    },
  },
];

// BL-386: Escape must work regardless of where focus sits. A listener on _root only fires when the
// keydown target is _root or a descendant; on first-run / just-opened, focus is on <body>, so a _root
// listener never receives it and the 'esc' chip advertised an exit that never fired. Listen on
// document (capture), added on open and removed on close so it can never accumulate across opens.
function _onDocKeydown(e) {
  if (!_open) return;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeSelfTest(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement('div');
  _root.id = 'selftest';
  _root.className = 'cmdp-backdrop sysdiag-backdrop';
  _root.setAttribute('role', 'dialog');
  _root.setAttribute('aria-modal', 'true');
  _root.setAttribute('aria-label', 'Self-test');
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel selftest-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">✓</span>' +
        '<span class="sysdiag-title">self-test — proof it works</span>' +
        '<button type="button" class="sysdiag-refresh selftest-run">run</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="selftest-list">' +
        CHECKS.map((c) =>
          '<div class="selftest-row" id="selftest-' + c.key + '">' +
            '<span class="selftest-dot" data-state="idle">•</span>' +
            '<span class="selftest-label">' + c.label + '</span>' +
            '<span class="selftest-detail">—</span></div>'
        ).join('') +
      '</div>' +
      '<div class="selftest-summary" hidden></div>' +
    '</div>';
  document.body.appendChild(_root);
  _root.addEventListener('mousedown', (e) => { if (e.target === _root) closeSelfTest(); });
  _root.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeSelfTest(); } });
  // BL-386: the 'esc' chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector('.cmdp-esc');
  if (_escChip) {
    _escChip.setAttribute('role', 'button');
    _escChip.setAttribute('tabindex', '0');
    _escChip.setAttribute('aria-label', 'Close');
    _escChip.addEventListener('click', () => closeSelfTest());
    _escChip.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); closeSelfTest(); } });
  }
  _root.querySelector('.selftest-run').addEventListener('click', runSelfTest);
}

function _setRow(key, state, detail) {
  const row = _root.querySelector('#selftest-' + key);
  if (!row) return;
  const dot = row.querySelector('.selftest-dot');
  dot.setAttribute('data-state', state);
  dot.textContent = state === 'pass' ? '✓' : state === 'fail' ? '✕' : state === 'running' ? '…' : '•';
  if (detail != null) row.querySelector('.selftest-detail').textContent = detail;
}

export async function runSelfTest() {
  _build();
  if (_running) return;
  _running = true;
  const summary = _root.querySelector('.selftest-summary');
  summary.hidden = true;
  CHECKS.forEach((c) => _setRow(c.key, 'idle', '—'));
  let passed = 0;
  for (const c of CHECKS) {
    _setRow(c.key, 'running', 'checking…');
    try {
      const res = await c.fn();
      _setRow(c.key, res.ok ? 'pass' : 'fail', res.detail);
      if (res.ok) passed++;
    } catch (e) {
      _setRow(c.key, 'fail', 'error — ' + (e && e.message ? e.message : e));
    }
  }
  summary.hidden = false;
  const ok = passed === CHECKS.length;
  summary.textContent = ok ? 'ready — all ' + CHECKS.length + ' checks passed' : passed + '/' + CHECKS.length + ' passed';
  summary.setAttribute('data-ok', ok ? 'true' : 'false');
  _running = false;
  return { passed, total: CHECKS.length };
}

export function openSelfTest() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener('keydown', _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  runSelfTest();
}

export function closeSelfTest() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener('keydown', _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}
