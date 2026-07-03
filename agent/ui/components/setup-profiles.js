/**
 * components/setup-profiles.js — intent-driven Setup & Profiles wizard (W-S: BL-202/203/209).
 *
 * "What do you want to do?" (pick use-case profiles) → "Optional features" (enable + install
 * only what you need) → apply as the startup default. Opened during onboarding and later from
 * Settings (reconfigure). Reuses the palette/diagnostics overlay shell + G1 tokens; fetches are
 * relative (auth applied by the patched fetch).
 */

let _root = null;
let _open = false;
let _data = null; // { profiles, features }
let _step = 0;
const _selProfiles = new Set();
const _selFeatures = new Set();

function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function _profileImpliedFeatures() {
  const out = new Set();
  (_data ? _data.profiles : []).forEach((p) => {
    if (_selProfiles.has(p.id)) (p.features || []).forEach((f) => out.add(f));
  });
  return out;
}

function _build() {
  if (_root) return;
  _root = document.createElement('div');
  _root.id = 'setupwiz';
  _root.className = 'cmdp-backdrop sysdiag-backdrop';
  _root.setAttribute('role', 'dialog');
  _root.setAttribute('aria-modal', 'true');
  _root.setAttribute('aria-label', 'Set up Layla');
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel setupwiz-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">∴</span>' +
        '<span class="sysdiag-title setupwiz-title">set up layla</span>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="setupwiz-body"></div>' +
      '<div class="setupwiz-foot">' +
        '<button type="button" class="setupwiz-back sysdiag-refresh" hidden>back</button>' +
        '<span class="setupwiz-note"></span>' +
        '<button type="button" class="setupwiz-next setup-btn primary">continue</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(_root);
  _root.addEventListener('mousedown', (e) => { if (e.target === _root) closeSetupProfiles(); });
  _root.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeSetupProfiles(); } });
  _root.querySelector('.setupwiz-back').addEventListener('click', () => { _step = 0; _render(); });
  _root.querySelector('.setupwiz-next').addEventListener('click', _onNext);
}

function _render() {
  const body = _root.querySelector('.setupwiz-body');
  const back = _root.querySelector('.setupwiz-back');
  const next = _root.querySelector('.setupwiz-next');
  const note = _root.querySelector('.setupwiz-note');
  note.textContent = '';
  if (!_data) { body.innerHTML = '<div class="sysdiag-muted">loading…</div>'; back.hidden = true; return; }

  if (_step === 0) {
    back.hidden = true;
    next.textContent = 'continue';
    body.innerHTML = '<div class="setupwiz-q">what do you want to do?</div><div class="setupwiz-profiles"></div>';
    const wrap = body.querySelector('.setupwiz-profiles');
    _data.profiles.forEach((p) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'setupwiz-card' + (_selProfiles.has(p.id) ? ' is-sel' : '');
      card.innerHTML = '<span class="setupwiz-card-label"></span><span class="setupwiz-card-desc"></span>';
      card.querySelector('.setupwiz-card-label').textContent = p.label;
      card.querySelector('.setupwiz-card-desc').textContent = p.desc || '';
      card.addEventListener('click', () => {
        if (_selProfiles.has(p.id)) _selProfiles.delete(p.id); else _selProfiles.add(p.id);
        card.classList.toggle('is-sel');
      });
      wrap.appendChild(card);
    });
  } else {
    back.hidden = false;
    next.textContent = 'apply';
    // pre-seed features from chosen profiles the first time we land here
    _profileImpliedFeatures().forEach((f) => _selFeatures.add(f));
    body.innerHTML = '<div class="setupwiz-q">optional features — enable only what you need</div><div class="setupwiz-features"></div>';
    const wrap = body.querySelector('.setupwiz-features');
    _data.features.forEach((f) => {
      const row = document.createElement('label');
      row.className = 'setupwiz-frow';
      const size = f.size_mb ? ' · ' + (f.size_mb >= 1000 ? (f.size_mb / 1000).toFixed(1) + ' GB' : f.size_mb + ' MB') : '';
      const needs = (f.deps && f.deps.length) ? ' · installs: ' + f.deps.join(', ') : '';
      row.innerHTML =
        '<input type="checkbox" class="setupwiz-fcheck"' + (_selFeatures.has(f.id) ? ' checked' : '') + ' />' +
        '<span class="setupwiz-fmain"><span class="setupwiz-flabel"></span>' +
        '<span class="setupwiz-fdesc"></span></span>' +
        '<span class="setupwiz-fmeta">' + _esc(size + needs).replace(/^ · /, '') + '</span>';
      row.querySelector('.setupwiz-flabel').textContent = f.label;
      row.querySelector('.setupwiz-fdesc').textContent = f.unlocks || '';
      row.querySelector('.setupwiz-fcheck').addEventListener('change', (e) => {
        if (e.target.checked) _selFeatures.add(f.id); else _selFeatures.delete(f.id);
      });
      wrap.appendChild(row);
    });
  }
}

async function _onNext() {
  if (_step === 0) {
    if (!_selProfiles.size) { _root.querySelector('.setupwiz-note').textContent = 'pick at least one'; return; }
    _step = 1;
    _render();
    return;
  }
  // apply
  const note = _root.querySelector('.setupwiz-note');
  note.textContent = 'applying…';
  try {
    const r = await fetch('/setup/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profiles: [..._selProfiles], features: [..._selFeatures] }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'apply failed');
    const n = (d.features || []).length;
    note.textContent = '✓ configured — ' + n + ' feature' + (n === 1 ? '' : 's') + ' enabled';
    note.setAttribute('data-ok', 'true');
    if (typeof window.showToast === 'function') window.showToast('Layla configured for you — ' + (d.profiles || []).join(', '));
    setTimeout(closeSetupProfiles, 1200);
  } catch (e) {
    note.textContent = 'error — ' + (e && e.message ? e.message : e);
  }
}

export async function openSetupProfiles() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _step = 0;
  _render();
  try {
    const r = await fetch('/setup/profiles', { headers: { Accept: 'application/json' } });
    _data = await r.json();
  } catch (e) {
    _data = { profiles: [], features: [] };
  }
  if (_open) _render();
}

export function closeSetupProfiles() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}
