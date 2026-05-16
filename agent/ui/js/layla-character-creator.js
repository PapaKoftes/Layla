/**
 * layla-character-creator.js — Full videogame-style Character Lab for Layla's 6 aspects.
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
 *
 * Depends on: layla-utils.js (escapeHtml, showToast, fetchWithTimeout)
 *             layla-aspect.js (ASPECT_COLORS, setAspect)
 */
(function () {
  'use strict';

  var _esc = (typeof window.escapeHtml === 'function') ? window.escapeHtml : function (s) { return String(s); };

  // ── State ──────────────────────────────────────────────────────────────────
  var _profiles = {};       // aspect_id -> full profile
  var _traitsMeta = [];     // personality trait metadata
  var _voiceMeta = [];      // voice param metadata
  var _selectedAspect = 'morrigan';
  var _tutorialState = {};
  var _maturityRank = 0;
  var _charLabOpen = false;
  var _dirty = {};          // aspect_id -> {field: value} of unsaved changes

  // ── API helpers ────────────────────────────────────────────────────────────
  var _ft = (typeof window.fetchWithTimeout === 'function') ? window.fetchWithTimeout : fetch;
  var _toast = (typeof window.showToast === 'function') ? window.showToast : function () {};

  function _api(path, opts) {
    return _ft('/character' + path, opts).then(function (r) { return r.json(); }).catch(function (e) {
      return { ok: false, error: String(e) };
    });
  }

  // ── Data loading ───────────────────────────────────────────────────────────

  function loadCharacterData() {
    return Promise.all([
      _api('/summary'),
      _api('/traits'),
      _api('/voice-params'),
    ]).then(function (results) {
      var summary = results[0] || {};
      _traitsMeta = (results[1] && results[1].traits) || [];
      _voiceMeta = (results[2] && results[2].params) || [];
      _tutorialState = summary.tutorial || {};
      _maturityRank = summary.maturity_rank || 0;

      // Build profiles from summary.aspects
      var aspects = summary.aspects || {};
      Object.keys(aspects).forEach(function (aid) {
        _profiles[aid] = aspects[aid];
      });

      // If no profiles from summary, load individually
      if (Object.keys(_profiles).length === 0) {
        return _api('/aspects').then(function (all) {
          Object.keys(all).forEach(function (aid) {
            if (all[aid] && all[aid].ok !== false) _profiles[aid] = all[aid];
          });
        });
      }
    });
  }

  // ── Main render ────────────────────────────────────────────────────────────

  function renderCharacterLab() {
    var container = document.getElementById('character-lab-container');
    if (!container) return;

    var html = '';

    // Header
    html += '<div class="charlab-header">';
    html += '<div class="charlab-title">Character Lab</div>';
    html += '<div class="charlab-subtitle">Customize Layla\'s aspects — personality, voice, appearance, titles</div>';
    html += '</div>';

    // Aspect selector (horizontal card strip)
    html += '<div class="charlab-aspect-strip" role="tablist" aria-label="Aspect selector">';
    var aspectOrder = ['morrigan', 'nyx', 'echo', 'eris', 'cassandra', 'lilith'];
    aspectOrder.forEach(function (aid) {
      var p = _profiles[aid] || {};
      var isActive = (aid === _selectedAspect);
      var color = p.color_primary || '#888';
      var sym = _esc(p.symbol || '?');
      var name = _esc(p.name || aid);
      html += '<button type="button" class="charlab-aspect-card' + (isActive ? ' active' : '') + '"'
        + ' data-aspect="' + _esc(aid) + '"'
        + ' role="tab" aria-selected="' + isActive + '"'
        + ' style="--card-color:' + _esc(color) + '"'
        + ' title="' + name + '">'
        + '<div class="charlab-card-sym">' + sym + '</div>'
        + '<div class="charlab-card-name">' + name + '</div>'
        + '</button>';
    });
    html += '</div>';

    // Detail panel for selected aspect
    html += renderAspectDetail(_selectedAspect);

    container.innerHTML = html;

    // Bind aspect card clicks
    container.querySelectorAll('.charlab-aspect-card').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _selectedAspect = btn.getAttribute('data-aspect') || 'morrigan';
        renderCharacterLab();
      });
    });

    // Bind all interactive elements
    bindSliders(container);
    bindColorPickers(container);
    bindTitleSelect(container);
    bindActionButtons(container);
  }

  // ── Aspect detail panel ────────────────────────────────────────────────────

  function renderAspectDetail(aid) {
    var p = _profiles[aid] || {};
    var color = p.color_primary || '#888';
    var glow = p.color_glow || 'rgba(128,128,128,0.28)';
    var sym = _esc(p.symbol || '?');
    var name = _esc(p.name || aid);
    var title = _esc(p.title || '');
    var tagline = _esc(p.tagline || '');

    var html = '<div class="charlab-detail" style="--detail-color:' + _esc(color) + ';--detail-glow:' + _esc(glow) + '">';

    // ── Identity header ──
    html += '<div class="charlab-identity">';
    html += '<div class="charlab-avatar" style="background:' + _esc(color) + ';box-shadow:0 0 20px ' + _esc(glow) + '">';
    html += '<span class="charlab-avatar-sym">' + sym + '</span>';
    html += '</div>';
    html += '<div class="charlab-id-text">';
    html += '<div class="charlab-name">' + name + '</div>';
    html += '<div class="charlab-active-title">' + title + '</div>';
    html += '<div class="charlab-tagline">' + tagline + '</div>';
    html += '</div>';
    html += '</div>';

    // ── Personality sliders ──
    html += '<div class="charlab-section">';
    html += '<div class="charlab-section-title">Personality</div>';
    html += '<div class="charlab-sliders">';
    _traitsMeta.forEach(function (t) {
      var key = 'personality_' + t.id;
      var personality = p.personality || {};
      var val = (personality[t.id] !== undefined) ? personality[t.id] : (p[key] || 5);
      html += renderSlider(t.id, t.icon + ' ' + t.label, t.desc, val, t.min || 1, t.max || 10, 1, 'personality');
    });
    html += '</div></div>';

    // ── Voice profile ──
    html += '<div class="charlab-section">';
    html += '<div class="charlab-section-title">Voice Profile</div>';
    html += '<div class="charlab-sliders">';
    _voiceMeta.forEach(function (v) {
      var key = 'voice_' + v.id;
      var voice = p.voice || {};
      var val = (voice[v.id] !== undefined) ? voice[v.id] : (p[key] || 1.0);
      var step = v.step || 0.05;
      html += renderSlider(v.id, v.label, v.desc, val, v.min || 0, v.max || 2.0, step, 'voice');
    });
    html += '</div></div>';

    // ── Color customization ──
    html += '<div class="charlab-section">';
    html += '<div class="charlab-section-title">Colors</div>';
    html += '<div class="charlab-color-row">';
    html += '<label class="charlab-color-label">Primary';
    html += '<input type="color" class="charlab-color-input" data-field="color_primary" value="' + _esc(color) + '">';
    html += '</label>';
    html += '<div class="charlab-color-preview" style="background:' + _esc(color) + ';box-shadow:0 0 12px ' + _esc(glow) + '"></div>';
    html += '</div></div>';

    // ── Titles ──
    var titles = (p.available_titles || []);
    if (titles.length > 0) {
      html += '<div class="charlab-section">';
      html += '<div class="charlab-section-title">Title</div>';
      html += '<div class="charlab-titles">';
      titles.forEach(function (t) {
        var isActive = (t.title === (p.title || p.active_title));
        html += '<button type="button" class="charlab-title-btn' + (isActive ? ' active' : '') + '"'
          + ' data-title="' + _esc(t.title) + '"'
          + ' title="' + _esc(t.condition) + '">'
          + _esc(t.title)
          + '</button>';
      });
      html += '</div></div>';
    }

    // ── Lore ──
    var loreOrigin = p.lore_origin || '';
    var lorePhilosophy = p.lore_philosophy || '';
    if (loreOrigin || lorePhilosophy) {
      html += '<div class="charlab-section">';
      html += '<div class="charlab-section-title">Lore</div>';
      html += '<div class="charlab-lore">';
      if (loreOrigin) {
        html += '<div class="charlab-lore-block"><strong>Origin:</strong> ' + _esc(loreOrigin) + '</div>';
      }
      if (lorePhilosophy) {
        html += '<div class="charlab-lore-block"><strong>Philosophy:</strong> ' + _esc(lorePhilosophy) + '</div>';
      }
      html += '</div></div>';
    }

    // ── Prompt hints preview ──
    html += '<div class="charlab-section">';
    html += '<div class="charlab-section-title">Active Prompt Hints</div>';
    html += '<div id="charlab-hints-preview" class="charlab-hints">Loading hints...</div>';
    html += '</div>';

    // ── Actions ──
    html += '<div class="charlab-actions">';
    html += '<button type="button" class="charlab-btn charlab-btn-save" id="charlab-save-btn" title="Save all changes">Save Changes</button>';
    html += '<button type="button" class="charlab-btn charlab-btn-main" id="charlab-setmain-btn" title="Set as your default aspect">Set as Main</button>';
    html += '<button type="button" class="charlab-btn charlab-btn-reset" id="charlab-reset-btn" title="Reset to factory defaults">Reset Defaults</button>';
    html += '</div>';

    html += '</div>'; // .charlab-detail

    // Load hints asynchronously
    setTimeout(function () { loadHintsPreview(aid); }, 100);

    return html;
  }

  // ── Slider renderer ────────────────────────────────────────────────────────

  function renderSlider(id, label, desc, value, min, max, step, group) {
    var pct = ((value - min) / (max - min)) * 100;
    var html = '<div class="charlab-slider-row">';
    html += '<div class="charlab-slider-label">' + _esc(label) + '</div>';
    html += '<div class="charlab-slider-wrap">';
    html += '<input type="range" class="charlab-slider" data-group="' + _esc(group) + '" data-id="' + _esc(id) + '"'
      + ' min="' + min + '" max="' + max + '" step="' + step + '" value="' + value + '"'
      + ' style="--slider-pct:' + pct + '%"'
      + ' aria-label="' + _esc(label) + '"'
      + ' title="' + _esc(desc) + '">';
    html += '<span class="charlab-slider-val" data-val-for="' + _esc(group) + '_' + _esc(id) + '">' + value + '</span>';
    html += '</div>';
    html += '</div>';
    return html;
  }

  // ── Bindings ───────────────────────────────────────────────────────────────

  function bindSliders(container) {
    container.querySelectorAll('.charlab-slider').forEach(function (sl) {
      sl.addEventListener('input', function () {
        var group = sl.getAttribute('data-group');
        var id = sl.getAttribute('data-id');
        var val = parseFloat(sl.value);
        var valSpan = container.querySelector('[data-val-for="' + group + '_' + id + '"]');
        if (valSpan) valSpan.textContent = (Number.isInteger(val) ? val : val.toFixed(2));

        // Track dirty
        var key = group + '_' + id;
        if (!_dirty[_selectedAspect]) _dirty[_selectedAspect] = {};
        _dirty[_selectedAspect][key] = val;

        // Update slider fill
        var min = parseFloat(sl.min);
        var max = parseFloat(sl.max);
        var pct = ((val - min) / (max - min)) * 100;
        sl.style.setProperty('--slider-pct', pct + '%');
      });
    });
  }

  function bindColorPickers(container) {
    container.querySelectorAll('.charlab-color-input').forEach(function (inp) {
      inp.addEventListener('input', function () {
        var field = inp.getAttribute('data-field');
        if (!_dirty[_selectedAspect]) _dirty[_selectedAspect] = {};
        _dirty[_selectedAspect][field] = inp.value;
      });
    });
  }

  function bindTitleSelect(container) {
    container.querySelectorAll('.charlab-title-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var title = btn.getAttribute('data-title');
        _api('/aspects/' + _selectedAspect + '/title', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: title }),
        }).then(function (r) {
          if (r.ok !== false) {
            _toast('Title set: ' + title);
            return loadCharacterData().then(renderCharacterLab);
          }
          _toast('Failed: ' + (r.error || 'unknown'));
        });
      });
    });
  }

  function bindActionButtons(container) {
    var saveBtn = container.querySelector('#charlab-save-btn');
    var mainBtn = container.querySelector('#charlab-setmain-btn');
    var resetBtn = container.querySelector('#charlab-reset-btn');

    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        saveCurrentAspect();
      });
    }

    if (mainBtn) {
      mainBtn.addEventListener('click', function () {
        _api('/main-aspect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ aspect_id: _selectedAspect }),
        }).then(function (r) {
          if (r.ok !== false) {
            _toast(_selectedAspect.charAt(0).toUpperCase() + _selectedAspect.slice(1) + ' set as main aspect');
            if (typeof window.setAspect === 'function') window.setAspect(_selectedAspect);
            try { localStorage.setItem('layla_default_aspect', _selectedAspect); } catch (_) {}
          } else {
            _toast('Failed: ' + (r.error || 'unknown'));
          }
        });
      });
    }

    if (resetBtn) {
      resetBtn.addEventListener('click', async function () {
        if (!(await laylaConfirm('Reset ' + _selectedAspect + ' to factory defaults? All customizations will be lost.'))) return;
        _api('/aspects/' + _selectedAspect + '/reset', { method: 'POST' }).then(function (r) {
          if (r.ok !== false) {
            _toast(_selectedAspect + ' reset to defaults');
            delete _dirty[_selectedAspect];
            return loadCharacterData().then(renderCharacterLab);
          }
          _toast('Reset failed: ' + (r.error || 'unknown'));
        });
      });
    }
  }

  // ── Save ───────────────────────────────────────────────────────────────────

  function saveCurrentAspect() {
    var changes = _dirty[_selectedAspect];
    if (!changes || Object.keys(changes).length === 0) {
      _toast('No changes to save');
      return;
    }

    _api('/aspects/' + _selectedAspect, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    }).then(function (r) {
      if (r.ok !== false) {
        _toast('Saved ' + (r.saved_keys || []).length + ' changes for ' + _selectedAspect);
        delete _dirty[_selectedAspect];
        return loadCharacterData().then(renderCharacterLab);
      }
      _toast('Save failed: ' + (r.error || 'unknown'));
    });
  }

  // ── Hints preview ──────────────────────────────────────────────────────────

  function loadHintsPreview(aid) {
    var el = document.getElementById('charlab-hints-preview');
    if (!el) return;
    _api('/aspects/' + aid + '/prompt-hints').then(function (r) {
      if (!el) return;
      var hints = (r && r.hints) || [];
      if (hints.length === 0) {
        el.innerHTML = '<span style="color:var(--text-dim);font-size:0.68rem">No special hints active (sliders near center)</span>';
        return;
      }
      el.innerHTML = hints.map(function (h) {
        return '<div class="charlab-hint-item">' + _esc(h) + '</div>';
      }).join('');
    });
  }

  // ── Character Lab panel toggle ─────────────────────────────────────────────

  function openCharacterLab() {
    var overlay = document.getElementById('character-lab-overlay');
    if (!overlay) return;
    _charLabOpen = true;
    overlay.classList.add('visible');
    overlay.setAttribute('aria-hidden', 'false');
    loadCharacterData().then(function () {
      renderCharacterLab();
    });
  }

  function closeCharacterLab() {
    var overlay = document.getElementById('character-lab-overlay');
    if (!overlay) return;
    _charLabOpen = false;
    overlay.classList.remove('visible');
    overlay.setAttribute('aria-hidden', 'true');
  }

  // ── Wizard integration (first-run character creation) ──────────────────────

  function renderWizardCharacterStep(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;

    return loadCharacterData().then(function () {
      var html = '<div class="charlab-wizard">';
      html += '<div class="charlab-wizard-title">Choose Your Primary Aspect</div>';
      html += '<div class="charlab-wizard-desc">Each aspect shapes how Layla thinks, speaks, and solves problems. '
        + 'Pick the one that fits your style — you can customize all six later in the Character Lab.</div>';

      html += '<div class="charlab-wizard-grid">';
      var aspectOrder = ['morrigan', 'nyx', 'echo', 'eris', 'cassandra', 'lilith'];
      aspectOrder.forEach(function (aid) {
        var p = _profiles[aid] || {};
        var color = p.color_primary || '#888';
        var sym = _esc(p.symbol || '?');
        var name = _esc(p.name || aid);
        var tagline = _esc(p.tagline || '');
        var isSelected = (aid === _selectedAspect);

        html += '<button type="button" class="charlab-wizard-card' + (isSelected ? ' selected' : '') + '"'
          + ' data-wiz-aspect="' + _esc(aid) + '"'
          + ' style="--card-color:' + _esc(color) + '">';
        html += '<div class="charlab-wizard-sym" style="color:' + _esc(color) + '">' + sym + '</div>';
        html += '<div class="charlab-wizard-name">' + name + '</div>';
        html += '<div class="charlab-wizard-tag">' + tagline + '</div>';

        // Mini personality radar
        var personality = p.personality || {};
        html += '<div class="charlab-wizard-stats">';
        _traitsMeta.forEach(function (t) {
          var val = personality[t.id] || 5;
          var pct = (val / 10) * 100;
          html += '<div class="charlab-mini-bar">';
          html += '<span class="charlab-mini-label">' + _esc(t.icon) + '</span>';
          html += '<div class="charlab-mini-track"><div class="charlab-mini-fill" style="width:' + pct + '%;background:' + _esc(color) + '"></div></div>';
          html += '</div>';
        });
        html += '</div>';

        html += '</button>';
      });
      html += '</div>'; // .charlab-wizard-grid
      html += '</div>'; // .charlab-wizard

      container.innerHTML = html;

      // Bind wizard card clicks
      container.querySelectorAll('.charlab-wizard-card').forEach(function (card) {
        card.addEventListener('click', function () {
          _selectedAspect = card.getAttribute('data-wiz-aspect') || 'morrigan';
          // Update selection visuals
          container.querySelectorAll('.charlab-wizard-card').forEach(function (c) {
            c.classList.toggle('selected', c.getAttribute('data-wiz-aspect') === _selectedAspect);
          });
          // Set aspect globally
          if (typeof window.setAspect === 'function') window.setAspect(_selectedAspect);
          try { localStorage.setItem('layla_default_aspect', _selectedAspect); } catch (_) {}
        });
      });
    });
  }

  // ── Tutorial intro sequence ────────────────────────────────────────────────

  var TUTORIAL_STEPS = [
    {
      id: 'welcome',
      title: 'Welcome to Layla',
      text: 'Layla is your sovereign AI companion. She runs entirely on your machine, learns your preferences, and grows alongside you.',
      highlight: null,
    },
    {
      id: 'aspects',
      title: 'Meet the Aspects',
      text: 'Layla has 6 personality facets — each one shapes how she thinks and communicates. You\'ve already chosen your primary. The others unlock as you use them.',
      highlight: '#aspect-bar',
    },
    {
      id: 'chat',
      title: 'Start Talking',
      text: 'Type anything in the chat box. Layla can write code, research topics, plan projects, and learn about you over time.',
      highlight: '#msg-input',
    },
    {
      id: 'memory',
      title: 'Memory System',
      text: 'Everything Layla learns is stored locally. Check the Memory tab to see what she remembers. You can edit or delete any learning.',
      highlight: '[data-rcp="workspace"]',
    },
    {
      id: 'character_lab',
      title: 'Character Lab',
      text: 'Customize each aspect\'s personality, voice, and appearance in the Character Lab. Open it any time from the header.',
      highlight: '#charlab-open-btn',
    },
    {
      id: 'complete',
      title: 'You\'re Ready',
      text: 'That\'s the basics. Layla will adapt to your style as you work together. Enjoy.',
      highlight: null,
    },
  ];

  var _tutStep = 0;

  function startTutorial() {
    _tutStep = 0;
    renderTutorialStep();
    var overlay = document.getElementById('tutorial-overlay');
    if (overlay) {
      overlay.classList.add('visible');
      overlay.setAttribute('aria-hidden', 'false');
    }
  }

  function renderTutorialStep() {
    var overlay = document.getElementById('tutorial-overlay');
    if (!overlay) return;

    var step = TUTORIAL_STEPS[_tutStep] || TUTORIAL_STEPS[0];
    var isLast = (_tutStep >= TUTORIAL_STEPS.length - 1);

    var html = '<div class="tutorial-dialog">';
    html += '<div class="tutorial-progress">';
    for (var i = 0; i < TUTORIAL_STEPS.length; i++) {
      html += '<span class="tutorial-dot' + (i === _tutStep ? ' active' : '') + (i < _tutStep ? ' done' : '') + '"></span>';
    }
    html += '</div>';
    html += '<div class="tutorial-title">' + _esc(step.title) + '</div>';
    html += '<div class="tutorial-text">' + _esc(step.text) + '</div>';
    html += '<div class="tutorial-actions">';
    if (_tutStep > 0) {
      html += '<button type="button" class="tutorial-btn tutorial-btn-back" id="tut-back">Back</button>';
    }
    html += '<button type="button" class="tutorial-btn tutorial-btn-next" id="tut-next">' + (isLast ? 'Finish' : 'Next') + '</button>';
    html += '<button type="button" class="tutorial-btn tutorial-btn-skip" id="tut-skip">Skip Tutorial</button>';
    html += '</div>';
    html += '</div>';

    overlay.innerHTML = html;

    // Highlight target element
    if (step.highlight) {
      var target = document.querySelector(step.highlight);
      if (target) {
        target.classList.add('tutorial-highlight');
        // Remove highlights from all others
        document.querySelectorAll('.tutorial-highlight').forEach(function (el) {
          if (el !== target) el.classList.remove('tutorial-highlight');
        });
      }
    } else {
      document.querySelectorAll('.tutorial-highlight').forEach(function (el) {
        el.classList.remove('tutorial-highlight');
      });
    }

    // Bind buttons
    var nextBtn = document.getElementById('tut-next');
    var backBtn = document.getElementById('tut-back');
    var skipBtn = document.getElementById('tut-skip');

    if (nextBtn) {
      nextBtn.addEventListener('click', function () {
        if (isLast) {
          completeTutorial();
        } else {
          _tutStep++;
          _api('/tutorial/advance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ step: _tutStep }),
          });
          renderTutorialStep();
        }
      });
    }
    if (backBtn) {
      backBtn.addEventListener('click', function () {
        if (_tutStep > 0) {
          _tutStep--;
          renderTutorialStep();
        }
      });
    }
    if (skipBtn) {
      skipBtn.addEventListener('click', function () {
        completeTutorial();
      });
    }
  }

  function completeTutorial() {
    document.querySelectorAll('.tutorial-highlight').forEach(function (el) {
      el.classList.remove('tutorial-highlight');
    });
    var overlay = document.getElementById('tutorial-overlay');
    if (overlay) {
      overlay.classList.remove('visible');
      overlay.setAttribute('aria-hidden', 'true');
    }
    _api('/tutorial/advance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step: 99 }),
    });
    _toast('Tutorial complete!');
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  function init() {
    // Try to load default aspect from localStorage
    try {
      var stored = localStorage.getItem('layla_default_aspect');
      if (stored) _selectedAspect = stored;
    } catch (_) {}

    // Check if tutorial should auto-start
    loadCharacterData().then(function () {
      if (_tutorialState && !_tutorialState.tutorial_complete && _tutorialState.wizard_complete) {
        // Auto-start tutorial after wizard
        setTimeout(function () { startTutorial(); }, 1500);
      }
    }).catch(function () {});
  }

  // ── Exports ────────────────────────────────────────────────────────────────

  window.openCharacterLab = openCharacterLab;
  window.closeCharacterLab = closeCharacterLab;
  window.renderWizardCharacterStep = renderWizardCharacterStep;
  window.startTutorial = startTutorial;
  window.loadCharacterData = loadCharacterData;

  // Auto-init when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
