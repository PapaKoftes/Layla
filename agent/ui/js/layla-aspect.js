/**
 * layla-aspect.js — Aspect switching, maturity card, and aspect registry.
 * Depends on: layla-utils.js (escapeHtml, showToast)
 */
(function () {
  'use strict';

  // ── Per-aspect color palette ───────────────────────────────────────────────
  var ASPECT_COLORS = {
    morrigan: { asp: '#8b0000', glow: 'rgba(139,0,0,0.28)',   mid: 'rgba(139,0,0,0.10)' },
    nyx:      { asp: '#3a1f9a', glow: 'rgba(58,31,154,0.28)', mid: 'rgba(58,31,154,0.10)' },
    echo:     { asp: '#006878', glow: 'rgba(0,104,120,0.28)', mid: 'rgba(0,104,120,0.10)' },
    eris:     { asp: '#8a4000', glow: 'rgba(138,64,0,0.28)',  mid: 'rgba(138,64,0,0.10)' },
    cassandra: { asp: '#4a1a7a', glow: 'rgba(74,26,122,0.28)', mid: 'rgba(74,26,122,0.10)' },
    lilith:   { asp: '#6a0070', glow: 'rgba(106,0,112,0.28)', mid: 'rgba(106,0,112,0.10)' },
  };
  window.ASPECT_COLORS = ASPECT_COLORS;

  // ── Aspect registry ────────────────────────────────────────────────────────
  var ASPECTS = [
    { id: 'morrigan', sym: '⚔', name: 'Morrigan', desc: 'Code, debug, architecture — the blade' },
    { id: 'nyx',      sym: '✦', name: 'Nyx',      desc: 'Research, depth, synthesis' },
    { id: 'echo',     sym: '◎', name: 'Echo',     desc: 'Reflection, patterns, memory' },
    { id: 'eris',     sym: '⚡', name: 'Eris',     desc: 'Creative chaos, banter, lateral leaps' },
    { id: 'cassandra',sym: '⌖', name: 'Cassandra',desc: 'Unfiltered oracle — sees it first' },
    { id: 'lilith',   sym: '⊛', name: 'Lilith',   desc: 'Sovereign will, ethics, full honesty' },
  ];
  window.ASPECTS = ASPECTS;

  function facetMetaFromNameOrId(aspectNameOrId) {
    if (!aspectNameOrId) return null;
    var s = String(aspectNameOrId).trim().toLowerCase();
    return ASPECTS.find(function (a) { return a.id === s || a.name.toLowerCase() === s; }) || null;
  }
  window.facetMetaFromNameOrId = facetMetaFromNameOrId;

  function formatLaylaLabelHtml(aspectId) {
    var aid = String(aspectId || 'morrigan').toLowerCase();
    var a = ASPECTS.find(function (x) { return x.id === aid; }) || ASPECTS[0];
    var sym = String(a.sym || '').replace(/</g, '&lt;');
    var name = String(a.name || '').replace(/</g, '&lt;');
    return '<span class="msg-brand">Layla</span><span class="msg-facet-chip" title="Facet (voice)">' + sym + ' ' + name + '</span>';
  }
  window.formatLaylaLabelHtml = formatLaylaLabelHtml;

  // ── Aspect switching ───────────────────────────────────────────────────────
  var _lastAspectSwitchTime = 0;
  window._aspectLocked = false;

  function setAspect(id, force) {
    if (window._aspectLocked && !force) return;
    window.currentAspect = id;
    document.querySelectorAll('.aspect-btn').forEach(function (b) { b.classList.remove('active'); });
    var btn = document.getElementById('btn-' + id);
    if (btn) btn.classList.add('active');
    var badge = document.getElementById('aspect-badge');
    var ASPECT_SYMBOLS = { morrigan:'⚔', nyx:'✦', echo:'◎', eris:'⚡', cassandra:'⌖', lilith:'⊛' };
    var sym = ASPECT_SYMBOLS[id] || '∴';
    if (badge) { badge.textContent = sym + ' ' + id.toUpperCase(); badge.style.animation = 'none'; void badge.offsetWidth; badge.style.animation = ''; }
    var c = ASPECT_COLORS[id] || ASPECT_COLORS.morrigan;
    var root = document.documentElement.style;
    if (document.body) document.body.setAttribute('data-aspect', id);
    root.setProperty('--asp',      c.asp);
    root.setProperty('--asp-glow', c.glow);
    root.setProperty('--asp-mid',  c.mid);
    if (Date.now() - _lastAspectSwitchTime > 300) {
      _lastAspectSwitchTime = Date.now();
      var name = ASPECTS.find(function (a) { return a.id === id; });
      if (typeof showToast === 'function') showToast('Now talking to ' + (name ? name.name : id));
    }
    try { if (typeof updateContextChip === 'function') updateContextChip(); } catch (_) {}
    try {
      var doodles = {
        morrigan: '⚔ ⟁ ⚔ ⎔ ⚔ ◈\n/\\\\==/\\\\  ─┼─  /\\\\==/\\\\\n⎔  ◈  ⟁  ⚔  ⟁  ◈',
        nyx: '✦ ⊛ ∴ ✦ ⌁ ✦\n..✦..::...✦..::..\n⌁  ✦  ⊛  ∴  ✦  ⌁',
        echo: '◎ ∞ ◎ ⟡ ◎ ∞\n====  ~~~  ====\n⟡  ◎  ∞  ◎  ⟡',
        eris: '⚡ ⊘ ⚡ ⌇ ⚡ ⊘\n/\\/\\/\\/\\  ╱╲  /\\/\\/\\/\\\n⌇  ⚡  ⊘  ⚡  ⌇',
        cassandra: '⌖ △ ⌖ ⟟ ⌖ △\n<>  /\\  <>  /\\  <>\n⟟  ⌖  △  ⌖  ⟟',
        lilith: '⊛ ♾ ✶ ⊛ ⟁ ⊛\n###  ╳  ###  ╳  ###\n✶  ⊛  ♾  ⊛  ✶',
      };
      var ov = document.getElementById('doodle-overlay');
      if (ov) ov.textContent = (doodles[id] || doodles.morrigan).repeat(180);
    } catch (_) {}
    try {
      if (typeof window.laylaSetAspectSprite === 'function') window.laylaSetAspectSprite(id);
    } catch (_) {}
  }
  window.setAspect = setAspect;

  // ── Aspect lock ────────────────────────────────────────────────────────────
  function toggleAspectLock() {
    window._aspectLocked = !window._aspectLocked;
    var btn = document.getElementById('aspect-lock-btn');
    if (btn) {
      btn.textContent = window._aspectLocked ? '🔒' : '🔓';
      btn.classList.toggle('locked', window._aspectLocked);
      btn.title = window._aspectLocked
        ? 'Locked to ' + (window.currentAspect || 'morrigan').toUpperCase() + ' — click to unlock'
        : 'Lock this aspect (prevent auto-routing)';
    }
  }
  window.toggleAspectLock = toggleAspectLock;

  // ── Maturity / Mastery rank UI ─────────────────────────────────────────────
  async function refreshMaturityCard(showCeremony) {
    try {
      var r = await fetch('/operator/profile');
      var d = await r.json();
      if (!d || !d.ok) return;
      var rank = (d.maturity && d.maturity.rank != null) ? Number(d.maturity.rank) : 0;
      var xp = (d.maturity && d.maturity.xp != null) ? Number(d.maturity.xp) : 0;
      var phaseRaw = String((d.maturity && d.maturity.phase) || 'awakening').trim().toLowerCase() || 'awakening';
      var phase = phaseRaw.toUpperCase();
      var xpToNext = (d.maturity && d.maturity.xp_to_next != null) ? Number(d.maturity.xp_to_next) : null;
      var milestones = (d.maturity && Array.isArray(d.maturity.milestones)) ? d.maturity.milestones : [];
      var elRank = document.getElementById('maturity-rank');
      var elPhase = document.getElementById('maturity-phase');
      var elXp = document.getElementById('maturity-xp');
      var fill = document.getElementById('maturity-bar-fill');
      var sigil = document.getElementById('maturity-sigil');
      var msList = document.getElementById('maturity-milestones-list');
      if (elRank) elRank.textContent = isFinite(rank) ? String(rank) : '0';
      if (elPhase) elPhase.textContent = phase;
      var need = (xpToNext != null && isFinite(xpToNext) && xpToNext > 0) ? xpToNext : null;
      if (elXp) elXp.textContent = need ? (xp + ' / ' + need) : (String(xp) + ' / —');
      if (fill) fill.style.width = need ? (Math.max(0, Math.min(100, Math.floor((xp / need) * 100))) + '%') : '0%';
      try {
        if (sigil) {
          sigil.setAttribute('data-phase', phaseRaw);
          var src = '/layla-ui/assets/sigils/' + encodeURIComponent(phaseRaw) + '.svg';
          sigil.innerHTML = '<img src="' + src + '" alt="" onerror="this.remove()" />';
        }
      } catch (_) {}
      try {
        if (msList) {
          if (!milestones.length) {
            msList.innerHTML = '<span style="color:var(--text-dim);font-size:0.7rem">No milestones yet.</span>';
          } else {
            msList.innerHTML = milestones.slice(0, 8).map(function (m) {
              var done = !!(m && m.completed);
              var label = escapeHtml(String((m && (m.label || m.id)) || ''));
              var prog = escapeHtml(String((m && (m.progress || '')) || ''));
              return '<div class="maturity-milestone-row' + (done ? ' completed' : '') + '">' +
                '<div class="maturity-milestone-label">' + (done ? '✓ ' : '○ ') + label + '</div>' +
                '<div class="maturity-milestone-progress">' + prog + '</div>' +
                '</div>';
            }).join('');
          }
        }
      } catch (_) {}
      try {
        var lastRank = Number(localStorage.getItem('layla_last_maturity_rank') || '0');
        localStorage.setItem('layla_last_maturity_rank', String(rank));
        if (showCeremony && isFinite(lastRank) && rank > lastRank) {
          var ov2 = document.getElementById('rankup-overlay');
          var detail = document.getElementById('rankup-detail');
          if (detail) detail.textContent = 'Mastery Rank increased to ' + rank + ' (' + phase + ').';
          if (ov2) {
            ov2.classList.add('visible');
            setTimeout(function () { ov2.classList.remove('visible'); }, 2200);
          }
          if (typeof showToast === 'function') showToast('Rank up: MR ' + rank);
        }
      } catch (_) {}
    } catch (_) {}
  }
  window.refreshMaturityCard = refreshMaturityCard;

  // ── Aspect description toggle ──────────────────────────────────────────────
  function toggleAspectDescription(id) {
    var all = document.querySelectorAll('.aspect-option.expandable');
    all.forEach(function (el) {
      var isTarget = el.id === ('aspect-opt-' + id);
      el.classList.toggle('expanded', isTarget ? !el.classList.contains('expanded') : false);
    });
  }
  window.toggleAspectDescription = toggleAspectDescription;

  function expandAspectDescription(id) {
    document.querySelectorAll('.aspect-option.expandable').forEach(function (el) {
      el.classList.toggle('expanded', el.id === ('aspect-opt-' + id));
    });
  }
  window.expandAspectDescription = expandAspectDescription;

  // ── Sidebar highlight for onboarding ───────────────────────────────────────
  function highlightAspectSidebar(on) {
    var el = document.querySelector('.layout .sidebar');
    if (!el) return;
    el.classList.toggle('onboarding-highlight', !!on);
  }
  window.highlightAspectSidebar = highlightAspectSidebar;

  // ── Options dependency refresh ─────────────────────────────────────────────
  function refreshOptionDependencies() {
    var showThinkingEl = document.getElementById('show-thinking');
    var showThinking = showThinkingEl ? showThinkingEl.checked : false;
    var reasoningRow = document.getElementById('reasoning-effort-row');
    var reasoningBox = document.getElementById('reasoning-effort');
    if (reasoningRow && reasoningBox) {
      var disabled = !showThinking;
      reasoningRow.classList.toggle('disabled', disabled);
      reasoningBox.disabled = disabled;
      if (disabled) reasoningBox.checked = false;
    }
    var wpEl = document.getElementById('workspace-path');
    var wp = wpEl ? (wpEl.value || '').trim() : '';
    var addBtn = document.getElementById('workspace-add-btn');
    var removeBtn = document.getElementById('workspace-remove-btn');
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
  window.refreshOptionDependencies = refreshOptionDependencies;

  window.laylaAspectModuleLoaded = true;
})();
