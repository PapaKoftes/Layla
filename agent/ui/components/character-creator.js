/**
 * components/character-creator.js — Full videogame-style Character Lab for Layla's 6 aspects.
 *
 * Converted from js/layla-character-creator.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast, laylaConfirm)
 *
 * Features:
 *   - Visual aspect selection with animated cards
 *   - Personality sliders (aggression, humor, verbosity, curiosity, bluntness, empathy)
 *   - Voice profile tuning (pitch, speed, warmth, formality)
 *   - Title selection (unlockable via maturity rank)
 *   - Color customization (primary color, glow)
 *   - Lore display (origin story, philosophy)
 *   - Reset to defaults
 *   - Tutorial / intro integration
 */

import { escapeHtml, showToast, laylaConfirm } from '../services/utils.js';

// ── State ───────────────────────────────────────────────────────────────────
let _profiles = {};
let _traitsMeta = [];
let _voiceMeta = [];
let _selectedAspect = 'morrigan';
let _tutorialState = {};
let _maturityRank = 0;
let _charLabOpen = false;
let _dirty = {};

// ── API helper ──────────────────────────────────────────────────────────────
function _api(path, opts) {
  const _ft = (typeof window.fetchWithTimeout === 'function') ? window.fetchWithTimeout : fetch;
  return _ft('/character' + path, opts).then(function (r) { return r.json(); }).catch(function (e) {
    return { ok: false, error: String(e) };
  });
}

// ── Data loading ────────────────────────────────────────────────────────────
export function loadCharacterData() {
  return Promise.all([
    _api('/summary'),
    _api('/traits'),
    _api('/voice-params'),
  ]).then(function (results) {
    const summary = results[0] || {};
    _traitsMeta = (results[1] && results[1].traits) || [];
    _voiceMeta = (results[2] && results[2].params) || [];
    _tutorialState = summary.tutorial || {};
    _maturityRank = summary.maturity_rank || 0;

    const aspects = summary.aspects || {};
    Object.keys(aspects).forEach(function (aid) {
      _profiles[aid] = aspects[aid];
    });

    if (Object.keys(_profiles).length === 0) {
      return _api('/aspects').then(function (all) {
        Object.keys(all).forEach(function (aid) {
          if (all[aid] && all[aid].ok !== false) _profiles[aid] = all[aid];
        });
      });
    }
  });
}

// ── Slider renderer ─────────────────────────────────────────────────────────
function _renderSlider(id, label, desc, value, min, max, step, group) {
  const pct = ((value - min) / (max - min)) * 100;
  let html = '<div class="charlab-slider-row">';
  html += '<div class="charlab-slider-label">' + escapeHtml(label) + '</div>';
  html += '<div class="charlab-slider-wrap">';
  html += '<input type="range" class="charlab-slider" data-group="' + escapeHtml(group) + '" data-id="' + escapeHtml(id) + '"'
    + ' min="' + min + '" max="' + max + '" step="' + step + '" value="' + value + '"'
    + ' style="--slider-pct:' + pct + '%"'
    + ' aria-label="' + escapeHtml(label) + '"'
    + ' title="' + escapeHtml(desc) + '">';
  html += '<span class="charlab-slider-val" data-val-for="' + escapeHtml(group) + '_' + escapeHtml(id) + '">' + value + '</span>';
  html += '</div></div>';
  return html;
}

// ── Aspect detail panel ─────────────────────────────────────────────────────
function _renderAspectDetail(aid) {
  const p = _profiles[aid] || {};
  const color = p.color_primary || '#888';
  const glow = p.color_glow || 'rgba(128,128,128,0.28)';
  const sym = escapeHtml(p.symbol || '?');
  const name = escapeHtml(p.name || aid);
  const title = escapeHtml(p.title || '');
  const tagline = escapeHtml(p.tagline || '');

  let html = '<div class="charlab-detail" style="--detail-color:' + escapeHtml(color) + ';--detail-glow:' + escapeHtml(glow) + '">';

  // Identity header
  html += '<div class="charlab-identity">';
  html += '<div class="charlab-avatar" style="background:' + escapeHtml(color) + ';box-shadow:0 0 20px ' + escapeHtml(glow) + '">';
  html += '<span class="charlab-avatar-sym">' + sym + '</span></div>';
  html += '<div class="charlab-id-text">';
  html += '<div class="charlab-name">' + name + '</div>';
  html += '<div class="charlab-active-title">' + title + '</div>';
  html += '<div class="charlab-tagline">' + tagline + '</div>';
  html += '</div></div>';

  // Personality sliders
  html += '<div class="charlab-section"><div class="charlab-section-title">Personality</div><div class="charlab-sliders">';
  _traitsMeta.forEach(function (t) {
    const personality = p.personality || {};
    const val = (personality[t.id] !== undefined) ? personality[t.id] : (p['personality_' + t.id] || 5);
    html += _renderSlider(t.id, t.icon + ' ' + t.label, t.desc, val, t.min || 1, t.max || 10, 1, 'personality');
  });
  html += '</div></div>';

  // Voice profile
  html += '<div class="charlab-section"><div class="charlab-section-title">Voice Profile</div><div class="charlab-sliders">';
  _voiceMeta.forEach(function (v) {
    const voice = p.voice || {};
    const val = (voice[v.id] !== undefined) ? voice[v.id] : (p['voice_' + v.id] || 1.0);
    html += _renderSlider(v.id, v.label, v.desc, val, v.min || 0, v.max || 2.0, v.step || 0.05, 'voice');
  });
  html += '</div></div>';

  // Color customization
  html += '<div class="charlab-section"><div class="charlab-section-title">Colors</div>';
  html += '<div class="charlab-color-row"><label class="charlab-color-label">Primary';
  html += '<input type="color" class="charlab-color-input" data-field="color_primary" value="' + escapeHtml(color) + '">';
  html += '</label><div class="charlab-color-preview" style="background:' + escapeHtml(color) + ';box-shadow:0 0 12px ' + escapeHtml(glow) + '"></div></div></div>';

  // Titles
  const titles = p.available_titles || [];
  if (titles.length > 0) {
    html += '<div class="charlab-section"><div class="charlab-section-title">Title</div><div class="charlab-titles">';
    titles.forEach(function (t) {
      const isActive = (t.title === (p.title || p.active_title));
      html += '<button type="button" class="charlab-title-btn' + (isActive ? ' active' : '') + '"'
        + ' data-title="' + escapeHtml(t.title) + '"'
        + ' title="' + escapeHtml(t.condition) + '">'
        + escapeHtml(t.title) + '</button>';
    });
    html += '</div></div>';
  }

  // Lore
  const loreOrigin = p.lore_origin || '';
  const lorePhilosophy = p.lore_philosophy || '';
  if (loreOrigin || lorePhilosophy) {
    html += '<div class="charlab-section"><div class="charlab-section-title">Lore</div><div class="charlab-lore">';
    if (loreOrigin) html += '<div class="charlab-lore-block"><strong>Origin:</strong> ' + escapeHtml(loreOrigin) + '</div>';
    if (lorePhilosophy) html += '<div class="charlab-lore-block"><strong>Philosophy:</strong> ' + escapeHtml(lorePhilosophy) + '</div>';
    html += '</div></div>';
  }

  // Prompt hints preview
  html += '<div class="charlab-section"><div class="charlab-section-title">Active Prompt Hints</div>';
  html += '<div id="charlab-hints-preview" class="charlab-hints">Loading hints...</div></div>';

  // Actions
  html += '<div class="charlab-actions">';
  html += '<button type="button" class="charlab-btn charlab-btn-save" id="charlab-save-btn" title="Save all changes">Save Changes</button>';
  html += '<button type="button" class="charlab-btn charlab-btn-main" id="charlab-setmain-btn" title="Set as your default aspect">Set as Main</button>';
  html += '<button type="button" class="charlab-btn charlab-btn-reset" id="charlab-reset-btn" title="Reset to factory defaults">Reset Defaults</button>';
  html += '</div>';

  html += '</div>';

  setTimeout(function () { _loadHintsPreview(aid); }, 100);
  return html;
}

// ── Bindings ────────────────────────────────────────────────────────────────
function _bindSliders(container) {
  container.querySelectorAll('.charlab-slider').forEach(function (sl) {
    sl.addEventListener('input', function () {
      const group = sl.getAttribute('data-group');
      const id = sl.getAttribute('data-id');
      const val = parseFloat(sl.value);
      const valSpan = container.querySelector('[data-val-for="' + group + '_' + id + '"]');
      if (valSpan) valSpan.textContent = (Number.isInteger(val) ? val : val.toFixed(2));
      const key = group + '_' + id;
      if (!_dirty[_selectedAspect]) _dirty[_selectedAspect] = {};
      _dirty[_selectedAspect][key] = val;
      const min = parseFloat(sl.min);
      const max = parseFloat(sl.max);
      const pct = ((val - min) / (max - min)) * 100;
      sl.style.setProperty('--slider-pct', pct + '%');
    });
  });
}

function _bindColorPickers(container) {
  container.querySelectorAll('.charlab-color-input').forEach(function (inp) {
    inp.addEventListener('input', function () {
      const field = inp.getAttribute('data-field');
      if (!_dirty[_selectedAspect]) _dirty[_selectedAspect] = {};
      _dirty[_selectedAspect][field] = inp.value;
    });
  });
}

function _bindTitleSelect(container) {
  container.querySelectorAll('.charlab-title-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const titleVal = btn.getAttribute('data-title');
      _api('/aspects/' + _selectedAspect + '/title', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: titleVal }),
      }).then(function (r) {
        if (r.ok !== false) {
          showToast('Title set: ' + titleVal);
          return loadCharacterData().then(renderCharacterLab);
        }
        showToast('Failed: ' + (r.error || 'unknown'));
      });
    });
  });
}

function _bindActionButtons(container) {
  const saveBtn = container.querySelector('#charlab-save-btn');
  const mainBtn = container.querySelector('#charlab-setmain-btn');
  const resetBtn = container.querySelector('#charlab-reset-btn');

  if (saveBtn) saveBtn.addEventListener('click', _saveCurrentAspect);
  if (mainBtn) mainBtn.addEventListener('click', function () {
    _api('/main-aspect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ aspect_id: _selectedAspect }),
    }).then(function (r) {
      if (r.ok !== false) {
        showToast(_selectedAspect.charAt(0).toUpperCase() + _selectedAspect.slice(1) + ' set as main aspect');
        if (typeof window.setAspect === 'function') window.setAspect(_selectedAspect);
        try { localStorage.setItem('layla_default_aspect', _selectedAspect); } catch (_) {}
      } else {
        showToast('Failed: ' + (r.error || 'unknown'));
      }
    });
  });
  if (resetBtn) resetBtn.addEventListener('click', async function () {
    if (!(await laylaConfirm('Reset ' + _selectedAspect + ' to factory defaults? All customizations will be lost.'))) return;
    _api('/aspects/' + _selectedAspect + '/reset', { method: 'POST' }).then(function (r) {
      if (r.ok !== false) {
        showToast(_selectedAspect + ' reset to defaults');
        delete _dirty[_selectedAspect];
        return loadCharacterData().then(renderCharacterLab);
      }
      showToast('Reset failed: ' + (r.error || 'unknown'));
    });
  });
}

// ── Save ────────────────────────────────────────────────────────────────────
function _saveCurrentAspect() {
  const changes = _dirty[_selectedAspect];
  if (!changes || Object.keys(changes).length === 0) {
    showToast('No changes to save');
    return;
  }
  _api('/aspects/' + _selectedAspect, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  }).then(function (r) {
    if (r.ok !== false) {
      showToast('Saved ' + (r.saved_keys || []).length + ' changes for ' + _selectedAspect);
      delete _dirty[_selectedAspect];
      return loadCharacterData().then(renderCharacterLab);
    }
    showToast('Save failed: ' + (r.error || 'unknown'));
  });
}

// ── Hints preview ───────────────────────────────────────────────────────────
function _loadHintsPreview(aid) {
  const el = document.getElementById('charlab-hints-preview');
  if (!el) return;
  _api('/aspects/' + aid + '/prompt-hints').then(function (r) {
    if (!el) return;
    const hints = (r && r.hints) || [];
    if (hints.length === 0) {
      el.innerHTML = '<span style="color:var(--text-dim);font-size:0.68rem">No special hints active (sliders near center)</span>';
      return;
    }
    el.innerHTML = hints.map(function (h) { return '<div class="charlab-hint-item">' + escapeHtml(h) + '</div>'; }).join('');
  });
}

// ── Main render ─────────────────────────────────────────────────────────────
export function renderCharacterLab() {
  const container = document.getElementById('character-lab-container');
  if (!container) return;

  let html = '';
  html += '<div class="charlab-header"><div class="charlab-title">Character Lab</div>';
  html += '<div class="charlab-subtitle">Customize Layla\'s aspects — personality, voice, appearance, titles</div></div>';

  // Aspect selector strip
  html += '<div class="charlab-aspect-strip" role="tablist" aria-label="Aspect selector">';
  const aspectOrder = ['morrigan', 'nyx', 'echo', 'eris', 'cassandra', 'lilith'];
  aspectOrder.forEach(function (aid) {
    const p = _profiles[aid] || {};
    const isActive = (aid === _selectedAspect);
    html += '<button type="button" class="charlab-aspect-card' + (isActive ? ' active' : '') + '"'
      + ' data-aspect="' + escapeHtml(aid) + '"'
      + ' role="tab" aria-selected="' + isActive + '"'
      + ' style="--card-color:' + escapeHtml(p.color_primary || '#888') + '"'
      + ' title="' + escapeHtml(p.name || aid) + '">'
      + '<div class="charlab-card-sym">' + escapeHtml(p.symbol || '?') + '</div>'
      + '<div class="charlab-card-name">' + escapeHtml(p.name || aid) + '</div></button>';
  });
  html += '</div>';

  html += _renderAspectDetail(_selectedAspect);
  container.innerHTML = html;

  // Bind interactions
  container.querySelectorAll('.charlab-aspect-card').forEach(function (btn) {
    btn.addEventListener('click', function () {
      _selectedAspect = btn.getAttribute('data-aspect') || 'morrigan';
      renderCharacterLab();
    });
  });
  _bindSliders(container);
  _bindColorPickers(container);
  _bindTitleSelect(container);
  _bindActionButtons(container);
}

// ── Character Lab panel toggle ──────────────────────────────────────────────
export function openCharacterLab() {
  const overlay = document.getElementById('character-lab-overlay');
  if (!overlay) return;
  _charLabOpen = true;
  overlay.classList.add('visible');
  overlay.setAttribute('aria-hidden', 'false');
  loadCharacterData().then(renderCharacterLab);
}

export function closeCharacterLab() {
  const overlay = document.getElementById('character-lab-overlay');
  if (!overlay) return;
  _charLabOpen = false;
  overlay.classList.remove('visible');
  overlay.setAttribute('aria-hidden', 'true');
}

// ── Wizard integration ──────────────────────────────────────────────────────
export function renderWizardCharacterStep(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  return loadCharacterData().then(function () {
    let html = '<div class="charlab-wizard">';
    html += '<div class="charlab-wizard-title">Choose Your Primary Aspect</div>';
    html += '<div class="charlab-wizard-desc">Each aspect shapes how Layla thinks, speaks, and solves problems. '
      + 'Pick the one that fits your style — you can customize all six later in the Character Lab.</div>';
    html += '<div class="charlab-wizard-grid">';

    const aspectOrder = ['morrigan', 'nyx', 'echo', 'eris', 'cassandra', 'lilith'];
    aspectOrder.forEach(function (aid) {
      const p = _profiles[aid] || {};
      const color = p.color_primary || '#888';
      const isSelected = (aid === _selectedAspect);
      html += '<button type="button" class="charlab-wizard-card' + (isSelected ? ' selected' : '') + '"'
        + ' data-wiz-aspect="' + escapeHtml(aid) + '" style="--card-color:' + escapeHtml(color) + '">';
      html += '<div class="charlab-wizard-sym" style="color:' + escapeHtml(color) + '">' + escapeHtml(p.symbol || '?') + '</div>';
      html += '<div class="charlab-wizard-name">' + escapeHtml(p.name || aid) + '</div>';
      html += '<div class="charlab-wizard-tag">' + escapeHtml(p.tagline || '') + '</div>';

      const personality = p.personality || {};
      html += '<div class="charlab-wizard-stats">';
      _traitsMeta.forEach(function (t) {
        const val = personality[t.id] || 5;
        const pct = (val / 10) * 100;
        html += '<div class="charlab-mini-bar"><span class="charlab-mini-label">' + escapeHtml(t.icon) + '</span>';
        html += '<div class="charlab-mini-track"><div class="charlab-mini-fill" style="width:' + pct + '%;background:' + escapeHtml(color) + '"></div></div></div>';
      });
      html += '</div></button>';
    });
    html += '</div></div>';
    container.innerHTML = html;

    container.querySelectorAll('.charlab-wizard-card').forEach(function (card) {
      card.addEventListener('click', function () {
        _selectedAspect = card.getAttribute('data-wiz-aspect') || 'morrigan';
        container.querySelectorAll('.charlab-wizard-card').forEach(function (c) {
          c.classList.toggle('selected', c.getAttribute('data-wiz-aspect') === _selectedAspect);
        });
        if (typeof window.setAspect === 'function') window.setAspect(_selectedAspect);
        try { localStorage.setItem('layla_default_aspect', _selectedAspect); } catch (_) {}
      });
    });
  });
}

// ── Tutorial ────────────────────────────────────────────────────────────────
const TUTORIAL_STEPS = [
  { id: 'welcome', title: 'Welcome to Layla', text: 'Layla is your sovereign AI companion. She runs entirely on your machine, learns your preferences, and grows alongside you.', highlight: null },
  { id: 'aspects', title: 'Meet the Aspects', text: 'Layla has 6 personality facets — each one shapes how she thinks and communicates. You\'ve already chosen your primary. The others unlock as you use them.', highlight: '#aspect-bar' },
  { id: 'chat', title: 'Start Talking', text: 'Type anything in the chat box. Layla can write code, research topics, plan projects, and learn about you over time.', highlight: '#msg-input' },
  { id: 'memory', title: 'Memory System', text: 'Everything Layla learns is stored locally. Check the Memory tab to see what she remembers. You can edit or delete any learning.', highlight: '[data-rcp="workspace"]' },
  { id: 'character_lab', title: 'Character Lab', text: 'Customize each aspect\'s personality, voice, and appearance in the Character Lab. Open it any time from the header.', highlight: '#charlab-open-btn' },
  { id: 'complete', title: 'You\'re Ready', text: 'That\'s the basics. Layla will adapt to your style as you work together. Enjoy.', highlight: null },
];

let _tutStep = 0;

export function startTutorial() {
  _tutStep = 0;
  _renderTutorialStep();
  const overlay = document.getElementById('tutorial-overlay');
  if (overlay) {
    overlay.classList.add('visible');
    overlay.setAttribute('aria-hidden', 'false');
  }
}

function _renderTutorialStep() {
  const overlay = document.getElementById('tutorial-overlay');
  if (!overlay) return;

  const step = TUTORIAL_STEPS[_tutStep] || TUTORIAL_STEPS[0];
  const isLast = (_tutStep >= TUTORIAL_STEPS.length - 1);

  let html = '<div class="tutorial-dialog"><div class="tutorial-progress">';
  for (let i = 0; i < TUTORIAL_STEPS.length; i++) {
    html += '<span class="tutorial-dot' + (i === _tutStep ? ' active' : '') + (i < _tutStep ? ' done' : '') + '"></span>';
  }
  html += '</div>';
  html += '<div class="tutorial-title">' + escapeHtml(step.title) + '</div>';
  html += '<div class="tutorial-text">' + escapeHtml(step.text) + '</div>';
  html += '<div class="tutorial-actions">';
  if (_tutStep > 0) html += '<button type="button" class="tutorial-btn tutorial-btn-back" id="tut-back">Back</button>';
  html += '<button type="button" class="tutorial-btn tutorial-btn-next" id="tut-next">' + (isLast ? 'Finish' : 'Next') + '</button>';
  html += '<button type="button" class="tutorial-btn tutorial-btn-skip" id="tut-skip">Skip Tutorial</button>';
  html += '</div></div>';

  overlay.innerHTML = html;

  // Highlight target element
  document.querySelectorAll('.tutorial-highlight').forEach(function (el) { el.classList.remove('tutorial-highlight'); });
  if (step.highlight) {
    const target = document.querySelector(step.highlight);
    if (target) target.classList.add('tutorial-highlight');
  }

  const nextBtn = document.getElementById('tut-next');
  const backBtn = document.getElementById('tut-back');
  const skipBtn = document.getElementById('tut-skip');

  if (nextBtn) nextBtn.addEventListener('click', function () {
    if (isLast) { _completeTutorial(); } else {
      _tutStep++;
      _api('/tutorial/advance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ step: _tutStep }) });
      _renderTutorialStep();
    }
  });
  if (backBtn) backBtn.addEventListener('click', function () { if (_tutStep > 0) { _tutStep--; _renderTutorialStep(); } });
  if (skipBtn) skipBtn.addEventListener('click', _completeTutorial);
}

function _completeTutorial() {
  document.querySelectorAll('.tutorial-highlight').forEach(function (el) { el.classList.remove('tutorial-highlight'); });
  const overlay = document.getElementById('tutorial-overlay');
  if (overlay) { overlay.classList.remove('visible'); overlay.setAttribute('aria-hidden', 'true'); }
  _api('/tutorial/advance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ step: 99 }) });
  showToast('Tutorial complete!');
}

// ── Init ────────────────────────────────────────────────────────────────────
export function initCharacterCreator() {
  try {
    const stored = localStorage.getItem('layla_default_aspect');
    if (stored) _selectedAspect = stored;
  } catch (_) {}

  loadCharacterData().then(function () {
    if (_tutorialState && !_tutorialState.tutorial_complete && _tutorialState.wizard_complete) {
      setTimeout(function () { startTutorial(); }, 1500);
    }
  }).catch(function () {});
}
