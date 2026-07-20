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
let _loadErr = ''; // non-empty when the last /setup/profiles load failed (drives the visible-error path)
let _step = 0;
const _selProfiles = new Set();
const _selFeatures = new Set();
// Step 2 (install) state. `_toInstall` is the server's own plan from /setup/apply — the
// field the wizard used to throw away while telling the user "installs: faster-whisper".
let _toInstall = [];      // [{id,label,deps,models,size_mb}]
let _installRes = {};     // feature id -> {state:'pending'|'running'|'ok'|'fail'|'unknown', detail, failed:[]}
let _installing = false;
// Features that were asked for and are NOT in force for a reason that is NOT missing packages
// — auto-tune owns the key on this hardware tier, it is a setting nobody switched on, a security
// policy refused it, or nobody owns it and we say so. The server reads these back out of the
// effective config (/setup/apply → not_enabled); the wizard has no business inferring them.
let _blocked = [];        // [{id,label,owner,reason}]

// BL-386: Escape must work regardless of where focus sits. A listener on _root only fires
// when the keydown target is _root or a descendant; on first-run focus is usually on <body>,
// so a _root listener never receives it and the "esc" chip advertised an exit that never fired.
// Listen on document (capture, like wizard.js / the overlay manager), added on open and removed
// on close so it can never accumulate across opens.
function _onDocKeydown(e) {
  if (!_open) return;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeSetupProfiles(); }
}

function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function _profileImpliedFeatures() {
  const out = new Set();
  ((_data && _data.profiles) || []).forEach((p) => {
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
  // Kept as a belt-and-suspenders in-panel handler; the authoritative Escape wiring is the
  // document listener added in openSetupProfiles (see _onDocKeydown).
  _root.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeSetupProfiles(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const escChip = _root.querySelector('.cmdp-esc');
  if (escChip) {
    escChip.setAttribute('role', 'button');
    escChip.setAttribute('tabindex', '0');
    escChip.setAttribute('aria-label', 'Close setup');
    escChip.addEventListener('click', () => closeSetupProfiles());
    escChip.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); closeSetupProfiles(); } });
  }
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

  if (_step === 2) { _renderInstallStep(body, back, next); return; }

  if (_step === 0) {
    back.hidden = true;
    const profiles = (_data && _data.profiles) || [];
    // BL-386: an empty/failed load must FAIL VISIBLY — never a silent empty forEach that
    // leaves a dead-end modal (zero cards + "pick at least one" forever). Offer retry + a
    // clear escape; the app still works, so skipping is safe.
    if (!profiles.length) {
      next.hidden = true;
      body.innerHTML =
        '<div class="setupwiz-q">setup couldn’t load</div>' +
        '<div class="sysdiag-muted setupwiz-loaderr"></div>' +
        '<div class="setupwiz-erractions">' +
          '<button type="button" class="setup-btn primary setupwiz-retry">retry</button>' +
          '<button type="button" class="setup-btn setupwiz-skip">skip for now</button>' +
        '</div>';
      body.querySelector('.setupwiz-loaderr').textContent =
        'Couldn’t load the setup options' + (_loadErr ? ' (' + _loadErr + ')' : '') +
        '. Layla still works — retry, or skip and reconfigure any time from ⌘K → “Set up / reconfigure”. ' +
        'Press Esc or the esc chip to close.';
      body.querySelector('.setupwiz-retry').addEventListener('click', () => { _load(); });
      body.querySelector('.setupwiz-skip').addEventListener('click', () => closeSetupProfiles());
      return;
    }
    next.hidden = false;
    next.textContent = 'continue';
    body.innerHTML = '<div class="setupwiz-q">what do you want to do?</div><div class="setupwiz-profiles"></div>';
    const wrap = body.querySelector('.setupwiz-profiles');
    profiles.forEach((p) => {
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
    next.hidden = false;
    next.textContent = 'apply';
    // pre-seed features from chosen profiles the first time we land here
    _profileImpliedFeatures().forEach((f) => _selFeatures.add(f));
    body.innerHTML = '<div class="setupwiz-q">optional features — enable only what you need</div><div class="setupwiz-features"></div>';
    const wrap = body.querySelector('.setupwiz-features');
    ((_data && _data.features) || []).forEach((f) => {
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

function _sizeLabel(mb) {
  if (!mb) return '';
  return mb >= 1000 ? (mb / 1000).toFixed(1) + ' GB' : mb + ' MB';
}

/**
 * The last MEANINGFUL line of an error blob. pip stderr ends with a trailing newline, so the
 * obvious `.split('\n').slice(-1)[0]` yields "" and the failure row renders as an empty
 * string in red — styled like an explanation, containing none. (Same fix in marketplace.js.)
 */
function _lastLine(err) {
  const lines = String(err == null ? '' : err).split('\n').map((s) => s.trim()).filter(Boolean);
  return lines.length ? lines[lines.length - 1] : 'install failed (no error text)';
}

/**
 * Step 2 — the install step the wizard never had.
 *
 * /setup/apply has ALWAYS returned `to_install`; the wizard discarded it, flipped flags,
 * and said "✓ configured". So the checkbox that read "installs: faster-whisper, kokoro-onnx"
 * installed nothing and still reported success. This step makes the promise real: it shows
 * exactly which packages are about to be fetched and how big they are, asks before spending
 * the bandwidth, then reports per-feature what actually landed — including the pip error
 * text when it did not.
 */
/**
 * The "asked for, not in force, and here is who decided that" section.
 *
 * This is the part the wizard could not draw at all, because it never had the information:
 * it computed its outcome as "requested minus failed packages", so a feature switched off by
 * auto-tune (every CPU tier holds hyde/multi-agent off) or, at the time, by the maturity gate
 * (initiative below rank 1) had no package to blame and simply vanished — reported as enabled, hidden by
 * the palette, unexplained anywhere. The reasons below come from the server re-reading its
 * effective config, one owner per feature, including a plain "reason unknown" when nothing
 * claims it.
 */
function _blockedRows() {
  if (!_blocked.length) return '';
  const rows = _blocked.map((b) => (
    '<div class="setupwiz-irow" data-state="blocked" data-fid="' + _esc(b.id) + '">' +
      '<span class="setupwiz-imark">◦</span>' +
      '<span class="setupwiz-imain"><span class="setupwiz-ilabel">' + _esc(b.label || b.id) + '</span>' +
      '<span class="setupwiz-ideps">' + _esc(_ownerLabel(b.owner)) + '</span>' +
      '<span class="setupwiz-idetail">' + _esc(b.reason || 'not switched on — reason unknown.') + '</span>' +
      '</span></div>'
  )).join('');
  return '<div class="setupwiz-q setupwiz-subq">not switched on</div>' +
    '<div class="setupwiz-installs setupwiz-blocked">' + rows + '</div>';
}

// Mirrors the owner ids install/feature_status.py can return. `maturity` was removed with the
// rank gate itself — leaving it would have been harmless (it can never arrive) but the missing
// half was not: the `setting` owner that replaced it had no case here, so a plainly-unchecked
// setting fell through to `default` and rendered as "reason unknown" — a defect report over a
// switch that works. Keep this in step with _KEY_OWNERS and key_off_reason.
function _ownerLabel(owner) {
  switch (owner) {
    case 'auto_tune': return 'held off by auto-tune (hardware tier)';
    case 'setting': return 'off — turn it on in Settings';
    case 'security_policy': return 'refused by a security policy';
    case 'credential': return 'needs a credential from another program';
    case 'packages': return 'needs packages';
    case 'unreadable': return 'could not be confirmed';
    default: return 'reason unknown';
  }
}

function _renderInstallStep(body, back, next) {
  back.hidden = _installing;
  next.hidden = true;
  const totalMb = _toInstall.reduce((a, f) => a + (f.size_mb || 0), 0);
  const rows = _toInstall.map((f) => {
    const st = _installRes[f.id] || { state: 'pending' };
    const mark = st.state === 'ok' ? '✓' : st.state === 'fail' ? '✕'
      : st.state === 'unknown' ? '?' : st.state === 'running' ? '⋯' : '·';
    return '<div class="setupwiz-irow" data-state="' + st.state + '" data-fid="' + _esc(f.id) + '">' +
      '<span class="setupwiz-imark">' + mark + '</span>' +
      '<span class="setupwiz-imain"><span class="setupwiz-ilabel">' + _esc(f.label) + '</span>' +
      '<span class="setupwiz-ideps">' + _esc((f.deps || []).join(', ')) +
      (f.size_mb ? ' · ' + _sizeLabel(f.size_mb) : '') + '</span>' +
      (st.detail ? '<span class="setupwiz-idetail">' + _esc(st.detail) + '</span>' : '') +
      '</span></div>';
  }).join('');

  const done = _toInstall.length && _toInstall.every((f) => {
    const s = (_installRes[f.id] || {}).state;
    return s === 'ok' || s === 'fail' || s === 'unknown';
  });
  const anyFail = _toInstall.some((f) => (_installRes[f.id] || {}).state === 'fail');
  // UNKNOWN is its own outcome. Collapsing it into "failed" is how a lost HTTP response got
  // rendered as "not switched on" while the server had completed the install and the flag was
  // already true on disk.
  const anyUnknown = _toInstall.some((f) => (_installRes[f.id] || {}).state === 'unknown');

  let head;
  let actions = '';
  let foot = '';
  if (_installing) {
    head = 'installing — this downloads from the internet and can take a few minutes';
  } else if (!_toInstall.length) {
    // Nothing to install; we are here only to explain what did not switch on.
    head = _blocked.length ? 'applied — but not everything you picked is on' : 'applied';
    foot = 'Everything else you picked is switched on.';
    actions = '<div class="setupwiz-erractions">' +
      '<button type="button" class="setup-btn primary setupwiz-idone">done</button></div>';
  } else if (done) {
    head = anyUnknown ? 'some results could not be confirmed'
      : anyFail ? 'some packages did not install' : 'installed and switched on';
    if (anyUnknown) {
      // Do NOT assert an outcome here. We asked the server and could not get an answer; the
      // install may well have completed. Say exactly that, and how to find out.
      foot = 'One or more results could not be confirmed — the request did not complete and the ' +
        'server could not be re-read. The install may or may not have finished. ' +
        'Reopen this wizard, or check Settings, to see the current state.';
    } else if (anyFail) {
      // Verified, not assumed: every row below was re-read from the server after installing.
      foot = 'The features whose packages failed were NOT switched on (confirmed with the server). ' +
        'Fix the error above (usually no internet or a missing compiler) and retry, or install the ' +
        'packages yourself with pip in Layla’s Python environment.';
    } else {
      foot = 'Packages installed and the features switched on (confirmed with the server).';
    }
    actions = '<div class="setupwiz-erractions">' +
      ((anyFail || anyUnknown) ? '<button type="button" class="setup-btn primary setupwiz-retry-inst">retry</button>' : '') +
      '<button type="button" class="setup-btn' + ((anyFail || anyUnknown) ? '' : ' primary') + ' setupwiz-idone">done</button></div>';
  } else {
    head = 'these features need extra packages' + (totalMb ? ' (~' + _sizeLabel(totalMb) + ' to download)' : '');
    // Say the state plainly BEFORE the install, so "skip" is an informed choice.
    foot = 'These are not switched on yet — each one turns on only when its packages install.';
    actions = '<div class="setupwiz-erractions">' +
      '<button type="button" class="setup-btn primary setupwiz-run-inst">install now</button>' +
      '<button type="button" class="setup-btn setupwiz-skip-inst">skip for now</button></div>';
  }

  body.innerHTML = '<div class="setupwiz-q">' + _esc(head) + '</div>' +
    (_toInstall.length ? '<div class="setupwiz-installs">' + rows + '</div>' : '') +
    (foot ? '<div class="sysdiag-muted setupwiz-ifoot">' + _esc(foot) + '</div>' : '') +
    _blockedRows() +
    actions;

  const on = (sel, fn) => { const el = body.querySelector(sel); if (el) el.addEventListener('click', fn); };
  on('.setupwiz-run-inst', () => _runInstalls());
  on('.setupwiz-retry-inst', () => _runInstalls(true));
  on('.setupwiz-idone', () => closeSetupProfiles());
  on('.setupwiz-skip-inst', () => {
    // Honest exit. These features were never switched on (their packages are absent), so the
    // old "Enabled, but not installed" was backwards — it named the one state that is now
    // impossible. Say what is true and how to finish.
    const names = _toInstall.map((f) => (f.deps || []).join(' ')).join(' ').trim();
    if (typeof window.showToast === 'function') {
      window.showToast('Not enabled — install the packages to turn these on: pip install ' + names);
    }
    closeSetupProfiles();
  });
}

/**
 * Ask the SERVER what is true, for the given feature ids.
 *
 * Returns id -> {on, reason} or null when the server itself could not be reached — null is a
 * third answer and callers must treat it as "unknown", never as "off".
 */
async function _confirmFromServer(ids) {
  try {
    const r = await fetch('/setup/state', { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    const d = await r.json();
    if (!d || !Array.isArray(d.enabled_features)) return null;
    const on = new Set(d.enabled_features);
    const why = {};
    (d.unavailable_features || []).forEach((u) => { if (u && u.id) why[u.id] = u; });
    const out = {};
    ids.forEach((id) => { out[id] = { on: on.has(id), reason: (why[id] || {}).reason || '' }; });
    return out;
  } catch (_) {
    return null;
  }
}

async function _runInstalls(onlyFailed) {
  if (_installing) return;
  _installing = true;
  const targets = _toInstall.filter((f) => {
    if (!onlyFailed) return true;
    const s = (_installRes[f.id] || {}).state;
    return s === 'fail' || s === 'unknown';
  });
  targets.forEach((f) => { _installRes[f.id] = { state: 'pending' }; });
  _render();
  for (const f of targets) {
    _installRes[f.id] = { state: 'running', detail: 'installing ' + (f.deps || []).join(', ') + '…' };
    _render();
    try {
      const r = await fetch('/setup/feature/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feature_id: f.id, confirm: true }),
      });
      const d = await r.json().catch(() => ({}));
      if (d && d.ok) {
        _installRes[f.id] = { state: 'ok', detail: d.models_note || 'installed' };
      } else {
        // Surface the REAL reason (pip stderr tail), not a generic failure.
        const why = (d && d.failed && d.failed.length)
          ? d.failed.map((x) => x.dep + ': ' + _lastLine(x.error)).join(' | ')
          : ((d && d.error) || ('HTTP ' + r.status));
        _installRes[f.id] = { state: 'fail', detail: why, failed: (d && d.failed) || [] };
      }
    } catch (e) {
      // A LOST RESPONSE IS NOT A FAILED INSTALL. This catch fires for anything that stops the
      // reply reaching us — an aborted request, a dropped connection, a reload mid-flight —
      // and the server carries on regardless. Proved: aborting the client at 0.4s still left
      // litellm_enabled flipped true and `cloud_models` listed by /setup/state, while this
      // branch had drawn ✕ "not switched on". So: report UNKNOWN, then go and find out.
      const msg = (e && e.message) ? e.message : String(e);
      _installRes[f.id] = {
        state: 'unknown',
        detail: 'the request did not complete (' + msg + ') — the server may have finished anyway; checking…',
      };
      _render();
      // ONLY A POSITIVE CONFIRMATION IS CONCLUSIVE HERE, and it has to be polled for.
      // Losing the response does not stop the server: a pip install keeps running for minutes
      // after the client gives up. A single immediate re-read therefore races the work it is
      // trying to observe — driven live, it saw `vision` off, printed "not switched on —
      // confirmed with the server", and the very next request showed the feature enabled. That
      // is the same false-definite this whole change exists to delete, so: poll for a bounded
      // window, and if it never comes on, say UNKNOWN rather than inventing a negative.
      let on = false;
      for (let i = 0; i < 10 && !on; i++) {
        if (i) await new Promise((r) => setTimeout(r, 1000));
        const truth = await _confirmFromServer([f.id]);
        on = !!(truth && truth[f.id] && truth[f.id].on);
      }
      if (on) {
        _installRes[f.id] = { state: 'ok', detail: 'switched on — confirmed with the server after the reply was lost in transit.' };
      } else {
        _installRes[f.id] = {
          state: 'unknown',
          detail: 'could not confirm (' + msg + '). It is still not switched on, but the server may '
            + 'be working on it — installs continue after the connection drops. Reopen this wizard '
            + 'in a minute, or check Settings, to see the current state.',
        };
      }
    }
    _render();
  }
  // FINAL READ-BACK. Even the happy path is a claim about the server's state made from a
  // response body; ask the server itself before saying "switched on". This is also the only
  // thing that can catch a feature whose packages installed but whose flag another owner
  // (auto-tune, a security policy) holds off — the installer cannot see those and would report success.
  const truth = await _confirmFromServer(targets.map((f) => f.id));
  if (truth) {
    targets.forEach((f) => {
      const t = truth[f.id];
      const cur = _installRes[f.id] || {};
      if (!t) return;
      if (t.on && cur.state !== 'ok') {
        _installRes[f.id] = { state: 'ok', detail: 'switched on — confirmed with the server.' };
      } else if (!t.on && cur.state === 'ok') {
        _installRes[f.id] = { state: 'fail', detail: t.reason || 'the packages installed but the feature is not in force.' };
      }
    });
  }
  _installing = false;
  _render();
  const failed = _toInstall.filter((f) => (_installRes[f.id] || {}).state === 'fail');
  const unconfirmed = _toInstall.filter((f) => (_installRes[f.id] || {}).state === 'unknown');
  const ok = targets.filter((f) => (_installRes[f.id] || {}).state === 'ok');
  // The feature flags are written by /setup/feature/install, i.e. HERE — not at apply time
  // any more. Anything gating on them (palette, marketplace badges) has to re-read now, or it
  // shows the pre-install state until a reload.
  if (ok.length) {
    try {
      window.dispatchEvent(new CustomEvent('layla:profiles-applied', { detail: { features: ok.map((f) => f.id) } }));
    } catch (_) {}
  }
  if (typeof window.showToast === 'function') {
    let msg;
    if (unconfirmed.length) {
      msg = unconfirmed.length + ' feature' + (unconfirmed.length === 1 ? '' : 's')
        + ' could not be confirmed — reopen setup to see the current state';
    } else if (failed.length) {
      msg = failed.length + ' feature' + (failed.length === 1 ? '' : 's') + ' not switched on — see the reason above';
    } else {
      msg = 'Installed and enabled — ' + targets.map((f) => f.label).join(', ');
    }
    window.showToast(msg);
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
    // `features` is now what the server RE-READ out of its effective config — not the
    // selection, and not the selection minus missing packages. `not_enabled` carries the rest
    // with a reason each, which is the only way an auto-tune-reverted or otherwise-owned
    // feature can be reported at all: it has no package to blame, so the old summary counted
    // it as enabled while the palette hid it.
    const n = (d.features || []).length;
    const notOn = Array.isArray(d.not_enabled) ? d.not_enabled : [];
    note.textContent = '✓ configured — ' + n + ' feature' + (n === 1 ? '' : 's') + ' on' +
      (notOn.length ? ' · ' + notOn.length + ' not switched on' : '');
    note.setAttribute('data-ok', 'true');
    try { localStorage.setItem('layla_setup_profiles_v1_done', '1'); } catch (_) {}
    // Let listeners (feature-gated palette, etc.) refresh against the new flags.
    try { window.dispatchEvent(new CustomEvent('layla:profiles-applied', { detail: { features: d.features || [], profiles: d.profiles || [] } })); } catch (_) {}
    if (typeof window.showToast === 'function') window.showToast('Layla configured for you — ' + (d.profiles || []).join(', '));

    // Anything that needs packages goes to the install step instead of closing on a
    // success message. Only a selection that needs NOTHING may claim to be done here.
    _toInstall = Array.isArray(d.to_install) ? d.to_install.filter((f) => (f.deps || []).length) : [];
    const pkgIds = new Set(_toInstall.map((f) => f.id));
    // Off for a reason that installing cannot fix — shown with its owner's explanation rather
    // than silently dropped. (Package-blocked ones are already an install row; not both.)
    _blocked = notOn.filter((b) => !pkgIds.has(b.id))
      .map((b) => ({ id: b.id, label: b.label, owner: b.owner, reason: b.reason }));
    if (_toInstall.length || _blocked.length) {
      _installRes = {};
      note.textContent = '';
      _step = 2;
      _render();
      return;
    }
    setTimeout(closeSetupProfiles, 1200);
  } catch (e) {
    note.textContent = 'error — ' + (e && e.message ? e.message : e);
  }
}

async function _load() {
  _data = null;      // → _render shows "loading…"
  _loadErr = '';
  _step = 0;
  // A reopened wizard must not show the LAST run's outcome — the whole point is that the
  // outcome is re-read, and stale rows are the inferred-outcome bug in miniature.
  _toInstall = [];
  _blocked = [];
  _installRes = {};
  if (_open) _render();
  try {
    const r = await fetch('/setup/profiles', { headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const j = await r.json();
    // Guard against an error/404 payload (e.g. {"detail":"Not Found"} before the setup router
    // is live) that would otherwise crash _render on .forEach — and treat it as a visible failure.
    if (!j || !Array.isArray(j.profiles)) throw new Error('bad response');
    _data = { profiles: j.profiles, features: Array.isArray(j.features) ? j.features : [] };
    _loadErr = '';
  } catch (e) {
    _data = { profiles: [], features: [] };
    _loadErr = (e && e.message) ? e.message : String(e);
  }
  if (_open) _render();
}

export async function openSetupProfiles() {
  _build();
  if (_open) return;
  _open = true;
  // Authoritative Escape wiring (BL-386): document-level, removed again in closeSetupProfiles.
  document.addEventListener('keydown', _onDocKeydown, true);
  _root.hidden = false;
  _step = 0;
  _render();
  await _load();
}

export function closeSetupProfiles() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener('keydown', _onDocKeydown, true);
  _root.hidden = true;
  // Mark first-run setup as seen (shown once) and notify the boot sequence so it can
  // continue to the mini onboarding tour. Reconfigure later via ⌘K.
  try { localStorage.setItem('layla_setup_profiles_v1_done', '1'); } catch (_) {}
  try { window.dispatchEvent(new CustomEvent('layla:setup-closed')); } catch (_) {}
}
