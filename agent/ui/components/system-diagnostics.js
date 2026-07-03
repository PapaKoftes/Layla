/**
 * components/system-diagnostics.js — System surface (GUI rebuild, P4).
 *
 * Surfaces backend telemetry that had no UI: reasoning cost (cot_stats), the metrics
 * summary, the security audit, and doctor/capabilities — one calm overlay opened via
 * ⌘K → "System diagnostics". Vanilla ES module; styled from the G1 tokens; fetches use
 * relative URLs so they hit the serving app (auth is applied by the patched fetch).
 */

let _root = null;
let _open = false;

const SECTIONS = [
  // `pick` extracts a dot-path from the response before rendering (e.g. the governor/
  // optimizer metrics live under system_optimizer in the big /health payload).
  { key: 'resources', title: 'resources (governor)', url: '/health', pick: 'system_optimizer.metrics' },
  { key: 'cot', title: 'reasoning cost', url: '/agent/cot_stats' },
  { key: 'metrics', title: 'metrics', url: '/metrics/summary' },
  { key: 'security', title: 'security audit', url: '/metrics/security' },
  { key: 'caps', title: 'capabilities', url: '/doctor/capabilities' },
];

function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function _renderValue(v) {
  if (v == null) return '—';
  if (Array.isArray(v)) return v.length ? v.length + ' item' + (v.length === 1 ? '' : 's') : 'none';
  if (typeof v === 'object') {
    const n = Object.keys(v).length;
    return n ? n + ' field' + (n === 1 ? '' : 's') : 'none';
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2);
  const s = String(v);
  return s.length > 90 ? s.slice(0, 90) + '…' : s;
}

// Flatten to leaf rows: small non-empty nested objects expand (dot-prefixed) so the
// useful values (e.g. split_config.reasoning_model) show instead of "3 fields".
function _flatten(data, prefix, rows, depth) {
  for (const [k, v] of Object.entries(data)) {
    if (k.startsWith('_')) continue;
    const key = prefix ? prefix + '.' + k : k;
    const isPlainObj = v && typeof v === 'object' && !Array.isArray(v);
    const size = isPlainObj ? Object.keys(v).length : 0;
    if (isPlainObj && size > 0 && size <= 8 && depth < 2) {
      _flatten(v, key, rows, depth + 1);
    } else {
      rows.push([key, _renderValue(v)]);
    }
  }
}

function _renderData(data) {
  if (data == null) return '<div class="sysdiag-muted">no data</div>';
  if (typeof data !== 'object') return '<div class="sysdiag-row"><span class="v">' + _esc(data) + '</span></div>';
  const rows = [];
  _flatten(data, '', rows, 0);
  if (!rows.length) return '<div class="sysdiag-muted">empty</div>';
  return rows.map(([k, v]) =>
    '<div class="sysdiag-row"><span class="k">' + _esc(k) + '</span><span class="v">' + _esc(v) + '</span></div>'
  ).join('');
}

function _build() {
  if (_root) return;
  _root = document.createElement('div');
  _root.id = 'sysdiag';
  _root.className = 'cmdp-backdrop sysdiag-backdrop';
  _root.setAttribute('role', 'dialog');
  _root.setAttribute('aria-modal', 'true');
  _root.setAttribute('aria-label', 'System diagnostics');
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">∴</span>' +
        '<span class="sysdiag-title">system diagnostics</span>' +
        '<button type="button" class="sysdiag-refresh" aria-label="Refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="sysdiag-list">' +
        SECTIONS.map((s) =>
          '<section class="sysdiag-card" id="sysdiag-' + s.key + '">' +
            '<div class="sysdiag-card-title">' + _esc(s.title) + '</div>' +
            '<div class="sysdiag-body"><div class="sysdiag-muted">loading…</div></div>' +
          '</section>'
        ).join('') +
      '</div>' +
    '</div>';
  document.body.appendChild(_root);
  _root.addEventListener('mousedown', (e) => { if (e.target === _root) closeSystemDiagnostics(); });
  _root.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeSystemDiagnostics(); } });
  const refresh = _root.querySelector('.sysdiag-refresh');
  if (refresh) refresh.addEventListener('click', _load);
}

async function _load() {
  for (const s of SECTIONS) {
    const body = _root.querySelector('#sysdiag-' + s.key + ' .sysdiag-body');
    if (!body) continue;
    try {
      const r = await fetch(s.url, { headers: { Accept: 'application/json' } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      let data = await r.json();
      if (s.pick) data = s.pick.split('.').reduce((o, k) => (o == null ? o : o[k]), data);
      body.innerHTML = _renderData(data);
    } catch (e) {
      body.innerHTML = '<div class="sysdiag-err">unavailable — ' + _esc(e.message) + '</div>';
    }
  }
}

export function openSystemDiagnostics() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _load();
}

export function closeSystemDiagnostics() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

// Exposed for the generic renderer to be unit/inspect-testable without a live fetch.
export const _internals = { _renderData, _renderValue };
