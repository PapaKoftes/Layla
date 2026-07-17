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
  const s = String(aspectNameOrId).trim().toLowerCase();
  return ASPECTS.find(a => a.id === s || a.name.toLowerCase() === s) || null;
}

export function formatLaylaLabelHtml(aspectId) {
  const aid = String(aspectId || 'morrigan').toLowerCase();
  const a = ASPECTS.find(x => x.id === aid) || ASPECTS[0];
  const sym = String(a.sym || '').replace(/</g, '&lt;');
  const name = String(a.name || '').replace(/</g, '&lt;');
  return `<span class="msg-brand">Layla</span><span class="msg-facet-chip" title="Facet (voice)"><span class="aspect-sigil">${sym}</span> ${name}</span>`;
}

// ── Aspect switching ─────────────────────────────────────────────────────────
let _lastAspectSwitchTime = 0;
let _aspectLocked = false;

export function setAspect(id, force) {
  if (_aspectLocked && !force) return;

  // Update state (triggers compat bridge's property descriptor)
  appState.set('aspect.current', id);

  // Update sidebar buttons
  document.querySelectorAll('.aspect-btn').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('btn-' + id);
  if (btn) btn.classList.add('active');

  // Reflect the active aspect in the collapsed sidebar summary (name · function).
  // BL-301: a custom aspect id is not in the built-in ASPECTS registry — fall back to the id
  // itself, NOT ASPECTS[0] (which would mislabel the active custom aspect as "Morrigan").
  const _meta = ASPECTS.find(a => a.id === id) || { name: id, fn: '' };
  const sva = document.getElementById('sidebar-voices-active');
  if (sva) sva.textContent = _meta.name + (_meta.fn ? ' · ' + _meta.fn : '');

  // Update badges
  const sym = ASPECT_SYMBOLS[id] || '∴';
  // Wrap the sigil in .aspect-sigil so one canonical rule normalizes it (the badge otherwise
  // inherits Cinzel serif; sym/id come from the fixed ASPECT_SYMBOLS map so this is injection-safe).
  const _sigilHtml = '<span class="aspect-sigil">' + sym + '</span> ' + id.toUpperCase();
  const badge = document.getElementById('aspect-badge');
  if (badge) {
    badge.innerHTML = _sigilHtml;
    badge.style.animation = 'none';
    void badge.offsetWidth;
    badge.style.animation = '';
  }
  const topBadge = document.getElementById('topbar-aspect-badge');
  if (topBadge) topBadge.innerHTML = _sigilHtml;

  // Apply CSS custom properties
  const c = ASPECT_COLORS[id] || ASPECT_COLORS.morrigan;
  const root = document.documentElement.style;
  if (document.body) document.body.setAttribute('data-aspect', id);
  root.setProperty('--asp',      c.asp);
  root.setProperty('--asp-glow', c.glow);
  root.setProperty('--asp-mid',  c.mid);

  // Toast
  if (Date.now() - _lastAspectSwitchTime > 300) {
    _lastAspectSwitchTime = Date.now();
    const meta = ASPECTS.find(a => a.id === id);
    showToast('Now talking to ' + (meta ? meta.name : id));
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
