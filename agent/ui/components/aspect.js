/**
 * components/aspect.js — Aspect switching, colors, maturity card, registry.
 *
 * Converted from js/layla-aspect.js (IIFE → ES module).
 * Depends on: services/utils.js (escapeHtml, showToast)
 */

import { bus } from '../core/bus.js';
import { appState } from '../core/state.js';
import { api } from '../services/api.js';
import { escapeHtml, showToast } from '../services/utils.js';

// ── Per-aspect color palette ─────────────────────────────────────────────────
// Reconciled to the shipped design-system tokens (layla-rebuild.css --asp-*): these
// are the aspect identity colors. Was a third, divergent source that rendered cassandra
// purple and lilith magenta; now the live --asp matches each aspect's real hue.
export const ASPECT_COLORS = {
  morrigan:  { asp: '#8b0000', glow: 'rgba(139,0,0,0.28)',    mid: 'rgba(139,0,0,0.10)' },
  nyx:       { asp: '#6a1f9c', glow: 'rgba(106,31,156,0.28)', mid: 'rgba(106,31,156,0.10)' },
  echo:      { asp: '#2f5aa8', glow: 'rgba(47,90,168,0.28)',  mid: 'rgba(47,90,168,0.10)' },
  eris:      { asp: '#b06a1e', glow: 'rgba(176,106,30,0.28)', mid: 'rgba(176,106,30,0.10)' },
  cassandra: { asp: '#1f7a72', glow: 'rgba(31,122,114,0.28)', mid: 'rgba(31,122,114,0.10)' },
  lilith:    { asp: '#a33b52', glow: 'rgba(163,59,82,0.28)',  mid: 'rgba(163,59,82,0.10)' },
};

// ── Aspect registry ──────────────────────────────────────────────────────────
export const ASPECTS = [
  { id: 'morrigan',  sym: '⚔', name: 'Morrigan',  fn: 'Coding',   desc: 'Code, debug, architecture — the blade' },
  { id: 'nyx',       sym: '✦', name: 'Nyx',       fn: 'Research',  desc: 'Research, depth, synthesis' },
  { id: 'echo',      sym: '◎', name: 'Echo',      fn: 'Memory',    desc: 'Reflection, patterns, memory' },
  { id: 'eris',      sym: '⚡', name: 'Eris',      fn: 'Ideas',     desc: 'Creative chaos, banter, lateral leaps' },
  { id: 'cassandra', sym: '⌖', name: 'Cassandra', fn: 'Critique',  desc: 'Unfiltered oracle — sees it first' },
  { id: 'lilith',    sym: '⊛', name: 'Lilith',    fn: 'Ethics',    desc: 'Sovereign will, ethics, full honesty' },
];

const ASPECT_SYMBOLS = { morrigan:'⚔', nyx:'✦', echo:'◎', eris:'⚡', cassandra:'⌖', lilith:'⊛' };

// ── Custom aspects are first-class members of the SAME roster ────────────────
// BL-301b. `ASPECTS` above is the built-in seed; at runtime it is also the LIVE roster, because
// every consumer (the @mention dropdown in input.js, the @mention resolver in app.js, the ⌘K
// palette, the wizard, setAspect's own label/colour lookup) reads this one array. Custom aspects
// used to exist only in the create-overlay, so a persona you had just made resolved NOWHERE —
// `@sable` produced "No aspect “@sable”" and the bar had no button for it. mergeCustomAspects()
// appends them here IN PLACE (never reassigning the binding, so importers keep seeing it).
//
// THE COLLISION RULE IS THE ORDER: the 6 built-ins are always the first 6 entries and every
// resolver takes the first match, so a custom aspect can never shadow one of them.
const BUILTIN_ASPECTS = ASPECTS.slice();
export const BUILTIN_ASPECT_IDS = Object.freeze(BUILTIN_ASPECTS.map(a => a.id));
const _CUSTOM_ID_RE = /^[a-z][a-z0-9_]{1,31}$/;

export function isBuiltinAspect(id) {
  return BUILTIN_ASPECT_IDS.indexOf(String(id || '').trim().toLowerCase()) >= 0;
}

/** The custom slice of the live roster (everything after the 6 built-ins). */
export function customAspects() {
  return ASPECTS.slice(BUILTIN_ASPECTS.length);
}

function _cleanLine(s, max) {
  // Strip control chars (a name with a newline breaks the one-line bar label) and collapse runs.
  return String(s == null ? '' : s).replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')
    .replace(/\s+/g, ' ').trim().slice(0, max || 80);
}

/**
 * Replace the custom slice of the roster from a `/character/custom-aspects` payload.
 * Invalid ids, blank ids and anything colliding with a built-in are dropped.
 * Returns the rows that were merged.
 */
export function mergeCustomAspects(list) {
  const seen = new Set(BUILTIN_ASPECT_IDS);
  const rows = [];
  (Array.isArray(list) ? list : []).forEach((c) => {
    if (!c || typeof c !== 'object') return;
    const id = String(c.id == null ? '' : c.id).trim().toLowerCase();
    if (!_CUSTOM_ID_RE.test(id) || seen.has(id)) return;   // invalid, or would shadow a built-in
    seen.add(id);
    const base = _cleanLine(c.base_aspect, 32).toLowerCase() || 'morrigan';
    const name = _cleanLine(c.name, 60) || (id.charAt(0).toUpperCase() + id.slice(1));
    rows.push({
      id,
      sym: _cleanLine(c.symbol, 8) || '✦',
      name,
      fn: 'Custom',
      desc: _cleanLine(c.tagline, 160) || ('Your aspect — inherits ' + base),
      color: _cleanLine(c.color_primary, 32),
      base_aspect: base,
      custom: true,
    });
  });
  // Rebuild in place: importers (input.js, main.js, window.ASPECTS) hold this exact array.
  ASPECTS.length = 0;
  BUILTIN_ASPECTS.forEach(a => ASPECTS.push(a));
  rows.forEach(r => ASPECTS.push(r));
  try { renderCustomAspectBar(); } catch (_) {}
  try { bus.emit('aspect:roster', { aspects: ASPECTS.slice() }); } catch (_) {}
  return rows;
}

/** Pull the operator's custom aspects from the backend and merge them into the roster. */
export async function refreshCustomAspects() {
  try {
    const r = await fetch('/character/custom-aspects', { headers: { Accept: 'application/json' } });
    const d = await r.json();
    const merged = mergeCustomAspects((d && d.custom) || []);
    _notifyRosterChanged();
    return merged;
  } catch (_) {
    return [];
  }
}

/**
 * Tell consumers that hold a COPY of the roster to rebuild it.
 *
 * The ⌘K palette maps ASPECTS once at init and keeps the result, so it cannot see a roster that
 * arrives from this async fetch (or changes on create/delete) — that is why "Switch to <custom>"
 * was missing while the bar and @mention worked. Notifying here, at the one place the roster is
 * mutated, keeps every consumer honest instead of asking each caller to remember.
 */
function _notifyRosterChanged() {
  try {
    if (typeof window !== 'undefined' && typeof window.refreshAspectPaletteCommands === 'function') {
      window.refreshAspectPaletteCommands();
    }
  } catch (_) { /* palette not initialised yet — it builds from the live roster anyway */ }
}

/**
 * Load the operator's custom aspects into the roster once the DOM exists.
 *
 * Self-scheduling on purpose. Every consumer of this roster (bar, @mention, palette) reads
 * `ASPECTS` synchronously and none of them owns the fetch, so making some other module remember
 * to call it is exactly how a custom aspect ends up resolving in one place and not another.
 * Exported as well, so a create/delete can re-run it (custom-aspect.js does).
 */
export function initAspectRoster() {
  return refreshCustomAspects();
}

try {
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => { initAspectRoster(); }, { once: true });
    } else {
      initAspectRoster();
    }
  }
} catch (_) { /* non-browser (module link check / unit harness) — nothing to hydrate */ }

/**
 * Resolve an @mention / bar reference (id OR display name, case-insensitive) to a roster entry.
 * Built-ins are scanned first and ids before names, so `@morrigan` always reaches the built-in
 * even if a custom aspect is *named* "Morrigan".
 */
export function resolveAspectRef(ref) {
  const s = String(ref == null ? '' : ref).trim().replace(/^@/, '').toLowerCase();
  if (!s) return null;
  return ASPECTS.find(a => a.id === s)
      || ASPECTS.find(a => String(a.name || '').toLowerCase() === s)
      || null;
}

/**
 * Render a sidebar button for every custom aspect, alongside the 6 static built-in buttons.
 * DOM-built (never innerHTML) because names/taglines/sigils are operator input.
 */
export function renderCustomAspectBar() {
  if (typeof document === 'undefined' || !document.getElementById) return 0;
  const host = document.getElementById('sidebar-voices');
  if (!host || !host.appendChild) return 0;
  try {
    const old = host.querySelectorAll ? host.querySelectorAll('[data-custom-aspect]') : [];
    Array.prototype.forEach.call(old, el => { if (el && el.remove) el.remove(); });
  } catch (_) {}
  const active = appState.get('aspect.current');
  const rows = customAspects();
  rows.forEach((a) => {
    const wrap = document.createElement('div');
    wrap.className = 'aspect-option expandable';
    wrap.id = 'aspect-opt-' + a.id;
    wrap.setAttribute('data-custom-aspect', a.id);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'aspect-btn' + (active === a.id ? ' active' : '');
    btn.id = 'btn-' + a.id;
    // Same delegation contract as the built-in buttons (bootstrap.js reads id/data-action).
    btn.setAttribute('data-action', 'setAspect');
    btn.setAttribute('data-arg', a.id);
    btn.setAttribute('data-action-stop', '');
    btn.setAttribute('aria-label', 'Switch to ' + a.name + ' aspect (custom)');
    btn.setAttribute('aria-pressed', active === a.id ? 'true' : 'false');
    const sig = document.createElement('span');
    sig.className = 'aspect-sigil';
    sig.textContent = a.sym;
    btn.appendChild(sig);
    btn.appendChild(document.createTextNode(' ' + a.name + ' · ' + a.fn));
    const desc = document.createElement('span');
    desc.className = 'aspect-desc';
    desc.textContent = a.desc;
    wrap.appendChild(btn);
    wrap.appendChild(desc);
    host.appendChild(wrap);
  });
  return rows.length;
}

const DOODLES = {
  morrigan:  '⚔ ⟁ ⚔ ⎔ ⚔ ◈\n/\\\\==/\\\\  ─┼─  /\\\\==/\\\\\n⎔  ◈  ⟁  ⚔  ⟁  ◈',
  nyx:       '✦ ⊛ ∴ ✦ ⌁ ✦\n..✦..::...✦..::..\n⌁  ✦  ⊛  ∴  ✦  ⌁',
  echo:      '◎ ∞ ◎ ⟡ ◎ ∞\n====  ~~~  ====\n⟡  ◎  ∞  ◎  ⟡',
  eris:      '⚡ ⊘ ⚡ ⌇ ⚡ ⊘\n/\\/\\/\\/\\  ╱╲  /\\/\\/\\/\\\n⌇  ⚡  ⊘  ⚡  ⌇',
  cassandra: '⌖ △ ⌖ ⟟ ⌖ △\n<>  /\\  <>  /\\  <>\n⟟  ⌖  △  ⌖  ⟟',
  lilith:    '⊛ ♾ ✶ ⊛ ⟁ ⊛\n###  ╳  ###  ╳  ###\n✶  ⊛  ♾  ⊛  ✶',
};

// ── Lookup ───────────────────────────────────────────────────────────────────
export function facetMetaFromNameOrId(aspectNameOrId) {
  if (!aspectNameOrId) return null;
  return resolveAspectRef(aspectNameOrId);
}

export function formatLaylaLabelHtml(aspectId) {
  const aid = String(aspectId || 'morrigan').toLowerCase();
  // A custom aspect resolves here too; only a genuinely unknown id falls back to Morrigan.
  const a = resolveAspectRef(aid) || ASPECTS[0];
  const sym = escapeHtml(String(a.sym || ''));
  const name = escapeHtml(String(a.name || ''));
  return `<span class="msg-brand">Layla</span><span class="msg-facet-chip" title="Facet (voice)"><span class="aspect-sigil">${sym}</span> ${name}</span>`;
}

/** Build an ASPECT_COLORS-shaped palette from a custom aspect's `#rrggbb` accent, or null. */
function _customPalette(meta) {
  const hex = String((meta && meta.color) || '').trim();
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const rgb = ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255);
  return { asp: '#' + m[1], glow: 'rgba(' + rgb + ',0.28)', mid: 'rgba(' + rgb + ',0.10)' };
}

// ── Aspect switching ─────────────────────────────────────────────────────────
let _lastAspectSwitchTime = 0;
let _aspectLocked = false;

export function setAspect(id, force) {
  if (_aspectLocked && !force) return;

  // Update state (triggers compat bridge's property descriptor)
  appState.set('aspect.current', id);

  // Update sidebar buttons (class + ARIA so the active aspect isn't conveyed by colour alone)
  document.querySelectorAll('.aspect-btn').forEach(b => {
    b.classList.remove('active');
    b.setAttribute('aria-pressed', 'false');
  });
  const btn = document.getElementById('btn-' + id);
  if (btn) { btn.classList.add('active'); btn.setAttribute('aria-pressed', 'true'); }

  // Reflect the active aspect in the collapsed sidebar summary (name · function).
  // BL-301: a custom aspect id is not in the built-in ASPECTS registry — fall back to the id
  // itself, NOT ASPECTS[0] (which would mislabel the active custom aspect as "Morrigan").
  // BL-301b: it usually IS in the roster now (custom aspects are merged in), so this resolves
  // to the real custom name/sigil rather than a bare id.
  const _meta = resolveAspectRef(id) || { name: id, fn: '' };
  const sva = document.getElementById('sidebar-voices-active');
  if (sva) sva.textContent = _meta.name + (_meta.fn ? ' · ' + _meta.fn : '');

  // Update badges
  const sym = ASPECT_SYMBOLS[id] || (_meta && _meta.sym) || '∴';
  // Wrap the sigil in .aspect-sigil so one canonical rule normalizes it (the badge otherwise
  // inherits Cinzel serif). sym/id can now come from a CUSTOM aspect (operator input), so both
  // are escaped rather than trusted.
  const _sigilHtml = '<span class="aspect-sigil">' + escapeHtml(sym) + '</span> ' + escapeHtml(id.toUpperCase());
  const badge = document.getElementById('aspect-badge');
  if (badge) {
    badge.innerHTML = _sigilHtml;
    badge.style.animation = 'none';
    void badge.offsetWidth;
    badge.style.animation = '';
  }
  const topBadge = document.getElementById('topbar-aspect-badge');
  if (topBadge) topBadge.innerHTML = _sigilHtml;

  // Apply CSS custom properties. A custom aspect brings its own accent (#hex) if the operator
  // set one; otherwise it borrows its base aspect's palette rather than always looking Morrigan-red.
  const c = ASPECT_COLORS[id]
    || _customPalette(_meta)
    || ASPECT_COLORS[(_meta && _meta.base_aspect) || '']
    || ASPECT_COLORS.morrigan;
  const root = document.documentElement.style;
  if (document.body) document.body.setAttribute('data-aspect', id);
  root.setProperty('--asp',      c.asp);
  root.setProperty('--asp-glow', c.glow);
  root.setProperty('--asp-mid',  c.mid);
  // The stylesheet carries a `body[data-aspect="<builtin>"]` block per built-in, which re-declares
  // --asp at BODY scope and therefore beats the :root inline we just set. There is no such block
  // for a custom aspect, so its accent used to lose to the default and every custom persona
  // rendered Morrigan-red. Mirror onto body only when no built-in palette owns the id, and clear
  // the mirror again for built-ins so they keep using the design-system tokens.
  try {
    const bs = document.body && document.body.style;
    if (bs) {
      if (!ASPECT_COLORS[id]) {
        bs.setProperty('--asp', c.asp);
        bs.setProperty('--asp-glow', c.glow);
        bs.setProperty('--asp-mid', c.mid);
      } else {
        bs.removeProperty('--asp');
        bs.removeProperty('--asp-glow');
        bs.removeProperty('--asp-mid');
      }
    }
  } catch (_) {}

  // Toast
  if (Date.now() - _lastAspectSwitchTime > 300) {
    _lastAspectSwitchTime = Date.now();
    showToast('Now talking to ' + (_meta && _meta.name ? _meta.name : id));
  }

  // Context chip
  try { if (typeof window.updateContextChip === 'function') window.updateContextChip(); } catch (_) {}

  // Doodle overlay
  try {
    const ov = document.getElementById('doodle-overlay');
    if (ov) ov.textContent = (DOODLES[id] || DOODLES.morrigan).repeat(180);
  } catch (_) {}

  // Sprite
  try {
    if (typeof window.laylaSetAspectSprite === 'function') window.laylaSetAspectSprite(id);
  } catch (_) {}

  bus.emit('aspect:switched', { id, colors: c });
}

export function toggleAspectLock() {
  _aspectLocked = !_aspectLocked;
  window._aspectLocked = _aspectLocked;
  const btn = document.getElementById('aspect-lock-btn');
  if (btn) {
    btn.textContent = _aspectLocked ? '🔒' : '🔓';
    btn.classList.toggle('locked', _aspectLocked);
    btn.title = _aspectLocked
      ? 'Locked to ' + (appState.get('aspect.current') || 'morrigan').toUpperCase() + ' — click to unlock'
      : 'Lock this aspect (prevent auto-routing)';
  }
}

// ── Maturity / Mastery rank UI ───────────────────────────────────────────────
export async function refreshMaturityCard(showCeremony) {
  try {
    const d = await api.get('/operator/profile', { timeout: 8000 });
    if (!d || !d.ok) return;
    const rank = (d.maturity && d.maturity.rank != null) ? Number(d.maturity.rank) : 0;
    const xp = (d.maturity && d.maturity.xp != null) ? Number(d.maturity.xp) : 0;
    const phaseRaw = String((d.maturity && d.maturity.phase) || 'awakening').trim().toLowerCase() || 'awakening';
    const phase = phaseRaw.toUpperCase();
    const xpToNext = (d.maturity && d.maturity.xp_to_next != null) ? Number(d.maturity.xp_to_next) : null;
    const milestones = (d.maturity && Array.isArray(d.maturity.milestones)) ? d.maturity.milestones : [];

    const elRank = document.getElementById('maturity-rank');
    const elPhase = document.getElementById('maturity-phase');
    const elXp = document.getElementById('maturity-xp');
    const fill = document.getElementById('maturity-bar-fill');
    const sigil = document.getElementById('maturity-sigil');
    const msList = document.getElementById('maturity-milestones-list');

    if (elRank) elRank.textContent = isFinite(rank) ? String(rank) : '0';
    if (elPhase) elPhase.textContent = phase;
    const need = (xpToNext != null && isFinite(xpToNext) && xpToNext > 0) ? xpToNext : null;
    if (elXp) elXp.textContent = need ? (xp + ' / ' + need) : (String(xp) + ' / —');
    if (fill) fill.style.width = need ? (Math.max(0, Math.min(100, Math.floor((xp / need) * 100))) + '%') : '0%';

    try {
      if (sigil) {
        sigil.setAttribute('data-phase', phaseRaw);
        const src = '/layla-ui/assets/sigils/' + encodeURIComponent(phaseRaw) + '.svg';
        sigil.innerHTML = '<img src="' + src + '" alt="" onerror="this.remove()" />';
      }
    } catch (_) {}

    try {
      if (msList) {
        if (!milestones.length) {
          msList.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">No milestones yet.</span>';
        } else {
          msList.innerHTML = milestones.slice(0, 8).map(m => {
            const done = !!(m && m.completed);
            const label = escapeHtml(String((m && (m.label || m.id)) || ''));
            const prog = escapeHtml(String((m && (m.progress || '')) || ''));
            return '<div class="maturity-milestone-row' + (done ? ' completed' : '') + '">' +
              '<div class="maturity-milestone-label">' + (done ? '✓ ' : '○ ') + label + '</div>' +
              '<div class="maturity-milestone-progress">' + prog + '</div>' +
              '</div>';
          }).join('');
        }
      }
    } catch (_) {}

    // Rank-up ceremony
    try {
      const lastRank = Number(localStorage.getItem('layla_last_maturity_rank') || '0');
      localStorage.setItem('layla_last_maturity_rank', String(rank));
      if (showCeremony && isFinite(lastRank) && rank > lastRank) {
        const ov = document.getElementById('rankup-overlay');
        const detail = document.getElementById('rankup-detail');
        if (detail) detail.textContent = 'Mastery Rank increased to ' + rank + ' (' + phase + ').';
        if (ov) {
          ov.classList.add('visible');
          setTimeout(() => ov.classList.remove('visible'), 2200);
        }
        showToast('Rank up: MR ' + rank);
        bus.emit('growth:rank-up', { rank, phase });
      }
    } catch (_) {}
  } catch (_) {}
}

// ── Aspect description toggle ────────────────────────────────────────────────
export function toggleAspectDescription(id) {
  document.querySelectorAll('.aspect-option.expandable').forEach(el => {
    const isTarget = el.id === ('aspect-opt-' + id);
    el.classList.toggle('expanded', isTarget ? !el.classList.contains('expanded') : false);
  });
}

export function expandAspectDescription(id) {
  document.querySelectorAll('.aspect-option.expandable').forEach(el => {
    el.classList.toggle('expanded', el.id === ('aspect-opt-' + id));
  });
}

// ── Sidebar highlight for onboarding ─────────────────────────────────────────
export function highlightAspectSidebar(on) {
  const el = document.querySelector('.layout .sidebar');
  if (!el) return;
  el.classList.toggle('onboarding-highlight', !!on);
}

// ── Options dependency refresh ───────────────────────────────────────────────
export function refreshOptionDependencies() {
  const showThinkingEl = document.getElementById('show-thinking');
  const showThinking = showThinkingEl ? showThinkingEl.checked : false;
  const reasoningRow = document.getElementById('reasoning-effort-row');
  const reasoningBox = document.getElementById('reasoning-effort');
  if (reasoningRow && reasoningBox) {
    const disabled = !showThinking;
    reasoningRow.classList.toggle('disabled', disabled);
    reasoningBox.disabled = disabled;
    if (disabled) reasoningBox.checked = false;
  }
  const wpEl = document.getElementById('workspace-path');
  const wp = wpEl ? (wpEl.value || '').trim() : '';
  const addBtn = document.getElementById('workspace-add-btn');
  const removeBtn = document.getElementById('workspace-remove-btn');
  if (addBtn) {
    addBtn.disabled = !wp;
    addBtn.style.opacity = wp ? '1' : '0.45';
    addBtn.style.pointerEvents = wp ? 'auto' : 'none';
  }
  if (removeBtn) {
    removeBtn.disabled = !wp;
    removeBtn.style.opacity = wp ? '1' : '0.45';
    removeBtn.style.pointerEvents = wp ? 'auto' : 'none';
  }
}
